"""Issue #45 eval CLI regression: ``--questions-file`` with omitted
``--questions`` must select the custom file's questions (not the standing
default q18/q19/q20/q01/q05, which do not exist in a custom file and made
the eval fail before HTTP).

Pure, pre-network: exercises ``select_questions`` and the argument
selection path of ``run_timetravel_eval_http.py``. No model, no server.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# The script imports livekit at module load (persona_prompt -> agent path
# is NOT imported here; the script only imports persona + persona_prompt +
# fact_grounding, which are pure). But to be safe, import lazily.
from run_timetravel_eval_http import (  # noqa: E402
    DEFAULT_QUESTIONS_PATH,
    FACT_GROUNDING_QUESTIONS_PATH,
    select_questions,
)


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ── the bug: custom file + omitted --questions ──────────────────────────────


def test_custom_file_omitted_questions_selects_all_custom_questions():
    """The PR-body failing command:
    ``--questions-file evals/fact_grounding_questions.json`` (no --questions)
    must select all f01–f12, NOT the default q18/q19/q20/q01/q05."""
    data = _load(FACT_GROUNDING_QUESTIONS_PATH)
    qs = select_questions(data, "", FACT_GROUNDING_QUESTIONS_PATH)
    ids = [q["id"] for q in qs]
    # All 12 fact-grounding questions selected.
    assert len(qs) == 12
    assert ids == [f"f{i:02d}" for i in range(1, 13)]


def test_custom_file_omitted_questions_does_not_use_default_ids():
    """The default probe IDs must NOT appear when a custom file is used."""
    data = _load(FACT_GROUNDING_QUESTIONS_PATH)
    qs = select_questions(data, "", FACT_GROUNDING_QUESTIONS_PATH)
    ids = {q["id"] for q in qs}
    for bad in ("q18", "q19", "q20", "q01", "q05"):
        assert bad not in ids


# ── preserved: default file + omitted --questions ──────────────────────────


def test_default_file_omitted_questions_preserves_default_subset():
    """The standing persona eval default (q18,q19,q20,q01,q05) is
    preserved when no --questions-file is given and --questions is omitted."""
    data = _load(DEFAULT_QUESTIONS_PATH)
    qs = select_questions(data, "", DEFAULT_QUESTIONS_PATH)
    ids = [q["id"] for q in qs]
    assert ids == ["q18", "q19", "q20", "q01", "q05"]


# ── explicit --questions still honors IDs ───────────────────────────────────


def test_explicit_questions_on_custom_file_honors_ids():
    data = _load(FACT_GROUNDING_QUESTIONS_PATH)
    qs = select_questions(data, "f01,f05", FACT_GROUNDING_QUESTIONS_PATH)
    assert [q["id"] for q in qs] == ["f01", "f05"]


def test_explicit_questions_on_default_file_honors_ids():
    data = _load(DEFAULT_QUESTIONS_PATH)
    qs = select_questions(data, "q01,q05", DEFAULT_QUESTIONS_PATH)
    assert [q["id"] for q in qs] == ["q01", "q05"]


def test_unknown_explicit_questions_raises():
    data = _load(FACT_GROUNDING_QUESTIONS_PATH)
    with pytest.raises(SystemExit, match="unknown question ids"):
        select_questions(data, "q18,q19", FACT_GROUNDING_QUESTIONS_PATH)


# ── reproduce the PR-body command past argument selection ───────────────────


def test_pr_body_command_arg_selection_succeeds():
    """Reproduces the PR-body eval command's argument-selection stage (the
    stage that failed before HTTP). No live brain is contacted."""
    data = _load(FACT_GROUNDING_QUESTIONS_PATH)
    # The exact failing invocation: --questions-file ... (no --questions)
    qs = select_questions(data, "", FACT_GROUNDING_QUESTIONS_PATH)
    assert len(qs) == 12
    # Sanity: every selected question has an answer key (the fact-grounding
    # subset's judgeability contract).
    keys = set(data["answer_keys"])
    for q in qs:
        assert q["id"] in keys


# ── the real CLI path: argparse default IDs against a custom file ──────────


def test_real_cli_default_ids_against_custom_file_selects_all():
    """The actual production failure: the CLI's ``--questions`` argparse
    default is ``DEFAULT_QUESTION_IDS_ARG`` (``q18,q19,q20,q01,q05``), NOT
    empty. When the user runs ``--questions-file evals/fact_grounding_questions.json``
    WITHOUT ``--questions``, argparse fills in the default IDs, which do not
    exist in the custom file — so the old code raised ``unknown question ids``
    before HTTP. This test reproduces the real CLI argument shape (the
    default ID string, not empty) and asserts the fix routes to all 12."""
    from run_timetravel_eval_http import DEFAULT_QUESTION_IDS_ARG

    data = _load(FACT_GROUNDING_QUESTIONS_PATH)
    qs = select_questions(
        data, DEFAULT_QUESTION_IDS_ARG, FACT_GROUNDING_QUESTIONS_PATH
    )
    assert len(qs) == 12
    assert [q["id"] for q in qs] == [f"f{i:02d}" for i in range(1, 13)]


def test_real_cli_default_ids_against_default_file_preserves_subset():
    """The standing persona eval: default IDs against the default file must
    still select the q18/q19/q20/q01/q05 probe subset (backward compat)."""
    from run_timetravel_eval_http import DEFAULT_QUESTION_IDS_ARG

    data = _load(DEFAULT_QUESTIONS_PATH)
    qs = select_questions(
        data, DEFAULT_QUESTION_IDS_ARG, DEFAULT_QUESTIONS_PATH
    )
    assert [q["id"] for q in qs] == ["q18", "q19", "q20", "q01", "q05"]
