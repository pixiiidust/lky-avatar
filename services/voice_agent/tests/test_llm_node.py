"""LKYAgent.llm_node behavior (issue #6): the busy-429 and unreachable paths
turn brain failures into a spoken message + published status instead of a
crashed turn, and everything else passes through untouched.

Uses a stub LLM in place of the plugin — no network, no LiveKit room.
"""

from __future__ import annotations

import asyncio

import pytest
from livekit.agents import APIConnectionError, APIStatusError, llm as llm_types

from agent import LKYAgent
from brain_status import (
    BUSY_MESSAGE,
    STATUS_BUSY,
    STATUS_ERROR,
    STATUS_OK,
    UNREACHABLE_MESSAGE,
)

BUSY_EXC = APIStatusError(
    "busy",
    status_code=429,
    body={"error": {"code": "busy", "message": BUSY_MESSAGE}},
)


def _chunk(text: str) -> llm_types.ChatChunk:
    return llm_types.ChatChunk(
        id="chunk", delta=llm_types.ChoiceDelta(role="assistant", content=text)
    )


class _StubStream:
    """Async-context-manager + async-iterator, like the plugin's LLMStream."""

    def __init__(self, chunks, exc=None):
        self._chunks = list(chunks)
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for chunk in self._chunks:
            yield chunk
        if self._exc is not None:
            raise self._exc


class _StubLLM(llm_types.LLM):
    def __init__(self, chunks=(), exc=None):
        super().__init__()
        self._chunks = chunks
        self._exc = exc

    def chat(self, **kwargs):  # signature compatible enough for llm_node
        return _StubStream(self._chunks, self._exc)


class _StubActivity:
    def __init__(self, llm):
        self.llm = llm


def _run_llm_node(agent: LKYAgent, stub: _StubLLM) -> list:
    agent._get_activity_or_raise = lambda: _StubActivity(stub)  # type: ignore[method-assign]

    async def collect():
        out = []
        async for item in agent.llm_node(
            chat_ctx=llm_types.ChatContext.empty(), tools=[], model_settings=None
        ):
            out.append(item)
        return out

    return asyncio.run(collect())


def _agent(statuses: list[str]) -> LKYAgent:
    async def report(status: str) -> None:
        statuses.append(status)

    return LKYAgent(instructions="test instructions", report_status=report)


def test_busy_429_is_spoken_not_raised():
    statuses: list[str] = []
    out = _run_llm_node(_agent(statuses), _StubLLM(exc=BUSY_EXC))
    assert out == [BUSY_MESSAGE]  # yielded => spoken + shown in transcript
    assert statuses == [STATUS_BUSY]  # web client's busy banner


def test_unreachable_brain_is_spoken_error_state():
    statuses: list[str] = []
    out = _run_llm_node(_agent(statuses), _StubLLM(exc=APIConnectionError()))
    assert out == [UNREACHABLE_MESSAGE]
    assert statuses == [STATUS_ERROR]


def test_successful_stream_passes_chunks_through_and_reports_ok():
    statuses: list[str] = []
    chunks = [_chunk("Nothing "), _chunk("is free.")]
    out = _run_llm_node(_agent(statuses), _StubLLM(chunks=chunks))
    assert out == chunks
    assert statuses == [STATUS_OK]  # once, on first chunk


def test_mid_stream_failure_appends_message_after_partial_answer():
    statuses: list[str] = []
    chunks = [_chunk("Nothing ")]
    out = _run_llm_node(
        _agent(statuses), _StubLLM(chunks=chunks, exc=APIConnectionError())
    )
    assert out == chunks + [UNREACHABLE_MESSAGE]
    assert statuses == [STATUS_OK, STATUS_ERROR]


def test_programming_errors_are_not_swallowed():
    statuses: list[str] = []
    with pytest.raises(ValueError):
        _run_llm_node(_agent(statuses), _StubLLM(exc=ValueError("bug")))
    assert statuses == []


def test_status_reporter_failure_never_breaks_the_answer():
    async def broken_report(status: str) -> None:
        raise RuntimeError("attributes not available")

    agent = LKYAgent(instructions="test", report_status=broken_report)
    out = _run_llm_node(agent, _StubLLM(exc=BUSY_EXC))
    assert out == [BUSY_MESSAGE]
