# brain_api

OpenAI-compatible streaming server for the LKY brain (issue #5). Will hold
`app.py`, `engine.py`, `streaming.py`, `config.py` per plan §6.

Contract: `POST /v1/chat/completions` (SSE streaming), `GET /health`,
`GET /v1/models`. Qwen3-14B + epoch-2 LoRA, 4-bit NF4, plain
Transformers + PEFT — no Unsloth at inference. One generation at a time.

Runs in its own venv (`.venv/`, gitignored); GPU work runs under WSL.
