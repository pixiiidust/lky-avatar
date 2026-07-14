"""Typed-input seam (issue #33: "pass a note to the interviewer").

The web client sends typed questions to the agent as a LiveKit text stream on
the SDK's chat topic. The agent deliberately relies on livekit-agents' native
room text input (verified in 1.6.5 source): ``RoomIO`` registers a handler on
``TOPIC_CHAT`` whenever text input is not explicitly disabled — the agent
passes no ``RoomOptions``, so it is enabled by default — and the default
callback claims the user turn, interrupts current speech, and generates a
spoken reply through the normal LLM -> TTS pipeline.

These tests PIN that SDK contract so a livekit-agents upgrade that renames
the topic, disables text input by default, or stops speaking the reply fails
loudly here instead of silently killing the typed-question fallback.
"""

import inspect

from livekit.agents.types import TOPIC_CHAT
from livekit.agents.voice.room_io import types as room_io_types
from livekit.agents.voice.room_io.types import RoomOptions, TextInputOptions


def test_chat_topic_matches_the_web_client():
    # web/src/main.ts sends notes with sendText(text, { topic: "lk.chat" }).
    assert TOPIC_CHAT == "lk.chat"


def test_text_input_is_enabled_by_default():
    # agent.py starts the session without RoomOptions: text input must
    # default to enabled or typed questions are dropped on the floor.
    opts = RoomOptions().get_text_input_options()
    assert isinstance(opts, TextInputOptions)
    assert opts.text_input_cb is room_io_types._default_text_input_cb


def test_default_callback_interrupts_and_speaks_a_reply():
    """Source pin: the default text-input callback must barge into current
    speech and route the typed text through generate_reply (the spoken
    pipeline), i.e. a typed question gets the same voiced answer as speech."""
    src = inspect.getsource(room_io_types._default_text_input_cb)
    assert "interrupt()" in src
    assert "generate_reply(user_input=ev.text)" in src


def test_room_io_registers_the_chat_topic_handler():
    """Source pin: RoomIO wires TOPIC_CHAT to the text-input callback."""
    from livekit.agents.voice.room_io import room_io

    src = inspect.getsource(room_io.RoomIO.register_text_input)
    assert "register_text_stream_handler(TOPIC_CHAT" in src
