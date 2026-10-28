"""Backup coverage and DR plan review for one client (B-70). Reads a fixture; writes only the report pair.

    uv run --frozen python -m workflows.backup_coverage report contoso-dental [--as-of 2026-10-26] [--stale-months 12]
    uv run --frozen python -m workflows.backup_coverage verify build/backup-coverage/contoso-dental/contoso-dental.json

Exit 0 = done (verify: matches), 1 = verify mismatch, 2 = bad input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from workflows.backup_coverage.report import (
    DEFAULT_DATA_DIR,
    DEFAULT_OUT_DIR,
    BackupCoverageError,
    VerifyError,
    verify,
    write_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.backup_coverage",
        description="M365 backup coverage, retention, immutability and DR plan review (synthetic, read-only).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report", help="write the JSON and Markdown report for one client, each with a .sha256")
    rep.add_argument("client", help="client id, e.g. contoso-dental")
    rep.add_argument("--as-of", default=None, help="ISO date (default: the fixture's pinned date)")
    rep.add_argument("--stale-months", type=int, default=None, help="DR section age limit (default: the client's)")
    rep.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    rep.add_argument("--data", type=Path, default=DEFAULT_DATA_DIR, help=argparse.SUPPRESS)
    ver = sub.add_parser("verify", help="re-hash a report file against its .sha256")
    ver.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    if args.command == "verify":
        try:
            digest = verify(args.path)
        except VerifyError as exc:
            print(f"MISMATCH: {exc}", file=sys.stderr)
            return 1
        print(f"OK {digest}  {args.path.name}")
        return 0
    try:
        written = write_report(
            args.client, args.out, data_dir=args.data, as_of=args.as_of, stale_months=args.stale_months
        )
    except BackupCoverageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "json": str(written.json_path),
                "json_sha256": written.json_sha256,
                "markdown": str(written.md_path),
                "markdown_sha256": written.md_sha256,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
