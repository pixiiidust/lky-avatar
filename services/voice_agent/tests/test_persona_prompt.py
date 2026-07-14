"""Prompt construction (issue #6): variant/date matrix, byte-parity with the
vendored persona module, and the spoken-style policy. Pure logic — no
LiveKit imports, no credentials."""

import pytest

from lky_avatar import persona
from persona_prompt import (
    DEFAULT_SIM_DATE,
    DEFAULT_VARIANT,
    PRESENT_DAY_AWARENESS,
    SPOKEN_STYLE_POLICY,
    build_instructions,
    normalize_variant,
    persona_system_prompt,
)

# Dates spanning every role_for() era boundary plus the sim date.
DATE_MATRIX = [
    "1985-01-01",  # Prime Minister
    "1990-11-27",  # last PM day
    "1995-06-01",  # Senior Minister
    "2005-01-15",  # Minister Mentor
    "2011-05-18",  # former PM (boundary)
    "2026-07-13",  # the simulated present day
]


@pytest.mark.parametrize("date", DATE_MATRIX)
def test_variant_a_is_vendored_prompt_bytewise(date):
    assert persona_system_prompt(date, "A") == persona.system_prompt(date)


@pytest.mark.parametrize("date", DATE_MATRIX)
def test_variant_b_is_a_plus_exact_awareness_sentence(date):
    a = persona_system_prompt(date, "A")
    b = persona_system_prompt(date, "B")
    assert b == a + PRESENT_DAY_AWARENESS
    assert b.startswith(persona.system_prompt(date))  # base never reworded


def test_defaults_are_sim_date_and_variant_b():
    assert DEFAULT_SIM_DATE == "2026-07-13"
    assert DEFAULT_VARIANT == "B"
    assert persona_system_prompt() == persona_system_prompt("2026-07-13", "B")


def test_sim_date_yields_present_day_framing():
    prompt = persona_system_prompt("2026-07-13", "B")
    assert "It is July 2026." in prompt
    assert "former Prime Minister of Singapore" in prompt


def test_anti_fabrication_rule_present_in_variant_b_only():
    assert "do not fabricate" in persona_system_prompt("2026-07-13", "B")
    assert "do not fabricate" not in persona_system_prompt("2026-07-13", "A")


def test_variant_is_case_insensitive_and_trimmed():
    assert normalize_variant(" b ") == "B"
    assert persona_system_prompt("2026-07-13", "a") == persona_system_prompt(
        "2026-07-13", "A"
    )


@pytest.mark.parametrize("bad", ["", "C", "AB", "variant-b"])
def test_unknown_variant_raises_naming_the_env_var(bad):
    with pytest.raises(ValueError, match="LKY_PROMPT_VARIANT"):
        persona_system_prompt("2026-07-13", bad)


@pytest.mark.parametrize("bad", ["", "2026", "13-07-2026", "2026-13-01", "July 2026"])
def test_bad_date_raises_naming_the_env_var(bad):
    with pytest.raises(ValueError, match="LKY_SIM_DATE"):
        persona_system_prompt(bad, "B")


def test_build_instructions_layers_style_after_persona():
    instructions = build_instructions("2026-07-13", "B")
    persona_part, _, style_part = instructions.partition("\n\n")
    assert persona_part == persona_system_prompt("2026-07-13", "B")
    assert style_part == SPOKEN_STYLE_POLICY


def test_spoken_style_demands_two_to_five_sentences():
    assert "two to five sentences" in SPOKEN_STYLE_POLICY
    assert "No markdown" in SPOKEN_STYLE_POLICY
