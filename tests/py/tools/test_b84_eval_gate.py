"""B-84 eval gates: evals/gates.json and tools/eval_gate.py (specs/B-84.md, acceptance B84-1).

Offline. Gate logic is tested on hand-made results; the real eval sources are run once each (they are small, fixture
based and deterministic); a degraded copy of the routing backends proves a regression turns the gate red.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/tools/test_b84_eval_gate.py
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[3]
GATES = REPO / "evals" / "gates.json"
SCRIPT = REPO / "tools" / "eval_gate.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eval_gate_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["eval_gate_under_test"] = module
    spec.loader.exec_module(module)
    return module


gate = _load()


def write_gates(tmp_path: Path, gates: list[dict[str, object]]) -> Path:
    path = tmp_path / "gates.json"
    path.write_text(json.dumps({"version": 1, "basis": "fixture-based", "gates": gates}), encoding="utf-8")
    return path


def one(op: str = ">=", threshold: float = 0.9, metric: str = "acc", source: str = "routing") -> dict[str, object]:
    return {"id": "t.acc", "workflow": "t", "source": source, "metric": metric, "op": op, "threshold": threshold}


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, repo script, current interpreter
        [sys.executable, str(SCRIPT), *args], cwd=REPO, capture_output=True, text=True, timeout=300, check=False
    )


# --- the committed gate definitions ----------------------------------------------------------------------------


def test_b84_1_committed_gates_load_and_cover_routing_and_guard_evals() -> None:
    gates = gate.load_gates(GATES)
    assert len(gates) == len({g.id for g in gates})
    assert {g.source for g in gates} >= {"routing", "injection", "redaction", "phishing", "load"}
    assert all(g.op in (">=", "<=") for g in gates)
    # every accuracy-like gate sits below 1.0 only by a stated margin; every count gate is a hard zero
    for g in gates:
        assert g.why, f"{g.id} says nothing about why its threshold is where it is"
    data = json.loads(GATES.read_text(encoding="utf-8"))
    assert "fixture-based" in data["basis"]


def test_b84_1_committed_gates_pass_on_the_committed_evals() -> None:
    result = run_cli("--source", "routing", "--source", "injection", "--source", "redaction", "--source", "phishing")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FAIL" not in result.stdout
    assert "fixture-based" in result.stdout


def test_b84_1_load_source_gates_pass_on_a_seeded_run() -> None:
    result = run_cli("--source", "load")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "load.chain_breaks" in result.stdout


# --- the comparison rules ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("op", "threshold", "value", "passed"),
    [
        (">=", 0.9, 0.9, True),
        (">=", 0.9, 0.8999, False),
        (">=", 0.9, 1.0, True),
        ("<=", 0, 0, True),
        ("<=", 0, 1, False),
        ("<=", 0.25, 0.2500001, False),
    ],
)
def test_b84_1_comparison_is_exact_at_the_threshold(op: str, threshold: float, value: float, passed: bool) -> None:
    g = gate.parse_gates({"version": 1, "basis": "fixture-based", "gates": [{**one(op, threshold), "why": "w"}]})[0]
    (verdict,) = gate.evaluate([g], {"routing": {"acc": value}})
    assert verdict.passed is passed


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), True, "0.99", [0.99]])
def test_b84_1_a_missing_or_unusable_value_fails_it_is_never_skipped(bad: object) -> None:
    g = gate.parse_gates({"version": 1, "basis": "fixture-based", "gates": [{**one(), "why": "w"}]})[0]
    (verdict,) = gate.evaluate([g], {"routing": {"acc": bad}})
    assert verdict.passed is False and verdict.reason
    (absent,) = gate.evaluate([g], {"routing": {}})
    assert absent.passed is False and "no value" in absent.reason
    (no_source,) = gate.evaluate([g], {})
    assert no_source.passed is False


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(version=2),
        lambda d: d["gates"].append(dict(d["gates"][0])),  # duplicate id
        lambda d: d["gates"][0].update(op="=="),
        lambda d: d["gates"][0].update(source="nope"),
        lambda d: d["gates"][0].update(threshold="0.9"),
        lambda d: d["gates"][0].update(threshold=True),
        lambda d: d["gates"][0].update(threshold=float("nan")),
        lambda d: d["gates"][0].pop("why"),
        lambda d: d["gates"][0].update(surprise=1),
        lambda d: d.update(gates=[]),
        lambda d: d.pop("basis"),
        lambda d: d.update(basis="trust me"),
    ],
)
def test_b84_1_a_malformed_gate_file_is_a_config_error_not_a_pass(mutate: object) -> None:
    data = {"version": 1, "basis": "fixture-based", "gates": [{**one(), "why": "w"}]}
    mutate(data)  # type: ignore[operator]
    with pytest.raises(gate.GateConfigError):
        gate.parse_gates(data)


# --- the CLI: usable locally and from CI -------------------------------------------------------------------------


def test_b84_1_cli_passes_on_good_results_and_fails_below_a_gate(tmp_path: Path) -> None:
    gates = write_gates(tmp_path, [{**one(), "why": "w"}])
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps({"routing": {"acc": 0.95}}), encoding="utf-8")
    bad.write_text(json.dumps({"routing": {"acc": 0.5}}), encoding="utf-8")
    ok = run_cli("--gates", str(gates), "--results", str(good))
    assert ok.returncode == 0 and "PASS" in ok.stdout and "t.acc" in ok.stdout
    red = run_cli("--gates", str(gates), "--results", str(bad))
    assert red.returncode == 1 and "FAIL" in red.stdout and "t.acc" in red.stdout and "0.5" in red.stdout


def test_b84_1_cli_json_output_and_usage_errors(tmp_path: Path) -> None:
    gates = write_gates(tmp_path, [{**one(), "why": "w"}])
    results = tmp_path / "r.json"
    results.write_text(json.dumps({"routing": {"acc": 0.95}}), encoding="utf-8")
    out = run_cli("--gates", str(gates), "--results", str(results), "--json")
    payload = json.loads(out.stdout)
    assert payload["passed"] is True and payload["gates"][0]["id"] == "t.acc" and "basis" in payload
    assert run_cli("--gates", str(tmp_path / "missing.json"), "--results", str(results)).returncode == 2
    assert run_cli("--gates", str(gates), "--results", str(tmp_path / "missing.json")).returncode == 2
    (tmp_path / "junk.json").write_text("{not json", encoding="utf-8")
    assert run_cli("--gates", str(gates), "--results", str(tmp_path / "junk.json")).returncode == 2
    assert run_cli("--gates", str(gates), "--results", str(results), "--source", "nope").returncode == 2


def test_b84_1_results_mode_never_runs_an_eval(tmp_path: Path) -> None:
    # a gate on a source absent from the results file fails; it does not fall back to running the eval
    gates = write_gates(tmp_path, [{**one(source="injection", metric="recall"), "why": "w"}])
    results = tmp_path / "r.json"
    results.write_text(json.dumps({"routing": {"acc": 1}}), encoding="utf-8")
    red = run_cli("--gates", str(gates), "--results", str(results))
    assert red.returncode == 1 and "no result" in red.stdout


def test_b84_1_a_crashing_source_fails_its_gates_and_names_the_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> dict[str, float]:
        raise RuntimeError("synthetic crash")

    monkeypatch.setitem(gate.SOURCES, "routing", boom)
    g = gate.parse_gates({"version": 1, "basis": "fixture-based", "gates": [{**one(), "why": "w"}]})
    verdicts = gate.run(g)
    assert verdicts[0].passed is False and "RuntimeError" in verdicts[0].reason


# --- a real regression turns the real gate red -------------------------------------------------------------------


def test_b84_1_a_degraded_routing_backend_fails_the_committed_routing_gates(tmp_path: Path) -> None:
    gates = [g for g in gate.load_gates(GATES) if g.source == "routing"]
    healthy = gate.evaluate(gates, {"routing": gate.routing_metrics()})
    assert all(v.passed for v in healthy)
    backends = json.loads((REPO / "evals" / "routing" / "mock_backends.json").read_text(encoding="utf-8"))
    for tier in ("small", "strong"):  # the model tiers start answering "network" to everything
        for rule in backends["tiers"][tier]["rules"]:
            rule["category"] = "network"
        backends["tiers"][tier]["fallback"]["category"] = "network"
    degraded_path = tmp_path / "degraded.json"
    degraded_path.write_text(json.dumps(backends), encoding="utf-8")
    degraded = gate.evaluate(gates, {"routing": gate.routing_metrics(backends_path=degraded_path)})
    assert any(not v.passed for v in degraded)


def test_b84_1_a_weakened_injection_detector_corpus_result_fails_the_guard_gate() -> None:
    gates = [g for g in gate.load_gates(GATES) if g.source == "injection"]
    metrics = gate.injection_metrics()
    assert all(v.passed for v in gate.evaluate(gates, {"injection": metrics}))
    worse = {**metrics, "recall": metrics["recall"] - 0.2, "false_negatives": metrics["false_negatives"] + 3}
    assert any(not v.passed for v in gate.evaluate(gates, {"injection": worse}))


def test_b84_1_the_proposed_ci_step_matches_the_script_and_touches_no_protected_file() -> None:
    proposal = (REPO / "docs" / "changes" / "B-84.ci-eval-gate.yml").read_text(encoding="utf-8")
    assert "tools/eval_gate.py" in proposal and "uv run --frozen" in proposal
    assert "PROPOSAL" in proposal.splitlines()[0]
    assert not (REPO / ".github" / "workflows" / "eval-gate.yml").exists()  # a human applies it
