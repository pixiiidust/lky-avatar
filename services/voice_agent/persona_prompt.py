"""Persona instructions for the voice agent (issue #6).

Builds the system prompt the agent sends to the brain API. The brain server
deliberately does NOT inject a persona prompt — the agent owns the framing —
so this module is the single place the spoken persona is assembled:

1. The base persona line comes byte-for-byte from the vendored
   ``lky_avatar.persona.system_prompt()`` (parity with lky-brain is verified
   elsewhere; never reword it here).
2. The time-traveler framing variant on top of it is issue #2's experiment:

   - variant ``A`` — the base prompt alone (present-day date only)
   - variant ``B`` — base prompt + the present-day-awareness /
     anti-fabrication sentence (the spec's Implementation Decisions already
     mandate the anti-fabrication rule, so ``B`` is the default)

   Issue #2's verdict is still being evaluated on GPU; whichever way it
   lands, flipping ``LKY_PROMPT_VARIANT`` is the only change required.
3. The spoken-answer style policy (spec user story 8: short 2–5 sentence
   answers) is appended as a separate paragraph — it never alters the
   persona text itself.

Pure logic: no LiveKit imports, unit-testable anywhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

# lky_avatar lives at the repo root (services/voice_agent/ -> two up).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lky_avatar import persona  # noqa: E402  (needs the sys.path bootstrap)

#: Simulated "present day" for the time-traveler framing (issue #2).
DEFAULT_SIM_DATE = "2026-07-13"

VARIANT_A = "A"
VARIANT_B = "B"
DEFAULT_VARIANT = VARIANT_B

#: Variant B's addition — exact wording under evaluation in issue #2.
#: Do not reword without a new eval run.
PRESENT_DAY_AWARENESS = (
    " You are aware of world developments up to the present day. Reason from"
    " your principles and experience; do not fabricate specific quotes,"
    " meetings, or personal memories."
)

#: Spoken-answer policy (spec user story 8). Lives at the agent, not the
#: brain server, together with LKY_MAX_TOKENS as the hard budget.
SPOKEN_STYLE_POLICY = (
    "You are speaking aloud in a live voice conversation. Answer in short"
    " spoken style: roughly two to five sentences, then stop. No markdown,"
    " no lists, no headings, no stage directions."
)


def _validate_date(date: str) -> None:
    """Cheap YYYY-MM-DD shape check with an env-var-naming error message."""
    parts = date.split("-")
    ok = (
        len(date) == 10
        and len(parts) == 3
        and all(p.isdigit() for p in parts)
        and 1 <= int(parts[1]) <= 12
        and 1 <= int(parts[2]) <= 31
    )
    if not ok:
        raise ValueError(
            f"LKY_SIM_DATE must be YYYY-MM-DD (got {date!r}); see .env.example."
        )


def normalize_variant(variant: str) -> str:
    """``'b '`` -> ``'B'``; unknown values raise with the env-var name."""
    v = variant.strip().upper()
    if v not in (VARIANT_A, VARIANT_B):
        raise ValueError(
            f"LKY_PROMPT_VARIANT must be 'A' or 'B' (got {variant!r});"
            " see .env.example."
        )
    return v


def persona_system_prompt(
    date: str = DEFAULT_SIM_DATE, variant: str = DEFAULT_VARIANT
) -> str:
    """The persona framing: vendored base prompt + the variant's addition."""
    _validate_date(date)
    v = normalize_variant(variant)
    base = persona.system_prompt(date)
    if v == VARIANT_A:
        return base
    return base + PRESENT_DAY_AWARENESS


def build_instructions(
    date: str = DEFAULT_SIM_DATE, variant: str = DEFAULT_VARIANT
) -> str:
    """Full Agent instructions: persona framing + spoken-answer policy."""
    return persona_system_prompt(date, variant) + "\n\n" + SPOKEN_STYLE_POLICY
