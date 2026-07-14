"""Walking-skeleton voice agent (issue #4).

A LiveKit Agents (1.x) voice pipeline built entirely from stock parts:

- STT: Deepgram streaming (interim transcripts on)
- LLM: the OpenAI plugin pointed at OPENAI_BASE_URL — any OpenAI-compatible
  endpoint works. Issue #6 swaps LKY's brain in by changing ONLY the env vars
  (OPENAI_BASE_URL / OPENAI_API_KEY / SKELETON_LLM_MODEL); no code change.
- TTS: Deepgram Aura stock voice (same API key as STT)
- VAD / turn detection / barge-in: Silero VAD via the SDK's standard
  AgentSession pipeline; interruptions are handled by the SDK.

Run (inside services/voice_agent/.venv):

    python agent.py dev       # development mode, connects to LIVEKIT_URL
    python agent.py console   # terminal-only mode (no LiveKit round-trip)

Configuration comes exclusively from env vars / the repo-root .env file; see
.env.example. With placeholder credentials the agent refuses to start with a
clear explanation instead of a provider stack trace.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load the repo-root .env (services/voice_agent/ -> repo root is two up).
REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

from livekit.agents import (  # noqa: E402
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    RoomOutputOptions,
    WorkerOptions,
    cli,
    metrics,
)
from livekit.plugins import deepgram, openai, silero  # noqa: E402

from config import AgentConfig, explain_unusable, unusable_keys  # noqa: E402
from latency import LatencyTracker  # noqa: E402

logger = logging.getLogger("lky.skeleton")

# Stock instructions for the skeleton. The LKY persona arrives with issue #6.
INSTRUCTIONS = (
    "You are a friendly voice assistant in a technical walking-skeleton demo. "
    "You communicate by voice, so answer in one to three short spoken-style "
    "sentences. No markdown, no lists, no emojis."
)


def prewarm(proc: JobProcess) -> None:
    """Load the Silero VAD once per process so sessions start fast."""
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext) -> None:
    config = AgentConfig.from_env(os.environ)

    session: AgentSession = AgentSession(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(
            model=config.stt_model,
            api_key=config.deepgram_api_key,
            interim_results=True,  # live interim transcripts in the browser
        ),
        # The one client that later points at the LKY brain API (issue #6).
        llm=openai.LLM(
            model=config.llm_model,
            base_url=config.openai_base_url,
            api_key=config.openai_api_key,
        ),
        tts=deepgram.TTS(
            model=config.tts_model,
            api_key=config.deepgram_api_key,
        ),
        # Barge-in: on by default in the SDK; kept explicit because the spec
        # treats interruption as a core requirement.
        allow_interruptions=True,
    )

    # Issue #4: measure end-of-speech -> first-audio latency per turn.
    tracker = LatencyTracker()

    @session.on("metrics_collected")
    def _on_metrics(ev: MetricsCollectedEvent) -> None:
        m = ev.metrics
        metrics.log_metrics(m)
        if isinstance(m, metrics.EOUMetrics):
            done = tracker.record("eou", m.speech_id, m.end_of_utterance_delay)
        elif isinstance(m, metrics.LLMMetrics):
            done = tracker.record("llm", m.speech_id, m.ttft)
        elif isinstance(m, metrics.TTSMetrics):
            done = tracker.record("tts", m.speech_id, m.ttfb)
        else:
            done = None
        if done is not None:
            logger.info("LATENCY %s", done.summary())

    await session.start(
        agent=Agent(instructions=INSTRUCTIONS),
        room=ctx.room,
        room_output_options=RoomOutputOptions(
            # Publish transcriptions to the room so the web client can render
            # interim + final segments (lk.transcription text streams).
            transcription_enabled=True,
        ),
    )

    await ctx.connect()

    await session.generate_reply(
        instructions=(
            "Greet the visitor in one short sentence and invite them to ask "
            "you anything."
        )
    )


def main() -> None:
    config = AgentConfig.from_env(os.environ)
    missing = unusable_keys(config)
    if missing:
        print(explain_unusable(missing), file=sys.stderr)
        raise SystemExit(1)

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        )
    )


if __name__ == "__main__":
    main()
