# Session handoff — lky-avatar orchestration (2026-07-14, night — run complete)

## Resume prompt (paste into a new session)

```
Read docs/HANDOFF.md in C:\Users\Jamie\lky-avatar and resume as the
orchestrator it describes — same proven pattern: worktree subagents pointed
at docs/GOAL.md, you review/merge every PR, close issues only on verified
evidence, serialize GPU work, take over stalled agents' final assembly
yourself. The build run is COMPLETE (docs/reports/implementation-report.md);
what remains is reactive: #12 once I finish the #10 Cubism rig, the lky-voice
integration PR into services/tts_server if its voice wins my blind A/B
(review it against the handoff's contract), the hosting go-live when I say
so, and the queued 3-minute lky.tts recovery check next time the stack is
up. The full stack is DOWN — relaunch order is in the implementation
report's last section; never leave two agent workers registered. The
parallel lky-voice session's state and the coordination contract are in the
handoff's "Parallel session" section. Any questions before you start? If
no, wait for my direction — nothing is agent-actionable until I finish an
operator step or a PR arrives.
```

## Where things stand

The orchestrated build reached its end state: **every issue closed on
verified evidence except #10/#12, which wait on operator art time.** Full
outcome, numbers, and the operator queue:
[`docs/reports/implementation-report.md`](reports/implementation-report.md).

Agent-actionable work that may arrive:

- **#12 final rig** once the operator finishes #10 — agent-able except the
  art; measure lip-sync offset (≤120 ms target) in lipSync.ts, don't tune by
  eye.
- **lky-voice integration PR** (their ticket #7) against
  `services/tts_server` — review like any PR; the operator's blind-A/B
  verdict is its acceptance criterion; GPT-SoVITS output must be watermarked
  post-hoc (standalone `perth`) to keep the §9 requirement.
- **Hosting go-live** if the operator green-lights the tunnel
  ([`docs/reports/hosting-decision.md`](reports/hosting-decision.md)).
- Residual 3-min check: `lky.tts` error→ok flip in-session after a TTS
  restart (next time the stack is up; recovery itself verified, flip is
  unit-tested).

## Parallel session: lky-voice (status as relayed 2026-07-14 night)

Their orchestrated run is ALSO complete (run report merged:
`lky-voice/docs/reports/orchestrated-run-2026-07-14.md`, PR #14). GPU clean
(1.7 GB desktop floor, lock free). Key facts for this repo:

- GPT-SoVITS runs on the sm_120 card (torch 2.12.1+cu130, RTF 0.148,
  ~2.1 GB VRAM). Honest baseline frozen: similarity 0.8693 / WER 0.032.
- Draft-transcript training already **beats the baseline on similarity
  (0.8963) but fails intelligibility (WER 0.19)** — retrain on corrected
  transcripts is queued and cheap (~20–30 min GPU; training takes minutes on
  this card, not hours).
- **The entire critical path is two operator steps over there:** (1)
  transcript review (`data/processed/dataset_v1/transcripts_review.tsv`,
  ~10–60 min) → triggers retrain → dense checkpoint sweep → listening pack;
  (2) blind A/B listen (~20 min). Only a winning verdict produces the
  integration PR here (their #7); a LoRA comparison arm (#8) is an explicit
  fallback outcome in their verdict tooling.
- Accent complaints from any future live session stay delegated to
  lky-voice — log on this repo's #8 history, don't hunt references here.

## Coordination contract (unchanged)

One GPU; check nvidia-smi before loading; their retrain bursts (~20–30 min)
want the card — don't load llama/chatterbox while one is announced. Never
kill processes you didn't start (the auto-mode classifier enforces this
hard — for your OWN launches keep task ids and use TaskStop; for anything
older, ask the operator). lky-voice touches this repo only via its #7 PR.
Both sessions never edit the same repo concurrently.

## Stack state at handoff

All services DOWN (operator shutdown ~20:45; two harness-level mass-kills —
treat that as "leave the machine quiet until asked"). Relaunch order and the
two-workers trap are in the implementation report's last section. `.env` is
correct as-is (8001 brain, chatterbox TTS, vad interrupts, min-interrupt
0.25 s — note: NOT the 0.3 default; probes must read it from env).

## Operator working style

See memory dir + `docs/GOAL.md`. New tonight: explanatory docs follow
"technical answer → what this means → for example" (`docs/faq.md` is the
template); he reviews visuals from labeled screenshots on his Desktop
(`lky-ui-screenshots\_view-all.html` contact sheet) rather than PR embeds.
