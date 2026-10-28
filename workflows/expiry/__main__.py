"""Expiry watch for one client (B-54). Reads fixtures; renews nothing.

    uv run --frozen python -m workflows.expiry contoso-dental [--as-of 2026-10-21] [--within-days 30] [--markdown]

Prints JSON (or Markdown): one reminder row per finding with a due date and an owner. Exit 0 = ran, 2 = bad input.
"""

from __future__ import annotations

import argparse
import json
import sys

from workflows.expiry.expiry import ExpiryError, build_report, render_markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.expiry",
        description="List expiring secrets, certificates, GDAP relationships and weak mail authentication.",
    )
    parser.add_argument("client", help="client id, e.g. contoso-dental")
    parser.add_argument("--as-of", help="UTC date (default: the fixture's pinned date)")
    parser.add_argument("--within-days", type=int, default=30)
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = build_report(args.client, as_of=args.as_of, within_days=args.within_days)
    except ExpiryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.markdown:
        print(render_markdown(report), end="")
    else:
        body = {"client": report.client, "as_of": report.as_of, "note": report.note, "reminders": report.rows()}
        print(json.dumps(body, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
