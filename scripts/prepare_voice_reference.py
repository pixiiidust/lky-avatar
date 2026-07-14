"""Prepare an elder-LKY voice reference clip for TTS cloning (issue #7).

Cuts a 6-12 s segment from a rights-checked source recording, converts it to
a normalized mono WAV (24 kHz, 16-bit PCM, EBU R128 loudness-normalized), and
records provenance in ``assets/voices/elder/metadata.json``: source, date,
processing steps, and rights status (spec user story 35; plan §9). Neither the
audio nor the metadata is ever committed — ``assets/voices/*`` is gitignored.

Usage (Windows Python, stdlib-only; requires ffmpeg on PATH):

    python scripts/prepare_voice_reference.py INPUT --start 1:23 --end 1:31 \
        --source "Charlie Rose interview, PBS" --source-date 2009-10-22 \
        --rights "personal research use; not redistributed" \
        --notes "calm register, low room noise"

Timestamps accept ``SS``, ``MM:SS``, or ``HH:MM:SS``, each with optional
``.fraction``. Metadata flags left off the command line are prompted for
interactively when running in a terminal.

Clips must be 6-12 s (issue #7 acceptance criteria); pass ``--force`` to
keep an out-of-range cut anyway (e.g. while auditioning candidate segments).

ffmpeg does the audio work. If it is missing, the script prints install
instructions and exits instead of crashing. Pure logic (timestamps, filename
allocation, metadata, validation) is unit-tested in
``tests/test_prepare_voice_reference.py``; ffmpeg itself is not (testing
standards: no unit tests through audio providers/tools).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import shutil
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "assets" / "voices" / "elder"
METADATA_FILENAME = "metadata.json"

# Output format: mono, 24 kHz, 16-bit PCM. 24 kHz covers the native rates of
# every candidate engine's reference-audio loader (Chatterbox/XTTS/F5/Fish all
# resample internally); mono 16-bit keeps clips small and uniform.
SAMPLE_RATE = 24_000

# Loudness normalization only — no denoising. The plan (§7 Milestone 3) wants
# clips "natural, not over-denoised"; -18 LUFS is a conservative speech level
# that avoids clipping quiet archival sources.
LOUDNORM_FILTER = "loudnorm=I=-18:TP=-2:LRA=11"

MIN_CLIP_SECONDS = 6.0
MAX_CLIP_SECONDS = 12.0

CLIP_PREFIX = "elder_ref_"

FFMPEG_INSTALL_INSTRUCTIONS = """\
ffmpeg was not found on PATH. Install it, then re-run this script:

  Windows:  winget install Gyan.FFmpeg
            (or: choco install ffmpeg)
  WSL/Linux: sudo apt install ffmpeg
  macOS:    brew install ffmpeg

After installing, open a NEW terminal so PATH is refreshed, and verify with:
  ffmpeg -version
"""


class ClipValidationError(ValueError):
    """A clip request that violates the issue-#7 acceptance criteria."""


# ---------------------------------------------------------------------------
# Pure logic (unit-tested)
# ---------------------------------------------------------------------------

def parse_timestamp(text: str) -> float:
    """Parse ``SS``, ``MM:SS``, or ``HH:MM:SS`` (fractions allowed) to seconds.

    Raises ValueError on empty input, negative values, more than three
    fields, or out-of-range minutes/seconds in multi-field forms.
    """
    text = text.strip()
    if not text:
        raise ValueError("empty timestamp")
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError(f"too many ':' in timestamp: {text!r}")
    try:
        values = [float(p) for p in parts]
    except ValueError:
        raise ValueError(f"non-numeric timestamp: {text!r}") from None
    if any(v < 0 for v in values):
        raise ValueError(f"negative timestamp component: {text!r}")
    if len(parts) > 1 and values[-1] >= 60:
        raise ValueError(f"seconds field must be < 60: {text!r}")
    if len(parts) == 3 and values[1] >= 60:
        raise ValueError(f"minutes field must be < 60: {text!r}")
    seconds = 0.0
    for value in values:
        seconds = seconds * 60 + value
    return seconds


def format_timestamp(seconds: float) -> str:
    """Render seconds as ``HH:MM:SS.mmm`` (ffmpeg-friendly, metadata-stable)."""
    if seconds < 0:
        raise ValueError("negative seconds")
    whole_ms = round(seconds * 1000)
    hours, rem = divmod(whole_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs = rem / 1000
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def validate_clip_range(start: float, end: float, *,
                        force: bool = False) -> float:
    """Check start < end and 6 s <= duration <= 12 s; return the duration.

    ``force=True`` skips only the duration-window check (the range must
    still be positive).
    """
    if end <= start:
        raise ClipValidationError(
            f"end ({format_timestamp(end)}) must be after start "
            f"({format_timestamp(start)})")
    duration = end - start
    if not force and not (MIN_CLIP_SECONDS <= duration <= MAX_CLIP_SECONDS):
        raise ClipValidationError(
            f"clip is {duration:.2f} s; reference clips must be "
            f"{MIN_CLIP_SECONDS:.0f}-{MAX_CLIP_SECONDS:.0f} s "
            f"(issue #7). Adjust --start/--end, or pass --force to keep "
            f"an out-of-range cut anyway.")
    return duration


def next_clip_filename(existing_names) -> str:
    """Allocate the next ``elder_ref_NN.wav`` name after existing clips.

    Non-matching names are ignored; numbering continues after the highest
    existing index so deleted clips never cause a name collision in metadata.
    """
    highest = 0
    for name in existing_names:
        stem = pathlib.Path(str(name)).name
        if not (stem.startswith(CLIP_PREFIX) and stem.endswith(".wav")):
            continue
        middle = stem[len(CLIP_PREFIX):-len(".wav")]
        if middle.isdigit():
            highest = max(highest, int(middle))
    return f"{CLIP_PREFIX}{highest + 1:02d}.wav"


def processing_steps(start: float, end: float) -> list[str]:
    """The exact processing applied, recorded for provenance (plan §9)."""
    return [
        f"trim {format_timestamp(start)}-{format_timestamp(end)}",
        "downmix to mono",
        f"resample to {SAMPLE_RATE} Hz",
        f"loudness normalize ({LOUDNORM_FILTER})",
        "encode 16-bit PCM WAV",
    ]


def build_metadata_entry(*, filename: str, input_name: str, source: str,
                         source_date: str, rights_status: str,
                         start: float, end: float, notes: str = "",
                         prepared_at: str | None = None) -> dict:
    """Assemble one clip's provenance record (source, date, processing,
    rights — the four fields issue #7 requires)."""
    for field, value in [("source", source), ("source_date", source_date),
                         ("rights_status", rights_status)]:
        if not str(value).strip():
            raise ClipValidationError(
                f"{field} must not be empty — issue #7 requires source, "
                f"date, and rights status recorded for every clip")
    return {
        "file": filename,
        "source": source.strip(),
        "source_date": source_date.strip(),
        "rights_status": rights_status.strip(),
        "input_file": input_name,
        "clip_start": format_timestamp(start),
        "clip_end": format_timestamp(end),
        "duration_seconds": round(end - start, 3),
        "processing_steps": processing_steps(start, end),
        "notes": notes.strip(),
        "prepared_at": prepared_at or _dt.datetime.now(
            _dt.timezone.utc).isoformat(timespec="seconds"),
    }


def load_metadata(metadata_path: pathlib.Path) -> dict:
    """Load metadata.json, or a fresh skeleton if it doesn't exist yet."""
    if metadata_path.is_file():
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(
                data.get("clips"), list):
            raise ClipValidationError(
                f"{metadata_path} exists but is not in the expected "
                f'{{"clips": [...]}} shape — fix or move it aside')
        return data
    return {
        "voice": "elder",
        "_comment": ("Voice-reference provenance (spec story 35). "
                     "Local-only — never committed (gitignored via "
                     "assets/voices/*)."),
        "clips": [],
    }


def append_metadata(metadata_path: pathlib.Path, entry: dict) -> dict:
    """Append one clip entry to metadata.json (creating it if needed)."""
    data = load_metadata(metadata_path)
    data["clips"].append(entry)
    metadata_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return data


def build_ffmpeg_command(input_path: pathlib.Path, output_path: pathlib.Path,
                         start: float, duration: float) -> list[str]:
    """The exact ffmpeg invocation: trim, mono, resample, loudnorm, PCM."""
    return [
        "ffmpeg", "-nostdin", "-hide_banner", "-y",
        "-ss", format_timestamp(start),
        "-t", f"{duration:.3f}",
        "-i", str(input_path),
        "-af", LOUDNORM_FILTER,
        "-ac", "1",
        "-ar", str(SAMPLE_RATE),
        "-c:a", "pcm_s16le",
        str(output_path),
    ]


# ---------------------------------------------------------------------------
# Shell / IO (thin, not unit-tested)
# ---------------------------------------------------------------------------

def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _prompt_if_missing(value: str | None, flag: str, question: str) -> str:
    """Return the flag value, prompting interactively when possible."""
    if value is not None and value.strip():
        return value
    if not sys.stdin.isatty():
        sys.exit(f"ERROR: {flag} is required (no terminal to prompt on). "
                 f"Pass it as an argument.")
    answer = input(f"{question}: ").strip()
    while not answer:
        answer = input(f"(required) {question}: ").strip()
    return answer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cut and normalize an elder-LKY voice reference clip, "
                    "recording provenance in metadata.json.")
    parser.add_argument("input", help="source audio/video file (any format "
                                      "ffmpeg can read)")
    parser.add_argument("--start", required=True,
                        help="clip start (SS, MM:SS, or HH:MM:SS)")
    parser.add_argument("--end", required=True,
                        help="clip end (SS, MM:SS, or HH:MM:SS)")
    parser.add_argument("--source",
                        help="where the recording comes from, e.g. "
                             "'Charlie Rose interview, PBS'")
    parser.add_argument("--source-date",
                        help="recording date (YYYY-MM-DD or best known)")
    parser.add_argument("--rights",
                        help="rights status, e.g. 'personal research use; "
                             "not redistributed'")
    parser.add_argument("--notes", default="",
                        help="optional notes (register, noise, context)")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                        help=f"output directory (default: {DEFAULT_OUT_DIR})")
    parser.add_argument("--force", action="store_true",
                        help="allow a clip outside the 6-12 s window")
    args = parser.parse_args(argv)

    if not ffmpeg_available():
        print(FFMPEG_INSTALL_INSTRUCTIONS, file=sys.stderr)
        return 2

    input_path = pathlib.Path(args.input)
    if not input_path.is_file():
        print(f"ERROR: input file not found: {input_path}", file=sys.stderr)
        return 1

    try:
        start = parse_timestamp(args.start)
        end = parse_timestamp(args.end)
        duration = validate_clip_range(start, end, force=args.force)
    except (ValueError, ClipValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    source = _prompt_if_missing(args.source, "--source",
                                "Source (publication/interview/archive)")
    source_date = _prompt_if_missing(args.source_date, "--source-date",
                                     "Recording date (YYYY-MM-DD)")
    rights = _prompt_if_missing(args.rights, "--rights",
                                "Rights status (basis for using this "
                                "recording)")

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = out_dir / METADATA_FILENAME
    existing = load_metadata(metadata_path)
    filename = next_clip_filename(
        [clip.get("file", "") for clip in existing["clips"]]
        + [p.name for p in out_dir.glob("*.wav")])
    output_path = out_dir / filename

    command = build_ffmpeg_command(input_path, output_path, start, duration)
    print("Running:", " ".join(command))
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0 or not output_path.is_file():
        print("ERROR: ffmpeg failed:\n" + result.stderr, file=sys.stderr)
        return 1

    try:
        entry = build_metadata_entry(
            filename=filename, input_name=input_path.name, source=source,
            source_date=source_date, rights_status=rights,
            start=start, end=end, notes=args.notes)
    except ClipValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    data = append_metadata(metadata_path, entry)

    print(f"\nWrote {output_path}  ({duration:.2f} s, mono, "
          f"{SAMPLE_RATE} Hz, 16-bit)")
    print(f"Metadata: {metadata_path}  ({len(data['clips'])} clip(s) "
          f"recorded)")
    print("Reminder: audio and metadata are local-only and gitignored -- "
          "never commit them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
