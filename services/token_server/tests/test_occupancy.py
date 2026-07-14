"""Unit tests for session-room naming + the single-session occupancy logic.

Pure module: the LiveKit directory is a fake, no network anywhere.
"""

import asyncio
import re

from occupancy import (
    ParticipantSnapshot,
    RoomSnapshot,
    find_occupied_session_room,
    is_session_room,
    new_session_room,
)


class FakeDirectory:
    """{room name: [(identity, is_agent), ...]}"""

    def __init__(self, rooms: dict[str, list[tuple[str, bool]]]):
        self.rooms = rooms
        self.participant_lookups: list[str] = []

    async def list_rooms(self):
        return [RoomSnapshot(name, len(p)) for name, p in self.rooms.items()]

    async def list_participants(self, room):
        self.participant_lookups.append(room)
        return [ParticipantSnapshot(i, a) for i, a in self.rooms.get(room, [])]


def find(rooms) -> str | None:
    return asyncio.run(find_occupied_session_room(FakeDirectory(rooms)))


# --- Room naming ---------------------------------------------------------------


def test_session_room_names_are_prefixed_timestamped_and_unique():
    names = {new_session_room() for _ in range(50)}
    assert len(names) == 50
    for name in names:
        assert re.fullmatch(r"lky-\d+-[0-9a-f]{6}", name)


def test_is_session_room_matches_only_the_visitor_prefix():
    assert is_session_room(new_session_room())
    assert is_session_room("lky-demo")  # legacy fixed room still counts
    assert not is_session_room("barge-probe-c612208-1752444000")
    assert not is_session_room("someones-own-room")


# --- Occupancy -----------------------------------------------------------------


def test_no_rooms_means_no_occupancy():
    assert find({}) is None


def test_a_session_room_with_a_live_visitor_occupies_the_studio():
    room = "lky-1752444000-abc123"
    assert find({room: [("visitor-2f9a", False), ("agent-AJ_x", True)]}) == room


def test_probe_rooms_never_occupy_the_studio():
    assert find({"barge-probe-c612208-1752444000": [("barge-probe", False)]}) is None


def test_empty_rooms_waiting_for_the_reaper_are_ignored():
    assert find({"lky-1752444000-abc123": []}) is None


def test_agent_only_rooms_are_ignored_the_visitor_already_left():
    assert find({"lky-1752444000-abc123": [("agent-AJ_x", True)]}) is None


def test_participants_are_only_listed_for_candidate_session_rooms():
    directory = FakeDirectory(
        {
            "barge-probe-c612208-1": [("barge-probe", False)],
            "lky-1752444000-abc123": [],
            "lky-1752444999-def456": [("visitor-11", False)],
        }
    )
    result = asyncio.run(find_occupied_session_room(directory))
    assert result == "lky-1752444999-def456"
    assert directory.participant_lookups == ["lky-1752444999-def456"]
