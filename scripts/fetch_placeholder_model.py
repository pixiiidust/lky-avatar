#!/usr/bin/env python3
"""Download the licensed placeholder Live2D model (Hiyori) into web/public/models/.

The model files are deliberately NOT committed (see .gitignore and
web/public/models/README.md); every checkout runs this script once instead:

    python scripts/fetch_placeholder_model.py

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

import json
import sys
import urllib.request
from pathlib import Path

REPO = "Live2D/CubismWebSamples"
TAG = "5-r.5"  # pinned so downloads are reproducible
MODEL_DIR_IN_REPO = "Samples/Resources/Hiyori"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{TAG}"
API_BASE = f"https://api.github.com/repos/{REPO}/contents"

DEST = Path(__file__).resolve().parent.parent / "web" / "public" / "models" / "hiyori"

# Everything the model3.json references, plus the licence/notice files that
# must travel with the material per the Free Material License.
FILES = [
    f"{MODEL_DIR_IN_REPO}/Hiyori.model3.json",
    f"{MODEL_DIR_IN_REPO}/Hiyori.moc3",
    f"{MODEL_DIR_IN_REPO}/Hiyori.physics3.json",
    f"{MODEL_DIR_IN_REPO}/Hiyori.pose3.json",
    f"{MODEL_DIR_IN_REPO}/Hiyori.cdi3.json",
    f"{MODEL_DIR_IN_REPO}/Hiyori.userdata3.json",
    f"{MODEL_DIR_IN_REPO}/Hiyori.2048/texture_00.png",
    f"{MODEL_DIR_IN_REPO}/Hiyori.2048/texture_01.png",
    "LICENSE.md",
    "NOTICE.md",
]


def list_motions() -> list[str]:
    """Motion files are enumerated from the repo so the set never drifts."""
    url = f"{API_BASE}/{MODEL_DIR_IN_REPO}/motions?ref={TAG}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        entries = json.load(resp)
    return [e["path"] for e in entries if e["name"].endswith(".motion3.json")]


def fetch(repo_path: str) -> None:
    rel = (
        repo_path[len(MODEL_DIR_IN_REPO) + 1 :]
        if repo_path.startswith(MODEL_DIR_IN_REPO)
        else repo_path
    )
    target = DEST / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    url = f"{RAW_BASE}/{repo_path}"
    print(f"  {url}\n    -> {target.relative_to(DEST.parent.parent.parent)}")
    with urllib.request.urlopen(url, timeout=60) as resp:
        target.write_bytes(resp.read())


def main() -> int:
    print(f"Fetching placeholder model Hiyori ({REPO}@{TAG}) into {DEST}")
    print("License: Live2D Free Material License Agreement (see files below).")
    try:
        paths = FILES + list_motions()
        for path in paths:
            fetch(path)
    except Exception as exc:  # noqa: BLE001 - report and fail the script
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    model3 = DEST / "Hiyori.model3.json"
    if not model3.is_file() or model3.stat().st_size == 0:
        print("ERROR: Hiyori.model3.json missing after download", file=sys.stderr)
        return 1
    print(f"\nDone: {len(paths)} files. Model entry point: {model3}")
    print("The web client loads it from /models/hiyori/Hiyori.model3.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
