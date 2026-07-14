"""Puts the service directory (flat modules: app, engine, config, streaming)
and the repo root (lky_avatar) on sys.path, so tests run from anywhere with
this service's venv: ``cd services/brain_api && .venv/Scripts/python -m pytest``.
"""

import sys
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parent
REPO_ROOT = SERVICE_DIR.parents[1]

for path in (str(SERVICE_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)
