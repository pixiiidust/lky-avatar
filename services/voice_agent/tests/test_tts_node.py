"""LKYAgent.tts_node behavior (issue #13): a dead voice server degrades to a
text-only transcript turn + published ``lky.tts`` status instead of the
silent void, and everything else passes through untouched.

Stubs replace the SDK's synthesis pipeline (``_default_tts_node``) and the
session — no network, no LiveKit room. The SDK behaviors these tests lean on
(what the pipeline does with a zero-frame tts_node, why text-only ``say``
provably reaches the visitor) are documented with source references on the
agent methods themselves.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from livekit.agents import APIConnectionError

from agent import LKYAgent
from tts_status import TTS_STATUS_ERROR, TTS_STATUS_OK

FRAME_A = object()  # tts_node passes frames through opaquely
FRAME_B = object()


async def _chunks(*texts: str) -> AsyncIterator[str]:
    for text in texts:
        yield text


def _agent(statuses: list[str] | None = None) -> LKYAgent:
    async def report(status: str) -> None:
        if statuses is not None:
            statuses.append(status)

    return LKYAgent(instructions="test", report_tts_status=report)


def _fake_node(*, frames=(), consume: int | None = None, exc=None):
    """A stand-in for the SDK pipeline: read some input, yield, maybe die.

    ``consume`` mimics the real sentence-tokenizer pipeline reading input
    ahead of synthesis (None = drain everything, N = die after N chunks —
    the LLM is still streaming when the TTS connection is refused).
    """

    async def node(text, model_settings):
        read = 0
        async for _chunk in text:
            read += 1
            if consume is not None and read >= consume:
                break
        for frame in frames:
            yield frame
        if exc is not None:
            raise exc

    return node


def _run_tts_node(agent: LKYAgent, node, *texts: str) -> list:
    agent._default_tts_node = node  # type: ignore[method-assign]

    async def collect():
        out = []
        async for frame in agent.tts_node(_chunks(*texts), None):
            out.append(frame)
        return out

    return asyncio.run(collect())


def test_successful_synthesis_passes_frames_and_reports_ok_once():
    statuses: list[str] = []
    agent = _agent(statuses)
    out = _run_tts_node(
        agent, _fake_node(frames=(FRAME_A, FRAME_B)), "Nothing ", "is free."
    )
    assert out == [FRAME_A, FRAME_B]
    assert statuses == [TTS_STATUS_OK]  # once, on the first frame
    assert agent._text_only_tasks == set()  # no fallback scheduled


def test_dead_tts_yields_no_audio_and_schedules_the_full_reply_as_text():
    statuses: list[str] = []
    delivered: list[str] = []
    agent = _agent(statuses)
    agent._schedule_text_only_reply = delivered.append  # type: ignore[method-assign]

    # The connection is refused after the pipeline read only the first
    # sentence; the rest of the reply is still streaming from the LLM.
    out = _run_tts_node(
        agent,
        _fake_node(consume=1, exc=APIConnectionError()),
        "Nothing is free. ",
        "Somebody pays — ",
        "the question is who.",
    )
    assert out == []  # generator ends cleanly: the turn completes, no crash
    assert statuses == [TTS_STATUS_ERROR]
    # The fallback carries the WHOLE reply, including chunks that arrived
    # after the failure.
    assert delivered == [
        "Nothing is free. Somebody pays — the question is who."
    ]


def test_mid_reply_failure_after_audio_does_not_redeliver_text():
    # Audio reached the speakers, then the server died: the SDK's transcript
    # synchronizer flushes the remaining text itself on playback-finished
    # (synchronizer.py, _playback_completed) — re-delivering would duplicate
    # the reply in the record and in history.
    statuses: list[str] = []
    delivered: list[str] = []
    agent = _agent(statuses)
    agent._schedule_text_only_reply = delivered.append  # type: ignore[method-assign]

    out = _run_tts_node(
        agent,
        _fake_node(frames=(FRAME_A,), exc=APIConnectionError()),
        "Nothing is free.",
    )
    assert out == [FRAME_A]
    assert statuses == [TTS_STATUS_OK, TTS_STATUS_ERROR]  # outage still flagged
    assert delivered == []


def test_whitespace_only_reply_schedules_nothing():
    delivered: list[str] = []
    agent = _agent()
    agent._schedule_text_only_reply = delivered.append  # type: ignore[method-assign]
    out = _run_tts_node(
        agent, _fake_node(exc=APIConnectionError()), "  ", "\n"
    )
    assert out == []
    assert delivered == []


def test_programming_errors_are_not_swallowed():
    statuses: list[str] = []
    with pytest.raises(ValueError):
        _run_tts_node(_agent(statuses), _fake_node(exc=ValueError("bug")))
    assert statuses == []


def test_status_reporter_failure_never_breaks_the_audio():
    async def broken_report(status: str) -> None:
        raise RuntimeError("attributes not available")

    agent = LKYAgent(instructions="test", report_tts_status=broken_report)
    out = _run_tts_node(agent, _fake_node(frames=(FRAME_A,)), "text")
    assert out == [FRAME_A]


# --- the text-only delivery path (_say_text_only) --------------------------


class _FakeHandle:
    async def wait_for_playout(self) -> None:
        return None


class _FakeSession:
    """Records the exact ordering of output toggles and say() calls."""

    def __init__(self, say_exc: Exception | None = None) -> None:
        self.events: list[object] = []
        self._say_exc = say_exc
        outer = self

        class _Output:
            def set_audio_enabled(self, enabled: bool) -> None:
                outer.events.append(("audio", enabled))

        self.output = _Output()

    def say(self, text: str) -> _FakeHandle:
        self.events.append(("say", text))
        if self._say_exc is not None:
            raise self._say_exc
        return _FakeHandle()


def _run_say_text_only(
    monkeypatch: pytest.MonkeyPatch, session: _FakeSession, reply: str
) -> None:
    monkeypatch.setattr(LKYAgent, "session", property(lambda self: session))
    asyncio.run(_agent()._say_text_only(reply))


def test_text_only_delivery_disables_audio_around_the_say(monkeypatch):
    session = _FakeSession()
    _run_say_text_only(monkeypatch, session, "Somebody pays.")
    # Audio must be OFF before say() (that is what flips the transcript
    # synchronizer to passthrough and makes _tts_task_impl skip synthesis)
    # and back ON afterwards.
    assert session.events == [
        ("audio", False),
        ("say", "Somebody pays."),
        ("audio", True),
    ]


def test_text_only_delivery_reenables_audio_even_when_say_fails(monkeypatch):
    session = _FakeSession(say_exc=RuntimeError("session closing"))
    _run_say_text_only(monkeypatch, session, "Somebody pays.")  # must not raise
    assert session.events == [
        ("audio", False),
        ("say", "Somebody pays."),
        ("audio", True),
    ]
