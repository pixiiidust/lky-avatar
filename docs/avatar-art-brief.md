# Avatar Art Brief — LKY Portrait (issue #10)

What to generate, what constraints the Live2D pipeline imposes, how to
iterate, and what "done" looks like. Companion doc:
[`style-feasibility-rig.md`](style-feasibility-rig.md) (what happens to the
winning portrait next).

**Where files go:** every portrait candidate, source image, and working file
goes in `assets/avatar-source/` — gitignored, never committed (plan §9;
issue #10 acceptance criteria). Keep prompts/seeds in a local text file next
to the images so the winning candidate can be regenerated or varied.

---

## 1. Style target

**Semi-realistic, dramatized anime — the "well-drawn AI anime dramatization"
register** (plan §7, Milestone 4 Track B). Think prestige-drama key art or a
painterly seinen illustration of a real statesman: realistic facial structure
and proportions, dignified rendering, visible painterly brushwork in skin and
hair — clearly an artwork, not a photograph, and equally clearly *him*.

- **Recognizably elder Lee Kuan Yew** (late-era: 1990s–2000s, roughly
  70s–80s). The likeness carries the demo; a beautiful portrait of a generic
  elderly statesman is a failure.
  - Likeness anchors to check every candidate against: receding swept-back
    grey/white hair; strong brow ridge with age-thinned brows; deep nasolabial
    folds; firm, slightly downturned mouth; alert, penetrating eyes with heavy
    lids; prominent ears; age spots acceptable and humanizing.
- **Expression:** composed, attentive, faintly stern — the interview
  listening face. Not smiling, not scowling. This is the avatar's *neutral*;
  every animated state is built on top of it.
- **Wardrobe:** plain dark suit or his signature light windbreaker over a
  shirt; no medals, no flags, no props.
- **Background:** flat or softly gradiented dark neutral. No scenery — it
  will be masked or replaced in the rig.
- Painterly is wanted, but the style must survive puppeteering: brushwork
  that reads as *rendered form* (directional strokes following anatomy) rigs
  far better than texture noise or heavy canvas grain, which shimmers when
  deformed.

### NOT this

- ❌ Chibi, cel-shaded moe, big-eyed cartoon, VTuber-cute — any register
  that would make the disclosure label feel like a joke.
- ❌ Photorealism / uncanny photo-composite (also raises "is this real
  footage?" confusion the spec's honesty requirements exist to prevent).
- ❌ Caricature or editorial-cartoon exaggeration of features.
- ❌ Young or middle-aged LKY. One persona, one (elder) avatar.

## 2. Technical constraints (Live2D rigging)

These are hard requirements — a gorgeous portrait that violates them is
unusable. They exist because the portrait will be layer-separated and
deformed (mouth, eyelids, later head XYZ and physics).

| # | Constraint | Why |
|---|---|---|
| 1 | **Front-facing to slight 3/4** (≤ ~15–20° yaw), level camera | Live2D fakes rotation by warping; a strong 3/4 or tilted head halves the usable rotation range and breaks symmetry when the head turns |
| 2 | **Neutral, fully closed mouth** | The rig *opens* the mouth from closed; a parted-lips base makes "silence = closed mouth" (spec story 20) impossible without repainting |
| 3 | **Eyes open, looking at camera** | Eyelids are rigged to close from open; catchlights should sit consistently in both eyes |
| 4 | **Even, soft, frontal lighting** | Baked-in dramatic side light shears when layers move. Soft top-front key is fine; avoid hard shadows across features |
| 5 | **No rim-light or specular highlight on/around the mouth area** | Any baked highlight on the lips/chin visibly smears the moment the mouth deforms — this is the first thing that breaks in a feasibility rig |
| 6 | **Hair silhouette cleanly separable from face and background** | Hair becomes its own layer(s) for physics; wisps blending into the forehead or a busy background make clean cutting impossible |
| 7 | **High resolution** — 2048×2048 minimum, 4096 preferred, face ≥ ~50 % of frame height | Layers get cut, inpainted, and zoomed; upscale a winning low-res candidate before layer work |
| 8 | **Shoulders-up composition**, centered, with headroom and ~10 % margin on all sides | The rig needs shoulders for breathing motion; cropped crowns or shoulders cannot be animated in |
| 9 | Nothing occluding the face or neck — no hands, glasses (unless committed to rigging them), microphones, high collars over the jaw | Every occluder is another layer to separate and animate |
| 10 | Plain background, strong subject/background contrast | Fast, clean masking |

## 3. Iteration guidance (AI generation)

1. **Volume first.** Generate wide (10–20 per prompt variant) and cull hard.
   Vary: style strength (painterly ↔ realistic), age emphasis, lighting
   flatness, camera angle. Keep every prompt + seed with its output.
2. **Iterate on likeness before style.** Get a face that is unmistakably him
   in *any* acceptable register first; then pull style toward the painterly
   target. Style-first iteration converges on handsome strangers.
3. Likeness tools in roughly increasing effort: descriptive prompting alone →
   img2img from a reference photo at low denoise → identity adapters
   (IP-Adapter/InstantID-class) if available. Respect the constraint set
   above regardless of tool. (Rights note: generate *from* the likeness, do
   not composite archival photos into the final art.)
4. **Fix near-misses, don't reroll them.** A candidate with the right face
   but a lighting/mouth/crop violation is usually salvageable with inpainting
   (close the mouth, flatten a highlight, extend shoulders) faster than
   another 20 rolls.
5. **Squint test + swap test.** At thumbnail size it should still read as
   LKY; shown next to a real late-era photo, a stranger should match them
   without hesitation.
6. Shortlist 3–5, view at 100 % zoom (AI artifacts around teeth, ears,
   hairline disqualify), pick **one** winner. Note the runner-up — the
   feasibility rig may reveal the winner deforms badly.

## 4. What "done" looks like

The art track (issue #10, first acceptance criterion) is done when **one
selected portrait** satisfies all of:

- [ ] Recognizably elder LKY — passes the squint test and the swap test
      against a real late-era photo.
- [ ] In the target register: semi-realistic dramatized anime/painterly;
      unambiguously artwork, unambiguously not chibi/cartoon/photoreal.
- [ ] Composed, attentive neutral expression; mouth fully closed; eyes open.
- [ ] All ten technical constraints in §2 satisfied (check them one by one).
- [ ] ≥ 2048 px, face ≥ ~50 % of frame height, shoulders-up with margins.
- [ ] Stored in `assets/avatar-source/` with its prompt/seed/tool notes;
      nothing committed to Git.
- [ ] Candidate iteration recorded (a short local note: how many generated,
      shortlist, why the winner won) — this becomes part of the issue-#10
      verdict comment.

**Next step:** take the winner into
[`style-feasibility-rig.md`](style-feasibility-rig.md) — cut mouth + eyelid
layers and prove the style survives animation *before* any full layer
separation (risk register: "semi-realistic style rigs poorly → wasted art
effort").
