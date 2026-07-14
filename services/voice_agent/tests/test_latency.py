"""Unit tests for per-turn latency aggregation (pure logic, no SDK)."""

from latency import LatencyTracker, TurnLatency


def test_turn_completes_when_all_three_metrics_arrive():
    t = LatencyTracker()
    assert t.record("eou", "s1", 0.5) is None
    assert t.record("llm", "s1", 0.8) is None
    done = t.record("tts", "s1", 0.3)
    assert isinstance(done, TurnLatency)
    assert done.speech_id == "s1"
    assert done.end_of_speech_to_first_audio == 0.5 + 0.8 + 0.3


def test_arrival_order_does_not_matter():
    t = LatencyTracker()
    assert t.record("tts", "s1", 0.3) is None
    assert t.record("eou", "s1", 0.5) is None
    assert t.record("llm", "s1", 0.8) is not None


def test_turns_are_tracked_independently_by_speech_id():
    t = LatencyTracker()
    t.record("eou", "s1", 0.5)
    t.record("eou", "s2", 0.6)
    t.record("llm", "s1", 0.8)
    t.record("llm", "s2", 0.9)
    done2 = t.record("tts", "s2", 0.1)
    assert done2 is not None and done2.speech_id == "s2"
    done1 = t.record("tts", "s1", 0.2)
    assert done1 is not None and done1.speech_id == "s1"
    assert [x.speech_id for x in t.completed] == ["s2", "s1"]


def test_negative_values_are_ignored_interrupted_turns_never_complete():
    # The SDK reports negative sentinels when a stage was cancelled by
    # barge-in before it measured anything.
    t = LatencyTracker()
    t.record("eou", "s1", 0.5)
    t.record("llm", "s1", -1.0)
    assert t.record("tts", "s1", 0.3) is None
    assert t.completed == []


def test_unknown_kind_and_empty_speech_id_ignored():
    t = LatencyTracker()
    assert t.record("vad", "s1", 0.5) is None
    assert t.record("eou", "", 0.5) is None
    assert t.completed == []


def test_summary_contains_total_and_components():
    done = TurnLatency(speech_id="s9", eou_delay=0.5, llm_ttft=1.0, tts_ttfb=0.25)
    s = done.summary()
    assert "1.75s" in s
    assert "s9" in s
