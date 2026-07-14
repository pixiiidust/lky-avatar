"""Fixtures: a real uvicorn server (random port, background thread) wrapping
the app with an injected FakeEngine.

The spec's Seam 1 says brain behavior is tested *as an HTTP client*; a live
server (rather than an in-process ASGI transport) is deliberate — it makes
client-disconnect cancellation, SSE incrementality, and the OpenAI-client
end-to-end test exercise the exact transport LiveKit's plugin will use.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import pytest
import uvicorn

from app import create_app
from config import ENGINE_FAKE, BrainConfig
from engine import FakeEngine

DEFAULT_TEST_TEXT = (
    "The fundamentals do not change: discipline, education, and the will "
    "to adapt decide whether a society thrives."
)


@dataclass
class RunningServer:
    base_url: str
    engine: FakeEngine
    _server: uvicorn.Server
    _thread: threading.Thread


def _start(app) -> tuple[uvicorn.Server, threading.Thread, str]:
    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="warning", lifespan="on"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("uvicorn test server failed to start")
        if not thread.is_alive():
            raise RuntimeError("uvicorn test server thread died")
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, thread, f"http://127.0.0.1:{port}"


@pytest.fixture
def make_server():
    """Factory: spin up a server with a FakeEngine tuned per test
    (text length / per-piece delay control the window each test needs)."""
    running: list[RunningServer] = []

    def _make(
        text: str = DEFAULT_TEST_TEXT, delay_s: float = 0.01
    ) -> RunningServer:
        engine = FakeEngine(text=text, delay_s=delay_s)
        app = create_app(BrainConfig(engine=ENGINE_FAKE), engine_obj=engine)
        server, thread, base_url = _start(app)
        handle = RunningServer(base_url, engine, server, thread)
        running.append(handle)
        return handle

    yield _make

    for handle in running:
        handle._server.should_exit = True
    for handle in running:
        handle._thread.join(timeout=10)


@pytest.fixture
def server(make_server) -> RunningServer:
    """One server with the default deterministic FakeEngine."""
    return make_server()
