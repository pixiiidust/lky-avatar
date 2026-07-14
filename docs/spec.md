# Spec: LKY Avatar — Time-Traveler Reasoning Demo

> Derived from [`lky-avatar-plan.md`](lky-avatar-plan.md) (2026-07-13). The plan holds the
> milestones, sequencing, costs, and risk register; this spec holds the product
> definition, user stories, and implementation/testing decisions for the v1 release.

## Problem Statement

Lee Kuan Yew's reasoning — his first principles, pragmatism, and rhetorical style — is
locked away in static archives and a fine-tuned model (`lky-brain`) that can only be
reached through a developer terminal. There is no way for an ordinary person to *converse*
with that reasoning: to ask how he would think about a modern question — AI, today's
geopolitics — and hear an answer in his manner of speaking, delivered by a present,
expressive figure. Existing interfaces (text terminal, plain chatbot) lose the qualities
that make the persona compelling: the voice, the presence, the natural turn-taking of a
real interview.

## Solution

A web app where a visitor speaks naturally with a simulated elder Lee Kuan Yew,
"time-traveled" to the present day: aware of the modern world, reasoning about it from his
formed worldview. The visitor talks; a live transcript appears; LKY answers in a cloned
elder voice within a few seconds, speaking before his full answer is even generated; a
semi-realistic Live2D avatar lip-syncs, blinks, and breathes; the visitor can interrupt at
any moment and be heard. A persistent label makes clear that everything — voice, words,
face — is an AI-generated simulation, and the openly counterfactual framing (a man
answering questions about a world he never saw) reinforces that honesty.

The existing epoch-2 LoRA on Qwen3-14B remains the reasoning core. The product is one
persona, one voice, one avatar — no era selection.

## User Stories

### Conversation

1. As a visitor, I want to open one web page and start talking immediately, so that trying the demo requires no setup, account, or instructions.
2. As a visitor, I want to speak naturally without push-to-talk, so that the conversation feels like an interview rather than a walkie-talkie.
3. As a visitor, I want to see an interim transcript of my words while I am still speaking, so that I trust the system is hearing me correctly.
4. As a visitor, I want LKY to begin answering within a few seconds of my finishing, so that the exchange feels conversational rather than like submitting a form.
5. As a visitor, I want his spoken answer to begin before the full response is generated, so that I am never staring at a silent screen while text piles up.
6. As a visitor, I want to interrupt him mid-answer and have him stop almost immediately, so that I can steer the conversation the way I would with a person.
7. As a visitor, I want the conversation to continue coherently after I interrupt, with the system remembering only what I actually heard, so that follow-ups make sense.
8. As a visitor, I want short, spoken-style answers (a few sentences) by default, so that the exchange stays a dialogue rather than a lecture.
9. As a visitor, I want a visible reset control, so that I can start a fresh conversation at any time.
10. As a visitor, I want the session to survive a brief network hiccup, so that one dropped packet doesn't kill a good conversation.

### Persona and reasoning

11. As a visitor, I want to ask about modern topics — AI, social media, today's geopolitics — and receive answers reasoned from LKY's principles, so that I experience how he *would* think, not just what he once said.
12. As a visitor, I want his answers to carry his characteristic style — direct, pragmatic, historically grounded — so that the persona feels authentic rather than generic.
13. As a visitor, I want him to admit uncertainty naturally when a question is outside anything his worldview can address, so that the simulation stays credible.
14. As a visitor, I want him to never invent specific quotes, meetings, or memories, so that I am not misled by fabricated history delivered confidently.
15. As a history enthusiast, I want to ask about his actual era — 1965, merger and separation, housing, bilingualism — and get answers consistent with his known positions, so that the demo rewards knowledgeable users too.

### Voice and avatar

16. As a visitor, I want to hear an elder-LKY-like voice with his measured delivery, so that the answer lands with the gravitas of the persona.
17. As a visitor, I want regional terms — Singapore, PAP, HDB, ASEAN, Malay/Mandarin/Hokkien words — pronounced correctly, so that the voice doesn't break the illusion on the words that matter most.
18. As a visitor, I want the avatar to lip-sync to the audio I'm hearing, blink, and breathe, so that the figure feels present rather than like a static picture.
19. As a visitor, I want the avatar to visibly react to the conversation state — attentive while I speak, reflective while thinking, animated while speaking, immediately silent and still-mouthed when interrupted — so that I always know whose turn it is.
20. As a visitor, I want the avatar's mouth fully closed during silence, so that the figure never looks broken or possessed.
21. As a visitor on an unsupported or low-power browser, I want a graceful static-image fallback, so that the demo degrades rather than crashes.

### Trust and disclosure

22. As a visitor, I want a persistent, unmissable label stating this is an AI-generated simulation and not authentic LKY audio or statements, so that I am never deceived about what I'm hearing.
23. As a visitor, I want the generated transcript displayed beside the audio, so that I can verify what was actually said and quote the *simulation* accurately.
24. As a member of the public (or of LKY's family or the Singapore government), I want the demo to claim no endorsement and present nothing as a real quotation, so that the simulation cannot be mistaken for, or misused as, the man's actual words.
25. As a privacy-conscious visitor, I want my microphone audio discarded by default and a clear way to end and delete my session, so that trying a voice demo doesn't mean donating my voice.

### Operations (operator = the developer running the showcase)

26. As the operator, I want the brain reachable only through an OpenAI-compatible API, so that I can move it between my home GPU and cloud hosting without changing anything downstream.
27. As the operator, I want the cloned voice callable only by the agent — never as a public text-to-speech endpoint — so that nobody can make LKY's voice say arbitrary text.
28. As the operator, I want the TTS watermark preserved in all output audio, so that generated speech remains detectable as synthetic.
29. As the operator, I want one live conversation at a time with a polite "LKY is speaking with someone" state for other visitors, so that a 16GB-class deployment never melts under concurrency.
30. As the operator, I want an honest "waking the model up" state during serverless cold starts, so that a visitor's first impression is anticipation rather than a broken page.
31. As the operator, I want per-turn latency timestamps recorded (speech end, first token, first audio, playback, interruption-to-stop), so that I can tune the pipeline against measured numbers instead of feel.
32. As the operator, I want API keys held server-side and LiveKit access tokens minted short-lived per session, so that publishing the demo doesn't publish my accounts.
33. As the operator, I want sessions rate-limited, so that one visitor cannot monopolize or bankrupt the showcase.
34. As the operator, I want the persona's regression eval runnable on demand, so that any change to prompt, serving stack, or quantization can be checked against the epoch-2 baseline before shipping.
35. As the operator, I want voice-reference rights and processing recorded in local metadata (never committed), so that the provenance of the cloned voice is always documented.

## Implementation Decisions

- **Separate repo.** `lky-avatar` consumes `lky-brain`; the training repo is never
  modified. Coupling is exactly two things: the epoch-2 adapter pulled from HuggingFace at
  runtime, and vendored persona/prompting logic verified once for parity against
  lky-brain's terminal output.
- **Time-traveler persona frame.** The system prompt sets the present date and instructs:
  reason from your principles and experience; do not fabricate specific quotes, meetings,
  or memories. This prompt rule — plus the standing eval — is v1's anti-fabrication
  mechanism; there is no retrieval in v1. An out-of-distribution check (present-day date,
  modern questions) gates the concept before any other build work; fallback is a fixed
  ~2011 date.
- **Brain serving.** Qwen3-14B + epoch-2 LoRA, 4-bit NF4, plain Transformers + PEFT
  (no Unsloth at inference), loaded once in a long-running process. Sampling locked:
  `enable_thinking=false`, temperature 0.7, top_p 0.9, repetition_penalty 1.1. Spoken
  answers default short (~2–5 sentences, ~320 max tokens). Concurrency: one generation;
  excess requests rejected, surfaced as the busy state.
- **Brain API contract.** OpenAI-compatible chat-completions with SSE streaming, plus
  health and model-listing endpoints. Cancellation mid-stream aborts generation and frees
  GPU resources. This contract is the hosting-portability boundary and the primary test
  seam.
- **Orchestration.** LiveKit room + Python agent: VAD, endpointing, turn-taking, and
  barge-in come from LiveKit rather than bespoke code. Interruption is one atomic
  operation — cancel LLM generation, flush the TTS queue, stop browser playback — and
  conversation history keeps only text the user actually heard.
- **Speech-to-text.** Hosted streaming provider via LiveKit, with interim transcripts.
  Custom vocabulary/pronunciation hints for regional terms where supported. Raw
  microphone audio is not stored.
- **Text-to-speech.** Self-hosted open-weights voice cloning (Chatterbox first candidate;
  winner chosen by blind test) behind a small provider interface so engines are swappable.
  Hosted cloning providers are excluded: their terms require the voice owner's consent.
  One elder voice cloned from late-era reference clips. LLM output is segmented at
  punctuation into ~8–24-word phrases; synthesis is pipelined ahead of playback; the queue
  cancels instantly on interruption. Output watermark preserved; the TTS service is
  reachable only by the agent. Text-only fallback if synthesis fails.
- **Avatar.** Live2D Cubism for Web. Art is AI-generated (semi-realistic, dramatized
  style), layer-separated and rigged DIY; a licensed placeholder model carries all
  development until the interaction gate passes, and remains the shippable fallback if
  rigging stalls. Lip sync v1 drives mouth openness from the RMS of the *played* audio
  (Web Audio analyser) — never from generation-side timing alone — so the mouth can never
  move out of step with what the visitor hears, and closes the instant playback stops.
- **Avatar state machine.** A pure module mapping agent events to avatar states —
  the second test seam. From the plan (decision-precise, so inlined):

  ```text
  states: idle | listening | thinking | speaking | interrupted | error
  interrupted ⇒ mouth closes immediately, expression resets
  error       ⇒ neutral pose + visible status message
  ```
- **Frontend.** Single page: conversation view with live transcript, persistent
  disclosure label, reset control, connection/busy/waking states. No era picker, no
  push-to-talk. Static hosting; all secrets server-side; LiveKit tokens minted by a small
  server endpoint.
- **Environments.** Separate Python environments per service (brain inference / agent /
  TTS) to avoid dependency conflicts. Brain inference runs under WSL2 locally; deployment
  targets native Linux.

## Testing Decisions

- **Philosophy.** Test external behavior at the agreed seams; never implementation
  details. Anything behind a seam (model loading, tokenizer plumbing, rig internals) may
  change freely without touching tests.
- **Seam 1 — brain API over HTTP** (primary). All persona and serving behavior is tested
  as a client: streaming chunks arrive incrementally; cancellation mid-stream stops
  generation and frees resources; token limits enforced; sampling defaults applied;
  concurrent request rejected while one is active; health endpoint truthful. The persona
  regression suite runs through this same seam: the lky-brain held-out eval (prior art —
  the score must not fall below the epoch-2 baseline) plus the modern-question set
  asserting in-character reasoning, no fabricated quotes/meetings/memories, and natural
  admission of uncertainty.
- **Seam 2 — avatar state machine as a pure module.** Given sequences of agent events,
  assert emitted avatar states and parameters: interruption closes the mouth immediately;
  silence means zero mouth movement; error yields neutral pose. No browser, no rig, no
  audio required.
- **Not unit-tested by design.** LiveKit transport, STT accuracy, TTS quality, lip-sync
  feel, and end-to-end latency are perceptual or integration concerns covered by the
  plan's protocols instead: scripted benchmark runs (per-turn timestamp instrumentation),
  the ~30-prompt STT test set (WER + proper-noun accuracy), the blind voice-scoring
  protocol, and the stability pass (30-minute session, 20 turns, five rapid interruptions,
  provider-failure recovery, reconnect). Mocking these providers would be high-effort,
  low-signal.
- **Prior art.** The codebase is greenfield; the only inherited test asset is lky-brain's
  held-out persona evaluation, which becomes the regression gate here.

## Out of Scope (v1)

- **Retrieval and the source panel.** Deferred to v1.1, reframed as an
  "how he actually reasoned about analogous topics" enrichment panel — not fact-grounding.
- **Era selection** in any form: no era picker, no age-variant voices or avatars, no
  date-filtered retrieval machinery.
- **Hosted voice cloning** (ToS-blocked for a real person's voice) and any public
  text-in/voice-out endpoint.
- **Multi-session concurrency**; v1 is single-conversation with a busy state.
- **Local/offline STT** (faster-whisper fallback is v1.1).
- **Word-aligned or viseme lip sync**; v1 ships RMS-driven mouth openness.
- **LoRA retraining**; epoch-3 adoption requires a new evaluation first.
- **Mobile-first polish**; desktop is the target, mobile gets the graceful fallback.

## Further Notes

- The plan's decision gates govern spending: no serious rigging hours before the
  interaction gate (brain stable + voice acceptable + latency targets met with the
  placeholder), and the hosting decision waits for measured VRAM/latency numbers.
- Sequencing is walking-skeleton-first: a full stock-parts voice loop exists from day
  one, and every subsequent milestone swaps a real component into a working demo. The
  spec's user stories are therefore satisfiable incrementally — the demo is never more
  than one milestone away from demonstrable.
- The disclosure requirements in this spec are product requirements, not copy polish;
  the counterfactual framing only stays honest while the label stays persistent.
- This spec was published to `docs/` per project convention; no issue tracker exists for
  this repo yet. If one is adopted, this document maps to a single `ready-for-agent`
  epic with the user stories as its checklist.
