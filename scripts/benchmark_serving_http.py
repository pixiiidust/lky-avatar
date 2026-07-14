"""Serving benchmark over HTTP — the GGUF/llama-server counterpart of
``benchmark_brain.py`` (issue #3's yardstick, re-measured through the
OpenAI-compatible seam).

Where ``benchmark_brain.py`` measures the in-process Transformers engine,
this script measures ANY OpenAI-compatible server (llama-server, brain_api,
vLLM...) as an HTTP client — the exact vantage point the voice agent has.
It reuses the same prompt set (``evals/benchmark_prompts.json``), the same
persona system prompt, the same per-prompt seeds, and the same aggregate
schema (imported from ``benchmark_brain``) so the JSONs diff cleanly against
``evals/results/benchmark_baseline_<sha>.json``.

Measured per prompt, from SSE chunk arrival times (stdlib urllib only):
  * TTFT — first non-empty content delta
  * decode tok/s — (completion_tokens - 1) / (t_end - t_first), prefill excluded
  * overall tok/s, generation seconds
Token counts come from the server's ``usage`` block
(``stream_options: {"include_usage": true}``).

VRAM is sampled via ``nvidia-smi`` (total GPU memory.used — includes any
other GPU processes, so run this with the GPU otherwise idle).

Sampling: temperature/top_p from ``lky_avatar.persona`` are sent explicitly;
repetition_penalty and thinking suppression are the SERVER's responsibility
(llama-server: ``--repeat-penalty 1.1 --chat-template-kwargs
'{"enable_thinking":false}'`` — see docs/reports/serving-upgrade.md).

Usage (server already running):
    python scripts/benchmark_serving_http.py --base-url http://127.0.0.1:8001 \
        --git-sha <sha> --engine-label llamacpp-q4km \
        --load-seconds <measured at launch>
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import subprocess
import sys
import time
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from benchmark_brain import (  # noqa: E402  (stdlib-only module imports)
    SEED_BASE, ANSWER_PREVIEW_CHARS, PROMPTS_PATH, RESULTS_DIR,
    PRESENT_DATE_DEFAULT, aggregate, print_summary, resolve_git_sha,
    timing_row,
)
from lky_avatar import persona  # noqa: E402

SCHEMA_VERSION = 1


def gpu_memory_used_gib() -> float | None:
    """Total GPU memory.used per nvidia-smi (GiB); None if unavailable."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            return round(int(out.stdout.strip().splitlines()[0]) / 1024, 2)
    except (OSError, ValueError, IndexError):
        pass
    return None


def stream_completion(base_url: str, payload: dict, timeout: float) -> dict:
    """POST a streaming chat completion; return timestamps, text, usage."""
    request = urllib.request.Request(
        base_url + "/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    t_first = None
    parts: list[str] = []
    usage = None
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            data = line[len("data: "):]
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            if "error" in chunk:
                raise RuntimeError(f"server error mid-stream: {chunk['error']}")
            if chunk.get("usage"):
                usage = chunk["usage"]
            choices = chunk.get("choices") or []
            if not choices:
                continue
            piece = choices[0].get("delta", {}).get("content")
            if piece:
                if t_first is None:
                    t_first = time.perf_counter()
                parts.append(piece)
    t_end = time.perf_counter()
    return {"t0": t0, "t_first": t_first, "t_end": t_end,
            "text": "".join(parts), "usage": usage or {}}


def run_prompt(base_url: str, model: str, system: str, question: str,
               max_tokens: int, seed: int, timeout: float) -> dict:
    payload = {
        "model": model,
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": max_tokens,
        "temperature": persona.TEMPERATURE,
        "top_p": persona.TOP_P,
        "seed": seed,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ],
    }
    stream = stream_completion(base_url, payload, timeout)
    usage = stream["usage"]
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    row = timing_row(stream, prompt_tokens, completion_tokens)
    row["answer_preview"] = stream["text"].strip()[:ANSWER_PREVIEW_CHARS]
    return row


def main() -> None:
    ap = argparse.ArgumentParser(
        description="HTTP serving benchmark (OpenAI-compatible seam)")
    ap.add_argument("--base-url", default="http://127.0.0.1:8001")
    ap.add_argument("--model", default="lky")
    ap.add_argument("--engine-label", default="llamacpp-gguf-q4km",
                    help="engine tag recorded in metadata and the filename")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--date", default=PRESENT_DATE_DEFAULT)
    ap.add_argument("--git-sha", default="")
    ap.add_argument("--load-seconds", type=float, default=None,
                    help="server model-load seconds, measured at launch "
                         "(HTTP client cannot observe it)")
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    data = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
    prompts = data["prompts"]
    if args.limit:
        prompts = prompts[:args.limit]

    system = persona.system_prompt(args.date)
    git_sha = resolve_git_sha(args.git_sha)
    base_url = args.base_url.rstrip("/")
    vram_before = gpu_memory_used_gib()

    print(f"benchmark_serving_http: {base_url} engine={args.engine_label} "
          f"prompts={len(prompts)} git_sha={git_sha}")
    print(f"system prompt: {system!r}")
    print(f"GPU memory.used before run: {vram_before} GiB")

    # Warmup (excluded from aggregates), same as benchmark_brain.
    print("warmup generation (excluded from aggregates)...", flush=True)
    warmup = {"id": "warmup", "category": "warmup", "max_new_tokens": 16,
              "status": "ok"}
    try:
        warmup.update(run_prompt(base_url, args.model, system,
                                 "Who are you?", 16, SEED_BASE, args.timeout))
    except Exception as exc:  # noqa: BLE001
        warmup.update({"status": "error",
                       "error": f"{type(exc).__name__}: {exc}"})
    print(f"warmup: {warmup.get('generation_seconds', '-')}s "
          f"(status {warmup['status']})", flush=True)

    rows = []
    vram_samples = [v for v in [vram_before] if v is not None]
    for i, p in enumerate(prompts):
        seed = SEED_BASE + int(p["id"][1:])  # stable per prompt id
        row = {"id": p["id"], "category": p["category"],
               "source": p["source"], "max_new_tokens": p["max_new_tokens"],
               "question": p["question"], "status": "ok"}
        print(f"[{i + 1}/{len(prompts)}] {p['id']} ({p['category']}, "
              f"max_new_tokens={p['max_new_tokens']})...", flush=True)
        try:
            row.update(run_prompt(base_url, args.model, system,
                                  p["question"], p["max_new_tokens"], seed,
                                  args.timeout))
            print(f"    {row['completion_tokens']} tok, TTFT "
                  f"{row['ttft_seconds']}s, decode "
                  f"{row['decode_tokens_per_second']} tok/s, total "
                  f"{row['generation_seconds']}s", flush=True)
        except Exception as exc:  # noqa: BLE001 — count it, keep going
            row["status"] = "error"
            row["error"] = f"{type(exc).__name__}: {exc}"
            print(f"    FAILED: {row['error']}", flush=True)
        rows.append(row)
        sample = gpu_memory_used_gib()
        if sample is not None:
            vram_samples.append(sample)

    agg = aggregate(rows)
    mem = {
        "vram_after_load": {"allocated_gib": vram_before,
                            "reserved_gib": None},
        "peak_vram_allocated_gib": max(vram_samples) if vram_samples else None,
        "peak_vram_reserved_gib": None,
        "note": "nvidia-smi total memory.used (whole GPU), sampled "
                "before the run and after every prompt",
    }
    out = {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "benchmark": "serving-http (OpenAI-compatible seam)",
            "run_at": datetime.datetime.now(datetime.timezone.utc)
                      .isoformat(timespec="seconds"),
            "git_sha": git_sha,
            "base_url": base_url,
            "engine_label": args.engine_label,
            "limit": args.limit or None,
            "sampling": {
                **persona.sampling_defaults(),
                "note": "temperature/top_p sent per request; "
                        "repetition_penalty + enable_thinking=false are "
                        "server-side defaults (see launch command in "
                        "docs/reports/serving-upgrade.md)",
            },
            "system_prompt": system,
            "present_date": args.date,
            "prompt_set": {
                "path": str(PROMPTS_PATH.relative_to(REPO_ROOT)).replace(
                    "\\", "/"),
                "version": data["version"],
                "count": len(prompts),
            },
        },
        "load": {
            "model_load_seconds": args.load_seconds,
            "allocated_gib": vram_before,
        },
        "warmup": warmup,
        "aggregates": agg,
        "vram": mem,
        "results": rows,
    }

    if args.output:
        path = pathlib.Path(args.output)
    else:
        suffix = "_smoke" if args.limit else ""
        path = (RESULTS_DIR /
                f"benchmark_{args.engine_label}_{git_sha}{suffix}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")

    load_s = args.load_seconds if args.load_seconds is not None else float("nan")
    print_summary(rows, agg, mem, load_s)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
