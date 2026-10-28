"""Daily backup review for one client (B-68). Reads fixtures; writes nothing; retries nothing.

    uv run --frozen python -m workflows.backup_review contoso-dental [--as-of 2026-10-21T07:00:00Z]

Prints JSON: counts, the failed, missed and long-running jobs with the reason from the job record, and ticket drafts.
Exit 0 = ran, 2 = bad input. A lead approves any real retry through the queue (`backup.retry-job`, R2).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from adapters.backup import BackupMock
from adapters.backup.mock import DEFAULT_BACKUP_DIR
from adapters.base import AdapterError
from workflows.backup_review.review import (
    DEFAULT_CONFIG_PATH,
    ReviewError,
    draft_tickets,
    load_config,
    review_client,
    summary,
    utc,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.backup_review",
        description="Daily backup job review for one client (synthetic data; read-only, never retries anything).",
    )
    parser.add_argument("client", help="client id, e.g. contoso-dental")
    parser.add_argument("--as-of", help="review as at this UTC time (default: the fixture's pinned time)")
    parser.add_argument("--backup", type=Path, default=DEFAULT_BACKUP_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        adapter = BackupMock.for_fixture(args.client, args.backup)
        config = load_config(args.config)
        review = review_client(adapter, utc(args.as_of or adapter.as_of), config)
        drafts = draft_tickets(adapter, review, config)
    except (AdapterError, ReviewError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary(review, drafts), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
