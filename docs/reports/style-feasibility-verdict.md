# Style-Feasibility Verdict — Crude 2-Parameter Rig (issue #10)

**Verdict: FEASIBLE.** The painterly semi-realistic style survives being
puppeteered. Operator judgment after scrubbing both parameters slowly and at
snap speed, at 100 % zoom and presentation size: mid-motion frames read as
the same painting moving — soft painterly edges hold, no shimmering
brushwork, no visible seams. Residual roughness is beginner-rigging jank
(fixable with hours), not style failure. The full DIY rig (#12) is
green-lit; the licensed placeholder remains the shippable fallback until it
lands.

Date: 2026-07-15. Time spent: well under the 4 h time-box (~1 h operator
GUI time in Cubism; layer prep was automated, see below).

## What was tested

- 8-layer PSD per [`style-feasibility-rig.md`](../style-feasibility-rig.md)
  §1, cut from the final 2048² portrait (issue #10 portrait milestone).
- Crude rig in the **free** Cubism Editor 5.3 (Pro trial untouched, still
  reserved for Milestone 5): auto-meshed moving parts, one warp deformer per
  lip and per eyelid, `ParamMouthOpenY` 0→1 (closed→open) and eye-blink
  keyforms, scrubbed slow and fast.

## What held

- **Default state is pixel-faithful**: flattened default composite vs the
  original portrait measured mean abs diff 0.004/255 (spec story 20's
  "silence = closed mouth" requirement is achievable exactly).
- **Mouth open reads as natural mid-speech**: teeth hint at top, cavity
  shadow below, corners pinned, chin follows. Interior and lid inpainting
  match the portrait's rendering (see pipeline note — they ARE the
  portrait's rendering).
- **Blink looks native**: closed lids keep lash lines and socket shading in
  the portrait's language.
- Cut seams (5–10 px feathered skin margins) invisible in motion.

## What fought us (none of it style-level)

- **PSD dialect, not art**: Cubism silently imported layer *structure* but
  zero *pixels* from pytoshop-written PSDs (tried both raw and RLE
  encodings; psd-tools and Krita read the same files fine). Fix: round-trip
  through Krita (`krita in.psd --export --export-filename out.psd`) — its
  writer is the dialect Cubism expects. Byte-verified lossless.
- **Eye parameter polarity inverted** in the crude rig (0 = open, 1 =
  closed; Live2D standard is 1 = open). Deliberately left as-is under the
  time-box. **Milestone-5 rig must key `ParamEyeLOpen`/`ParamEyeROpen` with
  standard polarity** or the web runtime's blink/state machine will drive it
  backwards.

## Pipeline learning — no hand-painting was needed

The doc's layer-prep assumed manual painting of the mouth interior and
closed eyelids (the skill-heavy step). Instead:

1. Operator generated two GPT **edit-variants** of the base portrait (mouth
   open / eyes closed). Framing consistency was near-pixel (SIFT alignment
   residual < 1 px; only content drift was ~12 px vertical in the eye
   region, corrected at cut time).
2. Same Real-ESRGAN anime upscale as the portrait set → 2048².
3. Layers cut programmatically (OpenCV): lips/eyes from the base with
   feathered margins, interior/lids harvested from the variants — so the
   inpainting is by construction in the portrait's exact style. The
   variant's own lower lip must be excluded from `mouth_interior` (else
   doubled lips); a darkness ramp below the upper-teeth row makes deeper jaw
   drops read as cavity depth.
4. Base healed under the lips with OpenCV inpaint; invisible behind the
   interior at every mouth position.

This is the recommended path for the Milestone-5 full layer separation:
generate expression/pose variants with GPT, harvest regions, reserve human
hours for rigging and taste.

## Rigging learnings for Milestone 5

- Auto-mesh (Standard preset) is fine for lips/lids at this motion range.
- Corner-pinned parabolic jaw drop of ~65–80 px (≈6 % of face height) is
  the sweet spot for this portrait; the painted interior supports it.
- Warp deformer per moving part, keyed at the parameter extremes, with a
  mid-key only if interpolation looks rubbery — none was needed.
- Free-edition limits were nowhere near binding for 2 parameters.
- Keep every art source in `assets/avatar-source/` (gitignored); the .cmo3
  and PSDs there seed the full rig.
