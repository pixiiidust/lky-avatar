# Fine-tuned voice integration: Chatterbox LoRA e14 behind tts_server

**Date:** 2026-07-15 · **lky-voice ticket:** #7 (integration), triggered by
the #8 LoRA arm's eval-gate win · **verdict doc:**
`lky-voice/docs/verdict-2026-07-15-lora.md` (operator blind listen 18/20,
all objective gates PASS)

## What changed

One env knob, no API change, no client change:

- `services/tts_server/app.py`: new optional `LKY_TTS_T3` — path to a merged
  fine-tuned t3 safetensors (LoRA rank 16 folded into the stock weights).
  Loaded with `strict=True` onto the stock `ChatterboxTTS` at startup: either
  the full fine-tuned voice serves, or the server refuses to start. `/health`
  and the startup log report the tag (`t3=t3_lky_lora_e14` vs `t3=stock`).
- `services/voice_agent/config.py`: comment-only — documents that pacing is
  now learned at generation time and `DEFAULT_TTS_SPEED` stays 1.0.
- `run_real.md`: production launch now sets `LKY_TTS_T3`; env-knob table and
  latency notes updated.
- Weights (local-only, never committed): WSL
  `~/lky-voice-models/t3_lky_lora_e14.safetensors` (2.1 GB, fp32), produced
  by merging `epoch_14` of lky-voice training run 3 (their
  `docs/training-run-3.md`) via peft `merge_and_unload`.

## Acceptance criteria — evidence

**1. Unchanged HTTP interface; client tests pass as-is.**
Server launched with the overlay; `/health` → `engine: "chatterbox
t3=t3_lky_lora_e14 ref=elder_ref_04.wav seed=7 sr=24000"`; `/synthesize`
returns 200 + `audio/wav` with the standard `X-*` headers. Full voice_agent
suite (includes the tts provider contract tests) run unmodified on this
branch: **all pass, 0 failures** (3 pre-existing skips for live-service
tests).

**2. Watermark present in served output.**
The LoRA touches only the t3 (token model); generation still flows through
`ChatterboxTTS.generate()`, which embeds PerTh. Verified on an actual served
sample (`/synthesize` response written to disk, decoded, checked with
`perth.PerthImplicitWatermarker.get_watermark`): **confidence 1.0000**.

**3. Same-GPU placement beside the brain.**
`scripts/benchmark_tts_placement.py` (new, committed, rerunnable): 10-turn
conversation alternating llama-server (Qwen3-14B Q4_K_M, port 8001) replies
and tts_server synthesis of each reply, VRAM sampled per turn. Result
(`evals/results/tts_placement_lora-e14_ad1b5a6.json`):

| metric | value | gate |
|---|---|---|
| synthesis RTF mean / max | 0.369 / 0.397 | ≤ 0.6 → **PASS** |
| failures (OOM / 5xx) | 0 / 10 turns | 0 → **PASS** |
| VRAM peak (total card) | 15,813 MiB of 16,303 | no OOM, stable across turns |
| brain reply latency | 0.6–3.0 s (160-token cap) | unchanged vs stock-voice runs |

Same footprint as the stock voice (merged weights = identical architecture;
the historical 0.37–0.49 placement band still applies).

**4. Pacing at generation time — time-stretch retired.**
The fine-tune learned delivery pace from the real recordings: measured on
the frozen eval set, 17.25 chars/s (stock) → 16.18 chars/s (e14), and the
operator's blind listen preferred the unstretched fine-tuned voice on 18/20
pairs. Production serves `speed 1.0` end to end — the phase-vocoder
time-stretch path (known echo artifact, the reason the old default was
0.85) is now idle. It remains available per-request for A/B experiments.

## Rollback

Unset `LKY_TTS_T3` and restart tts_server → stock zero-shot voice, bit-for-
bit the pre-integration behavior. The stock path stays exercised by the
`t3=stock` tag in `/health`.

## Follow-ups (tracked in lky-voice)

- SG proper-noun pronunciation: unfixed by LoRA in either arm (both verdicts
  note it; operator IPA hints recorded — Toa Payoh, Ang Mo Kio, Temasek).
  Next lever: pronunciation-respelling entries in the agent's
  `pronunciation.py` seam + a dedicated SG-nouns eval set.
- More clean same-era data remains the biggest similarity lever
  (lky-voice PLAN §8 wishlist).
