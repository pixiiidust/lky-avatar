"""Parity check: vendored persona vs lky-brain's train/chat.py.

Loads ``role_for``/``system_prompt`` from BOTH the vendored module
(``lky_avatar/persona.py``) and the lky-brain checkout (via importlib from
the file path — lky-brain is never imported as an installed package and never
modified), then compares outputs byte-for-byte across dates covering every
branch of ``role_for``.

Usage (Windows Python, no GPU deps needed):
    python scripts/check_persona_parity.py

Env:
    LKY_BRAIN_PATH  path to the lky-brain checkout
                    (default: C:\\Users\\Jamie\\lky-brain)

Exits nonzero on any mismatch and prints a date -> role -> match table.
"""
import importlib.util
import os
import pathlib
import sys
import types

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_LKY_BRAIN = r"C:\Users\Jamie\lky-brain"

# Dates chosen from role_for's branch boundaries (see lky-brain train/chat.py):
#   < 1990-11-28  -> Prime Minister of Singapore
#   < 2004-08-12  -> Senior Minister of Singapore
#   < 2011-05-18  -> Minister Mentor of Singapore
#   otherwise     -> former Prime Minister of Singapore
# Each side of each boundary is tested, plus era-interior and present dates.
TEST_DATES = [
    "1959-06-05",  # deep in PM era
    "1965-08-09",  # independence; lky-brain's default date
    "1990-11-27",  # last day of PM branch
    "1990-11-28",  # first day of Senior Minister branch
    "1997-01-15",  # SM era interior
    "2004-08-11",  # last day of Senior Minister branch
    "2004-08-12",  # first day of Minister Mentor branch
    "2008-12-31",  # MM era interior
    "2011-05-17",  # last day of Minister Mentor branch
    "2011-05-18",  # first day of former-PM branch
    "2015-03-23",  # former-PM era
    "2026-07-13",  # present day (time-traveler framing target)
]


def load_lky_brain_chat(brain_path: pathlib.Path):
    """Load lky-brain's train/chat.py as a module from its file path.

    chat.py imports torch/peft/transformers at module top; those are GPU
    deps we neither have nor need for prompt parity. Stub them in
    sys.modules just for the exec (role_for/system_prompt don't touch them).
    """
    chat_py = brain_path / "train" / "chat.py"
    if not chat_py.is_file():
        sys.exit(f"ERROR: {chat_py} not found. Set LKY_BRAIN_PATH to the "
                 f"lky-brain checkout.")

    stubs = {}
    torch_stub = types.ModuleType("torch")
    torch_stub.bfloat16 = object()
    torch_stub.no_grad = lambda: None
    stubs["torch"] = torch_stub
    peft_stub = types.ModuleType("peft")
    peft_stub.PeftModel = object
    stubs["peft"] = peft_stub
    tf_stub = types.ModuleType("transformers")
    for name in ("AutoModelForCausalLM", "AutoTokenizer",
                 "BitsAndBytesConfig", "TextStreamer"):
        setattr(tf_stub, name, object)
    stubs["transformers"] = tf_stub

    saved = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location("lky_brain_chat",
                                                      chat_py)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name, prev in saved.items():
            if prev is None:
                del sys.modules[name]
            else:
                sys.modules[name] = prev
    return module


def main() -> int:
    sys.path.insert(0, str(REPO_ROOT))
    from lky_avatar import persona

    brain_path = pathlib.Path(os.environ.get("LKY_BRAIN_PATH",
                                             DEFAULT_LKY_BRAIN))
    upstream = load_lky_brain_chat(brain_path)
    print(f"lky-brain: {brain_path / 'train' / 'chat.py'}")
    print(f"vendored:  {persona.__file__}\n")

    header = f"{'date':<12} {'role (upstream)':<38} {'role':>5} {'prompt':>7}"
    print(header)
    print("-" * len(header))

    failures = 0
    for date in TEST_DATES:
        up_role, v_role = upstream.role_for(date), persona.role_for(date)
        up_sp, v_sp = upstream.system_prompt(date), persona.system_prompt(date)
        role_ok, prompt_ok = up_role == v_role, up_sp == v_sp
        print(f"{date:<12} {up_role:<38} "
              f"{'OK' if role_ok else 'FAIL':>5} "
              f"{'OK' if prompt_ok else 'FAIL':>7}")
        if not role_ok:
            failures += 1
            print(f"  role mismatch: upstream={up_role!r} vendored={v_role!r}")
        if not prompt_ok:
            failures += 1
            print(f"  prompt mismatch:\n    upstream={up_sp!r}\n"
                  f"    vendored={v_sp!r}")

    print()
    if failures:
        print(f"PARITY FAILED: {failures} mismatch(es).")
        return 1
    print(f"PARITY OK: {len(TEST_DATES)} dates, all roles and system "
          f"prompts byte-identical.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
