"""Busy/unreachable classification (issue #6): the 429-busy path and the
brain-unreachable path, unit-tested by constructing the exact exceptions the
LiveKit openai plugin raises. No network, no room."""

import pytest
from livekit.agents import APIConnectionError, APIStatusError, APITimeoutError

from brain_status import (
    BUSY_MESSAGE,
    STATUS_BUSY,
    STATUS_ERROR,
    UNREACHABLE_MESSAGE,
    classify_brain_error,
)

#: The brain server's exact 429 body (services/brain_api README / app.py).
BUSY_BODY = {
    "error": {
        "code": "busy",
        "message": "LKY is speaking with someone — please wait.",
        "type": "rate_limit_error",
    }
}


def test_429_with_server_body_is_busy_and_uses_server_wording():
    exc = APIStatusError("busy", status_code=429, body=BUSY_BODY)
    failure = classify_brain_error(exc)
    assert failure is not None
    assert failure.status == STATUS_BUSY
    assert failure.message == "LKY is speaking with someone — please wait."


def test_429_with_openai_sdk_unwrapped_body_uses_server_wording():
    # The openai SDK unwraps the top-level {"error": ...} envelope before it
    # reaches the plugin's exception; both shapes must work.
    exc = APIStatusError("busy", status_code=429, body=BUSY_BODY["error"])
    failure = classify_brain_error(exc)
    assert failure.status == STATUS_BUSY
    assert failure.message == "LKY is speaking with someone — please wait."


def test_429_without_body_falls_back_to_default_busy_message():
    failure = classify_brain_error(APIStatusError("busy", status_code=429))
    assert failure.status == STATUS_BUSY
    assert failure.message == BUSY_MESSAGE


@pytest.mark.parametrize(
    "body", [None, {}, {"error": "busy"}, {"error": {"message": ""}}]
)
def test_429_with_unusable_body_shapes_still_polite(body):
    failure = classify_brain_error(
        APIStatusError("busy", status_code=429, body=body)
    )
    assert failure.status == STATUS_BUSY
    assert failure.message == BUSY_MESSAGE


@pytest.mark.parametrize("status_code", [400, 500, 503])
def test_non_busy_http_errors_are_error_state(status_code):
    failure = classify_brain_error(
        APIStatusError("boom", status_code=status_code)
    )
    assert failure.status == STATUS_ERROR
    assert failure.message == UNREACHABLE_MESSAGE


def test_connection_refused_is_error_state():
    failure = classify_brain_error(APIConnectionError())
    assert failure.status == STATUS_ERROR
    assert failure.message == UNREACHABLE_MESSAGE


def test_timeout_is_error_state():
    failure = classify_brain_error(APITimeoutError())
    assert failure.status == STATUS_ERROR


@pytest.mark.parametrize(
    "exc", [ValueError("bug"), RuntimeError("bug"), KeyError("bug")]
)
def test_non_api_errors_are_not_swallowed(exc):
    assert classify_brain_error(exc) is None
