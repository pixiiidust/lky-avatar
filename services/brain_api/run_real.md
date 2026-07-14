# Running the brain API with the real model (GPU verification)

The real engine (Qwen3-14B 4-bit NF4 + epoch-2 adapter) is CUDA-only and runs
under **WSL** in the `~/uns` venv (torch 2.12.1+cu130, transformers 5.3.0,
peft 0.19.1 — the only CUDA-capable Python on this machine, per GOAL.md).
The GPU fits **one** model at a time: make sure no eval/benchmark run is
using it first.

## One-time: web-server deps into the WSL env

`~/uns` has the CUDA stack but not the web stack. Install the three small,
pure-Python server deps (pinned to match `requirements.txt`; no CUDA
packages are touched):

```powershell
wsl -d Ubuntu-24.04 -- bash -c '~/uns/bin/pip install "fastapi==0.139.0" "uvicorn==0.51.0" "python-dotenv==1.2.2"'
```

## Launch

From Windows (PowerShell or Git Bash). `--host 0.0.0.0` is required so the
Windows-side agent can reach the server; the adapter is read from the local
lky-brain checkout (faster and offline-safe vs pulling `sjsim/lky-qlora`):

```powershell
wsl -d Ubuntu-24.04 -- bash -c 'cd /mnt/c/Users/Jamie/lky-avatar/services/brain_api && BRAIN_ENGINE=transformers LKY_ADAPTER=/mnt/c/Users/Jamie/lky-brain/train/out-lky-qlora/keep-epoch2-step1050 ~/uns/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8000 --log-level info'
```

Expect several minutes of load time; the server accepts requests only after
the model is loaded and warmed up (the log prints
`brain api ready: engine=transformers ...` and the warmup VRAM figure —
expect ~10.5 GiB allocated; a warning fires above `LKY_VRAM_WARN_GIB`=12).

**WSL2 localhost forwarding:** Windows reaches the server at
`http://127.0.0.1:8000` automatically (WSL2 forwards localhost). If that ever
fails (forwarding occasionally breaks after a WSL restart), use the WSL IP
directly: `wsl -d Ubuntu-24.04 hostname -I` → `http://<that-ip>:8000`.

Shut the server down with Ctrl-C (or `wsl -d Ubuntu-24.04 -- pkill -f "uvicorn app:app"`)
when done — do not leave the model holding VRAM (GOAL.md GPU serialization).

## Verification checklist (issue #5 acceptance)

All commands from the Windows side. Reality check: NF4 decode measures
~2–3 tok/s on this GPU, so full answers take minutes — watch the stream,
don't wait silently.

1. **Health / models truthful**

   ```bash
   curl -s http://127.0.0.1:8000/health
   # expect: model_loaded true, generation_in_flight false, vram_allocated_gib ≈ 10.5
   curl -s http://127.0.0.1:8000/v1/models
   # expect: one model, id "lky"
   ```

2. **Streaming from a plain client** (chunks must appear incrementally, in
   character, ending with `data: [DONE]`)

   ```bash
   curl -N -s http://127.0.0.1:8000/v1/chat/completions \
     -H 'Content-Type: application/json' \
     -d '{"model":"lky","stream":true,"max_tokens":96,"messages":[
           {"role":"system","content":"You are Lee Kuan Yew, former Prime Minister of Singapore, speaking candidly in an interview. It is July 2026."},
           {"role":"user","content":"What do you make of artificial intelligence?"}]}'
   ```

3. **Cancellation mid-stream frees the GPU**: run the curl above again,
   Ctrl-C after a few chunks, then immediately:

   ```bash
   curl -s http://127.0.0.1:8000/health
   # expect within ~a second: generation_in_flight false,
   # vram_allocated_gib back to the idle figure (no growth)
   ```

   The server log should show `finish=disconnected` for that request. A new
   request afterwards must work (slot released, no 429).

4. **Busy guard**: start one streaming curl, and while it runs, from a second
   terminal send another request — expect HTTP 429 with the
   "LKY is speaking with someone" body.

5. **20-turn conversation, one process, VRAM stable** (also covers the
   "matches terminal-chat behavior" persona check — it uses the vendored
   `persona.system_prompt()`; compare answers' character against the issue #2
   / #3 transcripts):

   ```bash
   python scripts/brain_20turn_check.py --base-url http://127.0.0.1:8000 \
     --max-tokens 160 --out scripts/out_brain_20turn.json
   ```

   PASS criteria enforced by the script: 20/20 streamed turns, `instance_id`
   never changes (no restart), `generation_in_flight` false after every turn,
   VRAM peak < 12 GiB and drift < 1 GiB across the conversation.
   (`--max-tokens 160` keeps the run under ~30–45 min at measured decode
   speed; drop the flag for full-length 320-token answers.)

6. **Tidy up**: stop the server, confirm VRAM is released
   (`wsl -d Ubuntu-24.04 -- nvidia-smi`).
