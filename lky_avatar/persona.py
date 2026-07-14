"""Vendored persona/prompting logic from lky-brain.

``role_for()`` and ``system_prompt()`` are vendored verbatim from
``lky-brain/train/chat.py`` (which itself reproduces the training format from
``lky/build_dataset.py``). Do NOT edit their logic or output strings — parity
with lky-brain is verified by ``scripts/check_persona_parity.py`` and must
hold byte-for-byte so the two repos can evolve independently without the
persona drifting.

Also captured here: the locked sampling defaults and the epoch-2 adapter
identifiers (the only two coupling points between lky-avatar and lky-brain).
"""

TIME_TRAVELER_NOTE = (
    "Time-traveler framing: v1 extends this system prompt with a present-day "
    "date and an anti-fabrication rule (reason from principles; do not invent "
    "specific quotes, meetings, or memories). The exact present-day prompt is "
    "NOT defined here yet — it is layered on top of system_prompt() only after "
    "issue #2's out-of-distribution test delivers its verdict (fallback: fixed "
    "~2011 date). Until then this module reproduces lky-brain behavior only."
)

# Epoch-2 adapter — the weights coupling point (plan §2).
ADAPTER_HF_ID = "sjsim/lky-qlora"
ADAPTER_LOCAL_PATH_WINDOWS = (
    r"C:\Users\Jamie\lky-brain\train\out-lky-qlora\keep-epoch2-step1050"
)
ADAPTER_LOCAL_PATH_WSL = (
    "/mnt/c/Users/Jamie/lky-brain/train/out-lky-qlora/keep-epoch2-step1050"
)

# Locked sampling settings (plan §2, spec "Brain serving"). Do not change
# without a new evaluation.
ENABLE_THINKING = False
TEMPERATURE = 0.7
TOP_P = 0.9
REPETITION_PENALTY = 1.1

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def role_for(date: str) -> str:
    if date < "1990-11-28":
        return "Prime Minister of Singapore"
    if date < "2004-08-12":
        return "Senior Minister of Singapore"
    if date < "2011-05-18":
        return "Minister Mentor of Singapore"
    return "former Prime Minister of Singapore"


def system_prompt(date: str) -> str:
    month_year = f"{MONTHS[int(date[5:7]) - 1]} {date[:4]}"
    return (f"You are Lee Kuan Yew, {role_for(date)}, speaking candidly"
            f" in an interview. It is {month_year}.")


def sampling_defaults() -> dict:
    """The locked sampling settings as generation kwargs.

    ``enable_thinking`` belongs to the chat template
    (``tokenizer.apply_chat_template(..., enable_thinking=False)``), not to
    ``model.generate()``; it is included here so callers have one source of
    truth for every locked knob.
    """
    return {
        "enable_thinking": ENABLE_THINKING,
        "temperature": TEMPERATURE,
        "top_p": TOP_P,
        "repetition_penalty": REPETITION_PENALTY,
    }
