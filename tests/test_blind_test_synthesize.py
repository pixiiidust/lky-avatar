"""Unit tests for scripts/blind_test_synthesize.py — pure logic only.

Per the testing standards (spec.md), TTS engines are NOT unit-tested; these
cover test-script parsing from docs/voice-blind-test.md, era/reference-set
construction, output naming, and plan building. Engine adapters import their
packages lazily, so importing the module here must not pull in torch or any
audio stack (asserted below).
"""
import pathlib
import sys

import pytest

from scripts.blind_test_synthesize import (
    DEFAULT_PRIMARY,
    DOC_PATH,
    ENGINES,
    ERA_CLIPS,
    EXPECTED_RESPONSES,
    build_arg_parser,
    build_output_path,
    build_plan,
    build_reference_set,
    condition_label,
    load_test_script,
    response_filename,
    strip_tags,
)


def test_importing_module_does_not_import_engine_stacks():
    for heavy in ("torch", "torchaudio", "chatterbox", "f5_tts", "TTS"):
        assert heavy not in sys.modules, f"{heavy} imported eagerly"


# --- strip_tags -------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("**[pace]** You cannot wish a technology away.",
     "You cannot wish a technology away."),
    ("**[regional] [num]** When we started, most of our people",
     "When we started, most of our people"),
    ("No tags here.", "No tags here."),
])
def test_strip_tags(raw, expected):
    assert strip_tags(raw) == expected


# --- load_test_script -------------------------------------------------------

@pytest.fixture(scope="module")
def texts():
    return load_test_script(DOC_PATH)


def test_loads_exactly_20_responses(texts):
    assert len(texts) == EXPECTED_RESPONSES == 20


def test_no_markdown_left_in_texts(texts):
    for t in texts:
        assert "**" not in t
        assert "[regional]" not in t and "[long]" not in t
        assert "\n" not in t and "  " not in t  # wrapped lines joined cleanly
        assert t.strip() == t and t


def test_known_texts_spot_checks(texts):
    assert texts[0].startswith("You cannot wish a technology away.")
    assert "August 1965" in texts[6]            # response 7 [num]
    assert "kiasu" in texts[15]                 # response 16 [regional]
    assert "Deng Xiaoping" in texts[16]         # response 17 [regional]
    assert texts[19].endswith("history can make of it what it will.")


def test_long_responses_are_joined_whole(texts):
    # Responses 12-13 are the [long] stability probes; wrapped over many
    # doc lines, they must come through as one long sentence each.
    assert len(texts[11]) > 300 and texts[11].endswith("unravel the other two.")
    assert len(texts[12]) > 250 and "three-room flat" in texts[12]


def test_malformed_doc_rejected(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text(
        "## 2. The fixed test script (20 responses)\n\n"
        "1. Only one response.\n\n"
        "### Synthesis rules\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected 20"):
        load_test_script(doc)


# --- reference sets ----------------------------------------------------------

def test_era_conditions_match_operator_note():
    assert ERA_CLIPS["1990"] == tuple(
        f"elder_ref_{n:02d}.wav" for n in (1, 2, 3, 4, 5))
    assert ERA_CLIPS["2005"] == tuple(
        f"elder_ref_{n:02d}.wav" for n in (6, 7, 8, 9))
    assert DEFAULT_PRIMARY == {"1990": "elder_ref_01.wav",
                               "2005": "elder_ref_06.wav"}


def test_build_reference_set(tmp_path):
    refs = build_reference_set("2005", tmp_path)
    assert refs.era == "2005"
    assert [p.name for p in refs.clips] == [
        "elder_ref_06.wav", "elder_ref_07.wav",
        "elder_ref_08.wav", "elder_ref_09.wav"]
    assert refs.primary == tmp_path / "elder_ref_06.wav"
    assert refs.primary_transcript() is None  # no .txt yet


def test_reference_set_ref_clip_override(tmp_path):
    refs = build_reference_set("1990", tmp_path, "elder_ref_03.wav")
    assert refs.primary.name == "elder_ref_03.wav"
    with pytest.raises(ValueError, match="not in the 2005 set"):
        build_reference_set("2005", tmp_path, "elder_ref_01.wav")
    with pytest.raises(ValueError, match="unknown era"):
        build_reference_set("1965", tmp_path)


def test_primary_transcript_read_from_txt_beside_wav(tmp_path):
    (tmp_path / "elder_ref_06.txt").write_text(
        " We had to make it work. \n", encoding="utf-8")
    refs = build_reference_set("2005", tmp_path)
    assert refs.primary_transcript() == "We had to make it work."


# --- naming and plan ---------------------------------------------------------

def test_output_naming():
    assert condition_label("chatterbox", "2005") == "chatterbox-2005"
    assert response_filename(1) == "response_01.wav"
    assert response_filename(20) == "response_20.wav"
    with pytest.raises(ValueError):
        response_filename(0)
    with pytest.raises(ValueError):
        response_filename(21)
    out = build_output_path(pathlib.Path("raw"), "f5", "1990", 7)
    assert out == pathlib.Path("raw") / "f5-1990" / "response_07.wav"


def test_build_plan_full_and_limited(texts):
    root = pathlib.Path("raw")
    plan = build_plan(texts, "xtts", "2005", root)
    assert len(plan) == 20
    assert plan[0] == (1, texts[0], root / "xtts-2005" / "response_01.wav")
    assert plan[-1][0] == 20

    smoke = build_plan(texts, "xtts", "2005", root, limit=3)
    assert [n for n, _, _ in smoke] == [1, 2, 3]
    assert build_plan(texts, "xtts", "2005", root, limit=0) == []
    assert len(build_plan(texts, "xtts", "2005", root, limit=99)) == 20


# --- CLI surface -------------------------------------------------------------

def test_arg_parser_choices_and_defaults():
    ap = build_arg_parser()
    args = ap.parse_args(["--engine", "chatterbox", "--era", "2005"])
    assert args.device == "cuda" and args.seed == 7
    assert args.limit is None and not args.list and not args.overwrite
    with pytest.raises(SystemExit):
        ap.parse_args(["--engine", "espeak", "--era", "2005"])
    with pytest.raises(SystemExit):
        ap.parse_args(["--engine", "f5", "--era", "1979"])
    assert set(ENGINES) == {"chatterbox", "f5", "xtts"}
