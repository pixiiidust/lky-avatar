# Interview-studio design plan (issue #33)

The written plan required by #33, committed before implementation. Everything the visitor
sees derives from three artifacts this project already owns: the **1990 SBC studio
broadcast** (the voice source), the **printed transcript / Hansard tradition** (the
corpus), and the **chosen portrait** (light-grey suit, oxblood-and-navy striped tie,
soft mottled grey backdrop — `assets/raw anime/default expression.png`).

**Premise.** The visitor has not opened a chat app; they have walked onto a television
set where an interview is already prepared. Two planes exist at once: the **set** (him,
live, spatial — canvas, lamp, slate) and the **record** (his words, accumulating as
print). The page's one job is to get the visitor talking to him; everything else stays
quiet.

## 1. Tokens

Five named colors, all sampled from or keyed to the portrait. Oxblood is the *only*
accent anywhere on the page. Dark mode is the same studio with the house lights dimmed —
warm blacks and lit-paper greys, never inverted navy.

| token       | light      | dark       | source & role                                                        |
| ----------- | ---------- | ---------- | -------------------------------------------------------------------- |
| `--set`     | `#E6E3DE`  | `#211F1D`  | the mottled studio backdrop → page/set background                     |
| `--paper`   | `#F2F0EB`  | `#2A2724`  | the printed record's stock → record column, note card, slate cards    |
| `--ink`     | `#232C42`  | `#D9D4CA`  | the tie's navy stripe → all text (dark mode: paper lit by a desk lamp)|
| `--suit`    | `#B9BEC6`  | `#4A4740`  | the suit's cool grey → rules, borders, disabled chrome                |
| `--oxblood` | `#7E2530`  | `#C2454E`  | the tie's red → the lamp, live/active elements, focus rings. Nothing else may use it. |

Derived, not named: translucent tints of the above (e.g. `--ink` at 55% for secondary
text, `--oxblood` glows for the lamp face). No pure white, no pure black anywhere.

## 2. Type roles

| role | face | rationale |
| ---- | ---- | --------- |
| **The record** — his words, the record's headings | **Literata** (variable, optical sizes) | a book/memoir face commissioned for long-form reading; humanist serif with real print presence — his speech is set as typeset paragraphs of record, never bubbles |
| **The interviewer & the chrome** — visitor questions, UI, buttons, hints | **Archivo** (variable) | a quiet grotesk with 19th-century foundry roots; the visitor's finalized questions set smaller and italic — the interviewer is not the star |
| **The slate** — lamp captions, chyron, eyebrows, speaker attributions | Archivo again, in letterspaced caps at small sizes | broadcast caption vocabulary; one family doing two registers keeps the chrome quiet |

Both are OFL, self-hosted via `@fontsource-variable/*` (no CDN — the app must work
offline-ish and #13 hosting stays self-contained). Scale: record body 1.0625rem/1.65;
record display (his name) uses Literata's opsz axis; slate captions 0.6875rem caps with
+0.14em tracking.

## 3. Layout — (B) split set, justified

```
+----------------------------------------------------------+
| eyebrow / programme slate            (set)   |  THE RECORD|
|                                              |  ----------|
|        [ avatar, full column height ]        |  LEE  He...|
|                                              |  (serif    |
|        [==== studio lamp ====]               |   record)  |
|        [ begin-the-interview control ]       |  YOU  ital.|
|        [ slate card: busy / error ]          |  [pass-a-  |
|                                              |   note]    |
| [chyron: locked disclosure, full width, persistent]       |
+----------------------------------------------------------+
```

Chosen over (A) center stage because the interview produces two simultaneous artifacts —
the live set and the printed record — and a split maps each to its own plane instead of
forcing the record to scroll underneath the subject. The avatar owns a full-height column
(~55% of the viewport) at every common desktop size, so he is unambiguously the focal
point; the record reads as a galley of print beside him. The lamp sits **on the set,
beneath the canvas**, like studio furniture — not in a toolbar. The chyron runs the full
width of the bottom edge: a lower-third that belongs to the broadcast frame, unmissable
without being an apology banner.

Mobile: the set stacks above the record (avatar keeps ≈45vh so he stays focal), the
chyron stays pinned to the bottom edge, the note control remains reachable beneath the
record. The static-portrait fallback (no WebGL) inherits the same set styling, so the
identity survives degradation.

**The chyron fold (operator revision, 2026-07-14).** On a phone the full notice is a
five-line slab holding the bottom of the screen for the whole interview. So, on small
viewports only, once the visitor has **engaged** — first connect, or a first turn on the
record — the chyron folds to a thin one-line slate pill: the oxblood tab,
`FICTIONAL SIMULATION` in slate caps, and an expand affordance. This is a **fold, never a
dismissal**: the pill is persistent at the bottom edge, and expanding it restores the
operator's locked wording byte-for-byte. The visitor meets the full notice before they
have done anything; the pill only earns its place after the interview has their
attention. The affordance is a real `<button>` (focusable; Enter/Space toggles;
`aria-expanded`/`aria-controls` carry the state), styled as the same slate slab reduced
to its caption — a broadcast control, not a cookie-banner dismiss. State swaps **cut**
like broadcast slates — no animation at all — so `prefers-reduced-motion` is respected by
construction. Desktop never folds. The rule lives in a pure module
(`web/src/chyron.ts`, tested in `chyron.test.ts`): mode is only ever `full` or `pill`;
there is deliberately no hidden state.

## 4. Signature element — the studio lamp

One physical-feeling indicator replaces all debug-y status text: a lamp housing with a
glass face and an engraved caption, glowing in the single accent. The state machine's six
states are expressed as **light behavior + broadcast/parliamentary vocabulary**, not as
six colors:

| machine state | light                          | caption          |
| ------------- | ------------------------------ | ---------------- |
| idle          | unlit                          | `STANDBY`        |
| listening     | steady low glow                | `LISTENING`      |
| thinking      | slow breathing pulse           | `THINKING`       |
| speaking      | full glow                      | `ON AIR`         |
| interrupted   | sharp cut to low               | `FLOOR IS YOURS` |
| error         | unlit, housing dimmed          | `OFF AIR`        |

Connection chrome borrows the same vocabulary (`CONNECTING…` unlit while joining;
`IN SESSION` while the single-slot brain is busy with someone else). `FLOOR IS YOURS`
and `IN SESSION` are deliberately parliamentary — the corpus's own register. The glow is
opacity/box-shadow on a composited layer only (no canvas repaints; the ≥50 FPS budget is
measured, not assumed). `prefers-reduced-motion`: pulses become static levels.

Busy and error render as **slate cards** on the set (paper stock, letterspaced slate
caption, one sentence of ink), matching the lamp's caption — same identity, no red
banners.

## 5. Transcript as record

- His speech: `LEE` attribution in slate caps, then Literata paragraphs. Interim text
  (still being spoken) sets at reduced ink; it settles to full ink when final —
  captions becoming print.
- The visitor: `YOU` attribution, Archivo italic, smaller, inset — an interviewer's
  note in the margin of the record. Interim speech is lighter still and resolves into
  the record when finalized.
- No bubbles, no avatars-in-rows, no timestamps. A single column of print with a
  `TRANSCRIPT OF RECORD` running head.

## 6. Passing a note (typed input, operator addition 2026-07-14)

For visitors who cannot use the mic, a quiet affordance under the record: **"Pass him a
written note"**. It expands into a note card on the record's paper — single ruled field,
Archivo italic, button `Pass the note`. On send, the note resolves into the printed
record as a finalized visitor question marked *written*, and the question is delivered
over the `lk.chat` LiveKit text stream (verified against livekit-agents 1.6.5: RoomIO's
default text-input callback interrupts and generates a spoken reply — no agent change).
When microphone permission fails, the session stays connected, a slate card explains in
the studio's voice, and the note card opens itself — discoverable exactly when needed,
invisible competition otherwise. Fully keyboard operable: the affordance is a real
`<button>`, the field is a real `<input>`, Enter passes the note, focus is visible in
oxblood.

## 7. Self-review — "would any AI produce this for any chatbot?"

First-draft decisions that failed the test, and their revisions:

1. **Disclosure as a red top banner** (current skeleton) — that is the generic
   compliance-banner answer. Revised: a bottom **chyron/lower-third** in slate caps on
   ink, part of the broadcast frame. Wording untouched (operator's locked copy);
   placement and typography are the design.
2. **Six state colors** (green=listening, amber=thinking…) — traffic-light status dots
   are what every dashboard does. Revised: one accent, six **light behaviors + captions**
   in broadcast vocabulary; the lamp is furniture, not an icon.
3. **Cream page + serif** was the reflexive "dignified" palette and is explicitly the
   stock-AI look the brief bans. Revised: **warm set-greys from the portrait's backdrop**,
   navy ink from the tie, paper reserved for the record surfaces only.
4. **"Send" / chat input docked at the bottom** — the universal chat-app answer.
   Revised: **"pass him a written note"** on the record's paper, collapsed by default,
   surfaced by the mic-failure state.
5. Generic labels ("Connect", "Transcript", "Agent") — revised to the studio's own
   vocabulary: *Begin the interview*, *Transcript of record*, `LEE`/`YOU` attributions,
   `ON AIR`/`OFF AIR`/`FLOOR IS YOURS`/`IN SESSION`.

What deliberately stays quiet: no page-load animation sequence, no parallax, no texture
overlays on the set (the mottled backdrop stays in the portrait, not the CSS). The lamp
is the one place the design spends its boldness.
