"""Unit tests for barge-in interrupt latency (issue #11 — pure logic, no SDK).

The tracker's inputs mirror livekit-agents 1.6.5 session events; the two SDK
stop paths (pause vs. hard buffer-clear) are exercised separately, including
the ordering that must never double-count one barge-in.
"""

from latency import InterruptLatency, InterruptTracker


def _speaking_agent(t: InterruptTracker) -> None:
    assert t.on_agent_state("speaking", at=100.0) is None


def test_pause_path_agent_state_leaving_speaking_completes():
    # Deployed config: interruption pauses playback and flips the agent
    # state away from "speaking" in the same call — that is the stop.
    t = InterruptTracker(min_duration=0.3)
    _speaking_agent(t)
    t.on_user_state("speaking", at=101.0)
    done = t.on_agent_state("listening", at=101.42)
    assert isinstance(done, InterruptLatency)
    assert abs(done.onset_to_stopped - 0.42) < 1e-9
    assert abs(done.detected_to_stopped - 0.12) < 1e-9


def test_hard_path_playback_finished_interrupted_completes():
    t = InterruptTracker(min_duration=0.3)
    _speaking_agent(t)
    t.on_user_state("speaking", at=101.0)
    done = t.on_playback_finished(at=101.5, interrupted=True)
    assert done is not None
    assert abs(done.onset_to_stopped - 0.5) < 1e-9


def test_hard_path_followed_by_state_change_counts_once():
    # After a hard interrupt the agent state also leaves "speaking";
    # the onset was consumed, so no second measurement appears.
    t = InterruptTracker()
    _speaking_agent(t)
    t.on_user_state("speaking", at=101.0)
    assert t.on_playback_finished(at=101.5, interrupted=True) is not None
    assert t.on_agent_state("listening", at=101.6) is None
    assert len(t.completed) == 1


def test_pause_path_late_playback_finished_does_not_double_count():
    # In the pause path playback_finished(interrupted=True) arrives only
    # when the user's turn commits, seconds after the pause stopped audio.
    t = InterruptTracker()
    _speaking_agent(t)
    t.on_user_state("speaking", at=101.0)
    assert t.on_agent_state("listening", at=101.4) is not None
    assert t.on_playback_finished(at=103.0, interrupted=True) is None
    assert len(t.completed) == 1


def test_user_speech_while_agent_silent_never_arms():
    t = InterruptTracker()
    t.on_user_state("speaking", at=101.0)  # a normal turn, not a barge-in
    assert t.on_agent_state("thinking", at=102.0) is None
    assert t.on_playback_finished(at=103.0, interrupted=True) is None
    assert t.completed == []


def test_short_interjection_that_never_interrupted_is_discarded():
    # The user stopped speaking before any stop happened (< min-interrupt
    # window, e.g. a cough): the later natural end of speech is NOT a stop.
    t = InterruptTracker()
    _speaking_agent(t)
    t.on_user_state("speaking", at=101.0)
    t.on_user_state("listening", at=101.15)
    assert t.on_agent_state("listening", at=104.0) is None
    assert t.completed == []


def test_new_agent_speech_clears_stale_onset():
    t = InterruptTracker()
    _speaking_agent(t)
    t.on_user_state("speaking", at=101.0)
    _speaking_agent(t)  # a new answer started; the old onset is moot
    assert t.on_agent_state("listening", at=102.0) is None
    assert t.completed == []


def test_uninterrupted_playback_finished_records_nothing():
    t = InterruptTracker()
    _speaking_agent(t)
    t.on_user_state("speaking", at=101.0)
    assert t.on_playback_finished(at=101.5, interrupted=False) is None
    assert t.completed == []


def test_windows_beyond_max_are_treated_as_natural_end():
    t = InterruptTracker(max_window=10.0)
    _speaking_agent(t)
    t.on_user_state("speaking", at=101.0)
    assert t.on_agent_state("listening", at=115.0) is None
    assert t.completed == []


def test_negative_window_is_discarded():
    t = InterruptTracker()
    _speaking_agent(t)
    t.on_user_state("speaking", at=101.0)
    assert t.on_agent_state("listening", at=100.9) is None
    assert t.completed == []


def test_detected_to_stopped_floors_at_zero():
    done = InterruptLatency(onset_to_stopped=0.2, min_duration=0.3)
    assert done.detected_to_stopped == 0.0


def test_summary_contains_raw_and_detected_milliseconds():
    done = InterruptLatency(onset_to_stopped=0.42, min_duration=0.3)
    s = done.summary()
    assert "420 ms raw" in s
    assert "120 ms" in s
    assert "min-interrupt window" in s
