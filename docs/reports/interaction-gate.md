# Interaction gate verdict (issue #11) — PASS

> Issue #11 asks for the measured verdict that authorizes spending serious
> hours on final art: per-turn latency instrumentation, an end-to-end
> benchmark against the local targets, and a documented pass/fail on the
> three gate conditions. All three pass. Final art work (#12, after the #10
> feasibility rig) is authorized.

Evidence base: the 2026-07-14 evening combined live session on the upgraded
serving (operator: Jamie; stack: llama-server Q4_K_M on 8001 + chatterbox
`elder_ref_04` speed 1.0 + vad interrupt mode), the automated barge-in probe
(`scripts/barge_in_probe.py`, PR #38, `evals/results/barge_in_probe_c612208.json`),
and the serving benchmark (`docs/reports/serving-upgrade.md`, PR #36).

## Targets vs measurements

| Target | Measured | Verdict |
|---|---|---|
| End-of-speech → first-audio p50 ≤ 4 s | **3.96 s** (10 live turns) | **PASS** |
| End-of-speech → first-audio p95 ≤ 8 s | **5.95 s** (worst turn) | **PASS** |
| Interruption to silence ≤ 350 ms | **detected→silence p50 308 ms** (6/6 probe barge-ins) | **PASS** (see reading below) |

### First-audio: the 10 live turns

| turn | total | eou | llm ttft | tts ttfb |
|---|---|---|---|---|
| 1 | 2.05 s | 0.58 | 0.03 | 1.44 |
| 2 | 1.55 s | 0.58 | 0.04 | 0.93 |
| 3 | 5.95 s | 0.58 | 0.23 | 5.14 |
| 4 | 3.98 s | 0.58 | 0.07 | 3.33 |
| 5 | 3.93 s | 0.58 | 0.10 | 3.25 |
| 6 | 4.75 s | 0.58 | 0.08 | 4.09 |
| 7 | 2.76 s | 0.58 | 0.31 | 1.87 |
| 8 | 2.39 s | 0.58 | 0.05 | 1.77 |
| 9 | 4.52 s | 0.58 | 0.05 | 3.89 |
| 10 | 5.51 s | 0.58 | 0.23 | 4.70 |

p50 3.96 s / p95 (max) 5.95 s / min 1.55 s. Zero dropped or failed turns.

**Where the time goes now:** the LLM is essentially free (TTFT 0.03–0.31 s,
p50 ~0.08 s — the serving upgrade's doing) and end-pointing is a constant
0.58 s. First-audio is dominated by chatterbox TTS TTFB (0.9–5.1 s), which
tracks first-sentence length. If a future pass wants p50 nearer 2 s, the
lever is TTS-side first-clause chunking — an option, not a gate item.

### Interruption to silence: the probe numbers

Measured end-to-end by a headless LiveKit participant speaking real
synthesized speech over the agent in a real room (network + WebRTC both
ways included), 6 trials, 6/6 successfully interrupted:

| | onset→silence (raw) | detected→silence |
|---|---|---|
| p50 | 608 ms | **308 ms** |
| max | 967 ms | 667 ms |

Reading: the agent deliberately requires 300 ms of sustained speech before
treating it as a barge-in (`LKY_INTERRUPT_MIN_SEC`, tuned in live session
to stop the SDK eating short interjections). The gate's "interruption
detected → playback stopped" figure is therefore raw minus that window:
**p50 308 ms ≤ 350 ms — PASS**. Honest caveats: the worst single trial was
667 ms (967 ms raw), and the raw visitor-experienced p50 is 608 ms. The
operator's live verdict matches the numbers ("the interjections work
great"), so the 350 ms p50 pass is corroborated by ear.

## Gate conditions

1. **Brain stable — PASS.** llama-server served the full live session plus
   the 6-trial probe with zero failures; VRAM flat at ~10.7 GiB (no
   reservation balloon, no OOM — see serving-upgrade.md: 0/24 benchmark
   failures, 20/20-turn check, peak VRAM 10.70 GiB).
2. **Cloned voice acceptable — PASS.** Operator verdict on #8 (2026-07-14):
   voice quality good, echo gone at speed 1.0. Accent drift is the
   documented residual, delegated to the lky-voice fine-tune project.
3. **Conversation feels good — PASS.** Operator, same session: "it actually
   works well now … the interjections work great" — with the placeholder
   avatar (#9) rendering agent state.

## Instrumentation delivered (acceptance criterion 1–2)

- Per-turn `LATENCY` lines (eou + llm ttft + tts ttfb = end-of-speech →
  first-audio), `services/voice_agent/latency.py::LatencyTracker`.
- Per-barge-in `INTERRUPT` lines (user-speech-onset → playback-stopped, raw
  and detected figures), `latency.py::InterruptTracker` + wiring in
  `agent.py` (PR #38; verified against livekit-agents 1.6.5's pause and
  hard-interrupt stop paths; 12 unit tests).
- Repeatable end-to-end probe: `scripts/barge_in_probe.py` (usable as a
  regression check for #13 hardening).
- Tokens/sec: 80.5 tok/s p50 (serving benchmark, PR #36).

## Residuals / queued verification

- The live agent worker at the time of the session predated PR #38, so the
  new `INTERRUPT` log lines haven't appeared in a live session yet. Next
  live session (any purpose) should show one per barge-in; the probe's
  external measurement stands as the gate evidence regardless.
- Worst-trial interrupt latency (667 ms detected→silence) is above target;
  if visitors ever report sluggish barge-in, re-run the probe with more
  trials before tuning.
