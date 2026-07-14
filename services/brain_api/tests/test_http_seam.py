"""Seam-1 tests: brain API behavior as seen by an HTTP client, FakeEngine
behind the endpoint (spec Testing Decisions). Covers: incremental SSE
streaming ending in [DONE], non-stream completions, disconnect cancellation,
the single-generation 429 guard, the max_tokens hard cap, locked sampling
defaults, truthful /health before/during/after generation, and /v1/models.
"""

from __future__ import annotations

import json
import time

import httpx

from config import DEFAULT_MAX_TOKENS, MAX_TOKENS_HARD_CAP
from lky_avatar import persona

CHAT = "/v1/chat/completions"


def _chat_body(**overrides) -> dict:
    body = {
        "model": "lky",
        "messages": [
            {"role": "system", "content": "You are Lee Kuan Yew."},
            {"role": "user", "content": "What do you make of AI?"},
        ],
    }
    body.update(overrides)
    return body


def _stream_events(response) -> tuple[list[str], list[float]]:
    """Collect SSE data payloads and their arrival times."""
    events, times = [], []
    for line in response.iter_lines():
        if line.startswith("data: "):
            events.append(line[len("data: "):])
            times.append(time.perf_counter())
    return events, times


def _wait_for(predicate, timeout=5.0, interval=0.02) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


# ── streaming ────────────────────────────────────────────────────────────────


def test_streaming_chunks_arrive_incrementally_and_end_with_done(make_server):
    srv = make_server(delay_s=0.02)
    with httpx.Client(timeout=30) as client:
        with client.stream(
            "POST", srv.base_url + CHAT, json=_chat_body(stream=True)
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith(
                "text/event-stream"
            )
            events, times = _stream_events(response)

    assert events[-1] == "[DONE]"
    payloads = [json.loads(event) for event in events[:-1]]
    assert all(p["object"] == "chat.completion.chunk" for p in payloads)
    assert all(p["model"] == "lky" for p in payloads)
    # one id per completion, chatcmpl-prefixed
    assert len({p["id"] for p in payloads}) == 1
    assert payloads[0]["id"].startswith("chatcmpl-")
    # first chunk announces the assistant role; last carries finish_reason
    assert payloads[0]["choices"][0]["delta"]["role"] == "assistant"
    assert payloads[-1]["choices"][0]["finish_reason"] == "stop"
    assert all(
        p["choices"][0]["finish_reason"] is None for p in payloads[:-1]
    )
    # reassembled deltas equal the engine's deterministic text
    content = "".join(
        p["choices"][0]["delta"].get("content") or "" for p in payloads
    )
    assert content == srv.engine.full_text
    # incremental arrival, not one buffered blob: the content chunks span
    # real wall time (>= half the engine's total inter-piece delay)
    n_pieces = len(payloads) - 2  # minus role chunk and finish chunk
    assert n_pieces > 3
    assert times[-2] - times[0] >= 0.5 * n_pieces * 0.02 * 0.5


def test_stream_options_include_usage_appends_usage_chunk(server):
    body = _chat_body(stream=True, stream_options={"include_usage": True})
    with httpx.Client(timeout=30) as client:
        with client.stream(
            "POST", server.base_url + CHAT, json=body
        ) as response:
            events, _ = _stream_events(response)
    assert events[-1] == "[DONE]"
    usage_payload = json.loads(events[-2])
    assert usage_payload["choices"] == []
    assert usage_payload["usage"]["completion_tokens"] > 0
    assert usage_payload["usage"]["total_tokens"] > 0


# ── non-streaming ────────────────────────────────────────────────────────────


def test_non_streaming_completion(server):
    response = httpx.post(
        server.base_url + CHAT, json=_chat_body(stream=False), timeout=30
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "chat.completion"
    assert payload["model"] == "lky"
    assert payload["id"].startswith("chatcmpl-")
    choice = payload["choices"][0]
    assert choice["message"]["role"] == "assistant"
    assert choice["message"]["content"] == server.engine.full_text
    assert choice["finish_reason"] == "stop"
    assert payload["usage"]["total_tokens"] > 0
    assert response.headers["x-request-id"].startswith("chatcmpl-")


# ── cancellation on client disconnect ────────────────────────────────────────


def test_client_disconnect_cancels_generation(make_server):
    # ~10 s of stream if run to completion; we bail out after a few chunks.
    srv = make_server(text=" ".join(["word"] * 200), delay_s=0.05)
    with httpx.Client(timeout=30) as client:
        with client.stream(
            "POST", srv.base_url + CHAT, json=_chat_body(stream=True)
        ) as response:
            received = 0
            lines = response.iter_lines()
            for line in lines:
                if line.startswith("data: "):
                    received += 1
                if received >= 3:
                    break
            # leaving the context closes the partially-read response,
            # which closes the connection: the client disconnect

    engine = srv.engine
    assert _wait_for(lambda: engine.cancelled and not engine.active), (
        f"engine not cancelled after disconnect: cancelled={engine.cancelled} "
        f"active={engine.active}"
    )
    assert engine.streams_started == 1
    assert engine.streams_finished == 1
    assert engine.last_finish_reason == "cancelled"
    # the busy slot was freed: health is truthful and a new request works
    assert _wait_for(
        lambda: httpx.get(srv.base_url + "/health").json()[
            "generation_in_flight"
        ]
        is False
    )
    retry = httpx.post(
        srv.base_url + CHAT,
        json=_chat_body(stream=False, max_tokens=4),
        timeout=30,
    )
    assert retry.status_code == 200


# ── single-generation guard ──────────────────────────────────────────────────


def test_concurrent_request_rejected_with_429(make_server):
    srv = make_server(text=" ".join(["word"] * 100), delay_s=0.03)
    with httpx.Client(timeout=30) as client:
        with client.stream(
            "POST", srv.base_url + CHAT, json=_chat_body(stream=True)
        ) as response:
            # Wait until generation has demonstrably started. NB: the
            # iterator must stay referenced — discarding it mid-iteration
            # closes the connection, which this server treats as a client
            # disconnect (and rightly cancels the generation).
            lines = response.iter_lines()
            for line in lines:
                if line.startswith("data: "):
                    break

            second = httpx.post(
                srv.base_url + CHAT, json=_chat_body(stream=False), timeout=10
            )
            assert second.status_code == 429
            error = second.json()["error"]
            assert error["code"] == "busy"
            assert "please wait" in error["message"]

            # health is truthful DURING generation
            health = httpx.get(srv.base_url + "/health").json()
            assert health["generation_in_flight"] is True
            assert health["model_loaded"] is True

    # after the client abandons the stream the slot frees up again
    assert _wait_for(
        lambda: httpx.get(srv.base_url + "/health").json()[
            "generation_in_flight"
        ]
        is False
    )
    third = httpx.post(
        srv.base_url + CHAT,
        json=_chat_body(stream=False, max_tokens=4),
        timeout=30,
    )
    assert third.status_code == 200


# ── validation: max_tokens cap and bad requests ──────────────────────────────


def test_max_tokens_above_hard_cap_rejected_400(server):
    response = httpx.post(
        server.base_url + CHAT,
        json=_chat_body(max_tokens=MAX_TOKENS_HARD_CAP + 1),
        timeout=10,
    )
    assert response.status_code == 400
    message = response.json()["error"]["message"]
    assert str(MAX_TOKENS_HARD_CAP) in message
    # engine never touched
    assert server.engine.streams_started == 0


def test_max_completion_tokens_alias_also_capped(server):
    response = httpx.post(
        server.base_url + CHAT,
        json=_chat_body(max_completion_tokens=4096),
        timeout=10,
    )
    assert response.status_code == 400


def test_max_tokens_at_cap_accepted(server):
    response = httpx.post(
        server.base_url + CHAT,
        json=_chat_body(max_tokens=MAX_TOKENS_HARD_CAP),
        timeout=30,
    )
    assert response.status_code == 200


def test_empty_messages_rejected_400(server):
    response = httpx.post(
        server.base_url + CHAT, json=_chat_body(messages=[]), timeout=10
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_messages"


# ── locked sampling defaults ─────────────────────────────────────────────────


def test_sampling_defaults_applied_when_omitted(server):
    httpx.post(server.base_url + CHAT, json=_chat_body(), timeout=30)
    request = server.engine.last_request
    assert request is not None
    assert request.temperature == persona.TEMPERATURE == 0.7
    assert request.top_p == persona.TOP_P == 0.9
    assert request.repetition_penalty == persona.REPETITION_PENALTY == 1.1
    assert request.max_tokens == DEFAULT_MAX_TOKENS == 320


def test_explicit_sampling_values_honored(server):
    httpx.post(
        server.base_url + CHAT,
        json=_chat_body(temperature=0.2, top_p=0.5, max_tokens=64),
        timeout=30,
    )
    request = server.engine.last_request
    assert request.temperature == 0.2
    assert request.top_p == 0.5
    assert request.max_tokens == 64
    # repetition_penalty is not an OpenAI field: always the locked value
    assert request.repetition_penalty == persona.REPETITION_PENALTY


# ── health and models ────────────────────────────────────────────────────────


def test_health_truthful_before_during_after_generation(make_server):
    srv = make_server(text=" ".join(["word"] * 100), delay_s=0.03)

    # before: loaded (startup completed), idle
    before = httpx.get(srv.base_url + "/health").json()
    assert before["status"] == "ok"
    assert before["engine"] == "fake"
    assert before["model_loaded"] is True
    assert before["generation_in_flight"] is False
    assert before["vram_allocated_gib"] is None  # truthful for the fake

    # during: in flight
    seen_in_flight = {}

    def probe():
        seen_in_flight["health"] = httpx.get(srv.base_url + "/health").json()

    with httpx.Client(timeout=30) as client:
        with client.stream(
            "POST", srv.base_url + CHAT, json=_chat_body(stream=True)
        ) as response:
            lines = response.iter_lines()  # keep referenced: see 429 test
            for line in lines:
                if line.startswith("data: "):
                    break
            probe()
    assert seen_in_flight["health"]["generation_in_flight"] is True
    assert seen_in_flight["health"]["model_loaded"] is True

    # after: idle again, same instance (no restart)
    assert _wait_for(
        lambda: httpx.get(srv.base_url + "/health").json()[
            "generation_in_flight"
        ]
        is False
    )
    after = httpx.get(srv.base_url + "/health").json()
    assert after["instance_id"] == before["instance_id"]
    assert after["model_loaded"] is True


def test_models_endpoint_lists_lky(server):
    response = httpx.get(server.base_url + "/v1/models", timeout=10)
    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "list"
    assert len(payload["data"]) == 1
    assert payload["data"][0]["id"] == "lky"
    assert payload["data"][0]["object"] == "model"
