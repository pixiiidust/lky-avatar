"""Baseline brain benchmark (issue #3) — the serving yardstick.

Measures, for local Qwen3-14B + epoch-2 LoRA in 4-bit NF4 (plain Transformers
+ PEFT, the exact serving path the product uses — NO Unsloth at inference):

  * cold-process model+adapter load time
  * time-to-first-token (TTFT) per prompt, timestamped from the FIRST chunk a
    ``TextIteratorStreamer`` actually yields — not inferred from totals
  * decode tokens/sec (excluding prefill) and overall tokens/sec per prompt
  * steady VRAM after load and peak VRAM over the whole run
  * failure rate (any prompt whose generation raises)

over the standing 24-prompt set in ``evals/benchmark_prompts.json`` (short
factual / long reflective / modern+adversarial, in max_new_tokens 80 and 320
regimes; modern prompts are shared verbatim with issue #2's time-travel eval).

Sampling is the locked default from ``lky_avatar.persona``
(enable_thinking=False, temperature 0.7, top_p 0.9, repetition_penalty 1.1);
the system prompt is ``persona.system_prompt(--date)``.

Output: ONE JSON at ``evals/results/benchmark_baseline_<git-short-sha>.json``
with per-prompt rows, aggregate percentiles (p50/p95 TTFT and tok/s, overall
and per regime), and a full environment block (GPU, library versions, quant
config, git SHA) so future runs — new serving stacks, quantizations, or
drivers — diff cleanly against this baseline. A human-readable summary table
is printed at the end.

Known baseline context (orchestrator probe 2026-07-13, RTX 5070 Ti, torch
2.12.1+cu130): model+adapter load ~34.7 s warm-cache, ~10.9 GiB VRAM after
load, decode ~2.3-3.15 tok/s — an inherent bitsandbytes-NF4 decode cost with
use_cache on and healthy peak alloc (~10.5 GiB). This benchmark's job is to
make that baseline rigorous and comparable, not to fix it.

Run under WSL in the uns venv (CUDA required):
    wsl -d Ubuntu-24.04 -- bash -c \
      '~/uns/bin/python /mnt/c/.../scripts/benchmark_brain.py --git-sha <sha>'

Options:
    --dry-run             run the whole pipeline on a CPU-only fake engine
                          (no torch/CUDA imports) to validate plumbing and the
                          JSON schema; output gets a ``_dryrun`` suffix
    --limit N             only the first N prompts (smoke); ``_smoke`` suffix
    --date YYYY-MM-DD     persona system-prompt date (default 2026-07-13)
    --git-sha SHA         short git SHA for the output filename/metadata
                          (pass explicitly when git can't resolve the worktree,
                          e.g. WSL running a Windows-side git worktree)
    --output PATH         override the output JSON path entirely
"""
import argparse
import datetime
import json
import math
import pathlib
import platform
import subprocess
import sys
import threading
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lky_avatar import persona  # noqa: E402

SCHEMA_VERSION = 1
BASE_ID = "Qwen/Qwen3-14B"
PROMPTS_PATH = REPO_ROOT / "evals" / "benchmark_prompts.json"
RESULTS_DIR = REPO_ROOT / "evals" / "results"
PRESENT_DATE_DEFAULT = "2026-07-13"
SEED_BASE = 20260713
ANSWER_PREVIEW_CHARS = 240

QUANTIZATION = {
    "method": "bitsandbytes",
    "load_in_4bit": True,
    "bnb_4bit_quant_type": "nf4",
    "bnb_4bit_compute_dtype": "bfloat16",
}


# --------------------------------------------------------------------------
# timing helper (shared by real and fake engines)
# --------------------------------------------------------------------------

def consume_stream(chunks) -> dict:
    """Consume an iterator of text chunks, timestamping the first non-empty
    one. Returns wall-clock t0/t_first/t_end and the joined text."""
    t0 = time.perf_counter()
    t_first = None
    parts = []
    for chunk in chunks:
        if chunk and t_first is None:
            t_first = time.perf_counter()
        parts.append(chunk)
    t_end = time.perf_counter()
    return {"t0": t0, "t_first": t_first, "t_end": t_end,
            "text": "".join(parts)}


def timing_row(stream: dict, prompt_tokens: int, completion_tokens: int) -> dict:
    """Turn raw stream timestamps + token counts into the per-prompt metrics."""
    t0, t_first, t_end = stream["t0"], stream["t_first"], stream["t_end"]
    ttft = (t_first - t0) if t_first is not None else None
    gen_s = t_end - t0
    decode_s = (t_end - t_first) if t_first is not None else None
    # Decode rate: tokens after the first, over the time after the first
    # token appeared (i.e. pure decode, prefill excluded).
    decode_tok_s = None
    if decode_s and decode_s > 0 and completion_tokens > 1:
        decode_tok_s = (completion_tokens - 1) / decode_s
    overall_tok_s = completion_tokens / gen_s if gen_s > 0 else None
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "ttft_seconds": round(ttft, 3) if ttft is not None else None,
        "decode_tokens_per_second":
            round(decode_tok_s, 3) if decode_tok_s is not None else None,
        "overall_tokens_per_second":
            round(overall_tok_s, 3) if overall_tok_s is not None else None,
        "generation_seconds": round(gen_s, 3),
    }


# --------------------------------------------------------------------------
# real engine (CUDA; imports torch/transformers lazily so --dry-run works on
# a machine without them)
# --------------------------------------------------------------------------

class RealEngine:
    name = "cuda"

    def __init__(self):
        self.torch = None
        self.tokenizer = None
        self.model = None
        self.load_seconds = None
        self.vram_after_load = None

    def load(self) -> None:
        import torch
        from peft import PeftModel
        from transformers import (AutoModelForCausalLM, AutoTokenizer,
                                  BitsAndBytesConfig)
        self.torch = torch
        print(f"loading tokenizer: {BASE_ID}", flush=True)
        t0 = time.perf_counter()
        self.tokenizer = AutoTokenizer.from_pretrained(BASE_ID)
        bnb = BitsAndBytesConfig(
            load_in_4bit=QUANTIZATION["load_in_4bit"],
            bnb_4bit_quant_type=QUANTIZATION["bnb_4bit_quant_type"],
            bnb_4bit_compute_dtype=torch.bfloat16)
        print("loading base (4-bit NF4)...", flush=True)
        model = AutoModelForCausalLM.from_pretrained(
            BASE_ID, quantization_config=bnb, dtype=torch.bfloat16,
            device_map={"": 0})
        adapter = persona.ADAPTER_LOCAL_PATH_WSL
        print(f"loading epoch-2 adapter: {adapter}", flush=True)
        model = PeftModel.from_pretrained(model, adapter)
        model.eval()
        self.model = model
        self.load_seconds = time.perf_counter() - t0
        self.vram_after_load = {
            "allocated_gib": round(torch.cuda.memory_allocated() / 2**30, 2),
            "reserved_gib": round(torch.cuda.memory_reserved() / 2**30, 2),
        }
        print(f"model+adapter loaded in {self.load_seconds:.1f}s; VRAM "
              f"allocated {self.vram_after_load['allocated_gib']:.2f} GiB",
              flush=True)

    def generate(self, system: str, question: str, max_new_tokens: int,
                 seed: int) -> dict:
        from transformers import TextIteratorStreamer
        torch = self.torch
        sampling = persona.sampling_defaults()
        prompt = self.tokenizer.apply_chat_template(
            [{"role": "system", "content": system},
             {"role": "user", "content": question}],
            tokenize=False, add_generation_prompt=True,
            enable_thinking=sampling.pop("enable_thinking"))
        ids = self.tokenizer(prompt, return_tensors="pt").to("cuda")
        prompt_tokens = int(ids["input_ids"].shape[1])
        torch.manual_seed(seed)  # reproducible-ish per prompt

        streamer = TextIteratorStreamer(
            self.tokenizer, skip_prompt=True, skip_special_tokens=True)
        holder = {"output": None, "error": None}

        def _worker():
            try:
                with torch.no_grad():
                    holder["output"] = self.model.generate(
                        **ids, streamer=streamer,
                        max_new_tokens=max_new_tokens, do_sample=True,
                        **sampling,
                        pad_token_id=self.tokenizer.eos_token_id)
            except Exception as exc:  # noqa: BLE001 — recorded as a failure
                holder["error"] = exc
                streamer.end()  # unblock the consuming iterator

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        stream = consume_stream(streamer)
        thread.join()
        if holder["error"] is not None:
            raise holder["error"]
        completion_tokens = int(
            holder["output"][0].shape[0] - prompt_tokens)
        row = timing_row(stream, prompt_tokens, completion_tokens)
        row["answer_preview"] = stream["text"].strip()[:ANSWER_PREVIEW_CHARS]
        return row

    def memory_stats(self) -> dict:
        torch = self.torch
        return {
            "vram_after_load": self.vram_after_load,
            "peak_vram_allocated_gib":
                round(torch.cuda.max_memory_allocated() / 2**30, 2),
            "peak_vram_reserved_gib":
                round(torch.cuda.max_memory_reserved() / 2**30, 2),
        }

    def environment(self) -> dict:
        import importlib.metadata as md
        torch = self.torch
        props = torch.cuda.get_device_properties(0)
        return {
            "engine": self.name,
            "gpu_name": torch.cuda.get_device_name(0),
            "gpu_total_vram_gib": round(props.total_memory / 2**30, 2),
            "cuda": torch.version.cuda,
            "torch": torch.__version__,
            "transformers": md.version("transformers"),
            "peft": md.version("peft"),
            "bitsandbytes": md.version("bitsandbytes"),
            "python": platform.python_version(),
            "platform": platform.platform(),
        }


# --------------------------------------------------------------------------
# dry-run engine (pure stdlib; validates plumbing + JSON schema without CUDA)
# --------------------------------------------------------------------------

class FakeEngine:
    name = "dry-run-stub"

    def __init__(self):
        self.load_seconds = None
        self.vram_after_load = {"allocated_gib": 0.0, "reserved_gib": 0.0}

    def load(self) -> None:
        t0 = time.perf_counter()
        time.sleep(0.02)  # stand-in for model load
        self.load_seconds = time.perf_counter() - t0
        print(f"[dry-run] fake model loaded in {self.load_seconds:.3f}s",
              flush=True)

    def generate(self, system: str, question: str, max_new_tokens: int,
                 seed: int) -> dict:
        completion_tokens = min(max_new_tokens, 24)

        def _chunks():
            time.sleep(0.005)  # stand-in for prefill (TTFT)
            for i in range(completion_tokens):
                time.sleep(0.0005)
                yield f"tok{i} "

        stream = consume_stream(_chunks())
        prompt_tokens = max(1, (len(system) + len(question)) // 4)
        row = timing_row(stream, prompt_tokens, completion_tokens)
        row["answer_preview"] = stream["text"].strip()[:ANSWER_PREVIEW_CHARS]
        return row

    def memory_stats(self) -> dict:
        return {
            "vram_after_load": self.vram_after_load,
            "peak_vram_allocated_gib": 0.0,
            "peak_vram_reserved_gib": 0.0,
        }

    def environment(self) -> dict:
        return {
            "engine": self.name,
            "gpu_name": None,
            "gpu_total_vram_gib": None,
            "cuda": None,
            "torch": None,
            "transformers": None,
            "peft": None,
            "bitsandbytes": None,
            "python": platform.python_version(),
            "platform": platform.platform(),
        }


# --------------------------------------------------------------------------
# aggregation
# --------------------------------------------------------------------------

def percentile(values: list, p: float):
    """Linear-interpolated percentile (numpy default), stdlib only."""
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * p / 100.0
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return round(xs[int(k)], 3)
    return round(xs[f] + (xs[c] - xs[f]) * (k - f), 3)


def metric_summary(values: list) -> dict:
    xs = [v for v in values if v is not None]
    if not xs:
        return {"p50": None, "p95": None, "mean": None,
                "min": None, "max": None, "n": 0}
    return {
        "p50": percentile(xs, 50),
        "p95": percentile(xs, 95),
        "mean": round(sum(xs) / len(xs), 3),
        "min": round(min(xs), 3),
        "max": round(max(xs), 3),
        "n": len(xs),
    }


def aggregate(rows: list) -> dict:
    ok = [r for r in rows if r["status"] == "ok"]

    def block(subset: list) -> dict:
        return {
            "ttft_seconds": metric_summary(
                [r["ttft_seconds"] for r in subset]),
            "decode_tokens_per_second": metric_summary(
                [r["decode_tokens_per_second"] for r in subset]),
            "overall_tokens_per_second": metric_summary(
                [r["overall_tokens_per_second"] for r in subset]),
            "generation_seconds": metric_summary(
                [r["generation_seconds"] for r in subset]),
        }

    by_regime = {}
    for regime in sorted({r["max_new_tokens"] for r in ok}):
        by_regime[str(regime)] = block(
            [r for r in ok if r["max_new_tokens"] == regime])
    return {
        "num_prompts": len(rows),
        "num_ok": len(ok),
        "num_failures": len(rows) - len(ok),
        "failure_rate": round((len(rows) - len(ok)) / len(rows), 4)
                        if rows else None,
        "all": block(ok),
        "by_regime": by_regime,
    }


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------

def resolve_git_sha(cli_value: str) -> str:
    if cli_value:
        return cli_value
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            return out.stdout.strip()
    except OSError:
        pass
    return "nogit"


def print_summary(rows: list, agg: dict, mem: dict, load_s: float) -> None:
    print("\n=== per-prompt results ===")
    header = (f"{'id':<5} {'category':<30} {'max':>4} {'stat':<5} "
              f"{'ptok':>5} {'ctok':>5} {'ttft_s':>7} {'dec t/s':>8} "
              f"{'gen_s':>7}")
    print(header)
    print("-" * len(header))
    for r in rows:
        def fmt(v, spec):
            return format(v, spec) if v is not None else "-"
        print(f"{r['id']:<5} {r['category']:<30} {r['max_new_tokens']:>4} "
              f"{r['status']:<5} {fmt(r.get('prompt_tokens'), '>5')} "
              f"{fmt(r.get('completion_tokens'), '>5')} "
              f"{fmt(r.get('ttft_seconds'), '>7.3f')} "
              f"{fmt(r.get('decode_tokens_per_second'), '>8.3f')} "
              f"{fmt(r.get('generation_seconds'), '>7.2f')}")
    print("\n=== aggregates ===")
    print(f"model+adapter load: {load_s:.1f}s")
    a = agg["all"]
    print(f"prompts: {agg['num_ok']}/{agg['num_prompts']} ok "
          f"(failure rate {agg['failure_rate']})")
    print(f"TTFT s        p50 {a['ttft_seconds']['p50']}  "
          f"p95 {a['ttft_seconds']['p95']}")
    print(f"decode tok/s  p50 {a['decode_tokens_per_second']['p50']}  "
          f"p95 {a['decode_tokens_per_second']['p95']}")
    print(f"overall tok/s p50 {a['overall_tokens_per_second']['p50']}  "
          f"p95 {a['overall_tokens_per_second']['p95']}")
    for regime, b in agg["by_regime"].items():
        print(f"  [max_new_tokens={regime}] TTFT p50 "
              f"{b['ttft_seconds']['p50']}s, decode p50 "
              f"{b['decode_tokens_per_second']['p50']} tok/s, gen p50 "
              f"{b['generation_seconds']['p50']}s")
    print(f"VRAM after load: {mem['vram_after_load']['allocated_gib']} GiB "
          f"allocated; peak {mem['peak_vram_allocated_gib']} GiB allocated / "
          f"{mem['peak_vram_reserved_gib']} GiB reserved")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Baseline brain benchmark (issue #3)")
    ap.add_argument("--dry-run", action="store_true",
                    help="fake engine, no CUDA — validates plumbing/schema")
    ap.add_argument("--limit", type=int, default=0,
                    help="run only the first N prompts (smoke test)")
    ap.add_argument("--date", default=PRESENT_DATE_DEFAULT,
                    help="persona system-prompt date (YYYY-MM-DD)")
    ap.add_argument("--git-sha", default="",
                    help="short git SHA (auto-detected when omitted)")
    ap.add_argument("--output", default="",
                    help="override output JSON path")
    args = ap.parse_args()

    data = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
    prompts = data["prompts"]
    if args.limit:
        prompts = prompts[:args.limit]

    system = persona.system_prompt(args.date)
    git_sha = resolve_git_sha(args.git_sha)
    engine = FakeEngine() if args.dry_run else RealEngine()

    print(f"benchmark_brain: engine={engine.name} prompts={len(prompts)} "
          f"git_sha={git_sha}")
    print(f"system prompt: {system!r}")
    engine.load()

    # Warmup (excluded from aggregates): the first CUDA generation pays
    # one-off kernel/cache costs that would otherwise pollute TTFT p95.
    print("warmup generation (excluded from aggregates)...", flush=True)
    warmup = {"id": "warmup", "category": "warmup", "max_new_tokens": 16,
              "status": "ok"}
    try:
        warmup.update(engine.generate(system, "Who are you?", 16, SEED_BASE))
    except Exception as exc:  # noqa: BLE001
        warmup.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
    print(f"warmup: {warmup.get('generation_seconds', '-')}s "
          f"(status {warmup['status']})", flush=True)

    rows = []
    for i, p in enumerate(prompts):
        seed = SEED_BASE + int(p["id"][1:])  # stable per prompt id
        row = {"id": p["id"], "category": p["category"],
               "source": p["source"], "max_new_tokens": p["max_new_tokens"],
               "question": p["question"], "status": "ok"}
        print(f"[{i + 1}/{len(prompts)}] {p['id']} ({p['category']}, "
              f"max_new_tokens={p['max_new_tokens']})...", flush=True)
        try:
            row.update(engine.generate(system, p["question"],
                                       p["max_new_tokens"], seed))
            print(f"    {row['completion_tokens']} tok, TTFT "
                  f"{row['ttft_seconds']}s, decode "
                  f"{row['decode_tokens_per_second']} tok/s, total "
                  f"{row['generation_seconds']}s", flush=True)
        except Exception as exc:  # noqa: BLE001 — count it, keep going
            row["status"] = "error"
            row["error"] = f"{type(exc).__name__}: {exc}"
            print(f"    FAILED: {row['error']}", flush=True)
        rows.append(row)

    agg = aggregate(rows)
    mem = engine.memory_stats()
    out = {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "benchmark": "baseline-brain (issue #3)",
            "run_at": datetime.datetime.now(datetime.timezone.utc)
                      .isoformat(timespec="seconds"),
            "git_sha": git_sha,
            "dry_run": args.dry_run,
            "limit": args.limit or None,
            "base_model": BASE_ID,
            "adapter": persona.ADAPTER_LOCAL_PATH_WSL,
            "adapter_hf_id": persona.ADAPTER_HF_ID,
            "quantization": QUANTIZATION,
            "sampling": persona.sampling_defaults(),
            "system_prompt": system,
            "present_date": args.date,
            "prompt_set": {
                "path": str(PROMPTS_PATH.relative_to(REPO_ROOT)).replace(
                    "\\", "/"),
                "version": data["version"],
                "count": len(prompts),
            },
            "environment": engine.environment(),
            "baseline_context": (
                "orchestrator probe 2026-07-13: load ~34.7s warm cache, "
                "~10.9 GiB VRAM after load, decode ~2.3-3.15 tok/s "
                "(inherent bnb NF4 decode cost; use_cache on)"),
        },
        "load": {
            "model_load_seconds": round(engine.load_seconds, 1),
            **mem["vram_after_load"],
        },
        "warmup": warmup,
        "aggregates": agg,
        "vram": mem,
        "results": rows,
    }

    if args.output:
        path = pathlib.Path(args.output)
    else:
        suffix = ("_dryrun" if args.dry_run else "") + \
                 ("_smoke" if args.limit else "")
        path = RESULTS_DIR / f"benchmark_baseline_{git_sha}{suffix}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")

    print_summary(rows, agg, mem, engine.load_seconds)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
