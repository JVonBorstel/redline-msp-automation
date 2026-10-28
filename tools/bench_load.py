"""Benchmark the B-84 load harness and record throughput and latency in a labelled report (fixture-based).

    uv run --frozen python tools/bench_load.py                          # 1,000 calls, 100 clients, 4 threads
    uv run --frozen python tools/bench_load.py --jobs 10000 --clients 300  # B84-2 size, minutes
    uv run --frozen python tools/bench_load.py --out some/folder        # default folder is evals/load/

It runs three scenarios on fresh temporary SQLite files: `clean-sequential` (no injected faults), `faulty-sequential`
(the shared fault mix, one driver) and `faulty-threaded` (same mix, N threads contending for one database). For each it
writes the invariants (chain breaks, cross-client results, double applies, lost jobs: all must be 0), wall time,
end-to-end jobs per second and p50/p95/p99/max latency of each store call, to `bench_report.json` and `bench_report.md`.

HONEST LABEL: the numbers are what this machine did, once, on the run that wrote them. They are not a capacity claim
for any deployment, they have no variance estimate, and the adapter is a local SQLite file standing in for an external
system. Nothing here gates a build: timings depend on the disk. The gate (tools/eval_gate.py) uses invariants only.
Exit codes: 0 done and every invariant held, 1 an invariant broke or a run did not finish, 2 bad arguments.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import platform
import sqlite3
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from evals.load.harness import STANDARD_PLAN, FaultPlan, LoadConfig, LoadReport, Timings, run_simulation, run_threaded  # noqa: E402

DEFAULT_OUT = REPO / "evals" / "load"
OPS = ("enqueue", "claim", "adapter", "audit", "complete", "fail")
INVARIANTS = ("chain_breaks", "cross_client_results", "double_applies", "lost_jobs")

LABEL = (
    "MEASURED ON THIS MACHINE ONLY, ONCE. Synthetic harness on temporary SQLite files; fixture-based; "
    "not a capacity claim for any real deployment."
)
BASIS = (
    "fixture-based: synthetic clients and lever calls, a seeded fault plan, a local SQLite file standing in for the "
    "external adapter, stores in synchronous=FULL mode (one fsync per commit)."
)
CAVEATS = (
    "One run per scenario, no repeats, no variance estimate: treat differences under about 2x as noise.",
    "Latency is wall time around each store call (time.perf_counter), including the fsync. It depends on this "
    "machine's disk and the temp folder's filesystem; a CI runner or a server will differ, possibly a lot.",
    "The adapter is a local SQLite file with synchronous=OFF, so its latency says nothing about a real adapter "
    "(Graph, PSA, RMM) which would add network time and rate limits.",
    "Backoff and lease waits run on a simulated clock and cost no wall time, so end-to-end jobs per second is "
    "the cost of the work, not what a deployment waiting out real backoff would see.",
    "SQLite allows one writer at a time. The threaded scenario shows lock contention on one file; it is not a "
    "claim that more threads give more throughput.",
    "The real LeverRunner (identity, approval and registry checks) is not in this loop.",
    "Not measured: memory, CPU use, database size, multi-process contention on this scale, Linux behaviour.",
)


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile (q in 0..100) of the values, or None when there are none."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def _ms(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds * 1000, 3)


def latency_table(samples: Mapping[str, Sequence[float]]) -> dict[str, dict[str, Any]]:
    table: dict[str, dict[str, Any]] = {}
    for name, values in samples.items():
        table[name] = {
            "count": len(values),
            "p50_ms": _ms(percentile(values, 50)),
            "p95_ms": _ms(percentile(values, 95)),
            "p99_ms": _ms(percentile(values, 99)),
            "max_ms": _ms(max(values)) if values else None,
            "mean_ms": _ms(sum(values) / len(values)) if values else None,
        }
    return table


def run_scenario(name: str, mode: str, cfg: LoadConfig, workdir: Path, threads: int) -> dict[str, Any]:
    timings = Timings()
    began = time.perf_counter()
    if mode == "threaded":
        report: LoadReport = run_threaded(workdir, cfg, threads, timings)
    else:
        report = run_simulation(workdir, cfg, timings)
    wall = time.perf_counter() - began
    samples = {op: timings.samples.get(op, []) for op in OPS}
    return {
        "name": name,
        "mode": mode,
        "faults": cfg.plan != FaultPlan(seed=cfg.plan.seed),
        "wall_s": round(wall, 3),
        "jobs_created": report.jobs_created,
        "done": report.done,
        "dead": report.dead,
        "finished": report.finished,
        "jobs_per_s": round(report.jobs_created / wall, 2) if wall > 0 else 0.0,
        "audit_records": report.audit_records,
        "adapter_deliveries": report.adapter_deliveries,
        "invariants": {key: getattr(report, key) for key in INVARIANTS},
        "latency_ms": latency_table(samples),
    }


def build_report(
    *, scenarios: Sequence[Mapping[str, Any]], config: Mapping[str, Any], machine: Mapping[str, Any], generated_utc: str
) -> dict[str, Any]:
    return {
        "label": LABEL,
        "basis": BASIS,
        "generated_utc": generated_utc,
        "machine": dict(machine),
        "config": dict(config),
        "scenarios": [dict(s) for s in scenarios],
        "caveats": list(CAVEATS),
    }


def _cell(value: object) -> str:
    return "n/a" if value is None else str(value)


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Load benchmark (B-84)",
        "",
        f"> **{report['label']}**",
        ">",
        f"> Basis: {report['basis']}",
        "",
        f"Generated {report['generated_utc']} by `tools/bench_load.py`. Machine: "
        + ", ".join(f"{k} {v}" for k, v in report["machine"].items())
        + ".",
        "",
        "Config: " + ", ".join(f"{k} {v}" for k, v in report["config"].items()) + ".",
        "",
        "## Results",
        "",
        "| Scenario | Mode | Faults | Calls | Done | Dead-lettered | Wall (s) | Calls per second | Chain breaks | "
        "Cross-client | Double applies | Lost |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in report["scenarios"]:
        inv = s["invariants"]
        lines.append(
            f"| {s['name']} | {s['mode']} | {'yes' if s['faults'] else 'no'} | {s['jobs_created']} | {s['done']} | "
            f"{s['dead']} | {s['wall_s']} | {s['jobs_per_s']} | {inv['chain_breaks']} | "
            f"{inv['cross_client_results']} | {inv['double_applies']} | {inv['lost_jobs']} |"
        )
    lines += [
        "",
        "Calls per second is jobs created divided by total wall time of the scenario, which includes submitting, "
        "working, and verifying every audit chain.",
    ]
    for s in report["scenarios"]:
        lines += [
            "",
            f"## Latency per store call: {s['name']}",
            "",
            "| Call | Count | p50 (ms) | p95 (ms) | p99 (ms) | Max (ms) | Mean (ms) |",
            "|---|---|---|---|---|---|---|",
        ]
        for op, row in s["latency_ms"].items():
            lines.append(
                f"| {op} | {row['count']} | {_cell(row['p50_ms'])} | {_cell(row['p95_ms'])} | {_cell(row['p99_ms'])} | "
                f"{_cell(row['max_ms'])} | {_cell(row['mean_ms'])} |"
            )
    lines += ["", "## Read this before quoting a number", ""]
    lines += [f"- {c}" for c in report["caveats"]]
    return "\n".join(lines) + "\n"


def machine_info() -> dict[str, Any]:
    """OS, Python and SQLite versions and the CPU count. No host name, user name or path."""
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "cpu_count": os.cpu_count(),
    }


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools/bench_load.py", description="Benchmark the B-84 load harness.")
    parser.add_argument("--jobs", type=_positive, default=1000, help="lever calls to submit (default 1000)")
    parser.add_argument("--clients", type=_positive, default=100, help="clients (default 100)")
    parser.add_argument("--threads", type=_positive, default=4, help="threads in the threaded scenario (default 4)")
    parser.add_argument("--seed", type=int, default=84)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="folder for bench_report.json and .md")
    args = parser.parse_args(argv)

    base = LoadConfig(seed=args.seed, clients=args.clients, jobs=args.jobs, workers=8)
    faulty = dataclasses.replace(base, plan=dataclasses.replace(STANDARD_PLAN, seed=args.seed))
    plan = [
        ("clean-sequential", "sequential", base),
        ("faulty-sequential", "sequential", faulty),
        (
            "faulty-threaded",
            "threaded",
            dataclasses.replace(faulty, lease_s=300.0),
        ),  # a long lease: only crashes expire
    ]
    scenarios = []
    with tempfile.TemporaryDirectory(prefix="b84-bench-") as tmp:
        for name, mode, cfg in plan:
            print(f"running {name} ...", file=sys.stderr, flush=True)
            scenarios.append(run_scenario(name, mode, cfg, Path(tmp) / name, args.threads))
    report = build_report(
        scenarios=scenarios,
        config={"seed": args.seed, "clients": args.clients, "jobs": args.jobs, "threads": args.threads, "workers": 8},
        machine=machine_info(),
        generated_utc=datetime.now(UTC).replace(microsecond=0).isoformat(),
    )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "bench_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    (args.out / "bench_report.md").write_text(render_markdown(report), encoding="utf-8", newline="\n")
    print(render_markdown(report))
    broken = [s["name"] for s in scenarios if not s["finished"] or any(s["invariants"].values())]
    if broken:
        print(f"INVARIANT BROKEN OR RUN UNFINISHED: {', '.join(broken)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
