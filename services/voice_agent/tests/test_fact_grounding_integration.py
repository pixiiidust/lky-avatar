"""Issue #45 fact-grounding integration tests against the REAL pinned SDK.

These exercise the production path that the pure-logic tests cannot:
``_last_user_text`` against a real ``livekit.agents.llm.ChatContext`` whose
``add_message(content="...")`` stores content as ``list[str]`` (the pinned
livekit-agents 1.6.5 shape), and ``_grounded_chat_ctx`` ordering the
grounding system message immediately BEFORE the user turn rather than
appending after it.

Requires the voice_agent venv (livekit-agents 1.6.5); skips with
instructions if the SDK is not importable. No network, no LiveKit room.
"""

from __future__ import annotations

import pytest

pytest.importorskip("livekit.agents.llm")  # skip cleanly if venv missing

from livekit.agents import llm as llm_types  # noqa: E402

from agent import LKYAgent, _last_user_text  # noqa: E402
from persona_prompt import (  # noqa: E402
    FEW_SHOT_TURNS,
    build_instructions,
    fact_sheet_path_from_env,
)
from fact_grounding import load_fact_sheet  # noqa: E402

import os  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
FACT_SHEET = os.path.join(REPO_ROOT, "assets", "persona", "lky_facts.md")


def _agent_with_grounding() -> LKYAgent:
    """An LKYAgent whose fact sheet is the committed production sheet."""
    fact_sheet_path = fact_sheet_path_from_env({})  # default committed sheet
    instructions = build_instructions("2026-07-13", "C")
    return LKYAgent(
        instructions=instructions,
        fact_sheet_path=fact_sheet_path,
    )


def _production_like_ctx(user_question: str) -> llm_types.ChatContext:
    """Build a chat context shaped like a real session: system instructions,
    seeded few-shot exemplars, then the current user turn — exactly what
    ``LKYAgent.__init__`` seeds and what ``llm_node`` receives."""
    ctx = llm_types.ChatContext.empty()
    instructions = build_instructions("2026-07-13", "C")
    ctx.add_message(role="system", content=instructions)
    for turn in FEW_SHOT_TURNS:
        ctx.add_message(role=turn["role"], content=turn["content"])
    ctx.add_message(role="user", content=user_question)
    return ctx


# ── _last_user_text against the real SDK content shape ─────────────────────


def test_last_user_text_extracts_str_from_real_chat_context():
    """The pinned SDK wraps ``content="str"`` as ``list[str]``; the old
    hand-rolled parts walk returned ``""`` for this shape, making
    production grounding a no-op. ``text_content`` handles it."""
    ctx = llm_types.ChatContext.empty()
    ctx.add_message(role="system", content="instructions")
    ctx.add_message(role="user", content="What was your constituency? Toa Payoh?")
    # Confirm the SDK really stored a list (the bug shape):
    last_user = [m for m in ctx.items if m.role == "user"][-1]
    assert isinstance(last_user.content, list)
    assert isinstance(last_user.content[0], str)
    # And that our extractor now reads it:
    assert _last_user_text(ctx) == "What was your constituency? Toa Payoh?"


def test_last_user_text_picks_latest_user_turn():
    ctx = llm_types.ChatContext.empty()
    ctx.add_message(role="user", content="earlier question")
    ctx.add_message(role="assistant", content="earlier answer")
    ctx.add_message(role="user", content="latest question")
    assert _last_user_text(ctx) == "latest question"


def test_last_user_text_empty_when_no_user():
    ctx = llm_types.ChatContext.empty()
    ctx.add_message(role="system", content="only system")
    assert _last_user_text(ctx) == ""


# ── _grounded_chat_ctx: grounding reaches the context, in the right place ──


def test_tanjong_pagar_grounding_block_reaches_llm_context():
    """The live-session failure (Toa Payoh question) must surface the
    Tanjong Pagar correction in the grounded context the brain receives."""
    agent = _agent_with_grounding()
    ctx = _production_like_ctx(
        "What was your constituency? Did you represent Toa Payoh or Ang Mo Kio?"
    )
    grounded = agent._grounded_chat_ctx(ctx)
    # The grounding block must contain the Tanjong Pagar correction.
    grounding_texts = [
        (m.text_content or "")
        for m in grounded.items
        if m.role == "system" and "Tanjong Pagar" in (m.text_content or "")
    ]
    assert grounding_texts, "Tanjong Pagar grounding block did not reach the context"
    assert "Trust these dates" in grounding_texts[0]


def test_grounding_system_message_is_immediately_before_user_turn():
    """The documented contract: the grounding block sits immediately BEFORE
    the latest user turn (brain reads facts before answering), not appended
    after it (which was the pre-fix bug)."""
    agent = _agent_with_grounding()
    ctx = _production_like_ctx("What was your constituency? Toa Payoh?")
    grounded = agent._grounded_chat_ctx(ctx)
    items = list(grounded.items)
    # Find the latest user turn index.
    user_idx = max(i for i, m in enumerate(items) if m.role == "user")
    # The item immediately before it must be the grounding system message
    # (not the original persona system message, not an exemplar).
    preceding = items[user_idx - 1]
    assert preceding.role == "system"
    assert "Trust these dates" in (preceding.text_content or "")


def test_grounding_does_not_mutate_original_context():
    """Grounding is per-turn and in-place-copy; the session's accumulated
    history is not mutated."""
    agent = _agent_with_grounding()
    ctx = _production_like_ctx("What was your constituency? Toa Payoh?")
    original_count = len(list(ctx.items))
    _ = agent._grounded_chat_ctx(ctx)
    assert len(list(ctx.items)) == original_count


def test_grounding_noop_when_no_fact_sheet():
    """No fact sheet -> unchanged context (same object, not a copy)."""
    agent = LKYAgent(instructions="test", fact_sheet_path="")
    ctx = _production_like_ctx("What was your constituency? Toa Payoh?")
    grounded = agent._grounded_chat_ctx(ctx)
    assert grounded is ctx


def test_grounding_noop_when_no_keyword_match():
    """A turn with no keyword match -> unchanged context (same object)."""
    agent = _agent_with_grounding()
    ctx = _production_like_ctx("What do you think of artificial intelligence?")
    grounded = agent._grounded_chat_ctx(ctx)
    assert grounded is ctx
