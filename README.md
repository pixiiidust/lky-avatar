# lky-avatar

A time-traveler LKY reasoning demo: speak with a simulated elder Lee Kuan Yew —
present-day aware, answering modern questions from his principles — voiced and
fronted by a Live2D avatar, honestly labeled as an AI-generated simulation.

See [`docs/spec.md`](docs/spec.md) for the product definition and
[`docs/lky-avatar-plan.md`](docs/lky-avatar-plan.md) for milestones.

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

### Tests

No real credentials needed:

```powershell
cd services/token_server; .venv\Scripts\python -m pytest -q; cd ../..
cd services/voice_agent;  .venv\Scripts\python -m pytest -q; cd ../..
cd web; npm run build; cd ..
```
