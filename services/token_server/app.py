"""Token server for the walking skeleton (issue #4) + hardening (issue #13).

Mints short-lived LiveKit access tokens server-side so the LiveKit API key
and secret never reach the browser (spec: operator story 32). Hardening
(issue #13) adds, at the point where sessions start:

- a UNIQUE room per visitor session (``lky-<timestamp>-<shortid>``) when the
  client does not name one — the durable fix for the stale-room bug where a
  fixed room name outliving an agent restart absorbed new visitors into an
  agent-less room;
- SINGLE-SESSION enforcement: if a session room already holds a live
  visitor, respond 409 with a structured busy body (llama-server queues
  concurrent brain requests instead of 429ing, so the old brain-busy guard
  no longer protects a second simultaneous visitor);
- per-IP RATE LIMITING on token minting, 429 with a structured body.

Explicitly named rooms (probes, tools) skip the occupancy gate and are
never counted by it — ``scripts/barge_in_probe.py`` keeps working.

Run (inside services/token_server/.venv):

    uvicorn app:app --port 8090

Endpoints:
    GET /healthz          liveness + whether real credentials are configured
    POST /api/token       {room?, identity?} -> {token, url, room, identity}
                          409 {"detail": {"reason": "busy", ...}} if occupied
                          429 {"detail": {"reason": "rate_limited", ...}}
"""

from __future__ import annotations

import logging
import math
import os
import secrets
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from occupancy import RoomDirectory, find_occupied_session_room, new_session_room
from rate_limit import RateLimiter
from tokens import DEFAULT_TTL_SECONDS, mint_token

# Load the repo-root .env (services/token_server/ -> repo root is two up).
REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

logger = logging.getLogger("token_server")

PLACEHOLDER_MARKER = "PLACEHOLDER"

BUSY_MESSAGE = (
    "LKY is in session with another visitor — please try again in a few minutes."
)
# Guidance only (sessions are single-visitor and token TTL is minutes);
# the web client renders it as retry advice, nothing enforces it.
BUSY_RETRY_SECONDS = 120

RATE_LIMITED_MESSAGE = (
    "Too many interview requests from your connection — "
    "please wait a moment and try again."
)

app = FastAPI(title="lky-avatar token server")

# The Vite dev server is the only expected caller during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("TOKEN_SERVER_CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


class TokenRequest(BaseModel):
    room: str | None = None
    identity: str | None = None


class TokenResponse(BaseModel):
    token: str
    url: str
    room: str
    identity: str


def _credentials() -> tuple[str, str, str]:
    return (
        os.environ.get("LIVEKIT_URL", ""),
        os.environ.get("LIVEKIT_API_KEY", ""),
        os.environ.get("LIVEKIT_API_SECRET", ""),
    )


def _usable(value: str) -> bool:
    return bool(value.strip()) and PLACEHOLDER_MARKER not in value


# --- Single-session occupancy (issue #13) -----------------------------------

def _live_directory(url: str, api_key: str, api_secret: str) -> RoomDirectory:
    # Imported lazily so unit tests (which inject fakes) never touch the
    # network-facing adapter.
    from livekit_directory import LiveKitRoomDirectory

    return LiveKitRoomDirectory(url, api_key, api_secret)


# Test seam: tests replace this with a factory returning a fake directory.
directory_factory: Callable[[str, str, str], RoomDirectory] = _live_directory


async def _occupied_session_room(url: str, key: str, secret: str) -> str | None:
    """Occupancy check that FAILS OPEN: if LiveKit can't be read, mint the
    token anyway — a visitor locked out by a transient API error is worse
    than the residual risk of a second concurrent session (which llama-server
    absorbs by queueing)."""
    directory = directory_factory(url, key, secret)
    try:
        return await find_occupied_session_room(directory)
    except Exception as exc:  # noqa: BLE001 — deliberate fail-open boundary
        logger.warning(
            "LiveKit occupancy check failed (%s: %s) — minting anyway (fail open)",
            type(exc).__name__,
            exc,
        )
        return None
    finally:
        aclose = getattr(directory, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:  # noqa: BLE001 — closing is best-effort
                pass


# --- Per-IP rate limiting (issue #13) ----------------------------------------

_rate_limiter: RateLimiter | None = None


def _limiter() -> RateLimiter:
    """Lazily built so env config is read at first request, not import."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(
            per_minute=float(os.environ.get("TOKEN_RATE_LIMIT_PER_MINUTE", "6")),
            burst=int(os.environ.get("TOKEN_RATE_LIMIT_BURST", "3")),
        )
    return _rate_limiter


@app.get("/healthz")
def healthz() -> dict:
    url, key, secret = _credentials()
    return {
        "ok": True,
        "livekit_configured": all(_usable(v) for v in (url, key, secret)),
    }


@app.post("/api/token", response_model=TokenResponse)
async def create_token(req: TokenRequest, request: Request) -> TokenResponse:
    url, key, secret = _credentials()
    if not all(_usable(v) for v in (url, key, secret)):
        raise HTTPException(
            status_code=503,
            detail=(
                "LiveKit credentials are missing or still PLACEHOLDER values. "
                "Copy .env.example to .env at the repo root and fill in "
                "LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET from "
                "your LiveKit Cloud project settings."
            ),
        )

    client_ip = request.client.host if request.client else "unknown"
    decision = _limiter().check(client_ip)
    if not decision.allowed:
        retry_after = max(1, math.ceil(decision.retry_after_seconds))
        raise HTTPException(
            status_code=429,
            detail={
                "reason": "rate_limited",
                "message": RATE_LIMITED_MESSAGE,
                "retry_after_seconds": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )

    explicit_room = (req.room or "").strip()
    if explicit_room:
        # Probes and tools name their own rooms; they bypass the visitor
        # session gate (and their rooms are ignored by it — see occupancy).
        room = explicit_room
    else:
        occupied = await _occupied_session_room(url, key, secret)
        if occupied is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": "busy",
                    "message": BUSY_MESSAGE,
                    "retry_after_seconds": BUSY_RETRY_SECONDS,
                },
            )
        room = new_session_room()

    identity = (req.identity or f"visitor-{secrets.token_hex(4)}").strip()
    ttl = int(os.environ.get("TOKEN_TTL_SECONDS", str(DEFAULT_TTL_SECONDS)))

    token = mint_token(key, secret, room=room, identity=identity, ttl_seconds=ttl)
    return TokenResponse(token=token, url=url, room=room, identity=identity)
