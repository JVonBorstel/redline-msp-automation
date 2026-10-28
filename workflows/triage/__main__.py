"""Triage one synthetic ticket from the shell and print the explanation.

    uv run python -m workflows.triage T-3101                    # mock model (default), offline
    uv run python -m workflows.triage T-3101 --provider ollama  # local model on loopback, if one is running
    uv run python -m workflows.triage T-3127 --json
    uv run python -m workflows.triage T-3218 --correct category=network --by tech-ben
    uv run python -m workflows.triage T-3101 --enqueue         # also put the proposal in the approval queue (.tmp/demo)

With a proposal, the output (text or --json) also shows who the lever affects (L1-L4) and the check a lead needs
before approving, both read from levers/registry.json, never from the ticket (B-05).
The dry-run is audited in .tmp/triage/audit.jsonl (gitignored); the mock tenant is only read, never written.
Exit 0 on success, 2 for an unknown ticket or an invalid correction.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.audit import AuditLog
from core.audit.router import AuditRouter
from core.identity import IdentityStore
from core.levers import LeverRunner, MockTenant, Registry
from core.queue import Proposal, open_queue
from workflows.triage.corrections import DEFAULT_CORRECTIONS_PATH, CorrectionError, record_correction
from workflows.triage.tickets import TicketError, get_ticket
from workflows.triage.triage import REPO_ROOT, classify_gateway, triage

STATE_DIR = REPO_ROOT / ".tmp" / "triage"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m workflows.triage", description="Triage one synthetic ticket.")
    parser.add_argument("ticket_id", help="ticket id from fixtures/tickets, e.g. T-3101")
    parser.add_argument("--provider", choices=("mock", "ollama"), default="mock", help="model for classify")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument("--state", type=Path, default=STATE_DIR, help="folder for the audit log (default .tmp/triage)")
    parser.add_argument(
        "--enqueue", action="store_true", help="add the proposal to the approval queue in --state (default .tmp/demo)"
    )
    parser.add_argument("--correct", metavar="FIELD=VALUE", help="record a correction instead of triaging")
    parser.add_argument("--by", help="identity recording the correction (a technician or lead)")
    parser.add_argument("--corrections", type=Path, default=DEFAULT_CORRECTIONS_PATH, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        ticket = get_ticket(args.ticket_id)
    except TicketError as exc:
        print(exc, file=sys.stderr)
        return 2

    if args.correct is not None:
        field, sep, value = args.correct.partition("=")
        if not sep or not args.by:
            print("--correct needs FIELD=VALUE and --by <identity>", file=sys.stderr)
            return 2
        try:
            correction = record_correction(
                ticket.id, field, None if value == "none" else value, args.by, path=args.corrections
            )
        except CorrectionError as exc:
            print(f"correction refused: {exc}", file=sys.stderr)
            return 2
        print(f"recorded in {args.corrections}: {correction.model_dump_json()}")
        return 0

    if args.enqueue:
        # one demo state: the queue's runner, so the dry-run, the lead's decision and the execute share one audit chain
        state = args.state if args.state != STATE_DIR else REPO_ROOT / ".tmp" / "demo"
        queue = open_queue(state)
        runner, audit_path = queue.runner, state / "audit.jsonl"
    else:
        audit_path = args.state / "audit.jsonl"
        runner = LeverRunner(Registry.load(), IdentityStore.load(), MockTenant(), AuditLog(audit_path))
    result = triage(ticket.unlabelled(), classify_gateway(args.provider), runner)
    print(json.dumps(result.to_json(), indent=2) if args.json else result.explain())
    if args.enqueue and result.proposal is not None:
        stored = queue.add(Proposal.model_validate(result.proposal))
        print(f"queued: {stored.id} ({stored.status}) in {state / 'queue.jsonl'}", file=sys.stderr)
    if result.dry_run is not None:
        if isinstance(runner.audit, AuditRouter):  # B-42: the queue's runner writes one chain per client
            audit_path = runner.audit.path_for(result.dry_run.client)
        print(f"audit: {audit_path} (seq {result.dry_run.audit_seq})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
