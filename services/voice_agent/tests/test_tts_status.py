"""TTS-failure classification (issue #13): service failures of the voice
server degrade to text-only delivery; programming errors and cancellation
must re-raise. Constructed with the exact exceptions the TTS pipeline
raises (providers/tts.py + the SDK's ChunkedStream) — no network, no room."""

import asyncio

import pytest
from livekit.agents import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
)

from tts_status import (
    TTS_STATUS_ATTRIBUTE,
    TTS_STATUS_ERROR,
    TTS_STATUS_OK,
    classify_tts_error,
)


def test_connection_refused_is_error():
    # The fault-injection case: TTS server process killed, POST refused.
    failure = classify_tts_error(APIConnectionError())
    assert failure is not None
    assert failure.status == TTS_STATUS_ERROR


def test_timeout_is_error():
    failure = classify_tts_error(APITimeoutError())
    assert failure.status == TTS_STATUS_ERROR


@pytest.mark.parametrize("status_code", [500, 503, 400])
def test_http_failures_are_error(status_code):
    failure = classify_tts_error(
        APIStatusError("boom", status_code=status_code)
    )
    assert failure.status == TTS_STATUS_ERROR


def test_adapter_api_error_is_error():
    # providers/tts.py raises a bare APIError on a sample-rate mismatch.
    failure = classify_tts_error(APIError("sample rate mismatch"))
    assert failure.status == TTS_STATUS_ERROR


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("bug"),
        RuntimeError("bug"),
        KeyError("bug"),
        asyncio.CancelledError(),
        GeneratorExit(),
    ],
)
def test_non_api_errors_are_not_swallowed(exc):
    # Cancellation/GeneratorExit never reach the classifier in practice
    # (tts_node catches Exception only), but the pure contract holds anyway.
    assert classify_tts_error(exc) is None


def test_attribute_contract_matches_the_web_client():
    # main.ts watches this attribute for the voice-down slate.
    assert TTS_STATUS_ATTRIBUTE == "lky.tts"
    assert TTS_STATUS_OK == "ok"
    assert TTS_STATUS_ERROR == "error"
