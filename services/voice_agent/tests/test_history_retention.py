"""Only-heard-text history retention (issue #6, spec "conversation history
keeps only text the user actually heard").

The agent deliberately relies on livekit-agents' native behavior (verified
in 1.6.5 source): when a speech is interrupted, the assistant message stored
in the chat context is the *synchronized transcript* — the text that actually
played through the speakers — and nothing is stored if audio never started.

These tests PIN that SDK contract so a livekit-agents upgrade that changes
the retention semantics fails loudly here instead of silently breaking the
spec. If they fail after an upgrade, re-verify the retention behavior and
either adjust the agent (override the retention) or update the pins.
"""

import inspect

from livekit.agents.voice import agent_activity
from livekit.agents.voice.generation import _ForwardOutput, _TextOutput

FULL_TEXT = "Nothing is free in this world. You must be realistic about that."
HEARD_PART = "Nothing is free in this world."


def _out(played, *, text=FULL_TEXT, synced=None) -> _ForwardOutput:
    return _ForwardOutput(
        text_out=_TextOutput(text=text, first_text_fut=None),
        audio_out=None,
        played=played,
        synchronized_transcript=synced,
    )


def test_fully_played_speech_retains_full_text():
    assert _out("full").forwarded_text == FULL_TEXT


def test_interrupted_speech_retains_only_the_heard_prefix():
    # Barge-in mid-answer: the playout reports how far playback got via the
    # transcript synchronizer; only that prefix goes to history.
    out = _out("partial", synced=HEARD_PART)
    assert out.forwarded_text == HEARD_PART
    assert not out.forwarded_text.endswith("realistic about that.")


def test_interrupted_before_any_audio_retains_nothing():
    # The visitor heard nothing -> nothing may enter history.
    assert _out("skipped").forwarded_text == ""


def test_partial_without_synchronizer_falls_back_to_generated_text():
    # Without a transcript synchronizer the SDK cannot know the heard prefix
    # and keeps the generated text. The agent therefore REQUIRES the room
    # transcript sync (RoomOutputOptions default) — see the pin below.
    assert _out("partial", synced=None).forwarded_text == FULL_TEXT


def test_sdk_stores_synchronized_transcript_for_interrupted_speech():
    """Source pin: the pipeline-reply path must still write the synchronized
    transcript (not the raw LLM output) into the chat context on interrupt."""
    src = inspect.getsource(agent_activity)
    assert "playback_ev.synchronized_transcript" in src
    assert "interrupted=speech_handle.interrupted" in src
