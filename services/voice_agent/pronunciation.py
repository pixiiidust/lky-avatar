"""Pronunciation overrides for the cloned voice (issue #8).

The blind-test winner (Chatterbox) reads text from spelling, so regional
terms that English spelling rules mangle — party/board acronyms, Hokkien and
Malay words, Mandarin names — get phonetic respellings applied to the text
JUST before synthesis. The respelled text goes only to the TTS engine; the
transcript the visitor sees keeps the real spelling (the LiveKit SDK's
StreamAdapter emits the transcript from the original sentence before our
adapter's ``synthesize()`` ever sees it).

Pure logic — no audio stack, no SDK imports — unit-tested on Windows.

Matching rules (deliberately simple and predictable):

- Whole words/phrases only (regex word boundaries): "PAP" never rewrites
  "PAPER".
- Acronym keys (all uppercase) match case-sensitively, so prose words like
  "pap" are untouched.
- Everything else matches case-insensitively ("hokkien" and "Hokkien" both
  rewrite).
- Longest key wins where keys overlap ("Lee Kuan Yew" before any single-word
  entry could fire inside it).

Extension: point ``LKY_TTS_PRONUNCIATIONS`` at a JSON object of
``{"spelling": "respelling"}``. Entries merge over the defaults; a ``null``
or empty value removes a default entry.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

#: Spelling -> phonetic respelling for terms the winner engine gets wrong or
#: risky from raw spelling. Verified terms that Chatterbox already renders
#: correctly from spelling (blind-test WER 0.021 across the 20-response
#: script, which exercises "Singapore", "Malay", "Mandarin", "bilingualism")
#: are deliberately NOT respelled — every rewrite is a chance to sound worse.
DEFAULT_PRONUNCIATIONS: dict[str, str] = {
    # Acronyms: spelled out letter by letter, never read as words.
    "PAP": "P. A. P.",
    "HDB": "H. D. B.",
    "CPF": "C. P. F.",
    "ASEAN": "AH-see-ahn",
    # The man himself and the Mandarin-romanized names around him.
    "Lee Kuan Yew": "Lee Kwan Yoo",
    "Lee Hsien Loong": "Lee Shen Loong",
    "Goh Chok Tong": "Goh Chock Tong",
    "Goh Keng Swee": "Goh Keng Sway",
    # Dialects and Malay terms.
    "Hokkien": "Hock-kee-en",
    "Teochew": "Teo-choo",
    "kampung": "kahm-pong",
    "kampong": "kahm-pong",
    "Tunku Abdul Rahman": "Toon-koo Ab-dool Rah-man",
    # Places.
    "Temasek": "Teh-mah-sek",
    "Tanjong Pagar": "Tan-jong Pah-gar",
    # Issue #45: SG proper-noun coverage the live session garbled — the
    # same list seeds the Deepgram STT keyword boost (agent.py) and the
    # TTS pronunciation map so input and output agree on spelling.
    "Toa Payoh": "Toh Pay-oh",
    "Ang Mo Kio": "Ang Moe Kee-oh",
    "Kallang": "Kah-lahng",
    "Sembawang": "Sem-bah-wahng",
    "NEWater": "New-water",
}


def load_overrides(path: str | Path) -> dict[str, str | None]:
    """Read a ``{"spelling": "respelling"}`` JSON file of extra overrides.

    Raises ValueError (with the path in the message) on malformed content,
    so a bad config fails loudly at agent startup instead of silently
    skipping entries mid-session.
    """
    raw = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"pronunciation file {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and (v is None or isinstance(v, str)) for k, v in data.items()
    ):
        raise ValueError(
            f"pronunciation file {path} must be a JSON object of "
            '{"spelling": "respelling"} (null removes a default entry)'
        )
    return data


def merge_overrides(
    base: Mapping[str, str], extra: Mapping[str, str | None]
) -> dict[str, str]:
    """Overlay ``extra`` on ``base``; None/empty values delete entries."""
    merged: dict[str, str] = dict(base)
    for key, value in extra.items():
        if value:
            merged[key] = value
        else:
            merged.pop(key, None)
    return merged


def _is_acronym(key: str) -> bool:
    letters = [c for c in key if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters) and " " not in key


class PronunciationMap:
    """Compiled spelling->respelling rewriter; build once, apply per phrase."""

    def __init__(self, overrides: Mapping[str, str] | None = None) -> None:
        entries = dict(DEFAULT_PRONUNCIATIONS if overrides is None else overrides)
        # Longest first so multi-word keys win over words they contain.
        ordered = sorted(entries, key=len, reverse=True)
        self._exact = {k: v for k, v in entries.items() if _is_acronym(k)}
        self._folded = {
            k.lower(): v for k, v in entries.items() if not _is_acronym(k)
        }
        if ordered:
            pattern = r"\b(?:" + "|".join(re.escape(k) for k in ordered) + r")\b"
            self._regex: re.Pattern[str] | None = re.compile(pattern, re.IGNORECASE)
        else:
            self._regex = None

    def _replace(self, match: re.Match[str]) -> str:
        word = match.group(0)
        if word in self._exact:  # acronym, case-sensitive
            return self._exact[word]
        return self._folded.get(word.lower(), word)

    def apply(self, text: str) -> str:
        """Rewrite every override occurrence in ``text``; everything else
        (punctuation, spacing, casing) passes through byte-identical."""
        if self._regex is None:
            return text
        return self._regex.sub(self._replace, text)


def build_pronunciation_map(
    pronunciations_path: str | Path | None = None,
) -> PronunciationMap:
    """The defaults, optionally overlaid with a JSON file (env-extensible)."""
    if not pronunciations_path:
        return PronunciationMap()
    extra = load_overrides(pronunciations_path)
    return PronunciationMap(merge_overrides(DEFAULT_PRONUNCIATIONS, extra))
