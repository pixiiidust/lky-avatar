"""Objective scoring of the blind-test synthesis outputs (issue #7).

Scores every ``assets/voices/blind-test/raw/<engine>-<era>/response_NN.wav``
against the elder-LKY reference clips with reproducible, CPU-only metrics.
The metrics map onto the rubric axes of ``docs/voice-blind-test.md``:

- **speaker_similarity** (rubric: similarity) — resemblyzer ``VoiceEncoder``
  cosine similarity of each sample against (a) the centroid of the 2005
  reference clips (PRIMARY — the persona target, issue #7 era note) and
  (b) the centroid of the sample's own cloning-era references. A
  leave-one-out ref-vs-ref baseline per era is reported as the calibration
  ceiling: a synthetic sample cannot be expected to beat it.
- **intelligibility** — faster-whisper (small.en, CPU, int8) transcript vs
  the known response text -> WER (local implementation, no jiwer dep).
  Light text normalization only, so WER is a slight upper bound.
- **stability** (rubric: long-sentence stability / naturalness proxies) —
  duration sanity vs text length, clipping ratio (|sample| > 0.99),
  leading/trailing/internal silence ratios, and synthesis failures
  (missing/unreadable outputs count as failures — a flubbed take is data).
- **pacing** — chars/sec of the sample vs chars/sec of the era's reference
  clips (their ``.txt`` transcripts vs their durations).
- **latency/RTF** — pulled per response from each condition's
  ``synthesis_log.jsonl`` (written by ``blind_test_synthesize.py``).

Composite ranking rule (the reproducible stand-in for human scoring):

1. Rank engine-era conditions by **mean primary similarity** (cosine vs the
   2005 reference centroid), descending.
2. **Disqualify** any condition with mean WER > 0.15 or >= 1 synthesis
   failure (missing/unreadable expected output). Disqualified conditions
   are listed after all qualified ones, with reasons.
3. Tie-breaks (similarity within 0.005): lower mean WER, then lower mean
   RTF.

The final winner still gets a human A/B listen (winner vs runner-up); this
scoring replaces ears everywhere else.

Typical run (WSL, CPU-only venv — never touches the GPU):

    ~/score/bin/python scripts/score_blind_test.py \
        --voices-root /mnt/c/Users/Jamie/lky-avatar/assets/voices

Output: ``<voices-root>/blind-test/scores.json`` (per-sample rows +
per-condition aggregates + calibration + ranking) and a printed ranking
table. Pure logic (WER, normalization, log parsing, aggregation, ranking)
is unit-tested on Windows Python with no audio deps (tests/test_score_blind_test.py).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import re
import sys

try:  # repo-root import (tests) or scripts-dir import (direct run)
    from scripts import blind_test_synthesize as bts
except ImportError:  # pragma: no cover - exercised only when run as a script
    import blind_test_synthesize as bts

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_VOICES_ROOT = REPO_ROOT / "assets" / "voices"

PRIMARY_ERA = "2005"          # the persona target (issue #7 era note)
WER_DISQUALIFY = 0.15         # mean-WER ceiling per the composite rule
SIMILARITY_TIE = 0.005        # similarity margin treated as a tie
CLIP_THRESHOLD = 0.99         # |sample| above this counts as clipped
SILENCE_FRAME_MS = 20         # frame size for silence analysis
SILENCE_DB_BELOW_PEAK = 40.0  # frame is silent if 40 dB below the loud frames
CPS_SUSPECT_LOW = 6.0         # chars/sec outside [low, high] means the
CPS_SUSPECT_HIGH = 25.0       # duration does not fit the text (truncation,
                              # loops, stuck synthesis) — absolute bounds,
                              # since the elderly refs speak far slower than
                              # any healthy TTS output


# --------------------------------------------------------------------------
# Pure logic (unit-tested on Windows, stdlib only)
# --------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")

_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: i * 10 for i, w in enumerate(
    "twenty thirty forty fifty sixty seventy eighty ninety".split(), 2)}
_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000}


def _words_to_digits(tokens: list[str]) -> list[str]:
    """Collapse spelled-out numbers to digits ('thirty one' -> '31').

    Whisper writes '31 years', '$500', '80%' where the script spells the
    numbers out; converting BOTH sides symmetrically stops that inflating
    WER without hiding real garbles.
    """
    out: list[str] = []
    cur = total = 0
    in_num = False

    def flush():
        nonlocal cur, total, in_num
        if in_num:
            out.append(str(total + cur))
            cur = total = 0
            in_num = False

    for tok in tokens:
        if tok in _UNITS:
            cur += _UNITS[tok]
            in_num = True
        elif tok in _TENS:
            cur += _TENS[tok]
            in_num = True
        elif tok in _SCALES and in_num:
            if tok == "hundred":
                cur *= 100
            else:
                total += cur * _SCALES[tok]
                cur = 0
        else:
            flush()
            out.append(tok)
    flush()
    return out


def normalize_for_wer(text: str) -> list[str]:
    """Normalize a transcript to a word list for WER.

    Lowercase, unify dashes to spaces, '$N' -> 'N dollars', 'per cent'/'%'
    -> 'percent', strip remaining punctuation, drop digit-grouping commas,
    spell-out numbers -> digits, collapse whitespace. Deliberately light
    beyond number handling: heavier normalization would hide real
    intelligibility failures.
    """
    t = text.lower()
    t = re.sub(r"[‐-―-]", " ", t)   # hyphens/dashes -> space
    t = re.sub(r"\$\s?(\d[\d,]*)", r"\1 dollars", t)
    t = t.replace("%", " percent ")
    t = re.sub(r"\bper\s+cent\b", "percent", t)
    t = re.sub(r"(\d),(\d)", r"\1\2", t)       # 12,000 -> 12000
    t = _PUNCT_RE.sub("", t)
    return _words_to_digits(_WS_RE.sub(" ", t).strip().split())


def wer(ref_words: list[str], hyp_words: list[str]) -> float:
    """Word error rate: (substitutions+deletions+insertions) / len(ref).

    Standard Levenshtein on word lists. Empty ref: 0.0 if hyp is empty too,
    else 1.0 (fully inserted).
    """
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    prev = list(range(len(hyp_words) + 1))
    for i, r in enumerate(ref_words, 1):
        cur = [i] + [0] * len(hyp_words)
        for j, h in enumerate(hyp_words, 1):
            cur[j] = min(prev[j] + 1,                    # deletion
                         cur[j - 1] + 1,                 # insertion
                         prev[j - 1] + (r != h))         # substitution
        prev = cur
    return prev[-1] / len(ref_words)


def parse_synthesis_log(lines: list[str]) -> tuple[dict[int, dict], dict]:
    """Parse a condition's synthesis_log.jsonl.

    Returns (per-response records, last session record). Multiple sessions
    may be appended (failed runs, resumes); the LAST record per response
    wins. Malformed lines are skipped.
    """
    per_response: dict[int, dict] = {}
    session: dict = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("event") == "session":
            session = rec
        elif isinstance(rec.get("response"), int):
            per_response[rec["response"]] = rec
    return per_response, session


def _mean(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def aggregate_condition(samples: list[dict]) -> dict:
    """Aggregate per-sample rows of ONE engine-era condition."""
    ok = [s for s in samples if not s.get("failed")]
    agg = {
        "n_expected": len(samples),
        "n_scored": len(ok),
        "failures": sum(1 for s in samples if s.get("failed")),
        "mean_sim_primary": _mean([s.get("sim_primary") for s in ok]),
        "min_sim_primary": (min([s["sim_primary"] for s in ok
                                 if s.get("sim_primary") is not None], default=None)),
        "mean_sim_own_era": _mean([s.get("sim_own_era") for s in ok]),
        "mean_wer": _mean([s.get("wer") for s in ok]),
        "max_wer": (max([s["wer"] for s in ok if s.get("wer") is not None],
                        default=None)),
        "mean_clipping_ratio": _mean([s.get("clipping_ratio") for s in ok]),
        "mean_internal_silence_ratio": _mean(
            [s.get("internal_silence_ratio") for s in ok]),
        "mean_pacing_ratio": _mean([s.get("pacing_ratio") for s in ok]),
        "n_duration_suspect": sum(1 for s in ok if s.get("duration_suspect")),
        "mean_rtf": _mean([s.get("synth_rtf") for s in ok]),
        "mean_synth_seconds": _mean([s.get("synth_seconds") for s in ok]),
    }
    if agg["min_sim_primary"] is not None:
        agg["min_sim_primary"] = round(agg["min_sim_primary"], 4)
    return agg


def rank_conditions(aggregates: dict[str, dict],
                    wer_limit: float = WER_DISQUALIFY,
                    sim_tie: float = SIMILARITY_TIE) -> list[dict]:
    """Apply the composite ranking rule (module docstring) to aggregates.

    Returns rows ordered best-first: qualified conditions ranked by mean
    primary similarity (WER, then RTF as tie-breaks within ``sim_tie``),
    then disqualified conditions (with reasons), also similarity-ordered.
    """
    rows = []
    for condition, agg in aggregates.items():
        reasons = []
        if agg["failures"]:
            reasons.append(f"{agg['failures']} synthesis failure(s)")
        if agg["mean_wer"] is None:
            reasons.append("no WER measured")
        elif agg["mean_wer"] > wer_limit:
            reasons.append(f"mean WER {agg['mean_wer']:.3f} > {wer_limit}")
        if agg["mean_sim_primary"] is None:
            reasons.append("no similarity measured")
        rows.append({"condition": condition, "qualified": not reasons,
                     "disqualify_reasons": reasons, **agg})

    def sort_key(row):
        sim = row["mean_sim_primary"] or 0.0
        w = row["mean_wer"] if row["mean_wer"] is not None else 1.0
        rtf = row["mean_rtf"] if row["mean_rtf"] is not None else float("inf")
        # Quantize similarity so near-ties fall through to WER then RTF.
        return (-round(sim / sim_tie), w, rtf)

    rows.sort(key=lambda r: (not r["qualified"],) + sort_key(r))
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows


def format_ranking_table(rows: list[dict]) -> str:
    header = (f"{'rank':<5}{'condition':<18}{'sim(2005)':>10}{'min sim':>9}"
              f"{'WER':>8}{'pace':>7}{'RTF':>7}{'fail':>6}  status")
    out = [header, "-" * len(header)]
    for r in rows:
        def f(v, spec=".3f"):
            return format(v, spec) if v is not None else "-"
        status = "OK" if r["qualified"] else \
            "DISQUALIFIED: " + "; ".join(r["disqualify_reasons"])
        out.append(f"{r['rank']:<5}{r['condition']:<18}"
                   f"{f(r['mean_sim_primary']):>10}{f(r['min_sim_primary']):>9}"
                   f"{f(r['mean_wer']):>8}{f(r['mean_pacing_ratio'], '.2f'):>7}"
                   f"{f(r['mean_rtf'], '.2f'):>7}{r['failures']:>6}  {status}")
    return "\n".join(out)


# --------------------------------------------------------------------------
# Audio metrics (lazy imports; WSL CPU venv only)
# --------------------------------------------------------------------------

def _load_mono(path: pathlib.Path):
    """(mono float32 array, sample rate) via soundfile."""
    import numpy as np
    import soundfile as sf

    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return np.mean(data, axis=1), sr


def clipping_ratio(x, threshold: float = CLIP_THRESHOLD) -> float:
    import numpy as np

    return float(np.mean(np.abs(x) > threshold)) if len(x) else 0.0


def silence_profile(x, sr: int, frame_ms: int = SILENCE_FRAME_MS,
                    db_below_peak: float = SILENCE_DB_BELOW_PEAK) -> dict:
    """Leading/trailing silence (s) and internal-silence ratio.

    Frame-RMS based: a frame is silent if it is `db_below_peak` dB under the
    95th-percentile frame RMS (robust to absolute level differences between
    engines). Internal ratio = silent frames strictly between the first and
    last voiced frame / frames in that span.
    """
    import numpy as np

    frame = max(1, int(sr * frame_ms / 1000))
    n_frames = len(x) // frame
    if n_frames == 0:
        return {"lead_silence_s": 0.0, "trail_silence_s": 0.0,
                "internal_silence_ratio": 0.0}
    rms = np.sqrt(np.mean(
        x[: n_frames * frame].reshape(n_frames, frame) ** 2, axis=1))
    peak = np.percentile(rms[rms > 0], 95) if np.any(rms > 0) else 0.0
    if peak <= 0:
        span_s = round(n_frames * frame / sr, 3)
        return {"lead_silence_s": span_s, "trail_silence_s": span_s,
                "internal_silence_ratio": 1.0}
    silent = rms < peak * (10 ** (-db_below_peak / 20))
    voiced_idx = np.flatnonzero(~silent)
    lead = int(voiced_idx[0])
    trail = int(n_frames - 1 - voiced_idx[-1])
    inner = silent[voiced_idx[0]: voiced_idx[-1] + 1]
    return {
        "lead_silence_s": round(lead * frame / sr, 3),
        "trail_silence_s": round(trail * frame / sr, 3),
        "internal_silence_ratio": round(float(np.mean(inner)), 4),
    }


class SpeakerSimilarity:
    """resemblyzer VoiceEncoder embeddings + era centroids (CPU)."""

    def __init__(self, ref_dir: pathlib.Path):
        import numpy as np
        from resemblyzer import VoiceEncoder, preprocess_wav

        self._np = np
        self._preprocess = preprocess_wav
        self.encoder = VoiceEncoder("cpu")
        self.ref_embeds: dict[str, list] = {}
        self.centroids: dict[str, object] = {}
        for era, names in bts.ERA_CLIPS.items():
            embeds = [self.encoder.embed_utterance(preprocess_wav(ref_dir / n))
                      for n in names if (ref_dir / n).is_file()]
            if not embeds:
                raise FileNotFoundError(
                    f"no reference clips for era {era} in {ref_dir}")
            self.ref_embeds[era] = embeds
            self.centroids[era] = self._centroid(embeds)

    def _centroid(self, embeds):
        c = self._np.mean(self._np.stack(embeds), axis=0)
        return c / self._np.linalg.norm(c)

    def embed_file(self, path: pathlib.Path):
        return self.encoder.embed_utterance(self._preprocess(path))

    def similarity(self, embed, era: str) -> float:
        return round(float(self._np.dot(embed, self.centroids[era])), 4)

    def calibration(self) -> dict:
        """Leave-one-out ref-vs-ref cosine per era (the ceiling), plus the
        cross-era similarity of each 1990 clip to the 2005 centroid."""
        np = self._np
        out = {}
        for era, embeds in self.ref_embeds.items():
            loo = []
            for i, e in enumerate(embeds):
                rest = embeds[:i] + embeds[i + 1:]
                if rest:
                    loo.append(float(np.dot(e, self._centroid(rest))))
            out[f"ref_vs_ref_loo_{era}"] = {
                "mean": round(sum(loo) / len(loo), 4),
                "min": round(min(loo), 4), "n_refs": len(embeds)}
        other = [era for era in self.ref_embeds if era != PRIMARY_ERA]
        for era in other:
            sims = [float(np.dot(e, self.centroids[PRIMARY_ERA]))
                    for e in self.ref_embeds[era]]
            out[f"refs_{era}_vs_{PRIMARY_ERA}_centroid"] = {
                "mean": round(sum(sims) / len(sims), 4),
                "min": round(min(sims), 4)}
        return out


class Transcriber:
    """faster-whisper small.en on CPU (int8)."""

    def __init__(self, model_name: str = "small.en"):
        from faster_whisper import WhisperModel

        self.model = WhisperModel(model_name, device="cpu",
                                  compute_type="int8")

    def transcribe(self, path: pathlib.Path) -> str:
        segments, _info = self.model.transcribe(str(path), beam_size=5)
        return " ".join(seg.text.strip() for seg in segments).strip()


def reference_pacing(ref_dir: pathlib.Path) -> dict[str, dict]:
    """chars/sec of each era's reference clips (transcripts beside wavs)."""
    out = {}
    for era, names in bts.ERA_CLIPS.items():
        chars = seconds = 0.0
        used = []
        for name in names:
            wav = ref_dir / name
            txt = wav.with_suffix(".txt")
            if not (wav.is_file() and txt.is_file()):
                continue
            import soundfile as sf

            info = sf.info(str(wav))
            seconds += info.frames / info.samplerate
            chars += len(re.sub(r"\s+", " ", txt.read_text(encoding="utf-8").strip()))
            used.append(name)
        out[era] = {"chars_per_sec": round(chars / seconds, 3) if seconds else None,
                    "clips_used": used}
    return out


# --------------------------------------------------------------------------
# Scoring run
# --------------------------------------------------------------------------

def score_sample(path: pathlib.Path, text: str, era: str,
                 sim: SpeakerSimilarity, asr: Transcriber | None,
                 ref_cps: dict[str, dict]) -> dict:
    row: dict = {}
    x, sr = _load_mono(path)
    duration = len(x) / sr
    row["duration_s"] = round(duration, 2)
    row["sample_rate"] = sr

    embed = sim.embed_file(path)
    row["sim_primary"] = sim.similarity(embed, PRIMARY_ERA)
    row["sim_own_era"] = sim.similarity(embed, era)

    if asr is not None:
        hyp = asr.transcribe(path)
        row["transcript"] = hyp
        row["wer"] = round(wer(normalize_for_wer(text), normalize_for_wer(hyp)), 4)

    row["clipping_ratio"] = round(clipping_ratio(x), 6)
    row.update(silence_profile(x, sr))

    cps_ref = (ref_cps.get(era) or {}).get("chars_per_sec")
    cps = len(text) / duration if duration else None
    row["chars_per_sec"] = round(cps, 3) if cps else None
    if cps:
        row["duration_suspect"] = not (CPS_SUSPECT_LOW <= cps <= CPS_SUSPECT_HIGH)
    if cps and cps_ref:
        row["pacing_ratio"] = round(cps / cps_ref, 3)
    return row


def run(args: argparse.Namespace) -> int:
    voices_root = args.voices_root
    raw_root = voices_root / "blind-test" / "raw"
    ref_dir = voices_root / "elder"
    texts = bts.load_test_script(args.doc)
    n_responses = args.limit or bts.EXPECTED_RESPONSES

    engines = args.engines or list(bts.ENGINES)
    eras = args.eras or sorted(bts.ERA_CLIPS)

    print(f"loading speaker encoder + references from {ref_dir} ...")
    sim = SpeakerSimilarity(ref_dir)
    calibration = sim.calibration()
    ref_cps = reference_pacing(ref_dir)
    asr = None
    if not args.no_whisper:
        print(f"loading faster-whisper {args.whisper_model} (cpu/int8) ...")
        asr = Transcriber(args.whisper_model)

    samples: list[dict] = []
    aggregates: dict[str, dict] = {}
    for engine in engines:
        for era in eras:
            condition = bts.condition_label(engine, era)
            cond_dir = raw_root / condition
            log_records, session = ({}, {})
            log_path = cond_dir / "synthesis_log.jsonl"
            if log_path.is_file():
                log_records, session = parse_synthesis_log(
                    log_path.read_text(encoding="utf-8").splitlines())
            cond_rows = []
            for n in range(1, n_responses + 1):
                wav_path = cond_dir / bts.response_filename(n)
                row = {"condition": condition, "engine": engine, "era": era,
                       "response": n, "file": str(wav_path.relative_to(raw_root)),
                       "text_chars": len(texts[n - 1])}
                rec = log_records.get(n, {})
                row["synth_seconds"] = rec.get("seconds")
                row["synth_rtf"] = rec.get("rtf")
                if not wav_path.is_file():
                    row.update(failed=True, failure_reason="missing output")
                else:
                    try:
                        row.update(score_sample(wav_path, texts[n - 1], era,
                                                sim, asr, ref_cps))
                        row["failed"] = False
                    except Exception as exc:  # unreadable wav = failure data
                        row.update(failed=True,
                                   failure_reason=f"unreadable: {exc}")
                cond_rows.append(row)
                if not row["failed"]:
                    print(f"  {condition} #{n:02d} sim={row['sim_primary']:.3f} "
                          f"wer={row.get('wer', float('nan')):.3f} "
                          f"dur={row['duration_s']:.1f}s")
                else:
                    print(f"  {condition} #{n:02d} FAILED: {row['failure_reason']}")
            samples.extend(cond_rows)
            aggregates[condition] = aggregate_condition(cond_rows)
            if session:
                aggregates[condition]["synthesis_device"] = session.get("device")

    ranking = rank_conditions(aggregates)
    result = {
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "config": {
            "voices_root": str(voices_root), "responses": n_responses,
            "primary_era": PRIMARY_ERA, "wer_disqualify": WER_DISQUALIFY,
            "whisper_model": None if args.no_whisper else args.whisper_model,
            "speaker_encoder": "resemblyzer VoiceEncoder (cpu)",
            "ranking_rule": "mean primary similarity; disqualify mean WER "
                            f"> {WER_DISQUALIFY} or any synthesis failure; "
                            "tie-break WER then RTF",
        },
        "calibration": {"speaker_similarity": calibration,
                        "reference_pacing": ref_cps},
        "aggregates": aggregates,
        "ranking": ranking,
        "samples": samples,
    }
    out_path = args.out or (voices_root / "blind-test" / "scores.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out_path}")
    print("\ncalibration (ref-vs-ref ceiling): " + json.dumps(calibration))
    print("\n" + format_ranking_table(ranking))
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Objective scoring of blind-test TTS outputs (issue #7).")
    ap.add_argument("--voices-root", type=pathlib.Path,
                    default=DEFAULT_VOICES_ROOT,
                    help="assets/voices root holding elder/ refs and blind-test/raw/")
    ap.add_argument("--out", type=pathlib.Path, default=None,
                    help="scores.json path (default <voices-root>/blind-test/scores.json)")
    ap.add_argument("--engines", nargs="*", choices=bts.ENGINES, default=None)
    ap.add_argument("--eras", nargs="*", choices=sorted(bts.ERA_CLIPS), default=None)
    ap.add_argument("--limit", type=int, default=None,
                    help="score only the first N responses (smoke runs)")
    ap.add_argument("--whisper-model", default="small.en")
    ap.add_argument("--no-whisper", action="store_true",
                    help="skip transcription/WER (fast smoke run)")
    ap.add_argument("--doc", type=pathlib.Path, default=bts.DOC_PATH)
    return ap


def main(argv: list[str] | None = None) -> int:
    return run(build_arg_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
