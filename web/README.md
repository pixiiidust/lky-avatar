# web

Single-page browser client (issues #4, #9, #12). Layout per plan §6:

- `src/livekit/` — room connection, token fetch, audio playback
- `src/avatar/` — `Live2DAvatar.ts`, `lipSync.ts`, `stateMachine.ts`
  (the state machine is a pure module — the second test seam)
- `src/components/` — `Conversation.tsx`, `Disclosure.tsx`
- `public/models/` — rigged Live2D assets (gitignored; see its README)

One page: live transcript, persistent AI-simulation disclosure label, reset
control, connection/busy/waking states. No era picker, no push-to-talk.
