"""HTTP-level tests for the token endpoint, with dummy credentials in env."""

import jwt
import pytest
from fastapi.testclient import TestClient

import app as app_module

DUMMY_URL = "wss://demo-project.livekit.cloud"
DUMMY_KEY = "APIdummykey123"
DUMMY_SECRET = "dummy-secret-dummy-secret-dummy-secret"


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


def test_token_endpoint_defaults_room_and_generates_identity(client, real_creds):
    resp = client.post("/api/token", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["room"] == app_module.DEFAULT_ROOM
    assert body["identity"].startswith("visitor-")


def test_secret_never_appears_in_the_response(client, real_creds):
    resp = client.post("/api/token", json={})
    assert DUMMY_SECRET not in resp.text
