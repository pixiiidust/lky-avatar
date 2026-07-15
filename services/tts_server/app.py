"""LKY cloned-voice TTS server (issue #8) — Chatterbox behind a loopback seam.

A small FastAPI service that loads the blind-test-winning engine ONCE
(resemble-ai Chatterbox, zero-shot clone from one elder reference clip) and
synthesizes one phrase per request:

    POST /synthesize {"text": "...", "speed": 0.85, "format": "pcm"|"wav"}
        -> audio bytes (raw s16le mono PCM, or a WAV file for curl/listening)
    GET  /health
        -> engine/readiness report (never blocks on a running synthesis)

Runs in the WSL ``~/tts-chatterbox`` venv (torch+cu130, chatterbox-tts,
setuptools<81) — see run_real.md for the exact install/launch commands.

Fine-tuned voice (lky-voice issue #8, eval-gate verdict: integrate): set
``LKY_TTS_T3`` to a merged t3 safetensors (LoRA already folded in) and the
engine overlays it onto the stock Chatterbox at load — same architecture,
same zero-shot conditioning, same watermark path; /health reports the t3 tag.
Production default: ``~/lky-voice-models/t3_lky_lora_e14.safetensors``.

Security posture (spec §9 / user story 27): this process must ONLY ever bind
127.0.0.1 — the LiveKit agent is its sole client, and nobody may reach a
public text-in/LKY-voice-out endpoint. The launch command in run_real.md
binds loopback; there is no auth layer by design, because there is no
non-loopback exposure.

Watermark (spec §9 / user story 28): Chatterbox embeds Resemble's PerTh
perceptual watermark inside ``generate()`` — every sample this server emits
is watermarked at the source, and nothing downstream may strip or re-encode
it away. The optional time-stretch (below) is a resampling of the
watermarked signal, not a watermark removal; ``X-Watermark: perth`` is set
on every response as a reminder.

Delivery speed: the engine clones the elder timbre but speaks much faster
than the real 82-year-old (~1.7x measured — voice-blind-test-results.md).
``speed`` < 1 slows delivery via librosa's pitch-preserving phase-vocoder
time stretch (``librosa.effects.time_stretch``), chosen because
``ChatterboxTTS.generate()`` exposes no rate parameter (verified signature:
repetition_penalty/min_p/top_p/exaggeration/cfg_weight/temperature only)
and naive resampling would also shift pitch and change the voice identity.
Request ``speed`` wins; else the LKY_TTS_SPEED env default; else 1.0.

Audio I/O goes through soundfile: torchaudio>=2.9 delegates save() to
torchcodec, which needs system FFmpeg libs this WSL lacks (same fix as
scripts/blind_test_synthesize.py, PR #29).

Concurrency: the GPU gets ONE synthesis at a time (a single threading.Lock
around generate; FastAPI runs these sync handlers in a threadpool, so /health
stays responsive while a synthesis runs).
"""

from __future__ import annotations

import io
import logging
import os
import pathlib
import threading
import time
from contextlib import asynccontextmanager
from typing import Literal

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

logger = logging.getLogger("lky.tts")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
# Default reference: the 1990 National Day set's primary clip. The objective
# blind-test ranking preferred the 2005 refs on embedding similarity, but the
# operator's A/B listen preferred 1990 (cleaner studio audio; matches the
# chosen portrait's age) — human override, recorded in
# docs/reports/voice-blind-test-results.md. Swap eras with LKY_TTS_REF.
DEFAULT_REF = REPO_ROOT / "assets" / "voices" / "elder" / "elder_ref_04.wav"
DEFAULT_SEED = 7

MAX_TEXT_CHARS = 1000  # phrases are sentences; reject essay-sized requests
SPEED_MIN, SPEED_MAX = 0.5, 2.0


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


class SynthesizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    speed: float | None = Field(default=None, ge=SPEED_MIN, le=SPEED_MAX)
    format: Literal["pcm", "wav"] = "wav"


class ChatterboxEngine:
    """The real engine. Heavy imports happen here, at load time, once."""

    def __init__(self, ref: pathlib.Path, seed: int, device: str,
                 t3_weights: pathlib.Path | None = None) -> None:
        import torch
        from chatterbox.tts import ChatterboxTTS

        self._torch = torch
        self.ref = ref
        self.seed = seed
        self.model = ChatterboxTTS.from_pretrained(device=device)
        # Fine-tuned t3 overlay (LKY_TTS_T3): a full t3 state dict with the
        # LKY LoRA merged in (lky-voice issue #8, verdict: integrate). Same
        # architecture/vocab as the stock t3, so a strict load either succeeds
        # completely or refuses to start — no silent half-loaded voice.
        self.t3_tag = "stock"
        if t3_weights is not None:
            from safetensors.torch import load_file

            self.model.t3.load_state_dict(load_file(str(t3_weights)), strict=True)
            self.model.t3.to(device).eval()
            self.t3_tag = t3_weights.stem
        self.sample_rate: int = int(self.model.sr)

    def describe(self) -> str:
        return (f"chatterbox t3={self.t3_tag} ref={self.ref.name} "
                f"seed={self.seed} sr={self.sample_rate}")

    def synthesize(self, text: str) -> np.ndarray:
        """Text -> float32 mono waveform (PerTh watermark already embedded)."""
        self._torch.manual_seed(self.seed)
        wav = self.model.generate(text, audio_prompt_path=str(self.ref))
        arr = wav.detach().cpu().numpy()
        if arr.ndim == 2:  # (channels, n) -> mono
            arr = arr[0]
        return arr.astype(np.float32)


class FakeEngine:
    """CPU-only stand-in (LKY_TTS_ENGINE=fake): a tone whose length scales
    with the text, so the HTTP contract is testable with no GPU/model."""

    sample_rate = 24_000

    def __init__(self, ref: pathlib.Path, seed: int, device: str,
                 t3_weights: pathlib.Path | None = None) -> None:
        self.ref = ref
        self.seed = seed

    def describe(self) -> str:
        return f"fake sr={self.sample_rate}"

    def synthesize(self, text: str) -> np.ndarray:
        n = int(self.sample_rate * max(0.2, len(text) * 0.05))
        t = np.arange(n, dtype=np.float32) / self.sample_rate
        return (0.1 * np.sin(2 * np.pi * 220.0 * t)).astype(np.float32)


def apply_speed(wav: np.ndarray, speed: float) -> np.ndarray:
    """Pitch-preserving time stretch; speed<1 slows delivery (see module doc).

    A stretch of the already-watermarked signal — never a re-synthesis, never
    a watermark strip. speed=1 is the identity (no processing at all).
    """
    if speed == 1.0:
        return wav
    import librosa  # lazy: only needed when a stretch is requested

    return librosa.effects.time_stretch(wav, rate=float(speed)).astype(np.float32)


def encode_pcm(wav: np.ndarray) -> bytes:
    """float32 [-1,1] -> raw s16le bytes (what the LiveKit adapter streams)."""
    clipped = np.clip(wav, -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


def encode_wav(wav: np.ndarray, sample_rate: int) -> bytes:
    """float32 -> WAV bytes via soundfile (torchcodec unavailable; PR #29)."""
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, wav, sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


_ENGINES = {"chatterbox": ChatterboxEngine, "fake": FakeEngine}

_engine: ChatterboxEngine | FakeEngine | None = None
_default_speed: float = 1.0
_synthesis_lock = threading.Lock()  # the GPU takes one synthesis at a time


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _engine, _default_speed
    engine_name = os.environ.get("LKY_TTS_ENGINE", "chatterbox").strip() or "chatterbox"
    if engine_name not in _ENGINES:
        raise RuntimeError(f"LKY_TTS_ENGINE={engine_name!r}; choose from {sorted(_ENGINES)}")
    ref = pathlib.Path(os.environ.get("LKY_TTS_REF", "").strip() or DEFAULT_REF)
    if engine_name == "chatterbox" and not ref.is_file():
        raise RuntimeError(
            f"reference clip not found: {ref} — set LKY_TTS_REF or place the "
            "elder reference clips in assets/voices/elder/ (local-only assets; "
            "see assets/voices/README.md)"
        )
    seed = int(os.environ.get("LKY_TTS_SEED", "").strip() or DEFAULT_SEED)
    device = os.environ.get("LKY_TTS_DEVICE", "").strip() or "cuda"
    _default_speed = min(SPEED_MAX, max(SPEED_MIN, _env_float("LKY_TTS_SPEED", 1.0)))
    t3_raw = os.environ.get("LKY_TTS_T3", "").strip()
    t3_weights = pathlib.Path(t3_raw) if t3_raw else None
    if engine_name == "chatterbox" and t3_weights is not None and not t3_weights.is_file():
        raise RuntimeError(f"fine-tuned t3 weights not found: {t3_weights} (LKY_TTS_T3)")

    t0 = time.monotonic()
    _engine = _ENGINES[engine_name](ref=ref, seed=seed, device=device, t3_weights=t3_weights)
    # Warm up (first CUDA generate pays one-off graph/alloc costs) so the
    # session's first phrase doesn't.
    _engine.synthesize("Good evening.")
    logger.info(
        "tts server ready in %.1fs: %s default_speed=%s (loopback only — "
        "PerTh watermark embedded in every response)",
        time.monotonic() - t0,
        _engine.describe(),
        _default_speed,
    )
    yield


app = FastAPI(title="lky-tts-server", lifespan=_lifespan)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok" if _engine is not None else "loading",
        "model_loaded": _engine is not None,
        "engine": _engine.describe() if _engine is not None else None,
        "sample_rate": _engine.sample_rate if _engine is not None else None,
        "default_speed": _default_speed,
        "synthesis_in_flight": _synthesis_lock.locked(),
        "watermark": "perth",
    }


@app.post("/synthesize")
def synthesize(req: SynthesizeRequest) -> Response:
    if _engine is None:  # pragma: no cover - lifespan loads before serving
        raise HTTPException(status_code=503, detail="model still loading")
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is empty")
    speed = req.speed if req.speed is not None else _default_speed

    t0 = time.monotonic()
    with _synthesis_lock:
        wav = _engine.synthesize(text)
        wav = apply_speed(wav, speed)
    synth_seconds = time.monotonic() - t0

    sr = _engine.sample_rate
    audio_seconds = len(wav) / sr
    if req.format == "pcm":
        body, media_type = encode_pcm(wav), "audio/pcm"
    else:
        body, media_type = encode_wav(wav, sr), "audio/wav"

    logger.info(
        "synthesized %d chars -> %.2fs audio in %.2fs (rtf %.2f, speed %s)",
        len(text), audio_seconds, synth_seconds,
        synth_seconds / audio_seconds if audio_seconds else 0.0, speed,
    )
    return Response(
        content=body,
        media_type=media_type,
        headers={
            "X-Sample-Rate": str(sr),
            "X-Audio-Seconds": f"{audio_seconds:.3f}",
            "X-Synth-Seconds": f"{synth_seconds:.3f}",
            "X-Speed": str(speed),
            "X-Watermark": "perth",
        },
    )
