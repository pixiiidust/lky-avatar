# Voice Blind-Test Protocol (issue #7)

The evidence-based voice decision for Milestone 3: score self-hosted cloning
TTS candidates blind, on identical responses, from the same elder-LKY
reference clips — then benchmark where the winner runs relative to the 16 GB
brain GPU. **No choosing from one demo clip** (plan §7, Milestone 3).

Hosted cloning providers are excluded by decision #3 in the plan: their terms
require the voice owner's consent.

**GPU note:** synthesis and the placement benchmark need the GPU. Schedule
them like any other GPU issue (one model in VRAM at a time — GOAL.md); do not
run them while the brain or a training job holds the card.

---

## 0. Prerequisites

- [ ] 3–5 reference clips in `assets/voices/elder/` (6–12 s, mono WAV) with
      provenance in `assets/voices/elder/metadata.json` — produced by
      `scripts/prepare_voice_reference.py` from a rights-checked late-era
      source. See `assets/voices/README.md`.
- [ ] ffmpeg on PATH (the prep script checks and prints install steps).
- [ ] One **separate venv per engine** (repo convention: dependency conflicts
      across audio stacks are a known risk). Suggested layout:
      `services/tts/.venv-chatterbox/`, `.venv-f5/`, etc. — all gitignored.
- [ ] Working directories (all gitignored via `assets/voices/*`):

  ```text
  assets/voices/blind-test/
    raw/<engine>/response_NN.wav   # synthesis output per engine
    blind/sample_XXX.wav           # shuffled, anonymized copies
    blind/key.json                 # sample -> (engine, response) map. Do not open until scored.
    scores.csv                     # your score sheet
  ```

## 1. Candidate engines

Chatterbox is the first candidate (plan, locked choices). At least **three**
engines must be tested (issue #7 acceptance criteria); all four below is
better if install goes smoothly.

| Engine | Repo | Install (own venv each) | Notes |
|---|---|---|---|
| **Chatterbox** | <https://github.com/resemble-ai/chatterbox> | `pip install chatterbox-tts` | First candidate. Ships **PerTh watermarking built in** — satisfies the spec's watermark requirement out of the box. Zero-shot clone from a single short reference. |
| **F5-TTS** | <https://github.com/SWivid/F5-TTS> | `pip install f5-tts` | Flow-matching model; needs reference audio **plus its transcript** — transcribe each reference clip once and keep the text beside it. |
| **XTTS-v2** | <https://github.com/idiap/coqui-ai-TTS> (maintained fork of coqui-ai/TTS) | `pip install coqui-tts`, model `tts_models/multilingual/multi-dataset/xtts_v2` | **Coqui Public Model License: non-commercial.** Fine for this evaluation; flag it in the verdict if it wins. |
| **Fish-Speech** | <https://github.com/fishaudio/fish-speech> | `git clone` + `pip install -e .` per its README (checkpoint download on first run) | Strong multilingual coverage — worth testing for Malay/Mandarin/Hokkien terms. |

If an engine will not install or synthesize after ~30 minutes of effort,
record that as its result ("disqualified: <reason>") and move on — install
friction is real evidence for a self-hosted deployment.

**Watermarking:** the spec requires the output watermark preserved. Only
Chatterbox ships one built in. If another engine wins, adopting it means
adding a watermarking step (e.g. Resemble's open-sourced Perth watermarker) —
count that as a cost in the final verdict.

## 2. The fixed test script (20 responses)

Synthesize **exactly these 20 texts with every engine** — identical text,
identical reference clips. They are written in the persona's register (spec:
direct, pragmatic, historically grounded, 2–5 spoken sentences) and
deliberately stress the six scoring axes. Do not edit them between engines;
if a text must change (e.g. an engine chokes on a character), change it for
all engines and note it.

Tags: **[regional]** regional-term pronunciation, **[long]** long-sentence
stability, **[pace]** pacing/measured delivery, **[num]** numbers and dates.

1. **[pace]** You cannot wish a technology away. Artificial intelligence will
   reshape work whether we like it or not. The question for Singapore is
   whether our people are trained to use it, or displaced by those who are.
2. Social media rewards the loudest voice, not the soundest argument. I would
   not ban it. I would make sure our schools teach young people to think for
   themselves before the algorithm thinks for them.
3. **[regional]** The contest between America and China will define this
   century. Small states like Singapore do not choose sides; we make
   ourselves useful to both, and indispensable to neither's enemies.
4. **[pace]** Cryptocurrency? I am sceptical. A currency must rest on
   something — production, trust, the credit of a state. Speculation is not
   an economy. But the technology beneath it may yet prove useful.
5. Working from home suits some trades and not others. What matters is
   output, not attendance. But a society that never gathers loses something —
   discipline, cohesion, the habit of common purpose.
6. **[regional]** Water taught Singapore that survival is an engineering
   problem. We built NEWater because dependence is vulnerability. Climate
   change is the same lesson on a larger scale: adapt early, or plead later.
7. **[num]** In August 1965 we were expelled from Malaysia, with no
   hinterland, no resources, and two million people to feed. We did not waste
   time on grievance. We got on with the job.
8. **[regional]** Bilingualism was among my hardest policies. English for the
   world's business, the mother tongue — Mandarin, Malay, Tamil — for one's
   roots. I pushed Mandarin over Hokkien and the other dialects, and I would
   do it again.
9. **[regional] [num]** When we started, most of our people lived in squatter
   huts and kampongs. The HDB, funded through the CPF, gave over eighty per
   cent of Singaporeans a home they own. A man who owns his flat defends his
   country.
10. **[regional]** ASEAN works precisely because it moves slowly. Indonesia,
    Malaysia, Thailand, Vietnam — different systems, different histories.
    Consensus is frustrating, but it has kept the peace in Southeast Asia for
    two generations.
11. That is outside anything I can judge with confidence. I never had to
    decide such a question, and I will not pretend otherwise. I can tell you
    the principles I would apply — nothing more.
12. **[long]** If you ask me what made the difference between the countries
    that prospered after the war and the countries that stagnated, I will
    tell you it was not resources, nor size, nor the slogans of their
    leaders, but the quality of their institutions, the discipline of their
    people, and the honesty of their governments — and all three must hold at
    once, because any one of them failing will unravel the other two.
13. **[long]** The test of a policy is never whether it sounds compassionate
    in a speech or wins applause at an election rally, but whether, ten or
    twenty years on, the ordinary citizen — the man driving the taxi, the
    woman raising children in a three-room flat — is measurably better off
    than he or she would otherwise have been.
14. **[num]** I stepped down as Prime Minister in November 1990, after
    thirty-one years. By then our per capita income had risen from about five
    hundred dollars to over twelve thousand. Numbers are not everything, but
    they do not lie.
15. **[regional]** Merdeka meant freedom, but freedom to do what? A flag and
    an anthem do not feed anyone. Independence is the beginning of the
    examination, not the end of it.
16. **[regional]** Singaporeans call it kiasu — afraid to lose. In moderation
    it is drive; in excess it is paralysis. I preferred a people hungry to
    win over a people terrified of failing.
17. **[regional]** Deng Xiaoping was the ablest leader I ever met. He saw
    what Singapore had done, drew his own conclusions, and turned China
    around. One man, at the right moment, can bend history.
18. Meritocracy is not a slogan; it is a discipline. The moment you appoint a
    man for his connections rather than his ability, you have told every able
    man in the system that effort is pointless. Decline follows.
19. **[pace]** No. That is populism, and populism is expensive. Somebody
    always pays; the politician merely arranges for the bill to arrive after
    he has left office.
20. **[pace]** I do not expect to be loved for what I did. I expected to be
    judged by results. Singapore works. That is my answer, and history can
    make of it what it will.

### Synthesis rules

- Same reference clip(s) for every engine. If an engine accepts multiple
  references, give each engine the same set.
- Default/recommended inference settings per engine; fix the seed where the
  engine supports it. No per-sample cherry-picking, no regeneration of "bad"
  takes — a flubbed take *is* data (that's the stability axis).
- Save as `assets/voices/blind-test/raw/<engine>/response_NN.wav`
  (NN = 01–20). 4 engines × 20 = 80 files.

## 3. Blinding and randomization

The operator is also the listener, so blinding is done by shuffle-and-rename.
Run this once after all synthesis is complete (stdlib-only):

```python
# blind_shuffle.py — run from repo root: python blind_shuffle.py
import json, pathlib, random, shutil

root = pathlib.Path("assets/voices/blind-test")
files = sorted((root / "raw").glob("*/response_*.wav"))
assert files, "no synthesized files found under raw/<engine>/"
random.shuffle(files)

blind = root / "blind"
blind.mkdir(exist_ok=True)
key = {}
for i, f in enumerate(files, 1):
    name = f"sample_{i:03d}.wav"
    shutil.copy2(f, blind / name)
    key[name] = {"engine": f.parent.name, "response": f.stem}
(blind / "key.json").write_text(json.dumps(key, indent=2))
print(f"{len(files)} samples blinded into {blind}. Do NOT open key.json "
      "until scores.csv is complete.")
```

Rules:

- **Do not open `key.json` until every sample is scored.**
- Score in `sample_XXX` order (already randomized). Listen on the same
  headphones at the same volume throughout.
- Before scoring, replay one original reference clip to re-anchor your ear
  for the similarity axis; re-anchor every ~20 samples.
- Score in at most two sittings; note the split point if you take a break.
- A second listener is optional but valuable: give them the same `blind/`
  folder and a fresh score sheet; average later.

## 4. Scoring rubric (1–5 on six axes)

Score **every sample on all six axes** (the axes from issue #7). Half-points
are allowed. Anchor descriptions:

| Score | Similarity (to elder LKY) | Naturalness | Intelligibility | Pacing | Long-sentence stability | Regional-term pronunciation |
|---|---|---|---|---|---|---|
| 1 | Different person | Robotic / synthetic artifacts throughout | Multiple words unrecognizable | Rushed or dragging; unusable | Collapses: repeats, skips, garbles | Term mangled beyond recognition |
| 2 | Vaguely similar timbre only | Noticeably synthetic | A phrase needs a second listen | Wrong overall; erratic pauses | Audible degradation late in sentence | Recognizable but clearly wrong |
| 3 | Same "kind" of voice; wouldn't fool a listener | Acceptable; occasional artifacts | Everything understood, minor slurs | Serviceable but not his measured delivery | Makes it through with strain | Understandable, slightly off |
| 4 | Close; a familiar listener hesitates | Natural with rare tells | Fully clear | Measured, deliberate; near-right | Clean through long clauses | Correct with minor accent drift |
| 5 | Would pass for archival elder-LKY audio | Indistinguishable from recorded speech | Perfect clarity | His cadence: unhurried, weighted pauses | Rock-solid to the last word | Native-quality (Singapore, HDB, kampong, kiasu, Deng Xiaoping…) |

Axis-specific guidance:

- **Similarity** — judge against the reference clips, not your memory.
- **Long-sentence stability** — most informative on responses 12–13, but
  score it on every sample (a 1-sentence sample that garbles scores low too).
- **Regional terms** — most informative on the **[regional]** samples; for
  samples with no regional terms, score the axis on general proper-noun and
  loanword handling, or enter 3 (neutral) and note it.

## 5. Score sheet

`assets/voices/blind-test/scores.csv` — one row per sample:

```csv
sample,similarity,naturalness,intelligibility,pacing,stability,regional,notes
sample_001,,,,,,,
sample_002,,,,,,,
...
sample_080,,,,,,,
```

(Generate the empty rows with a one-liner:
`python -c "print('sample,similarity,naturalness,intelligibility,pacing,stability,regional,notes'); [print(f'sample_{i:03d},,,,,,,') for i in range(1,81)]" > assets/voices/blind-test/scores.csv`)

### Unblinding and the winner

Only after `scores.csv` is complete, open `key.json` and join:

1. Per engine: mean of each axis, and the grand mean across all six.
2. **Winner** = highest grand mean, subject to a floor: **no axis mean
   below 3.0** (an engine that fails intelligibility or stability outright
   is unusable however similar it sounds).
3. Tie-breaks, in order: similarity → regional-term pronunciation →
   watermark support built-in → install/operational simplicity.
4. Sanity check the gate: the winner must be an "acceptable LKY-like result"
   in your honest judgment (Milestone-5 interaction gate, criterion 2) —
   the risk register accepts "good enough"; the persona carries the demo.

## 6. Placement benchmark (VRAM beside the 14B)

Benchmark, don't assume (plan §7 Milestone 3): does the winner fit next to
the 4-bit Qwen3-14B on the 16 GB 5070 Ti?

1. Start the brain (or reuse issue #3's baseline numbers) and record
   steady-state VRAM: `nvidia-smi --query-gpu=memory.used --format=csv`.
2. With the brain still resident, in a second process start the winning
   engine and synthesize all 20 responses back-to-back. Log VRAM at 1 s
   intervals throughout:
   `nvidia-smi --query-gpu=memory.used,memory.total --format=csv -l 1 > vram.log`
3. Record: peak combined VRAM, any OOM/allocator failure, per-response
   synthesis latency, and RTF (synthesis time ÷ audio duration).
4. Repeat the 20 syntheses on **CPU** (`device="cpu"`) and record RTF.

**Verdict rules:**

| Observation | Verdict |
|---|---|
| Peak combined VRAM ≤ ~15.0 GB, no OOM across all 20, GPU RTF comfortably < 1 | **Beside the 14B on 16 GB** ✅ |
| GPU doesn't fit, but CPU RTF ≤ ~0.5 (phrase-level pipelining needs synthesis well ahead of playback) | **CPU** |
| Neither | **Second device / hosting rethink** — feed this into Milestone 6's hosting decision |

## 7. Recording the results

- Commit the outcome to `docs/reports/voice-blind-test-results.md`: per-engine
  axis means table, winner + rationale, disqualifications, placement verdict
  with the measured numbers, and any pronunciation problem-words for the
  Milestone-3 override list. Scores and numbers are committable; **audio,
  key.json, and reference metadata are not** (gitignored).
- Post the winner + placement verdict on issue #7 and tick its acceptance
  boxes.
- Do not delete `raw/`, `blind/`, or `scores.csv` locally — they are the
  evidence trail if the choice is ever revisited.
