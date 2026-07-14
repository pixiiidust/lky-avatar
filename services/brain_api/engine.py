"""Generation engines behind the brain API.

The Engine protocol is the internal seam that makes the HTTP contract
testable without a GPU (spec Testing Decisions, Seam 1):

- :class:`FakeEngine` — deterministic, configurable token stream with a
  configurable per-piece delay. Used by ALL tests. Exposes its lifecycle
  state (started / active / cancelled / finished) so tests can verify from
  the HTTP seam that a client disconnect really stopped generation.
- :class:`TransformersEngine` — Qwen3-14B, 4-bit NF4, epoch-2 PEFT adapter
  (plain Transformers + PEFT, no Unsloth at inference — plan §2). Loads
  ONCE; iterator-based streaming via ``TextIteratorStreamer``; cancellation
  via a ``StoppingCriteria`` flag that aborts ``generate()`` between decode
  steps and frees CUDA cache afterwards. CUDA-only — run under WSL.

Measured reality on the RTX 5070 Ti (probe, 2026-07-13): NF4 decode runs at
roughly 2-3 tok/s on this torch 2.12 / bitsandbytes stack, with ~10.5 GiB
allocated — the slowness is inherent to quantized decode here, not a config
bug. Streaming-first design and per-request TTFT/tok-per-s logging exist so
downstream issues can measure, not guess. Faster serving (merged-LoRA GGUF
via llama.cpp, vLLM) is a known follow-up, deliberately out of scope for
issue #5.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from config import (
    ENGINE_FAKE,
    ENGINE_TRANSFORMERS,
    BrainConfig,
)
from lky_avatar import persona

logger = logging.getLogger("brain_api.engine")

FINISH_STOP = "stop"
FINISH_LENGTH = "length"
FINISH_CANCELLED = "cancelled"


@dataclass(frozen=True)
class GenerationRequest:
    """One generation, with every sampling knob resolved (locked defaults
    already applied by the endpoint when the client omitted them)."""

    messages: tuple[dict, ...]
    temperature: float
    top_p: float
    repetition_penalty: float
    max_tokens: int


class Engine(Protocol):
    """What the HTTP layer needs from a generation engine."""

    name: str
    #: Finish reason of the most recent stream (stop | length | cancelled).
    last_finish_reason: str | None

    @property
    def loaded(self) -> bool: ...

    def load(self) -> None:
        """Load weights (idempotent). Called once at server startup."""

    def stream(self, request: GenerationRequest) -> Iterator[str]:
        """Yield text pieces as they are generated. Blocking iterator —
        the app pumps it from a worker thread."""

    def cancel(self) -> None:
        """Abort the in-flight generation (client disconnected). Must
        unblock :meth:`stream` promptly and free GPU resources."""

    def vram_allocated_gib(self) -> float | None:
        """Currently allocated CUDA memory in GiB, or None off-GPU."""


def create_engine(config: BrainConfig) -> "FakeEngine | TransformersEngine":
    if config.engine == ENGINE_FAKE:
        return FakeEngine(
            text=config.fake_text, delay_s=config.fake_delay_ms / 1000.0
        )
    if config.engine == ENGINE_TRANSFORMERS:
        return TransformersEngine(config)
    raise ValueError(
        f"Unknown BRAIN_ENGINE {config.engine!r}: expected "
        f"{ENGINE_FAKE!r} or {ENGINE_TRANSFORMERS!r}"
    )


class FakeEngine:
    """Deterministic engine for tests: streams a fixed text word by word.

    ``delay_s`` between pieces makes streaming observable as *incremental*
    at the HTTP seam, and gives cancellation/busy tests a window to act in.
    Cancellation unblocks immediately (the delay is an Event.wait, not a
    sleep). All lifecycle state is public for test assertions.
    """

    name = ENGINE_FAKE

    def __init__(
        self, text: str | None = None, delay_s: float = 0.005
    ) -> None:
        text = text if text is not None else "fake brain reply"
        words = text.split()
        self._pieces = [
            (" " if i else "") + word for i, word in enumerate(words)
        ]
        self.delay_s = delay_s
        self.loaded = False  # load() flips it, mirroring the real lifecycle
        # ── test-observable state ──
        self.streams_started = 0
        self.streams_finished = 0
        self.active = False
        self.cancelled = False
        self.last_request: GenerationRequest | None = None
        self.last_finish_reason: str | None = None
        self._cancel_event = threading.Event()

    @property
    def full_text(self) -> str:
        """The exact content a completed, uncancelled stream produces."""
        return "".join(self._pieces)

    def load(self) -> None:
        self.loaded = True

    def stream(self, request: GenerationRequest) -> Iterator[str]:
        self._cancel_event = threading.Event()
        cancel_event = self._cancel_event
        self.cancelled = False
        self.last_request = request
        self.last_finish_reason = None
        self.streams_started += 1
        self.active = True
        try:
            n = min(request.max_tokens, len(self._pieces))
            for piece in self._pieces[:n]:
                # Event.wait doubles as the inter-piece delay AND an
                # immediately-responsive cancellation point.
                if cancel_event.wait(self.delay_s):
                    self.cancelled = True
                    self.last_finish_reason = FINISH_CANCELLED
                    return
                yield piece
            self.last_finish_reason = (
                FINISH_LENGTH if n < len(self._pieces) else FINISH_STOP
            )
        finally:
            self.active = False
            self.streams_finished += 1

    def cancel(self) -> None:
        self._cancel_event.set()

    def vram_allocated_gib(self) -> float | None:
        return None


def _resolve_adapter(spec: str) -> str:
    """A filesystem path if it exists (e.g. the WSL epoch-2 checkout),
    otherwise treated as a HuggingFace repo id (``sjsim/lky-qlora``)."""
    if Path(spec).exists():
        return str(Path(spec))
    return spec


class TransformersEngine:
    """The real brain: Qwen3-14B NF4 + epoch-2 LoRA, loaded once.

    Heavy imports are local to load()/stream() so this module imports fine
    on machines without torch (Windows test runs use FakeEngine only).
    """

    name = ENGINE_TRANSFORMERS

    def __init__(self, config: BrainConfig) -> None:
        self._config = config
        self._model = None
        self._tokenizer = None
        self._torch = None
        self._cancel_event = threading.Event()
        self.last_finish_reason: str | None = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self.loaded:
            return
        import torch
        from peft import PeftModel
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
        )

        if not torch.cuda.is_available():
            raise RuntimeError(
                "BRAIN_ENGINE=transformers requires CUDA (run under WSL, "
                "see run_real.md). For GPU-less runs use BRAIN_ENGINE=fake."
            )

        cfg = self._config
        adapter = _resolve_adapter(cfg.adapter)
        logger.info(
            "loading base=%s adapter=%s (4-bit NF4, epoch-2)",
            cfg.base_model,
            adapter,
        )
        t0 = time.perf_counter()
        tokenizer = AutoTokenizer.from_pretrained(cfg.base_model)
        quant = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            cfg.base_model,
            quantization_config=quant,
            device_map={"": 0},
        )
        model = PeftModel.from_pretrained(model, adapter)
        model.eval()
        # Explicitly pin use_cache on for decode. (Probe 2026-07-13: the
        # adapter load already leaves it True — this documents intent and
        # guards against future checkpoints shipping a training-state
        # config, at zero cost.)
        model.config.use_cache = True
        if getattr(model, "generation_config", None) is not None:
            model.generation_config.use_cache = True

        self._torch = torch
        self._model = model
        self._tokenizer = tokenizer
        logger.info("model loaded in %.1fs", time.perf_counter() - t0)
        self._warmup()

    def _warmup(self) -> None:
        """One tiny generation to trigger CUDA/kernel init, then a soft
        VRAM sanity check (warn — don't refuse — above the threshold)."""
        request = GenerationRequest(
            messages=({"role": "user", "content": "Ready?"},),
            temperature=persona.TEMPERATURE,
            top_p=persona.TOP_P,
            repetition_penalty=persona.REPETITION_PENALTY,
            max_tokens=8,
        )
        t0 = time.perf_counter()
        pieces = list(self.stream(request))
        allocated = self.vram_allocated_gib() or 0.0
        logger.info(
            "warmup: %d pieces in %.1fs, VRAM allocated %.2f GiB",
            len(pieces),
            time.perf_counter() - t0,
            allocated,
        )
        if allocated > self._config.vram_warn_gib:
            logger.warning(
                "VRAM allocated after warmup (%.2f GiB) exceeds the "
                "%.1f GiB soft limit — on a 16 GB card this risks "
                "shared-memory spill and severe slowdown. Check for "
                "other processes holding VRAM.",
                allocated,
                self._config.vram_warn_gib,
            )

    def stream(self, request: GenerationRequest) -> Iterator[str]:
        from transformers import (
            StoppingCriteria,
            StoppingCriteriaList,
            TextIteratorStreamer,
        )

        assert self._model is not None and self._tokenizer is not None
        model, tokenizer, torch = self._model, self._tokenizer, self._torch

        cancel_event = threading.Event()
        self._cancel_event = cancel_event
        self.last_finish_reason = None

        class _CancelledCriteria(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs) -> bool:
                return cancel_event.is_set()

        # enable_thinking=False is locked (persona.ENABLE_THINKING); it is a
        # chat-template knob, not a generate() kwarg.
        prompt = tokenizer.apply_chat_template(
            list(request.messages),
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=persona.ENABLE_THINKING,
        )
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        prompt_len = inputs["input_ids"].shape[-1]
        streamer = TextIteratorStreamer(
            tokenizer,
            skip_prompt=True,
            skip_special_tokens=True,
            timeout=300.0,
        )
        do_sample = request.temperature is not None and request.temperature > 0
        gen_kwargs = dict(
            **inputs,
            streamer=streamer,
            max_new_tokens=request.max_tokens,
            do_sample=do_sample,
            repetition_penalty=request.repetition_penalty,
            use_cache=True,  # explicit, matching the pinned config
            stopping_criteria=StoppingCriteriaList([_CancelledCriteria()]),
            pad_token_id=tokenizer.eos_token_id,
        )
        if do_sample:
            gen_kwargs["temperature"] = request.temperature
            gen_kwargs["top_p"] = request.top_p

        errors: list[BaseException] = []
        new_tokens = [0]

        def _run_generate() -> None:
            try:
                output = model.generate(**gen_kwargs)
                new_tokens[0] = int(output.shape[-1]) - prompt_len
            except BaseException as exc:  # surfaced to the caller below
                errors.append(exc)
            finally:
                streamer.end()  # idempotent; guarantees the iterator ends

        thread = threading.Thread(
            target=_run_generate, name="brain-generate", daemon=True
        )
        thread.start()
        was_cancelled = False
        try:
            for piece in streamer:
                if cancel_event.is_set():
                    was_cancelled = True
                    break
                if piece:
                    yield piece
            was_cancelled = was_cancelled or cancel_event.is_set()
        finally:
            # Normal completion: generate() has already returned. Abandoned
            # or cancelled: the StoppingCriteria stops decode at the next
            # step. Either way, reclaim cache headroom on this 16 GB card.
            cancel_event.set()
            thread.join(timeout=60)
            if torch is not None and torch.cuda.is_available():
                torch.cuda.empty_cache()
        if errors:
            raise errors[0]
        if was_cancelled:
            self.last_finish_reason = FINISH_CANCELLED
        elif new_tokens[0] >= request.max_tokens:
            self.last_finish_reason = FINISH_LENGTH
        else:
            self.last_finish_reason = FINISH_STOP

    def cancel(self) -> None:
        self._cancel_event.set()

    def vram_allocated_gib(self) -> float | None:
        if self._torch is None or not self._torch.cuda.is_available():
            return None
        return float(self._torch.cuda.memory_allocated()) / 2**30
