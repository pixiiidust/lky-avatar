# FAQ — problems we hit and how we solved them

Real-time voice AI looks like a model problem but is mostly a systems
problem. These are the walls this project actually hit, in the order we hit
them. Each entry gives the technical answer, then **what this means** in
plain language, then **a simple example**.

## 1. Why did the first reply take ~10 seconds — and how did it get 30× faster?

The LLM itself was never slow; the *serving* was. The QLoRA-adapter +
4-bit-NF4 transformers path decoded at 2.47 tokens/second. The fix: merge
the LoRA into the base model and serve a Q4_K_M GGUF on llama.cpp —
80.5 tokens/second (32.6×), time-to-first-token 0.05 s, behind the same
OpenAI-compatible API so nothing downstream changed. The non-obvious part:
the standard merge (`peft merge_and_unload`) needs ~28 GB of RAM this
machine doesn't have; llama.cpp's tensor-streaming `llama-export-lora` does
the identical math with almost no RAM. A parity eval gated the swap so the
speed gain couldn't silently change the persona.

**What this means:** the model always knew what to say — it just couldn't
get the words out fast enough. "2.47 tokens/second" is roughly two words
per second, about as fast as a person speaks, with zero headroom. The
answer wasn't a better model or a bigger GPU; it was repackaging the same
model in a faster engine.

**For example:** the reply's first sentence is ~20 tokens. At 2.47 tok/s it
takes ~8 seconds before the text-to-speech can even *start* talking. At
80 tok/s that same sentence exists in a quarter of a second — the wait a
visitor feels drops from "is this broken?" to a normal conversational pause.

Full method, benchmark table, and regeneration runbook:
[`reports/serving-upgrade.md`](reports/serving-upgrade.md).

## 2. Why did saying "stop stop" not interrupt him?

The voice SDK's default *adaptive* interruption mode is an ML classifier
that judges whether your speech is a real interruption or a backchannel —
and in live testing it ate short interjections. The fix was configuration:
plain VAD interruption (any sustained speech interrupts), a 0.3 s
sustained-speech threshold instead of the default 0.5 s, and
false-interruption resume as the safety net. An automated probe measured
the result: 6/6 barge-ins interrupted, detected→silence p50 308 ms against
a ≤ 350 ms target.

**What this means:** an agent that never shuts up when talked over is
maddening, so the pipeline listens *while* it speaks and must decide:
is that noise the visitor taking the floor, or just "mm-hm, go on"? The
"smart" classifier guessed wrong on short commands. We swapped it for a
dumb-but-reliable rule — if you keep speaking for a third of a second, he
yields — and kept a recovery mechanism for false alarms (a cough pauses
him; when no words follow, he resumes).

**For example:** he's mid-monologue about housing policy and you say
"wait, wait". Before the fix, the classifier filed that under "listener
noises" and he kept going. After it, he falls silent about a third of a
second after your second "wait" registers.

Numbers and verdict: [`reports/interaction-gate.md`](reports/interaction-gate.md);
probe: [`../scripts/barge_in_probe.py`](../scripts/barge_in_probe.py).

## 3. Why did the cloned voice sound echoey — and why the American accent drift?

Two unrelated causes. The echo came from the phase-vocoder time-stretch
slowing delivery to 0.85×; the fix was speed 1.0 plus choosing the
reference clip by blind listening rounds. The accent is the one genuine
*training-data* limitation in the stack: zero-shot cloning inherits the
predominantly American speech its TTS model was trained on, and three
structured listening rounds showed reference-clip tuning had hit its
ceiling — so accent work moved to a separate fine-tuning project
(lky-voice) that trains on ~48 minutes of his real speech.

**What this means:** the echo wasn't a recording problem — it was a side
effect of digitally stretching audio to sound slower and more deliberate;
stop stretching, echo gone. The accent is different: "zero-shot" cloning
means the model imitates a voice from a short sample *without retraining*,
so it can copy timbre and cadence but keeps pronouncing words the way its
(American) training data taught it. No knob fixes that; only training on
the actual voice does.

**For example:** give a zero-shot cloner a 10-second clip and the word
"water" still comes out with an American *r*. The only cure is fine-tuning
on enough of the real speaker's speech that the model learns *his*
vowels and consonants, not just his tone.

Listening evidence: [`reports/voice-blind-test-results.md`](reports/voice-blind-test-results.md).

## 4. What dominates latency now — and what would make it faster?

Not the LLM (time-to-first-token ~0.08 s) and not speech end-pointing (a
constant 0.58 s): it's TTS synthesis of the first sentence (0.9–5.1 s,
scaling with sentence length). End-of-speech → first-audio measured
p50 3.96 s / worst 5.95 s in a live session — inside the ≤ 4 s / ≤ 8 s gate
targets. The future lever is TTS-side first-clause chunking, not a bigger
GPU.

**What this means:** the delay a visitor feels is a relay race — detect
you've finished talking, write the reply, turn the reply's opening into
audio — and the *slowest leg* sets the feel. After fixing the brain
(question 1), the slow leg became voice synthesis: the system currently
waits for a complete first sentence before it starts speaking, so long
opening sentences mean long waits.

**For example:** a measured turn: 0.58 s (detecting you finished) +
0.08 s (first words of the reply) + 3.3 s (synthesizing the opening
sentence) ≈ 4 s. If synthesis started after the first *clause* — "Let me
be quite clear," — instead of the whole sentence, the same turn would feel
roughly twice as fast with no other change.

Per-turn decomposition: [`reports/interaction-gate.md`](reports/interaction-gate.md).

## 5. Why did a "connected" session sometimes get no response at all?

Two operational gotchas, both now on the launch checklist: (a) multiple
registered agent workers — the room service load-balances new rooms across
*every* registered worker, so a stale process from an earlier session can
win the dispatch and the visitor gets a dead room; (b) stale rooms — a
fixed room name plus dispatch-on-creation means a leftover room can hold a
dead agent session. The durable fix (unique room per session, minted by the
token server) is tracked for the hosting pass (#13).

**What this means:** "connected" only means your browser reached the video
call. The AI is a *separate participant* that has to be invited in — and
the invitation goes to whichever agent process the platform picks. If a
forgotten copy of the agent from an earlier run is still registered, the
invitation can go to that zombie instead of the healthy one, and nobody
answers.

**For example:** exactly this happened during our gate session — a morning
agent process was still alive at 3:22 PM, the platform dispatched the
evening visitor's room to it, and the page said "connected" while nothing
spoke. Killing the stale process and reconnecting fixed it in seconds.

## 6. Which parts of a realtime voice pipeline are commodity, and which are still hard?

Commodity: the realtime plumbing — WebRTC transport, voice-activity
detection, turn-taking, and barge-in mechanics come from the LiveKit Agents
SDK; STT, LLM, and TTS plug into its seams behind ordinary HTTP interfaces
(which is what made this project's brain and voice independently swappable
via env vars). Still hard: conversational *feel* — end-pointing is a guess
under uncertainty, interruption semantics are subtle (question 2), and
every stage's latency stacks into the one number a visitor perceives
(question 4). Per-stage instrumentation (`LATENCY` / `INTERRUPT` log lines)
is what made that work converge.

**What this means:** the parts that used to take teams months — getting
audio flowing both ways over the internet, noticing when someone is
speaking — are now downloadable building blocks. What no SDK solves for
you is judgment: *when* to answer, *when* to shut up, and shaving the
half-seconds that separate "talking with someone" from "using a voice
assistant".

**For example:** you pause after "I think…" to gather a thought. A human
waits; a naive pipeline hears silence and barges in with an answer to half
a question. Tune it the other way and it reliably waits two full seconds —
and now every single exchange feels laggy. That trade-off, not the audio
plumbing, is where the engineering time goes.
