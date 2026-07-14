"""Per-turn latency aggregation for the walking skeleton.

Issue #4 acceptance criterion: "End-of-speech to first-audio latency with
all-stock parts measured and noted." The LiveKit Agents SDK emits three
metrics per turn, correlated by ``speech_id``:

- EOU   ``end_of_utterance_delay``  (user stopped speaking -> turn committed)
- LLM   ``ttft``                    (LLM request -> first token)
- TTS   ``ttfb``                    (TTS request -> first audio byte)

Their sum approximates end-of-speech -> first agent audio. This module is
pure logic (no SDK imports) so it can be unit-tested without mocking any
provider.
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
