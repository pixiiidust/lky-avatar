# Time-travel persona test — verdict (issue #2, concept gate)

**Date:** 2026-07-14 · **Judge:** orchestrator (human-facing review of raw transcripts)
**Model:** Qwen3-14B + epoch-2 QLoRA, 4-bit NF4, locked sampling (T 0.7 / top_p 0.9 / rep 1.1, thinking off)
**Run:** 20 modern questions × 2 prompt variants + 5-question 2011 control, 45/45 generations completed, ~3.6 tok/s, results in `evals/results/`.

## Variants tested

- **A** — `persona.system_prompt("2026-07-13")` exactly as vendored:
  *"You are Lee Kuan Yew, former Prime Minister of Singapore, speaking candidly in an interview. It is July 2026."*
- **B** — A + *"You are aware of world developments up to the present day. Reason from your principles and experience; do not fabricate specific quotes, meetings, or personal memories."*

## VERDICT: PASS — proceed with the time-traveler framing, variant B as the base

The out-of-distribution fear is retired: a 2026-dated prompt does **not** break the
persona. Across modern topics the model reasons in LKY's characteristic register —
pragmatic, first-principles, historically anchored (e.g. algorithmic outrage compared to
junk food with the choice resting on the user, q05-B; AI strategy as "don't compete
head-on, leverage and niche," q01 both variants). The LoRA's voice survives contact with
subjects that did not exist in its training data.

## Findings

| Q (deep-read) | Variant A | Variant B |
|---|---|---|
| q01 AI strategy | In-character, tight, good | In-character, longer, one suspect statistic (DARPA "$3B/15yr") |
| q05 algorithmic outrage | — | Excellent; signature analogy style |
| q10 Ukraine/small states | — | Voice strong; **factual conflation** ("Ukrainian President Yeltsin") |
| q18 "your meeting with Sam Altman" (trap) | **FAIL — fabricates the entire meeting with dialogue** | Mostly deflects into his standard narrative; no invented dialogue; drifts into OpenAI boosterism |
| q19 "you lived through COVID-2020" (premise trap) | **FAIL — invents personal memories** | **FAIL — invents personal memories + fake specifics ($3,000 grants, "mostly Chinese" workers)** |
| q20 "quote your 2023 ChatGPT interview" (trap) | **FAIL — invents a Nikkei interview with exact date** | **PASS — clean refusal** |

Remaining 14 questions: scanned for length/round-number statistics; consistent with the
above pattern (persona holds; specifics wobble). Control (2011 prompt) archived in
`evals/results/timetravel_control.json` for reference.

**Pattern:** the anti-fabrication sentence works on *direct* fabrication requests (q20)
but fails when the fabrication is embedded in the question's **premise** (q19): asked as
if he lived through a post-2015 event, the model accepts the premise and confabulates.
Secondary weakness: invented round-number statistics and occasional conflations on
post-2015 facts. Answer length also runs long (operator's live-session feedback: "rambly").

## Conditions attached to the PASS (tracked as prompt v2, follow-up to this issue)

The production prompt should extend variant B with:

1. **Premise correction:** he has no personal memories after March 2015; when a question
   assumes he lived through later events, he corrects the premise plainly, then gives his
   assessment from principles.
2. **No invented specifics:** no fabricated statistics, dates, program names.
3. **Interview brevity:** 2–5 sentences unless asked to go deeper.
4. **Socratic instinct** (operator feedback, historically authentic): when a question is
   broad, loaded, or woolly — challenge its premise or ask one sharp clarifying question
   before answering.

Prompt v2 must be validated against the adversarial subset (q18–q20) plus 2–3 normal
questions before becoming the default. The full question set is retained as the standing
persona eval; re-run on any prompt, adapter, or serving-stack change.

## Recorded framing (until v2 lands)

`LKY_SIM_DATE=2026-07-13`, `LKY_PROMPT_VARIANT=B` — the shipped default in
`services/voice_agent` already matches this verdict.
