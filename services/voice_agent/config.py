"""Environment-driven configuration for the walking-skeleton voice agent.

Pure logic — no LiveKit imports — so it is unit-testable on any machine
without SDK installs or credentials.

Every credential is read from env vars. Values that are missing, empty, or
still carry the ``PLACEHOLDER`` marker from ``.env.example`` are reported by
:func:`unusable_keys` so the agent can refuse to start with a clear message
instead of a provider stack trace.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

PLACEHOLDER_MARKER = "PLACEHOLDER"

DEFAULT_STT_MODEL = "nova-3"
DEFAULT_TTS_MODEL = "aura-2-andromeda-en"
DEFAULT_LLM_MODEL = "gpt-4o-mini"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"

# Persona framing (issue #6; variant verdict pending from issue #2).
DEFAULT_SIM_DATE = "2026-07-13"
DEFAULT_PROMPT_VARIANT = "B"
# Spoken-answer token budget — matches the brain server's own default
# (services/brain_api DEFAULT_MAX_TOKENS): ~2-5 spoken sentences.
DEFAULT_MAX_TOKENS = 320

# TTS provider selection (issue #8). "deepgram" is the stock fallback and
# the default; "chatterbox" is the cloned voice behind the loopback
# tts_server (services/tts_server/run_real.md).
TTS_PROVIDERS = ("deepgram", "chatterbox")
DEFAULT_TTS_PROVIDER = "deepgram"
DEFAULT_TTS_BASE_URL = "http://127.0.0.1:8100"
# Delivery-speed factor sent with every cloned-voice request; <1
# time-stretches toward the real elder LKY's pace. Measured 2026-07-14
# against the 1990 reference set now in use: engine 2.70 words/s at
# speed 1.0 vs 2.18 words/s in the refs -> 1.24x too fast, exact-match
# speed 0.81. Default 0.85 sits slightly above exact-match because the
# refs' inter-sentence pauses inflate their apparent slowness; tune live
# with LKY_TTS_SPEED. (The report's ~1.74x figure was vs the 2005 refs.)
DEFAULT_TTS_SPEED = 0.85


@dataclass(frozen=True)
class AgentConfig:
    """Everything the skeleton agent needs, resolved from env vars."""

    # LiveKit room transport
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    # STT + stock TTS (both served by Deepgram on one key)
    deepgram_api_key: str
    # LLM — any OpenAI-compatible endpoint. This is deliberately the same
    # client configuration that issue #6 repoints at the LKY brain API.
    openai_base_url: str
    openai_api_key: str
    llm_model: str
    # Overridable model choices
    stt_model: str
    tts_model: str
    # Persona framing (issue #6): simulated present day + prompt variant
    # (A = vendored persona prompt alone; B = A + present-day-awareness /
    # anti-fabrication sentence — issue #2 decides which ships).
    lky_sim_date: str
    lky_prompt_variant: str
    # Max tokens per answer, passed to the LLM plugin (spoken-style budget).
    lky_max_tokens: int
    # TTS provider (issue #8): "deepgram" (stock, default) | "chatterbox"
    # (cloned voice via the loopback tts_server). Unknown values fall back
    # to deepgram — never a crashed session over a typo.
    tts_provider: str
    # Cloned-voice server root (loopback only) + delivery-speed factor +
    # optional JSON file of extra pronunciation overrides.
    tts_base_url: str
    tts_speed: float
    tts_pronunciations_path: str
    # Barge-in tuning (live-session feedback 2026-07-14: interruptions
    # "sometimes worked, sometimes didn't; several tries"). The SDK default
    # requires 0.5s of continuous speech before interrupting — short
    # interjections ("wait", "no") often miss it. 0.3s is snappier; false
    # triggers are recovered by resume_false_interruption.
    interrupt_min_duration: float
    false_interrupt_timeout: float
    resume_false_interruption: bool
    # "vad" = plain voice-activity interruption (any sustained speech stops
    # the agent). "adaptive" = the SDK's ML classifier, which live-tested as
    # eating short interjections ("stop stop") as backchannels — see agent.py.
    interrupt_mode: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "AgentConfig":
        return cls(
            livekit_url=env.get("LIVEKIT_URL", ""),
            livekit_api_key=env.get("LIVEKIT_API_KEY", ""),
            livekit_api_secret=env.get("LIVEKIT_API_SECRET", ""),
            deepgram_api_key=env.get("DEEPGRAM_API_KEY", ""),
            openai_base_url=env.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
            openai_api_key=env.get("OPENAI_API_KEY", ""),
            llm_model=env.get("SKELETON_LLM_MODEL", DEFAULT_LLM_MODEL),
            stt_model=env.get("SKELETON_STT_MODEL", DEFAULT_STT_MODEL),
            tts_model=env.get("SKELETON_TTS_MODEL", DEFAULT_TTS_MODEL),
            lky_sim_date=env.get("LKY_SIM_DATE", "").strip() or DEFAULT_SIM_DATE,
            lky_prompt_variant=(
                env.get("LKY_PROMPT_VARIANT", "").strip() or DEFAULT_PROMPT_VARIANT
            ),
            lky_max_tokens=_get_int(env, "LKY_MAX_TOKENS", DEFAULT_MAX_TOKENS),
            tts_provider=select_tts_provider(env.get("TTS_PROVIDER", "")),
            tts_base_url=(
                env.get("LKY_TTS_URL", "").strip() or DEFAULT_TTS_BASE_URL
            ),
            tts_speed=_get_float(env, "LKY_TTS_SPEED", DEFAULT_TTS_SPEED),
            tts_pronunciations_path=env.get(
                "LKY_TTS_PRONUNCIATIONS", ""
            ).strip(),
            interrupt_min_duration=_get_float(
                env, "LKY_INTERRUPT_MIN_SEC", 0.3
            ),
            false_interrupt_timeout=_get_float(
                env, "LKY_FALSE_INTERRUPT_TIMEOUT_SEC", 2.0
            ),
            resume_false_interruption=(
                env.get("LKY_RESUME_FALSE_INTERRUPT", "true").strip().lower()
                != "false"
            ),
            interrupt_mode=(
                "adaptive"
                if env.get("LKY_INTERRUPT_MODE", "").strip().lower()
                == "adaptive"
                else "vad"
            ),
        )


def select_tts_provider(raw: str) -> str:
    """Normalize TTS_PROVIDER; anything but "chatterbox" means deepgram.

    Deepgram-by-default is deliberate: the stock voice is the fallback that
    works with no local GPU server running, so a missing/typo'd value must
    never leave a session with a dead TTS.
    """
    value = raw.strip().lower()
    return value if value in TTS_PROVIDERS else DEFAULT_TTS_PROVIDER


def _get_int(env: Mapping[str, str], key: str, default: int) -> int:
    """Positive int from env; anything unusable falls back to the default."""
    raw = env.get(key, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        return default
    return value if value > 0 else default


def _get_float(env: Mapping[str, str], key: str, default: float) -> float:
    """Positive float from env; anything unusable falls back to the default."""
    raw = env.get(key, "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        return default
    return value if value > 0 else default


def is_placeholder(value: str) -> bool:
    """True if a config value is unusable: missing, blank, or a placeholder."""
    return not value.strip() or PLACEHOLDER_MARKER in value


#: env-var name -> attribute on AgentConfig, for the keys that MUST be real.
REQUIRED_KEYS: dict[str, str] = {
    "LIVEKIT_URL": "livekit_url",
    "LIVEKIT_API_KEY": "livekit_api_key",
    "LIVEKIT_API_SECRET": "livekit_api_secret",
    "DEEPGRAM_API_KEY": "deepgram_api_key",
    "OPENAI_BASE_URL": "openai_base_url",
    "OPENAI_API_KEY": "openai_api_key",
    "SKELETON_LLM_MODEL": "llm_model",
}


def unusable_keys(config: AgentConfig) -> list[str]:
    """Names of required env vars whose values are missing or placeholders."""
    return [
        env_name
        for env_name, attr in REQUIRED_KEYS.items()
        if is_placeholder(getattr(config, attr))
    ]


def explain_unusable(missing: list[str]) -> str:
    """A human-readable refusal message (no stack trace) for missing keys."""
    lines = [
        "Cannot start the voice agent: the following credentials are missing",
        "or still set to PLACEHOLDER values:",
        "",
    ]
    lines += [f"  - {name}" for name in missing]
    lines += [
        "",
        "Fix: copy .env.example to .env at the repo root and fill in real",
        "values. Each key's comment says exactly where to obtain it",
        "(LiveKit Cloud project settings, Deepgram console, any",
        "OpenAI-compatible LLM provider).",
    ]
    return "\n".join(lines)
