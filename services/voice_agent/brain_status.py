"""Brain-failure classification and status reporting values (issue #6).

The brain API is single-slot: a concurrent generation gets HTTP 429 with
``{"error": {"code": "busy", "message": "LKY is speaking with someone —
please wait."}}``. The agent must surface that politely (speak it, show it in
the transcript, flag it to the web client) instead of crashing or
retry-storming, and must do the same with a clear error when the brain is
unreachable.

This module holds the pure classification logic so it is unit-testable
without a LiveKit room: the agent's ``llm_node`` catches the plugin's
exception, asks :func:`classify_brain_error`, and speaks the returned
message.

Status is also published to the room on the ``lky.brain`` participant
attribute (``ok`` | ``busy`` | ``error``) so the web client can show a busy
banner / feed the avatar state machine's error state.
"""

from __future__ import annotations

from dataclasses import dataclass

from livekit.agents import APIConnectionError, APIError, APIStatusError

#: Participant attribute the agent publishes its brain status on.
STATUS_ATTRIBUTE = "lky.brain"
STATUS_OK = "ok"
STATUS_BUSY = "busy"
STATUS_ERROR = "error"

#: Fallback if a 429 arrives without the server's message (the brain's own
#: wording is preferred when present in the error body).
BUSY_MESSAGE = "LKY is speaking with someone — please wait."

#: Spoken/displayed when the brain cannot be reached or fails mid-answer.
UNREACHABLE_MESSAGE = (
    "I am sorry — I cannot reach my train of thought right now. "
    "Please give me a moment and try again."
)


@dataclass(frozen=True)
class BrainFailure:
    """What the agent should do about a failed brain request."""

    #: ``lky.brain`` attribute value: STATUS_BUSY or STATUS_ERROR.
    status: str
    #: The sentence to speak and show in the transcript.
    message: str


def _busy_message_from_body(body: object) -> str:
    """Prefer the server's own busy wording; fall back to BUSY_MESSAGE.

    Handles both body shapes seen at this seam: the raw response
    ``{"error": {"code": "busy", "message": ...}}`` and the openai SDK's
    unwrapped form (it passes ``body["error"]`` itself as the body).
    """
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message
    return BUSY_MESSAGE


def classify_brain_error(exc: BaseException) -> BrainFailure | None:
    """Map an LLM-plugin exception to the graceful handling it deserves.

    Returns ``None`` for anything that is not an API failure (programming
    errors, cancellation) — the caller must re-raise those untouched.
    """
    if isinstance(exc, APIStatusError):
        if exc.status_code == 429:
            return BrainFailure(STATUS_BUSY, _busy_message_from_body(exc.body))
        # 4xx/5xx other than busy: the brain answered but cannot serve.
        return BrainFailure(STATUS_ERROR, UNREACHABLE_MESSAGE)
    if isinstance(exc, APIConnectionError):
        # Connection refused / timed out — brain unreachable.
        return BrainFailure(STATUS_ERROR, UNREACHABLE_MESSAGE)
    if isinstance(exc, APIError):
        return BrainFailure(STATUS_ERROR, UNREACHABLE_MESSAGE)
    return None
