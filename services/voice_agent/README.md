# voice_agent

LiveKit voice agent (issues #4, #6, #8). Will hold `agent.py`, `session.py`,
and `providers/` (`stt.py`, `tts.py`) per plan §6.

Responsibilities: VAD/endpointing/barge-in via LiveKit; calls the brain API
as an OpenAI-compatible client; TTS is callable only from here — never a
public endpoint. Interruption is one atomic operation (cancel generation,
flush TTS queue, stop playback).

Runs in its own venv (`.venv/`, gitignored).
