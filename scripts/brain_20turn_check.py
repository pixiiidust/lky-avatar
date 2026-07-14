"""20-turn conversation check against a running brain API (issue #5).

Talks to the OpenAI-compatible seam exactly like a client would (stdlib
urllib only — no service venv needed), holding one growing conversation:
persona system prompt + 20 modern questions, streaming every answer.

Verifies, per the issue's acceptance criteria:
- 20 streamed turns complete against ONE server process (the /health
  instance_id must never change — a restart mid-conversation fails the run);
- every turn streams incrementally and produces non-empty content;
- /health returns to generation_in_flight=false after every turn;
- VRAM (when the real engine reports it) stays flat: max-min drift under
  --vram-drift-gib and absolute allocation under --vram-max-gib.

Records per-turn TTFT, wall time, and pieces/s — at the measured ~2-3 tok/s
of NF4 decode on the 5070 Ti these numbers are the baseline issues #6/#11
tune against.

Usage (server already running, real or fake engine):
    python scripts/brain_20turn_check.py --base-url http://127.0.0.1:8000
Exit code 0 = all checks passed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lky_avatar import persona  # noqa: E402

QUESTIONS = [
    "What do you make of artificial intelligence?",
    "Should Singapore worry about AI taking jobs?",
    "How would you handle social media's effect on politics?",
    "Is the US-China rivalry today more dangerous than the Cold War?",
    "What should small states do about it?",
    "Would you regulate cryptocurrencies?",
    "What do you think of remote work?",
    "How should a government approach climate change?",
    "Is Western liberal democracy in decline?",
    "What would you tell a young Singaporean choosing a career today?",
    "Does meritocracy still work?",
    "How do you keep a multiracial society stable in the internet age?",
    "Should governments fund universal basic income?",
    "What is the biggest threat to Singapore in the next twenty years?",
    "Can ASEAN ever act as one?",
    "What did your generation understand that today's leaders do not?",
    "How would you deal with an aging population?",
    "Is nuclear energy the answer for a country like Singapore?",
    "What makes a good minister?",
    "If you could change one decision you made, would you?",
]


def get_json(url: str, timeout: float = 30.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def stream_turn(base_url: str, payload: dict, timeout: float):
    """POST a streaming chat completion; yield (piece, arrival_time)."""
    request = urllib.request.Request(
        base_url + "/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            data = line[len("data: "):]
            if data == "[DONE]":
                return
            chunk = json.loads(data)
            if "error" in chunk:
                raise RuntimeError(f"server error mid-stream: {chunk['error']}")
            choices = chunk.get("choices") or []
            if not choices:
                continue
            piece = choices[0].get("delta", {}).get("content")
            if piece:
                yield piece, time.perf_counter()
        raise RuntimeError("stream ended without data: [DONE]")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--turns", type=int, default=len(QUESTIONS))
    parser.add_argument(
        "--max-tokens", type=int, default=None,
        help="per-turn max_tokens (default: server default, 320)",
    )
    parser.add_argument(
        "--turn-timeout", type=float, default=600.0,
        help="seconds allowed per turn (NF4 decode is slow: ~2-3 tok/s)",
    )
    parser.add_argument("--vram-max-gib", type=float, default=12.0)
    parser.add_argument("--vram-drift-gib", type=float, default=1.0)
    parser.add_argument("--out", help="write the JSON summary to this path")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    health = get_json(base_url + "/health")
    print(f"server: engine={health['engine']} model={health['model']} "
          f"instance={health['instance_id'][:12]} "
          f"vram={health['vram_allocated_gib']} GiB")
    if not health["model_loaded"]:
        print("FAIL: model not loaded", file=sys.stderr)
        return 1
    instance_id = health["instance_id"]

    today = date.today().isoformat()
    history: list[dict] = [
        {"role": "system", "content": persona.system_prompt(today)}
    ]
    turns: list[dict] = []
    failures: list[str] = []

    for turn_number, question in enumerate(QUESTIONS[: args.turns], start=1):
        history.append({"role": "user", "content": question})
        payload: dict = {
            "model": "lky",
            "messages": history,
            "stream": True,
        }
        if args.max_tokens is not None:
            payload["max_tokens"] = args.max_tokens

        t_start = time.perf_counter()
        first_at = None
        pieces: list[str] = []
        try:
            for piece, at in stream_turn(base_url, payload, args.turn_timeout):
                if first_at is None:
                    first_at = at
                pieces.append(piece)
        except (urllib.error.URLError, RuntimeError, TimeoutError) as exc:
            failures.append(f"turn {turn_number}: stream failed: {exc}")
            print(f"turn {turn_number:2d} FAIL: {exc}", file=sys.stderr)
            break
        t_end = time.perf_counter()

        answer = "".join(pieces)
        if not answer.strip():
            failures.append(f"turn {turn_number}: empty answer")
        history.append({"role": "assistant", "content": answer})

        health = get_json(base_url + "/health")
        if health["instance_id"] != instance_id:
            failures.append(
                f"turn {turn_number}: server instance changed "
                f"(restart mid-conversation)"
            )
        if health["generation_in_flight"]:
            failures.append(
                f"turn {turn_number}: generation_in_flight still true "
                f"after the stream finished"
            )

        ttft = (first_at - t_start) if first_at is not None else None
        rate = (
            len(pieces) / (t_end - first_at)
            if first_at is not None and t_end > first_at
            else None
        )
        vram = health["vram_allocated_gib"]
        turns.append(
            {
                "turn": turn_number,
                "question": question,
                "chars": len(answer),
                "pieces": len(pieces),
                "ttft_s": round(ttft, 2) if ttft is not None else None,
                "total_s": round(t_end - t_start, 2),
                "pieces_per_s": round(rate, 2) if rate is not None else None,
                "vram_gib": vram,
            }
        )
        print(
            f"turn {turn_number:2d} ok: {len(answer):4d} chars "
            f"ttft={ttft:.2f}s total={t_end - t_start:6.1f}s "
            f"pieces/s={rate if rate is None else round(rate, 1)} "
            f"vram={vram}"
        )

    # VRAM stability across the whole conversation (real engine only)
    vram_values = [t["vram_gib"] for t in turns if t["vram_gib"] is not None]
    if vram_values:
        drift = max(vram_values) - min(vram_values)
        if max(vram_values) > args.vram_max_gib:
            failures.append(
                f"VRAM peaked at {max(vram_values):.2f} GiB "
                f"(limit {args.vram_max_gib})"
            )
        if drift > args.vram_drift_gib:
            failures.append(
                f"VRAM drifted {drift:.2f} GiB across the conversation "
                f"(limit {args.vram_drift_gib})"
            )

    completed = len(turns)
    summary = {
        "base_url": base_url,
        "engine": health["engine"],
        "instance_id": instance_id,
        "turns_completed": completed,
        "turns_requested": args.turns,
        "failures": failures,
        "vram_min_gib": min(vram_values) if vram_values else None,
        "vram_max_gib": max(vram_values) if vram_values else None,
        "turns": turns,
    }
    print(json.dumps(summary, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(summary, indent=2) + "\n")
        print(f"summary written to {args.out}")

    if failures or completed < args.turns:
        print(f"FAIL: {len(failures)} problem(s), {completed}/{args.turns} "
              f"turns completed", file=sys.stderr)
        return 1
    print(f"PASS: {completed} turns, one server instance, "
          f"no stuck generation slot"
          + (f", VRAM stable ({min(vram_values):.2f}-"
             f"{max(vram_values):.2f} GiB)" if vram_values else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
