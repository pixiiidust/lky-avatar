# lky-avatar

A time-traveler LKY reasoning demo. You speak with a simulated elder Lee
Kuan Yew who is aware of the present day and answers modern questions from
his principles. An animated portrait avatar fronts the conversation, and
every session is honestly labeled as an AI-generated simulation.


https://github.com/user-attachments/assets/1d5e414c-2028-4b6a-abbc-724f847361d2
Sample Clip

Start with these docs:

- [`docs/spec.md`](docs/spec.md): the product definition
- [`docs/lky-avatar-plan.md`](docs/lky-avatar-plan.md): milestones
- [`docs/eval-process.md`](docs/eval-process.md): how the persona and
  serving stack are evaluated (question sets, judging rubric, prompt-variant
  history, benchmark baseline)

## Replicating this for your own persona

Everything LKY-specific plugs into a generic seam, so the same stack can
front a different persona:

- **Brain**: any OpenAI-compatible endpoint works (`OPENAI_BASE_URL`). This
  project serves its own QLoRA fine-tune; substitute a hosted model or your
  own fine-tune without code changes.
- **Voice**: `TTS_PROVIDER=deepgram` is fully stock. The cloned-voice path
  needs your own reference clips (never committed) and, optionally, your own
  fine-tune — the [lky-voice](https://github.com/pixiiidust/lky-voice) repo
  documents that pipeline end to end.
- **Facts**: point `LKY_FACT_SHEET` at your own audited fact sheet; the
  format is plain sectioned markdown.
- **Avatar**: drop your own portrait frames in `web/public/avatar/` or rig
  a Live2D model.

Performance numbers quoted in this README and in `docs/reports/` were
measured on the reference machine: Windows 11 + WSL2, RTX 5070 Ti (16 GB),
with brain and TTS sharing the one GPU. The runbooks (`run_real.md` files,
`docs/reports/serving-upgrade.md`) keep that machine's absolute paths as a
working record — adapt paths to your environment when following them.

## Running the walking skeleton

The walking skeleton (issue #4) is the full voice loop built from stock
parts: browser microphone → LiveKit → Deepgram STT → any OpenAI-compatible
LLM → Deepgram Aura TTS → browser playback. It supports interim transcripts
and barge-in.

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

# OPTIONAL: stock Live2D model (licensed Live2D sample; never committed).
# The default avatar is the bundled portrait sprite (web/public/avatar/).
# Fetch this only for the Live2D path (?renderer=live2d), which is kept
# for the #12 custom rig.
python scripts/fetch_placeholder_model.py
```

### 2. Configure keys

```powershell
copy .env.example .env
```

Fill in every `PLACEHOLDER_` value in `.env`. Each key's comment says
exactly where to obtain it (LiveKit Cloud project settings → Keys, Deepgram
console → API Keys, your LLM provider's key page). Never commit `.env`.

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

1. Click **Connect** and allow the microphone. The status shows
   "Connected — agent listening", and the agent greets you in a stock voice.
2. Speak. Your words appear as an *italic interim transcript while you are
   still talking*, then turn solid when final.
3. The agent answers out loud within a few seconds. Its transcript streams
   in as it speaks.
4. **Interrupt it mid-answer** by simply starting to talk. Playback stops
   almost immediately, and it listens to you again.
5. The AI-disclosure banner stays visible the whole time. It has been a
   spec requirement from day one.

The agent logs a per-turn latency line in Terminal 2:

`LATENCY turn <id>: end-of-speech -> first-audio = X.XXs (eou … + llm ttft … + tts ttfb …)`

This is the issue-#4 measurement: end-of-speech to first-audio with
all-stock parts.

If any key is missing or still a `PLACEHOLDER_` value, the agent refuses to
start and names the offending env vars. The token server answers `503` with
the same guidance.

## Running with the LKY brain

Issue #6 swaps the skeleton's stock LLM for the self-hosted LKY brain. The
browser conversation is then answered *in the LKY persona*. The swap is pure
configuration, with no code changes. Two interchangeable brain servers sit
behind the same OpenAI-compatible seam:

| Server | Port | Speed | Use |
|---|---|---|---|
| **llama.cpp, GGUF Q4_K_M** (production) | 8001 | **80.5 tok/s, TTFT 0.05 s** | live sessions, the demo |
| Transformers + PEFT, 4-bit NF4 | 8000 | 2.5 tok/s, TTFT 3.4 s | fallback + fake-engine test seam |

Numbers, method, parity evidence, and the GGUF regeneration runbook are in
[`docs/reports/serving-upgrade.md`](docs/reports/serving-upgrade.md).

### 1. Start a brain server

**Production (llama.cpp, native Windows, loads in ~4 s).** The launch
command is in
[`docs/reports/serving-upgrade.md`](docs/reports/serving-upgrade.md);
point `-m` at your own GGUF file (this project uses a Q4_K_M quant of its
fine-tuned 14B model). Confirm:

```bash
curl -s http://127.0.0.1:8001/health   # {"status":"ok"}
```

**Fallback (Transformers under WSL, loads in ~36 s).** Follow
[`services/brain_api/run_real.md`](services/brain_api/run_real.md), then
`curl -s http://127.0.0.1:8000/health`. For a keyless dry run without the
GPU, set `BRAIN_ENGINE=fake`. It serves the same endpoint with deterministic
answers ([`services/brain_api/README.md`](services/brain_api/README.md)).

### 2. Flip three env vars

In your repo-root `.env`, replace the stock-LLM trio with the brain. The
exact block is also documented in `.env.example` under BRAIN MODE:

```dotenv
OPENAI_BASE_URL=http://127.0.0.1:8001/v1   # or :8000 for the fallback server
OPENAI_API_KEY=local-development   # any value; the local seam doesn't authenticate
SKELETON_LLM_MODEL=lky
```

Optional persona knobs, with defaults built in:

- `LKY_SIM_DATE=2026-07-13` sets the simulated present day.
- `LKY_PROMPT_VARIANT=C` is the shipped time-traveler framing. Variant D is
  prompt v2 plus few-shot exemplars. Full history:
  [`docs/eval-process.md`](docs/eval-process.md).
- `LKY_MAX_TOKENS=320` is the spoken-answer budget.

### Fact grounding (on by default)

The persona fine-tune teaches style, not facts, and it will confidently
invent biography if left alone. Issue #45 added a grounding layer in the
agent: a deliberately minimal form of RAG (retrieval-augmented generation).
Retrieval is keyword scoring over the sections of one audited markdown
file. There are no embeddings and no vector store; the corpus is small
enough that determinism and hand-auditability win. Each turn, the agent
matches your question against the fact sheet
([`assets/persona/lky_facts.md`](assets/persona/lky_facts.md):
constituencies, offices, HDB/water/independence timelines, with sources).
The best-matching sections are injected into the context just before your
question, behind a "trust these dates over your memory" instruction and an
uncertainty guardrail. The brain server is untouched. Deepgram also gets a
Singapore proper-noun boost, so names like Toa Payoh transcribe correctly
on the way in.

Knobs:

- `LKY_FACT_SHEET`: path to the fact sheet. Defaults to the committed
  sheet. Set it to an empty string to disable grounding.
- `LKY_STT_KEYWORDS=<path.json>`: extra STT keyword boosts merged over the
  built-in Singapore list.

A fact-anchored eval subset measures the effect:
`evals/fact_grounding_questions.json` via
`scripts/run_timetravel_eval_http.py --questions-file ... --with-grounding`.

### 3. Run the agent as before

Restart the voice agent (`python agent.py dev`). The token server and web
client are unchanged. On top of the skeleton behavior you should see:

- Answers arrive in LKY's persona, in a short spoken style of roughly 2–5
  sentences. Replies feel immediate on the production llama-server. On the
  Transformers fallback, first audio takes noticeably longer. Measured
  numbers: [`docs/eval-process.md`](docs/eval-process.md) §2–3.
- Conversation history holds across turns within your session. If you
  interrupt him, only the words you actually heard are remembered.
- A second simultaneous visitor (for example, a second browser tab while an
  answer is generating) politely hears and sees "LKY is speaking with
  someone — please wait." The live session is not degraded, and the status
  line shows the busy state.
- If the brain server is down, the agent says so, and the page shows a
  clear error state instead of crashing.

## Running with the cloned voice

Issue #8 swaps the stock Deepgram voice for the cloned elder LKY voice. The
blind-test winner was Chatterbox (issue #7). Since 2026-07-15 the server
carries the **fine-tuned** version of that voice: a LoRA trained on his real
speech in the [lky-voice](https://github.com/pixiiidust/lky-voice) sister
repo. It won the eval gate
on an 18/20 operator blind listen and loads via the `LKY_TTS_T3` weights
overlay. Details:
[`docs/reports/tts-finetuned-integration.md`](docs/reports/tts-finetuned-integration.md).

The voice runs as a small loopback-only TTS server on the same GPU as the
brain. Placement is measured-viable. The agent selects the voice with one
env var.

### 1. Start the brain server

As above: production llama-server on 8001
([`docs/reports/serving-upgrade.md`](docs/reports/serving-upgrade.md)), or
the Transformers fallback per
[`services/brain_api/run_real.md`](services/brain_api/run_real.md).

### 2. Start the TTS server

Follow [`services/tts_server/run_real.md`](services/tts_server/run_real.md)
(one-time dep install, then one launch command). Wait for `tts server
ready`, then confirm from Windows:

```bash
curl -s http://127.0.0.1:8100/health   # model_loaded: true, watermark: perth
```

### 3. Flip one env var

In your repo-root `.env`, with the BRAIN MODE block from the previous
section already active:

```dotenv
TTS_PROVIDER=chatterbox
```

Optional knobs:

- `LKY_TTS_SPEED`: delivery-speed factor. **Default 1.0.** The fine-tuned
  voice paces itself at generation time, so no slowdown is needed. The old
  phase-vocoder slowdown also added echo and amplified accent drift; see
  [`docs/reports/voice-blind-test-results.md`](docs/reports/voice-blind-test-results.md).
- `LKY_TTS_REF`: reference clip. Default `elder_ref_04.wav`, the
  listening-round winner.
- `LKY_TTS_PRONUNCIATIONS=<path.json>`: extra pronunciation respellings on
  top of the built-in Singapore-terms map.

### 4. Run the agent as before

Restart the voice agent. LKY now answers in the cloned elder voice. Phrase
streaming and barge-in behave exactly as with the stock voice, because both
come from the same LiveKit pipeline. (Phrase streaming means speech starts
before the full answer is generated. Barge-in cancels generation, the
synthesis queue, and playback as one operation.)

If the TTS server dies mid-session, the interview drops to a degraded but
honest mode. The agent publishes `lky.tts=error`, and the page shows a
"Sound is down" slate in the studio's voice. His replies keep arriving as
text-only turns on the record. This needs explicit handling because the SDK
alone would produce a silent void: transcription output is synced to audio
playout, so a turn whose synthesis fails emits neither sound nor text. The
agent re-delivers the reply text itself; see `LKYAgent.tts_node`. Once the
TTS server is back, the next answer speaks again, `lky.tts` returns to
`ok`, and the slate clears with no restart needed. To fall back to the
stock voice for the rest of the session, set `TTS_PROVIDER=deepgram` and
restart.

Every sample the cloned voice produces carries Chatterbox's built-in PerTh
audio watermark. The TTS server binds `127.0.0.1` only. The agent is its
sole client, and the cloned voice is never exposed as a public endpoint.

### Tests

No real credentials needed:

```powershell
cd services/token_server; .venv\Scripts\python -m pytest -q; cd ../..
cd services/voice_agent;  .venv\Scripts\python -m pytest -q; cd ../..
cd web; npm run build; cd ..
```

## Hard-won lessons

Real-time voice AI looks like a model problem but is mostly a systems
problem. [`docs/faq.md`](docs/faq.md) walks through the problems this
project actually hit and how each was solved: the 10-second replies, the
interruptions that didn't interrupt, the echoey clone, and where the
latency actually lives.
