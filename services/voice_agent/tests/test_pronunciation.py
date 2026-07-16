"""Pronunciation preprocessing (issue #8): the text rewrites applied before
cloned-voice synthesis. Pure logic — no audio, no SDK."""

from __future__ import annotations

import json

import pytest

from pronunciation import (
    DEFAULT_PRONUNCIATIONS,
    PronunciationMap,
    build_pronunciation_map,
    load_overrides,
    merge_overrides,
)


@pytest.fixture()
def default_map() -> PronunciationMap:
    return PronunciationMap()


class TestDefaults:
    def test_issue_terms_have_coverage(self):
        """The issue's named term families are represented in the defaults."""
        keys = " ".join(DEFAULT_PRONUNCIATIONS)
        for term in ("PAP", "HDB", "ASEAN", "Hokkien", "Lee Kuan Yew"):
            assert term in keys

    def test_issue45_sg_proper_nouns_have_coverage(self):
        """Issue #45: the SG proper nouns the live session garbled must be
        in the TTS pronunciation map (matching the STT keyword list)."""
        keys = set(DEFAULT_PRONUNCIATIONS)
        for term in (
            "Toa Payoh",
            "Ang Mo Kio",
            "Kallang",
            "Sembawang",
            "NEWater",
        ):
            assert term in keys, f"missing pronunciation: {term}"

    def test_acronyms_spelled_out(self, default_map):
        assert default_map.apply("The PAP built HDB flats.") == (
            "The P. A. P. built H. D. B. flats."
        )

    def test_full_name(self, default_map):
        assert (
            default_map.apply("Lee Kuan Yew said so.") == "Lee Kwan Yoo said so."
        )

    def test_hokkien_and_malay_terms(self, default_map):
        out = default_map.apply("They spoke Hokkien in the kampung.")
        assert out == "They spoke Hock-kee-en in the kahm-pong."

    def test_terms_that_read_correctly_are_untouched(self, default_map):
        text = "Singapore chose Malay and Mandarin under bilingualism."
        assert default_map.apply(text) == text


class TestMatchingRules:
    def test_word_boundaries(self, default_map):
        # "PAP" inside a longer word must not rewrite.
        assert default_map.apply("PAPERWORK") == "PAPERWORK"
        assert default_map.apply("The PAP.") == "The P. A. P.."

    def test_acronyms_are_case_sensitive(self, default_map):
        # lowercase "pap" is prose, not the party.
        assert default_map.apply("a pap smear") == "a pap smear"

    def test_non_acronyms_match_case_insensitively(self, default_map):
        assert default_map.apply("the HOKKIEN dialect") == "the Hock-kee-en dialect"

    def test_longest_key_wins(self):
        m = PronunciationMap({"Lee Kuan Yew": "FULL", "Lee": "SHORT"})
        assert m.apply("Lee Kuan Yew and Lee.") == "FULL and SHORT."

    def test_punctuation_and_spacing_preserved(self, default_map):
        assert (
            default_map.apply('He said: "ASEAN, obviously!"')
            == 'He said: "AH-see-ahn, obviously!"'
        )

    def test_empty_map_is_identity(self):
        m = PronunciationMap({})
        assert m.apply("The PAP built HDB flats.") == "The PAP built HDB flats."


class TestEnvExtension:
    def test_load_and_merge(self, tmp_path):
        p = tmp_path / "extra.json"
        p.write_text(
            json.dumps({"Shenzhen": "Shen-jen", "PAP": None}), encoding="utf-8"
        )
        extra = load_overrides(p)
        merged = merge_overrides(DEFAULT_PRONUNCIATIONS, extra)
        assert merged["Shenzhen"] == "Shen-jen"
        assert "PAP" not in merged  # null removes a default

    def test_build_with_file(self, tmp_path):
        p = tmp_path / "extra.json"
        p.write_text(json.dumps({"Whampoa": "Wam-po-ah"}), encoding="utf-8")
        m = build_pronunciation_map(p)
        assert m.apply("Whampoa and the PAP") == "Wam-po-ah and the P. A. P."

    def test_build_without_file_uses_defaults(self):
        m = build_pronunciation_map(None)
        assert m.apply("HDB") == "H. D. B."

    def test_malformed_json_raises_with_path(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="bad.json"):
            load_overrides(p)

    def test_non_object_json_rejected(self, tmp_path):
        p = tmp_path / "list.json"
        p.write_text('["PAP"]', encoding="utf-8")
        with pytest.raises(ValueError, match="JSON object"):
            load_overrides(p)

    def test_missing_file_raises_oserror(self, tmp_path):
        with pytest.raises(OSError):
            load_overrides(tmp_path / "absent.json")
