"""KEV relevance report for one or more clients (B-47). Reads fixtures; writes nothing; deploys nothing.

    uv run --frozen python -m workflows.advisories [client ...] [--as-of 2026-10-21T12:00:00Z]

Prints JSON: affected clients and devices per CVE, a ranked list with every factor shown, and the emergency-patch
list with proposed change windows. Exit 0 = ran, 2 = bad input. With no client, every client in the fixtures is checked.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from workflows.advisories.advisories import DEFAULT_FIXTURES_DIR, AdvisoriesError, report_for, utc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.advisories",
        description="Match the (synthetic) KEV feed to client inventories. Report only; never deploys anything.",
    )
    parser.add_argument("clients", nargs="*", help="client ids, e.g. contoso-dental (default: all in the fixtures)")
    parser.add_argument("--as-of", help="UTC time to propose windows from (default: the feed's as_of)")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES_DIR, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        report = report_for(args.clients or None, args.fixtures, utc(args.as_of) if args.as_of else None)
    except AdvisoriesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
