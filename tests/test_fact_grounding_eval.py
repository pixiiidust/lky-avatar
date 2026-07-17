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


# ── Fix #5 (issue #45 review HOLD): corrected, auditable answer keys ──────
#
# The parent fact-check (task t_189455a2) flagged five correctness gaps in
# the original sheet/keys. These pins guard each correction so a future edit
# cannot silently regress the audited facts. Sources are cited per-section
# in the fact sheet itself (lky_facts.md > sources: lines).


def test_f02_distinguishes_self_government_from_pm_swearing_in():
    """3 June 1959 = self-government proclamation; 5 June 1959 = LKY sworn
    in as PM. The original key conflated them; the corrected key must name
    both dates distinctly."""
    k = _load()["answer_keys"]["f02"]
    assert "3 June 1959" in k
    assert "5 June 1959" in k


def test_f05_toa_payoh_is_first_hdb_built_not_first_satellite():
    """Toa Payoh = first town built SOLELY by HDB; Queenstown was the first
    satellite town overall (built by the SIT). The original key implied Toa
    Payoh was the first satellite town, which would penalize a correct
    answer that names Queenstown first."""
    k = _load()["answer_keys"]["f05"].lower()
    assert "first town built solely by" in k
    assert "hdb" in k
    assert "queenstown" in k
    assert "second satellite town" in k


def test_f04_distinguishes_home_ownership_launch_from_cpf_use():
    """Home Ownership scheme launched 1964; CPF savings allowed for HDB
    mortgages from 1968 — two separate milestones the original key merged."""
    k = _load()["answer_keys"]["f04"]
    assert "1964" in k
    assert "1968" in k
    assert "1968" not in k.split("1964")[0]  # 1968 comes after 1964 textually


def test_f05_fact_sheet_cites_toa_payoh_and_queenstown():
    """The fact sheet (not just the answer key) must carry the Queenstown
    / Toa Payoh distinction so the grounded brain reads the correction."""
    text = FACT_SHEET.read_text(encoding="utf-8")
    assert "Queenstown" in text
    assert "first town built solely by the HDB" in text


def test_fact_sheet_distinguishes_self_government_from_pm_dates():
    """The fact sheet must carry the 3 June / 5 June distinction so the
    grounded brain reads it, not just the answer key."""
    text = FACT_SHEET.read_text(encoding="utf-8")
    assert "3 June 1959" in text
    assert "5 June 1959" in text
    # The distinction must be called out explicitly, not just two dates
    # sitting near each other.
    assert "proclamation" in text.lower()


def test_fact_sheet_distinguishes_home_ownership_from_cpf():
    text = FACT_SHEET.read_text(encoding="utf-8")
    assert "Home Ownership for the People scheme" in text
    assert "1968" in text
    assert "1968" in text.split("1964")[1]  # 1968 appears after 1964


def test_fact_sheet_uses_stop_at_two_as_campaign_name():
    """The official campaign name is "Stop at Two"; "Two is Enough" is a
    poster slogan, not the campaign name. The sheet must use the canonical
    name and flag the slogan as a slogan, not the name."""
    text = FACT_SHEET.read_text(encoding="utf-8")
    assert "Stop at Two" in text
    # The slogan must appear but must be labeled as a slogan, not as the
    # campaign name.
    assert "Two is Enough" in text or "Girl or Boy, Two is Enough" in text


def test_fact_sheet_has_per_section_source_citations():
    """Every section must end with a ``> sources:`` line naming the
    primary-source institution(s) so the sheet is auditable from its own
    references — the auditability gap the parent fact-check flagged."""
    text = FACT_SHEET.read_text(encoding="utf-8")
    # Count sections and source lines. A section is a "## Section:" header;
    # a source line is a "> sources:" line.
    import re

    n_sections = len(re.findall(r"^##\s+Section:\s", text, re.MULTILINE))
    n_sources = len(re.findall(r"^>\s*sources:\s", text, re.MULTILINE))
    assert n_sources == n_sections, (
        f"every section needs a sources line: "
        f"{n_sections} sections, {n_sources} source lines"
    )

