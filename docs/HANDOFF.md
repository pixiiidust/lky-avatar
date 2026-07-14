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

## ⚡ IN FLIGHT — CRITICAL: serving upgrade (your first action)

A subagent (worktree `.claude/worktrees/agent-a6971746ee7ae3f88`, branch
`serving-gguf-llamacpp`) replaced the 2.47 tok/s bitsandbytes serving:

- **`llama-server.exe` is RUNNING natively on Windows, port 8001**, model
  `C:\Users\Jamie\lky-avatar-serving\models\lky-qwen3-14b-epoch2-q4_k_m.gguf`
  (~10.9 GB VRAM). Orchestrator's live sample: **66 tokens in 1.04 s (~60+
  tok/s, ~25× baseline)**, answer fully in-voice.
- Report draft exists at `<worktree>/docs/reports/serving-upgrade.md`; no PR yet.
- Still owed: formal measurements, the parity probe (q18,q19,q20,q01,q05 with the
  PRODUCTION prompt = variant C + FEW_SHOT_TURNS + style policy from
  services/voice_agent/persona_prompt.py, via HTTP, locked sampling), the PR.
- **First action**: check for its PR/notification; if stalled, take over from the
  worktree per the pattern. YOU judge parity transcripts (rubric:
  docs/eval-process.md — q19 premise correction must hold; q18/q20 fabrication is
  the documented residual, not a regression). Merge on pass.

## Then: the combined live session (closes #8, feeds #11)

1. Flip `.env`: `OPENAI_BASE_URL=http://127.0.0.1:8001/v1` (llama-server; port
   8000 transformers brain_api remains the fallback). `.env` holds REAL keys —
   never print it; validated already (LiveKit + Deepgram work).
2. Launch: llama-server (if not running) · TTS server (WSL:
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
- Sibling project **lky-voice** (accent fine-tune, own tracker + GOAL.md) starts
  in a fresh session AFTER this project's GPU work ends — don't start it here;
  its integration lands later via lky-avatar's tts_server seam.

## Operator's own queue (don't nag, do surface when relevant)

#10 Cubism rig · #12 after that · launching lky-voice · final say on every
voice/feel verdict.
