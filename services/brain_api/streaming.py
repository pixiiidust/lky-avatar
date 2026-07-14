"""OpenAI chat-completions wire format (JSON payloads + SSE framing).

Pure functions, no I/O — everything the OpenAI Python client (and LiveKit's
openai plugin, which wraps it) needs to parse our responses:

- non-stream: one ``chat.completion`` object
- stream: ``chat.completion.chunk`` objects as ``data: {...}\\n\\n`` SSE
  events, terminated by ``data: [DONE]\\n\\n``
"""

from __future__ import annotations

import json
import uuid

DONE_EVENT = "data: [DONE]\n\n"


def new_completion_id() -> str:
    return "chatcmpl-" + uuid.uuid4().hex[:24]


def sse(payload: dict) -> str:
    """Frame one JSON payload as a Server-Sent Event."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _estimate_tokens(text: str) -> int:
    """Crude ~4-chars/token estimate; engines don't expose exact counts at
    this seam and no consumer of this API makes billing decisions on usage."""
    return max(1, len(text) // 4) if text else 0


def usage_payload(prompt_text: str, completion_text: str) -> dict:
    prompt = _estimate_tokens(prompt_text)
    completion = _estimate_tokens(completion_text)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def chunk(
    completion_id: str,
    model: str,
    created: int,
    delta: dict,
    finish_reason: str | None = None,
) -> dict:
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {"index": 0, "delta": delta, "finish_reason": finish_reason}
        ],
    }


def usage_chunk(
    completion_id: str, model: str, created: int, usage: dict
) -> dict:
    """Final extra chunk when the client asked for
    ``stream_options: {"include_usage": true}`` (the OpenAI client and
    LiveKit's plugin request this for metrics); its ``choices`` is empty."""
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [],
        "usage": usage,
    }


def completion(
    completion_id: str,
    model: str,
    created: int,
    content: str,
    finish_reason: str,
    usage: dict,
) -> dict:
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage,
    }
