"""Fact-anchored eval subset (issue #45): shape + answer-key coverage.
Pure JSON validation — no model, no SDK."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
QUESTIONS_PATH = REPO_ROOT / "evals" / "fact_grounding_questions.json"
FACT_SHEET = REPO_ROOT / "assets" / "persona" / "lky_facts.md"


def _load():
    return json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))


def test_subset_has_10_to_15_questions():
    data = _load()
    qs = data["questions"]
    assert 10 <= len(qs) <= 15, f"expected 10-15 questions, got {len(qs)}"


def test_every_question_has_answer_key():
    """Each question must have a known-correct answer in answer_keys so the
    factual-accuracy signal is judgeable."""
    data = _load()
    keys = set(data["answer_keys"])
    for q in data["questions"]:
        assert q["id"] in keys, f"missing answer key for {q['id']}"


def test_signal_separation_fields_present():
    """The eval must separate factual_accuracy from persona_quality."""
    data = _load()
    sep = data["signal_separation"]
    assert "factual_accuracy" in sep
    assert "persona_quality" in sep
    assert "fabrication_detected" in sep


def test_toa_payoh_constituency_class_is_covered():
    """The live-session failure class (Toa Payoh / Ang Mo Kio /
    constituency) must be in the subset."""
    data = _load()
    text = " ".join(q["question"] for q in data["questions"])
    assert "Toa Payoh" in text
    assert "constituency" in text.lower()


def test_hdb_timeline_class_is_covered():
    data = _load()
    text = " ".join(q["question"] for q in data["questions"])
    assert "HDB" in text or "home ownership" in text.lower()


def test_answer_key_for_constituency_question_mentions_tanjong_pagar():
    data = _load()
    # The f01 answer key must contain the Tanjong Pagar correction.
    assert "Tanjong Pagar" in data["answer_keys"]["f01"]
