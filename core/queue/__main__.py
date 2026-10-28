"""Offline CLI for the approval queue (synthetic data, mock tenant).

    uv run python -m core.queue seed --demo            # 3 pending proposals into .tmp/demo
    uv run python -m core.queue list [--status pending] [--viewer lead-lee]

Each seeded proposal is first dry-run through the lever runner as `triage-bot` (audited), and is
queued only if that dry-run is allowed (STD-PR-1, DR-15, B03-4). Seeding is idempotent:
proposals already in the queue (any status) are left as they are, with no new dry-run. To start
the demo over, remove the state folder (`pwsh -File scripts/clean.ps1` removes .tmp).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.queue.store import DEFAULT_STATE_DIR, STATUSES, Proposal, QueueError, open_queue

SEED_AGENT = "triage-bot"  # the agent identity that proposes the demo set


def demo_proposals() -> list[Proposal]:
    """One triage-style and two baseline-style proposals over the synthetic mock tenants."""
    return [
        Proposal.new(
            source="triage",
            ref="T-1001",
            lever="user.reset-mfa",
            client="contoso-dental",
            params={"upn": "ana.lopez@contosodental.example"},
            requested_by="tech-ana",
            reason="Lost phone, cannot approve sign-in: reset MFA so she can re-register",
        ),
        Proposal.new(
            source="baseline",
            ref="TB-DEMO-STALE-01",
            lever="user.disable",
            client="contoso-dental",
            params={"upn": "jamie.chen@contosodental.example", "reason": "Left the practice; account still enabled"},
            requested_by="tech-ana",
            reason="Baseline-style demo finding: a leaver's account is still enabled",
        ),
        Proposal.new(
            source="baseline",
            ref="TB-DEMO-MFA-01",
            lever="user.reset-mfa",
            client="fabrikam-capital",
            params={"upn": "morgan.reyes@fabrikamcapital.example"},
            requested_by="tech-ben",
            reason="Baseline-style demo finding: Authenticator registered on a phone reported lost",
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.queue", description="Offline CLI for the approval queue.")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_DIR, help="demo state folder (default .tmp/demo)")
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("seed", help="add synthetic pending proposals")
    seed.add_argument("--demo", action="store_true", required=True, help="the built-in demo set (the only one)")
    show = sub.add_parser("list", help="print proposals as JSON lines")
    show.add_argument("--status", choices=STATUSES)
    show.add_argument("--viewer", help="only proposals for clients in this identity's list (DR-12)")
    args = parser.parse_args(argv)

    queue = open_queue(args.state)
    if args.command == "seed":
        failed = 0
        for proposal in demo_proposals():
            try:
                stored, dry_run = queue.propose(proposal, SEED_AGENT)
            except QueueError as exc:
                failed += 1
                print(f"{proposal.id} not queued: {exc}", file=sys.stderr)
                continue
            seq = f"dry-run seq {dry_run.audit_seq}" if dry_run else "already queued"
            line = f"{stored.id} {stored.status:8} {stored.lever} {stored.client} ({stored.source} {stored.ref})"
            print(f"{line} [{seq}]")
        print(f"queue: {queue.path}", file=sys.stderr)
        return 1 if failed else 0
    for proposal in queue.list(args.status, args.viewer):
        print(proposal.model_dump_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
