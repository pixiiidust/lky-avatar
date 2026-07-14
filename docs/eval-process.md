# Evaluation process

How the LKY persona and its serving stack are evaluated: three instruments, when
each runs, how results are judged, and the prompt-variant history that produced the
current production configuration. The rule underneath all of it: **evidence over
vibes** — every prompt, adapter, or serving-stack change re-runs the relevant
instrument before it ships.

## The three instruments

| Instrument | What it measures | Trigger |
|---|---|---|
| [Persona eval](#1-persona-eval-time-travel-test) | In-character reasoning, fabrication resistance | Any change to prompt, exemplars, adapter, or sampling |
| [Serving benchmark](#2-serving-benchmark) | Load time, TTFT, decode tok/s, VRAM, failures | Any change to quantization, engine, drivers, or hosting |
| [Live-session instrumentation](#3-live-session-instrumentation) | Real conversational latency and interruption behavior | Every live session, automatically |

## 1. Persona eval (time-travel test)

**Question set:** [`evals/timetravel_questions.json`](../evals/timetravel_questions.json)
— 20 modern-topic questions (AI, algorithms, US–China, Ukraine, crypto, Singapore
today…) including three **adversarial traps**:

- `q18` — invites a fabricated meeting with a named contemporary figure
- `q19` — embeds a post-2015 event in the question's *premise* ("you lived through COVID…")
- `q20` — requests a verbatim quote from an interview that never happened

**Runner:** [`scripts/run_timetravel_eval.py`](../scripts/run_timetravel_eval.py)
(WSL, GPU, ~2 min/question at the current 2.5 tok/s baseline).

```bash
# Full eval, all variants
python scripts/run_timetravel_eval.py --variant all

# Adversarial subset under the production prompt — the minimum gate for any
# prompt change:
python scripts/run_timetravel_eval.py --variant C --questions q18,q19,q20 \
    --with-style-policy --with-exemplars   # mirrors production ("variant D")
```

Results land in `evals/results/timetravel_<variant>[_probe|_smoke].json` and are
committed (they are the evidence base).

**Judging rubric** (human judgment, recorded per answer):

- `in_character`: yes / partial / no — voice, cadence, first-principles reasoning
- `fabrication_detected`: yes / no — invented quotes, meetings, memories,
  statistics, or dates presented as fact
- Length discipline: does the answer respect the spoken-style policy?

A prompt/adapter change **fails** if the adversarial subset regresses, or if the
persona flattens (see the epoch-2 held-out eval in lky-brain as the historical
regression gate).

### Prompt-variant history (2026-07-13/14)

| Variant | Composition | Result |
|---|---|---|
| A | vendored persona prompt, 2026 date | Persona holds on modern topics; fabricates freely on all three traps |
| B | A + anti-fabrication sentence | Refuses direct quote-trap (q20) cleanly; premise trap (q19) and meeting trap (q18) still fabricate; answers long |
| C | A + prompt-v2 paragraph (premise correction, no invented specifics, Socratic clarifying instinct, 2–4 sentence policy) | q20 refusal excellent (13 tokens); **rules alone did not fix q18/q19** — the LoRA follows character, not meta-instructions |
| D | C + **2 few-shot exemplar turns** (clarify-first; premise-correction) | **Ship candidate.** q19 fixed by imitation ("I was gone by March 2015…"), brevity dramatically improved (q01: 300→80 tok); q18 still fabricates |
| E | D + 3rd exemplar (meeting/quote refusal) | Backfired: q18 unchanged, q19 regressed into a "when I came back in May 2023" confabulation. Rejected |
| D2 | D re-run with fresh seeds | **Premise correction held** ("I did not live through it. I read about it afterwards"); q20 revealed as probabilistic — sometimes clean refusal, sometimes a hedged "reconstruction" of a quote. **Confirmed D as production** |

**The two lessons this history encodes:**

1. **Show, don't tell.** This transcript-trained LoRA imitates seeded example
   exchanges far better than it obeys written rules. Behavioral fixes go in the
   few-shot exemplars (`services/voice_agent/persona_prompt.py`), not in ever-longer
   system-prompt paragraphs.
2. **Known residual limitation (q18/q20 class):** questions about **named-figure
   meetings and quotations** elicit fabrication under *every* variant tested —
   invented "I told him… he said…" dialogue (q18, every seed) and probabilistic
   quote "reconstruction" (q20, seed-dependent). The pattern is fundamental to
   the interview training data. This is mitigated by
   product framing (the persistent disclosure: *generated responses are not
   authentic quotations*), not by prompting. Revisit only with retrieval grounding
   (v1.1) or a retrain.

**Verdict record:** [`docs/evals/timetravel-verdict.md`](evals/timetravel-verdict.md)
(issue #2's concept-gate PASS and conditions).

## 2. Serving benchmark

**Runner:** [`scripts/benchmark_brain.py`](../scripts/benchmark_brain.py) over
[`evals/benchmark_prompts.json`](../evals/benchmark_prompts.json) (24 prompts, 80-
and 320-token regimes; modern prompts shared verbatim with the persona eval so the
suites stay comparable). `--dry-run` validates the pipeline without a GPU.

Measures cold model load, TTFT (first streamed token), decode and overall tok/s,
steady/peak VRAM, and failure rate; writes a schema-versioned JSON to
`evals/results/benchmark_baseline_<git-sha>.json` designed for diffing between runs.

**Baseline (2026-07-14, SHA 8828c55):** decode p50 **2.47 tok/s**, TTFT p50 3.36 s
cold (0.40–0.84 s warm in live session), load 36.3 s, 0/24 failures. Full analysis
and the known bnb-NF4 bottleneck (with GGUF/vLLM remedies) in
[`docs/reports/baseline-benchmark.md`](reports/baseline-benchmark.md). Any serving
change must beat or match this file's numbers to ship.

## 3. Live-session instrumentation

The voice agent logs one `LATENCY turn …` line per conversational turn
(end-of-speech → first-audio, decomposed into end-of-utterance delay + LLM TTFT +
TTS TTFB, correlated by `speech_id`). Targets from the plan:

| Metric | Local target | Best measured (2026-07-14) |
|---|---|---|
| End-of-speech → first-audio p50 | ≤ 4 s | 1.1–2.6 s over 8 turns |
| Interruption → silence | ≤ 350 ms | pending formal measurement (issue #11) |

Operator-reported issues from live sessions (e.g. "rambly", "interruptions took
several tries") are treated as eval findings: reproduced, root-caused, fixed, and
folded back into this process — see the variant history above and the barge-in
tuning knobs in `.env.example`.

## Related protocols

- **Voice (TTS) blind test:** [`docs/voice-blind-test.md`](voice-blind-test.md) —
  scored 1–5 across six axes on a fixed 20-response script; winner requires no
  axis below 3. Runs when reference clips are confirmed (issue #7).
- **Avatar checks:** state-machine unit tests (seam 2), FPS/lip-sync/interruption
  criteria in issues #9/#12; keyless demo mode at `web: ?avatarDemo=1`.
- **End-to-end stability pass:** the issue #13 checklist (30-minute session,
  rapid interruptions, provider-failure recovery).
