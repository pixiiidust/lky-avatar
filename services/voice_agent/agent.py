"""LKY voice agent (issues #4 walking skeleton + #6 brain swap).

A LiveKit Agents (1.x) voice pipeline:

- STT: Deepgram streaming (interim transcripts on)
- LLM: the OpenAI plugin pointed at OPENAI_BASE_URL — any OpenAI-compatible
  endpoint. Pointing it at the self-hosted LKY brain API (issue #6) is a
  pure env-var swap (OPENAI_BASE_URL / OPENAI_API_KEY / SKELETON_LLM_MODEL);
  see ".Swapping the brain in" in the repo README.
- TTS: selected by TTS_PROVIDER (issue #8): "deepgram" (stock Aura voice,
  default fallback) or "chatterbox" (the cloned elder voice via the
  loopback-only tts_server — see build_tts and providers/tts.py; start
  services/tts_server first per its run_real.md).
- VAD / turn detection / barge-in: Silero VAD via the SDK's standard
  AgentSession pipeline; interruptions are handled by the SDK. The cloned
  voice inherits identical phrase streaming + barge-in cancellation because
  the SDK wraps any non-streaming TTS in its StreamAdapter (sentence
  tokenizer -> per-phrase synthesize, all cancelled as one operation).

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

Issue #13 addition — TTS-outage honesty: if the cloned-voice server dies
mid-session, ``LKYAgent.tts_node`` catches the synthesis failure, publishes
the ``lky.tts`` participant attribute (ok|error), and re-delivers the reply
as a text-only transcript turn (``_say_text_only``) instead of the silent
void the stock pipeline produces (transcription output is synced to audio
playout, so a turn with no audio emits no text). SDK evidence for each step
is documented on those methods.

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

import asyncio
import logging
import os
import sys
import time
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
)
from livekit.agents.voice.agent_session import (  # noqa: E402
    InterruptionOptions,
    TurnHandlingOptions,
)
from livekit.agents import (  # noqa: E402
    AgentStateChangedEvent,
    APIConnectOptions,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    ModelSettings,
    RoomOutputOptions,
    UserStateChangedEvent,
    WorkerOptions,
    cli,
    llm as llm_types,
    metrics,
)
from livekit import rtc  # noqa: E402
from livekit.agents.voice.io import PlaybackFinishedEvent  # noqa: E402
from livekit.plugins import deepgram, openai, silero  # noqa: E402

from brain_status import (  # noqa: E402
    STATUS_ATTRIBUTE,
    STATUS_OK,
    classify_brain_error,
)
from tts_status import (  # noqa: E402
    TTS_STATUS_ATTRIBUTE,
    TTS_STATUS_OK,
    classify_tts_error,
)
from config import AgentConfig, explain_unusable, unusable_keys  # noqa: E402
from fact_grounding import (  # noqa: E402
    build_grounding_block,
    load_fact_sheet,
    retrieve,
)
from latency import InterruptLatency, InterruptTracker, LatencyTracker  # noqa: E402
from persona_prompt import (  # noqa: E402
    FEW_SHOT_TURNS,
    build_instructions,
    fact_sheet_path_from_env,
)
from pronunciation import build_pronunciation_map  # noqa: E402
from providers.tts import ChatterboxTTS  # noqa: E402
from stt_keywords import build_keywords  # noqa: E402

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


def _last_user_text(chat_ctx: llm_types.ChatContext) -> str:
    """Extract the latest user-role message text from a chat context.

    Used by fact-grounding retrieval (issue #45) to pick the relevant
    fact-sheet sections for the current turn. Returns "" when there is no
    user message (e.g. the seed exemplars path, or a brand-new session).
    """
    msgs = list(chat_ctx.items) if hasattr(chat_ctx, "items") else []
    for msg in reversed(msgs):
        role = getattr(msg, "role", "")
        if role == "user":
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                return content
            # content can be a list of parts; coerce to text.
            parts = []
            for p in content or []:
                txt = getattr(p, "text", None) or (
                    p.get("text") if isinstance(p, dict) else None
                )
                if txt:
                    parts.append(txt)
            return "".join(parts)
    return ""

#: Upper bound on one text-only fallback delivery (issue #13). The text-only
#: ``say`` forwards an already-complete string with no synthesis and no
#: playout clock, so it finishes in well under a second; the bound only
#: guarantees that audio output can never stay disabled forever if the SDK
#: wedges. 30s is deliberately generous — hitting it is a bug, not tuning.
TEXT_ONLY_SAY_TIMEOUT = 30.0


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


def build_tts(config: AgentConfig) -> ChatterboxTTS | deepgram.TTS:
    """The one TTS client, from env config — the voice swap seam (issue #8).

    TTS_PROVIDER=chatterbox speaks in the cloned elder voice through the
    loopback tts_server (which embeds Chatterbox's PerTh watermark in every
    sample — preserved untouched through this pipeline). Anything else is
    the stock Deepgram voice, which also remains the operator fallback if
    the local TTS server misbehaves mid-demo.
    """
    if config.tts_provider == "chatterbox":
        logger.info(
            "TTS: cloned voice via %s (speed=%.2f)",
            config.tts_base_url,
            config.tts_speed,
        )
        return ChatterboxTTS(
            base_url=config.tts_base_url,
            speed=config.tts_speed,
            pronunciations=build_pronunciation_map(
                config.tts_pronunciations_path or None
            ),
        )
    logger.info("TTS: stock Deepgram voice (%s)", config.tts_model)
    return deepgram.TTS(
        model=config.tts_model,
        api_key=config.deepgram_api_key,
    )


class LKYAgent(Agent):
    """The persona agent: LKY instructions + graceful brain-failure handling.

    Every session's chat context is seeded with the FEW_SHOT_TURNS exemplars
    before the first real user turn — the LoRA imitates demonstrated behavior
    (premise correction, clarify-first, brevity) far better than it obeys
    written rules; see docs/eval-process.md, probes D/D2.

    Issue #45 fact grounding: when ``fact_sheet_path`` is set, ``llm_node``
    retrieves the fact-sheet sections whose keywords best match the latest
    user turn and injects them as a system message (the "trust these dates"
    block) right before that user turn — so the brain reads the audited
    facts before answering, without the brain server changing at all. A
    missing/unset path is a clean no-op (the instructions are unchanged).
    """

    def __init__(
        self,
        *,
        instructions: str,
        report_status: StatusReporter | None = None,
        report_tts_status: StatusReporter | None = None,
        fact_sheet_path: str = "",
    ) -> None:
        seeded = llm_types.ChatContext.empty()
        for turn in FEW_SHOT_TURNS:
            seeded.add_message(role=turn["role"], content=turn["content"])
        super().__init__(instructions=instructions, chat_ctx=seeded)
        self._report_status = report_status
        self._report_tts_status = report_tts_status
        # Issue #45: load the fact sheet once at session start so per-turn
        # retrieval is an in-memory keyword match, not a file read. Empty
        # path -> no grounding (clean no-op).
        self._fact_sections = (
            load_fact_sheet(fact_sheet_path) if fact_sheet_path else []
        )
        # Serializes text-only fallback deliveries (issue #13) and keeps
        # strong references to their tasks so they aren't GC-cancelled.
        self._text_only_lock = asyncio.Lock()
        self._text_only_tasks: set[asyncio.Task[None]] = set()

    async def _publish_status(self, status: str) -> None:
        if self._report_status is None:
            return
        try:
            await self._report_status(status)
        except Exception:  # never let status plumbing break the answer
            logger.exception("failed to publish brain status %r", status)

    async def _publish_tts_status(self, status: str) -> None:
        if self._report_tts_status is None:
            return
        try:
            await self._report_tts_status(status)
        except Exception:  # never let status plumbing break the answer
            logger.exception("failed to publish tts status %r", status)

    async def llm_node(
        self,
        chat_ctx: llm_types.ChatContext,
        tools: list[llm_types.Tool],
        model_settings: ModelSettings,
    ) -> AsyncIterator[llm_types.ChatChunk | str]:
        """Default LLM node + brain busy/unreachable handling + fact grounding.

        Mirrors ``Agent.default.llm_node`` (stream the configured LLM) but
        with no-retry conn options and a catch that turns API failures into
        a spoken, transcribed message instead of a crashed turn. The message
        is yielded through the normal pipeline, so it IS retained in history
        — which is correct: it is exactly what the visitor heard.

        Issue #45: before the LLM call, the latest user turn is used to
        retrieve relevant fact-sheet sections and inject them as a system
        message immediately before that turn. This is a per-turn, in-place
        copy of the chat context — the session's accumulated history is
        not mutated. Empty fact sheet / no match -> unchanged context.
        """
        activity = self._get_activity_or_raise()
        assert activity.llm is not None, "llm_node called but no LLM available"
        assert isinstance(activity.llm, llm_types.LLM)
        tool_choice = model_settings.tool_choice if model_settings else NOT_GIVEN

        grounded_ctx = self._grounded_chat_ctx(chat_ctx)

        answered = False
        try:
            async with activity.llm.chat(
                chat_ctx=grounded_ctx,
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

    def _grounded_chat_ctx(
        self, chat_ctx: llm_types.ChatContext
    ) -> llm_types.ChatContext:
        """Return a copy of ``chat_ctx`` with the fact-grounding block
        injected as a system message immediately before the latest user
        turn (issue #45).

        No-op when the fact sheet is empty or no section matches the turn:
        the original context is returned unchanged (not a copy) so the
        brain sees exactly what it sees today. The copy is made only when
        there is something to inject, so the common path stays cheap.
        """
        if not self._fact_sections:
            return chat_ctx
        user_text = _last_user_text(chat_ctx)
        if not user_text:
            return chat_ctx
        block = build_grounding_block(retrieve(user_text, self._fact_sections))
        if not block:
            return chat_ctx
        ctx = chat_ctx.copy()
        ctx.add_message(role="system", content=block)
        return ctx

    async def _default_tts_node(
        self,
        text: AsyncIterator[str],
        model_settings: ModelSettings,
    ) -> AsyncIterator[rtc.AudioFrame]:
        """The SDK's stock synthesis pipeline, isolated so tests can stub it."""
        async for frame in Agent.default.tts_node(self, text, model_settings):
            yield frame

    async def tts_node(
        self,
        text: AsyncIterator[str],
        model_settings: ModelSettings,
    ) -> AsyncIterator[rtc.AudioFrame]:
        """Default TTS node + degraded-but-honest handling of a dead voice.

        Why this exists — verified against livekit-agents 1.6.5 source (the
        installed .venv), after live fault injection (2026-07-14) showed a
        TTS outage producing a silent void (no audio AND no transcript):

        - RoomIO syncs the room transcript to audio playout. The synced text
          segment only starts emitting on ``on_playback_started`` — i.e.
          after the FIRST audio frame reaches the speakers
          (transcription/synchronizer.py: ``_main_task`` waits on
          ``_start_fut``, set only by ``on_playback_started``).
        - When no audio ever arrives, the audio flush sees
          ``_pushed_duration == 0`` and rotates the segment
          (``_SyncedAudioOutput.flush``); the rotated impl closes without
          playback and ``_main_task`` returns WITHOUT emitting the buffered
          text (`if self.closed and not self._playback_completed: return`).
          The reply text is silently dropped — the observed bug.
        - The turn's failure surfaces here: the default tts_node's
          ``async for ev in stream`` re-raises the adapter/ChunkedStream
          error typed (tts/tts.py ``__anext__`` re-raises the task
          exception), e.g. providers/tts.py's APIConnectionError.

        The fix: catch service-class failures (classify_tts_error), publish
        ``lky.tts=error``, END THE GENERATOR CLEANLY (no re-raise), and
        deliver the reply text through a queued text-only ``say`` (see
        ``_say_text_only`` for why that provably reaches the visitor).
        Swallowing is safe: with zero frames yielded the pipeline completes
        instead of dying — ``_tts_inference_task`` returns False, the audio
        channel closes empty, ``wait_for_playout`` returns immediately
        because no segment was ever captured (io.py: target == 0), and the
        skipped turn's message is dropped from chat history (generation.py:
        ``played == "skipped"``), so the fallback ``say`` is history's ONLY
        copy of the reply — exactly what the visitor received.

        Recovery: ``lky.tts=ok`` is republished on the first audio frame of
        the next successful synthesis, clearing the web's voice-down slate.

        Session survival during long outages: each failed synthesis makes
        the TTS emit a non-recoverable TTSError, and AgentSession closes
        after ``max_unrecoverable_errors`` (3) CONSECUTIVE ones — but the
        counter resets whenever the agent reaches the "speaking" state
        (agent_session.py:1686), which the text-only ``say`` triggers via
        its first-text future. Degraded turns therefore keep the session
        alive indefinitely, while each new turn still probes the TTS for
        recovery.
        """
        captured: list[str] = []

        async def _tap() -> AsyncIterator[str]:
            # Runs ahead of synthesis (the default node forwards input to
            # the sentence tokenizer as it arrives), so on failure
            # ``captured`` already holds everything synthesis consumed.
            async for chunk in text:
                captured.append(chunk)
                yield chunk

        yielded_audio = False
        try:
            async for frame in self._default_tts_node(_tap(), model_settings):
                if not yielded_audio:
                    yielded_audio = True
                    await self._publish_tts_status(TTS_STATUS_OK)
                yield frame
        except Exception as exc:
            # GeneratorExit/CancelledError (barge-in teardown) are
            # BaseException and pass through untouched.
            failure = classify_tts_error(exc)
            if failure is None:
                raise
            logger.warning("TTS synthesis failed (voice unavailable): %s", exc)
            await self._publish_tts_status(failure.status)
            if yielded_audio:
                # Mid-reply failure after audio reached the speakers: the
                # transcript synchronizer flushes the REMAINING text itself
                # once playout finishes un-interrupted (synchronizer.py:
                # mark_playback_finished -> _playback_completed=True -> the
                # word loop drains with delay=0), and the pipeline keeps the
                # full text in history. Only the voice was lost — nothing to
                # re-deliver.
                return
            # Silent-void case: no audio at all this turn. Drain the rest of
            # the reply (the LLM may still be streaming; the pipeline feeds
            # this channel with send_nowait, so reading here cannot block
            # it) and deliver the whole reply as text.
            async for chunk in text:
                captured.append(chunk)
            reply = "".join(captured).strip()
            if reply:
                self._schedule_text_only_reply(reply)

    def _schedule_text_only_reply(self, reply: str) -> None:
        """Queue the fallback delivery without blocking the failed turn.

        Must not be awaited from inside ``tts_node``: the queued ``say``
        cannot start until the CURRENT speech turn finishes, and the current
        turn is waiting on this very generator — awaiting here would
        deadlock. A fire-and-forget task awaits it safely instead.
        """
        task = asyncio.create_task(self._say_text_only(reply))
        self._text_only_tasks.add(task)
        task.add_done_callback(self._text_only_tasks.discard)

    async def _say_text_only(self, reply: str) -> None:
        """Deliver a reply as transcript text with no audio — provably.

        Mechanism chosen after reading the installed livekit-agents 1.6.5
        source; it is the SDK's own documented text-without-audio path (the
        default tts_node literally instructs: "If audio output is not
        needed, disable it using session.output.set_audio_enabled(False)"):

        - ``set_audio_enabled(False)`` detaches the room audio output
          (io.py:589), which flips the transcript synchronizer to
          PASSTHROUGH: ``_SyncedTextOutput.capture_text`` forwards text
          straight to the room's lk.transcription stream instead of pacing
          it against (nonexistent) audio (synchronizer.py:747).
        - ``session.say(text)`` then runs ``_tts_task_impl`` with
          ``audio_output=None`` (agent_activity.py:2541 checks
          ``output.audio_enabled``): TTS is never invoked, the text is
          forwarded and flushed as a final transcript segment, the agent
          state flips to "speaking" via ``first_text_fut`` (resetting the
          SDK's unrecoverable-TTS-error counter), and the message lands in
          chat history (agent_activity.py:2696 — ``forwarded_text`` comes
          from the text output when audio is disabled).
        - ``activity.say`` does not require a TTS when audio is disabled
          (agent_activity.py:1232 only raises when audio output is enabled).

        Audio is re-enabled in ``finally`` so one wedged delivery can never
        mute the session; the lock serializes overlapping deliveries so an
        enable/disable pair can't interleave with another delivery's. If the
        visitor's next turn slips in during this window it degrades to the
        same honest text-only path — never to silence.
        """
        try:
            async with self._text_only_lock:
                session = self.session
                session.output.set_audio_enabled(False)
                try:
                    handle = session.say(reply)
                    await asyncio.wait_for(
                        handle.wait_for_playout(), TEXT_ONLY_SAY_TIMEOUT
                    )
                finally:
                    session.output.set_audio_enabled(True)
        except Exception:
            logger.exception("text-only reply delivery failed")


def prewarm(proc: JobProcess) -> None:
    """Load the Silero VAD once per process so sessions start fast."""
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext) -> None:
    config = AgentConfig.from_env(os.environ)
    instructions = build_instructions(
        config.lky_sim_date, config.lky_prompt_variant
    )
    fact_sheet_path = fact_sheet_path_from_env(os.environ)

    session: AgentSession = AgentSession(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(
            model=config.stt_model,
            api_key=config.deepgram_api_key,
            interim_results=True,  # live interim transcripts in the browser
            keywords=build_keywords(config.stt_keywords_path or None),
        ),
        # The one client that reaches the brain (or any OpenAI-compatible
        # stand-in) — see build_llm.
        llm=build_llm(config),
        tts=build_tts(config),
        # Barge-in: the spec treats interruption as a core requirement.
        # mode="vad" (default here) DISABLES the SDK's adaptive interruption
        # classifier — live sessions on 2026-07-14 showed it classifying the
        # operator's "wait wait / no no / stop stop" as backchannels
        # (num_backchannels>0, num_interruptions=0 in the metrics log) and
        # letting the agent talk over them. Plain VAD interruption + the
        # tuned min_duration is the correct behavior for this product:
        # any sustained user speech stops LKY, full stop.
        turn_handling=TurnHandlingOptions(
            interruption=InterruptionOptions(
                enabled=True,
                mode=config.interrupt_mode,
                min_duration=config.interrupt_min_duration,
                false_interruption_timeout=config.false_interrupt_timeout,
                resume_false_interruption=config.resume_false_interruption,
            ),
        ),
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

    # Issue #11: measure interruption-detected -> playback-stopped per
    # barge-in. With this agent's config (mode="vad" +
    # resume_false_interruption) the SDK stops audio via its pause path,
    # which flips the agent state away from "speaking" in the same
    # synchronous call as audio_output.pause() — so that state change is
    # the playback-stopped moment. The hard-interrupt path (pause
    # unavailable) instead reports playback_finished(interrupted=True)
    # immediately; the tracker handles both without double-counting.
    interrupts = InterruptTracker(min_duration=config.interrupt_min_duration)

    def _log_interrupt(done: InterruptLatency | None) -> None:
        if done is not None:
            logger.info("INTERRUPT %s", done.summary())

    @session.on("user_state_changed")
    def _on_user_state(ev: UserStateChangedEvent) -> None:
        interrupts.on_user_state(ev.new_state, at=ev.created_at)

    @session.on("agent_state_changed")
    def _on_agent_state(ev: AgentStateChangedEvent) -> None:
        _log_interrupt(interrupts.on_agent_state(ev.new_state, at=ev.created_at))

    async def report_status(status: str) -> None:
        # Published on the local participant; the web client watches the
        # lky.brain attribute for its busy banner / avatar error state.
        await ctx.room.local_participant.set_attributes(
            {STATUS_ATTRIBUTE: status}
        )

    async def report_tts_status(status: str) -> None:
        # Same pattern for the voice (issue #13): the web client watches
        # lky.tts for its "voice unavailable — replies continue as text"
        # slate, cleared when a later synthesis succeeds.
        await ctx.room.local_participant.set_attributes(
            {TTS_STATUS_ATTRIBUTE: status}
        )

    await session.start(
        agent=LKYAgent(
            instructions=instructions,
            report_status=report_status,
            report_tts_status=report_tts_status,
            fact_sheet_path=fact_sheet_path,
        ),
        room=ctx.room,
        room_output_options=RoomOutputOptions(
            # Publish transcriptions to the room so the web client can render
            # interim + final segments (lk.transcription text streams). The
            # SDK's transcript synchronizer (on by default) is also what makes
            # interrupted answers keep only the text actually heard.
            transcription_enabled=True,
        ),
    )

    # The room audio output only exists after session.start (RoomIO wires
    # it); subscribe here for the hard-interrupt stop path (issue #11).
    if session.output.audio is not None:

        @session.output.audio.on("playback_finished")
        def _on_playback_finished(ev: PlaybackFinishedEvent) -> None:
            _log_interrupt(
                interrupts.on_playback_finished(
                    at=time.time(), interrupted=ev.interrupted
                )
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

    # Fail fast on a bad LKY_TTS_PRONUNCIATIONS file too — a malformed JSON
    # map should refuse startup, not throw during the first spoken answer.
    if config.tts_provider == "chatterbox":
        try:
            build_pronunciation_map(config.tts_pronunciations_path or None)
        except (OSError, ValueError) as exc:
            print(f"Cannot start the voice agent: {exc}", file=sys.stderr)
            raise SystemExit(1) from None

    # Fail fast on a bad LKY_STT_KEYWORDS file (issue #45) — same reason.
    if config.stt_keywords_path:
        try:
            build_keywords(config.stt_keywords_path)
        except (OSError, ValueError) as exc:
            print(f"Cannot start the voice agent: {exc}", file=sys.stderr)
            raise SystemExit(1) from None

    # Fail fast on a bad LKY_FACT_SHEET path (issue #45) — a missing
    # fact sheet should surface at startup, not silently disable
    # grounding mid-session. An explicit empty value disables grounding.
    sheet_path = fact_sheet_path_from_env(os.environ)
    if sheet_path:
        try:
            load_fact_sheet(sheet_path)
        except OSError as exc:
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
