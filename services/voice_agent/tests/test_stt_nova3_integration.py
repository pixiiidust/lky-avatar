"""Deepgram STT construction against the REAL pinned plugin (issue #45).

The repo pins livekit-plugins-deepgram 1.6.5; its default model is Nova-3,
which REJECTS the ``(term, boost)`` ``keywords`` parameter with
``ValueError: ... For Nova-3, use Keyterm Prompting.`` This file proves the
model-aware adapter wires the correct parameter at construction time —
constructor-level, against the real plugin, with a placeholder API key.
Pure tuple-shape tests are insufficient (the bug is a constructor raise).

Requires the voice_agent venv; skips with instructions if the SDK is not
importable. No network — ``deepgram.STT(...)`` only validates arguments;
it does not open a connection until a stream starts.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("livekit.plugins.deepgram")  # skip cleanly if venv missing

from livekit.plugins import deepgram  # noqa: E402

from stt_keywords import (  # noqa: E402
    DEFAULT_KEYWORDS,
    build_keyterms,
    build_stt_boost_args,
)


PLACEHOLDER_KEY = "PLACEHOLDER_FOR_TEST"


def _make_stt(model: str, keywords_path=None) -> deepgram.STT:
    """Construct a Deepgram STT with the adapter's boost args. Placeholder
    key is sufficient — the constructor only checks the key is non-empty;
    it does not call the API."""
    kwargs = build_stt_boost_args(model, keywords_path)
    return deepgram.STT(model=model, api_key=PLACEHOLDER_KEY, **kwargs)


# ── the bug: Nova-3 + keywords raises ───────────────────────────────────────


def test_nova_3_with_keywords_raises_value_error():
    """The pre-fix production path: default model nova-3 + the (term, boost)
    keywords list raises ValueError at construction time."""
    from stt_keywords import build_keywords

    with pytest.raises(ValueError, match="Nova-3"):
        deepgram.STT(
            model="nova-3",
            api_key=PLACEHOLDER_KEY,
            keywords=build_keywords(None),
        )


# ── the fix: adapter routes Nova-3 to keyterm ──────────────────────────────


def test_adapter_returns_keyterm_for_nova_3():
    args = build_stt_boost_args("nova-3", None)
    assert "keyterm" in args
    assert "keywords" not in args
    assert isinstance(args["keyterm"], list)
    assert all(isinstance(t, str) for t in args["keyterm"])
    # The SG proper-noun set is present.
    assert "Tanjong Pagar" in args["keyterm"]
    assert "Toa Payoh" in args["keyterm"]


def test_adapter_returns_keywords_for_other_models():
    args = build_stt_boost_args("nova-2", None)
    assert "keywords" in args
    assert "keyterm" not in args
    assert all(isinstance(t, tuple) and len(t) == 2 for t in args["keywords"])


def test_nova_3_constructor_succeeds_with_adapter():
    """The production default-model path must construct without raising."""
    stt = _make_stt("nova-3")
    # The plugin stores the effective keyterm list on _opts.keyterm.
    assert stt._opts.keyterm, "keyterm list is empty"
    assert "Tanjong Pagar" in stt._opts.keyterm
    assert "Toa Payoh" in stt._opts.keyterm


def test_nova_2_constructor_succeeds_with_adapter():
    """A non-Nova-3 model keeps the (term, boost) keywords shape."""
    stt = _make_stt("nova-2")
    assert stt._opts.keywords, "keywords list is empty"
    assert any(term == "Tanjong Pagar" for term, _ in stt._opts.keywords)


def test_build_keyterms_respects_overrides(tmp_path):
    """Overrides flow through build_keyterms the same way they flow through
    build_keywords (null removes a default)."""
    import json

    p = tmp_path / "extra.json"
    p.write_text(json.dumps({"Whampoa": 0.5, "PAP": None}), encoding="utf-8")
    terms = build_keyterms(p)
    assert "Whampoa" in terms
    assert "PAP" not in terms
    # defaults preserved
    assert "Tanjong Pagar" in terms


def test_default_terms_cover_issue_examples():
    terms = set(build_keyterms(None))
    for term in (
        "Tanjong Pagar",
        "Toa Payoh",
        "Ang Mo Kio",
        "Kallang",
        "Sembawang",
        "Temasek",
        "NEWater",
        "HDB",
        "PAP",
        "CPF",
        "Lee Kuan Yew",
        "Lee Hsien Loong",
        "Goh Chok Tong",
        "Kwa Geok Choo",
    ):
        assert term in terms, f"missing keyterm: {term}"
