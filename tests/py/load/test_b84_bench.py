"""B-84 benchmark script: tools/bench_load.py records throughput and latency into a labelled report (specs/B-84.md).

The statistics and the report text are tested on canned numbers; one tiny real run checks the files, the labels and
that every figure is derived from the run, not typed in. Timings themselves are machine-dependent and never asserted.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/load/test_b84_bench.py
"""

from __future__ import annotations

import getpass
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "tools" / "bench_load.py"
COMMITTED_JSON = REPO / "evals" / "load" / "bench_report.json"
COMMITTED_MD = REPO / "evals" / "load" / "bench_report.md"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bench_load_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["bench_load_under_test"] = module
    spec.loader.exec_module(module)
    return module


bench = _load()


def test_b84_bench_percentiles_are_nearest_rank_and_empty_is_none() -> None:
    values = [float(i) for i in range(1, 101)]
    assert bench.percentile(values, 50) == 50.0
    assert bench.percentile(values, 95) == 95.0
    assert bench.percentile(values, 99) == 99.0
    assert bench.percentile(values, 100) == 100.0
    assert bench.percentile([7.0], 99) == 7.0
    assert bench.percentile([], 50) is None
    assert bench.percentile([3.0, 1.0, 2.0], 50) == 2.0  # sorts for itself


def test_b84_bench_latency_table_reports_count_and_milliseconds() -> None:
    table = bench.latency_table({"claim": [0.001, 0.002, 0.003, 0.004], "empty": []})
    assert table["claim"] == {"count": 4, "p50_ms": 2.0, "p95_ms": 4.0, "p99_ms": 4.0, "max_ms": 4.0, "mean_ms": 2.5}
    assert table["empty"]["count"] == 0 and table["empty"]["p50_ms"] is None


def test_b84_bench_markdown_carries_the_honest_labels_and_never_invents_a_cell() -> None:
    scenario = {
        "name": "faulty-sequential",
        "mode": "sequential",
        "faults": True,
        "wall_s": 10.0,
        "jobs_created": 100,
        "done": 95,
        "dead": 5,
        "jobs_per_s": 10.0,
        "invariants": {"chain_breaks": 0, "cross_client_results": 0, "double_applies": 0, "lost_jobs": 0},
        "latency_ms": {
            "claim": {"count": 4, "p50_ms": 2.0, "p95_ms": 4.0, "p99_ms": 4.0, "max_ms": 4.0, "mean_ms": 2.5},
            "fail": {"count": 0, "p50_ms": None, "p95_ms": None, "p99_ms": None, "max_ms": None, "mean_ms": None},
        },
    }
    report = bench.build_report(
        scenarios=[scenario],
        config={"seed": 84, "clients": 3, "jobs": 100},
        machine={"platform": "TestOS", "python": "3.12", "sqlite": "3.x", "cpu_count": 2},
        generated_utc="2026-10-27T12:00:00+00:00",
    )
    text = bench.render_markdown(report)
    assert "this machine only" in text.lower()
    assert "fixture-based" in text.lower()
    assert "not a capacity" in text.lower()
    assert "n/a" in text  # an operation that never ran shows n/a, not 0
    assert "10.0" in text and "TestOS" in text
    assert report["label"] in text


@pytest.mark.skipif(not COMMITTED_JSON.exists(), reason="no committed report yet")
def test_b84_bench_committed_report_is_labelled_and_internally_consistent() -> None:
    report = json.loads(COMMITTED_JSON.read_text(encoding="utf-8"))
    assert "this machine only" in report["label"].lower()
    assert "fixture-based" in report["basis"].lower()
    for s in report["scenarios"]:
        assert s["done"] + s["dead"] == s["jobs_created"]
        assert s["invariants"]["chain_breaks"] == 0 and s["invariants"]["cross_client_results"] == 0
        assert s["invariants"]["double_applies"] == 0 and s["invariants"]["lost_jobs"] == 0
        assert abs(s["jobs_per_s"] - s["jobs_created"] / s["wall_s"]) <= 0.01 * s["jobs_per_s"] + 0.01
    assert COMMITTED_MD.read_text(encoding="utf-8") == bench.render_markdown(
        report
    )  # the .md is rendered from the .json


def test_b84_bench_small_real_run_writes_both_files_with_derived_numbers(tmp_path: Path) -> None:
    code = bench.main(["--jobs", "40", "--clients", "8", "--threads", "2", "--out", str(tmp_path)])
    assert code == 0
    report = json.loads((tmp_path / "bench_report.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "bench_report.md").read_text(encoding="utf-8")
    assert [s["name"] for s in report["scenarios"]] == ["clean-sequential", "faulty-sequential", "faulty-threaded"]
    assert markdown == bench.render_markdown(report)
    for s in report["scenarios"]:
        assert s["done"] + s["dead"] == s["jobs_created"] >= 40
        assert s["invariants"] == {"chain_breaks": 0, "cross_client_results": 0, "double_applies": 0, "lost_jobs": 0}
        assert abs(s["jobs_per_s"] - s["jobs_created"] / s["wall_s"]) <= 0.01 * s["jobs_per_s"] + 0.01
    clean = report["scenarios"][0]
    assert clean["dead"] == 0 and clean["latency_ms"]["claim"]["count"] >= clean["jobs_created"]
    assert report["scenarios"][2]["mode"] == "threaded" and report["config"]["threads"] == 2
    # no machine or person identifiers beyond OS/Python/SQLite versions and the CPU count
    for secret in (os.environ.get("COMPUTERNAME", ""), getpass.getuser()):
        if len(secret) > 3:
            assert secret.lower() not in (markdown + json.dumps(report)).lower()


def test_b84_bench_refuses_nonsense_arguments(tmp_path: Path) -> None:
    for argv in (["--jobs", "0"], ["--clients", "0"], ["--threads", "0"], ["--jobs", "-5"]):
        with pytest.raises(SystemExit) as exc:
            bench.main([*argv, "--out", str(tmp_path)])
        assert exc.value.code == 2
