"""Integration (issue #6): the agent's LLM path against a REAL brain server.

Runs the brain_api service as a subprocess with ``BRAIN_ENGINE=fake`` — a
real uvicorn HTTP server behind the exact OpenAI-compatible seam the real
engine sits behind — and exercises the agent's configured LLM plugin
(``agent.build_llm``) against it, without a LiveKit room:

- persona-framed streaming answer arrives incrementally and completely
- a concurrent request surfaces as the polite 429 busy state, immediately
  (no retry-storm)
- dropping the stream mid-answer (what LiveKit does on barge-in) frees the
  brain's single generation slot within ~a second

Requires the brain_api venv (services/brain_api/.venv); skips with
instructions if it is missing. No GPU, no credentials.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from livekit.agents import APIStatusError
from livekit.agents.llm import ChatContext

from agent import BRAIN_CONN_OPTIONS, build_llm
from brain_status import STATUS_BUSY, classify_brain_error
from config import AgentConfig
from persona_prompt import build_instructions

REPO_ROOT = Path(__file__).resolve().parents[3]
BRAIN_DIR = REPO_ROOT / "services" / "brain_api"

#: 36 words at 100 ms/piece ≈ 3.6 s per full answer — long enough that the
#: busy and cancellation tests have a comfortable window to act in.
FAKE_TEXT = (
    "The fundamentals do not change with the technology. Artificial"
    " intelligence is a tool, and like every tool it rewards societies with"
    " discipline and education and punishes those without. We must adapt"
    " quickly or be left behind entirely."
)
FAKE_DELAY_MS = 100

SERVER_BUSY_MESSAGE = "LKY is speaking with someone — please wait."


def _brain_python() -> Path:
    win = BRAIN_DIR / ".venv" / "Scripts" / "python.exe"
    posix = BRAIN_DIR / ".venv" / "bin" / "python"
    return win if win.exists() else posix


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read())


@pytest.fixture(scope="module")
def brain_server():
    """A fake-engine brain_api server in a subprocess; yields its base URL."""
    python = _brain_python()
    if not python.exists():
        pytest.skip(
            "brain_api venv missing — create it first: cd services/brain_api"
            " && python -m venv .venv && .venv/Scripts/python -m pip install"
            " -r requirements.txt"
        )
    port = _free_port()
    env = {
        **os.environ,
        "BRAIN_ENGINE": "fake",
        "BRAIN_FAKE_TEXT": FAKE_TEXT,
        "BRAIN_FAKE_DELAY_MS": str(FAKE_DELAY_MS),
    }
    proc = subprocess.Popen(
        [
            str(python), "-m", "uvicorn", "app:app",
            "--host", "127.0.0.1", "--port", str(port),
            "--log-level", "warning",
        ],
        cwd=str(BRAIN_DIR),
        env=env,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 30
        while True:
            if proc.poll() is not None:
                raise RuntimeError("brain server subprocess died on startup")
            try:
                health = _get_json(base_url + "/health")
                if health.get("model_loaded"):
                    break
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            if time.time() > deadline:
                raise RuntimeError("brain server did not become healthy")
            time.sleep(0.1)
        yield base_url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def _config(base_url: str) -> AgentConfig:
    """The exact three-var brain swap from .env.example, as env config."""
    return AgentConfig.from_env(
        {
            "LIVEKIT_URL": "wss://demo-project.livekit.cloud",
            "LIVEKIT_API_KEY": "APIabc123",
            "LIVEKIT_API_SECRET": "secretsecretsecretsecret",
            "DEEPGRAM_API_KEY": "dgkey123",
            # the swap:
            "OPENAI_BASE_URL": base_url + "/v1",
            "OPENAI_API_KEY": "local-development",
            "SKELETON_LLM_MODEL": "lky",
        }
    )


def _chat_ctx(cfg: AgentConfig, question: str) -> ChatContext:
    ctx = ChatContext.empty()
    ctx.add_message(
        role="system",
        content=build_instructions(cfg.lky_sim_date, cfg.lky_prompt_variant),
    )
    ctx.add_message(role="user", content=question)
    return ctx


def test_persona_framed_answer_streams_completely(brain_server):
    cfg = _config(brain_server)

    async def run() -> list[str]:
        llm = build_llm(cfg)
        pieces: list[str] = []
        async with llm.chat(
            chat_ctx=_chat_ctx(cfg, "What do you make of AI?"),
            conn_options=BRAIN_CONN_OPTIONS,
        ) as stream:
            async for chunk in stream:
                if chunk.delta and chunk.delta.content:
                    pieces.append(chunk.delta.content)
        return pieces

    pieces = asyncio.run(run())
    assert "".join(pieces) == FAKE_TEXT  # complete, uncorrupted answer
    assert len(pieces) > 5  # arrived incrementally, not one blob


def test_concurrent_request_gets_polite_busy_without_retry_storm(brain_server):
    cfg = _config(brain_server)

    async def run():
        llm1 = build_llm(cfg)
        llm2 = build_llm(cfg)
        stream1 = llm1.chat(
            chat_ctx=_chat_ctx(cfg, "First visitor's question."),
            conn_options=BRAIN_CONN_OPTIONS,
        )
        it = stream1.__aiter__()
        # Wait until the first visitor's generation holds the slot.
        while True:
            chunk = await it.__anext__()
            if chunk.delta and chunk.delta.content:
                break
        started = time.monotonic()
        with pytest.raises(APIStatusError) as excinfo:
            async with llm2.chat(
                chat_ctx=_chat_ctx(cfg, "Second visitor's question."),
                conn_options=BRAIN_CONN_OPTIONS,
            ) as stream2:
                async for _ in stream2:
                    pass
        elapsed = time.monotonic() - started
        await stream1.aclose()
        return excinfo.value, elapsed

    exc, elapsed = asyncio.run(run())
    assert exc.status_code == 429
    # This exception is exactly what LKYAgent.llm_node catches and turns
    # into the spoken busy message:
    failure = classify_brain_error(exc)
    assert failure is not None
    assert failure.status == STATUS_BUSY
    assert failure.message == SERVER_BUSY_MESSAGE
    # max_retry=0: surfaced immediately, no retry-storm against the slot.
    assert elapsed < 5


def test_dropping_the_stream_frees_the_slot_within_a_second(brain_server):
    cfg = _config(brain_server)

    async def run() -> None:
        llm = build_llm(cfg)
        stream = llm.chat(
            chat_ctx=_chat_ctx(cfg, "A question that gets barged into."),
            conn_options=BRAIN_CONN_OPTIONS,
        )
        got = 0
        async for chunk in stream:
            if chunk.delta and chunk.delta.content:
                got += 1
                if got >= 2:
                    break  # barge-in: abandon the stream mid-answer
        await stream.aclose()

    asyncio.run(run())

    # The server must notice the disconnect and free its single slot fast.
    deadline = time.time() + 3
    health = _get_json(brain_server + "/health")
    while health["generation_in_flight"] and time.time() < deadline:
        time.sleep(0.1)
        health = _get_json(brain_server + "/health")
    assert health["generation_in_flight"] is False
