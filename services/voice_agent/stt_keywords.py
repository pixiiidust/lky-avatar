"""Deepgram STT keyword boost for Singapore proper nouns (issue #45).

The live session garbled proper nouns on the INPUT side ("Topayo",
"Ang Mokio") because Deepgram's generic English model does not weight
Singapore place and institution names. Deepgram's Nova-3 model accepts a
``keywords`` parameter — a list of ``(term, boost)`` tuples — that biases
recognition toward those terms.

This module is the single source of truth for that list. It is pure logic
(no SDK import) so it is unit-testable on any machine, matching the repo's
pure-module convention. The same proper-noun set also seeds the TTS
pronunciation map (``pronunciation.py``) so the input and output spellings
agree.

Boost: Deepgram recommends a boost between 0 and 1 for light biasing. We
use a single mid-range value (0.8) for every term — enough to fix the
garbling seen in the live session without over-weighting rare names into
unrelated turns. The terms cover the issue's examples plus the HDB/constituency
vocabulary the fact sheet anchors.

Extension: point ``LKY_STT_KEYWORDS`` at a JSON object of
``{"term": boost_number}`` to merge extra entries over the defaults; a
``null``/empty value removes a default entry (mirrors the pronunciation
override convention).
"""

from __future__ import annotations

import json
from pathlib import Path

#: Default boost applied to every term unless overridden. 0.8 is a light-
#: to-moderate bias: enough to fix garbled proper nouns without forcing
#: these terms into unrelated turns.
DEFAULT_BOOST = 0.8

#: The SG proper-noun keyword set (issue #45). The same names appear in the
#: fact sheet (assets/persona/lky_facts.md) and the TTS pronunciation map
#: so input transcription and output synthesis agree on spelling.
DEFAULT_KEYWORDS: dict[str, float] = {
    # Constituencies / towns (the live-session failure).
    "Tanjong Pagar": DEFAULT_BOOST,
    "Toa Payoh": DEFAULT_BOOST,
    "Ang Mo Kio": DEFAULT_BOOST,
    "Kallang": DEFAULT_BOOST,
    "Sembawang": DEFAULT_BOOST,
    # Institutions / policies.
    "Temasek": DEFAULT_BOOST,
    "NEWater": DEFAULT_BOOST,
    "HDB": DEFAULT_BOOST,
    "PAP": DEFAULT_BOOST,
    "CPF": DEFAULT_BOOST,
    # People (so transcription does not mangle the man's own name or his
    # successors').
    "Lee Kuan Yew": DEFAULT_BOOST,
    "Lee Hsien Loong": DEFAULT_BOOST,
    "Goh Chok Tong": DEFAULT_BOOST,
    "Kwa Geok Choo": DEFAULT_BOOST,
}


def load_overrides(path: str | Path) -> dict[str, float | None]:
    """Read a ``{"term": boost}`` JSON file of extra keyword overrides.

    Raises ValueError (with the path in the message) on malformed content,
    so a bad config fails loudly at agent startup instead of silently
    skipping entries mid-session. Mirrors pronunciation.load_overrides.
    """
    raw = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"stt keywords file {path} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and (v is None or isinstance(v, (int, float)))
        for k, v in data.items()
    ):
        raise ValueError(
            f"stt keywords file {path} must be a JSON object of "
            '{"term": boost_number} (null removes a default entry)'
        )
    return data


def merge_overrides(
    base: dict[str, float], extra: dict[str, float | None]
) -> dict[str, float]:
    """Overlay ``extra`` on ``base``; None/empty values delete entries."""
    merged: dict[str, float] = dict(base)
    for key, value in extra.items():
        if value:
            merged[key] = float(value)
        else:
            merged.pop(key, None)
    return merged


def build_keywords(
    keywords_path: str | Path | None = None,
) -> list[tuple[str, float]]:
    """The defaults, optionally overlaid with a JSON file, as the
    ``(term, boost)`` tuple list Deepgram's STT expects."""
    if not keywords_path:
        merged = dict(DEFAULT_KEYWORDS)
    else:
        extra = load_overrides(keywords_path)
        merged = merge_overrides(DEFAULT_KEYWORDS, extra)
    return [(term, boost) for term, boost in merged.items()]
