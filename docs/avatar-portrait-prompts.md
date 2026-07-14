# Portrait prompt pack (issue #10)

Ready-to-paste prompts implementing [`avatar-art-brief.md`](avatar-art-brief.md).
Use the **named** version first; if your tool blocks real-person likenesses, switch
to the **described** version and iterate toward likeness with reference images.

Keep fixed across every iteration: shoulders-up framing, closed mouth, eyes open,
even frontal lighting, plain dark background. Vary ONE thing at a time (style
strength, age emphasis, wardrobe) so you can tell what moved the result.

## A. Primary prompt (named)

> Dignified portrait of elder Lee Kuan Yew in his 80s, semi-realistic dramatized
> anime style, painterly digital illustration, cinematic and stately. Front-facing,
> very slight three-quarter turn, shoulders-up composition. Composed, attentive,
> faintly stern interview expression; mouth fully closed; eyes open, sharp and
> alert. Thinning combed-back white hair, high forehead, deep nasolabial folds,
> strong jaw, aged skin rendered with soft painterly brushwork. Plain dark suit,
> white shirt, dark tie. Even, soft frontal studio lighting, no rim light, no harsh
> shadows around the mouth or eyes. Flat dark neutral background. Clean silhouette,
> hair clearly separable from background, no glasses, no hands, no microphone,
> nothing overlapping the face. High detail, 2048px, portrait orientation.

## B. Described version (if the tool refuses names)

> Dignified portrait of an East Asian elder statesman in his 80s — thinning
> combed-back white hair, high forehead, penetrating narrow eyes, deep nasolabial
> folds, strong jaw, composed faintly stern expression — semi-realistic dramatized
> anime style, painterly digital illustration, cinematic and stately. Front-facing,
> slight three-quarter turn, shoulders-up. Mouth fully closed, eyes open and alert.
> Plain dark suit, white shirt, dark tie. Even soft frontal lighting, no rim light.
> Flat dark neutral background, clean separable silhouette, no glasses, no hands,
> no occlusions. High detail, 2048px, portrait orientation.

Then feed 2–3 real reference photos of elder LKY (2000s interviews) through your
tool's image-reference / face-reference feature and iterate toward likeness.

## C. Style-axis variations (swap into A or B)

- **More painterly/dramatic:** replace the style clause with — *"painterly
  semi-realistic style of a prestige historical drama poster, visible confident
  brushwork, muted dignified palette, subtle film grain"*
- **Cleaner/more anime:** — *"refined seinen manga illustration style, realistic
  proportions, clean linework with painterly shading, absolutely not chibi, not
  cel-shaded moe"*
- **Windbreaker variant (his signature late-era look):** replace wardrobe with —
  *"light beige windbreaker over an open-collared shirt"*

## D. Negative prompt (SD/ComfyUI-style tools)

> photorealistic, photograph, uncanny, chibi, cute, big eyes, cel shading,
> caricature, exaggerated features, young man, middle-aged, smiling, open mouth,
> teeth, glasses, hands, microphone, rim lighting, dramatic side lighting, busy
> background, scenery, text, watermark, low resolution, cropped forehead

## E. Midjourney-flavored one-liner

> elder Lee Kuan Yew, 80s, semi-realistic dramatized anime portrait, painterly,
> stately, front-facing slight 3/4, shoulders-up, composed stern interview
> expression, closed mouth, thinning white combed-back hair, dark suit, even soft
> frontal light, flat dark background, clean silhouette --ar 4:5 --stylize 250

(If the platform blocks the name, use section B's description + reference images
via image prompts.)

## Workflow reminder (from the brief §3)

1. 10–20 generations per variant, cull hard at thumbnail size (squint test).
2. Nail **likeness first**, then style; fix near-misses with inpainting/img2img
   rather than rerolling a good face.
3. Shortlist 3–5 → check the brief's §2 ten constraints one by one → drop into
   `assets/avatar-source/` with prompt/seed notes → I review them against the
   brief and tell you what passes and what to regenerate.
