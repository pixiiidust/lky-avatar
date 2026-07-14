"""Time-travel persona eval runner (issue #2 concept gate).

Loads Qwen3-14B + the epoch-2 LoRA in 4-bit NF4 via plain Transformers + PEFT
(same proven loading path as lky-brain's train/chat.py — NO Unsloth at
inference), applies the locked sampling defaults from ``lky_avatar.persona``
with ``enable_thinking=False`` in the chat template, and answers the standing
modern-question set (``evals/timetravel_questions.json``) under:

  A        persona.system_prompt("2026-07-13") exactly as vendored
  B        variant A + an explicit awareness + anti-fabrication sentence
  control  persona.system_prompt("2011-01-01") on the 5 control questions
           (in-distribution comparison point / the plan's fallback date)

Results (answers + generation stats + judgment placeholders) are written to
``evals/results/timetravel_<variant>.json``. Judgments are filled in by a
human/orchestrator pass afterwards; this script never grades.

Run under WSL in the uns venv (CUDA required):
    wsl -d Ubuntu-24.04 -- bash -c \
      '~/uns/bin/python /mnt/c/.../scripts/run_timetravel_eval.py --variant all'

Options:
    --variant {A,B,control,all}   which prompt variant(s) to run (default all)
    --limit N                     only the first N questions (smoke test)
    --max-new-tokens N            default 400
    --date YYYY-MM-DD             present-day date for variants A/B
                                  (default 2026-07-13)
"""
import argparse
import datetime
import json
import pathlib
import sys
import time

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lky_avatar import persona  # noqa: E402

BASE_ID = "Qwen/Qwen3-14B"
QUESTIONS_PATH = REPO_ROOT / "evals" / "timetravel_questions.json"
RESULTS_DIR = REPO_ROOT / "evals" / "results"

PRESENT_DATE_DEFAULT = "2026-07-13"
CONTROL_DATE = "2011-01-01"

# Variant B's addition, verbatim from the issue-#2 task definition (mirrors
# the plan §4 persona frame). Appended to the vendored system_prompt().
VARIANT_B_SUFFIX = (
    " You are aware of world developments up to the present day. Reason from"
    " your principles and experience; do not fabricate specific quotes,"
    " meetings, or personal memories."
)


def build_system_prompt(variant: str, present_date: str,
                        with_style_policy: bool = False) -> str:
    if variant == "A":
        prompt = persona.system_prompt(present_date)
    elif variant == "B":
        prompt = persona.system_prompt(present_date) + VARIANT_B_SUFFIX
    elif variant == "C":
        # Prompt v2 lives with the voice agent — single source of truth.
        sys.path.insert(0, str(REPO_ROOT / "services" / "voice_agent"))
        from persona_prompt import PRESENT_DAY_AWARENESS_V2
        prompt = persona.system_prompt(present_date) + PRESENT_DAY_AWARENESS_V2
    elif variant == "control":
        prompt = persona.system_prompt(CONTROL_DATE)
    else:
        raise ValueError(f"unknown variant: {variant}")
    if with_style_policy:
        sys.path.insert(0, str(REPO_ROOT / "services" / "voice_agent"))
        from persona_prompt import SPOKEN_STYLE_POLICY
        prompt = prompt + "\n\n" + SPOKEN_STYLE_POLICY
    return prompt


def load_model():
    print(f"loading tokenizer: {BASE_ID}")
    tokenizer = AutoTokenizer.from_pretrained(BASE_ID)
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.bfloat16)
    print("loading base (4-bit NF4, takes a few minutes)...")
    t0 = time.perf_counter()
    model = AutoModelForCausalLM.from_pretrained(
        BASE_ID, quantization_config=bnb, dtype=torch.bfloat16,
        device_map={"": 0})
    adapter = persona.ADAPTER_LOCAL_PATH_WSL
    print(f"loading epoch-2 adapter: {adapter}")
    model = PeftModel.from_pretrained(model, adapter)
    model.eval()
    load_s = time.perf_counter() - t0
    print(f"model+adapter loaded in {load_s:.1f}s; "
          f"VRAM allocated {torch.cuda.memory_allocated() / 2**30:.2f} GiB")
    return tokenizer, model, load_s


def generate_answer(tokenizer, model, system: str, question: str,
                    max_new_tokens: int, seed: int) -> dict:
    sampling = persona.sampling_defaults()
    prompt = tokenizer.apply_chat_template(
        [{"role": "system", "content": system},
         {"role": "user", "content": question}],
        tokenize=False, add_generation_prompt=True,
        enable_thinking=sampling.pop("enable_thinking"))
    ids = tokenizer(prompt, return_tensors="pt").to("cuda")
    torch.manual_seed(seed)  # reproducible-ish per question
    t0 = time.perf_counter()
    with torch.no_grad():
        out = model.generate(**ids, max_new_tokens=max_new_tokens,
                             do_sample=True, **sampling,
                             pad_token_id=tokenizer.eos_token_id)
    gen_s = time.perf_counter() - t0
    new_tokens = out[0][ids["input_ids"].shape[1]:]
    answer = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
    return {
        "answer": answer,
        "prompt_tokens": int(ids["input_ids"].shape[1]),
        "completion_tokens": int(new_tokens.shape[0]),
        "generation_seconds": round(gen_s, 2),
        "tokens_per_second": round(new_tokens.shape[0] / gen_s, 2),
    }


def run_variant(variant: str, questions: list, tokenizer, model,
                args, load_s: float) -> None:
    system = build_system_prompt(variant, args.date,
                                 with_style_policy=args.with_style_policy)
    if variant == "control":
        data = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
        control_ids = set(data["control_question_ids"])
        qs = [q for q in questions if q["id"] in control_ids]
    else:
        qs = questions
    if args.questions:
        wanted = {w.strip() for w in args.questions.split(",")}
        qs = [q for q in qs if q["id"] in wanted]
    if args.limit:
        qs = qs[:args.limit]

    print(f"\n=== variant {variant} — {len(qs)} question(s) ===")
    print(f"system prompt: {system!r}")

    results = []
    for i, q in enumerate(qs):
        seed = 20260713 + int(q["id"][1:])  # stable per question id
        print(f"[{variant} {i + 1}/{len(qs)}] {q['id']} ({q['category']})...",
              flush=True)
        gen = generate_answer(tokenizer, model, system, q["question"],
                              args.max_new_tokens, seed)
        print(f"    {gen['completion_tokens']} tok in "
              f"{gen['generation_seconds']}s "
              f"({gen['tokens_per_second']} tok/s)")
        results.append({
            "id": q["id"],
            "category": q["category"],
            "adversarial": q["adversarial"],
            "question": q["question"],
            **gen,
            "judgment": {
                "in_character": None,        # yes | partial | no
                "fabrication_detected": None,  # yes | no
                "notes": None,
            },
        })

    peak_gib = torch.cuda.max_memory_allocated() / 2**30
    reserved_gib = torch.cuda.max_memory_reserved() / 2**30
    out = {
        "metadata": {
            "run_at": datetime.datetime.now(datetime.timezone.utc)
                      .isoformat(timespec="seconds"),
            "variant": variant,
            "system_prompt": system,
            "present_date": (CONTROL_DATE if variant == "control"
                             else args.date),
            "base_model": BASE_ID,
            "adapter": persona.ADAPTER_LOCAL_PATH_WSL,
            "adapter_hf_id": persona.ADAPTER_HF_ID,
            "quantization": "4-bit NF4, bfloat16 compute (BitsAndBytes)",
            "sampling": persona.sampling_defaults(),
            "max_new_tokens": args.max_new_tokens,
            "model_load_seconds": round(load_s, 1),
            "peak_vram_allocated_gib": round(peak_gib, 2),
            "peak_vram_reserved_gib": round(reserved_gib, 2),
            "torch": torch.__version__,
            "gpu": torch.cuda.get_device_name(0),
            "judged_by": None,  # filled by the judging pass
        },
        "results": results,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = ("_probe" if args.questions
              else "_smoke" if args.limit else "")
    path = RESULTS_DIR / f"timetravel_{variant}{suffix}.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print(f"wrote {path} (peak VRAM {peak_gib:.2f} GiB allocated / "
          f"{reserved_gib:.2f} GiB reserved)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=["A", "B", "C", "control", "all"],
                    default="all")
    ap.add_argument("--questions", default="",
                    help="comma-separated question ids to run (e.g. "
                         "q18,q19,q20 for the adversarial subset)")
    ap.add_argument("--with-style-policy", action="store_true",
                    help="append the voice agent's spoken-style policy, "
                         "mirroring production instructions")
    ap.add_argument("--limit", type=int, default=0,
                    help="run only the first N questions (smoke test); "
                         "output gets a _smoke suffix")
    ap.add_argument("--max-new-tokens", type=int, default=400)
    ap.add_argument("--date", default=PRESENT_DATE_DEFAULT,
                    help="present-day date for variants A/B")
    args = ap.parse_args()

    questions = json.loads(
        QUESTIONS_PATH.read_text(encoding="utf-8"))["questions"]
    tokenizer, model, load_s = load_model()

    variants = ["A", "B", "control"] if args.variant == "all" else [args.variant]
    for v in variants:
        run_variant(v, questions, tokenizer, model, args, load_s)
    print("\ndone.")


if __name__ == "__main__":
    main()
