"""Licence true-up report (B-75). Writes a report file; buys, cancels, assigns and removes nothing.

    uv run --frozen python -m workflows.licensing report contoso-dental --as-of 2026-10-22 --within-days 90

Writes build/licensing/<as_of>/<client>.json, .md and .json.sha256. Without --as-of the licensing fixture's pinned date
is used, never the clock. Exit 0 = written, 2 = bad input (nothing written).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from workflows.licensing.report import (
    DEFAULT_DEVICE_DAYS,
    DEFAULT_INACTIVE_DAYS,
    DEFAULT_OUT_DIR,
    DEFAULT_WITHIN_DAYS,
    LicensingError,
    write_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m workflows.licensing", description="Licence true-up report.")
    sub = parser.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report", help="write the true-up report for one client")
    rep.add_argument("client", help="client id, e.g. contoso-dental")
    rep.add_argument("--as-of", default=None, help="ISO date (default: the fixture's pinned date)")
    rep.add_argument("--within-days", type=int, default=DEFAULT_WITHIN_DAYS, help="renewals due this many days ahead")
    rep.add_argument("--inactive-days", type=int, default=DEFAULT_INACTIVE_DAYS, help="no sign-in this long = unused")
    rep.add_argument("--device-days", type=int, default=DEFAULT_DEVICE_DAYS, help="no check-in this long = stale")
    rep.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    try:
        written = write_report(
            args.client,
            args.as_of,
            out_dir=args.out,
            within_days=args.within_days,
            inactive_days=args.inactive_days,
            device_days=args.device_days,
        )
    except LicensingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "json": str(written.json_path),
                "markdown": str(written.markdown_path),
                "sha256": written.sha256,
                "proposals": written.proposals,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
