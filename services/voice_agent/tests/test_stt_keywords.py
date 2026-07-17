"""Deepgram STT keyword boost for SG proper nouns (issue #45): pure
logic — defaults, merge/override, and the (term, boost) tuple shape
Deepgram expects. No SDK, no network."""

from __future__ import annotations

import json

import pytest

from stt_keywords import (
    DEFAULT_BOOST,
    DEFAULT_KEYWORDS,
    build_keywords,
    load_overrides,
    merge_overrides,
)


class TestDefaults:
    def test_issue_terms_have_coverage(self):
        """The issue's named SG proper nouns are all in the default list."""
        keys = set(DEFAULT_KEYWORDS)
        for term in (
            "Toa Payoh",
            "Ang Mo Kio",
            "Temasek",
            "Kallang",
            "NEWater",
            "Sembawang",
            "Tanjong Pagar",
        ):
            assert term in keys, f"missing STT keyword: {term}"

    def test_default_boost_is_in_deepgram_range(self):
        assert 0 < DEFAULT_BOOST <= 1.0

    def test_build_keywords_returns_tuples(self):
        kws = build_keywords()
        assert all(isinstance(t, tuple) and len(t) == 2 for t in kws)
        assert all(isinstance(term, str) for term, _ in kws)
        assert all(isinstance(boost, (int, float)) for _, boost in kws)

    def test_build_keywords_defaults_without_file(self):
        kws = build_keywords(None)
        terms = {t for t, _ in kws}
        assert "Toa Payoh" in terms
        assert "Lee Kuan Yew" in terms


class TestMatchingRules:
    def test_load_and_merge(self, tmp_path):
        p = tmp_path / "extra.json"
        p.write_text(
            json.dumps({"Whampoa": 0.5, "PAP": None}), encoding="utf-8"
        )
        extra = load_overrides(p)
        merged = merge_overrides(DEFAULT_KEYWORDS, extra)
        assert merged["Whampoa"] == 0.5
        assert "PAP" not in merged  # null removes a default

    def test_build_with_file(self, tmp_path):
        p = tmp_path / "extra.json"
        p.write_text(json.dumps({"Whampoa": 0.5}), encoding="utf-8")
        kws = build_keywords(p)
        d = dict(kws)
        assert d["Whampoa"] == 0.5
        assert "Toa Payoh" in d  # defaults preserved

    def test_build_without_file_uses_defaults(self):
        kws = build_keywords(None)
        assert dict(kws) == dict(DEFAULT_KEYWORDS)

    def test_malformed_json_raises_with_path(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="bad.json"):
            load_overrides(p)

    def test_non_object_json_rejected(self, tmp_path):
        p = tmp_path / "list.json"
        p.write_text('["Toa Payoh"]', encoding="utf-8")
        with pytest.raises(ValueError, match="JSON object"):
            load_overrides(p)

    def test_missing_file_raises_oserror(self, tmp_path):
        with pytest.raises(OSError):
            load_overrides(tmp_path / "absent.json")
