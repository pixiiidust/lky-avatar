"""Pure token-minting logic for LiveKit access tokens.

Kept free of FastAPI so it can be unit-tested with a dummy secret and no
network or LiveKit account (spec: keys server-side, tokens short-lived).
"""

from __future__ import annotations

import datetime

from livekit import api

DEFAULT_TTL_SECONDS = 15 * 60  # short-lived: 15 minutes


def mint_token(
    api_key: str,
    api_secret: str,
    room: str,
    identity: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> str:
    """Mint a short-lived LiveKit access token for one participant in one room.

    The grant is deliberately minimal: join this one room, publish (microphone)
    and subscribe (agent audio). No admin, no room-creation beyond auto-create
    on join.
    """
    if not api_key or not api_secret:
        raise ValueError("api_key and api_secret are required")
    if not room or not identity:
        raise ValueError("room and identity are required")
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")

    token = (
        api.AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_ttl(datetime.timedelta(seconds=ttl_seconds))
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
    )
    return token.to_jwt()
