"""Unit tests for env-driven agent configuration (pure logic, no providers)."""

from config import (
    DEFAULT_LLM_MODEL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_PROMPT_VARIANT,
    DEFAULT_SIM_DATE,
    DEFAULT_STT_MODEL,
    DEFAULT_TTS_MODEL,
    AgentConfig,
    explain_unusable,
    is_placeholder,
    unusable_keys,
)

REAL_ENV = {
    "LIVEKIT_URL": "wss://demo-project.livekit.cloud",
    "LIVEKIT_API_KEY": "APIabc123",
    "LIVEKIT_API_SECRET": "secretsecretsecretsecret",
    "DEEPGRAM_API_KEY": "dgkey123",
    "OPENAI_BASE_URL": "http://127.0.0.1:8000/v1",
    "OPENAI_API_KEY": "local-development",
    "SKELETON_LLM_MODEL": "lky",
}


def test_from_env_reads_all_keys():
    cfg = AgentConfig.from_env(REAL_ENV)
    assert cfg.livekit_url == "wss://demo-project.livekit.cloud"
    assert cfg.livekit_api_key == "APIabc123"
    assert cfg.livekit_api_secret == "secretsecretsecretsecret"
    assert cfg.deepgram_api_key == "dgkey123"
    assert cfg.openai_base_url == "http://127.0.0.1:8000/v1"
    assert cfg.openai_api_key == "local-development"
    assert cfg.llm_model == "lky"


def test_defaults_applied_when_optional_keys_absent():
    env = {k: v for k, v in REAL_ENV.items() if k not in ("OPENAI_BASE_URL", "SKELETON_LLM_MODEL")}
    cfg = AgentConfig.from_env(env)
    assert cfg.openai_base_url == DEFAULT_OPENAI_BASE_URL
    assert cfg.llm_model == DEFAULT_LLM_MODEL
    assert cfg.stt_model == DEFAULT_STT_MODEL
    assert cfg.tts_model == DEFAULT_TTS_MODEL


def test_stt_and_tts_models_overridable():
    env = dict(REAL_ENV, SKELETON_STT_MODEL="nova-2", SKELETON_TTS_MODEL="aura-2-orion-en")
    cfg = AgentConfig.from_env(env)
    assert cfg.stt_model == "nova-2"
    assert cfg.tts_model == "aura-2-orion-en"


def test_persona_defaults_pending_issue_2_verdict():
    cfg = AgentConfig.from_env(REAL_ENV)
    assert cfg.lky_sim_date == DEFAULT_SIM_DATE == "2026-07-13"
    assert cfg.lky_prompt_variant == DEFAULT_PROMPT_VARIANT == "B"
    assert cfg.lky_max_tokens == DEFAULT_MAX_TOKENS == 320


def test_persona_env_overrides():
    env = dict(
        REAL_ENV,
        LKY_SIM_DATE="2011-05-01",
        LKY_PROMPT_VARIANT="A",
        LKY_MAX_TOKENS="160",
    )
    cfg = AgentConfig.from_env(env)
    assert cfg.lky_sim_date == "2011-05-01"
    assert cfg.lky_prompt_variant == "A"
    assert cfg.lky_max_tokens == 160


def test_unusable_max_tokens_falls_back_to_default():
    for bad in ("", "  ", "banana", "-5", "0"):
        cfg = AgentConfig.from_env(dict(REAL_ENV, LKY_MAX_TOKENS=bad))
        assert cfg.lky_max_tokens == DEFAULT_MAX_TOKENS


def test_is_placeholder():
    assert is_placeholder("")
    assert is_placeholder("   ")
    assert is_placeholder("PLACEHOLDER_LIVEKIT_API_KEY")
    assert is_placeholder("wss://PLACEHOLDER.livekit.cloud")
    assert not is_placeholder("APIabc123")


def test_valid_config_has_no_unusable_keys():
    assert unusable_keys(AgentConfig.from_env(REAL_ENV)) == []


def test_placeholder_and_missing_keys_are_reported_by_env_name():
    env = dict(REAL_ENV)
    env["DEEPGRAM_API_KEY"] = "PLACEHOLDER_DEEPGRAM_API_KEY"
    del env["LIVEKIT_API_SECRET"]
    missing = unusable_keys(AgentConfig.from_env(env))
    assert set(missing) == {"DEEPGRAM_API_KEY", "LIVEKIT_API_SECRET"}


def test_empty_env_reports_every_required_key_except_defaulted_base_url():
    missing = unusable_keys(AgentConfig.from_env({}))
    # OPENAI_BASE_URL and SKELETON_LLM_MODEL have real defaults; the rest
    # of the required keys must be flagged.
    assert set(missing) == {
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "DEEPGRAM_API_KEY",
        "OPENAI_API_KEY",
    }


def test_explain_unusable_names_keys_and_points_at_env_example():
    msg = explain_unusable(["LIVEKIT_URL", "DEEPGRAM_API_KEY"])
    assert "LIVEKIT_URL" in msg
    assert "DEEPGRAM_API_KEY" in msg
    assert ".env.example" in msg
    assert "Traceback" not in msg
