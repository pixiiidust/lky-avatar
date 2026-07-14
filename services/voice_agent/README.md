# voice_agent

LiveKit voice agent (issues #4 walking skeleton, #6 brain swap; #8 adds the
cloned voice). Pipeline: browser mic → LiveKit → Deepgram STT (interim
transcripts) → OpenAI-compatible LLM → Deepgram Aura TTS → browser, with
Silero VAD turn-taking and barge-in handled by the SDK.

## Modules

| File | Role |
|---|---|
| `agent.py` | The worker: `LKYAgent` (persona instructions + graceful brain busy/error handling in `llm_node`), session wiring, latency logging. `build_llm()` is the one LLM client — the brain swap seam. |
| `persona_prompt.py` | Pure prompt construction: vendored `lky_avatar.persona` base prompt + framing variant (`LKY_SIM_DATE`, `LKY_PROMPT_VARIANT`) + spoken-style policy. |
| `brain_status.py` | Pure classification of brain failures (429-busy vs unreachable) and the `lky.brain` participant-attribute values the web client watches. |
| `config.py` | Env-driven config; refuses placeholder credentials with a clear message. |
| `latency.py` | Per-turn end-of-speech → first-audio latency assembly (issue #4). |

## The brain swap (issue #6)

The LLM client is a generic OpenAI-compatible client; pointing it at the
self-hosted LKY brain is three env vars (see repo-root `README.md`,
"Running with the LKY brain", and the BRAIN MODE block in `.env.example`):

```dotenv
OPENAI_BASE_URL=http://127.0.0.1:8000/v1
OPENAI_API_KEY=local-development
SKELETON_LLM_MODEL=lky
```

Decisions encoded in `agent.py`:

- The **agent owns the persona prompt** (the brain server injects nothing).
- **No retries** against the brain (`max_retry=0`): a 429 means the single
  generation slot is held for potentially minutes — the agent speaks the
  polite busy message instead. Brain-unreachable is spoken too and published
  as `lky.brain=error` for the web client's avatar error state.
- **History keeps only heard text**: on barge-in, livekit-agents stores the
  transcript-synchronizer's played-text prefix (verified against 1.6.5
  source; pinned by `tests/test_history_retention.py`).
- **Interruption = dropping the HTTP stream**; the brain server cancels
  generation and frees its slot (~1 s) — covered by the integration test.

## Test

```bash
cd services/voice_agent
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pytest tests -v
```

No LiveKit/Deepgram keys and no GPU needed. `tests/test_brain_integration.py`
starts the brain_api service (subprocess, `BRAIN_ENGINE=fake`) and drives the
agent's configured LLM plugin against it over real HTTP — the exact seam the
real engine sits behind; it skips (with instructions) if
`services/brain_api/.venv` hasn't been created.
