"""Unit tests for LiveKit token minting.

Uses a dummy API key/secret — no LiveKit account or network needed. The JWT
is decoded with PyJWT and its claims asserted directly (spec: tokens must be
short-lived, scoped to one room, and keys stay server-side).
"""

import jwt
import pytest

from tokens import DEFAULT_TTL_SECONDS, mint_token

DUMMY_KEY = "APIdummykey123"
DUMMY_SECRET = "dummy-secret-dummy-secret-dummy-secret"


def decode(token: str) -> dict:
    return jwt.decode(token, DUMMY_SECRET, algorithms=["HS256"], issuer=DUMMY_KEY)


def test_token_decodes_with_the_shared_secret_and_names_the_key_as_issuer():
    token = mint_token(DUMMY_KEY, DUMMY_SECRET, room="lky-demo", identity="visitor-1")
    claims = decode(token)  # raises if signature or issuer is wrong
    assert claims["iss"] == DUMMY_KEY
    assert claims["sub"] == "visitor-1"


def test_token_is_rejected_with_a_different_secret():
    token = mint_token(DUMMY_KEY, DUMMY_SECRET, room="lky-demo", identity="visitor-1")
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, "some-other-secret-entirely-wrong!", algorithms=["HS256"])


def test_grants_join_exactly_one_room_with_publish_and_subscribe():
    token = mint_token(DUMMY_KEY, DUMMY_SECRET, room="lky-demo", identity="visitor-1")
    video = decode(token)["video"]
    assert video["roomJoin"] is True
    assert video["room"] == "lky-demo"
    assert video["canPublish"] is True
    assert video["canSubscribe"] is True
    assert video["canPublishData"] is True
    # No admin powers on a visitor token.
    assert not video.get("roomAdmin")
    assert not video.get("roomCreate")


def test_default_expiry_is_short_lived():
    token = mint_token(DUMMY_KEY, DUMMY_SECRET, room="r", identity="i")
    claims = decode(token)
    lifetime = claims["exp"] - claims["nbf"]
    assert lifetime == pytest.approx(DEFAULT_TTL_SECONDS, abs=5)
    assert lifetime <= 3600, "tokens must be short-lived (minutes, not days)"


def test_custom_ttl_respected():
    token = mint_token(DUMMY_KEY, DUMMY_SECRET, room="r", identity="i", ttl_seconds=60)
    claims = decode(token)
    assert claims["exp"] - claims["nbf"] == pytest.approx(60, abs=5)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(room="", identity="i"),
        dict(room="r", identity=""),
        dict(room="r", identity="i", ttl_seconds=0),
        dict(room="r", identity="i", ttl_seconds=-10),
    ],
)
def test_invalid_inputs_raise(kwargs):
    with pytest.raises(ValueError):
        mint_token(DUMMY_KEY, DUMMY_SECRET, **kwargs)


def test_missing_credentials_raise():
    with pytest.raises(ValueError):
        mint_token("", DUMMY_SECRET, room="r", identity="i")
    with pytest.raises(ValueError):
        mint_token(DUMMY_KEY, "", room="r", identity="i")
