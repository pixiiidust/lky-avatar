# Hosting decision (issue #13)

> The choice between "works on my machine" and a link worth putting in a
> portfolio, priced from this repo's MEASURED numbers — not from vendor
> marketing. Written 2026-07-14; indicative prices checked the same day and
> cited inline (prices drift; the measured numbers don't).

## What has to be hosted

| Piece | Measured footprint | Source |
|---|---|---|
| Brain (llama-server, merged-LoRA Q4_K_M GGUF) | **~10.7 GiB VRAM**, model file 8.38 GiB, **4.1 s load → /health ready**, 80.5 tok/s p50 decode, TTFT 0.05 s p50 | [serving-upgrade.md](serving-upgrade.md) |
| Cloned-voice TTS (Chatterbox, loopback-only) | **~3.5 GB VRAM** beside the brain on one 16 GB card | docs/HANDOFF.md (2026-07-14); voice-blind-test-results.md |
| Voice agent worker (LiveKit Agents) | CPU-only process; outbound WebSocket to LiveKit Cloud | services/voice_agent |
| Token server (FastAPI) | tiny; the only inbound HTTP surface (token minting) | services/token_server |
| Web client (static Vite build) | static files; any static host/CDN | web/ |
| Realtime media (rooms, VAD, barge-in) | **not self-hosted** — LiveKit Cloud already carries it | .env.example |
| STT | Deepgram cloud (streaming) | .env.example |

Latency budget context ([interaction-gate.md](interaction-gate.md)): end-of-speech →
first-audio p50 **3.96 s**, dominated by TTS TTFB (0.9–5.1 s); the LLM is
~0.08 s of it. Any hosting shape that keeps the GPU warm preserves the
gate's PASS; anything that cold-starts the model must cover the wait
honestly in the UI.

Total GPU budget: **~14.2 GiB → a 16 GB-class card**, exactly what the demo
runs on today (RTX 5070 Ti 16 GB).

## The three candidate shapes

### (a) Serverless GPU, scale-to-zero (Runpod/Modal class)

Per-second billing while a session (or warm window) is active, $0 while
idle. Indicative prices (checked 2026-07-14): Runpod serverless flex
24 GB (RTX 4090 class) ≈ **$1.10/hr** ($0.00031/s), with cheaper 16–20 GB
tiers around $0.58/hr; Modal L4 (24 GB) ≈ **$0.80/hr**, A10G ≈ $1.10/hr.

- **Per-session cost:** a 10-minute interview ≈ $0.10–0.18 of GPU time.
  Low traffic (20 sessions/mo ≈ 3.5 GPU-hours incl. warm windows):
  **~$3–6/mo**, plus a few $/mo for persistent volume storage of the
  ~12 GB of weights (GGUF 8.4 GiB + TTS).
- **Cold start, priced honestly.** The measured 4.1 s model load assumes
  the GGUF is already on local NVMe. Serverless adds, before that: worker
  provisioning + container start (sub-second to ~12 s on Runpod
  FlashBoot-class caching, 2–4 s typical on Modal) and reading ~12 GB of
  weights from the platform volume into the container (tens of seconds at
  typical 0.5–1.5 GB/s volume throughput, unless the platform's weight
  cache is warm). Realistic first-visitor-after-a-quiet-spell wait:
  **~20–60 s**, occasionally worse. That wait MUST be covered by a
  "waking the model up" UI state (spec below) — the alternative is a
  visitor staring at a dead CONNECTING lamp.
- **Ops:** two GPU processes (llama-server + TTS) must be packaged into
  one worker image; the LiveKit agent worker must either run serverless
  too (waking on LiveKit dispatch) or sit on a tiny always-on CPU
  instance (~$5/mo) that triggers the GPU worker.

### (b) Always-on small GPU instance

Indicative prices (checked 2026-07-14, Runpod): RTX A4000 16 GB
**$0.17/hr ≈ $124/mo**; RTX A4500 20 GB $0.19/hr ≈ $139/mo; RTX 4090
community $0.34/hr ≈ **$248/mo** (secure-cloud/datacenter tiers roughly
2x). Comparable classes at Vast/Lambda sit in the same band.

- Zero cold start, simplest ops (it is exactly today's stack, on rent).
- 16 GB is precisely the measured budget — workable (it is what the demo
  runs on) but with no headroom; the honest rental spec is 20–24 GB.
- **$124–250/mo to serve a single-session demo that is idle >95% of the
  time.** At portfolio traffic this is the worst value of the three.

### (c) Home GPU + tunnel (current machine) — CHOSEN

The architecture makes this unusually clean: **media never touches the
home connection's inbound side.** LiveKit Cloud carries all WebRTC (the
agent worker and the browser both dial OUT to it); Deepgram is outbound;
TTS and the brain are loopback-only. The only things a visitor needs to
reach are the static web page and the token server.

- Static site: GitHub Pages / Cloudflare Pages, **$0**.
- Token server: exposed via **Cloudflare Tunnel (free tier)** — outbound-
  only connector, no opened ports, real TLS hostname. $0.
- LiveKit Cloud **Build tier (free): 5,000 WebRTC minutes, 1,000 agent
  minutes, 50 GB egress per month** — the binding cap is 1,000 agent
  minutes ≈ ~16 h of interviews/mo, far above portfolio traffic (the
  free allowance is a hard cap: sessions past it fail — acceptable for a
  demo, and a nice natural spend ceiling).
- Marginal cost: electricity. The loaded GPU box draws ~400–500 W → a
  10-minute session is ~$0.02 at US$0.25/kWh; leaving the stack warm
  24/7 costs roughly **$10–20/mo of electricity** (or near zero if only
  brought up for scheduled demo windows).
- Cold start after a reboot/restart is the measured **4.1 s** (local
  NVMe) — no UI state needed; the existing CONNECTING lamp covers it.

**Expected monthly cost at low traffic: ~$0 in services, ~$10–20 in
electricity.** Weaknesses, stated plainly: availability equals the
operator's machine (demo is down when the box sleeps or the GPU is
borrowed for training runs); residential upload bandwidth is a
non-factor for media (LiveKit Cloud) but the machine is a single point
of failure with no SLA.

## Decision

**Host the portfolio demo from the home GPU behind a tunnel (shape c),
now.** It is the only shape whose numbers are all measured rather than
projected, it costs ~nothing at low traffic, and it preserves the gate's
latency PASS exactly (same card, same processes). The single-session
model this issue enforces (one visitor at a time, per-IP rate limits)
fits a 16 GB single-card host by construction.

**What changes at higher traffic** (or when "always up" starts to
matter): move the GPU pair (llama-server + TTS) to **serverless
scale-to-zero (shape a)** — at 200 sessions/mo it is still only
~$30–60/mo versus $124–250/mo always-on, and the token server/web tier
is already portable (the brain is behind the OpenAI-compatible seam;
hosting was a stated portability boundary). Build the
"waking the model up" state (below) as part of that migration, not
before. Always-on (b) only wins if traffic becomes steady enough that
the serverless per-second bill approaches ~500 GPU-hours/mo — not a
portfolio-demo scenario.

## "Waking the model up" — UI spec (build only if/when serverless ships)

The #33 lamp/slate vocabulary already has room for the cold start; this
is the designed state, specified so the serverless migration ships it
with no design debate:

- **Lamp:** caption `WARMING UP`, light `pulse` (the thinking behavior),
  housing warm (`live: true`) — the studio is coming to light, not off
  air. Under `prefers-reduced-motion` the pulse degrades to `low`, as
  the lamp already does.
- **Slate card** (tone `quiet`, not trouble): caption `Warming up`,
  message: *"The studio lights are coming up — his first answer can take
  up to a minute after a quiet spell. Your microphone opens the moment
  the lamp reads LISTENING."*
- **Trigger:** the token server (which knows it just woke the worker)
  returns `202 {"detail": {"reason": "warming", "retry_after_seconds": N}}`;
  the web client polls/retries and keeps the slate up until the join
  succeeds. Same structured-refusal pattern as the busy/rate-limit
  gates this issue added (`web/src/gate.ts` extends with one more kind).
- **Honesty rule:** the message may not promise less than the measured
  cold start of the deployed platform; measure before wording.

## Trust surface (verifiable facts, current stack)

Stated here as the record for the public demo; each item is checkable in
this repo:

- **Keys never leave the server.** LiveKit/Deepgram/LLM keys live in the
  repo-root `.env`, read only by services; the browser receives a
  short-lived (15 min), single-room, non-admin JWT
  (`services/token_server/tokens.py`; tests assert the secret never
  appears in any response and grants carry no admin/create powers).
- **Microphone audio is streamed, not stored.** Mic audio flows through
  LiveKit to the agent solely for streaming STT; `STORE_AUDIO=false`, no
  LiveKit egress/recording is configured anywhere in this repo, and the
  TTS/brain services never see audio in (text in, audio out).
- **Transcripts live only in the visitor's browser.** Rendering is
  client-side; `STORE_TRANSCRIPTS=false` and the brain's content logging
  is off by default (`BRAIN_LOG_CONTENT=0`). The only way a transcript
  leaves the page is the visitor's own export (issue #40 — a client-side
  Blob download; nothing is sent anywhere).
- **Visible reset.** "End the interview" disconnects; the wrap card
  offers the export, then "Start afresh" clears the record and returns
  to the pre-connect state (issue #13, `web/src/reset.ts`).
- **Disclosure is persistent.** The locked AI-simulation wording renders
  as a permanent chyron; on small screens it folds — never dismisses
  (issue #33, `web/src/chyron.ts`).
- **Every generated voice sample is watermarked.** Chatterbox embeds
  Resemble's PerTh perceptual watermark at generation; the TTS server
  never strips or re-synthesizes it and labels responses
  `X-Watermark: perth` (`services/tts_server/app.py`).
- **Honest residuals.** Single-session enforcement has a documented race
  (two tokens minted in the same instant can both pass — accepted at
  this scale; the second session queues on the brain, nothing breaks).
  The per-IP rate limiter is in-process (single worker) and resets on
  restart; keys and enforcement all remain server-side either way.

## Sources (indicative pricing, checked 2026-07-14)

- Runpod pricing: <https://www.runpod.io/pricing> (serverless flex 24 GB
  ≈ $1.10/hr; pods: A4000 $0.17/hr, A4500 $0.19/hr, 4090 community
  $0.34/hr); comparison: <https://northflank.com/blog/runpod-gpu-pricing>
- Modal pricing: <https://modal.com/pricing> (L4 $0.000222/s ≈ $0.80/hr,
  A10G ≈ $1.10/hr)
- Serverless cold-start behavior: Runpod FlashBoot
  <https://www.runpod.io/blog/introducing-flashboot-serverless-cold-start>
  (sub-second when cache-warm, 6–12 s for large containers otherwise);
  Modal typical 2–4 s container starts
  <https://www.beam.cloud/blog/top-serverless-gpu-providers>
- LiveKit Cloud plans: <https://livekit.com/pricing> (Build tier free:
  5,000 WebRTC min, 1,000 agent min, 50 GB egress; hard cap)
- Cloudflare Tunnel (free with a Cloudflare zone):
  <https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/>
