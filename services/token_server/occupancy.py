"""Session-room naming + single-session occupancy logic (issue #13).

Two jobs, both kept network-free at the core so they unit-test with fakes:

1. **Unique room per session** — fixes the stale-room bug found in live
   testing (issue #13 comments): with a FIXED room name, a room that
   outlives an agent restart absorbs new visitor connections with no agent
   inside ("connected but nothing happens"). A fresh
   ``lky-<timestamp>-<shortid>`` per visitor guarantees every session gets
   a fresh room and therefore a fresh agent dispatch.

2. **Single-session enforcement** — production serving is llama-server,
   which QUEUES concurrent requests instead of 429ing
   (docs/reports/serving-upgrade.md, "Behavioral differences"), so the old
   brain-busy guard no longer protects against a second simultaneous
   visitor. The guard moves to where sessions start: before minting a
   visitor token, look for an existing session room that still holds a live
   visitor.

Known race (accepted, documented): two visitors who request tokens in the
same instant can both pass the check — there is no lock between check and
mint, and LiveKit's room listing is not transactional. At portfolio-demo
traffic this residual risk is acceptable: the second visitor lands in their
own room and shares the brain's request queue rather than breaking anything.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Protocol

SESSION_ROOM_PREFIX = "lky-"


def new_session_room() -> str:
    """A unique visitor-session room name: ``lky-<epoch>-<shortid>``."""
    return f"{SESSION_ROOM_PREFIX}{int(time.time())}-{secrets.token_hex(3)}"


def is_session_room(name: str) -> bool:
    """True for rooms this server mints for visitors.

    Probe rooms (``barge-probe-*``) and any other explicitly named rooms
    live outside the prefix and are never counted toward occupancy.
    """
    return name.startswith(SESSION_ROOM_PREFIX)


@dataclass(frozen=True)
class RoomSnapshot:
    name: str
    num_participants: int


@dataclass(frozen=True)
class ParticipantSnapshot:
    identity: str
    is_agent: bool


class RoomDirectory(Protocol):
    """What the occupancy check needs from LiveKit (fake-able in tests)."""

    async def list_rooms(self) -> list[RoomSnapshot]: ...

    async def list_participants(self, room: str) -> list[ParticipantSnapshot]: ...


async def find_occupied_session_room(directory: RoomDirectory) -> str | None:
    """Name of a session room currently holding a live visitor, else None.

    Deliberately ignored:
    - non-session rooms (probes and tools name their own rooms),
    - empty rooms lingering until LiveKit's empty-timeout reaps them,
    - rooms holding only agents (the visitor already left; the room is
      winding down and must not block the next visitor).
    """
    for room in await directory.list_rooms():
        if not is_session_room(room.name) or room.num_participants == 0:
            continue
        participants = await directory.list_participants(room.name)
        if any(not p.is_agent for p in participants):
            return room.name
    return None
