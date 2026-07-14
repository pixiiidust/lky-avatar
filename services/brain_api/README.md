# brain_api — OpenAI-compatible streaming server (issue #5)

LKY answering over HTTP: a long-running server that loads Qwen3-14B + the
epoch-2 adapter **once** and exposes an OpenAI-compatible chat-completions
endpoint with SSE streaming and mid-stream cancellation. This contract is the
hosting-portability boundary and the spec's **primary test seam** — issue #6
points the LiveKit agent's `OPENAI_BASE_URL` at this server and nothing
downstream changes.

## Endpoints

| Endpoint | Behavior |
|---|---|
| `POST /v1/chat/completions` | OpenAI chat completions. `stream: true` → SSE `chat.completion.chunk` events ending in `data: [DONE]` (supports `stream_options: {"include_usage": true}`); `stream: false` → one `chat.completion` object. Client disconnect mid-stream cancels generation and frees GPU resources. |
| `GET /health` | Truthful status: `model_loaded`, `generation_in_flight`, `instance_id` (changes on restart — the 20-turn check uses it), `uptime_s`, `vram_allocated_gib` (null off-GPU). |
| `GET /v1/models` | Lists the single model, `lky`. |

Guard rails, enforced server-side:

- **Locked sampling** (from `lky_avatar/persona.py`, do not change without a
  new eval): temperature 0.7, top_p 0.9, repetition_penalty 1.1 (always — not
  an OpenAI field), `enable_thinking=false` via the chat template. Client
  `temperature` / `top_p` / `max_tokens` are honored when provided.
- **`max_tokens` hard cap 1024** → 400 above it; default 320 (`LKY_MAX_TOKENS`),
  the voice-friendly ~2–5-sentence length.
- **One generation at a time** → concurrent request gets **429** with
  `{"error": {"code": "busy", "message": "LKY is speaking with someone — please wait."}}`
  (issue #6 surfaces this as the busy state).
- **Privacy**: request ids and timing (TTFT, pieces/s) are logged; message and
  completion content is **never** logged unless `BRAIN_LOG_CONTENT=1`.

## Engine seam

`engine.py` defines the `Engine` protocol with two implementations:

- **`FakeEngine`** (`BRAIN_ENGINE=fake`) — deterministic token stream with a
  configurable delay; exposes its lifecycle state so tests can verify (from
  the HTTP side) that a disconnect really cancelled generation. **All tests
  run against this**, per the spec's testing decisions: real-model runs are
  verification, not CI.
- **`TransformersEngine`** (`BRAIN_ENGINE=transformers`, the default) —
  Qwen3-14B 4-bit NF4 + epoch-2 PEFT adapter, plain Transformers + PEFT (no
  Unsloth at inference), `TextIteratorStreamer` streaming, cancellation via a
  `StoppingCriteria` flag + `torch.cuda.empty_cache()`. CUDA only — run under
  WSL, see [`run_real.md`](run_real.md).

## Performance reality (measured 2026-07-13)

NF4 decode on the RTX 5070 Ti (torch 2.12 / bitsandbytes) runs at roughly
**2–3 tok/s** with ~10.5 GiB allocated — inherent to quantized decode on this
stack, not a config bug (`use_cache` is pinned on regardless; a post-warmup
soft check warns if VRAM exceeds `LKY_VRAM_WARN_GIB`, default 12). The server
is therefore streaming-first: the first SSE chunk leaves the moment the first
tokens exist, and every request logs TTFT and pieces/s so issues #6/#11 tune
against numbers.

Known follow-ups for faster serving — out of scope for issue #5, do not build
here: merged-LoRA GGUF via llama.cpp, or vLLM (the plan's hosted Profile B).

## Configuration (env; see repo-root `.env.example`)

| Var | Default | Meaning |
|---|---|---|
| `BRAIN_ENGINE` | `transformers` | `transformers` or `fake` |
| `LKY_MODEL_NAME` | `lky` | model id served |
| `LKY_BASE_MODEL` | `Qwen/Qwen3-14B` | HF base model |
| `LKY_ADAPTER` | `sjsim/lky-qlora` | adapter: HF id or local path |
| `LKY_MAX_TOKENS` | `320` | default `max_tokens` when omitted |
| `LKY_VRAM_WARN_GIB` | `12` | post-warmup soft VRAM warning |
| `BRAIN_HOST` / `BRAIN_PORT` | `0.0.0.0` / `8000` | bind address |
| `BRAIN_FAKE_TEXT` / `BRAIN_FAKE_DELAY_MS` | built-in / `5` | FakeEngine tuning |
| `BRAIN_LOG_CONTENT` | off | log message content (debugging only) |

## Develop and test (Windows, no GPU)

```bash
cd services/brain_api
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pytest tests -v
```

The tests start a real uvicorn server on a random port with an injected
FakeEngine and exercise it as HTTP clients — including through the official
`openai` Python package, exactly how LiveKit's plugin consumes it. Run a
fake-engine server manually:

```bash
BRAIN_ENGINE=fake .venv/Scripts/python -m uvicorn app:app --port 8000
```

## Run with the real model

See [`run_real.md`](run_real.md) — WSL launch command and the GPU
verification checklist (curl streaming, mid-stream cancellation,
`scripts/brain_20turn_check.py`, VRAM stability).
