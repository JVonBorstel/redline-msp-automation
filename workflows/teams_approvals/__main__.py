"""Record the Teams approval cards one client's pending proposals would get (B-88). Dry run only; nothing is posted.

    uv run --frozen python -m workflows.teams_approvals contoso-dental [--state .tmp/demo] [--base-url http://127.0.0.1:8765]

Writes ``<state>/teams-approvals/<client>.json`` and prints its path and the card count.
Exit 0 = recorded (zero cards is fine), 2 = bad input or refused.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.queue import DEFAULT_STATE_DIR, open_queue
from workflows.teams_approvals.approvals import TeamsApprovalsError, plan_posts, record_dry_run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.teams_approvals", description="Record Teams approval cards in dry-run (synthetic)."
    )
    parser.add_argument("client", help="the client whose pending proposals get a card")
    parser.add_argument("--state", default=str(DEFAULT_STATE_DIR), help="state folder holding queue.jsonl and audit/")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765", help="loopback approval page the cards link to")
    args = parser.parse_args(argv)
    try:
        run = plan_posts(open_queue(Path(args.state)), args.client, base_url=args.base_url)
        path = record_dry_run(run, Path(args.state))
    except (TeamsApprovalsError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"dry run: {len(run.posts)} card(s) recorded, {len(run.skipped)} skipped, nothing posted: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
