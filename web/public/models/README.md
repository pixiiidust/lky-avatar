# web/public/models

Rigged Live2D model files (`.model3.json`, `.moc3`, textures, physics) go
here at runtime — the licensed placeholder model first, the final DIY-rigged
LKY model later.

**Never committed.** This directory's contents are gitignored (licensing on
the placeholder, size and provenance on the final model). Only this README
and `.gitkeep` are tracked.

## Placeholder model: Natori (`natori/`)

Downloaded — not committed — by running from the repo root:

```
python scripts/fetch_placeholder_model.py
```

The web client loads it from `/models/natori/Natori.model3.json`
(`DEFAULT_MODEL_URL` in `web/src/avatar/Live2DAvatar.ts`). Natori (adult
man, formal wear) replaced the original Hiyori placeholder on 2026-07-15 at
the operator's request — the closest subject match among the free samples;
`--model hiyori` still fetches the old one.

| | |
|---|---|
| Model | Natori (successor placeholder) / Hiyori Momose (original), official Live2D sample models |
| Source | <https://github.com/Live2D/CubismWebSamples>, tag `5-r.5`, `Samples/Resources/<Model>/` |
| License | [Live2D Free Material License Agreement](https://www.live2d.com/eula/live2d-free-material-license-agreement_en.html) |
| Per-model terms | [Sample model workmanship terms](https://www.live2d.com/eula/live2d-sample-model-terms_en.html) |
| License copies | `<model>/LICENSE.md` and `<model>/NOTICE.md` are downloaded alongside the model |

License notes (verified 2026-07-13 against the repo's `LICENSE.md`):

- The sample models listed in that file (including Hiyori and Natori) are provided
  under the **Free Material License Agreement**, which permits individuals
  and small-scale enterprises (annual revenue ≤ 10M JPY) to use them in
  published applications. This project is a personal, non-commercial demo,
  well inside those bounds.
- Businesses above that threshold need a Cubism SDK Release License — noted
  here in case the demo's hosting situation ever changes.
- The model is development scaffolding only: it carries all avatar work
  until the final rigged LKY model (issue #12) replaces it, and remains the
  shippable fallback per the plan's risk register.

## Cubism Core runtime (not in this directory)

The Live2D **Cubism Core** script (`live2dcubismcore.min.js`) is proprietary
([Live2D Proprietary Software License Agreement](https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html)).
It is neither committed nor bundled: the client loads it at runtime from
Live2D's official CDN (`https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js`),
see `web/src/avatar/cubismCore.ts`. Override with `VITE_CUBISM_CORE_URL`
if you must self-host a copy obtained under the same agreement.
