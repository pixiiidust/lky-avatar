# FAQ — problems we hit and how we solved them

Real-time voice AI looks like a model problem but is mostly a systems
problem. These are the walls this project actually hit, in the order we hit
them, each with the fix and the evidence linked.

## 1. Why did the first reply take ~10 seconds — and how did it get 30× faster?

The LLM itself was never slow; the *serving* was. The QLoRA-adapter +
4-bit-NF4 transformers path decoded at 2.47 tok/s, so the first spoken
sentence took ~7 s before TTS could even start — sustained speech needs
~15+ tok/s just to keep up with the voice.

**Fix:** merge the LoRA into the base model and serve a Q4_K_M GGUF on
llama.cpp: 80.5 tok/s (32.6×), TTFT 0.05 s, model load 4.1 s — behind the
same OpenAI-compatible seam, so the voice agent needed zero code changes.
The non-obvious part: the standard `peft merge_and_unload` needs ~28 GB of
RAM this machine doesn't have; llama.cpp's tensor-streaming
`llama-export-lora` does the identical math (`W' = W + (α/r)·B·A`) with no
RAM headroom. A parity eval (adversarial persona probes, judged against the
documented reference behavior) gated the swap so speed never silently
changed the persona.

Full method, benchmark table, and regeneration runbook:
[`reports/serving-upgrade.md`](reports/serving-upgrade.md).

## 2. Why did saying "stop stop" not interrupt him?

The voice SDK's default *adaptive* interruption mode is an ML classifier
that decides whether your speech is a real interruption or a backchannel
("mm-hm", "right") — and in live testing it ate short interjections,
letting the agent talk over exactly the person trying to stop it.

**Fix:** configuration, not code. Plain VAD interruption mode (any
sustained speech interrupts), a 0.3 s sustained-speech threshold (the SDK
default of 0.5 s missed quick "wait—" interjections), and
false-interruption resume as the safety net for coughs and background
noise. Measured afterwards by an automated headless probe that joins a real
room, speaks synthesized speech over the agent, and times the silence
([`../scripts/barge_in_probe.py`](../scripts/barge_in_probe.py)): 6/6
barge-ins interrupted, detected→silence p50 308 ms against a ≤ 350 ms
target.

Numbers and verdict: [`reports/interaction-gate.md`](reports/interaction-gate.md).

## 3. Why did the cloned voice sound echoey — and why the American accent drift?

Two different causes, found by treating the operator's ear as the eval.

**Echo:** the phase-vocoder time-stretch used to slow delivery to 0.85×
smeared the audio in a way perceived as reverb/echo. Fix: speed 1.0, and
choose the reference clip by blind listening rounds instead of tweaking
knobs ([`reports/voice-blind-test-results.md`](reports/voice-blind-test-results.md)).

**Accent:** the one genuine *training-data* limitation in the stack.
Zero-shot voice cloning inherits the (predominantly American) speech its
TTS model was trained on; three structured listening rounds showed
reference-clip tuning had hit its ceiling. Rather than endless prompt and
reference tweaks, accent work was formally delegated to a separate
fine-tuning project (lky-voice: GPT-SoVITS / Chatterbox-LoRA on ~48 min of
real speech), which only touches this repo if its voice beats the current
baseline in a blind A/B.

## 4. What dominates latency now — and what would make it faster?

Not the LLM (TTFT ~0.08 s) and not STT end-pointing (a constant 0.58 s):
it's TTS synthesis of the first sentence (0.9–5.1 s, scaling with
first-sentence length). End-of-speech → first-audio measured p50 3.96 s /
worst 5.95 s across a live session — inside the ≤ 4 s / ≤ 8 s gate targets
— and at 80 tok/s the voice can never outrun the brain again.

If a future pass wants ~2 s: the lever is TTS-side first-clause chunking
(start synthesizing on the first clause instead of the first sentence), not
a bigger GPU. Per-turn decomposition:
[`reports/interaction-gate.md`](reports/interaction-gate.md).

## 5. Why did a "connected" session sometimes get no response at all?

Operational gotchas, both now part of the launch checklist:

- **Two registered agent workers.** LiveKit load-balances new rooms across
  every registered worker; a stale agent process left over from an earlier
  session silently steals the dispatch and the visitor gets a dead room.
  Check for and stop old workers before launching a new one.
- **Stale rooms.** A fixed room name plus agent-dispatch-on-creation means
  a leftover room can hold a dead agent session. Delete existing rooms
  before connecting; the durable fix (unique room per session, minted by
  the token server) is tracked for the hosting pass (#13).

## 6. Which parts of a realtime voice pipeline are commodity, and which are still hard?

Commodity: the realtime plumbing. WebRTC transport, VAD, turn-taking, and
barge-in mechanics come from the LiveKit Agents SDK rather than being
hand-rolled; STT, LLM, and TTS plug into its seams behind ordinary HTTP
interfaces — which is also what made the brain and the voice independently
swappable in this project (each swap was env-var configuration, not code).

Still hard: conversational *feel*. End-pointing (deciding the speaker has
finished) is a guess under uncertainty — too eager and the agent talks over
people, too patient and it lags. Interruption semantics are subtle (see
question 2). And every stage's latency stacks into the single number a
visitor actually perceives (see question 4). That is where this project's
engineering hours went, and the per-stage instrumentation (the `LATENCY`
and `INTERRUPT` agent-log lines) is what made those hours converge instead
of guessing.
