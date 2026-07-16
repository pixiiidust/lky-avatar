"""Fact-grounding retrieval + prompt injection seam (issue #45).

The persona QLoRA teaches style, not facts. A 14B model at Q4 has thin
parametric Singapore-history knowledge and no retrieval layer to check
against — so the live-session failure mode is confident first-person
recollection that is wrong (e.g. claiming Toa Payoh / Ang Mo Kio as "my
constituencies" — LKY's only seat was Tanjong Pagar).

This module is the simplest thing that can work: it loads the audited fact
sheet (``assets/persona/lky_facts.md``), splits it on the ``---`` separator
into labeled sections, and on each user turn returns the sections whose
keywords best match the turn. The retrieved sections are then injected
behind a "trust these dates over your memory" instruction by
``build_grounding_block``, which the voice agent layers into its
instructions WITHOUT touching the serving infrastructure (the brain seam
is the OpenAI-compatible endpoint the agent already calls).

Design choices:

- **Pure logic, no SDK, no network, no embeddings.** Unit-testable on any
  machine, matching the repo's pure-module convention (config.py,
  persona_prompt.py, pronunciation.py).
- **Section-based retrieval, not whole-sheet injection.** The fact sheet
  is split into labeled units (Constituencies, HDB, Water, ...) so only
  the relevant slice goes into the prompt — keeping the token budget
  reasonable and avoiding context dilution.
- **Keyword overlap scoring.** Deliberately simple and predictable: the
  section's keywords are matched (case-insensitive, word boundary) against
  the user's turn; the N highest-overlap sections win. This is not a
  vector store and does not try to be.
- **No-op when disabled.** ``LKY_FACT_SHEET`` empty / missing -> the
  grounding block is an empty string and the instructions are unchanged,
  so the brain runs exactly as it does today.

Extension: point ``LKY_FACT_SHEET`` at a different markdown file to swap
the grounding source. The section format (``## Section: <title>`` followed
by a body, separated by ``---``) is the only contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: Path to the audited fact sheet, relative to the repo root. Resolved by
#: the voice agent from the repo-root path it already computes; see
#: ``default_fact_sheet_path``.
DEFAULT_FACT_SHEET_REL = "assets/persona/lky_facts.md"

#: The instruction that frames the injected facts to the brain. It must
#: be firm — "trust these over your memory" — but must NOT tell the model
#: to read the facts aloud; the persona voice is preserved by the
#: surrounding instructions.
GROUNDING_PREAMBLE = (
    "The following are audited biographical facts about Lee Kuan Yew"
    " and Singapore. Trust these dates, offices, and constituency"
    " details over your own memory; if your memory of a fact conflicts"
    " with what is written here, what is written here is correct. Do not"
    " quote these facts verbatim or recite them — use them only to keep"
    " your answers truthful."
)

#: The uncertainty guardrail appended to every grounded instruction block
#: (issue #45 scope item 4). Cheapest possible fabrication brake: when
#: unsure of a specific date, place, or statistic, speak in general terms
#: rather than inventing specifics.
UNCERTAINTY_GUARDRAIL = (
    "If you are not certain of a specific date, place, name, or"
    " statistic, speak in general terms rather than inventing a"
    " specific one. A vague answer from you is more truthful than a"
    " confident wrong date."
)


def default_fact_sheet_path(repo_root: str | Path) -> Path:
    """Resolve the default fact-sheet path from the repo root."""
    return Path(repo_root) / DEFAULT_FACT_SHEET_REL


_SECTION_HEADER_RE = re.compile(r"^##\s+Section:\s*(.+?)\s*$", re.MULTILINE)
_SECTION_SPLIT_RE = re.compile(r"^---\s*$", re.MULTILINE)

#: Title/body words with no retrieval signal — dropped from keywords.
_STOPWORDS = {
    "and", "the", "of", "a", "an", "in", "on", "for", "to", "with",
    "basics", "section", "selected", "key",
}


@dataclass
class FactSection:
    """One labeled, retrievable unit of the fact sheet."""

    title: str
    body: str
    keywords: tuple[str, ...] = ()

    def match_score(self, turn: str) -> int:
        """Number of this section's keywords that appear (word-bounded,
        case-insensitive) in ``turn``. Higher = more relevant."""
        turn_l = turn.lower()
        score = 0
        for kw in self.keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", turn_l):
                score += 1
        return score


def _extract_keywords(title: str, body: str) -> tuple[str, ...]:
    """Crude keyword set for a section: the title words plus any
    capitalized / notable proper nouns in the body. We intentionally do
    not try to be clever — overlap scoring just needs a signal, and the
    section count is small. Plural proper nouns (e.g. "constituencies")
    also emit their singular form so "constituency" in a turn matches."""
    words: list[str] = []
    for w in re.findall(r"[A-Za-z]+", title):
        wl = w.lower()
        if wl in _STOPWORDS or len(wl) < 3:
            continue
        words.append(wl)
    # Body proper nouns (Capitalized words) plus explicit acronyms
    # (all-caps >=2 letters). Lowercased for matching.
    for m in re.finditer(r"\b([A-Z][a-z]+|[A-Z]{2,})\b", body):
        words.append(m.group(1).lower())
    # Dedup, preserve order, and add singular forms for plural words so a
    # turn saying "constituency" matches the keyword "constituencies".
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
        sing = _singularize(w)
        if sing and sing not in seen:
            seen.add(sing)
            out.append(sing)
    return tuple(out)


def _singularize(word: str) -> str | None:
    """Return a singular form for common English plurals, or None.

    Deliberately covers only the two patterns the fact sheet uses
    ("-ies" -> "-y", "-es" -> drop the 's'); this is not a general
    stemmer and does not need to be."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("es") and len(word) > 3:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return None


def _parse_sections(text: str) -> list[FactSection]:
    """Split the fact sheet on ``---`` and parse each labeled section."""
    sections: list[FactSection] = []
    for raw in _SECTION_SPLIT_RE.split(text):
        raw = raw.strip()
        if not raw:
            continue
        m = _SECTION_HEADER_RE.search(raw)
        if not m:
            continue  # skip non-section blocks (preamble, etc.)
        title = m.group(1).strip()
        body = raw[m.end():].strip()
        if not body:
            continue
        sections.append(
            FactSection(
                title=title,
                body=body,
                keywords=_extract_keywords(title, body),
            )
        )
    return sections


def load_fact_sheet(path: str | Path) -> list[FactSection]:
    """Parse the fact sheet into labeled, retrievable sections.

    Returns an ordered list of ``FactSection``. The order matches the file
    so top-k retrieval breaks ties toward the earlier, higher-priority
    sections.
    """
    text = Path(path).read_text(encoding="utf-8")
    return _parse_sections(text)


def retrieve(
    user_turn: str, sections: list[FactSection], top_k: int = 2
) -> list[FactSection]:
    """Return the ``top_k`` sections whose keywords best match the turn.

    Ties break toward earlier sections (the file order reflects
    author-intended priority). Returns an empty list when no section has
    any keyword match (no spurious injection) or when the sheet is empty.
    """
    scored = [
        (s.match_score(user_turn), i, s) for i, s in enumerate(sections)
    ]
    scored = [t for t in scored if t[0] > 0]
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [s for _, _, s in scored[:top_k]]


def build_grounding_block(sections: list[FactSection]) -> str:
    """Render retrieved sections into the instruction text injected into
    the system prompt. Returns "" when no sections were retrieved (the
    no-op case — instructions are unchanged)."""
    if not sections:
        return ""
    parts = [GROUNDING_PREAMBLE, ""]
    for s in sections:
        parts.append(f"### {s.title}")
        parts.append(s.body)
        parts.append("")
    parts.append(UNCERTAINTY_GUARDRAIL)
    return "\n".join(parts).strip()


def grounding_for_turn(
    user_turn: str,
    fact_sheet_path: str | Path | None,
    *,
    top_k: int = 2,
) -> str:
    """Convenience: load the sheet and return the grounding block for a
    single turn. Empty/None path -> "". A missing file returns "" rather
    than raising (a live session must not crash on a bad path); tests
    pin the explicit OSError path on ``load_fact_sheet`` directly."""
    if not fact_sheet_path:
        return ""
    try:
        sections = load_fact_sheet(fact_sheet_path)
    except OSError:
        return ""
    return build_grounding_block(retrieve(user_turn, sections, top_k=top_k))
