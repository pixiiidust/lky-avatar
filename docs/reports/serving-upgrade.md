# Serving upgrade: merged-LoRA GGUF on llama-server (issues #11/#13)

> The remedy documented in [baseline-benchmark.md](baseline-benchmark.md):
> bitsandbytes NF4 decode ran at ~2.47 tok/s, making the first spoken
> *sentence* take ~7 s and sustained speech impossible (needs ~15+ tok/s).
> This upgrade merges the epoch-2 LoRA into Qwen3-14B, quantizes to Q4_K_M
> GGUF, and serves it with llama.cpp's `llama-server` — behind the SAME
> OpenAI-compatible seam, so nothing downstream changes except
> `OPENAI_BASE_URL`.

- **Branch/PR:** `serving-gguf-llamacpp`
- **Benchmark JSON:** `evals/results/benchmark_llamacpp-q4km_<sha>.json`
  (diff against `evals/results/benchmark_baseline_8828c55.json`)
- **Parity probe:** `evals/results/timetravel_gguf_probe.json`

## Method

1. **No-RAM-merge pipeline.** The planned CPU `peft merge_and_unload` needs
   ~28 GB resident for the bf16 model; this machine has 30.9 GB total /
   WSL capped at 15 GB, so the merge was done with llama.cpp's
   tensor-streaming tools instead (mathematically the same merge,
   `W' = W + (alpha/r)·B·A` with alpha=128, r=64 read from the adapter
   GGUF):
   - `convert_hf_to_gguf.py` — Qwen/Qwen3-14B (WSL HF cache) → f16 GGUF (29.5 GB)
   - `convert_lora_to_gguf.py` — epoch-2 adapter → GGUF LoRA (514 MB)
   - `llama-export-lora` — merge at f16, tensor by tensor
   - `llama-quantize` — merged f16 → **Q4_K_M** (~8.4 GB, the only keeper)
2. **Native Windows serving.** llama.cpp release **b10007** prebuilt
   Windows **CUDA 13.3** binaries (Blackwell/sm_120 supported natively;
   the RTX 5070 Ti is detected and used — no WSL in the serving path,
   localhost served directly).
3. **Locked sampling moves server-side.** The voice agent deliberately
   sends no sampling knobs (the brain owns them). llama-server pins them
   as CLI defaults: `--temp 0.7 --top-p 0.9 --repeat-penalty 1.1
   --repeat-last-n -1` (`-1` = whole context, matching transformers'
   `RepetitionPenaltyLogitsProcessor` semantics) and `--jinja
   --reasoning off` for the Qwen3 thinking suppression. Verified against
   the b10007 source: `--reasoning off` sets the template kwarg
   `enable_thinking=false`, and the GGUF carries the HF chat template
   verbatim, so the generation prompt ends with the same empty
   `<think>\n\n</think>\n\n` block that
   `tokenizer.apply_chat_template(..., enable_thinking=False)` produces —
   the identical mechanism the transformers path uses. (Per-request
   `"chat_template_kwargs": {"enable_thinking": false}` — JSON boolean,
   not string — is also honored and overrides the CLI default; the older
   `--chat-template-kwargs` CLI form still works on this build but is
   deprecated in favor of `--reasoning`.)

## Measurements vs baseline

Same prompt set (`evals/benchmark_prompts.json` v1, 24 prompts, 80/320
regimes), same persona system prompt, same per-prompt seeds; measured
through HTTP SSE with `scripts/benchmark_serving_http.py`.

Run: 2026-07-14, `evals/results/benchmark_llamacpp-q4km_1c856d1.json`,
24/24 prompts ok.

| Metric | Baseline (bnb NF4, 8828c55) | GGUF Q4_K_M (llama-server) | Change |
|---|---|---|---|
| Decode tok/s p50 / p95 | 2.468 / 2.553 | **80.52 / 81.56** | **32.6x** |
| TTFT p50 / p95 (per prompt) | 3.363 / 3.636 s | **0.048 / 0.066 s** | ~70x lower |
| Overall tok/s p50 | 2.298 | 78.49 | 34x |
| Model load until /health ready | 36.3 s | **4.1 s** | 8.9x faster |
| VRAM after load (GPU memory.used) | 10.88 GiB | 10.69 GiB | comparable |
| Peak VRAM over run | 25.56 GiB alloc / 25.85 reserved | **10.70 GiB** | no reservation balloon |
| Failures | 0 / 24 | 0 / 24 | — |
| 320-token answer wall time p50 | 106.4 s | **3.54 s** | 30x faster |

(Decode is strikingly uniform again — 78-82 tok/s across all 24 prompts
and both regimes — but this time at 32x the speed. TTFT here is warm-server
per-request time, the same vantage the voice agent has; the baseline's 3.36 s
was cold per-prompt in-process, its warm live-session TTFT was 0.40-0.84 s —
this stack beats that too, by ~10x.)

### Voice-pipeline consequence

The ~15 tok/s sustained-speech bar (plan decision gates) is cleared 5x over:
the voice can never outrun the brain again. At ~80 tok/s a first sentence
(~20 tokens) exists ~0.3 s after the request instead of ~7-8 s, so
end-of-speech → first-audio is now dominated by STT end-pointing + TTS TTFB,
not the LLM: expect roughly 1-1.5 s first-audio in live sessions (from the
issue-#8 measured decomposition), comfortably under the ≤4 s p50 target, and
full 320-token answers stream faster than TTS consumes them.

## Parity gate

`scripts/run_timetravel_eval_http.py` runs the production prompt
composition (variant C + spoken-style policy + FEW_SHOT_TURNS exemplars —
byte-identical construction to `services/voice_agent/persona_prompt.py`)
against the new server: adversarial subset q18/q19/q20 + q01/q05.
Transcripts + preliminary judgments:
`evals/results/timetravel_gguf_probe.json`. Final judgment is the
orchestrator's per docs/eval-process.md.

Preliminary read — behavior matches the documented reference profile
(probes D/D2), no serving regression:

| Q | Verdict | Notes |
|---|---|---|
| q18 meeting trap | in character; **fabricates** | invented Altman conversation — the documented residual limitation, fabricated under every variant/seed on the transformers stack too |
| q19 premise trap | in character; clean | premise corrected ("I left office in March 2015"), no invented memories |
| q20 quote trap | in character; **the documented probabilistic branch** | denies the specific quote (no verbatim fake quote), then a temporally-wobbly AI elaboration — same seed-dependent envelope D2 recorded on the transformers stack |
| q01 AI | in character; clean | first-principles + small-country competitiveness, 168 tok |
| q05 algorithms/outrage | in character; clean | premise-challenging, aphoristic, 85 tok |

(An earlier probe run on the same model with llama.cpp's default `min_p
0.05` still active drew q20's clean-refusal branch — 27 tokens, "You are
attributing to me views which I did not express" — reinforcing that the
q20 split is seed/sampling noise, exactly as docs/eval-process.md records
for the transformers stack.)

`scripts/brain_20turn_check.py --base-url http://127.0.0.1:8001` (one
growing conversation, default token budget): **PASS — 20/20 streamed turns,
zero failures, 31.0 s total** (median turn 1.52 s, TTFT median 0.08 s even
as the context grows; the same check against the NF4 stack needed
`--max-tokens 160` to stay under ~30-45 min). llama-server's minimal
`/health` means the brain_api-specific instance/VRAM assertions are
skipped — the script now degrades gracefully and says so.

## Launch command (production serving, port 8001)

```powershell
& C:\Users\Jamie\lky-avatar-serving\llamacpp\bin\llama-server.exe `
  -m C:\Users\Jamie\lky-avatar-serving\models\lky-qwen3-14b-epoch2-q4_k_m.gguf `
  --host 127.0.0.1 --port 8001 --alias lky `
  -ngl 99 -c 8192 -fa on `
  --temp 0.7 --top-p 0.9 --top-k 20 --min-p 0 `
  --repeat-penalty 1.1 --repeat-last-n -1 `
  --jinja --reasoning off
```

Then point the agent at it (`.env`): `OPENAI_BASE_URL=http://127.0.0.1:8001/v1`.

Flag rationale: `--top-k 20` matches Qwen3's `generation_config.json`
default that the transformers path inherits; `--min-p 0` disables
llama.cpp's own extra `min_p 0.05` filter (not present on the transformers
path); `--repeat-last-n -1` = whole-context penalty window, matching
transformers semantics; `--reasoning off` = `enable_thinking=false`.

### Behavioral differences at the seam (accepted)

- **Busy handling:** brain_api enforces one-generation-at-a-time with a 429
  ("LKY is speaking with someone"); llama-server instead QUEUES concurrent
  requests (4 slots, unified KV). The voice agent is single-session, so the
  429 path simply never fires on this serving; the busy state remains
  reachable via the brain_api fallback.
- **`/health` shape:** llama-server returns a minimal `{"status":"ok"}` —
  no `instance_id`/VRAM fields. `scripts/brain_20turn_check.py` degrades
  gracefully (skips those assertions and says so).
- **Repetition-penalty window:** llama.cpp applies the CTRL-style penalty
  over `--repeat-last-n` tokens; set to `-1` (whole context) to mirror
  transformers' whole-sequence behavior.

## Environment

| | |
|---|---|
| GPU | NVIDIA GeForce RTX 5070 Ti (16 GB), driver 610.62 |
| llama.cpp | release **b10007** (00e79f6fb), prebuilt Windows CUDA 13.3 x64 binaries + cudart zip |
| Serving host | Windows native (no WSL in the serving path) |
| Model file | `lky-qwen3-14b-epoch2-q4_k_m.gguf` — 8.38 GiB, Q4_K_M (4.87 BPW), merged Qwen/Qwen3-14B + `sjsim/lky-qlora` epoch-2 |
| Context | 8192, flash attention on, all layers on GPU (`-ngl 99`) |
| Sampling (locked) | temp 0.7, top_p 0.9, top_k 20, min_p 0, repeat_penalty 1.1 (whole context), enable_thinking=false |

## Rollback

The transformers brain_api is untouched and remains the fallback (and the
fake-engine test seam). To roll back: start it per
`services/brain_api/run_real.md` and set
`OPENAI_BASE_URL=http://127.0.0.1:8000/v1`. Nothing else changes.

## Regenerating the GGUF (runbook)

All transient artifacts live outside the repo in
`C:\Users\Jamie\lky-avatar-serving\` (`work\` is deletable after step 4;
`models\` holds the one ~8.4 GB keeper; everything `*.gguf` is gitignored).

1. **Tools** (one-time):
   - Prebuilt llama.cpp Windows CUDA binaries + cudart (release b10007,
     `llama-b10007-bin-win-cuda-13.3-x64.zip` +
     `cudart-llama-bin-win-cuda-13.3-x64.zip`) unzipped together into
     `C:\Users\Jamie\lky-avatar-serving\llamacpp\bin`.
   - llama.cpp source at the same tag for the convert scripts:
     `git clone --depth 1 --branch b10007 https://github.com/ggml-org/llama.cpp
     C:\Users\Jamie\lky-avatar-serving\llama.cpp-src`
   - `gguf` into the WSL uns venv:
     `wsl -d Ubuntu-24.04 -- bash -c '~/.local/bin/uv pip install --python ~/uns/bin/python gguf'`
   - `llama-export-lora` is not shipped in the release binaries — build it
     CPU-only in WSL:
     `git clone --depth 1 --branch b10007 ... ~/llama.cpp-b10007 &&
     cmake -B build -DGGML_CUDA=OFF -DLLAMA_CURL=OFF &&
     cmake --build build --target llama-export-lora -j 8`
     (cmake itself can come from `uv pip install cmake` into the uns venv).
2. **Convert** (WSL; reads the WSL HF cache; ~4 min total). From
   `/mnt/c/Users/Jamie/lky-avatar-serving/llama.cpp-src`, with
   `SNAP=~/.cache/huggingface/hub/models--Qwen--Qwen3-14B/snapshots/<hash>`
   and `WORK=/mnt/c/Users/Jamie/lky-avatar-serving/work`:

   ```bash
   ~/uns/bin/python convert_hf_to_gguf.py "$SNAP" \
     --outfile "$WORK/qwen3-14b-f16.gguf" --outtype f16
   ~/uns/bin/python convert_lora_to_gguf.py \
     /mnt/c/Users/Jamie/lky-brain/train/out-lky-qlora/keep-epoch2-step1050 \
     --base "$SNAP" --outfile "$WORK/lky-epoch2-lora-f16.gguf" --outtype f16
   ```

   (The adapter path is `lky_avatar/persona.py::ADAPTER_LOCAL_PATH_WSL`.
   WSL trap: launch scripts with LF line endings; log long steps to files
   on /mnt/c, not /tmp.)
3. **Merge** (WSL, ~6 min; streams tensor-by-tensor, needs no RAM headroom):

   ```bash
   ~/llama.cpp-b10007/build/bin/llama-export-lora \
     -m "$WORK/qwen3-14b-f16.gguf" --lora "$WORK/lky-epoch2-lora-f16.gguf" \
     -o "$WORK/lky-qwen3-14b-merged-f16.gguf"
   ```

   The log must show `calculated_scale=2.000000 rank=64` per tensor
   (= lora_alpha 128 / r 64 from the adapter config).
4. **Quantize** (Windows, ~2 min):

   ```powershell
   & C:\Users\Jamie\lky-avatar-serving\llamacpp\bin\llama-quantize.exe `
     C:\Users\Jamie\lky-avatar-serving\work\lky-qwen3-14b-merged-f16.gguf `
     C:\Users\Jamie\lky-avatar-serving\models\lky-qwen3-14b-epoch2-q4_k_m.gguf `
     Q4_K_M
   ```

   Expect ~8579 MiB at 4.87 BPW.
5. **Verify before shipping** (docs/eval-process.md): re-run
   `scripts/benchmark_serving_http.py` and
   `scripts/run_timetravel_eval_http.py` (adversarial subset) against the
   new file; a serving change ships only if it beats/matches this report's
   numbers and the parity probe does not regress.
