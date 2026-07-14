"""Env-driven configuration for the brain API (issue #5).

The service runs as flat modules from ``services/brain_api`` (``uvicorn
app:app``), while the locked persona constants live at the repo root in
``lky_avatar/persona.py`` — importing this module first puts the repo root
on ``sys.path`` so both import styles work.

Engine selection is ``BRAIN_ENGINE``: ``transformers`` (the real model —
WSL/CUDA only) or ``fake`` (deterministic token stream; used by ALL tests,
per the spec's Seam-1 testing decision).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lky_avatar import persona  # noqa: E402  (needs the sys.path bootstrap)

ENGINE_FAKE = "fake"
ENGINE_TRANSFORMERS = "transformers"

#: Hard ceiling on max_tokens per request. Requests above this are rejected
#: with 400 — at the measured single-digit tok/s of NF4 decode on this GPU an
#: unbounded generation would hold the single generation slot for minutes.
MAX_TOKENS_HARD_CAP = 1024

#: Voice-friendly default (~2-5 spoken sentences, plan §7 Milestone 2).
DEFAULT_MAX_TOKENS = 320

DEFAULT_MODEL_NAME = "lky"
DEFAULT_BASE_MODEL = "Qwen/Qwen3-14B"

#: Soft post-warmup VRAM check (GiB allocated). Probe on 2026-07-13 measured
#: ~10.5 GiB peak allocated for Qwen3-14B NF4 + epoch-2 adapter; exceeding
#: ~12 GiB on this 16 GB card risks shared-memory spill. Soft check: warn,
#: don't refuse to serve.
DEFAULT_VRAM_WARN_GIB = 12.0

#: Deterministic stream for the FakeEngine (joined pieces == this text).
DEFAULT_FAKE_TEXT = (
    "The fundamentals do not change: discipline, education, and the will "
    "to adapt decide whether a society thrives. Nothing is free in this "
    "world. You must be realistic about that."
)
DEFAULT_FAKE_DELAY_MS = 5.0


def _get_float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _get_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _strip_inline_comment(value: str) -> str:
    """``sjsim/lky-qlora   # epoch-2`` -> ``sjsim/lky-qlora``."""
    return value.split(" #")[0].split("\t#")[0].strip()


@dataclass(frozen=True)
class BrainConfig:
    """Everything the brain server needs, resolved from LKY_*/BRAIN_* vars."""

    engine: str = ENGINE_TRANSFORMERS
    model_name: str = DEFAULT_MODEL_NAME
    base_model: str = DEFAULT_BASE_MODEL
    adapter: str = persona.ADAPTER_HF_ID
    default_max_tokens: int = DEFAULT_MAX_TOKENS
    vram_warn_gib: float = DEFAULT_VRAM_WARN_GIB
    fake_text: str = DEFAULT_FAKE_TEXT
    fake_delay_ms: float = DEFAULT_FAKE_DELAY_MS
    #: Message content is NEVER logged unless this is explicitly enabled.
    log_content: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "BrainConfig":
        env = os.environ if env is None else env
        return cls(
            engine=env.get("BRAIN_ENGINE", ENGINE_TRANSFORMERS).strip().lower()
            or ENGINE_TRANSFORMERS,
            model_name=env.get("LKY_MODEL_NAME", DEFAULT_MODEL_NAME).strip()
            or DEFAULT_MODEL_NAME,
            base_model=env.get("LKY_BASE_MODEL", DEFAULT_BASE_MODEL).strip()
            or DEFAULT_BASE_MODEL,
            adapter=_strip_inline_comment(env.get("LKY_ADAPTER", ""))
            or persona.ADAPTER_HF_ID,
            default_max_tokens=_get_int(env, "LKY_MAX_TOKENS", DEFAULT_MAX_TOKENS),
            vram_warn_gib=_get_float(env, "LKY_VRAM_WARN_GIB", DEFAULT_VRAM_WARN_GIB),
            fake_text=env.get("BRAIN_FAKE_TEXT", "") or DEFAULT_FAKE_TEXT,
            fake_delay_ms=_get_float(env, "BRAIN_FAKE_DELAY_MS", DEFAULT_FAKE_DELAY_MS),
            log_content=env.get("BRAIN_LOG_CONTENT", "").strip().lower()
            in ("1", "true", "yes"),
            host=env.get("BRAIN_HOST", "0.0.0.0").strip() or "0.0.0.0",
            port=_get_int(env, "BRAIN_PORT", 8000),
        )
