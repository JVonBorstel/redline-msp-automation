"""Propose the undo of one applied change from the audit record (B-41). Executes nothing.

    uv run --frozen python -m workflows.rollback <audit_seq> --client contoso-dental [--as tech-ana] [--state .tmp/demo]

Prints the result as JSON: a queued rollback proposal, the manual steps for a lever without an undo, or why nothing
was proposed. Exit 0 = proposed, manual or nothing to undo, 2 = refused, drifted or bad input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.audit.router import AuditRouter
from core.queue import DEFAULT_STATE_DIR, open_queue
from workflows.rollback.rollback import OK_OUTCOMES, RollbackError, plan, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.rollback", description="Propose a rollback from the audit (synthetic)."
    )
    parser.add_argument("audit_seq", type=int, help="the record's seq in that client's chain")
    parser.add_argument("--client", required=True, help="client whose audit chain holds the record (B-42)")
    parser.add_argument("--as", dest="identity", default="tech-ana", help="technician who proposes (default tech-ana)")
    parser.add_argument(
        "--state", default=str(DEFAULT_STATE_DIR), help="state folder holding audit/<client>.jsonl and queue.jsonl"
    )
    args = parser.parse_args(argv)
    queue = open_queue(Path(args.state))
    try:
        audit = queue.runner.audit
        log = audit.path_for(args.client) if isinstance(audit, AuditRouter) else audit.path
        rb = plan(queue.runner, log, args.audit_seq, args.identity, queue)
    except RollbackError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary(rb), indent=2))
    return 0 if rb.outcome in OK_OUTCOMES else 2


if __name__ == "__main__":
    sys.exit(main())
