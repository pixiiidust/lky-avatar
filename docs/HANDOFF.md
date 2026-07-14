# Session handoff — lky-avatar orchestration (2026-07-14, evening)

You are resuming as the **orchestrator** of lky-avatar's issue implementation.
The operator is Jamie (GitHub pixiiidust). Your working pattern, proven all day:
spawn worktree-isolated subagents per issue pointed at `docs/GOAL.md` (the
subagent orientation doc — env facts, conventions, PR format), review every PR
yourself, merge on evidence, close issues only when acceptance criteria are
verifiably met (`Part of #N` when operator steps remain), serialize GPU work,
and if an agent goes quiet after a long run completes, **take over its final
assembly yourself** (fill reports, commit, PR) — they reliably stall there.
Operator feedback is terse and canonical ("much better", "sounds echoy") —
treat it as eval findings: reproduce, root-cause, fix, retest. His ear
overrides metrics on quality calls. The goal ends with every issue closed or
maxed-out-automatable + a run report in docs/reports/.

## Issue board

| Issue | State | What's left |
|---|---|---|
| #1–#7, #9 | ✅ CLOSED | evidence on each issue |
| **#8 cloned voice** | OPEN | one live session on the upgraded serving; voice locked: chatterbox + `elder_ref_04` + speed 1.0 (PR #35; rounds logged on the issue) |
| **#10 feasibility rig** | OPEN | operator-only: Cubism rig per docs/style-feasibility-rig.md on assets/avatar-source/lky-portrait-final-2048.png |
| **#11 gate** | OPEN | needs #8's session numbers; instrumentation exists (`LATENCY turn` agent-log lines; brain TTFT in server logs); targets: first-audio p50≤4s, interrupt≤350ms |
| **#12 final rig** | OPEN | blocked by #10 + #11; lip-sync delay noted by operator → measure offset (≤120ms) in lipSync.ts, don't tune by eye |
| **#13 hosting+hardening** | OPEN | after #33; stale-room bug logged there (fix: unique room per session in token server) |
| **#33 UI design pass** | OPEN | full design brief in the issue (interview-studio identity); after #8 |

## ✅ Serving upgrade: DONE and MERGED (PR #36, parity PASSED)

llama.cpp Q4_K_M serving replaced the 2.47 tok/s bitsandbytes path:
**80.5 tok/s p50 (32.6×), TTFT 0.048 s, load 4.1 s, no VRAM balloon, 0/24
failures, 20-turn check 31 s total.** Parity judged by orchestrator: q19
premise correction holds; q18/q20 = documented residual, no regression.
Full report + regeneration runbook: `docs/reports/serving-upgrade.md`.

- Launch command (PowerShell) is in that report; model at
  `C:\Users\Jamie\lky-avatar-serving\models\lky-qwen3-14b-epoch2-q4_k_m.gguf`.
  Server is currently DOWN (GPU free); `.env` already points at
  `http://127.0.0.1:8001/v1`. Port 8000 transformers brain_api = fallback.
- Seam notes: llama-server QUEUES concurrent requests (no 429-busy) and its
  /health is minimal — agent code needs zero changes.
- **Your first action is now the live session below.**

## FIRST ACTION: the combined live session (closes #8, feeds #11)

1. `.env` is already flipped to llama-server (8001). `.env` holds REAL keys —
   never print it; validated already (LiveKit + Deepgram work).
2. Launch: llama-server (command in docs/reports/serving-upgrade.md) · TTS server (WSL:
   `~/tts-chatterbox/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8100`
   in services/tts_server — defaults now ref04/speed1.0) · token server
   (services/token_server, Windows venv, port 8090) · voice agent
   (services/voice_agent `agent.py dev`, Windows venv) · web (`npm run dev`, 5173).
3. **Delete stale LiveKit rooms before the operator connects** (known bug: fixed
   room name + dispatch-on-creation; deletion snippet pattern is in the session
   history / trivial via livekit-api ListRooms→DeleteRoom with .env creds).
4. Operator tests: voice quality (echo should be gone at speed 1.0), reply
   latency (expect ~2s first-audio), barge-in (mode=vad — the SDK's adaptive
   classifier ate short interjections; never re-enable it), harvest `LATENCY`
   lines → #11 verdict doc → close #8, #11.

## Environment quick-facts (full set in docs/GOAL.md + memory dir)

- Windows 11 + WSL Ubuntu-24.04 (user jamie, **15 GB RAM cap** — no big CPU
  merges), RTX 5070 Ti 16 GB **sm_120** (torch 2.12+cu130 works; older doesn't).
- WSL traps: /tmp wiped on idle; CRLF-strip scripts; wrap wsl calls in
  `bash -c "..."`; never pipe long jobs through grep — log to /mnt/c files.
- venvs: WSL `~/uns` (brain), `~/tts-chatterbox` (TTS server), `~/score`;
  Windows: services/*/.venv, web/node_modules — all installed.
- lky-brain repo (C:\Users\Jamie\lky-brain) is READ-ONLY. Audio/art/weights
  never committed (gitignore enforces).
## Parallel session: lky-voice (the big picture)

The operator will run a SECOND orchestrated session for **lky-voice**
(`C:\Users\Jamie\lky-voice`, tracker github.com/pixiiidust/lky-voice, own
GOAL.md) — possibly concurrently with you. Know the whole story so the two
sessions stay coherent:

- **Why it exists:** the zero-shot cloned voice (this repo's #8) has American
  accent drift. Prompt/reference tuning hit its ceiling — three operator
  listening rounds settled on chatterbox + `elder_ref_04` + speed 1.0 as the
  best zero-shot gets (history on issue #8). lky-voice fine-tunes a voice
  (GPT-SoVITS primary, Chatterbox-LoRA arm) on ~48 min of his real speech to
  fix the accent properly.
- **The contract between the projects:** lky-voice changes NOTHING here unless
  its fine-tuned voice **beats the current baseline in the operator's blind
  A/B** (their ticket #6). If it wins, integration arrives as its ticket #7 —
  a PR *into this repo* touching only the `services/tts_server` engine seam,
  following THIS repo's GOAL.md conventions, and it must watermark GPT-SoVITS
  output post-hoc (standalone `perth` package) to keep the §9 requirement.
  Review that PR like any other; the A/B evidence is its acceptance criterion.
- **Shared resources — coordination rules:** one GPU. Check `nvidia-smi`
  before loading models; llama-server (~11 GB) + chatterbox (~3.5 GB) already
  fill the card during live sessions, and lky-voice training runs want the GPU
  alone. Don't kill processes you didn't start — they may be the other
  session's. If the operator says "lky-voice is training", defer GPU work.
  Both sessions must never edit the same repo concurrently: lky-voice only
  ever touches this repo via its #7 PR.
- **Don't duplicate its work**: accent complaints from future live sessions get
  logged on #8 and pointed at lky-voice — no more reference-clip hunting here.

## Operator's own queue (don't nag, do surface when relevant)

#10 Cubism rig · #12 after that · launching lky-voice · final say on every
voice/feel verdict.
