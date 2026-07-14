"""Automated barge-in probe (issue #11): interrupt-to-silence, end-to-end.

A headless LiveKit participant that measures how fast the running voice
agent falls silent when spoken over — no human in the loop:

1. Gets a token from the local token server for a FRESH probe room; the
   running agent worker auto-dispatches an LKY session into it.
2. Synthesizes real speech utterances via the local cloned-voice TTS server
   (actual speech, so the agent's Silero VAD + Deepgram STT trigger exactly
   as they would for a visitor).
3. Waits for agent audio frames, lets the agent speak for a grace period,
   then publishes a sustained utterance over it and measures the time from
   the barge-in's on-the-wire audio onset until agent audio goes silent
   (>= SILENCE_GAP seconds without an audible frame, then backdated to the
   last audible frame).
4. Repeats for N trials, prints per-trial numbers + p50/max, writes JSON to
   evals/results/barge_in_probe_<shortsha>.json, and deletes the room.

Two numbers are reported per trial, matching the issue #11 gate:

- raw onset->silence: includes the agent's deliberate min-interrupt window
  (LKY_INTERRUPT_MIN_SEC, default 0.3 s of sustained speech before a
  barge-in counts as an interruption);
- detected->silence: raw minus that window — the "interruption detected ->
  playback stopped" figure the <= 350 ms target applies to.

Everything is measured at the audio-frame seam of a real room round-trip,
so the numbers include network + WebRTC both ways (an upper bound on what
the agent itself can influence).

Run (voice_agent venv; the full stack must already be live):

    services\\voice_agent\\.venv\\Scripts\\python.exe scripts\\barge_in_probe.py

Credentials come from the repo-root .env, loaded programmatically and never
printed.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
from dotenv import load_dotenv
from livekit import api, rtc

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

TOKEN_URL = "http://127.0.0.1:8090/api/token"
TTS_URL = "http://127.0.0.1:8100/synthesize"

#: RMS (int16 units) above which a received agent frame counts as audible.
#: Silence/comfort-noise frames sit near 0; the cloned voice is in the
#: thousands. Verified against live frames before the measured trials.
AUDIBLE_RMS = 250.0
#: Agent audio is declared stopped after this long without an audible frame.
SILENCE_GAP_S = 0.5
FRAME_MS = 10

#: Sustained, question-shaped utterances (each several seconds of speech —
#: comfortably beyond the 0.3 s min-interrupt window) so the conversation
#: keeps flowing: every barge-in doubles as the next question.
UTTERANCES = [
    "Wait, wait, stop for a moment please. Let me ask you something "
    "different: what is your view on housing policy in Singapore?",
    "Hold on, hold on, I want to interrupt you there. What about the "
    "future of education for young Singaporeans?",
    "Excuse me, excuse me, let me stop you right there. Tell me about "
    "foreign policy and our neighbours instead.",
    "Wait a moment, wait a moment. I have a different question about "
    "the economy and jobs for the next generation.",
    "Stop, stop, please. Let me ask you instead about young people "
    "and whether they have it easier today.",
    "Hold on, please pause for a second. What would you say about "
    "climate change and how Singapore should respond?",
]


def _min_interrupt_s() -> float:
    raw = os.environ.get("LKY_INTERRUPT_MIN_SEC", "").strip()
    try:
        value = float(raw) if raw else 0.3
    except ValueError:
        return 0.3
    return value if value > 0 else 0.3


def _short_sha() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def synthesize_utterances(cache_dir: Path) -> tuple[int, list[np.ndarray]]:
    """TTS every utterance once (cached as WAV) -> (sample_rate, int16 arrays)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    sample_rate: int | None = None
    waves: list[np.ndarray] = []
    with httpx.Client(timeout=120.0) as client:
        for text in UTTERANCES:
            key = hashlib.sha1(text.encode()).hexdigest()[:16]
            path = cache_dir / f"utt_{key}.wav"
            if not path.is_file():
                resp = client.post(TTS_URL, json={"text": text, "format": "wav"})
                resp.raise_for_status()
                path.write_bytes(resp.content)
            with wave.open(str(path), "rb") as wf:
                sr = wf.getframerate()
                assert wf.getnchannels() == 1 and wf.getsampwidth() == 2
                samples = np.frombuffer(
                    wf.readframes(wf.getnframes()), dtype=np.int16
                )
            # Normalize to a confident speaking level so VAD never misses.
            peak = int(np.abs(samples).max()) or 1
            samples = (samples.astype(np.float64) * (0.85 * 32767 / peak)).astype(
                np.int16
            )
            sample_rate = sample_rate or sr
            assert sr == sample_rate, "TTS sample rate changed between requests"
            waves.append(samples)
    assert sample_rate is not None
    return sample_rate, waves


class Mic:
    """Publishes a continuous 10 ms-frame mic stream: silence by default,
    queued utterances when asked. ``speak`` resolves with the utterance's
    on-the-wire onset time (push time + whatever was already queued)."""

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self.frame_samples = sample_rate * FRAME_MS // 1000
        # A small source queue keeps capture_frame pacing near-realtime and
        # bounds the onset correction below to <= 40 ms.
        self.source = rtc.AudioSource(sample_rate, 1, queue_size_ms=40)
        self._pending: asyncio.Queue[tuple[np.ndarray, asyncio.Future[float]]] = (
            asyncio.Queue()
        )
        self._task: asyncio.Task[None] | None = None

    async def speak(self, samples: np.ndarray) -> float:
        """Queue an utterance; returns its wire-onset perf_counter time."""
        fut: asyncio.Future[float] = asyncio.get_running_loop().create_future()
        self._pending.put_nowait((samples, fut))
        return await fut

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def aclose(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        silence = np.zeros(self.frame_samples, dtype=np.int16)
        current: np.ndarray | None = None
        pos = 0
        while True:
            if current is None and not self._pending.empty():
                current, fut = self._pending.get_nowait()
                pos = 0
                # Frames already queued in the source play out first; the
                # utterance actually hits the wire after them.
                if not fut.done():
                    fut.set_result(
                        time.perf_counter() + self.source.queued_duration
                    )
            if current is not None:
                chunk = current[pos : pos + self.frame_samples]
                pos += self.frame_samples
                if pos >= len(current):
                    current = None
                if len(chunk) < self.frame_samples:
                    chunk = np.concatenate(
                        [chunk, np.zeros(self.frame_samples - len(chunk), np.int16)]
                    )
            else:
                chunk = silence
            frame = rtc.AudioFrame(
                data=chunk.tobytes(),
                sample_rate=self.sample_rate,
                num_channels=1,
                samples_per_channel=self.frame_samples,
            )
            # Blocks when the source queue is full -> realtime pacing.
            await self.source.capture_frame(frame)


class AgentEar:
    """Consumes the agent's audio track and tracks the last audible frame."""

    def __init__(self) -> None:
        self.last_audible: float | None = None
        self.frames_seen = 0
        self._tasks: list[asyncio.Task[None]] = []

    def attach(self, track: rtc.Track) -> None:
        self._tasks.append(asyncio.create_task(self._consume(track)))

    async def _consume(self, track: rtc.Track) -> None:
        stream = rtc.AudioStream(track)
        async for ev in stream:
            self.frames_seen += 1
            data = np.frombuffer(ev.frame.data, dtype=np.int16)
            rms = float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))
            if rms >= AUDIBLE_RMS:
                self.last_audible = time.perf_counter()

    def audible_within(self, window_s: float) -> bool:
        return (
            self.last_audible is not None
            and time.perf_counter() - self.last_audible <= window_s
        )

    async def wait_audible_after(self, marker: float, timeout: float) -> float:
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            if self.last_audible is not None and self.last_audible > marker:
                return self.last_audible
            await asyncio.sleep(0.02)
        raise TimeoutError("no agent audio within timeout")

    async def wait_silence(self, gap_s: float, timeout: float) -> float:
        """Returns the timestamp of the last audible frame once a >= gap_s
        stretch without audible frames has been observed."""
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            now = time.perf_counter()
            if self.last_audible is not None and now - self.last_audible >= gap_s:
                return self.last_audible
            await asyncio.sleep(0.01)
        raise TimeoutError("agent never went silent within timeout")

    async def aclose(self) -> None:
        for task in self._tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


@dataclass
class Trial:
    trial: int
    utterance: str
    agent_audible_before_barge_s: float
    onset_to_silence_ms: float
    detected_to_silence_ms: float
    interrupted: bool


async def run_probe(args: argparse.Namespace) -> dict:
    min_interrupt_s = _min_interrupt_s()
    short_sha = _short_sha()
    room_name = f"barge-probe-{short_sha}-{int(time.time())}"

    cache_dir = Path(tempfile.gettempdir()) / "lky_barge_probe_cache"
    print(f"synthesizing {len(UTTERANCES)} utterances via {TTS_URL} ...")
    sample_rate, waves = synthesize_utterances(cache_dir)
    print(f"utterances ready ({sample_rate} Hz, cached in {cache_dir})")

    resp = httpx.post(
        TOKEN_URL,
        json={"room": room_name, "identity": "barge-probe"},
        timeout=10.0,
    )
    resp.raise_for_status()
    grant = resp.json()
    print(f"joining fresh room {grant['room']!r} as {grant['identity']!r}")

    room = rtc.Room()
    ear = AgentEar()

    @room.on("track_subscribed")
    def _on_track(
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            print(f"subscribed to agent audio from {participant.identity!r}")
            ear.attach(track)

    trials: list[Trial] = []
    try:
        await room.connect(
            grant["url"], grant["token"], options=rtc.RoomOptions(auto_subscribe=True)
        )
        mic = Mic(sample_rate)
        track = rtc.LocalAudioTrack.create_audio_track("probe-mic", mic.source)
        await room.local_participant.publish_track(
            track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
        )
        mic.start()

        marker = time.perf_counter()
        utt_idx = 0
        attempts = 0
        while len(trials) < args.trials and attempts < args.max_attempts:
            attempts += 1
            try:
                speech_start = await ear.wait_audible_after(marker, timeout=120.0)
            except TimeoutError:
                print("no agent speech; nudging with a plain question")
                await mic.speak(waves[utt_idx % len(waves)])
                utt_idx += 1
                marker = time.perf_counter()
                continue
            await asyncio.sleep(args.grace)
            if not ear.audible_within(0.4):
                # The agent finished before we could barge in; ask a plain
                # question to elicit the next (longer) answer instead.
                print("agent finished early; asking a plain question")
                await mic.speak(waves[utt_idx % len(waves)])
                utt_idx += 1
                marker = time.perf_counter()
                continue

            utterance = UTTERANCES[utt_idx % len(waves)]
            onset = await mic.speak(waves[utt_idx % len(waves)])
            utt_idx += 1
            try:
                t_stop = await ear.wait_silence(SILENCE_GAP_S, timeout=25.0)
            except TimeoutError:
                print(f"trial {len(trials) + 1}: agent never went silent (FAILED)")
                marker = time.perf_counter()
                continue
            raw_s = t_stop - onset
            marker = t_stop
            if raw_s < 0:
                # The agent stopped on its own before our audio reached it —
                # not an interruption; don't count it either way.
                print("agent stopped before barge-in arrived; retrying")
                continue
            trial = Trial(
                trial=len(trials) + 1,
                utterance=utterance,
                agent_audible_before_barge_s=round(onset - speech_start, 3),
                onset_to_silence_ms=round(raw_s * 1000, 1),
                detected_to_silence_ms=round(
                    max(0.0, raw_s - min_interrupt_s) * 1000, 1
                ),
                interrupted=raw_s <= 8.0,
            )
            trials.append(trial)
            print(
                f"trial {trial.trial}: onset->silence {trial.onset_to_silence_ms:.0f} ms raw, "
                f"detected->silence {trial.detected_to_silence_ms:.0f} ms "
                f"(agent had spoken {trial.agent_audible_before_barge_s:.1f} s)"
            )
    finally:
        with contextlib.suppress(Exception):
            await mic.aclose()
        with contextlib.suppress(Exception):
            await ear.aclose()
        with contextlib.suppress(Exception):
            await room.disconnect()
        # Delete the probe room so nothing lingers for the live stack.
        try:
            lkapi = api.LiveKitAPI()  # credentials from env, never printed
            await lkapi.room.delete_room(api.DeleteRoomRequest(room=room_name))
            await lkapi.aclose()
            print(f"deleted room {room_name!r}")
        except Exception as exc:  # room may already be gone
            print(f"room delete: {type(exc).__name__} (ignored)")

    interrupted = [t for t in trials if t.interrupted]
    raw = [t.onset_to_silence_ms for t in interrupted]
    adj = [t.detected_to_silence_ms for t in interrupted]
    summary = {
        "n_trials": len(trials),
        "n_interrupted": len(interrupted),
        "raw_onset_to_silence_p50_ms": round(statistics.median(raw), 1) if raw else None,
        "raw_onset_to_silence_max_ms": max(raw) if raw else None,
        "detected_to_silence_p50_ms": round(statistics.median(adj), 1) if adj else None,
        "detected_to_silence_max_ms": max(adj) if adj else None,
        "target_ms": 350,
        "pass_detected_p50": bool(adj) and statistics.median(adj) <= 350,
        "pass_raw_p50": bool(raw) and statistics.median(raw) <= 350,
    }
    return {
        "probe": "barge_in",
        "issue": 11,
        "git_sha": short_sha,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "room": room_name,
        "config": {
            "trials_target": args.trials,
            "grace_s": args.grace,
            "silence_gap_s": SILENCE_GAP_S,
            "min_interrupt_s": min_interrupt_s,
            "audible_rms_threshold": AUDIBLE_RMS,
            "mic_sample_rate": sample_rate,
            "notes": (
                "onset->silence measured at the probe's audio-frame seam of a "
                "real LiveKit round-trip (includes network/WebRTC both ways); "
                "silence backdated to the last audible agent frame; "
                "detected->silence subtracts the agent's min-interrupt window"
            ),
        },
        "trials": [asdict(t) for t in trials],
        "summary": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trials", type=int, default=6)
    parser.add_argument("--max-attempts", type=int, default=15)
    parser.add_argument(
        "--grace",
        type=float,
        default=2.0,
        help="seconds of agent speech before barging in",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=REPO_ROOT / "evals" / "results"
    )
    args = parser.parse_args()

    report = asyncio.run(run_probe(args))
    out_path = args.out_dir / f"barge_in_probe_{report['git_sha']}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))
    print(f"wrote {out_path}")
    if report["summary"]["n_interrupted"] == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
