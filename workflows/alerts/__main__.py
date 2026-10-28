"""Group one client's alerts and print the on-call summary (B-43). Reads fixtures; writes nothing; acts on nothing.

    uv run --frozen python -m workflows.alerts contoso-dental [--since 2026-10-20T00:00:00Z] [--after-hours] [--text]

Prints JSON (or plain text with --text). Alert text appears only inside untrusted-data blocks.
Exit 0 = ran, 2 = bad input. Synthetic data only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from adapters.alerts import DEFAULT_ALERTS_DIR, AlertsMock
from adapters.base import AdapterError
from adapters.binding import BoundBinding
from workflows.alerts.alerts import (
    DEFAULT_CONFIG_PATH,
    AlertsError,
    build_summary,
    load_config,
    pool_from_adapter,
    render_text,
    utc,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.alerts",
        description="Group one client's alerts and print the on-call summary (synthetic data; never acts on an alert).",
    )
    parser.add_argument("client", help="client id, e.g. contoso-dental")
    parser.add_argument("--since", help="only alerts at or after this UTC time")
    parser.add_argument("--until", help="only alerts at or before this UTC time")
    parser.add_argument("--after-hours", action="store_true", help="only groups that began outside business hours")
    parser.add_argument("--text", action="store_true", help="plain text instead of JSON")
    parser.add_argument("--alerts", type=Path, default=DEFAULT_ALERTS_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        # The mock fixture names its own account id, so the CLI reads it to build the one-client binding.
        account = json.loads((args.alerts / f"{args.client}.json").read_text(encoding="utf-8"))["account_id"]
        adapter = AlertsMock(args.client, BoundBinding(args.client, "alerts", "mock", str(account)), args.alerts)
        since = utc(args.since) if args.since else None
        until = utc(args.until) if args.until else None
        pool = pool_from_adapter(adapter, since=since, until=until)
        summary = build_summary(
            args.client,
            pool.alerts,
            load_config(args.config),
            since=since,
            until=until,
            after_hours_only=args.after_hours,
        )
    except (AlertsError, AdapterError, OSError, ValueError, KeyError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(render_text(summary) if args.text else json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
