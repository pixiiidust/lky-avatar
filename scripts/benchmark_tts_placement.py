"""Same-GPU placement benchmark: tts_server beside the brain (lky-voice #7).

Drives a 10-turn conversation through the two production servers exactly the
way the voice agent does — brain reply (llama-server, OpenAI-compatible,
port 8001) then cloned-voice synthesis of that reply (tts_server, port 8100)
— and records per-turn timing, synthesis RTF, and total-GPU VRAM samples
(nvidia-smi). Pass criteria from the plan: synthesis RTF <= 0.6, no OOM/5xx
across all 10 turns.

Both servers must already be running (their run_real.md launch commands).
Stdlib only; run from the repo root with any Python:

    python scripts/benchmark_tts_placement.py \
        --out evals/results/tts_placement_<t3-tag>_<sha>.json

The result JSON is committed (text only) as the placement evidence.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import subprocess
import sys
import time
import urllib.request

BRAIN_URL = "http://127.0.0.1:8001/v1/chat/completions"
TTS_URL = "http://127.0.0.1:8100"

PROMPTS = [
    "Good evening. How are you tonight?",
    "What made Singapore succeed where others failed?",
    "Was the ban on chewing gum really necessary?",
    "How should a small country think about superpower rivalry?",
    "What do you make of social media and public discourse?",
    "Tell me about the water agreements with Malaysia.",
    "What keeps a government honest?",
    "Is multiculturalism engineered or organic in Singapore?",
    "What would you tell a young Singaporean entering politics?",
    "Any regrets about the hard choices you made?",
]

SYSTEM = ("You are Lee Kuan Yew in his elder years: direct, precise, "
          "unsentimental. Answer in 2-4 sentences.")


def vram_mib() -> int | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout.strip().splitlines()
        return int(out[0]) if out else None
    except Exception:
        return None


def post_json(url: str, payload: dict, timeout: float = 120.0):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, dict(resp.headers), resp.read()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--turns", type=int, default=10)
    args = ap.parse_args()

    health = json.loads(urllib.request.urlopen(TTS_URL + "/health", timeout=10).read())
    if not health.get("model_loaded"):
        sys.exit("tts_server not ready")

    messages = [{"role": "system", "content": SYSTEM}]
    turns, failures = [], 0
    vram_samples = [vram_mib()]

    for i, prompt in enumerate(PROMPTS[: args.turns], 1):
        messages.append({"role": "user", "content": prompt})
        t0 = time.perf_counter()
        st, _, body = post_json(BRAIN_URL, {
            "model": "lky", "messages": messages, "max_tokens": 160, "stream": False})
        brain_s = time.perf_counter() - t0
        if st != 200:
            failures += 1
            turns.append({"turn": i, "brain_status": st})
            continue
        reply = json.loads(body)["choices"][0]["message"]["content"].strip()
        messages.append({"role": "assistant", "content": reply})

        t1 = time.perf_counter()
        st2, hdrs, _audio = post_json(TTS_URL + "/synthesize", {
            "text": reply[:1000], "format": "wav"})
        synth_s = time.perf_counter() - t1
        hdrs = {k.lower(): v for k, v in hdrs.items()}  # uvicorn lowercases
        audio_s = float(hdrs.get("x-audio-seconds", 0) or 0)
        server_synth_s = float(hdrs.get("x-synth-seconds", 0) or 0)
        rtf = (server_synth_s / audio_s) if audio_s else None
        vram_samples.append(vram_mib())
        ok = st2 == 200
        failures += 0 if ok else 1
        turns.append({
            "turn": i, "prompt": prompt, "reply_chars": len(reply),
            "brain_s": round(brain_s, 2), "synth_wall_s": round(synth_s, 2),
            "audio_s": round(audio_s, 2), "server_synth_s": round(server_synth_s, 2),
            "rtf": round(rtf, 3) if rtf is not None else None,
            "tts_status": st2, "vram_mib": vram_samples[-1],
        })
        rtf_str = f"{rtf:.2f}" if rtf is not None else "n/a"
        print(f"turn {i:2d}: brain {brain_s:5.1f}s | {audio_s:5.1f}s audio "
              f"in {server_synth_s:5.1f}s (rtf {rtf_str}) | vram {vram_samples[-1]} MiB")

    rtfs = [t["rtf"] for t in turns if t.get("rtf") is not None]
    result = {
        "recorded_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "tts_engine": health.get("engine"),
        "brain": "llama-server q4_k_m 14B (port 8001)",
        "turns": turns,
        "aggregate": {
            "n_turns": len(turns), "failures": failures,
            "rtf_mean": round(sum(rtfs) / len(rtfs), 3) if rtfs else None,
            "rtf_max": round(max(rtfs), 3) if rtfs else None,
            "vram_mib_max": max(v for v in vram_samples if v is not None),
            "gates": {"rtf_max <= 0.6": (max(rtfs) <= 0.6) if rtfs else False,
                      "no failures": failures == 0},
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    agg = result["aggregate"]
    print(f"\nrtf mean {agg['rtf_mean']} max {agg['rtf_max']}; "
          f"vram max {agg['vram_mib_max']} MiB; failures {agg['failures']}")
    print("wrote", args.out)
    return 0 if all(agg["gates"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
