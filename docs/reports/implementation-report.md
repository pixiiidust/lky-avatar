# Implementation report — lky-avatar orchestrated build

**Date:** 2026-07-14 · **Operator:** Jamie (pixiiidust) · **Method:** orchestrated
worktree subagents per issue, orchestrator-reviewed PRs, issues closed only on
verified evidence.

## What was built

A voice conversation with a simulated elder Lee Kuan Yew, honestly labeled as
an AI simulation, staged as a broadcast interview: browser mic → LiveKit →
Deepgram STT → a fine-tuned Qwen3-14B persona brain served locally at 80 tok/s
→ a cloned elder voice (Chatterbox zero-shot, watermarked) → the browser,
with sub-300 ms barge-in, a typed-question fallback, a transcript that reads
as a record of proceedings, and export for eval traces.

**What this means:** everything from "speak into the page" to "he answers in
his own voice and manner, and you can cut him off mid-sentence" runs on one
home GPU, with the media transport on LiveKit Cloud's free tier. Nothing in
the serving path leaves the machine except STT and the WebRTC media.

## Issue board — final state

| Issue | Outcome | Evidence |
|---|---|---|
| #1–#7, #9 | ✅ closed earlier in the run | on each issue |
| #8 cloned voice | ✅ closed — live session verdict: voice good, echo gone, barge-in works | issue #8; voice locked chatterbox + `elder_ref_04` + speed 1.0 |
| #11 interaction gate | ✅ closed — **PASS on all three targets** | [`interaction-gate.md`](interaction-gate.md) |
| #33 UI design pass | ✅ closed — interview-studio identity + operator revisions (chyron fold, typed input) | PRs #39, #41; screenshots in docs/design/ |
| #40 transcript export | ✅ closed — JSONL eval trace + Markdown record | PR #41; fixture `evals/sample_session_trace.jsonl` |
| #13 hosting + hardening | ✅ closed — unique rooms, busy gate, rate limit, reset, TTS-outage fix, hosting decision, stability gauntlet | PRs #42, #43; [`hosting-decision.md`](hosting-decision.md) |
| **#10 feasibility rig** | ⏳ **operator** — Cubism rig on the final portrait (queued: tomorrow) | `docs/style-feasibility-rig.md` |
| **#12 final rig** | ⏳ blocked by #10 (final-art hours formally authorized by the #11 gate) | includes measuring lip-sync offset ≤120 ms, not tuning by eye |

Two issues remain open, both waiting on operator art time — the run's defined
end state ("every issue closed with evidence or advanced to its automatable
maximum with operator steps queued") is reached.

## The numbers that matter

| Metric | Value | Where measured |
|---|---|---|
| Brain decode | 80.5 tok/s p50 (32.6× over the NF4 baseline) | [`serving-upgrade.md`](serving-upgrade.md) |
| Brain TTFT | 0.05 s (warm, per request) | same |
| End-of-speech → first-audio | p50 3.96 s / worst 5.95 s (10 live turns) | [`interaction-gate.md`](interaction-gate.md) |
| Interruption → playback stop | ~15–20 ms after detection; ~270 ms raw incl. the deliberate 250 ms window | agent `INTERRUPT` lines, live |
| Typed note → spoken answer | 3.2–9.3 s (TTS-load dependent) | live probes |
| 30-min session soak | 37/37 turns, 0 failures | #13 stability pass |
| VRAM (brain + voice resident) | ~14.3 GiB of 16 GiB | nvidia-smi during sessions |

**What this means:** the visitor-facing feel is now bounded by voice
synthesis of the first sentence, not by the language model; interruptions are
effectively instant once the agent decides you mean it; and the whole stack
held a half-hour conversation without a single dropped turn.

## What the hardening pass caught (and fixed)

The stability gauntlet's one real find: with the TTS server dead, a reply
became a **silent void** — no audio, no transcript, no error, because the SDK
only emits transcript text in sync with audio playout. Fixed same evening
(PR #43): the reply now arrives as text on the record, the page shows a
"Sound is down" slate, and the session survives arbitrarily long voice
outages. Verified by live fault injection. The stale-room bug ("connected but
nothing answers") was eliminated by minting a unique room per session, and a
second simultaneous visitor now gets a designed IN SESSION slate instead of
silently sharing the brain (verified live: 409 while occupied, released on
leave; rate limit 429 + Retry-After beyond burst).

For the full problems-and-solutions story in plain language:
[`docs/faq.md`](../faq.md).

## What remains (the operator's queue)

1. **#10 Cubism rig** (tomorrow) → unblocks **#12 final rig** (agent-able
   except the art itself; lip-sync offset gets measured, ≤120 ms).
2. **lky-voice**: transcript-correction pass + blind A/B listen. If the
   fine-tuned voice wins, its integration arrives as a PR into
   `services/tts_server` (their ticket #7) — review like any other PR, with
   the A/B verdict as acceptance evidence. Accent complaints stay delegated
   there.
3. **Hosting go/no-go**: the recommendation (home GPU + tunnel, ~$0/mo) is
   documented in [`hosting-decision.md`](hosting-decision.md); publishing the
   link is your call.
4. Residual 3-minute check queued for the next live stack: watch `lky.tts`
   flip back to `ok` in the same session after a TTS restart (recovery itself
   already verified; the flip is unit-tested).

## Current machine state (end of run)

All services are **down** (operator shutdown at ~20:45). Relaunch order when
wanted: llama-server (8001, command in
[`serving-upgrade.md`](serving-upgrade.md)) → TTS (WSL, 8100, per
`services/tts_server/run_real.md`) → token server (8090) → voice agent →
web (5173) — then delete stale LiveKit rooms before connecting (or simply
trust the new unique-room minting). One rule from tonight: never leave two
agent workers registered; the second steals dispatch.
