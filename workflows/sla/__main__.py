"""SLA breach watch and backlog grooming report for the synthetic ticket fixtures (B-24). Nothing is sent.

    uv run --frozen python -m workflows.sla --as-of 2026-10-16T23:00:00Z --hours 4 --state .tmp/demo

Writes <state>/sla/report.json, report.md and drafts/<ticket>.followup.md, checks the report against the fixtures
(C-21) and prints report.md (or the JSON with --json). A person reads the report and sends any draft (HO-9).
If config/clients does not exist yet, synthetic mock PSA bindings are written under <state>/sla/clients/ and used.
Exit 0 = report written and reconciled, 1 = report does not reconcile, 2 = bad input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from adapters.binding import DEFAULT_CLIENT_DIR
from core.paths import REPO_ROOT
from workflows.sla.sla import (
    DEFAULT_TICKETS_DIR,
    DEFAULT_WAITING_HOURS,
    DEFAULT_WINDOW_HOURS,
    SlaError,
    collect,
    parse_time,
    render_markdown,
    validate_report,
    write_demo_bindings,
    write_report,
)

DEFAULT_STATE = REPO_ROOT / ".tmp" / "demo"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.sla",
        description="SLA breach watch and backlog grooming report (synthetic fixtures; never sends).",
    )
    parser.add_argument("--as-of", required=True, help="UTC time to judge from, e.g. 2026-10-16T23:00:00Z")
    parser.add_argument("--hours", type=float, default=DEFAULT_WINDOW_HOURS, help="breach watch window (default 4)")
    parser.add_argument(
        "--waiting-hours", type=float, default=DEFAULT_WAITING_HOURS, help="waiting threshold (default 72)"
    )
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE, help="state folder (default .tmp/demo)")
    parser.add_argument("--tickets", type=Path, default=DEFAULT_TICKETS_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    try:
        as_of = parse_time(args.as_of)
        config_dir = DEFAULT_CLIENT_DIR
        if not config_dir.is_dir():
            config_dir = args.state / "sla" / "clients"
            write_demo_bindings(config_dir)
        report = collect(
            as_of=as_of,
            tickets_dir=args.tickets,
            config_dir=config_dir,
            window_hours=args.hours,
            waiting_hours=args.waiting_hours,
        )
        problems = validate_report(report, tickets_dir=args.tickets)
        folder = write_report(report, args.state)
    except SlaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({k: v for k, v in report.items() if k != "drafts"}, indent=2))
    else:
        print(render_markdown(report).rstrip("\n"))
    print(f"report: {folder}", file=sys.stderr)
    for problem in problems:
        print(f"does not reconcile: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
