# Voice selection results (issue #7)

**Winner: Chatterbox + 2005-era reference clips** (`elder_ref_06..09`).

## Method deviation, documented

The protocol's human blind-scoring was replaced by objective scoring at the
operator's request ("pick the voices for me"): speaker-embedding similarity
(resemblyzer, cosine vs the 2005 reference centroid), intelligibility
(faster-whisper WER vs known script), stability, and pacing — 120 samples,
6 engine-era conditions, composite rule in `scripts/score_blind_test.py`.
Full per-sample data: `assets/voices/blind-test/scores.json` (PR #30).
An optional operator A/B listen (winner vs runner-up) remains available; a
strong disagreement there reopens the decision.

## Ranking

| rank | condition | sim(2005) | WER | RTF | outcome |
|---|---|---|---|---|---|
| 1 | chatterbox-2005 | 0.873 | 0.021 | 0.36 | **winner** |
| 2 | xtts-2005 | 0.873 | 0.084 | 0.19 | long-sentence degradation; CPML non-commercial license |
| 3 | chatterbox-1990 | 0.768 | 0.026 | 0.34 | era penalty |
| 4 | xtts-1990 | 0.768 | 0.037 | 0.19 | era penalty |
| 5 | f5-1990 | 0.722 | 0.027 | 0.20 | lowest similarity |
| — | f5-2005 | 0.926 | 0.531 | 0.30 | **disqualified: leaks reference-clip speech into generations** |

Calibration ceiling (2005 refs, leave-one-out): 0.939 mean. Winner is 0.066 below it.

## Placement benchmark (2026-07-14)

Chatterbox synthesized beside the resident Qwen3-14B brain on the 16 GB
RTX 5070 Ti: RTF 0.36–0.49 (vs 0.36 solo), no OOM, brain served requests
immediately after. **Same-GPU placement is viable for the prototype.**

## Notes for issue #8

- Chatterbox: 24 kHz output, single reference clip, PerTh watermark built in
  (preserve it — plan §9), needs `setuptools<81` in its venv (pkg_resources).
- Pacing: winner speaks ~1.74× the real 82-year-old's measured rate — tune
  delivery speed during integration (time-stretch or generation settings).
- XTTS remains the fallback engine but its CPML license forbids commercial use.
