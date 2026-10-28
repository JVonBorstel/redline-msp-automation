"""Eval gates (B-84): fail the run when a routing, guard or load result regresses below its threshold.

The thresholds are data: `evals/gates.json`. Each gate names a source (one of the eval runners below), a metric that
source reports, a comparison (`>=` or `<=`) and a threshold. This script gets the metrics, compares, prints one line per
gate and exits 0 only if every gate passed.

    uv run --frozen python tools/eval_gate.py                          # run every source, check every gate
    uv run --frozen python tools/eval_gate.py --source routing         # only the gates of one source (repeatable)
    uv run --frozen python tools/eval_gate.py --results metrics.json   # gate on metrics a CI step already produced
    uv run --frozen python tools/eval_gate.py --json                   # machine-readable verdicts

`--results` is a JSON object `{"<source>": {"<metric>": <number>}}`. In that mode no eval is run, and a gate whose
source or metric is absent FAILS: a missing result is never a pass. A source that crashes fails its gates and the
verdict names the exception class. Exit codes: 0 all gates passed, 1 at least one failed, 2 usage or config error.

Every number comes from this repo's synthetic fixtures and mock backends (fixture-based). A gate is a regression
alarm for those fixtures, not a quality target for real tickets or real models. Wall-clock timings are never gated: they
depend on the machine (see tools/bench_load.py).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DEFAULT_GATES = REPO / "evals" / "gates.json"
OPS = (">=", "<=")
_GATE_KEYS = {"id", "workflow", "source", "metric", "op", "threshold", "why"}
_TOP_KEYS = {"version", "basis", "gates", "note"}


class GateConfigError(ValueError):
    """The gate file or the results file is not usable."""


@dataclass(frozen=True)
class Gate:
    id: str
    workflow: str
    source: str
    metric: str
    op: str
    threshold: float
    why: str


@dataclass(frozen=True)
class Verdict:
    gate: Gate
    value: float | None
    passed: bool
    reason: str


# ---------------------------------------------------------------------------------------------------------------
# metric sources (each returns {metric: number}); imports are lazy so --results mode loads no eval code
# ---------------------------------------------------------------------------------------------------------------


def routing_metrics(backends_path: Path | None = None) -> dict[str, float]:
    from evals.routing.backends import DEFAULT_BACKENDS_PATH, TIERS
    from evals.routing.run import evaluate

    result = evaluate(backends_path=backends_path or DEFAULT_BACKENDS_PATH)

    def share(hits: int, total: int) -> float:
        return hits / total if total else 0.0

    metrics = {
        "cascade_accuracy_in_sample": share(sum(r.correct for r in result.routed), len(result.routed)),
        "cascade_accuracy_holdout": share(sum(r.correct for r in result.holdout_routed), len(result.holdout_routed)),
        "cascade_cost_vs_always_strong": share(
            int(result.cascade_cost * 1000), int(result.always_cost["strong"] * 1000)
        ),
    }
    for tier in TIERS:
        metrics[f"{tier}_accuracy"] = share(
            sum(r.decisions[tier].category == r.gold for r in result.rows), len(result.rows)
        )
    return metrics


def injection_metrics() -> dict[str, float]:
    from evals.injection.report import evaluate, load_corpus

    score, _ = evaluate(load_corpus())
    metrics: dict[str, float] = {"false_positives": score.fp, "false_negatives": score.fn}
    if score.precision is not None:
        metrics["precision"] = score.precision
    if score.recall is not None:
        metrics["recall"] = score.recall
    return metrics


def redaction_metrics() -> dict[str, float]:
    from evals.redaction.report import evaluate

    total = evaluate().total
    tickets = max(total.tickets, 1)
    return {
        "phi_npi_leaked": total.leaked["phi-npi"],
        "pii_leaked": total.leaked["pii"],
        "hosted_route_refused_rate": total.hosted_refused / tickets,
        "local_route_ok_rate": total.local_ok / tickets,
    }


def phishing_metrics() -> dict[str, float]:
    from evals.phishing.report import evaluate

    result = evaluate()
    per_client: dict[str, tuple[int, int]] = result["per_client"]  # type: ignore[assignment]
    reports = sum(n for n, _ in per_client.values())
    correct = sum(c for _, c in per_client.values())
    corpus: dict[str, list[int]] = result["corpus"]  # type: ignore[assignment]
    injected, benign = corpus["injection"], corpus["benign"]
    return {
        "verdict_accuracy": correct / reports if reports else 0.0,
        "corpus_injection_flag_rate": injected[1] / injected[0] if injected[0] else 0.0,
        "corpus_benign_flagged": benign[1],
    }


def load_metrics() -> dict[str, float]:
    """A seeded load run at gate size (the 10,000-call test's code, 120 calls). Invariants only, no timings."""
    from evals.load.harness import STANDARD_PLAN, LoadConfig, run_simulation

    cfg = LoadConfig(seed=84, clients=20, jobs=120, workers=8, plan=STANDARD_PLAN)
    with tempfile.TemporaryDirectory(prefix="b84-gate-") as tmp:
        report = run_simulation(Path(tmp), cfg)
    return {
        "finished": 1.0 if report.finished else 0.0,
        "chain_breaks": report.chain_breaks,
        "cross_client_results": report.cross_client_results,
        "double_applies": report.double_applies,
        "lost_jobs": report.lost_jobs,
        "audit_count_mismatches": report.audit_count_mismatches,
        "oracle_mismatches": report.oracle_mismatches,
        "submission_violations": report.submission_violations,
    }


SOURCES: dict[str, Callable[[], dict[str, float]]] = {
    "routing": routing_metrics,
    "injection": injection_metrics,
    "redaction": redaction_metrics,
    "phishing": phishing_metrics,
    "load": load_metrics,
}


# ---------------------------------------------------------------------------------------------------------------
# gates
# ---------------------------------------------------------------------------------------------------------------


def _number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def parse_gates(data: object) -> list[Gate]:
    if not isinstance(data, dict):
        raise GateConfigError("the gate file must be a JSON object")
    if set(data) - _TOP_KEYS or not {"version", "basis", "gates"} <= set(data):
        raise GateConfigError("the gate file needs exactly: version, basis, gates (and optionally note)")
    if data["version"] != 1:
        raise GateConfigError(f"unsupported gate file version {data['version']!r}")
    if not isinstance(data["basis"], str) or "fixture-based" not in data["basis"]:
        raise GateConfigError("basis must be a string that says the numbers are fixture-based")
    raw = data["gates"]
    if not isinstance(raw, list) or not raw:
        raise GateConfigError("gates must be a non-empty list")
    gates: list[Gate] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != _GATE_KEYS:
            raise GateConfigError(f"every gate needs exactly these keys: {sorted(_GATE_KEYS)}")
        for key in ("id", "workflow", "source", "metric", "op", "why"):
            if not isinstance(item[key], str) or not item[key].strip():
                raise GateConfigError(f"gate {item.get('id')!r}: {key} must be a non-empty string")
        if item["id"] in seen:
            raise GateConfigError(f"duplicate gate id {item['id']!r}")
        seen.add(item["id"])
        if item["op"] not in OPS:
            raise GateConfigError(f"gate {item['id']!r}: op must be one of {OPS}")
        if item["source"] not in SOURCES:
            raise GateConfigError(f"gate {item['id']!r}: unknown source {item['source']!r} (known: {sorted(SOURCES)})")
        if not _number(item["threshold"]):
            raise GateConfigError(f"gate {item['id']!r}: threshold must be a finite number")
        gates.append(Gate(**{**item, "threshold": float(item["threshold"])}))
    return gates


def load_gates(path: Path = DEFAULT_GATES) -> list[Gate]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GateConfigError(f"cannot read the gate file {path}: {exc.__class__.__name__}") from exc
    try:
        return parse_gates(json.loads(text))
    except json.JSONDecodeError as exc:
        raise GateConfigError(f"the gate file {path} is not JSON: {exc.msg}") from exc


def _judge(gate: Gate, value: object) -> Verdict:
    if not _number(value):
        return Verdict(gate, None, False, f"value is not a finite number: {value!r}")
    number = float(value)  # type: ignore[arg-type]
    passed = number >= gate.threshold if gate.op == ">=" else number <= gate.threshold
    return Verdict(gate, number, passed, "" if passed else f"{number:g} is not {gate.op} {gate.threshold:g}")


def evaluate(gates: Sequence[Gate], results: Mapping[str, object]) -> list[Verdict]:
    """Compare each gate with the metrics in `results` ({source: {metric: value}} or {source: error text})."""
    verdicts: list[Verdict] = []
    for gate in gates:
        source = results.get(gate.source)
        if isinstance(source, str):
            verdicts.append(Verdict(gate, None, False, source))
        elif not isinstance(source, Mapping):
            verdicts.append(Verdict(gate, None, False, f"no result for source {gate.source!r}"))
        elif gate.metric not in source:
            verdicts.append(Verdict(gate, None, False, f"no value for metric {gate.metric!r}"))
        else:
            verdicts.append(_judge(gate, source[gate.metric]))
    return verdicts


def collect(sources: Sequence[str]) -> dict[str, object]:
    """Run the named sources once each. A crash becomes that source's error text, which fails its gates."""
    results: dict[str, object] = {}
    for name in sources:
        try:
            results[name] = SOURCES[name]()
        except Exception as exc:  # noqa: BLE001 - any failure of an eval is a failed gate, never a skipped one
            results[name] = f"source {name!r} failed: {exc.__class__.__name__}"
    return results


def run(gates: Sequence[Gate]) -> list[Verdict]:
    return evaluate(gates, collect(sorted({g.source for g in gates})))


# ---------------------------------------------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------------------------------------------


def _read_results(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateConfigError(f"cannot read results file {path}: {exc.__class__.__name__}") from exc
    if not isinstance(data, dict):
        raise GateConfigError("the results file must be a JSON object {source: {metric: number}}")
    return data


def _render(basis: str, verdicts: Sequence[Verdict]) -> str:
    lines = [f"Eval gates ({basis})"]
    width = max(len(v.gate.id) for v in verdicts)
    for v in verdicts:
        shown = "n/a" if v.value is None else f"{v.value:.4f}".rstrip("0").rstrip(".") or "0"
        status = "PASS" if v.passed else "FAIL"
        extra = f"  ({v.reason})" if v.reason else ""
        lines.append(f"  {status}  {v.gate.id:<{width}}  {shown} {v.gate.op} {v.gate.threshold:g}{extra}")
    failed = sum(not v.passed for v in verdicts)
    lines.append(f"{len(verdicts)} gates, {len(verdicts) - failed} passed, {failed} failed")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools/eval_gate.py", description="Fail when an eval result regresses.")
    parser.add_argument("--gates", type=Path, default=DEFAULT_GATES, help="gate definitions (default evals/gates.json)")
    parser.add_argument("--results", type=Path, help="JSON {source: {metric: number}}; no eval is run")
    parser.add_argument("--source", action="append", default=[], help="check only this source's gates (repeatable)")
    parser.add_argument("--json", action="store_true", help="print the verdicts as JSON")
    args = parser.parse_args(argv)
    try:
        gates = load_gates(args.gates)
        for name in args.source:
            if name not in SOURCES:
                raise GateConfigError(f"unknown source {name!r} (known: {sorted(SOURCES)})")
        if args.source:
            gates = [g for g in gates if g.source in args.source]
            if not gates:
                raise GateConfigError("no gate uses the sources you named")
        basis = str(json.loads(args.gates.read_text(encoding="utf-8"))["basis"])
        verdicts = evaluate(gates, _read_results(args.results)) if args.results else run(gates)
    except GateConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    passed = all(v.passed for v in verdicts)
    if args.json:
        payload = {
            "basis": basis,
            "passed": passed,
            "gates": [
                {
                    "id": v.gate.id,
                    "workflow": v.gate.workflow,
                    "source": v.gate.source,
                    "metric": v.gate.metric,
                    "op": v.gate.op,
                    "threshold": v.gate.threshold,
                    "value": v.value,
                    "passed": v.passed,
                    "reason": v.reason,
                }
                for v in verdicts
            ],
        }
        print(json.dumps(payload, indent=2))
    else:
        print(_render(basis, verdicts))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
