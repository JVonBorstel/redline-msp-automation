"""Draft a cited reply or a closure follow-up for one synthetic ticket (B-25). Nothing is sent.

    uv run --frozen python -m workflows.replies reply T-5301 --state .tmp/demo
    uv run --frozen python -m workflows.replies closure T-5101 --state .tmp/demo --fix "Reset the printer's address"

Writes <state>/replies/<ticket>.<kind>.md and prints it. A person reviews and sends it (HO-9).
Exit 0 = draft written, 1 = no draft (printed as `no draft: ...`; the line is still written), 2 = bad input.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.audit import AuditLog
from core.identity import IdentityStore
from core.levers import LeverRunner, MockTenant, Registry
from workflows.replies.replies import (
    DEFAULT_TICKETS_DIR,
    REPLY_AGENT,
    ReplyError,
    default_tenant_dir,
    draft_closure,
    draft_reply,
    get_ticket,
    write_draft,
)

DEFAULT_STATE = Path(__file__).resolve().parents[2] / ".tmp" / "demo"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.replies",
        description="Draft a KB-cited reply or a closure follow-up for one ticket (synthetic data; never sends).",
    )
    parser.add_argument("kind", choices=("reply", "closure"))
    parser.add_argument("ticket_id", help="ticket id from fixtures/tickets, e.g. T-5301")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE, help="state folder (default .tmp/demo)")
    parser.add_argument("--tickets", type=Path, default=DEFAULT_TICKETS_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--fix", help="closure only: one plain line from the technician saying what was done")
    parser.add_argument("--agent", default=REPLY_AGENT, help="agent identity that runs kb.search (default triage-bot)")
    args = parser.parse_args(argv)
    try:
        ticket = get_ticket(args.ticket_id, args.tickets)
        tenant = MockTenant(default_tenant_dir(args.state))
        runner = LeverRunner(Registry.load(), IdentityStore.load(), tenant, AuditLog(args.state / "audit.jsonl"))
        if args.kind == "reply":
            draft = draft_reply(ticket, runner=runner, tenant=tenant, agent=args.agent)
        else:
            draft = draft_closure(ticket, runner=runner, tenant=tenant, fix_summary=args.fix, agent=args.agent)
        path = write_draft(draft, args.state)
    except ReplyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(draft.text.rstrip("\n"))
    print(f"{'draft' if draft.drafted else 'no draft'}: {path}", file=sys.stderr)
    return 0 if draft.drafted else 1


if __name__ == "__main__":
    sys.exit(main())
