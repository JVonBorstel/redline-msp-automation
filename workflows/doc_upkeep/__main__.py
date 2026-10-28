"""Client documentation upkeep (B-59). Read-only: writes a report pair, changes no documentation.

    uv run --frozen python -m workflows.doc_upkeep report contoso-dental [--as-of 2026-10-23] [--out build/doc-upkeep]
    uv run --frozen python -m workflows.doc_upkeep report contoso-dental --fail-on-findings

Exit 0 = done, 1 = findings exist and --fail-on-findings was given, 2 = bad input.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from workflows.doc_upkeep.upkeep import DEFAULT_OUT_DIR, DocUpkeepError, build_report, write_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m workflows.doc_upkeep", description="Client documentation upkeep.")
    sub = parser.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report", help="compare one client's documentation with observed state; write draft proposals")
    rep.add_argument("client", help="client id, e.g. contoso-dental")
    rep.add_argument("--as-of", default=None, help="ISO date (default: the documentation fixture's pinned date)")
    rep.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    rep.add_argument("--fail-on-findings", action="store_true", help="exit 1 when any finding exists")
    args = parser.parse_args(argv)
    try:
        report = build_report(args.client, as_of=args.as_of)
        written = write_report(report, args.out)
    except (DocUpkeepError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    counts = ", ".join(f"{kind} {count}" for kind, count in report.summary.items())
    print(f"{report.client} as of {report.as_of}: {counts} (read-only; drafts in {written[1].parent})")
    return 1 if args.fail_on_findings and report.findings else 0


if __name__ == "__main__":
    sys.exit(main())
