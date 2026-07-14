# Style-Feasibility Rig — Crude 2-Parameter Cubism Rig (issue #10)

One evening. Cut **just the mouth and eyelids** from the winning portrait
(see [`avatar-art-brief.md`](avatar-art-brief.md)) and build a crude
two-parameter rig in the **free** Live2D Cubism Editor. The point is a
cheap, early answer to one question — *does the painterly semi-realistic
style survive being puppeteered?* — before any full layer-separation or
Pro-trial rigging hours are spent (risk register: "semi-realistic style rigs
poorly → wasted art effort"). It doubles as rigging training for the
Milestone-5 full DIY rig.

**Time-box it.** If you exceed ~4 hours, stop and record what blocked you —
that is itself a feasibility finding.

**Files:** everything (PSD, `.cmo3` project, exports) lives in
`assets/avatar-source/` — gitignored, never committed. The `.gitignore`
already excludes `*.psd`, `*.model3.json`, and `*.moc3` globally.

---

## 0. Setup

- [ ] Download Live2D Cubism Editor (<https://www.live2d.com/en/cubism/download/editor/>)
      and start it with the **FREE plan** (choose FREE at the license
      prompt — do **not** start the 42-day Pro trial; the plan explicitly
      saves it for Milestone-5 full rigging). Free limits (fewer ArtMeshes/
      deformers/parameters) are far above what two parameters need.
- [ ] An editor that exports layered PSD: Photoshop, Krita (free), or
      Clip Studio. GIMP's PSD export works but flattens some features —
      prefer Krita if unsure.

## 1. Layer prep (mouth + eyelids only)

Work on a copy of the winning portrait. Target PSD structure — **each item
one raster layer, no groups-with-effects, no adjustment layers, no masks
left unapplied** (Cubism imports each PSD layer as one ArtMesh):

```text
lky-feasibility.psd
  eyelid_L        (skin-toned upper lid, painted to cover the left eye)
  eyelid_R        (same, right eye)
  eye_L           (visible eyeball: white + iris + catchlight)
  eye_R
  lip_upper       (upper lip + a few px of skin above)
  lip_lower       (lower lip + the chin skin that moves with the jaw)
  mouth_interior  (painted: dark oral cavity, hint of teeth — sits BEHIND lips)
  face_base       (everything else: face, hair, body, background)
```

Steps:

- [ ] **Mouth.** Lasso the upper lip and lower lip onto their own layers,
      cutting (not copying) from the base. Include a small overlap margin of
      skin (~5–10 px) around each cut so movement never reveals a gap.
- [ ] Paint `mouth_interior` behind the lips: dark cavity filling the whole
      area the open mouth could reveal (bigger than you think — the jaw
      drops), matching the portrait's painterly rendering (soft strokes, no
      flat fill).
- [ ] Heal the `face_base` under the removed lips (clone/inpaint) so nothing
      shows through if a lip layer moves.
- [ ] **Eyes.** Cut each visible eyeball (white + iris) to its own layer.
      Paint `eyelid_L`/`eyelid_R` above them: a closed-lid shape in matching
      skin tones with a lash line, initially positioned *above* its open
      position or at low opacity — its keyform, not the PSD, will control
      visibility, so paint it at full opacity in place and expect to move it
      in the editor.
- [ ] Keep every stroke in the portrait's style. If you cannot paint the
      interior/eyelids convincingly in that style, note it — that is
      *already* feasibility evidence about the full rig's cost.
- [ ] Export as PSD (flatten nothing).

## 2. Import into Cubism

- [ ] New project → drag the PSD in (import as Model). Confirm all 8 layers
      arrived as separate ArtMeshes with correct stacking order
      (`mouth_interior` behind lips; eyeballs behind eyelids).
- [ ] Run **automatic mesh generation** on the moving parts (lips, eyelids,
      eyes) with the default/standard preset — hand-tuned meshes are
      Milestone-5 business. Leave `face_base` as-is.
- [ ] Set the canvas/model scale so the face fills the preview comfortably.

## 3. Deformers and the two parameters

Two parameters, standard Cubism IDs (they must match what the web runtime
and state machine will drive later — `web/src/avatar/`):

| Parameter | ID | Range | Default |
|---|---|---|---|
| Mouth open | `ParamMouthOpenY` | 0 (closed) → 1 (open) | 0 |
| Eye blink | `ParamEyeLOpen` + `ParamEyeROpen` (keyed together as one blink) | 1 (open) → 0 (closed) | 1 |

- [ ] **Mouth:** create one **warp deformer** containing `lip_lower` (and the
      chin area of the cut), a second small one for `lip_upper`.
      On `ParamMouthOpenY` add two keys:
      - `0`: everything exactly as painted (closed — pixel-identical to the
        original portrait; spec story 20 makes "silence = closed mouth" a
        product requirement).
      - `1`: lower-lip deformer pulled down (jaw drop, ~5–8 % of face
        height), upper lip raised slightly, `mouth_interior` revealed.
        Add a mid-key at `0.5` if the interpolation looks rubbery.
- [ ] **Blink:** put each eyelid in its own warp deformer. On
      `ParamEyeLOpen`/`ParamEyeROpen` add keys:
      - `1`: lid raised/tucked so the painted eyeball shows (open — matches
        the original portrait).
      - `0`: lid drawn down fully covering the eyeball, lash line resting
        where the lower lid is.
      Key both eyes to blink together for this test.
- [ ] Scrub both sliders slowly end-to-end, then flick them fast (a blink is
      ~150 ms; an interruption snaps the mouth shut instantly — spec story
      19). Use the editor's random-pose/physics preview if helpful.

## 4. Feasible vs broken — what to look for

Judge at 100 % zoom and at presentation size, scrubbing each parameter.
**The question is whether the *style* survives, not whether your first rig
is pretty** — beginner rigging jank (fixable with hours) is not a style
failure (inherent to the art).

Signs the style is **feasible**:

- Closed mouth and open eyes at defaults are pixel-faithful to the portrait.
- Mid-motion frames look like *the same painting, moving*: brush strokes
  stretch coherently, painterly edges stay soft, no new visual language
  appears mid-animation.
- Cut seams (lip margins, eyelid edges) are invisible or fixable with a few
  px of overlap/feather.
- The painted mouth interior and closed lids read as belonging to the
  portrait's rendering.

Signs it is **broken** (style-level, not skill-level):

- Brushwork **shimmers or smears** when deformed — directional strokes
  slide over each other and the surface reads as rubber, not paint.
- Baked lighting tears: a highlight or shadow on the lips/chin/lids visibly
  detaches from the form when it moves (this is why the art brief bans
  rim-light on the mouth area).
- Seams cannot be hidden: the painterly texture is too irregular to blend a
  cut edge without visible repainting on every frame.
- Half-open states are unusable — the interpolated mouth/lids look like a
  different, cruder art style than the stills.
- The interior/lid inpainting cannot be matched to the style at all.

Middle verdict — **feasible with changes**: the style survives but this
*portrait* fights the rig (e.g. a specific highlight, too-hard lip edge,
hair over one eye). Note the exact art changes; regenerate/inpaint per the
art brief and re-test (the brief's §3.4 — fix near-misses, don't reroll).

## 5. Record the verdict

- [ ] Write `docs/reports/style-feasibility-verdict.md` (committable — text
      only, no art): verdict (**feasible / feasible with changes / broken**),
      what was tested, what broke or held with specifics, time spent, and
      rigging learnings for Milestone 5 (mesh density, overlap margins,
      deformer choices, free-edition friction).
- [ ] Post the verdict summary as a comment on issue #10 and tick the
      acceptance boxes that now hold.
- [ ] Keep the `.cmo3` and PSD in `assets/avatar-source/` (local-only) —
      they seed the Milestone-5 full rig.
- [ ] If **broken**: per the risk register, the licensed placeholder model
      remains the shippable fallback; the follow-up decision (adjust style
      target vs ship placeholder) belongs on issue #12, not here.
