"""Copilot readiness for one client (B-53). Reads fixtures; changes nothing.

    uv run --frozen python -m workflows.copilot_readiness contoso-dental [--as-of 2026-10-22] [--markdown]

Prints JSON (or Markdown): the score, its formula and weights, the findings behind every point, and the label and DLP
recommendations. Exit 0 = ran, 2 = bad input.
"""

from __future__ import annotations

import argparse
import json
import sys

from workflows.copilot_readiness.copilot_readiness import ReadinessError, build_report, render_markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.copilot_readiness",
        description="Score Copilot readiness from SharePoint and OneDrive sharing fixtures.",
    )
    parser.add_argument("client", help="client id, e.g. contoso-dental")
    parser.add_argument("--as-of", help="UTC date (default: the fixture's pinned date)")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = build_report(args.client, as_of=args.as_of)
    except ReadinessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.markdown:
        print(render_markdown(report), end="")
    else:
        print(json.dumps(report.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
