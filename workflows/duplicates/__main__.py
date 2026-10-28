"""Group one client's open tickets into duplicates and outages (B-23). Reads fixtures; writes nothing; links nothing.

    uv run --frozen python -m workflows.duplicates fabrikam-capital [--as-of 2026-10-16T23:00:00Z] [--history]

Prints JSON: duplicate groups, outage groups and the tickets a person must read (injection-flagged), as ids only.
Exit 0 = ran, 2 = bad input. A lead approves any real link through the queue (`ticket.link`, R1).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from workflows.duplicates.duplicates import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_TICKETS_DIR,
    DuplicatesError,
    group_client,
    load_config,
    load_tickets,
    summary,
    utc,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.duplicates",
        description="Suggest duplicate and outage groups for one client (synthetic data; never links anything).",
    )
    parser.add_argument("client", help="client id, e.g. fabrikam-capital")
    parser.add_argument("--as-of", help="only tickets created at or before this UTC time (default: all)")
    parser.add_argument("--history", action="store_true", help="include resolved tickets (default: open only)")
    parser.add_argument("--tickets", type=Path, default=DEFAULT_TICKETS_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        grouping = group_client(
            args.client,
            load_tickets(args.tickets),
            load_config(args.config),
            open_only=not args.history,
            as_of=utc(args.as_of) if args.as_of else None,
        )
    except DuplicatesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary(grouping), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
