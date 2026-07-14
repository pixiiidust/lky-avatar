"""Thin livekit-api adapter behind ``occupancy.RoomDirectory``.

The only network-touching piece of the single-session check, so tests never
import it — they inject fakes for the protocol instead. Uses the same
server-side LiveKit credentials as token minting (keys never leave the
server) and only READS room state: list rooms, list participants. It never
creates or deletes anything.
"""

from __future__ import annotations

from livekit import api
from livekit.protocol import models

from occupancy import ParticipantSnapshot, RoomSnapshot

_AGENT_KIND = models.ParticipantInfo.Kind.AGENT


class LiveKitRoomDirectory:
    def __init__(self, url: str, api_key: str, api_secret: str) -> None:
        self._lk = api.LiveKitAPI(url, api_key, api_secret)

    async def list_rooms(self) -> list[RoomSnapshot]:
        resp = await self._lk.room.list_rooms(api.ListRoomsRequest())
        return [RoomSnapshot(r.name, r.num_participants) for r in resp.rooms]

    async def list_participants(self, room: str) -> list[ParticipantSnapshot]:
        resp = await self._lk.room.list_participants(
            api.ListParticipantsRequest(room=room)
        )
        return [
            ParticipantSnapshot(p.identity, p.kind == _AGENT_KIND)
            for p in resp.participants
        ]

    async def aclose(self) -> None:
        await self._lk.aclose()
