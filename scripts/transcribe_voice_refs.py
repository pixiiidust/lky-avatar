"""Transcribe the elder reference clips once, for F5-TTS (issue #7).

F5-TTS needs each reference clip's transcript alongside the audio (protocol
doc §1). This writes ``elder_ref_NN.txt`` next to each ``elder_ref_NN.wav``
in ``assets/voices/elder/`` (all gitignored) using faster-whisper on CPU, so
no GPU window is needed and F5 never has to load its own ASR at synthesis
time. Existing ``.txt`` files are kept unless ``--overwrite`` is given —
operator hand-corrections survive re-runs.

Run from the F5 venv in WSL (faster-whisper is installed there):

    ~/tts-f5/bin/python scripts/transcribe_voice_refs.py

Review the transcripts afterwards — clone quality tracks transcript accuracy.
Per the testing standards, the ASR provider itself is not unit-tested.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_REF_DIR = REPO_ROOT / "assets" / "voices" / "elder"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ref-dir", type=pathlib.Path, default=DEFAULT_REF_DIR)
    ap.add_argument("--model", default="small.en",
                    help="faster-whisper model size (default: %(default)s; "
                         "clips are clean single-speaker English)")
    ap.add_argument("--overwrite", action="store_true",
                    help="re-transcribe clips that already have a .txt")
    args = ap.parse_args(argv)

    clips = sorted(args.ref_dir.glob("elder_ref_*.wav"))
    if not clips:
        print(f"ERROR: no elder_ref_*.wav in {args.ref_dir}", file=sys.stderr)
        return 1
    todo = [c for c in clips
            if args.overwrite or not c.with_suffix(".txt").exists()]
    if not todo:
        print("all clips already transcribed (use --overwrite to redo).")
        return 0

    from faster_whisper import WhisperModel  # lazy: keeps --help stdlib-only

    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    for clip in todo:
        segments, _info = model.transcribe(str(clip), language="en",
                                           beam_size=5)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        out = clip.with_suffix(".txt")
        out.write_text(text + "\n", encoding="utf-8")
        print(f"{clip.name}: {text}")
    print(f"\n{len(todo)} transcript(s) written beside the clips in "
          f"{args.ref_dir}. Proofread them before synthesis.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
