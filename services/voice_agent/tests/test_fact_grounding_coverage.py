"""Issue #45 fix #4: deterministic expected-section coverage for every one of
the 12 fact-grounding eval questions.

Before this fix, two questions retrieved the wrong section:

- f11 ("Tell me about your wife and her role.") retrieved **nothing** — the
  word "wife" was not a keyword, so the Family section never matched and the
  grounding was a silent no-op for a question that *should* be grounded.
- f07 ("On what date did Singapore become independent...") retrieved the
  Constituencies section first (wrong) instead of the Independence section.

Both are fixed by the ``> keywords:`` metadata lines in the fact sheet
(explicit aliases like ``wife``, ``independent``, ``independence``) plus
trimming over-broad aliases from the Critical-correction section that were
matching common words. This test pins the fix: each of the 12 questions
must retrieve its intended primary section as the **top** result.

Pure logic — no SDK, no network. Runs under the root pytest (imports the
module by path) and under the voice_agent venv.
"""

from __future__ import annotations

import json
import pathlib
import sys

# Make ``fact_grounding`` importable whether this runs from the voice_agent
# venv (cwd on sys.path) or from the repo root pytest (scripts/ not needed
# here; we add the voice_agent dir).
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
VOICE_AGENT = REPO_ROOT / "services" / "voice_agent"
if str(VOICE_AGENT) not in sys.path:
    sys.path.insert(0, str(VOICE_AGENT))

from fact_grounding import load_fact_sheet, retrieve  # noqa: E402

FACT_SHEET = REPO_ROOT / "assets" / "persona" / "lky_facts.md"
QUESTIONS = REPO_ROOT / "evals" / "fact_grounding_questions.json"

#: The intended primary section title for each eval question id. This is the
#: contract: the fact sheet's structure + keyword metadata must route every
#: question to its correct section. If a refactor breaks routing, this table
#: fails before the eval reaches a live brain.
EXPECTED_PRIMARY: dict[str, str] = {
    "f01": "Constituencies and offices",
    "f02": "Constituencies and offices",
    "f03": "Constituencies and offices",
    "f04": "Public housing and the HDB",
    "f05": "Public housing and the HDB",
    "f06": "Independence, merger, and separation timeline",
    "f07": "Independence, merger, and separation timeline",
    "f08": "Water and self-sufficiency",
    "f09": "Key policies (selected, high-signal)",
    "f10": "Key policies (selected, high-signal)",
    "f11": "Family basics",
    "f12": "Family basics",
}


def _load_questions() -> list[dict]:
    data = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    return data["questions"]


def test_every_question_has_an_expected_primary_section():
    """Sanity: the EXPECTED_PRIMARY table covers all 12 questions, no
    more, no less. A drift between the eval file and this test is a
    signal that the table needs updating, not a silent pass."""
    qs = _load_questions()
    ids = {q["id"] for q in qs}
    assert set(EXPECTED_PRIMARY) == ids, (
        "EXPECTED_PRIMARY ids do not match eval question ids; "
        f"missing={ids - set(EXPECTED_PRIMARY)}, "
        f"extra={set(EXPECTED_PRIMARY) - ids}"
    )


def test_every_question_retrieves_its_intended_primary_section():
    """The core fix #4 assertion: for each of the 12 fact eval questions,
    the top-1 retrieved section must be the intended primary section.
    Catches the two regressions this fix addresses (f11 empty, f07 wrong)
    and guards against future keyword/sheet drift on any of the 12."""
    sections = load_fact_sheet(FACT_SHEET)
    qs = _load_questions()
    failures: list[str] = []
    for q in qs:
        r = retrieve(q["question"], sections, top_k=1)
        if not r:
            failures.append(
                f"{q['id']}: no section retrieved for {q['question']!r}"
            )
            continue
        got = r[0].title
        want = EXPECTED_PRIMARY[q["id"]]
        if got != want:
            failures.append(
                f"{q['id']}: expected top-1={want!r}, got {got!r} "
                f"for {q['question']!r}"
            )
    assert not failures, "retrieval routing regressions:\n  " + "\n  ".join(
        failures
    )


def test_f11_wife_question_retrieves_family_section():
    """The specific pre-fix bug: ``Tell me about your wife and her role.``
    returned [] because ``wife`` was not a keyword. Pin it explicitly so a
    future keyword prune cannot silently re-break it."""
    sections = load_fact_sheet(FACT_SHEET)
    r = retrieve("Tell me about your wife and her role.", sections, top_k=1)
    assert r, "f11 retrieved nothing (the pre-fix bug)"
    assert r[0].title == "Family basics"


def test_f07_independence_question_retrieves_independence_section():
    """The specific pre-fix bug: the independence question routed to the
    Constituencies section first. Pin the correct routing."""
    sections = load_fact_sheet(FACT_SHEET)
    r = retrieve(
        "On what date did Singapore become independent, and was it won "
        "by armed struggle?",
        sections,
        top_k=1,
    )
    assert r[0].title == "Independence, merger, and separation timeline"


def test_no_question_retrieves_nothing():
    """Every one of the 12 must retrieve at least one section — a
    grounding no-op on an anchored eval question is a coverage gap."""
    sections = load_fact_sheet(FACT_SHEET)
    qs = _load_questions()
    for q in qs:
        r = retrieve(q["question"], sections, top_k=2)
        assert r, f"{q['id']}: no section retrieved (grounding is a no-op)"


def test_critical_correction_does_not_dominantly_match_unrelated_questions():
    """The Critical-correction section over-matched before its keyword
    metadata was trimmed (it listed common words like 'did', 'you'). It
    must NOT be the top-1 result for questions that are not about the
    Toa Payoh / Ang Mo Kio constituency confusion."""
    sections = load_fact_sheet(FACT_SHEET)
    qs = _load_questions()
    for q in qs:
        # f01 and f05 are legitimately about Toa Payoh / Ang Mo Kio.
        if q["id"] in {"f01", "f05"}:
            continue
        r = retrieve(q["question"], sections, top_k=1)
        if r:
            assert r[0].title != "Critical correction", (
                f"{q['id']}: Critical-correction section over-matched "
                f"for {q['question']!r}"
            )
