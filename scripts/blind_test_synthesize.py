"""Synthesize the blind-test responses with one TTS engine (issue #7).

Renders the fixed 20-response test script from ``docs/voice-blind-test.md``
(parsed from the doc so it stays the single source of truth) with one candidate
engine and one reference condition, into::

    assets/voices/blind-test/raw/<engine>-<era>/response_NN.wav

Reference conditions (operator's era note on issue #7): clips 01-05 are the
1990 National Day speech (age 67), clips 06-09 are 2005-era (age 82). The two
sets are scored as separate conditions; prefer 2005 for the elder persona if
clone quality is comparable.

Engines run in their own WSL venvs (GOAL.md env isolation). Typical GPU run,
one engine+era at a time (one model in VRAM at a time):

    ~/tts-chatterbox/bin/python scripts/blind_test_synthesize.py --engine chatterbox --era 2005
    ~/tts-f5/bin/python         scripts/blind_test_synthesize.py --engine f5         --era 2005
    ~/tts-xtts/bin/python       scripts/blind_test_synthesize.py --engine xtts       --era 2005

Dry-run (no engine imports, works on Windows Python):

    python scripts/blind_test_synthesize.py --engine chatterbox --era 2005 --list

Synthesis rules (protocol doc §2): identical texts and reference clips for
every engine, default inference settings, fixed seed where supported, no
regeneration of bad takes. Existing outputs are skipped (resume-friendly for
short GPU windows) unless ``--overwrite`` is given.

Engine adapters sit behind one small interface (``synthesize(text, out_path)``
plus a ``describe()``) — issue #8's TTS provider seam should keep this shape.
Adapters import their engine packages lazily so this module stays importable
(and unit-testable) with no audio stack installed.

F5-TTS needs a transcript of the reference clip: put it in a ``.txt`` file
beside the clip (``elder_ref_06.txt`` next to ``elder_ref_06.wav``), e.g. via
``scripts/transcribe_voice_refs.py``. Without one, the adapter falls back to
F5's built-in ASR (slower; loads Whisper at synthesis time).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import re
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC_PATH = REPO_ROOT / "docs" / "voice-blind-test.md"
DEFAULT_REF_DIR = REPO_ROOT / "assets" / "voices" / "elder"
DEFAULT_OUT_ROOT = REPO_ROOT / "assets" / "voices" / "blind-test" / "raw"

EXPECTED_RESPONSES = 20

ENGINES = ("chatterbox", "f5", "xtts")

# Reference conditions (issue #7 comment, operator era note).
ERA_CLIPS = {
    "1990": tuple(f"elder_ref_{n:02d}.wav" for n in range(1, 6)),
    "2005": tuple(f"elder_ref_{n:02d}.wav" for n in range(6, 10)),
}
# Engines that clone from a single reference use the first clip of the era
# set by default (override with --ref-clip); multi-reference engines (XTTS)
# receive the whole era set.
DEFAULT_PRIMARY = {"1990": "elder_ref_01.wav", "2005": "elder_ref_06.wav"}

DEFAULT_SEED = 7

# --- test-script loading (pure logic, unit-tested) -------------------------

_SCRIPT_HEADING = "## 2. The fixed test script"
_END_HEADING = "### Synthesis rules"
_ITEM_RE = re.compile(r"^(\d{1,2})\.\s+(.*)$")
_TAG_RE = re.compile(r"^\*\*(?:\[[^\]]+\]\s*)+\*\*\s*")


def strip_tags(text: str) -> str:
    """Remove the leading ``**[tag] [tag]**`` scoring-axis markers."""
    return _TAG_RE.sub("", text)


def load_test_script(doc_path: pathlib.Path = DOC_PATH) -> list[str]:
    """Parse the fixed 20 test responses out of docs/voice-blind-test.md.

    Returns the texts in order (index 0 = response 1), markdown tags stripped
    and wrapped lines joined. Raises ValueError if the doc does not yield
    exactly EXPECTED_RESPONSES texts (the protocol forbids editing the script
    for one engine only, so a mismatch means the doc changed shape).
    """
    lines = doc_path.read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.startswith(_SCRIPT_HEADING))
        end = next(i for i, l in enumerate(lines) if l.startswith(_END_HEADING))
    except StopIteration:  # pragma: no cover - doc restructure
        raise ValueError(f"could not locate the test-script section in {doc_path}")

    items: list[list[str]] = []
    for line in lines[start:end]:
        m = _ITEM_RE.match(line)
        if m:
            number = int(m.group(1))
            if number != len(items) + 1:
                raise ValueError(
                    f"test script numbering jumped to {number} after "
                    f"{len(items)} items — doc format changed?")
            items.append([m.group(2).strip()])
        elif items and line.startswith(("   ", "\t")) and line.strip():
            items[-1].append(line.strip())
        elif items and not line.strip():
            continue  # blank line between items
    texts = [re.sub(r"\s+", " ", strip_tags(" ".join(parts))).strip()
             for parts in items]
    if len(texts) != EXPECTED_RESPONSES or not all(texts):
        raise ValueError(
            f"expected {EXPECTED_RESPONSES} test responses in {doc_path}, "
            f"parsed {len(texts)}")
    return texts


# --- references and output naming (pure logic, unit-tested) ----------------

@dataclasses.dataclass(frozen=True)
class ReferenceSet:
    """The reference clips for one era condition."""
    era: str
    clips: tuple[pathlib.Path, ...]   # full era set, for multi-ref engines
    primary: pathlib.Path             # single clip, for single-ref engines

    @property
    def primary_transcript_path(self) -> pathlib.Path:
        return self.primary.with_suffix(".txt")

    def primary_transcript(self) -> str | None:
        p = self.primary_transcript_path
        if p.is_file():
            text = p.read_text(encoding="utf-8").strip()
            return text or None
        return None


def build_reference_set(era: str, ref_dir: pathlib.Path,
                        primary_name: str | None = None) -> ReferenceSet:
    if era not in ERA_CLIPS:
        raise ValueError(f"unknown era {era!r}; choose from {sorted(ERA_CLIPS)}")
    clips = tuple(ref_dir / name for name in ERA_CLIPS[era])
    primary_name = primary_name or DEFAULT_PRIMARY[era]
    if primary_name not in ERA_CLIPS[era]:
        raise ValueError(
            f"--ref-clip {primary_name!r} is not in the {era} set "
            f"{list(ERA_CLIPS[era])}")
    return ReferenceSet(era=era, clips=clips, primary=ref_dir / primary_name)


def condition_label(engine: str, era: str) -> str:
    return f"{engine}-{era}"


def response_filename(n: int) -> str:
    if not 1 <= n <= EXPECTED_RESPONSES:
        raise ValueError(f"response number {n} out of range 1..{EXPECTED_RESPONSES}")
    return f"response_{n:02d}.wav"


def build_output_path(out_root: pathlib.Path, engine: str, era: str,
                      n: int) -> pathlib.Path:
    return out_root / condition_label(engine, era) / response_filename(n)


def build_plan(texts: list[str], engine: str, era: str,
               out_root: pathlib.Path, limit: int | None = None,
               ) -> list[tuple[int, str, pathlib.Path]]:
    """(response number, text, output path) for each response to synthesize."""
    n_items = len(texts) if limit is None else max(0, min(limit, len(texts)))
    return [(i, texts[i - 1], build_output_path(out_root, engine, era, i))
            for i in range(1, n_items + 1)]


# --- engine adapters (lazy imports; the issue-#8-shaped seam) ---------------

class ChatterboxEngine:
    """resemble-ai Chatterbox: zero-shot clone from one reference clip.

    PerTh watermarking is built into ``generate()`` — nothing to add.
    """

    def __init__(self, refs: ReferenceSet, device: str, seed: int):
        import torch
        from chatterbox.tts import ChatterboxTTS

        self._torch = torch
        self.seed = seed
        self.ref = refs.primary
        self.model = ChatterboxTTS.from_pretrained(device=device)

    def describe(self) -> str:
        return (f"chatterbox (ChatterboxTTS.from_pretrained), ref={self.ref.name}, "
                f"seed={self.seed}, default exaggeration/cfg")

    def synthesize(self, text: str, out_path: pathlib.Path) -> None:
        # torchaudio>=2.9 routes save() through torchcodec, which needs
        # system FFmpeg libs this WSL lacks — write with soundfile instead.
        import soundfile as sf

        self._torch.manual_seed(self.seed)
        wav = self.model.generate(text, audio_prompt_path=str(self.ref))
        arr = wav.detach().cpu().numpy()
        if arr.ndim == 2:
            arr = arr.T  # (channels, n) -> (n, channels)
        sf.write(str(out_path), arr, self.model.sr)


def _shim_torchaudio_io() -> None:
    """Replace torchaudio.load/save with soundfile-backed versions.

    torchaudio>=2.9 delegates I/O to torchcodec, which requires system FFmpeg
    libraries unavailable in this WSL (no sudo). Engines that call
    torchaudio.load/save internally (F5-TTS) work fine once I/O goes through
    soundfile; the DSP paths are untouched.
    """
    import soundfile as sf
    import torch
    import torchaudio

    def _load(path, *args, **kwargs):
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return torch.from_numpy(data.T), sr

    def _save(path, tensor, sample_rate, *args, **kwargs):
        arr = tensor.detach().cpu().numpy()
        if arr.ndim == 2:
            arr = arr.T
        sf.write(str(path), arr, sample_rate)

    torchaudio.load = _load
    torchaudio.save = _save


class F5Engine:
    """SWivid F5-TTS: flow matching; needs reference audio + its transcript."""

    def __init__(self, refs: ReferenceSet, device: str, seed: int):
        _shim_torchaudio_io()  # before f5 touches torchaudio I/O
        from f5_tts.api import F5TTS

        self.seed = seed
        self.ref = refs.primary
        self.ref_text = refs.primary_transcript()
        if self.ref_text is None:
            print(f"WARNING: no transcript at {refs.primary_transcript_path}; "
                  "falling back to F5's built-in ASR (loads Whisper). "
                  "Run scripts/transcribe_voice_refs.py first to avoid this.",
                  file=sys.stderr)
        self.tts = F5TTS(device=device)

    def describe(self) -> str:
        return (f"f5 (F5TTS default model), ref={self.ref.name}, "
                f"ref_text={'file' if self.ref_text else 'auto-ASR'}, seed={self.seed}")

    def synthesize(self, text: str, out_path: pathlib.Path) -> None:
        kwargs = dict(ref_file=str(self.ref), ref_text=self.ref_text or "",
                      gen_text=text, file_wave=str(out_path))
        try:
            self.tts.infer(seed=self.seed, **kwargs)
        except TypeError:  # older f5-tts without a seed kwarg
            self.tts.infer(**kwargs)


class XTTSEngine:
    """Coqui XTTS-v2 (idiap-maintained fork, ``coqui-tts``).

    LICENSE: Coqui Public Model License — NON-COMMERCIAL. Fine for this
    evaluation; must be flagged in the verdict if it wins (protocol doc §1).
    Accepts multiple speaker wavs, so it gets the whole era set.
    """

    def __init__(self, refs: ReferenceSet, device: str, seed: int):
        import os

        os.environ.setdefault("COQUI_TOS_AGREED", "1")
        import torch
        from TTS.api import TTS

        self._torch = torch
        self.seed = seed
        self.refs = [str(p) for p in refs.clips]
        self.tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)

    def describe(self) -> str:
        return (f"xtts (tts_models/multilingual/multi-dataset/xtts_v2, "
                f"CPML non-commercial), refs={len(self.refs)} clips, "
                f"seed={self.seed}, language=en")

    def synthesize(self, text: str, out_path: pathlib.Path) -> None:
        self._torch.manual_seed(self.seed)
        self.tts.tts_to_file(text=text, speaker_wav=self.refs, language="en",
                             file_path=str(out_path))


_ENGINE_CLASSES = {
    "chatterbox": ChatterboxEngine,
    "f5": F5Engine,
    "xtts": XTTSEngine,
}
assert tuple(_ENGINE_CLASSES) == ENGINES


def make_engine(engine: str, refs: ReferenceSet, device: str, seed: int):
    """Instantiate an engine adapter (this is where heavy imports happen)."""
    try:
        cls = _ENGINE_CLASSES[engine]
    except KeyError:
        raise ValueError(f"unknown engine {engine!r}; choose from {ENGINES}")
    return cls(refs, device=device, seed=seed)


# --- runner -----------------------------------------------------------------

def _wav_seconds(path: pathlib.Path) -> float | None:
    """Duration of a wav file, engine-agnostic; None if unreadable."""
    try:
        import soundfile as sf  # present in every engine venv (librosa dep)

        info = sf.info(str(path))
        return info.frames / info.samplerate
    except Exception:
        try:
            import wave

            with wave.open(str(path), "rb") as w:
                return w.getnframes() / w.getframerate()
        except Exception:
            return None


def run(args: argparse.Namespace) -> int:
    texts = load_test_script(args.doc)
    refs = build_reference_set(args.era, args.ref_dir, args.ref_clip)
    plan = build_plan(texts, args.engine, args.era, args.out_root, args.limit)

    if args.list:
        print(f"# plan: engine={args.engine} era={args.era} "
              f"refs={[p.name for p in refs.clips]} primary={refs.primary.name} "
              f"seed={args.seed} device={args.device}")
        for n, text, out_path in plan:
            print(f"{n:2d}  {out_path}  <- {text[:60]}...")
        return 0

    missing = [p for p in refs.clips if not p.is_file()]
    if missing:
        print(f"ERROR: missing reference clips: {[str(p) for p in missing]}\n"
              "Reference clips live in assets/voices/elder/ (local-only; see "
              "assets/voices/README.md).", file=sys.stderr)
        return 1

    pending = [(n, t, p) for n, t, p in plan
               if args.overwrite or not p.is_file()]
    skipped = len(plan) - len(pending)
    if skipped:
        print(f"skipping {skipped} existing outputs (use --overwrite to redo)")
    if not pending:
        print("nothing to do.")
        return 0

    t0 = time.monotonic()
    engine = make_engine(args.engine, refs, device=args.device, seed=args.seed)
    load_s = time.monotonic() - t0
    print(f"engine ready in {load_s:.1f}s: {engine.describe()}")

    out_dir = plan[0][2].parent
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "synthesis_log.jsonl"
    with log_path.open("a", encoding="utf-8") as log:
        log.write(json.dumps({"event": "session", "engine": args.engine,
                              "era": args.era, "device": args.device,
                              "seed": args.seed, "load_seconds": round(load_s, 2),
                              "describe": engine.describe()}) + "\n")
        for n, text, out_path in pending:
            t0 = time.monotonic()
            engine.synthesize(text, out_path)
            elapsed = time.monotonic() - t0
            audio_s = _wav_seconds(out_path)
            rtf = round(elapsed / audio_s, 3) if audio_s else None
            rec = {"response": n, "seconds": round(elapsed, 2),
                   "audio_seconds": round(audio_s, 2) if audio_s else None,
                   "rtf": rtf, "file": out_path.name}
            log.write(json.dumps(rec) + "\n")
            print(f"[{n:2d}/{len(texts)}] {out_path.name}  "
                  f"{elapsed:6.1f}s  audio={audio_s and f'{audio_s:.1f}s'}  rtf={rtf}")
    print(f"done: {len(pending)} responses -> {out_dir}")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Synthesize the 20 blind-test responses with one engine "
                    "and one reference condition (docs/voice-blind-test.md).")
    ap.add_argument("--engine", required=True, choices=ENGINES)
    ap.add_argument("--era", required=True, choices=sorted(ERA_CLIPS),
                    help="reference condition: 1990 (clips 01-05) or 2005 (clips 06-09)")
    ap.add_argument("--limit", type=int, default=None,
                    help="synthesize only the first N responses (smoke runs)")
    ap.add_argument("--device", default="cuda",
                    help="torch device for the engine (default: cuda; use cpu "
                         "for the placement benchmark's CPU pass)")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED,
                    help=f"fixed seed where the engine supports it (default {DEFAULT_SEED})")
    ap.add_argument("--ref-clip", default=None, metavar="elder_ref_NN.wav",
                    help="override the primary (single-ref) clip within the era set")
    ap.add_argument("--ref-dir", type=pathlib.Path, default=DEFAULT_REF_DIR)
    ap.add_argument("--out-root", type=pathlib.Path, default=DEFAULT_OUT_ROOT)
    ap.add_argument("--doc", type=pathlib.Path, default=DOC_PATH,
                    help="protocol doc to parse the test script from")
    ap.add_argument("--list", action="store_true",
                    help="print the synthesis plan and exit (no engine imports)")
    ap.add_argument("--overwrite", action="store_true",
                    help="re-synthesize responses whose output already exists")
    return ap


def main(argv: list[str] | None = None) -> int:
    return run(build_arg_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
