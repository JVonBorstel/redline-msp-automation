"""Device reports for one client (B-64). Reads fixtures; writes only the report files; runs nothing.

    uv run --frozen python -m workflows.device_reports report contoso-dental [--as-of 2026-10-22T12:00:00Z] [--out DIR]
    uv run --frozen python -m workflows.device_reports verify build/device-reports/contoso-dental/2026-10-22.json

``report`` writes ``<client>/<date>.json`` and ``.md`` with a ``.sha256`` sidecar each and prints their hashes
and counts. ``verify`` re-checks both files. Exit 0 = ok, 1 = a file does not match its hash, 2 = bad input or an
adapter that is not configured.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from workflows.device_reports.reports import (
    DEFAULT_OUT_DIR,
    ReportError,
    build_client_report,
    parse_as_of,
    verify,
    write_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.device_reports",
        description="Device compliance, encryption, LAPS coverage and provisioning readiness (synthetic; read-only).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report", help="build and write one client's report")
    rep.add_argument("client", help="client id, e.g. contoso-dental")
    rep.add_argument("--as-of", help="report as at this UTC time (default: the RMM fixture's pinned time)")
    rep.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="output folder (default: build/device-reports)")
    rep.add_argument("--clients", type=Path, help="select adapters from the bindings in this config/clients folder")
    ver = sub.add_parser("verify", help="re-check a report's JSON and Markdown against their hashes")
    ver.add_argument("file", type=Path, help="the report's .json file")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            print(verify(args.file))
            return 0
        body = build_client_report(
            args.client, as_of=parse_as_of(args.as_of) if args.as_of else None, config_dir=args.clients
        )
        written = write_report(body, args.out)
    except ReportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1 if args.command == "verify" else 2
    print(
        json.dumps(
            {
                "json": str(written.json_path),
                "markdown": str(written.md_path),
                "sha256": written.sha256,
                "markdown_sha256": written.md_sha256,
                "counts": body["counts"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
