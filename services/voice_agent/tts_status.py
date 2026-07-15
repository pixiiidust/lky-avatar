"""TTS-failure classification and status reporting values (issue #13).

Live fault injection (2026-07-14, TTS server killed mid-session) showed the
worst kind of failure: a visitor turn produced NOTHING. No audio (expected),
but also no transcript and no error indication — because livekit-agents 1.6.5
synchronizes the room transcript to audio playout, a speech turn whose TTS
raises never emits its text (see the SDK-evidence comments on
``LKYAgent.tts_node`` in agent.py).

This module holds the pure, unit-testable half of the fix, mirroring
brain_status.py:

- :func:`classify_tts_error` decides whether an exception out of the TTS
  pipeline is a service failure the agent should degrade around (deliver the
  reply as text, flag the outage) or a programming error to re-raise.
- The ``lky.tts`` participant attribute (``ok`` | ``error``) tells the web
  client to show/clear its "voice unavailable — replies continue as text"
  slate, exactly as ``lky.brain`` drives the busy/error slates.

Unlike the brain seam there is no "busy" state: the TTS server is loopback,
single-client, and either serves or it doesn't.
"""

from __future__ import annotations

from dataclasses import dataclass

from livekit.agents import APIError

#: Participant attribute the agent publishes its voice (TTS) status on.
TTS_STATUS_ATTRIBUTE = "lky.tts"
TTS_STATUS_OK = "ok"
TTS_STATUS_ERROR = "error"


@dataclass(frozen=True)
class TtsFailure:
    """What the agent should do about a failed synthesis."""

    #: ``lky.tts`` attribute value: TTS_STATUS_ERROR (no busy state here).
    status: str


def classify_tts_error(exc: BaseException) -> TtsFailure | None:
    """Map a TTS-pipeline exception to the graceful handling it deserves.

    The whole ``APIError`` family counts as an outage of the voice, not of
    the conversation: connection refused / timed out (server down — the
    fault-injection case), HTTP failure statuses (server up but broken), and
    the adapter's own APIError for mis-rated audio (providers/tts.py). All
    of them leave the reply text perfectly deliverable.

    Returns ``None`` for anything else (programming errors, cancellation) —
    the caller must re-raise those untouched.
    """
    if isinstance(exc, APIError):
        return TtsFailure(TTS_STATUS_ERROR)
    return None
