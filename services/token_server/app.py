"""Token server for the walking skeleton (issue #4).

Mints short-lived LiveKit access tokens server-side so the LiveKit API key
and secret never reach the browser (spec: operator story 32).

Run (inside services/token_server/.venv):

    uvicorn app:app --port 8090

Endpoints:
    GET /healthz          liveness + whether real credentials are configured
    POST /api/token       {room?, identity?} -> {token, url, room, identity}
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from tokens import DEFAULT_TTL_SECONDS, mint_token

# Load the repo-root .env (services/token_server/ -> repo root is two up).
REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

PLACEHOLDER_MARKER = "PLACEHOLDER"
DEFAULT_ROOM = "lky-demo"

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


@app.get("/healthz")
def healthz() -> dict:
    url, key, secret = _credentials()
    return {
        "ok": True,
        "livekit_configured": all(_usable(v) for v in (url, key, secret)),
    }


@app.post("/api/token", response_model=TokenResponse)
def create_token(req: TokenRequest) -> TokenResponse:
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

    room = (req.room or os.environ.get("LKY_ROOM_NAME") or DEFAULT_ROOM).strip()
    identity = (req.identity or f"visitor-{secrets.token_hex(4)}").strip()
    ttl = int(os.environ.get("TOKEN_TTL_SECONDS", str(DEFAULT_TTL_SECONDS)))

    token = mint_token(key, secret, room=room, identity=identity, ttl_seconds=ttl)
    return TokenResponse(token=token, url=url, room=room, identity=identity)
