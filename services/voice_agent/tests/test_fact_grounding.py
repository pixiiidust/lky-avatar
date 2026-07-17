"""Fact-grounding retrieval + injection seam (issue #45): pure logic —
section parsing, keyword retrieval, grounding block rendering, and the
no-op/empty-path behavior. No SDK, no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fact_grounding import (
    FactSection,
    build_grounding_block,
    default_fact_sheet_path,
    grounding_for_turn,
    load_fact_sheet,
    retrieve,
)
from persona_prompt import build_instructions, fact_sheet_path_from_env

#: The committed fact sheet — the live-session failure fix is anchored here.
REPO_ROOT = Path(__file__).resolve().parents[3]
FACT_SHEET = REPO_ROOT / "assets" / "persona" / "lky_facts.md"


# ── fact sheet shape ────────────────────────────────────────────────────────


def test_fact_sheet_exists_and_is_committed():
    assert FACT_SHEET.is_file(), f"missing fact sheet: {FACT_SHEET}"


def test_fact_sheet_has_expected_sections():
    sections = load_fact_sheet(FACT_SHEET)
    titles = {s.title for s in sections}
    # The issue's core fact families must all be present.
    assert "Constituencies and offices" in titles
    assert "Public housing and the HDB" in titles
    assert "Water and self-sufficiency" in titles
    assert "Family basics" in titles
    assert "Critical correction" in titles


def test_sections_have_keywords():
    sections = load_fact_sheet(FACT_SHEET)
    for s in sections:
        assert s.keywords, f"section {s.title!r} has no keywords"


def test_load_missing_file_raises():
    with pytest.raises(OSError):
        load_fact_sheet(REPO_ROOT / "assets" / "persona" / "does_not_exist.md")


# ── retrieval ───────────────────────────────────────────────────────────────


def test_toa_payoh_constituency_question_retrieves_constituencies_section():
    """The exact live-session failure: a Toa Payoh / Ang Mo Kio question
    must retrieve the Constituencies section (which contains the
    Tanjong Pagar correction), not be silently dropped."""
    sections = load_fact_sheet(FACT_SHEET)
    turn = "What was your constituency? Did you represent Toa Payoh or Ang Mo Kio?"
    r = retrieve(turn, sections)
    titles = [s.title for s in r]
    assert "Constituencies and offices" in titles


def test_hdb_question_retrieves_hdb_section():
    sections = load_fact_sheet(FACT_SHEET)
    r = retrieve("When was the home ownership scheme introduced?", sections)
    assert any("HDB" in s.title or "housing" in s.title.lower() for s in r)


def test_water_question_retrieves_water_section():
    sections = load_fact_sheet(FACT_SHEET)
    r = retrieve("What were the Water Agreements with Malaysia?", sections)
    titles = [s.title for s in r]
    assert any("Water" in t for t in titles)


def test_unrelated_turn_returns_empty():
    """No keyword match -> no injection (no spurious grounding)."""
    sections = load_fact_sheet(FACT_SHEET)
    r = retrieve("What do you think of artificial intelligence?", sections)
    assert r == []


def test_empty_sheet_returns_empty():
    assert retrieve("anything", []) == []


def test_top_k_limits_results():
    sections = load_fact_sheet(FACT_SHEET)
    # A turn that matches many sections should still cap at top_k.
    turn = "Tell me about constituencies, HDB, water, independence, and your family."
    r = retrieve(turn, sections, top_k=2)
    assert len(r) <= 2


# ── grounding block rendering ───────────────────────────────────────────────


def test_build_grounding_block_includes_preamble_and_sections():
    sections = load_fact_sheet(FACT_SHEET)
    r = retrieve("What was your constituency? Toa Payoh?", sections)
    block = build_grounding_block(r)
    assert "Trust these dates" in block
    assert "Tanjong Pagar" in block
    assert "do not quote these facts verbatim".lower() in block.lower()


def test_build_grounding_block_empty_is_empty_string():
    assert build_grounding_block([]) == ""


def test_grounding_block_includes_uncertainty_guardrail():
    """Issue #45 scope item 4: the guardrail must appear in every
    non-empty grounding block."""
    sections = load_fact_sheet(FACT_SHEET)
    r = retrieve("What was your constituency?", sections)
    block = build_grounding_block(r)
    assert "uncertain" in block.lower() or "not certain" in block.lower()
    assert "general terms" in block.lower()


# ── no-op / disabled behavior ────────────────────────────────────────────────


def test_grounding_for_turn_empty_path_is_noop():
    assert grounding_for_turn("What was your constituency?", None) == ""
    assert grounding_for_turn("What was your constituency?", "") == ""


def test_grounding_for_turn_missing_file_is_noop():
    """A bad path returns "" rather than raising — a live session must
    not crash on a misconfigured path."""
    assert grounding_for_turn(
        "What was your constituency?", "/nonexistent/path.md"
    ) == ""


# ── integration with build_instructions ────────────────────────────────────


def test_build_instructions_with_real_grounding_preserves_persona_and_style():
    """The full production path: retrieve + inject into instructions. The
    persona framing must stay first, the style policy last, and the facts
    in the middle — the voice is not flattened."""
    block = grounding_for_turn(
        "What was your constituency? Toa Payoh?", str(FACT_SHEET)
    )
    assert block  # sanity: the turn matched something
    instructions = build_instructions("2026-07-13", "C", grounding_block=block)
    assert "Tanjong Pagar" in instructions
    assert instructions.endswith(
        "No markdown, no lists, no headings, no stage directions."
    )


# ── env path resolution ─────────────────────────────────────────────────────


def test_fact_sheet_path_from_env_defaults_to_committed_sheet():
    path = fact_sheet_path_from_env({})
    # Compare as Path parts, not a substring: Windows returns backslashes.
    assert Path(path).parts[-3:] == ("assets", "persona", "lky_facts.md")
    assert Path(path).is_file()


def test_fact_sheet_path_from_env_explicit_disable():
    """LKY_FACT_SHEET='' explicitly disables grounding."""
    assert fact_sheet_path_from_env({"LKY_FACT_SHEET": ""}) == ""


def test_fact_sheet_path_from_env_custom_relative():
    path = fact_sheet_path_from_env({"LKY_FACT_SHEET": "evals/foo.md"})
    assert Path(path).parts[-2:] == ("evals", "foo.md")
