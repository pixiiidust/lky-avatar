#!/usr/bin/env python3
"""Download a licensed placeholder Live2D model into web/public/models/.

The model files are deliberately NOT committed (see .gitignore and
web/public/models/README.md); every checkout runs this script once instead:

    python scripts/fetch_placeholder_model.py [--model natori|hiyori]

Default is Natori (adult man, formal wear) — the closest match to the
subject among Live2D's free samples; the operator swapped it in for the
original Hiyori placeholder on 2026-07-15. Both remain fetchable.

Source: Live2D's official Cubism Web Samples repository (pinned tag), where
the sample models are published under the Live2D Free Material License
Agreement:
  https://github.com/Live2D/CubismWebSamples
  https://www.live2d.com/eula/live2d-free-material-license-agreement_en.html
  https://www.live2d.com/eula/live2d-sample-model-terms_en.html

By running this script you accept those terms for local development use.
Runs on stock Python 3.9+ (stdlib only).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

REPO = "Live2D/CubismWebSamples"
TAG = "5-r.5"  # pinned so downloads are reproducible
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{TAG}"
API_BASE = f"https://api.github.com/repos/{REPO}/contents"

WEB_MODELS = Path(__file__).resolve().parent.parent / "web" / "public" / "models"

# Everything each model3.json references (canned motions are enumerated from
# the repo at fetch time), plus the licence/notice files that must travel
# with the material per the Free Material License.
MODELS: dict[str, dict] = {
    "natori": {
        "dir": "Samples/Resources/Natori",
        "entry": "Natori.model3.json",
        "files": [
            "Natori.model3.json",
            "Natori.moc3",
            "Natori.physics3.json",
            "Natori.pose3.json",
            "Natori.cdi3.json",
            "Natori.2048/texture_00.png",
            "exp/Angry.exp3.json",
            "exp/Blushing.exp3.json",
            "exp/Normal.exp3.json",
            "exp/Sad.exp3.json",
            "exp/Smile.exp3.json",
            "exp/Surprised.exp3.json",
            "exp/exp_01.exp3.json",
            "exp/exp_02.exp3.json",
        ],
    },
    "hiyori": {
        "dir": "Samples/Resources/Hiyori",
        "entry": "Hiyori.model3.json",
        "files": [
            "Hiyori.model3.json",
            "Hiyori.moc3",
            "Hiyori.physics3.json",
            "Hiyori.pose3.json",
            "Hiyori.cdi3.json",
            "Hiyori.userdata3.json",
            "Hiyori.2048/texture_00.png",
            "Hiyori.2048/texture_01.png",
        ],
    },
}
LICENSE_FILES = ["LICENSE.md", "NOTICE.md"]


def list_motions(model_dir: str) -> list[str]:
    """Motion files are enumerated from the repo so the set never drifts."""
    url = f"{API_BASE}/{model_dir}/motions?ref={TAG}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            entries = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # model has no motions directory
            return []
        raise
    return [e["path"] for e in entries if e["name"].endswith(".motion3.json")]


def fetch(repo_path: str, model_dir: str, dest: Path) -> None:
    rel = (
        repo_path[len(model_dir) + 1 :]
        if repo_path.startswith(model_dir)
        else repo_path
    )
    target = dest / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    url = f"{RAW_BASE}/{repo_path}"
    print(f"  {url}\n    -> {target}")
    with urllib.request.urlopen(url, timeout=60) as resp:
        target.write_bytes(resp.read())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", choices=sorted(MODELS), default="natori")
    args = ap.parse_args()

    spec = MODELS[args.model]
    dest = WEB_MODELS / args.model
    print(f"Fetching placeholder model {args.model} ({REPO}@{TAG}) into {dest}")
    print("License: Live2D Free Material License Agreement (see files below).")
    try:
        paths = (
            [f"{spec['dir']}/{f}" for f in spec["files"]]
            + list_motions(spec["dir"])
            + LICENSE_FILES
        )
        for path in paths:
            fetch(path, spec["dir"], dest)
    except Exception as exc:  # noqa: BLE001 - report and fail the script
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    model3 = dest / spec["entry"]
    if not model3.is_file() or model3.stat().st_size == 0:
        print(f"ERROR: {spec['entry']} missing after download", file=sys.stderr)
        return 1
    print(f"\nDone: {len(paths)} files. Model entry point: {model3}")
    print(f"The web client loads it from /models/{args.model}/{spec['entry']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
