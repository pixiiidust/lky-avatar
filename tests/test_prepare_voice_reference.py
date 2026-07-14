"""Unit tests for scripts/prepare_voice_reference.py — pure logic only.

Per the testing standards (spec.md), ffmpeg itself is NOT unit-tested; these
cover timestamp parsing, clip-range validation, filename allocation, metadata
construction/appending, and the ffmpeg command assembly (a pure function).
"""
import json

import pytest

from scripts.prepare_voice_reference import (
    ClipValidationError,
    append_metadata,
    build_ffmpeg_command,
    build_metadata_entry,
    format_timestamp,
    load_metadata,
    next_clip_filename,
    parse_timestamp,
    processing_steps,
    validate_clip_range,
)


# --- parse_timestamp -------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("7", 7.0),
    ("83.5", 83.5),
    ("1:23", 83.0),
    ("01:23.250", 83.25),
    ("1:02:03", 3723.0),
    ("00:00:00", 0.0),
    (" 2:05 ", 125.0),
])
def test_parse_timestamp_valid(text, expected):
    assert parse_timestamp(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", [
    "", "  ", "abc", "1:xx", "-5", "1:-2", "1:2:3:4", "1:75", "1:75:00",
])
def test_parse_timestamp_invalid(text):
    with pytest.raises(ValueError):
        parse_timestamp(text)


def test_format_timestamp_round_trip():
    assert format_timestamp(83.25) == "00:01:23.250"
    assert format_timestamp(3723.0) == "01:02:03.000"
    assert parse_timestamp(format_timestamp(451.789)) == pytest.approx(451.789)


def test_format_timestamp_rejects_negative():
    with pytest.raises(ValueError):
        format_timestamp(-1)


# --- validate_clip_range ---------------------------------------------------

def test_validate_clip_range_accepts_window_bounds():
    assert validate_clip_range(10.0, 16.0) == pytest.approx(6.0)
    assert validate_clip_range(0.0, 12.0) == pytest.approx(12.0)


def test_validate_clip_range_rejects_too_short_and_too_long():
    with pytest.raises(ClipValidationError, match="6-12 s"):
        validate_clip_range(0.0, 5.9)
    with pytest.raises(ClipValidationError, match="6-12 s"):
        validate_clip_range(0.0, 12.1)


def test_validate_clip_range_rejects_inverted_even_with_force():
    with pytest.raises(ClipValidationError, match="after start"):
        validate_clip_range(10.0, 10.0)
    with pytest.raises(ClipValidationError, match="after start"):
        validate_clip_range(10.0, 4.0, force=True)


def test_validate_clip_range_force_allows_out_of_window():
    assert validate_clip_range(0.0, 3.0, force=True) == pytest.approx(3.0)


# --- next_clip_filename ----------------------------------------------------

def test_next_clip_filename_starts_at_01():
    assert next_clip_filename([]) == "elder_ref_01.wav"


def test_next_clip_filename_continues_after_highest():
    names = ["elder_ref_01.wav", "elder_ref_07.wav", "elder_ref_03.wav"]
    assert next_clip_filename(names) == "elder_ref_08.wav"


def test_next_clip_filename_ignores_unrelated_names():
    names = ["notes.txt", "metadata.json", "elder_ref_xx.wav", "ref_02.wav"]
    assert next_clip_filename(names) == "elder_ref_01.wav"


def test_next_clip_filename_handles_paths():
    assert next_clip_filename(["some/dir/elder_ref_02.wav"]) == \
        "elder_ref_03.wav"


# --- metadata --------------------------------------------------------------

def _entry(**overrides):
    kwargs = dict(
        filename="elder_ref_01.wav",
        input_name="interview.mp4",
        source="Charlie Rose interview, PBS",
        source_date="2009-10-22",
        rights_status="personal research use; not redistributed",
        start=83.0,
        end=91.5,
        notes="calm register",
        prepared_at="2026-07-13T00:00:00+00:00",
    )
    kwargs.update(overrides)
    return build_metadata_entry(**kwargs)


def test_metadata_entry_records_required_provenance_fields():
    entry = _entry()
    # The four fields issue #7 names: source, date, processing, rights.
    assert entry["source"] == "Charlie Rose interview, PBS"
    assert entry["source_date"] == "2009-10-22"
    assert entry["rights_status"] == \
        "personal research use; not redistributed"
    assert entry["processing_steps"] == processing_steps(83.0, 91.5)
    assert entry["file"] == "elder_ref_01.wav"
    assert entry["duration_seconds"] == pytest.approx(8.5)
    assert entry["clip_start"] == "00:01:23.000"
    assert entry["clip_end"] == "00:01:31.500"


@pytest.mark.parametrize("field", ["source", "source_date", "rights_status"])
def test_metadata_entry_rejects_blank_provenance(field):
    with pytest.raises(ClipValidationError, match=field):
        _entry(**{field: "   "})


def test_processing_steps_describe_full_chain():
    steps = " | ".join(processing_steps(83.0, 91.5))
    for expected in ["trim", "mono", "24000 Hz", "loudnorm", "16-bit"]:
        assert expected in steps


def test_load_metadata_returns_skeleton_when_missing(tmp_path):
    data = load_metadata(tmp_path / "metadata.json")
    assert data["voice"] == "elder"
    assert data["clips"] == []


def test_load_metadata_rejects_wrong_shape(tmp_path):
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    with pytest.raises(ClipValidationError):
        load_metadata(path)


def test_append_metadata_creates_then_appends(tmp_path):
    path = tmp_path / "metadata.json"
    append_metadata(path, _entry())
    data = append_metadata(path, _entry(filename="elder_ref_02.wav"))
    assert [c["file"] for c in data["clips"]] == \
        ["elder_ref_01.wav", "elder_ref_02.wav"]
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk == data


# --- ffmpeg command assembly -----------------------------------------------

def test_ffmpeg_command_shape(tmp_path):
    cmd = build_ffmpeg_command(tmp_path / "in.mp4", tmp_path / "out.wav",
                               start=83.0, duration=8.5)
    assert cmd[0] == "ffmpeg"
    assert "-nostdin" in cmd  # never blocks waiting for input
    joined = " ".join(cmd)
    assert "-ss 00:01:23.000" in joined
    assert "-t 8.500" in joined
    assert "-ac 1" in joined          # mono
    assert "-ar 24000" in joined      # 24 kHz
    assert "pcm_s16le" in joined      # 16-bit PCM
    assert "loudnorm" in joined       # normalization, no denoising
    assert cmd[-1].endswith("out.wav")
    # trim happens before decode-heavy filters: -ss precedes -i
    assert cmd.index("-ss") < cmd.index("-i")
