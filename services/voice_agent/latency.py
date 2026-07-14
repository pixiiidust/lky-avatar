"""Per-turn latency aggregation for the walking skeleton.

Issue #4 acceptance criterion: "End-of-speech to first-audio latency with
all-stock parts measured and noted." The LiveKit Agents SDK emits three
metrics per turn, correlated by ``speech_id``:

- EOU   ``end_of_utterance_delay``  (user stopped speaking -> turn committed)
- LLM   ``ttft``                    (LLM request -> first token)
- TTS   ``ttfb``                    (TTS request -> first audio byte)

Their sum approximates end-of-speech -> first agent audio.

Issue #11 adds :class:`InterruptTracker`: barge-in responsiveness measured
from the session's own event stream (user speech onset while the agent is
speaking -> agent playback stopped). See the class docstring for how the two
SDK stop paths (pause vs. buffer-clear) map onto its inputs.

This module is pure logic (no SDK imports) so it can be unit-tested without
mocking any provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TurnLatency:
    speech_id: str
    eou_delay: float
    llm_ttft: float
    tts_ttfb: float

    @property
    def end_of_speech_to_first_audio(self) -> float:
        return self.eou_delay + self.llm_ttft + self.tts_ttfb

    def summary(self) -> str:
        return (
            f"turn {self.speech_id}: end-of-speech -> first-audio "
            f"= {self.end_of_speech_to_first_audio:.2f}s "
            f"(eou {self.eou_delay:.2f}s + llm ttft {self.llm_ttft:.2f}s "
            f"+ tts ttfb {self.tts_ttfb:.2f}s)"
        )


@dataclass
class _PartialTurn:
    eou_delay: float | None = None
    llm_ttft: float | None = None
    tts_ttfb: float | None = None


@dataclass
class LatencyTracker:
    """Collects the three per-turn metrics and yields a TurnLatency when a
    turn is complete. Negative values (the SDK's 'not measured' sentinel,
    e.g. a generation cancelled by barge-in before first token) are ignored,
    so interrupted turns never produce a bogus number."""

    _turns: dict[str, _PartialTurn] = field(default_factory=dict)
    completed: list[TurnLatency] = field(default_factory=list)

    def record(self, kind: str, speech_id: str, value: float) -> TurnLatency | None:
        """Record one measurement.

        kind: "eou" | "llm" | "tts". Unknown kinds and unusable values are
        ignored. Returns the completed TurnLatency the moment the third
        measurement for a speech_id arrives, else None.
        """
        if not speech_id or value is None or value < 0:
            return None
        turn = self._turns.setdefault(speech_id, _PartialTurn())
        if kind == "eou":
            turn.eou_delay = value
        elif kind == "llm":
            turn.llm_ttft = value
        elif kind == "tts":
            turn.tts_ttfb = value
        else:
            return None

        if turn.eou_delay is None or turn.llm_ttft is None or turn.tts_ttfb is None:
            return None

        done = TurnLatency(
            speech_id=speech_id,
            eou_delay=turn.eou_delay,
            llm_ttft=turn.llm_ttft,
            tts_ttfb=turn.tts_ttfb,
        )
        del self._turns[speech_id]
        self.completed.append(done)
        return done


@dataclass(frozen=True)
class InterruptLatency:
    """One measured barge-in: user speech onset -> agent playback stopped.

    ``onset_to_stopped`` is raw and includes the configured VAD
    min-interrupt window (the agent deliberately waits ``min_duration``
    seconds of sustained speech before treating it as an interruption), so
    ``detected_to_stopped`` — the gate's "interruption detected -> playback
    stopped" figure — subtracts it.
    """

    onset_to_stopped: float
    min_duration: float

    @property
    def detected_to_stopped(self) -> float:
        return max(0.0, self.onset_to_stopped - self.min_duration)

    def summary(self) -> str:
        return (
            f"barge-in: user-speech-onset -> playback-stopped "
            f"= {self.onset_to_stopped * 1000:.0f} ms raw "
            f"(includes the {self.min_duration * 1000:.0f} ms "
            f"min-interrupt window; detected -> stopped "
            f"~ {self.detected_to_stopped * 1000:.0f} ms)"
        )


@dataclass
class InterruptTracker:
    """Measures interruption-to-silence from session events (issue #11).

    Inputs map onto livekit-agents 1.6.5 behavior (verified in
    voice/agent_activity.py and voice/room_io/_output.py):

    - ``on_user_state("speaking", at)`` — VAD start-of-speech. While the
      agent is speaking this arms a pending barge-in at ``at``.
    - ``on_agent_state(state, at)`` — with the deployed config
      (interruption mode "vad" + resume_false_interruption, room audio
      output ``can_pause``) the SDK's *pause path* stops playback: it calls
      ``audio_output.pause()`` and flips the agent state away from
      "speaking" in the same synchronous call. So agent-state leaving
      "speaking" while a barge-in is pending IS the playback-stopped
      moment. A new "speaking" state clears any stale pending onset.
    - ``on_playback_finished(at, interrupted)`` — the *hard-interrupt
      path* (pause unavailable/disabled): ``SpeechHandle.interrupt()``
      clears the audio buffer and the output reports
      ``playback_finished(interrupted=True)`` immediately. In the pause
      path this event only fires much later (when the user's turn
      commits), by which time the pending onset has been consumed, so it
      never double-counts.

    A pending onset is discarded when the user stops speaking before any
    stop occurred (speech shorter than the min-interrupt window never
    interrupts) and windows longer than ``max_window`` are treated as "the
    agent finished on its own", not as an interruption measurement.
    """

    #: The configured InterruptionOptions.min_duration (LKY_INTERRUPT_MIN_SEC).
    min_duration: float = 0.3
    #: Longest plausible onset->stop window; anything above is discarded.
    max_window: float = 10.0

    completed: list[InterruptLatency] = field(default_factory=list)
    _agent_speaking: bool = False
    _onset_at: float | None = None

    def on_user_state(self, state: str, at: float) -> None:
        if state == "speaking":
            if self._agent_speaking:
                self._onset_at = at
        else:
            # The user stopped (or went away) before playback stopped: a
            # too-short interjection that never triggered an interruption.
            self._onset_at = None

    def on_agent_state(self, state: str, at: float) -> InterruptLatency | None:
        if state == "speaking":
            self._agent_speaking = True
            self._onset_at = None  # a new speech invalidates stale onsets
            return None
        was_speaking = self._agent_speaking
        self._agent_speaking = False
        if was_speaking and self._onset_at is not None:
            return self._complete(at)
        return None

    def on_playback_finished(
        self, at: float, interrupted: bool
    ) -> InterruptLatency | None:
        if interrupted and self._onset_at is not None:
            return self._complete(at)
        return None

    def _complete(self, at: float) -> InterruptLatency | None:
        assert self._onset_at is not None
        elapsed = at - self._onset_at
        self._onset_at = None
        if elapsed < 0 or elapsed > self.max_window:
            return None
        done = InterruptLatency(
            onset_to_stopped=elapsed, min_duration=self.min_duration
        )
        self.completed.append(done)
        return done
