"""Tests for scripts/benchmark_brain.py (issue #3).

The benchmark's real run needs CUDA; these tests exercise the identical
pipeline through ``--dry-run`` (pure stdlib fake engine) as a subprocess —
the same way the orchestrator invokes it — and validate the output JSON
schema that future benchmark runs must stay diffable against.
"""
import json
import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "benchmark_brain.py"
PROMPTS_PATH = REPO_ROOT / "evals" / "benchmark_prompts.json"

sys.path.insert(0, str(REPO_ROOT))
from scripts.benchmark_brain import metric_summary, percentile  # noqa: E402

ROW_REQUIRED_KEYS = {
    "id", "category", "source", "max_new_tokens", "question", "status",
    "prompt_tokens", "completion_tokens", "ttft_seconds",
    "decode_tokens_per_second", "overall_tokens_per_second",
    "generation_seconds", "answer_preview",
}
SUMMARY_KEYS = {"p50", "p95", "mean", "min", "max", "n"}


def run_benchmark(tmp_path, *extra_args):
    out_path = tmp_path / "bench.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run", "--git-sha", "testsha",
         "--output", str(out_path), *extra_args],
        capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(out_path.read_text(encoding="utf-8")), result.stdout


@pytest.fixture(scope="module")
def full_run(tmp_path_factory):
    return run_benchmark(tmp_path_factory.mktemp("bench"))


def test_prompt_set_has_at_least_20_varied_prompts():
    data = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
    prompts = data["prompts"]
    assert len(prompts) >= 20
    # both answer-length regimes present
    assert {p["max_new_tokens"] for p in prompts} == {80, 320}
    # variety: short factual, long reflective, modern, adversarial
    categories = {p["category"] for p in prompts}
    assert "short_factual" in categories
    assert "long_reflective" in categories
    assert any(c.startswith("modern_") for c in categories)
    assert any(c.startswith("adversarial_") for c in categories)
    # some prompts shared verbatim with the issue-#2 time-travel eval
    assert any(p["source"] for p in prompts)
    # unique ids
    assert len({p["id"] for p in prompts}) == len(prompts)


def test_dry_run_output_schema(full_run):
    out, _ = full_run
    assert out["schema_version"] == 1

    md = out["metadata"]
    assert md["git_sha"] == "testsha"
    assert md["dry_run"] is True
    assert md["base_model"] == "Qwen/Qwen3-14B"
    assert md["adapter_hf_id"] == "sjsim/lky-qlora"
    assert md["quantization"]["bnb_4bit_quant_type"] == "nf4"
    assert md["sampling"] == {"enable_thinking": False, "temperature": 0.7,
                              "top_p": 0.9, "repetition_penalty": 1.1}
    assert md["system_prompt"].startswith("You are Lee Kuan Yew")
    assert md["prompt_set"]["count"] >= 20
    env = md["environment"]
    for key in ("engine", "gpu_name", "torch", "transformers", "peft",
                "bitsandbytes", "python", "platform"):
        assert key in env
    assert env["engine"] == "dry-run-stub"

    assert isinstance(out["load"]["model_load_seconds"], (int, float))
    assert "allocated_gib" in out["load"]

    vram = out["vram"]
    assert "peak_vram_allocated_gib" in vram
    assert "peak_vram_reserved_gib" in vram
    assert "vram_after_load" in vram

    assert out["warmup"]["id"] == "warmup"


def test_dry_run_rows_and_aggregates(full_run):
    out, _ = full_run
    rows = out["results"]
    assert len(rows) >= 20
    for row in rows:
        assert ROW_REQUIRED_KEYS <= set(row), row["id"]
        assert row["status"] == "ok"
        assert row["ttft_seconds"] > 0
        assert row["decode_tokens_per_second"] > 0
        assert row["completion_tokens"] > 0

    agg = out["aggregates"]
    assert agg["num_prompts"] == len(rows)
    assert agg["num_failures"] == 0
    assert agg["failure_rate"] == 0
    for metric in ("ttft_seconds", "decode_tokens_per_second",
                   "overall_tokens_per_second", "generation_seconds"):
        summary = agg["all"][metric]
        assert SUMMARY_KEYS <= set(summary)
        assert summary["p50"] is not None
        assert summary["p95"] is not None
        assert summary["p50"] <= summary["p95"] or metric != "ttft_seconds"
    # per-regime blocks for both answer-length regimes
    assert set(agg["by_regime"]) == {"80", "320"}


def test_dry_run_prints_summary_table(full_run):
    _, stdout = full_run
    assert "=== per-prompt results ===" in stdout
    assert "=== aggregates ===" in stdout
    assert "failure rate" in stdout


def test_limit_smoke(tmp_path):
    out, _ = run_benchmark(tmp_path, "--limit", "3")
    assert len(out["results"]) == 3
    assert out["metadata"]["limit"] == 3
    assert out["aggregates"]["num_prompts"] == 3


def test_percentile_helpers():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([1], 95) == 1
    assert percentile([], 50) is None
    assert percentile([None, 2, 4], 50) == 3
    s = metric_summary([2.0, 4.0])
    assert s == {"p50": 3.0, "p95": 3.9, "mean": 3.0,
                 "min": 2.0, "max": 4.0, "n": 2}
    assert metric_summary([])["n"] == 0
