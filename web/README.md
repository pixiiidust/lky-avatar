# web

Single-page browser client (issues #4, #9, #12; visual identity #33). Layout per plan §6:

- `src/avatar/` — avatar stack (issue #9):
  - `stateMachine.ts` — **pure** agent-events → avatar-intents module (the
    project's second test seam; no DOM/pixi/LiveKit imports)
  - `lipSync.ts` — RMS-of-played-audio lip sync (pure envelope + Web Audio
    analyser wrapper)
  - `idle.ts` — procedural breathing / blinking / head sway (pure)
  - `Live2DAvatar.ts` — pixi + pixi-live2d-display renderer, responsive
    canvas, static-image fallback
  - `demo.ts` — keyless demo driver (`?avatarDemo=1`)
- `src/transcript.ts`, `src/main.ts` — LiveKit room wiring, transcript,
  playback events, typed-note input (`lk.chat`)
- `src/lamp.ts` — **pure** studio-lamp mapping (connection + machine state +
  brain status → caption/light), the design's signature element
- `src/export.ts` — **pure** session-export serializers (issue #40): the
  JSONL eval trace (session-config header + one line per finalized turn)
  and the Markdown transcript of record. Client-side Blob downloads via the
  quiet "Export the record" affordance at the foot of the record column;
  a reference trace lives at `evals/sample_session_trace.jsonl`
- `public/models/` — rigged Live2D assets (gitignored; see its README for
  the placeholder model's license and the fetch step)

One page, staged as a broadcast interview (design: see
`docs/design-interview-studio.md`): the set (avatar + studio lamp + slate
cards) beside the transcript of record, with the persistent AI-simulation
disclosure as a bottom chyron. The state machine renders as the lamp
(`STANDBY / LISTENING / THINKING / ON AIR / FLOOR IS YOURS / OFF AIR`, plus
`IN SESSION` while the single-slot brain is busy). Visitors who cannot use
the mic can **pass a written note** — typed questions go to the agent over
the LiveKit `lk.chat` text stream and get the same spoken answer + record
entry. No era picker, no push-to-talk.

## Setup

```bash
# once per checkout: download the licensed placeholder Live2D model
python ../scripts/fetch_placeholder_model.py   # (or scripts/... from repo root)

npm install
npm run dev        # dev server
npm test           # vitest (state machine, lip sync, idle — all pure)
npm run build      # strict tsc + vite build
```

The Live2D **Cubism Core** script is proprietary and is loaded at runtime
from Live2D's official CDN (never committed/bundled — see
`src/avatar/cubismCore.ts` and `public/models/README.md`). No Live2D
rendering (e.g. CDN unreachable, no WebGL, model not downloaded) degrades to
a static-image fallback instead of crashing.

## Keyless avatar demo (`?avatarDemo=1`)

Runs the full avatar stack — state machine, Live2D rendering, RMS lip sync —
against a scripted fake agent and a locally generated speech-like tone. No
LiveKit credentials, token server, or microphone needed:

```bash
npm run dev
# open http://localhost:5173/?avatarDemo=1
```

- **▶ Run script** loops a scripted conversation: idle → listening →
  thinking → speaking (tone plays, mouth follows the audio) → **interruption
  mid-sentence** (mouth snaps shut, expression resets) → a full turn →
  a simulated **connection error** (neutral pose + visible message) →
  recovery → disconnect.
- Manual buttons inject individual events (Listening / Thinking / Speak 5s /
  Interrupt / Error / Disconnect), plus studio-chrome states for design
  review (Busy slate / Seed record / Mic-fail note — the last opens the
  pass-a-note card, whose submissions stay local in demo mode).
- The readout shows renderer mode, **FPS** (turns red below the 50 FPS
  acceptance target), machine state, and whether the mouth is live.
- What to eyeball: idle breathing + autonomous blinking + subtle sway;
  mouth moving only while the tone is audible (closing in the scripted
  mid-phrase pauses); the instant mouth-close on Interrupt; the neutral
  pose + status message on Error.

Audio starts only after the first button press (browser autoplay policy).

## Live client

`npm run dev` plus the token server and agent from the walking skeleton
(issue #4, see `services/`). The avatar is driven by:

- `lk.agent.state` participant-attribute changes (listening/thinking/…)
- agent audibility (`ActiveSpeakersChanged`) as playback started/stopped
- the state machine infers barge-in (speaking → listening while audio is
  still audible ⇒ interrupted)

Lip sync analyses the very `MediaStreamTrack` being played, so the mouth
can never run ahead of what the visitor hears.
