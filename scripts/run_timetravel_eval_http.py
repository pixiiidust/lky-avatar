"""Time-travel persona eval over HTTP — the serving-parity gate runner.

``run_timetravel_eval.py`` loads the model in-process (Transformers + PEFT);
this variant asks a RUNNING OpenAI-compatible server instead, so a serving
change (GGUF/llama-server, vLLM, hosting move) can re-run the persona eval
through the exact seam the product uses (docs/eval-process.md: any
quantization/engine change re-runs the eval before shipping).

The prompt build mirrors production ("variant D"): variant-C system prompt +
spoken-style policy + the FEW_SHOT_TURNS exemplars — the same composition as
    run_timetravel_eval.py --variant C --with-style-policy --with-exemplars
and the same per-question seeds. Output schema matches the in-process runner
(judgment placeholders included; this script never grades).

Sampling: temperature/top_p from ``lky_avatar.persona`` are sent explicitly;
repetition_penalty 1.1 and enable_thinking=false must be enforced by the
server (llama-server: ``--repeat-penalty 1.1 --chat-template-kwargs
'{"enable_thinking":false}'``; brain_api enforces both itself).

Usage (server already running):
    python scripts/run_timetravel_eval_http.py \
        --base-url http://127.0.0.1:8001 \
        --questions q18,q19,q20,q01,q05 \
        --out evals/results/timetravel_gguf_probe.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys
import time
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "services" / "voice_agent"))

from lky_avatar import persona  # noqa: E402
from persona_prompt import (  # noqa: E402  (single source of truth)
    FEW_SHOT_TURNS, SPOKEN_STYLE_POLICY, persona_system_prompt,
)

QUESTIONS_PATH = REPO_ROOT / "evals" / "timetravel_questions.json"
PRESENT_DATE_DEFAULT = "2026-07-13"
SEED_BASE = 20260713


def complete(base_url: str, model: str, messages: list, max_tokens: int,
             seed: int, timeout: float) -> dict:
    """Non-streaming chat completion; returns answer text + usage + timing."""
    payload = {
        "model": model,
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": persona.TEMPERATURE,
        "top_p": persona.TOP_P,
        "seed": seed,
        "messages": messages,
    }
    request = urllib.request.Request(
        base_url + "/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    gen_s = time.perf_counter() - t0
    usage = body.get("usage") or {}
    answer = (body["choices"][0]["message"]["content"] or "").strip()
    completion_tokens = int(usage.get("completion_tokens") or 0)
    return {
        "answer": answer,
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": completion_tokens,
        "generation_seconds": round(gen_s, 2),
        "tokens_per_second": (round(completion_tokens / gen_s, 2)
                              if gen_s > 0 and completion_tokens else None),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Time-travel persona eval via an OpenAI-compatible server")
    ap.add_argument("--base-url", default="http://127.0.0.1:8001")
    ap.add_argument("--model", default="lky")
    ap.add_argument("--questions", default="q18,q19,q20,q01,q05",
                    help="comma-separated question ids")
    ap.add_argument("--variant", default="C",
                    help="prompt variant (production composition adds the "
                         "style policy + exemplars regardless)")
    ap.add_argument("--no-exemplars", action="store_true")
    ap.add_argument("--no-style-policy", action="store_true")
    ap.add_argument("--max-new-tokens", type=int, default=400)
    ap.add_argument("--date", default=PRESENT_DATE_DEFAULT)
    ap.add_argument("--engine-label", default="llamacpp-gguf-q4km")
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--out", required=True,
                    help="output JSON path (e.g. "
                         "evals/results/timetravel_gguf_probe.json)")
    args = ap.parse_args()

    system = persona_system_prompt(args.date, args.variant)
    if not args.no_style_policy:
        system = system + "\n\n" + SPOKEN_STYLE_POLICY
    exemplars = [] if args.no_exemplars else list(FEW_SHOT_TURNS)
    base_url = args.base_url.rstrip("/")

    data = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    wanted = [w.strip() for w in args.questions.split(",") if w.strip()]
    by_id = {q["id"]: q for q in data["questions"]}
    missing = [w for w in wanted if w not in by_id]
    if missing:
        raise SystemExit(f"unknown question ids: {missing}")
    qs = [by_id[w] for w in wanted]

    print(f"eval via {base_url} — {len(qs)} question(s), variant "
          f"{args.variant} (+exemplars={not args.no_exemplars}, "
          f"+style_policy={not args.no_style_policy})")
    print(f"system prompt: {system!r}")

    results = []
    for i, q in enumerate(qs):
        seed = SEED_BASE + int(q["id"][1:])  # stable per question id
        messages = ([{"role": "system", "content": system}]
                    + exemplars
                    + [{"role": "user", "content": q["question"]}])
        print(f"[{i + 1}/{len(qs)}] {q['id']} ({q['category']})...",
              flush=True)
        gen = complete(base_url, args.model, messages,
                       args.max_new_tokens, seed, args.timeout)
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

    out = {
        "metadata": {
            "run_at": datetime.datetime.now(datetime.timezone.utc)
                      .isoformat(timespec="seconds"),
            "variant": args.variant,
            "production_composition": (not args.no_exemplars
                                       and not args.no_style_policy),
            "system_prompt": system,
            "few_shot_exemplars": exemplars,
            "present_date": args.date,
            "base_url": base_url,
            "engine_label": args.engine_label,
            "serving": "OpenAI-compatible HTTP (see "
                       "docs/reports/serving-upgrade.md for the launch "
                       "command that pins repetition_penalty and "
                       "enable_thinking=false server-side)",
            "adapter_hf_id": persona.ADAPTER_HF_ID,
            "sampling": persona.sampling_defaults(),
            "max_new_tokens": args.max_new_tokens,
            "judged_by": None,  # filled by the judging pass
        },
        "results": results,
    }
    path = pathlib.Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
