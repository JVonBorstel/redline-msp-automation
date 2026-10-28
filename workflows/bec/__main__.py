"""Plan a BEC containment for one user, or audit one client's inbox rules (B-46). Executes nothing.

    uv run --frozen python -m workflows.bec plan <client> <upn> [--as tech-ana] [--incident ID] [--prompt]
    uv run --frozen python -m workflows.bec audit <client> [--as tech-ana]

``plan`` dry-runs every step, queues one proposal per change for a lead, writes the incident timeline to
``<state>/bec/timelines/<client>/<incident>.jsonl`` and prints the plan as JSON (or, with --prompt, only the text that
may go to a model). ``audit`` prints every flagged inbox rule of the client. Exit 0 = done, 2 = refused or bad input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.audit.router import AuditRouter
from core.levers.tenant import TenantError
from core.queue import DEFAULT_STATE_DIR, open_queue
from workflows.bec.bec import BecError, audit_rules, contain, prompt_text, summary, write_timeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.bec", description="BEC containment plan and inbox-rule audit (synthetic)."
    )
    parser.add_argument("command", choices=("plan", "audit"))
    parser.add_argument("client", help="client id, e.g. contoso-dental")
    parser.add_argument("upn", nargs="?", help="userPrincipalName of the one user to contain (plan)")
    parser.add_argument("--as", dest="identity", default="tech-ana", help="technician who proposes (default tech-ana)")
    parser.add_argument("--incident", help="incident id (default: derived from client and user)")
    parser.add_argument("--prompt", action="store_true", help="print only the model-safe text (plan)")
    parser.add_argument(
        "--state",
        default=str(DEFAULT_STATE_DIR),
        help="state folder holding audit/<client>.jsonl, queue.jsonl and tenant/",
    )
    args = parser.parse_args(argv)
    state = Path(args.state)
    queue = open_queue(state)
    try:
        if args.command == "audit":
            report = audit_rules(queue.runner, args.client, args.identity)
            print(json.dumps(report, indent=2))
            return 0 if report["ok"] else 2
        if not args.upn:
            print("error: plan needs one userPrincipalName", file=sys.stderr)
            return 2
        plan = contain(queue.runner, args.client, args.upn, args.identity, args.incident, queue)
        if plan.outcome == "planned":
            audit = queue.runner.audit
            # B-42: the timeline is built from the client's own chain (audit/<client>.jsonl), never another's.
            chain = audit.path_for(args.client) if isinstance(audit, AuditRouter) else audit.path
            path = write_timeline(plan, chain, state / "bec")
            plan.notes.append(f"incident timeline: {path.as_posix()}")
        print(prompt_text(plan) if args.prompt else json.dumps(summary(plan), indent=2))
        refused = plan.outcome != "planned" or any(s.status == "refused" for s in plan.steps)
        return 2 if refused else 0
    except (BecError, TenantError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
