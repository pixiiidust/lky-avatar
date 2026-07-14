"""Cloned-voice TTS provider behavior (issue #8), tested at the seams:

- provider selection logic (TTS_PROVIDER env -> which TTS the agent builds)
- the ChatterboxTTS adapter's HTTP request/response handling, against a
  local fake HTTP server (no GPU, no real TTS, no LiveKit room)
- speed + pronunciation plumbing into the request payload

The SDK's phrase streaming / interruption handling is NOT re-tested here —
that is livekit-agents' own StreamAdapter machinery (pinned by the SDK; see
providers/tts.py docstring) and spec-level "not unit-tested by design".
"""

from __future__ import annotations

import asyncio

import aiohttp
import pytest
from aiohttp import web
from livekit.agents import APIConnectionError, APIError, APIStatusError
from livekit.agents.types import APIConnectOptions

from config import (
    DEFAULT_TTS_BASE_URL,
    DEFAULT_TTS_SPEED,
    AgentConfig,
    select_tts_provider,
)
from pronunciation import PronunciationMap
from providers.tts import SAMPLE_RATE, ChatterboxTTS

NO_RETRY = APIConnectOptions(max_retry=0, timeout=5.0)

#: 4800 samples of s16le silence = exactly 0.2s at 24kHz.
FAKE_PCM = b"\x00\x00" * 4800


def _base_env() -> dict[str, str]:
    return {
        "LIVEKIT_URL": "wss://x", "LIVEKIT_API_KEY": "k",
        "LIVEKIT_API_SECRET": "s", "DEEPGRAM_API_KEY": "d",
        "OPENAI_API_KEY": "o",
    }


class TestProviderSelection:
    def test_default_is_deepgram(self):
        assert select_tts_provider("") == "deepgram"
        assert AgentConfig.from_env(_base_env()).tts_provider == "deepgram"

    def test_chatterbox_selected(self):
        env = _base_env() | {"TTS_PROVIDER": "chatterbox"}
        assert AgentConfig.from_env(env).tts_provider == "chatterbox"

    def test_case_and_whitespace_insensitive(self):
        assert select_tts_provider("  Chatterbox ") == "chatterbox"
        assert select_tts_provider("DEEPGRAM") == "deepgram"

    def test_unknown_value_falls_back_to_deepgram(self):
        # a typo must never leave a session with a dead TTS
        assert select_tts_provider("eleven-labs") == "deepgram"

    def test_url_and_speed_defaults_and_overrides(self):
        config = AgentConfig.from_env(_base_env())
        assert config.tts_base_url == DEFAULT_TTS_BASE_URL
        assert config.tts_speed == DEFAULT_TTS_SPEED
        env = _base_env() | {
            "LKY_TTS_URL": "http://127.0.0.1:9000",
            "LKY_TTS_SPEED": "0.9",
            "LKY_TTS_PRONUNCIATIONS": "extra.json",
        }
        config = AgentConfig.from_env(env)
        assert config.tts_base_url == "http://127.0.0.1:9000"
        assert config.tts_speed == 0.9
        assert config.tts_pronunciations_path == "extra.json"

    def test_unusable_speed_falls_back(self):
        env = _base_env() | {"LKY_TTS_SPEED": "fast"}
        assert AgentConfig.from_env(env).tts_speed == DEFAULT_TTS_SPEED

    def test_build_tts_returns_the_selected_provider(self):
        from agent import build_tts

        chatter = build_tts(
            AgentConfig.from_env(
                _base_env()
                | {"TTS_PROVIDER": "chatterbox", "LKY_TTS_SPEED": "0.9"}
            )
        )
        assert isinstance(chatter, ChatterboxTTS)
        assert chatter.speed == 0.9
        assert chatter.base_url == DEFAULT_TTS_BASE_URL

        stock = build_tts(AgentConfig.from_env(_base_env()))
        assert not isinstance(stock, ChatterboxTTS)
        assert type(stock).__module__.startswith("livekit.plugins.deepgram")


# --- adapter request/response handling, against a fake HTTP server ---------

async def _start_fake_server(handler) -> tuple[web.AppRunner, str]:
    app = web.Application()
    app.router.add_post("/synthesize", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][:2]
    return runner, f"http://{host}:{port}"


async def _synthesize_once(handler, text: str, **tts_kwargs):
    """Run one synthesize() against a fake server; return (events, error)."""
    runner, base_url = await _start_fake_server(handler)
    events, error = [], None
    try:
        async with aiohttp.ClientSession() as session:
            tts_client = ChatterboxTTS(
                base_url=base_url, http_session=session, **tts_kwargs
            )
            try:
                async with tts_client.synthesize(text, conn_options=NO_RETRY) as st:
                    async for ev in st:
                        events.append(ev)
            except Exception as exc:  # noqa: BLE001 - the assertion target
                error = exc
    finally:
        await runner.cleanup()
    return events, error


def _pcm_handler(captured: list[dict]):
    async def handler(request: web.Request) -> web.Response:
        captured.append(await request.json())
        return web.Response(
            body=FAKE_PCM,
            content_type="audio/pcm",
            headers={"X-Sample-Rate": str(SAMPLE_RATE)},
        )

    return handler


class TestAdapter:
    def test_happy_path_streams_pcm_frames(self):
        captured: list[dict] = []
        events, error = asyncio.run(
            _synthesize_once(_pcm_handler(captured), "Good evening.", speed=0.9)
        )
        assert error is None
        assert events, "no audio events emitted"
        assert events[-1].is_final
        total_samples = sum(ev.frame.samples_per_channel for ev in events)
        assert total_samples == 4800  # every PCM byte arrived, none invented
        assert all(ev.frame.sample_rate == SAMPLE_RATE for ev in events)
        assert all(ev.frame.num_channels == 1 for ev in events)

    def test_request_payload_speed_and_format(self):
        captured: list[dict] = []
        asyncio.run(
            _synthesize_once(_pcm_handler(captured), "Good evening.", speed=0.9)
        )
        assert captured == [
            {"text": "Good evening.", "format": "pcm", "speed": 0.9}
        ]

    def test_speed_none_omits_key(self):
        """No speed configured -> the server's own default applies."""
        captured: list[dict] = []
        asyncio.run(_synthesize_once(_pcm_handler(captured), "Hello."))
        assert captured and "speed" not in captured[0]

    def test_pronunciations_applied_to_request_text_only(self):
        captured: list[dict] = []
        asyncio.run(
            _synthesize_once(
                _pcm_handler(captured),
                "The PAP built HDB flats.",
                pronunciations=PronunciationMap(),
            )
        )
        assert captured[0]["text"] == "The P. A. P. built H. D. B. flats."

    def test_http_error_raises_api_status_error(self):
        async def failing(request: web.Request) -> web.Response:
            return web.Response(status=500, text="boom")

        events, error = asyncio.run(_synthesize_once(failing, "Hello."))
        assert not events
        assert isinstance(error, APIStatusError)
        assert error.status_code == 500

    def test_unreachable_server_raises_api_connection_error(self):
        async def run() -> Exception | None:
            async with aiohttp.ClientSession() as session:
                # nothing listens on this port (bind-then-close)
                tts_client = ChatterboxTTS(
                    base_url="http://127.0.0.1:9", http_session=session
                )
                try:
                    async with tts_client.synthesize("x", conn_options=NO_RETRY) as st:
                        async for _ in st:
                            pass
                except Exception as exc:  # noqa: BLE001
                    return exc
            return None

        error = asyncio.run(run())
        assert isinstance(error, APIConnectionError)

    def test_sample_rate_mismatch_is_rejected(self):
        async def wrong_rate(request: web.Request) -> web.Response:
            return web.Response(
                body=FAKE_PCM,
                content_type="audio/pcm",
                headers={"X-Sample-Rate": "44100"},
            )

        events, error = asyncio.run(_synthesize_once(wrong_rate, "Hello."))
        assert isinstance(error, APIError)
        assert "44100" in str(error)

    def test_declares_non_streaming_so_sdk_wraps_it(self):
        """streaming=False is what makes Agent.default.tts_node wrap this
        adapter in the SDK's StreamAdapter (sentence-by-sentence synthesis,
        atomic cancellation) — pin it so a refactor can't silently lose the
        phrase-streaming behavior."""
        tts_client = ChatterboxTTS()
        assert tts_client.capabilities.streaming is False
        assert tts_client.sample_rate == 24_000
        assert tts_client.num_channels == 1
