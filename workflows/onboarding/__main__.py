"""New-hire change plan and drafts (B-35). Dry-run only; executing and sending stay with people.

    uv run --frozen python -m workflows.onboarding plan <request.json> [--as tech-ana]
    uv run --frozen python -m workflows.onboarding drafts <request.json> --approver lead-lee --approver lead-fay

``request.json`` holds the form fields (see NewHireRequest). ``plan`` prints the plan as JSON; ``drafts`` writes
``welcome.md`` and ``handoff.md`` under the state folder and prints their paths. Exit 0 = ran, 2 = refused or bad input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.audit import AuditLog
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, LeverRunner, MockTenant, Registry
from workflows.onboarding.onboarding import (
    DEFAULT_AGENT,
    DEFAULT_TECHNICIAN,
    OnboardingError,
    build_plan,
    parse_request,
    welcome_and_handoff,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.onboarding", description="New-hire change plan (synthetic, dry-run only)."
    )
    parser.add_argument("command", choices=("plan", "drafts"))
    parser.add_argument("request", help="JSON file with the new-hire form fields")
    parser.add_argument("--as", dest="identity", default=DEFAULT_TECHNICIAN, help="technician identity")
    parser.add_argument("--agent", default=DEFAULT_AGENT, help="agent identity that runs the dry-runs")
    parser.add_argument("--approver", action="append", default=[], help="a lead who approved (drafts; repeat)")
    parser.add_argument("--state-dir", default=".tmp/onboarding-state", help="where drafts are written")
    parser.add_argument("--audit", default=".tmp/onboarding-audit.jsonl", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    runner = LeverRunner(Registry.load(), IdentityStore.load(), MockTenant(DEFAULT_TENANT_DIR), AuditLog(args.audit))
    try:
        request = parse_request(json.loads(Path(args.request).read_text(encoding="utf-8")))
        if args.command == "plan":
            plan = build_plan(runner, request, technician=args.identity, agent=args.agent)
            print(json.dumps(plan.as_dict(), indent=2))
        else:
            drafts = welcome_and_handoff(
                runner,
                request,
                approvers=args.approver,
                state_dir=Path(args.state_dir),
                technician=args.identity,
                agent=args.agent,
            )
            print(json.dumps({"plan_id": drafts.plan_id, "drafts": [str(p) for p in drafts.paths], "sent": False}))
    except (OnboardingError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
