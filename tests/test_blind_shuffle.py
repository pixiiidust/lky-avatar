"""Unit tests for scripts/blind_shuffle.py — pure logic only (stdlib script).

Covers mapping construction (seed determinism, coverage, naming), condition
label parsing, and the score-sheet template. File copying is a thin shutil
wrapper exercised via main() on a tmp tree with stub wav files.
"""
import json
import pathlib

import pytest

from scripts.blind_shuffle import (
    SCORE_COLUMNS,
    build_blind_mapping,
    main,
    parse_condition_label,
    scores_csv_text,
)


def _rel_paths():
    return [f"{label}/response_{n:02d}.wav"
            for label in ("chatterbox-2005", "chatterbox-1990", "f5-2005")
            for n in range(1, 21)]


# --- parse_condition_label ---------------------------------------------------

@pytest.mark.parametrize("label,expected", [
    ("chatterbox-2005", ("chatterbox", "2005")),
    ("f5-1990", ("f5", "1990")),
    ("xtts-2005", ("xtts", "2005")),
    ("chatterbox", ("chatterbox", None)),       # plain protocol layout
    ("fish-speech", ("fish-speech", None)),      # dash but no era suffix
])
def test_parse_condition_label(label, expected):
    assert parse_condition_label(label) == expected


# --- build_blind_mapping -----------------------------------------------------

def test_mapping_is_deterministic_given_a_seed():
    a = build_blind_mapping(_rel_paths(), seed=42)
    b = build_blind_mapping(_rel_paths(), seed=42)
    assert a == b


def test_mapping_ignores_input_order():
    paths = _rel_paths()
    assert build_blind_mapping(paths, seed=7) == \
        build_blind_mapping(list(reversed(paths)), seed=7)


def test_different_seeds_shuffle_differently():
    assert build_blind_mapping(_rel_paths(), seed=1) != \
        build_blind_mapping(_rel_paths(), seed=2)


def test_mapping_names_and_coverage():
    key = build_blind_mapping(_rel_paths(), seed=0)
    assert sorted(key) == [f"sample_{i:03d}.wav" for i in range(1, 61)]
    sources = {(v["engine"], v.get("era"), v["response"]) for v in key.values()}
    assert len(sources) == 60
    assert {"chatterbox", "f5"} == {v["engine"] for v in key.values()}
    assert all(v["response"].startswith("response_") for v in key.values())
    assert {v.get("era") for v in key.values()} == {"1990", "2005"}


def test_mapping_actually_shuffles():
    # With 60 items the identity permutation is astronomically unlikely.
    key = build_blind_mapping(_rel_paths(), seed=123)
    in_order = [f"{v['engine']}-{v['era']}/{v['response']}.wav"
                for _, v in sorted(key.items())]
    assert in_order != sorted(in_order)


# --- scores.csv template -----------------------------------------------------

def test_scores_csv_template():
    text = scores_csv_text(3)
    lines = text.strip().splitlines()
    assert lines[0] == "sample,similarity,naturalness,intelligibility,pacing,stability,regional,notes"
    assert lines[1:] == ["sample_001,,,,,,,",
                         "sample_002,,,,,,,",
                         "sample_003,,,,,,,"]
    assert len(SCORE_COLUMNS) == 8


# --- main() end-to-end on a stub tree ---------------------------------------

def _make_raw_tree(root: pathlib.Path, labels=("chatterbox-2005", "f5-2005"),
                   n=4) -> None:
    for label in labels:
        d = root / "raw" / label
        d.mkdir(parents=True)
        for i in range(1, n + 1):
            (d / f"response_{i:02d}.wav").write_bytes(b"RIFF" + label.encode())


def test_main_blinds_copies_and_writes_key(tmp_path, capsys):
    _make_raw_tree(tmp_path)
    assert main(["--root", str(tmp_path), "--seed", "5"]) == 0
    blind = tmp_path / "blind"
    samples = sorted(p.name for p in blind.glob("sample_*.wav"))
    assert samples == [f"sample_{i:03d}.wav" for i in range(1, 9)]
    key = json.loads((blind / "key.json").read_text(encoding="utf-8"))
    for name, entry in key.items():
        original = (tmp_path / "raw" / f"{entry['engine']}-{entry['era']}"
                    / f"{entry['response']}.wav")
        assert (blind / name).read_bytes() == original.read_bytes()
    scores = (tmp_path / "scores.csv").read_text(encoding="utf-8")
    assert scores.count("\n") == 9  # header + 8 rows
    assert "Do NOT open key.json" in capsys.readouterr().out


def test_main_refuses_to_reshuffle_without_force(tmp_path, capsys):
    _make_raw_tree(tmp_path)
    assert main(["--root", str(tmp_path), "--seed", "5"]) == 0
    assert main(["--root", str(tmp_path), "--seed", "6"]) == 1
    assert "must not be redone" in capsys.readouterr().err
    assert main(["--root", str(tmp_path), "--seed", "6", "--force"]) == 0


def test_main_errors_when_no_raw_files(tmp_path, capsys):
    assert main(["--root", str(tmp_path)]) == 1
    assert "no synthesized files" in capsys.readouterr().err
