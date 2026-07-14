"""HTTP-level tests for the token endpoint, with dummy credentials in env.

Issue #13 seams: the LiveKit room directory (single-session occupancy) is a
fake injected via ``app.directory_factory``; the per-IP rate limiter is
replaced per-test so tests neither share buckets nor sleep.
"""

import jwt
import pytest
from fastapi.testclient import TestClient

import app as app_module
from occupancy import ParticipantSnapshot, RoomSnapshot
from rate_limit import RateLimiter

DUMMY_URL = "wss://demo-project.livekit.cloud"
DUMMY_KEY = "APIdummykey123"
DUMMY_SECRET = "dummy-secret-dummy-secret-dummy-secret"


class FakeDirectory:
    """In-memory RoomDirectory: {room name: [(identity, is_agent), ...]}."""

    def __init__(self, rooms: dict[str, list[tuple[str, bool]]] | None = None):
        self.rooms = rooms or {}

    async def list_rooms(self):
        return [RoomSnapshot(name, len(p)) for name, p in self.rooms.items()]

    async def list_participants(self, room):
        return [ParticipantSnapshot(i, a) for i, a in self.rooms.get(room, [])]


@pytest.fixture(autouse=True)
def isolated_gates(monkeypatch):
    """Every test starts with an empty LiveKit and a fresh, generous limiter."""
    monkeypatch.setattr(
        app_module, "directory_factory", lambda url, key, secret: FakeDirectory()
    )
    monkeypatch.setattr(
        app_module, "_rate_limiter", RateLimiter(per_minute=6000, burst=1000)
    )


@pytest.fixture
def client():
    return TestClient(app_module.app)


@pytest.fixture
def real_creds(monkeypatch):
    monkeypatch.setenv("LIVEKIT_URL", DUMMY_URL)
    monkeypatch.setenv("LIVEKIT_API_KEY", DUMMY_KEY)
    monkeypatch.setenv("LIVEKIT_API_SECRET", DUMMY_SECRET)


@pytest.fixture
def placeholder_creds(monkeypatch):
    monkeypatch.setenv("LIVEKIT_URL", "PLACEHOLDER_LIVEKIT_URL")
    monkeypatch.setenv("LIVEKIT_API_KEY", "PLACEHOLDER_LIVEKIT_API_KEY")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "PLACEHOLDER_LIVEKIT_API_SECRET")


def test_healthz_reports_placeholder_credentials(client, placeholder_creds):
    body = client.get("/healthz").json()
    assert body["ok"] is True
    assert body["livekit_configured"] is False


def test_healthz_reports_configured_credentials(client, real_creds):
    body = client.get("/healthz").json()
    assert body["livekit_configured"] is True


def test_token_endpoint_refuses_placeholder_credentials_with_clear_message(
    client, placeholder_creds
):
    resp = client.post("/api/token", json={})
    assert resp.status_code == 503
    assert ".env.example" in resp.json()["detail"]


def test_token_endpoint_mints_a_valid_scoped_token(client, real_creds):
    resp = client.post("/api/token", json={"room": "my-room", "identity": "alice"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"] == DUMMY_URL
    assert body["room"] == "my-room"
    assert body["identity"] == "alice"

    claims = jwt.decode(body["token"], DUMMY_SECRET, algorithms=["HS256"])
    assert claims["sub"] == "alice"
    assert claims["video"]["room"] == "my-room"
    assert claims["video"]["roomJoin"] is True


def test_secret_never_appears_in_the_response(client, real_creds):
    resp = client.post("/api/token", json={})
    assert DUMMY_SECRET not in resp.text


# --- Unique room per session (issue #13: the stale-room bug fix) -------------


def test_visitor_without_a_room_gets_a_unique_session_room(client, real_creds):
    first = client.post("/api/token", json={}).json()
    second = client.post("/api/token", json={}).json()
    for body in (first, second):
        assert body["room"].startswith("lky-")
        assert body["identity"].startswith("visitor-")
        # The browser must join the room named in the response; the token
        # must be scoped to exactly that room.
        claims = jwt.decode(body["token"], DUMMY_SECRET, algorithms=["HS256"])
        assert claims["video"]["room"] == body["room"]
    assert first["room"] != second["room"], "each session gets a fresh room"


def test_explicit_room_names_still_pass_through(client, real_creds):
    # scripts/barge_in_probe.py and other probes name their own rooms.
    resp = client.post("/api/token", json={"room": "barge-probe-abc-123"})
    assert resp.status_code == 200
    assert resp.json()["room"] == "barge-probe-abc-123"


# --- Single-session enforcement (issue #13) -----------------------------------


def occupied_factory(rooms):
    return lambda url, key, secret: FakeDirectory(rooms)


def test_visitor_is_refused_while_a_session_room_holds_a_live_visitor(
    client, real_creds, monkeypatch
):
    monkeypatch.setattr(
        app_module,
        "directory_factory",
        occupied_factory({"lky-1752444000-abc123": [("visitor-11", False), ("agent-x", True)]}),
    )
    resp = client.post("/api/token", json={})
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["reason"] == "busy"
    assert "try again" in detail["message"]
    assert detail["retry_after_seconds"] > 0


def test_probe_and_agent_only_and_empty_rooms_do_not_block_a_visitor(
    client, real_creds, monkeypatch
):
    monkeypatch.setattr(
        app_module,
        "directory_factory",
        occupied_factory(
            {
                "barge-probe-abc-1": [("barge-probe", False)],  # probe room
                "lky-1752440000-dead00": [("agent-x", True)],  # visitor already left
                "lky-1752440001-dead01": [],  # empty, waiting for LiveKit's reaper
            }
        ),
    )
    resp = client.post("/api/token", json={})
    assert resp.status_code == 200


def test_explicit_room_requests_bypass_the_session_gate(
    client, real_creds, monkeypatch
):
    monkeypatch.setattr(
        app_module,
        "directory_factory",
        occupied_factory({"lky-1752444000-abc123": [("visitor-11", False)]}),
    )
    resp = client.post("/api/token", json={"room": "barge-probe-xyz-9"})
    assert resp.status_code == 200


def test_occupancy_check_fails_open_when_livekit_is_unreachable(
    client, real_creds, monkeypatch
):
    class ExplodingDirectory:
        async def list_rooms(self):
            raise RuntimeError("LiveKit unreachable")

        async def list_participants(self, room):  # pragma: no cover
            raise RuntimeError("LiveKit unreachable")

    monkeypatch.setattr(
        app_module, "directory_factory", lambda url, key, secret: ExplodingDirectory()
    )
    resp = client.post("/api/token", json={})
    assert resp.status_code == 200, "a broken check must not lock visitors out"


# --- Per-IP rate limiting (issue #13) ------------------------------------------


def test_rate_limit_returns_designed_429_after_the_burst(
    client, real_creds, monkeypatch
):
    monkeypatch.setattr(
        app_module,
        "_rate_limiter",
        RateLimiter(per_minute=6, burst=2, clock=lambda: 0.0),
    )
    assert client.post("/api/token", json={}).status_code == 200
    assert client.post("/api/token", json={}).status_code == 200
    resp = client.post("/api/token", json={})
    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail["reason"] == "rate_limited"
    assert "try again" in detail["message"]
    assert detail["retry_after_seconds"] >= 1
    assert resp.headers["Retry-After"] == str(detail["retry_after_seconds"])


def test_rate_limit_applies_to_explicitly_named_rooms_too(
    client, real_creds, monkeypatch
):
    monkeypatch.setattr(
        app_module,
        "_rate_limiter",
        RateLimiter(per_minute=6, burst=1, clock=lambda: 0.0),
    )
    assert (
        client.post("/api/token", json={"room": "barge-probe-a-1"}).status_code == 200
    )
    assert (
        client.post("/api/token", json={"room": "barge-probe-a-2"}).status_code == 429
    )
