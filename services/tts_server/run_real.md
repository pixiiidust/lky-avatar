# Running the cloned-voice TTS server (GPU, WSL)

The cloned elder voice (blind-test winner: Chatterbox — issue #7) is
CUDA-only and runs under **WSL** in the `~/tts-chatterbox` venv
(torch 2.13+cu130, chatterbox-tts, `setuptools<81`). Same-GPU placement
beside the resident brain is measured-viable (RTF 0.36–0.49 with the 14B
brain loaded — docs/reports/voice-blind-test-results.md), so this server and
the brain server run together on the 16 GB card.

Non-negotiables baked into this service:

- **Loopback only.** Bind `127.0.0.1` and nothing else — the LiveKit agent
  is the sole client; there must never be a public text-in/LKY-voice-out
  endpoint (spec §9). Do not "fix" a connectivity problem by binding
  `0.0.0.0`.
- **Watermark preserved.** Chatterbox embeds Resemble's PerTh perceptual
  watermark inside generation; every response carries it (`X-Watermark:
  perth`). Never strip, re-synthesize, or lossily launder the audio.

## One-time: web-server deps into the WSL venv

`~/tts-chatterbox` has the audio stack but not the web stack. Install the
small pure-Python server deps with uv (no CUDA packages are touched):

```powershell
wsl -d Ubuntu-24.04 -- bash -c '~/.local/bin/uv pip install --python ~/tts-chatterbox/bin/python "fastapi==0.139.0" "uvicorn==0.51.0"'
```

## Launch

From Windows (PowerShell or Git Bash). Loopback binding is mandatory (see
above); WSL2 forwards `127.0.0.1` to Windows automatically:

```powershell
wsl -d Ubuntu-24.04 -- bash -c 'cd /mnt/c/Users/Jamie/lky-avatar/services/tts_server && ~/tts-chatterbox/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8100 --log-level info'
```

Model load + warmup takes ~1 minute; the server accepts requests only after
the log prints `tts server ready`. If Windows→WSL localhost forwarding ever
breaks (occasionally after a WSL restart), restart WSL (`wsl --shutdown`) —
do NOT widen the bind address.

Environment knobs (all optional):

| var | default | meaning |
|---|---|---|
| `LKY_TTS_REF` | `assets/voices/elder/elder_ref_01.wav` | reference clip (1990-era primary; operator's A/B listen chose 1990 over the objective ranking's 2005 — swap eras here) |
| `LKY_TTS_SEED` | `7` | torch seed per generation (reproducibility) |
| `LKY_TTS_DEVICE` | `cuda` | torch device |
| `LKY_TTS_SPEED` | `1.0` | server-side default delivery-speed factor; the agent sends its own per-request (`LKY_TTS_SPEED` on the agent side, default 0.85 — measured exact match to the 1990 refs' word rate is 0.81) |
| `LKY_TTS_ENGINE` | `chatterbox` | `fake` = CPU-only tone generator for HTTP-contract smoke tests |

## Verify

```bash
curl -s http://127.0.0.1:8100/health
# expect: model_loaded true, sample_rate 24000, watermark "perth"

curl -s -X POST http://127.0.0.1:8100/synthesize \
  -H 'Content-Type: application/json' \
  -d '{"text": "Singapore was never meant to survive on sentiment.", "speed": 0.85}' \
  -o phrase.wav -D -
# expect: 200, audio/wav, X-Sample-Rate: 24000; play phrase.wav and listen
```

Latency expectation (measured 2026-07-14, RTX 5070 Ti, speed 0.85 —
includes the time stretch): a one-sentence phrase synthesizes in ~1.9–3.0 s
wall (RTF 0.31–0.86 of output audio duration; the high end is the first
request after warmup). With the 14B brain resident but idle on the same
GPU: RTF 0.37–0.49 — placement holds. While the brain is ACTIVELY decoding
a long answer, synthesis contends for the GPU and can briefly exceed
realtime (measured RTF up to 1.8 for one phrase); the agent's
synthesize-ahead pipeline absorbs this for typical spoken answers.

## Shut down

Ctrl-C, or from Windows:

```powershell
wsl -d Ubuntu-24.04 -- pkill -f "uvicorn app:app.*8100"
```

Do not leave the model holding VRAM (GOAL.md GPU serialization). Confirm with
`wsl -d Ubuntu-24.04 -- nvidia-smi`.
