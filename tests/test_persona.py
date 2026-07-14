"""Tests for the vendored persona module (pure logic, Windows Python).

These pin the vendored behavior itself; byte-parity against lky-brain is
covered separately by scripts/check_persona_parity.py.
"""
import pytest

from lky_avatar import persona

PM = "Prime Minister of Singapore"
SM = "Senior Minister of Singapore"
MM = "Minister Mentor of Singapore"
FORMER = "former Prime Minister of Singapore"


@pytest.mark.parametrize("date,role", [
    ("1959-06-05", PM),
    ("1965-08-09", PM),
    ("1990-11-27", PM),        # last day before SM boundary
    ("1990-11-28", SM),        # SM boundary
    ("2004-08-11", SM),        # last day before MM boundary
    ("2004-08-12", MM),        # MM boundary
    ("2011-05-17", MM),        # last day before former-PM boundary
    ("2011-05-18", FORMER),    # former-PM boundary
    ("2026-07-13", FORMER),    # present day
])
def test_role_boundaries(date, role):
    assert persona.role_for(date) == role


@pytest.mark.parametrize("date,role,month_year", [
    ("1965-08-09", PM, "August 1965"),
    ("1990-11-28", SM, "November 1990"),
    ("2004-08-12", MM, "August 2004"),
    ("2011-05-18", FORMER, "May 2011"),
    ("2026-01-01", FORMER, "January 2026"),
    ("2026-12-31", FORMER, "December 2026"),
])
def test_system_prompt_contains_role_and_date(date, role, month_year):
    prompt = persona.system_prompt(date)
    assert prompt == (f"You are Lee Kuan Yew, {role}, speaking candidly"
                      f" in an interview. It is {month_year}.")


def test_sampling_defaults_locked():
    assert persona.sampling_defaults() == {
        "enable_thinking": False,
        "temperature": 0.7,
        "top_p": 0.9,
        "repetition_penalty": 1.1,
    }


def test_adapter_identifiers():
    assert persona.ADAPTER_HF_ID == "sjsim/lky-qlora"
    assert persona.ADAPTER_LOCAL_PATH_WSL.endswith("keep-epoch2-step1050")
    assert persona.ADAPTER_LOCAL_PATH_WINDOWS.endswith("keep-epoch2-step1050")


def test_time_traveler_note_defers_to_issue_2():
    # The 2026 framing must not be baked in before issue #2's verdict.
    assert "issue #2" in persona.TIME_TRAVELER_NOTE
    assert "2026" not in persona.system_prompt("2011-05-18")
