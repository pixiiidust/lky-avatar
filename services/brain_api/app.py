"""OpenAI-compatible streaming server for the LKY brain (issue #5).

The HTTP contract — the hosting-portability boundary and the spec's PRIMARY
test seam:

- ``POST /v1/chat/completions`` — OpenAI chat completions; ``stream`` true
  (SSE chunks ending in ``data: [DONE]``) or false. Locked sampling defaults
  (persona.py) applied server-side when the client omits them; ``max_tokens``
  above the hard cap rejected with 400; a second concurrent generation
  rejected with 429 (the busy state issue #6 surfaces). Client disconnect
  mid-stream cancels generation and frees GPU resources.
- ``GET /health`` — truthful: engine, model loaded?, generation in flight?,
  instance id (detects restarts), uptime, VRAM allocated.
- ``GET /v1/models`` — lists the single model, ``lky``.

Privacy: request ids and timing (TTFT, pieces/s) are logged; message and
completion CONTENT is never logged unless BRAIN_LOG_CONTENT=1.

Run (tests / no GPU):   BRAIN_ENGINE=fake uvicorn app:app --port 8000
Run (real model, WSL):  see run_real.md
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

import streaming
from config import MAX_TOKENS_HARD_CAP, BrainConfig, _REPO_ROOT
from engine import FINISH_CANCELLED, Engine, GenerationRequest, create_engine

try:  # optional: pick up repo-root .env like the other services do
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env")
except ImportError:  # pragma: no cover - dotenv is in requirements.txt
    pass

logger = logging.getLogger("brain_api")

BUSY_MESSAGE = "LKY is speaking with someone — please wait."


# ── request schema ───────────────────────────────────────────────────────────
# extra="ignore" everywhere: OpenAI clients send fields we don't implement
# (n, tools, logprobs, ...); a strict schema would break real clients.


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str
    content: str | list | None = None


class StreamOptions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    include_usage: bool = False


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str | None = None
    messages: list[ChatMessage] = []
    stream: bool = False
    stream_options: StreamOptions | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    #: newer OpenAI clients send this instead of max_tokens
    max_completion_tokens: int | None = None


def _content_to_text(content: str | list | None) -> str:
    """Normalize OpenAI message content (plain string or content-part list)
    to text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            parts.append(str(part.get("text", "")))
    return "".join(parts)


def _error_response(
    status: int, message: str, err_type: str, code: str
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "message": message,
                "type": err_type,
                "param": None,
                "code": code,
            }
        },
    )


# ── app factory ──────────────────────────────────────────────────────────────


def create_app(
    config: BrainConfig | None = None, engine_obj: Engine | None = None
) -> FastAPI:
    """Build the server. ``engine_obj`` lets tests inject a FakeEngine
    directly; otherwise the engine comes from config (BRAIN_ENGINE)."""
    cfg = config or BrainConfig.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        eng = engine_obj if engine_obj is not None else create_engine(cfg)
        if not eng.loaded:
            logger.info("loading engine %r ...", eng.name)
            # The real model takes minutes to load; do it once, off the
            # event loop, before the server starts accepting requests.
            await asyncio.to_thread(eng.load)
        app.state.engine = eng
        logger.info(
            "brain api ready: engine=%s model=%s instance=%s",
            eng.name,
            cfg.model_name,
            app.state.instance_id,
        )
        yield
        eng.cancel()  # stop any in-flight generation on shutdown

    app = FastAPI(title="lky-brain-api", lifespan=lifespan)
    app.state.config = cfg
    app.state.instance_id = uuid.uuid4().hex
    app.state.started_at = time.time()
    # Single-generation guard (spec: one active generation; 16 GB card).
    # threading.Lock: acquire(blocking=False) is atomic and shares state
    # with the engine's worker threads.
    app.state.busy = threading.Lock()

    # ── endpoints ────────────────────────────────────────────────────────

    @app.get("/health")
    async def health() -> dict:
        eng: Engine | None = getattr(app.state, "engine", None)
        loaded = bool(eng is not None and eng.loaded)
        return {
            "status": "ok" if loaded else "loading",
            "engine": eng.name if eng is not None else cfg.engine,
            "model": cfg.model_name,
            "model_loaded": loaded,
            "generation_in_flight": app.state.busy.locked(),
            "instance_id": app.state.instance_id,
            "uptime_s": round(time.time() - app.state.started_at, 1),
            "vram_allocated_gib": (
                round(v, 2)
                if eng is not None and (v := eng.vram_allocated_gib()) is not None
                else None
            ),
        }

    @app.get("/v1/models")
    async def list_models() -> dict:
        return {
            "object": "list",
            "data": [
                {
                    "id": cfg.model_name,
                    "object": "model",
                    "created": int(app.state.started_at),
                    "owned_by": "lky-avatar",
                }
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request, body: ChatCompletionRequest):
        eng: Engine = app.state.engine
        request_id = streaming.new_completion_id()
        created = int(time.time())

        # ── validation (400s before the busy guard) ──
        requested_max = (
            body.max_tokens
            if body.max_tokens is not None
            else body.max_completion_tokens
        )
        if requested_max is not None and requested_max > MAX_TOKENS_HARD_CAP:
            return _error_response(
                400,
                f"max_tokens={requested_max} exceeds this server's hard cap "
                f"of {MAX_TOKENS_HARD_CAP}. Spoken answers default to "
                f"{cfg.default_max_tokens} tokens.",
                "invalid_request_error",
                "max_tokens_exceeded",
            )
        if requested_max is not None and requested_max < 1:
            return _error_response(
                400,
                "max_tokens must be a positive integer.",
                "invalid_request_error",
                "invalid_max_tokens",
            )
        if not body.messages:
            return _error_response(
                400,
                "messages must be a non-empty list.",
                "invalid_request_error",
                "invalid_messages",
            )

        messages = tuple(
            {"role": m.role, "content": _content_to_text(m.content)}
            for m in body.messages
        )
        # Locked sampling defaults (persona.py) applied server-side when the
        # client omits a knob; repetition_penalty is not an OpenAI field and
        # is ALWAYS the locked value.
        gen_request = GenerationRequest(
            messages=messages,
            temperature=(
                body.temperature
                if body.temperature is not None
                else app.state.sampling_defaults["temperature"]
            ),
            top_p=(
                body.top_p
                if body.top_p is not None
                else app.state.sampling_defaults["top_p"]
            ),
            repetition_penalty=app.state.sampling_defaults[
                "repetition_penalty"
            ],
            max_tokens=(
                requested_max
                if requested_max is not None
                else cfg.default_max_tokens
            ),
        )

        # ── single-generation guard ──
        if not app.state.busy.acquire(blocking=False):
            logger.info("request %s rejected: generation in flight", request_id)
            return _error_response(429, BUSY_MESSAGE, "busy", "busy")
        # From here on, app.state.busy MUST be released on every path.

        prompt_text = "".join(m["content"] for m in messages)
        log_ctx = {
            "rid": request_id,
            "t_start": time.perf_counter(),
            "messages": len(messages),
            "stream": body.stream,
        }
        logger.info(
            "request %s start: stream=%s messages=%d temp=%.2f top_p=%.2f "
            "max_tokens=%d",
            request_id,
            body.stream,
            len(messages),
            gen_request.temperature,
            gen_request.top_p,
            gen_request.max_tokens,
        )
        if cfg.log_content:
            logger.info("request %s content: %r", request_id, messages)

        if body.stream:
            include_usage = bool(
                body.stream_options and body.stream_options.include_usage
            )
            return StreamingResponse(
                _sse_stream(
                    request,
                    app,
                    eng,
                    gen_request,
                    request_id,
                    created,
                    prompt_text,
                    include_usage,
                    log_ctx,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Request-ID": request_id,
                    "X-Accel-Buffering": "no",
                },
            )

        # ── non-streaming ──
        try:
            pieces = await asyncio.to_thread(
                lambda: list(eng.stream(gen_request))
            )
        except asyncio.CancelledError:
            eng.cancel()
            raise
        except Exception:
            logger.exception("request %s failed", request_id)
            return _error_response(
                500, "generation failed", "server_error", "generation_failed"
            )
        finally:
            app.state.busy.release()
        content = "".join(pieces)
        finish = eng.last_finish_reason or "stop"
        if finish == FINISH_CANCELLED:
            finish = "stop"
        _log_finish(log_ctx, pieces_count=len(pieces), finish=finish)
        if cfg.log_content:
            logger.info("request %s completion: %r", request_id, content)
        payload = streaming.completion(
            request_id,
            cfg.model_name,
            created,
            content,
            finish,
            streaming.usage_payload(prompt_text, content),
        )
        return JSONResponse(payload, headers={"X-Request-ID": request_id})

    # Locked sampling defaults, resolved once (persona is the single source
    # of truth; enable_thinking is a chat-template knob used by the engine).
    from lky_avatar import persona

    app.state.sampling_defaults = {
        "temperature": persona.TEMPERATURE,
        "top_p": persona.TOP_P,
        "repetition_penalty": persona.REPETITION_PENALTY,
    }

    return app


def _log_finish(
    log_ctx: dict,
    pieces_count: int,
    finish: str,
    first_piece_at: float | None = None,
) -> None:
    """Per-request timing: TTFT and pieces/s are the numbers issues #6/#11
    tune against (measured NF4 decode here is single-digit tok/s)."""
    now = time.perf_counter()
    total_s = now - log_ctx["t_start"]
    ttft_s = (
        first_piece_at - log_ctx["t_start"] if first_piece_at is not None else None
    )
    rate = pieces_count / (now - first_piece_at) if first_piece_at and now > first_piece_at else None
    logger.info(
        "request %s finish=%s pieces=%d total=%.2fs ttft=%s pieces_per_s=%s",
        log_ctx["rid"],
        finish,
        pieces_count,
        total_s,
        f"{ttft_s:.2f}s" if ttft_s is not None else "n/a",
        f"{rate:.1f}" if rate is not None else "n/a",
    )


async def _sse_stream(
    request: Request,
    app: FastAPI,
    eng: Engine,
    gen_request: GenerationRequest,
    request_id: str,
    created: int,
    prompt_text: str,
    include_usage: bool,
    log_ctx: dict,
) -> AsyncIterator[str]:
    """Pump the engine's blocking iterator from a worker thread into SSE.

    Streaming-first: each piece is framed and flushed the moment it exists —
    at real NF4 decode speed (~2-3 tok/s) the first chunk must not wait for
    anything. Client disconnect cancels the Starlette task; the ``finally``
    then cancels the engine (which frees VRAM) and releases the busy slot.
    """
    cfg: BrainConfig = app.state.config
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    def _pump() -> None:
        try:
            for piece in eng.stream(gen_request):
                loop.call_soon_threadsafe(queue.put_nowait, piece)
        except BaseException as exc:  # surfaced on the SSE side
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, sentinel)

    worker = threading.Thread(
        target=_pump, name=f"pump-{request_id}", daemon=True
    )
    completed = False
    pieces_count = 0
    first_piece_at: float | None = None
    content_parts: list[str] = []
    try:
        worker.start()
        # OpenAI convention: first chunk carries the assistant role.
        yield streaming.sse(
            streaming.chunk(
                request_id,
                cfg.model_name,
                created,
                {"role": "assistant", "content": ""},
            )
        )
        failed = False
        while True:
            item = await queue.get()
            if item is sentinel:
                break
            if isinstance(item, BaseException):
                logger.error(
                    "request %s generation error: %r", log_ctx["rid"], item
                )
                yield streaming.sse(
                    {
                        "error": {
                            "message": "generation failed",
                            "type": "server_error",
                            "code": "generation_failed",
                        }
                    }
                )
                failed = True
                continue  # drain until sentinel
            if first_piece_at is None:
                first_piece_at = time.perf_counter()
            pieces_count += 1
            content_parts.append(item)
            yield streaming.sse(
                streaming.chunk(
                    request_id, cfg.model_name, created, {"content": item}
                )
            )
        if not failed:
            finish = eng.last_finish_reason or "stop"
            if finish == FINISH_CANCELLED:
                finish = "stop"
            yield streaming.sse(
                streaming.chunk(
                    request_id, cfg.model_name, created, {}, finish_reason=finish
                )
            )
            if include_usage:
                yield streaming.sse(
                    streaming.usage_chunk(
                        request_id,
                        cfg.model_name,
                        created,
                        streaming.usage_payload(
                            prompt_text, "".join(content_parts)
                        ),
                    )
                )
        yield streaming.DONE_EVENT
        completed = True
    finally:
        if not completed:
            # Client went away (task cancelled) or we errored: stop the
            # engine so it aborts generation and frees GPU resources.
            eng.cancel()
        worker.join(timeout=30)
        app.state.busy.release()
        _log_finish(
            log_ctx,
            pieces_count=pieces_count,
            finish="disconnected" if not completed else (eng.last_finish_reason or "stop"),
            first_piece_at=first_piece_at,
        )
        if cfg.log_content and completed:
            logger.info(
                "request %s completion: %r",
                log_ctx["rid"],
                "".join(content_parts),
            )


app = create_app()


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    _cfg = BrainConfig.from_env()
    uvicorn.run(app, host=_cfg.host, port=_cfg.port)
