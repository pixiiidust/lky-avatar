# Baseline brain benchmark (issue #3)

> The serving yardstick: every later change to the brain's serving stack
> (quantization, engine, drivers, hosting) is measured against this run by
> re-running `scripts/benchmark_brain.py` and diffing the JSON in
> `evals/results/`.

- **Benchmark JSON:** `evals/results/benchmark_baseline_<git-short-sha>.json`
- **Run command:** `wsl -d Ubuntu-24.04 -- bash -c '~/uns/bin/python .../scripts/benchmark_brain.py --git-sha <sha>'`
- **Run date:** _(fill from JSON `metadata.run_at`)_
- **Git SHA:** _(fill)_
- **Prompt set:** `evals/benchmark_prompts.json` v1 — 24 prompts (short factual / long reflective / modern + adversarial; max_new_tokens 80 and 320 regimes; modern prompts shared verbatim with the issue #2 time-travel eval)

## Headline numbers

| Metric | Value |
|---|---|
| Model + adapter load (cold process, warm HF cache) | _(fill)_ s |
| VRAM after load (allocated) | _(fill)_ GiB |
| Peak VRAM over run (allocated / reserved) | _(fill)_ / _(fill)_ GiB |
| TTFT p50 / p95 | _(fill)_ / _(fill)_ s |
| Decode tok/s p50 / p95 | _(fill)_ / _(fill)_ |
| Overall tok/s p50 / p95 | _(fill)_ / _(fill)_ |
| Failure rate | _(fill)_ (n = _(fill)_ prompts) |

### By answer-length regime

| Regime (max_new_tokens) | TTFT p50 (s) | Decode tok/s p50 | Generation p50 (s) |
|---|---|---|---|
| 80 (spoken-short) | _(fill)_ | _(fill)_ | _(fill)_ |
| 320 (product default cap) | _(fill)_ | _(fill)_ | _(fill)_ |

## Environment

| | |
|---|---|
| GPU | _(fill — expected: NVIDIA GeForce RTX 5070 Ti, 16 GB)_ |
| torch / CUDA | _(fill — expected: 2.12.1+cu130)_ |
| transformers / peft / bitsandbytes | _(fill)_ |
| Quantization | bitsandbytes 4-bit NF4, bfloat16 compute |
| Model | Qwen/Qwen3-14B + `sjsim/lky-qlora` epoch-2 adapter |
| Sampling (locked) | enable_thinking=false, temp 0.7, top_p 0.9, rep_penalty 1.1 |

## Known bottleneck: bitsandbytes NF4 decode speed

This baseline is expected to confirm what the orchestrator probe (2026-07-13)
already measured on this stack: **decode throughput of roughly 2.3–3.15
tok/s**. That is an inherent property of bitsandbytes NF4 dequantize-per-matmul
decoding on this GPU/driver stack — `use_cache` is confirmed on, peak
allocation is healthy (~10.5 GiB), and load time (~35 s warm cache) and VRAM
(~10.9 GiB after load) are fine. It is not a bug in this repo's serving code.

Consequence: at ~2.5 tok/s, a 320-token answer takes ~2 minutes of generation.
The plan's interaction targets (end-of-speech → first-audio p50 ≤ 4 s / p95
≤ 8 s, plan §"Decision gates") survive only because TTS streams sentence-by-
sentence off the first tokens — but sustained speech needs roughly **15+
tok/s** (comfortable speaking rate plus pipelining headroom) or the voice will
outrun the brain mid-answer. This baseline exists so the fix can be measured,
not guessed.

### Documented remedy options — explicitly OUT OF SCOPE for issue #3

Recorded here so the follow-up serving issue starts from the measured
baseline; none of these are implemented or benchmarked in this issue:

1. **Merged-LoRA GGUF via llama.cpp** — merge the epoch-2 adapter into the
   base weights, quantize to GGUF (e.g. Q4_K_M), serve with llama.cpp /
   llama-server. Typically 5–10x bnb-NF4 decode on consumer GPUs; requires a
   persona-regression pass (spec: any serving/quantization change re-runs the
   eval before shipping).
2. **vLLM (plan hosting Profile B — always-on GPU class)** — serve the base
   model + LoRA on vLLM with its quantization options. The strongest fit for
   the hosted/always-on deployment profile; heavier VRAM footprint, so on the
   local 16 GB card it needs careful quantization choices.

Both keep the Brain API's OpenAI-compatible contract (the hosting-portability
boundary), so downstream components are untouched by whichever wins.

## Notes / anomalies

_(fill after the run: warmup effect size, any failed prompts, TTFT outliers,
observations about 80- vs 320-token regimes, deviation from the probe
numbers)_
