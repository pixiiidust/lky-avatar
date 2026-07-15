# Session handoff — lky-avatar orchestration (2026-07-14, night — run complete)

The orchestrated build reached its end state: **every issue closed on
verified evidence except #10/#12, which wait on operator art time.** Full
outcome, numbers, and the operator queue:
[`docs/reports/implementation-report.md`](reports/implementation-report.md).

If you are resuming as orchestrator, the working pattern is unchanged
(worktree subagents per issue pointed at `docs/GOAL.md`, orchestrator reviews
every PR, close only on evidence, serialize GPU work, take over stalled
agents' final assembly). What's left that could need you:

- **#12 final rig** once the operator finishes #10 — agent-able except the
  art; measure lip-sync offset (≤120 ms target) in lipSync.ts, don't tune by
  eye.
- **lky-voice integration PR** (their ticket #7) may arrive against
  `services/tts_server` — review like any PR; operator's blind-A/B verdict is
  its acceptance criterion; GPT-SoVITS output must be watermarked post-hoc
  (standalone `perth`).
- **Hosting go-live** if the operator green-lights the tunnel
  ([`docs/reports/hosting-decision.md`](reports/hosting-decision.md)).
- Residual 3-min check: `lky.tts` error→ok flip in-session after a TTS
  restart (next time the stack is up).

## Stack state at handoff

All services DOWN (operator shutdown ~20:45; two harness-level mass-kills —
treat that as "leave the machine quiet until asked"). Relaunch order and the
two-workers trap are in the implementation report's last section. `.env` is
correct as-is (8001 brain, chatterbox TTS, vad interrupts, min-interrupt
0.25 s — note: NOT the 0.3 default; probes must read it from env).

## Coordination contract with lky-voice (unchanged)

One GPU; check nvidia-smi before loading; never kill processes you didn't
start (the auto-mode classifier enforces this hard — for your OWN launches,
keep task ids and use TaskStop; for anything older, ask the operator);
lky-voice touches this repo only via its integration PR.

## Operator working style

See memory dir + `docs/GOAL.md`. New tonight: explanatory docs follow
"technical answer → what this means → for example" (`docs/faq.md` is the
template); he reviews visuals from labeled screenshots on his Desktop
(`lky-ui-screenshots\_view-all.html` contact sheet) rather than PR embeds.
