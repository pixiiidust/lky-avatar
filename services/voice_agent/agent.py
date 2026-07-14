"""LKY voice agent (issues #4 walking skeleton + #6 brain swap).

A LiveKit Agents (1.x) voice pipeline:

- STT: Deepgram streaming (interim transcripts on)
- LLM: the OpenAI plugin pointed at OPENAI_BASE_URL — any OpenAI-compatible
  endpoint. Pointing it at the self-hosted LKY brain API (issue #6) is a
  pure env-var swap (OPENAI_BASE_URL / OPENAI_API_KEY / SKELETON_LLM_MODEL);
  see ".Swapping the brain in" in the repo README.
- TTS: Deepgram Aura stock voice (the cloned voice arrives with issue #8)
- VAD / turn detection / barge-in: Silero VAD via the SDK's standard
  AgentSession pipeline; interruptions are handled by the SDK.

Issue #6 additions on top of the skeleton:

- Persona: instructions come from the vendored ``lky_avatar.persona`` prompt
  (via persona_prompt.py), configurable with LKY_SIM_DATE / LKY_PROMPT_VARIANT
  pending issue #2's framing verdict. The brain server does NOT inject a
  persona — the agent owns it.
- Spoken style: the instructions demand ~2-5 sentences and LKY_MAX_TOKENS is
  passed to the LLM plugin as the hard budget (the brain server additionally
  caps and defaults this server-side).
- Busy / unreachable handling: the brain is single-slot; a concurrent
  generation gets HTTP 429 (code "busy"). ``LKYAgent.llm_node`` catches API
  failures, speaks a polite message instead of crashing, publishes the
  ``lky.brain`` participant attribute (ok|busy|error) for the web client's
  busy/error states, and never retry-storms (max_retry=0).

Per-session conversation history — verified against livekit-agents 1.6.5
source (voice/agent_activity.py, voice/generation.py):

- The ``AgentSession``'s chat context accumulates across turns for the
  lifetime of the session (one session per room/visitor), so history is
  per-session by construction.
- On barge-in the SDK stores ONLY the text the visitor actually heard: the
  assistant message is ``forwarded_text``, which for an interrupted playout
  is ``playback_ev.synchronized_transcript`` — the transcript-synchronizer's
  text-up-to-playback-position (RoomIO enables sync_transcription by
  default). If audio never reached the speakers the message is dropped
  entirely. This is exactly the spec's "remember only what was heard" rule;
  no override needed. tests/test_history_retention.py pins this SDK
  behavior so an upgrade that changes it fails loudly.

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
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

from dotenv import load_dotenv

# Load the repo-root .env (services/voice_agent/ -> repo root is two up).
REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

from livekit.agents import (  # noqa: E402
    NOT_GIVEN,
    Agent,
    AgentSession,
    APIConnectOptions,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    ModelSettings,
    RoomOutputOptions,
    WorkerOptions,
    cli,
    llm as llm_types,
    metrics,
)
from livekit.plugins import deepgram, openai, silero  # noqa: E402

from brain_status import (  # noqa: E402
    STATUS_ATTRIBUTE,
    STATUS_OK,
    classify_brain_error,
)
from config import AgentConfig, explain_unusable, unusable_keys  # noqa: E402
from latency import LatencyTracker  # noqa: E402
from persona_prompt import build_instructions  # noqa: E402

logger = logging.getLogger("lky.agent")

#: Connection options for every brain request. Deliberate choices:
#: - max_retry=0: a 429 means the single generation slot is taken for what
#:   may be minutes (~2-3 tok/s NF4 decode) — retrying is a retry-storm, not
#:   a fix; and an unreachable brain must surface as the error state
#:   immediately, not after three silent retries.
#: - timeout=60: this is the httpx connect/read timeout, where "read" is the
#:   gap BETWEEN SSE chunks — it never limits total answer length. 60s
#:   tolerates slow NF4 prefill before the first token without masking a
#:   truly dead server for long.
BRAIN_CONN_OPTIONS = APIConnectOptions(max_retry=0, timeout=60.0)

#: Reports a brain status ("ok" | "busy" | "error") to interested parties.
StatusReporter = Callable[[str], Awaitable[None]]


def build_llm(config: AgentConfig) -> openai.LLM:
    """The one LLM client, from env config — the brain swap seam.

    ``max_completion_tokens`` carries LKY_MAX_TOKENS (the brain API accepts
    it as the OpenAI-compatible alias of ``max_tokens`` and additionally
    enforces its own default/hard cap server-side). Sampling knobs are NOT
    set here: the brain locks temperature/top_p/repetition_penalty
    server-side per the spec.
    """
    return openai.LLM(
        model=config.llm_model,
        base_url=config.openai_base_url,
        api_key=config.openai_api_key,
        max_completion_tokens=config.lky_max_tokens,
    )


class LKYAgent(Agent):
    """The persona agent: LKY instructions + graceful brain-failure handling."""

    def __init__(
        self,
        *,
        instructions: str,
        report_status: StatusReporter | None = None,
    ) -> None:
        super().__init__(instructions=instructions)
        self._report_status = report_status

    async def _publish_status(self, status: str) -> None:
        if self._report_status is None:
            return
        try:
            await self._report_status(status)
        except Exception:  # never let status plumbing break the answer
            logger.exception("failed to publish brain status %r", status)

    async def llm_node(
        self,
        chat_ctx: llm_types.ChatContext,
        tools: list[llm_types.Tool],
        model_settings: ModelSettings,
    ) -> AsyncIterator[llm_types.ChatChunk | str]:
        """Default LLM node + brain busy/unreachable handling.

        Mirrors ``Agent.default.llm_node`` (stream the configured LLM) but
        with no-retry conn options and a catch that turns API failures into
        a spoken, transcribed message instead of a crashed turn. The message
        is yielded through the normal pipeline, so it IS retained in history
        — which is correct: it is exactly what the visitor heard.
        """
        activity = self._get_activity_or_raise()
        assert activity.llm is not None, "llm_node called but no LLM available"
        assert isinstance(activity.llm, llm_types.LLM)
        tool_choice = model_settings.tool_choice if model_settings else NOT_GIVEN

        answered = False
        try:
            async with activity.llm.chat(
                chat_ctx=chat_ctx,
                tools=tools,
                tool_choice=tool_choice,
                conn_options=BRAIN_CONN_OPTIONS,
            ) as stream:
                async for chunk in stream:
                    if not answered:
                        answered = True
                        await self._publish_status(STATUS_OK)
                    yield chunk
        except Exception as exc:  # GeneratorExit/CancelledError pass through
            failure = classify_brain_error(exc)
            if failure is None:
                raise
            logger.warning(
                "brain request failed (status=%s): %s", failure.status, exc
            )
            await self._publish_status(failure.status)
            yield failure.message


def prewarm(proc: JobProcess) -> None:
    """Load the Silero VAD once per process so sessions start fast."""
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext) -> None:
    config = AgentConfig.from_env(os.environ)
    instructions = build_instructions(
        config.lky_sim_date, config.lky_prompt_variant
    )

    session: AgentSession = AgentSession(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(
            model=config.stt_model,
            api_key=config.deepgram_api_key,
            interim_results=True,  # live interim transcripts in the browser
        ),
        # The one client that reaches the brain (or any OpenAI-compatible
        # stand-in) — see build_llm.
        llm=build_llm(config),
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

    async def report_status(status: str) -> None:
        # Published on the local participant; the web client watches the
        # lky.brain attribute for its busy banner / avatar error state.
        await ctx.room.local_participant.set_attributes(
            {STATUS_ATTRIBUTE: status}
        )

    await session.start(
        agent=LKYAgent(instructions=instructions, report_status=report_status),
        room=ctx.room,
        room_output_options=RoomOutputOptions(
            # Publish transcriptions to the room so the web client can render
            # interim + final segments (lk.transcription text streams). The
            # SDK's transcript synchronizer (on by default) is also what makes
            # interrupted answers keep only the text actually heard.
            transcription_enabled=True,
        ),
    )

    await ctx.connect()

    await session.generate_reply(
        instructions=(
            "Greet the visitor in one short sentence, in character, and "
            "invite them to ask you anything."
        )
    )


def main() -> None:
    config = AgentConfig.from_env(os.environ)
    missing = unusable_keys(config)
    if missing:
        print(explain_unusable(missing), file=sys.stderr)
        raise SystemExit(1)

    # Fail fast on a bad persona config (bad LKY_SIM_DATE / LKY_PROMPT_VARIANT)
    # with the env-var-naming message instead of a mid-session stack trace.
    try:
        build_instructions(config.lky_sim_date, config.lky_prompt_variant)
    except ValueError as exc:
        print(f"Cannot start the voice agent: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        )
    )


if __name__ == "__main__":
    main()
