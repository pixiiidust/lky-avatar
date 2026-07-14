"""End-to-end through the official ``openai`` Python package against a live
local server — exactly how LiveKit's openai plugin consumes this API in
issue #6 (OPENAI_BASE_URL pointed at this server)."""

from __future__ import annotations

from openai import OpenAI

MESSAGES = [
    {"role": "system", "content": "You are Lee Kuan Yew."},
    {"role": "user", "content": "What do you make of artificial intelligence?"},
]


def _client(server) -> OpenAI:
    # Any api_key works: the local seam does not authenticate (it is only
    # reachable by the agent; hosting hardening is issue #13).
    return OpenAI(base_url=server.base_url + "/v1", api_key="local-development")


def test_openai_client_streams_end_to_end(server):
    client = _client(server)
    stream = client.chat.completions.create(
        model="lky", messages=MESSAGES, stream=True
    )
    pieces: list[str] = []
    finish_reasons: list[str] = []
    for chunk in stream:
        assert chunk.model == "lky"
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            pieces.append(delta.content)
        if chunk.choices[0].finish_reason:
            finish_reasons.append(chunk.choices[0].finish_reason)
    assert "".join(pieces) == server.engine.full_text
    assert finish_reasons == ["stop"]


def test_openai_client_stream_with_usage(server):
    client = _client(server)
    stream = client.chat.completions.create(
        model="lky",
        messages=MESSAGES,
        stream=True,
        stream_options={"include_usage": True},
    )
    usage = None
    for chunk in stream:
        if chunk.usage is not None:
            usage = chunk.usage
    assert usage is not None and usage.total_tokens > 0


def test_openai_client_non_streaming(server):
    client = _client(server)
    completion = client.chat.completions.create(
        model="lky", messages=MESSAGES, stream=False
    )
    assert completion.choices[0].message.content == server.engine.full_text
    assert completion.choices[0].finish_reason == "stop"
    assert completion.usage.total_tokens > 0


def test_openai_client_models_list(server):
    client = _client(server)
    models = client.models.list()
    assert [m.id for m in models.data] == ["lky"]
