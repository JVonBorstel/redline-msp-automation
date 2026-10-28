"""Triage one client's user-reported messages and print the verdict drafts (B-45). Writes nothing; runs no lever.

    uv run --frozen python -m workflows.phishing --client contoso-dental [--reports PATH]

No URL is fetched and no attachment is opened. Exit 0 = ran (also when there is nothing to triage), 2 = bad input.
Synthetic data only.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from workflows.phishing.phishing import PhishingError, draft, load_reports, triage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.phishing",
        description="Print verdict drafts for one client's reported messages (synthetic; read as data only).",
    )
    parser.add_argument("--client", required=True, help="client id, e.g. contoso-dental")
    parser.add_argument("--reports", type=Path, help="reports file (default fixtures/mailflow/reports/<client>.json)")
    args = parser.parse_args(argv)
    try:
        loaded = load_reports(args.client, args.reports)
    except PhishingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not loaded.reports:
        print(f"No reported messages for {args.client}; nothing to triage.")
        return 0
    print("\n\n".join(draft(triage(m, loaded.accepted_domains), args.client) for m in loaded.reports))
    return 0


if __name__ == "__main__":
    sys.exit(main())
