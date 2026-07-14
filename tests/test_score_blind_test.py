"""Unit tests for scripts/score_blind_test.py — pure logic only.

Per the testing standards (spec.md), audio metrics (embeddings, whisper,
waveform analysis) are NOT unit-tested — they are the scripted-benchmark
layer. These cover the WER implementation, transcript normalization,
synthesis-log parsing, aggregation, and the composite ranking /
disqualification rules. Importing the module must not pull in numpy, torch,
or any audio stack (asserted below) so this suite runs on Windows Python.
"""
import sys

import pytest

from scripts.score_blind_test import (
    WER_DISQUALIFY,
    aggregate_condition,
    format_ranking_table,
    normalize_for_wer,
    parse_synthesis_log,
    rank_conditions,
    wer,
)


def test_importing_module_does_not_import_audio_stacks():
    for heavy in ("numpy", "torch", "resemblyzer", "faster_whisper",
                  "soundfile", "librosa"):
        assert heavy not in sys.modules, f"{heavy} imported eagerly"


# --- normalize_for_wer ------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Singapore works. That is my answer!", "singapore works that is my answer"),
    ("neither's enemies — and more", "neithers enemies and more"),
    ("  spaced   out\ttext ", "spaced out text"),
    # number handling: whisper writes digits where the script spells them out;
    # both sides must normalize to the same tokens.
    ("over eighty per cent of Singaporeans", "over 80 percent of singaporeans"),
    ("over 80% of Singaporeans", "over 80 percent of singaporeans"),
    ("thirty-one years", "31 years"),
    ("after 31 years", "after 31 years"),
    ("about five hundred dollars", "about 500 dollars"),
    ("about $500", "about 500 dollars"),
    ("over twelve thousand. Numbers", "over 12000 numbers"),
    ("over $12,000", "over 12000 dollars"),
    ("two million people", "2000000 people"),
    ("in August 1965", "in august 1965"),
    ("One man, at the right moment", "1 man at the right moment"),
])
def test_normalize_for_wer(raw, expected):
    assert normalize_for_wer(raw) == expected.split()


def test_number_normalization_makes_digit_and_word_forms_equal():
    ref = normalize_for_wer(
        "I stepped down as Prime Minister in November 1990, after thirty-one "
        "years. By then our per capita income had risen from about five "
        "hundred dollars to over twelve thousand.")
    hyp = normalize_for_wer(
        "I stepped down as Prime Minister in November 1990 after 31 years. "
        "By then our per capita income had risen from about $500 to over "
        "twelve thousand.")
    assert wer(ref, hyp) == 0.0


# --- wer --------------------------------------------------------------------

def test_wer_identical_is_zero():
    words = "we got on with the job".split()
    assert wer(words, list(words)) == 0.0


def test_wer_one_substitution_in_five():
    assert wer("a b c d e".split(), "a b x d e".split()) == pytest.approx(0.2)


def test_wer_deletion_and_insertion():
    assert wer("a b c d".split(), "a b d".split()) == pytest.approx(0.25)
    assert wer("a b d".split(), "a b c d".split()) == pytest.approx(1 / 3)


def test_wer_empty_hypothesis_is_total_error():
    assert wer("a b c".split(), []) == 1.0


def test_wer_empty_reference():
    assert wer([], []) == 0.0
    assert wer([], ["anything"]) == 1.0


def test_wer_can_exceed_one_on_heavy_insertion():
    assert wer(["a"], "a b c d".split()) == 3.0


def test_wer_end_to_end_with_normalization():
    ref = normalize_for_wer("In August 1965 we were expelled from Malaysia.")
    hyp = normalize_for_wer("in august 1965, we were expelled from malaysia")
    assert wer(ref, hyp) == 0.0


# --- parse_synthesis_log ------------------------------------------------------

LOG_LINES = [
    '{"event": "session", "engine": "chatterbox", "era": "2005", "device": "cuda", "seed": 7}',
    '{"response": 1, "seconds": 9.1, "audio_seconds": 12.0, "rtf": 0.76, "file": "response_01.wav"}',
    "not json at all",
    '{"event": "session", "engine": "chatterbox", "era": "2005", "device": "cuda", "seed": 7, "load_seconds": 9.5}',
    '{"response": 1, "seconds": 4.0, "audio_seconds": 12.0, "rtf": 0.33, "file": "response_01.wav"}',
    '{"response": 2, "seconds": 5.5, "audio_seconds": 11.0, "rtf": 0.5, "file": "response_02.wav"}',
    "",
]


def test_parse_synthesis_log_last_record_wins_and_sessions_skipped():
    records, session = parse_synthesis_log(LOG_LINES)
    assert set(records) == {1, 2}
    assert records[1]["rtf"] == 0.33          # re-run superseded the first try
    assert records[2]["seconds"] == 5.5
    assert session["load_seconds"] == 9.5     # last session line wins


def test_parse_synthesis_log_empty():
    records, session = parse_synthesis_log([])
    assert records == {} and session == {}


# --- aggregate_condition ------------------------------------------------------

def _sample(**kw):
    base = {"failed": False, "sim_primary": 0.8, "sim_own_era": 0.82,
            "wer": 0.05, "clipping_ratio": 0.0, "internal_silence_ratio": 0.1,
            "pacing_ratio": 1.0, "duration_suspect": False,
            "synth_rtf": 0.5, "synth_seconds": 5.0}
    base.update(kw)
    return base


def test_aggregate_condition_means_min_and_failures():
    rows = [
        _sample(sim_primary=0.80, wer=0.10, synth_rtf=0.4),
        _sample(sim_primary=0.70, wer=0.00, synth_rtf=0.6),
        {"failed": True, "failure_reason": "missing output",
         "synth_seconds": None, "synth_rtf": None},
    ]
    agg = aggregate_condition(rows)
    assert agg["n_expected"] == 3
    assert agg["n_scored"] == 2
    assert agg["failures"] == 1
    assert agg["mean_sim_primary"] == pytest.approx(0.75)
    assert agg["min_sim_primary"] == pytest.approx(0.70)
    assert agg["mean_wer"] == pytest.approx(0.05)
    assert agg["max_wer"] == pytest.approx(0.10)
    assert agg["mean_rtf"] == pytest.approx(0.5)


def test_aggregate_condition_ignores_missing_metrics():
    rows = [_sample(synth_rtf=None, synth_seconds=None),
            _sample(synth_rtf=0.4)]
    agg = aggregate_condition(rows)
    assert agg["mean_rtf"] == pytest.approx(0.4)   # None excluded, not zeroed


def test_aggregate_condition_all_failed():
    rows = [{"failed": True, "failure_reason": "missing output"}] * 2
    agg = aggregate_condition(rows)
    assert agg["failures"] == 2
    assert agg["mean_sim_primary"] is None
    assert agg["mean_wer"] is None


# --- rank_conditions ----------------------------------------------------------

def _agg(sim, wer_=0.05, failures=0, rtf=0.5, min_sim=None):
    return {"n_expected": 20, "n_scored": 20 - failures, "failures": failures,
            "mean_sim_primary": sim, "min_sim_primary": min_sim or sim,
            "mean_sim_own_era": sim, "mean_wer": wer_, "max_wer": wer_,
            "mean_clipping_ratio": 0.0, "mean_internal_silence_ratio": 0.1,
            "mean_pacing_ratio": 1.0, "n_duration_suspect": 0,
            "mean_rtf": rtf, "mean_synth_seconds": 5.0}


def test_ranking_orders_by_primary_similarity():
    rows = rank_conditions({"a-2005": _agg(0.70), "b-2005": _agg(0.80),
                            "c-1990": _agg(0.75)})
    assert [r["condition"] for r in rows] == ["b-2005", "c-1990", "a-2005"]
    assert [r["rank"] for r in rows] == [1, 2, 3]
    assert all(r["qualified"] for r in rows)


def test_ranking_disqualifies_high_wer_even_with_best_similarity():
    rows = rank_conditions({"good": _agg(0.70, wer_=0.05),
                            "similar-but-garbled": _agg(0.90, wer_=WER_DISQUALIFY + 0.01)})
    assert rows[0]["condition"] == "good"
    assert not rows[1]["qualified"]
    assert "WER" in rows[1]["disqualify_reasons"][0]


def test_ranking_wer_exactly_at_limit_is_qualified():
    rows = rank_conditions({"edge": _agg(0.8, wer_=WER_DISQUALIFY)})
    assert rows[0]["qualified"]


def test_ranking_disqualifies_any_synthesis_failure():
    rows = rank_conditions({"flaky": _agg(0.9, failures=1),
                            "solid": _agg(0.6)})
    assert rows[0]["condition"] == "solid"
    assert not rows[1]["qualified"]
    assert "failure" in rows[1]["disqualify_reasons"][0]


def test_ranking_tie_breaks_by_wer_then_rtf():
    rows = rank_conditions({
        "tie-worse-wer": _agg(0.800, wer_=0.10, rtf=0.2),
        "tie-better-wer": _agg(0.801, wer_=0.02, rtf=0.9),
    })
    assert rows[0]["condition"] == "tie-better-wer"

    rows = rank_conditions({
        "tie-slow": _agg(0.800, wer_=0.05, rtf=0.9),
        "tie-fast": _agg(0.801, wer_=0.05, rtf=0.2),
    })
    assert rows[0]["condition"] == "tie-fast"


def test_ranking_clear_similarity_gap_beats_wer_tiebreak():
    rows = rank_conditions({
        "high-sim": _agg(0.85, wer_=0.10),
        "low-sim-clean": _agg(0.70, wer_=0.00),
    })
    assert rows[0]["condition"] == "high-sim"


def test_ranking_all_failed_condition_has_reasons_and_sinks():
    rows = rank_conditions({
        "dead": {**_agg(None, wer_=None, failures=20, rtf=None),
                 "mean_sim_primary": None, "min_sim_primary": None,
                 "mean_wer": None},
        "alive": _agg(0.5),
    })
    assert rows[0]["condition"] == "alive"
    dead = rows[1]
    assert not dead["qualified"]
    assert any("failure" in r for r in dead["disqualify_reasons"])


def test_format_ranking_table_smoke():
    rows = rank_conditions({"xtts-2005": _agg(0.8), "f5-2005": _agg(0.7, failures=2)})
    table = format_ranking_table(rows)
    assert "xtts-2005" in table and "f5-2005" in table
    assert "DISQUALIFIED" in table
