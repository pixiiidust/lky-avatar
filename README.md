# lky-avatar

A time-traveler LKY reasoning demo: speak with a simulated elder Lee Kuan Yew —
present-day aware, answering modern questions from his principles — voiced and
fronted by a Live2D avatar, honestly labeled as an AI-generated simulation.

See [`docs/spec.md`](docs/spec.md) for the product definition,
[`docs/lky-avatar-plan.md`](docs/lky-avatar-plan.md) for milestones, and
[`docs/eval-process.md`](docs/eval-process.md) for how the persona and serving
stack are evaluated (question sets, judging rubric, prompt-variant history,
benchmark baseline).

## Running the walking skeleton

The walking skeleton (issue #4) is the full voice loop with stock parts:
browser microphone → LiveKit → Deepgram STT → any OpenAI-compatible LLM →
Deepgram Aura TTS → browser playback, with interim transcripts and barge-in.

### 0. Prerequisites

- Python 3.11+, Node 22+
- Free accounts: [LiveKit Cloud](https://cloud.livekit.io),
  [Deepgram](https://console.deepgram.com), and any OpenAI-compatible LLM
  provider (OpenAI, Groq, OpenRouter…)

### 1. Install

Each Python service gets its own venv (Windows commands shown; use
`bin/activate` paths on Linux/macOS):

```powershell
# Voice agent
cd services/voice_agent
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
cd ../..

# Token server
cd services/token_server
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
cd ../..

# Web client
cd web
npm install
cd ..

# Placeholder Live2D avatar model (licensed Live2D sample; never committed)
python scripts/fetch_placeholder_model.py
```

### 2. Configure keys

```powershell
copy .env.example .env
```

Fill in every `PLACEHOLDER_` value in `.env`. Each key's comment says exactly
where to obtain it (LiveKit Cloud project settings → Keys, Deepgram console →
API Keys, your LLM provider's key page). Never commit `.env`.

### 3. Run (three terminals)

```powershell
# Terminal 1 — token server (mints short-lived LiveKit tokens; keys stay server-side)
cd services/token_server
.venv\Scripts\python -m uvicorn app:app --port 8090

# Terminal 2 — voice agent (joins the LiveKit room and runs STT→LLM→TTS)
cd services/voice_agent
.venv\Scripts\python agent.py dev

# Terminal 3 — web client
cd web
npm run dev
```

Open http://localhost:5173.

### 4. What you should experience

1. Click **Connect** and allow the microphone. Status shows
   "Connected — agent listening"; the agent greets you in a stock voice.
2. Speak. Your words appear as an *italic interim transcript while you are
   still talking*, then turn solid when final.
3. The agent answers out loud within a few seconds; its transcript streams in
   as it speaks.
4. **Interrupt it mid-answer** — just start talking. Playback stops almost
   immediately and it listens to you again.
5. The red AI-disclosure banner stays visible the whole time (spec
   requirement from day one).

Latency: the agent logs a per-turn line
`LATENCY turn <id>: end-of-speech -> first-audio = X.XXs (eou … + llm ttft … + tts ttfb …)`
in Terminal 2 — this is the issue-#4 "end-of-speech to first-audio with
all-stock-parts" measurement.

If any key is missing or still a `PLACEHOLDER_` value, the agent refuses to
start with a message naming the offending env vars, and the token server
answers `503` with the same guidance.

## Running with the LKY brain

Issue #6 swaps the skeleton's stock LLM for the self-hosted LKY brain — the
browser conversation is then answered *in the LKY persona* (still in a stock
voice until issue #8). The swap is pure configuration; no code changes.

### 1. Start the brain server

Follow [`services/brain_api/run_real.md`](services/brain_api/run_real.md):
the real engine (Qwen3-14B + epoch-2 adapter, 4-bit NF4) runs under WSL and
takes several minutes to load. Wait for `brain api ready` in its log, then
confirm from Windows:

```bash
curl -s http://127.0.0.1:8000/health   # model_loaded: true
```

(Keyless dry run without the GPU: start the brain with `BRAIN_ENGINE=fake`
instead — same endpoint, deterministic answers. See
[`services/brain_api/README.md`](services/brain_api/README.md).)

### 2. Flip three env vars

In your repo-root `.env`, replace the stock-LLM trio with the brain
(this exact block is also documented in `.env.example` under BRAIN MODE):

```dotenv
OPENAI_BASE_URL=http://127.0.0.1:8000/v1
OPENAI_API_KEY=local-development   # any value; the local seam doesn't authenticate
SKELETON_LLM_MODEL=lky
```

Optional persona knobs (defaults built in): `LKY_SIM_DATE=2026-07-13` sets
the simulated present day; `LKY_PROMPT_VARIANT=B` selects the time-traveler
framing variant (A = vendored persona prompt alone, B = + present-day
awareness / anti-fabrication sentence — issue #2's eval decides which
ships). `LKY_MAX_TOKENS=320` is the spoken-answer budget.

### 3. Run the agent as before

Restart the voice agent (`python agent.py dev`); token server and web client
are unchanged. What you should experience on top of the skeleton behavior:

- Answers come in LKY's persona — short spoken style (~2–5 sentences).
  Reality check: the real brain decodes at ~2–3 tok/s on the local GPU, so
  first audio takes noticeably longer than with a hosted LLM.
- Conversation history holds across turns within your session; if you
  interrupt him, only the words you actually heard are remembered.
- A second simultaneous visitor (e.g. a second browser tab while an answer
  is generating) politely hears/sees "LKY is speaking with someone — please
  wait." instead of degrading the live session — the status line shows the
  busy state.
- If the brain server is down, the agent says so and the page shows a clear
  error state instead of crashing.

## Running with the cloned voice

Issue #8 swaps the stock Deepgram voice for the cloned elder LKY voice
(blind-test winner: Chatterbox, issue #7). The voice runs as a small
loopback-only TTS server on the same GPU as the brain (placement is
measured-viable), and the agent selects it with one env var.

### 1. Start the brain server

As above — [`services/brain_api/run_real.md`](services/brain_api/run_real.md),
wait for `brain api ready`.

### 2. Start the TTS server

Follow [`services/tts_server/run_real.md`](services/tts_server/run_real.md)
(one-time dep install, then one launch command). Wait for `tts server ready`,
then confirm from Windows:

```bash
curl -s http://127.0.0.1:8100/health   # model_loaded: true, watermark: perth
```

### 3. Flip one env var

In your repo-root `.env` (with the BRAIN MODE block from the previous
section already active):

```dotenv
TTS_PROVIDER=chatterbox
```

Optional knobs: `LKY_TTS_SPEED=0.85` (delivery-speed factor; the engine
speaks faster than the real elder LKY, so <1 slows it toward his pace) and
`LKY_TTS_PRONUNCIATIONS=<path.json>` (extra pronunciation respellings on
top of the built-in Singapore-terms map).

### 4. Run the agent as before

Restart the voice agent. LKY now answers in the cloned elder voice; phrase
streaming (speech starts before the full answer is generated) and barge-in
(interruption cancels generation, the synthesis queue, and playback as one
operation) behave exactly as with the stock voice — both come from the same
LiveKit pipeline. If the TTS server dies mid-session the agent logs the
failures and the conversation continues (transcript keeps flowing); set
`TTS_PROVIDER=deepgram` and restart to fall back to the stock voice.

Every sample the cloned voice produces carries Chatterbox's built-in PerTh
audio watermark, and the TTS server binds 127.0.0.1 only — the agent is its
sole client, and the cloned voice is never exposed as a public endpoint.

### Tests

No real credentials needed:

```powershell
cd services/token_server; .venv\Scripts\python -m pytest -q; cd ../..
cd services/voice_agent;  .venv\Scripts\python -m pytest -q; cd ../..
cd web; npm run build; cd ..
```
