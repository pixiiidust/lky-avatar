"""Shuffle-and-rename blinding for the voice blind test (issue #7).

Runnable form of the procedure in ``docs/voice-blind-test.md`` §3: after ALL
synthesis is complete, copies every ``raw/<engine>-<era>/response_NN.wav``
into ``blind/sample_XXX.wav`` in random order, writes the ``key.json``
mapping, and creates an empty ``scores.csv`` sheet with one row per sample.

    python scripts/blind_shuffle.py            # fresh random shuffle
    python scripts/blind_shuffle.py --seed 42  # reproducible shuffle

Rules (protocol doc §3): do NOT open ``key.json`` until every sample in
``scores.csv`` is scored. Everything under ``assets/voices/`` is gitignored.

Stdlib-only; pure logic (mapping construction, label parsing) is unit-tested
in ``tests/test_blind_shuffle.py``.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import shutil
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_ROOT = REPO_ROOT / "assets" / "voices" / "blind-test"

SCORE_COLUMNS = ("sample", "similarity", "naturalness", "intelligibility",
                 "pacing", "stability", "regional", "notes")


def parse_condition_label(label: str) -> tuple[str, str | None]:
    """Split a raw/ directory name into (engine, era).

    ``chatterbox-2005`` -> (``chatterbox``, ``2005``); a name without a
    4-digit era suffix (plain protocol layout) -> (name, None).
    """
    head, sep, tail = label.rpartition("-")
    if sep and tail.isdigit() and len(tail) == 4:
        return head, tail
    return label, None


def build_blind_mapping(rel_paths: list[str], seed: int | None,
                        ) -> dict[str, dict]:
    """Deterministic (given a seed) sample -> provenance mapping.

    ``rel_paths`` are POSIX-style paths relative to ``raw/``, e.g.
    ``chatterbox-2005/response_07.wav``. Input order does not matter: paths
    are sorted before the seeded shuffle, so the same file set and seed always
    produce the same mapping.
    """
    order = sorted(rel_paths)
    rng = random.Random(seed)
    rng.shuffle(order)
    key: dict[str, dict] = {}
    for i, rel in enumerate(order, 1):
        label, stem = rel.split("/", 1)[0], pathlib.PurePosixPath(rel).stem
        engine, era = parse_condition_label(label)
        entry = {"engine": engine, "response": stem}
        if era is not None:
            entry["era"] = era
        key[f"sample_{i:03d}.wav"] = entry
    return key


def scores_csv_text(n_samples: int) -> str:
    lines = [",".join(SCORE_COLUMNS)]
    lines += [f"sample_{i:03d}" + "," * (len(SCORE_COLUMNS) - 1)
              for i in range(1, n_samples + 1)]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Blind the synthesized samples: shuffle raw/*/response_NN.wav "
                    "into blind/sample_XXX.wav + key.json + empty scores.csv.")
    ap.add_argument("--root", type=pathlib.Path, default=DEFAULT_ROOT,
                    help="blind-test working directory (default: %(default)s)")
    ap.add_argument("--seed", type=int, default=None,
                    help="shuffle seed (default: fresh randomness)")
    ap.add_argument("--force", action="store_true",
                    help="redo blinding even if blind/key.json already exists")
    args = ap.parse_args(argv)

    raw = args.root / "raw"
    files = sorted(raw.glob("*/response_*.wav"))
    if not files:
        print(f"ERROR: no synthesized files under {raw}/<engine>/ — run "
              "scripts/blind_test_synthesize.py for every engine+era first.",
              file=sys.stderr)
        return 1

    blind = args.root / "blind"
    if (blind / "key.json").exists() and not args.force:
        print(f"ERROR: {blind / 'key.json'} already exists; blinding must not "
              "be redone mid-scoring. Pass --force to reshuffle from scratch.",
              file=sys.stderr)
        return 1

    rel_paths = [f.relative_to(raw).as_posix() for f in files]
    key = build_blind_mapping(rel_paths, args.seed)

    blind.mkdir(parents=True, exist_ok=True)
    for name, entry in key.items():
        src_label = entry["engine"] + (f"-{entry['era']}" if "era" in entry else "")
        shutil.copy2(raw / src_label / f"{entry['response']}.wav", blind / name)
    (blind / "key.json").write_text(json.dumps(key, indent=2) + "\n",
                                    encoding="utf-8")

    scores = args.root / "scores.csv"
    if not scores.exists() or args.force:
        scores.write_text(scores_csv_text(len(key)), encoding="utf-8")

    print(f"{len(key)} samples blinded into {blind}.")
    print(f"Score sheet: {scores}")
    print("Do NOT open key.json until scores.csv is complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
