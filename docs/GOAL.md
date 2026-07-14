# GOAL — read this first

You are a subagent implementing one GitHub issue of the **lky-avatar** project. This file
is your orientation. Read it fully, then read the two source-of-truth documents, then
your assigned issue (`gh issue view <N>`).

## Mission

Build v1 of a **time-traveler LKY reasoning demo**: a web app where a visitor speaks with
a simulated elder Lee Kuan Yew — present-day aware, answering modern questions from his
principles — voiced by a cloned elder voice and fronted by a Live2D avatar, with natural
interruption. Everything is honestly labeled as AI-generated simulation.

## Source of truth (in this order)

1. **Your assigned GitHub issue** — acceptance criteria are the contract you must satisfy.
2. [`docs/spec.md`](spec.md) — product definition, user stories, implementation and
   testing decisions. The two test seams live here.
3. [`docs/lky-avatar-plan.md`](lky-avatar-plan.md) — milestones, decisions log, risk
   register, repository layout (§6).

If issue, spec, and plan conflict: issue > spec > plan. Do not re-litigate decisions
recorded in the spec's Implementation Decisions or the plan's Decisions Log.

## Non-negotiable decisions (recap)

- **One persona, one voice, one avatar.** No era selection anywhere.
- **Time-traveler framing**: present-day date in the system prompt; the persona reasons
  from LKY's principles and must not fabricate specific quotes, meetings, or memories.
- **Sampling locked**: `enable_thinking=false`, temperature 0.7, top_p 0.9,
  repetition_penalty 1.1. Epoch-2 adapter only.
- **Brain API is strictly OpenAI-compatible** (chat completions + SSE). It is the primary
  test seam and the hosting-portability boundary.
- **Avatar state machine is a pure module** (idle | listening | thinking | speaking |
  interrupted | error) — the second test seam.
- **TTS is self-hosted** (Chatterbox-class), watermark preserved, callable only by the
  agent — never a public endpoint.
- Plain Transformers + PEFT + 4-bit NF4 for local inference. **No Unsloth at inference.**

## Environment facts (verified 2026-07-13)

- **This repo (Windows):** `C:\Users\Jamie\lky-avatar` → github.com/pixiiidust/lky-avatar
- **lky-brain checkout (READ-ONLY — never modify it):** `C:\Users\Jamie\lky-brain`
  - Persona functions to vendor: `train/chat.py` — `role_for()` (line ~33),
    `system_prompt()` (line ~43)
- **Epoch-2 adapter:**
  - Local: `C:\Users\Jamie\lky-brain\train\out-lky-qlora\keep-epoch2-step1050`
    (WSL path: `/mnt/c/Users/Jamie/lky-brain/train/out-lky-qlora/keep-epoch2-step1050`)
  - HuggingFace: `sjsim/lky-qlora`
- **GPU runs go through WSL** (RTX 5070 Ti, 16 GB — one model in VRAM at a time):
  `wsl -d Ubuntu-24.04 -- bash -c '~/uns/bin/python <script>'`
  The `uns` venv has torch 2.12.1+cu130 (CUDA verified), transformers 5.3.0, peft 0.19.1.
- **Windows host tooling:** Node 22 / npm 10, Python 3.11 (pure-logic tests run here;
  GPU work runs in WSL). The Bash tool is Git Bash.
- **GPU serialization:** if your issue needs the GPU, assume the orchestrator scheduled
  you exclusively. Do not leave model processes running when you finish.

## Working conventions

- **Branch** from `main`: `issue-<N>-<short-slug>`. Never commit to `main` directly.
- **PR**: title starts with the issue title; body starts with `Closes #<N>`, then a
  Verification section with actual evidence (test output, benchmark JSON, curl
  transcripts). End the body with:
  `🤖 Generated with [Claude Code](https://claude.com/claude-code)`
- **Commits** end with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- **Placeholder-key policy** (the operator is asleep; no real credentials tonight):
  services must build and unit-test with NO real keys. Read config from env; document
  every needed key in `.env.example` with a `PLACEHOLDER_` value and a comment saying
  where to get it. Where live verification is impossible without keys, implement against
  a fake/mock provider, make the fake injectable, and list the exact live-verification
  steps in the PR under "Needs live verification".
- **Never commit:** real keys, `.env`, audio files, art sources, rigged models, model
  weights, generated indexes. Check `.gitignore` covers your additions.
- **Testing standards** (from spec.md): test external behavior at the seams only.
  Brain-API behavior is tested as an HTTP client (a fake generation engine may be
  injected behind the endpoint for fast tests; real-model runs are verification, not CI).
  State-machine behavior is tested as a pure module. Do NOT unit-test through LiveKit,
  STT, or TTS providers — those are covered by scripted benchmarks and protocols.
- **Python services:** one venv per service (create under the service directory,
  `.venv/`, gitignored). Windows Python for pure logic; WSL only when CUDA is required.
- **Report back** (your final message to the orchestrator): PR URL, what you verified
  and how, what remains for live verification, and anything you discovered that later
  issues should know.

## Issue dependency graph

```text
#1 scaffold+persona ─┬─> #2 time-travel test (GPU)
                     ├─> #3 baseline benchmark (GPU)
                     └─> #5 brain API (GPU verify) ─┐
#4 walking skeleton ─────────────────┬─> #6 brain into skeleton ─> #8 cloned voice ─┐
                                     └─> #9 placeholder avatar ─────────────────────┼─> #11 gate
#7 voice ref + TTS test (user assets needed for clips; engine bench automatable)  ──┘     │
#10 portrait + feasibility rig (user assets needed)  ─> #12 final avatar <───────────────┤
                                                        #13 hosting + hardening <────────┘
```

Issues #7 and #10 are **blocked-on-user** for raw materials (rights-checked voice clips,
AI-generated portraits); build everything automatable around them.

## Definition of done for the orchestrated run

Every issue either (a) closed with acceptance criteria verifiably met, or (b) advanced to
the maximum automatable point with a PR merged and a precise checklist of the human steps
remaining (keys, assets, listening tests) recorded on the issue. A final implementation
report is committed to `docs/reports/`.
