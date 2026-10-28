"""Plan an offboarding, verify it, and reconcile the proof with the audit log (B-36). Executes nothing.

    uv run --frozen python -m workflows.offboarding plan <upn> --client contoso-dental [--manager <upn>] [--as tech-ana]
    uv run --frozen python -m workflows.offboarding verify <upn> --client contoso-dental
    uv run --frozen python -m workflows.offboarding reconcile <upn> --client contoso-dental

Each command prints JSON. ``plan`` dry-runs every step and queues one proposal per change for a lead.
Exit 0 = done and in order (plan: nothing refused; verify: every step in its target state; reconcile: all matches).
Exit 2 = refused, bad input, a step not in its target state or a mismatch (the output lists each one).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.audit.router import AuditRouter
from core.levers.tenant import TenantError
from core.queue import DEFAULT_STATE_DIR, open_queue
from workflows.offboarding.offboarding import OffboardingError, plan, reconcile, record_path, summary, verify


def _load(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OffboardingError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise OffboardingError(f"{path} is not a JSON object")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.offboarding", description="Offboarding plan and completion proof (synthetic)."
    )
    parser.add_argument("command", choices=("plan", "verify", "reconcile"))
    parser.add_argument("upn", help="userPrincipalName of the leaver")
    parser.add_argument("--client", required=True, help="client id, e.g. contoso-dental")
    parser.add_argument("--manager", help="manager of the same client who gets OneDrive access (plan)")
    parser.add_argument("--leave-at", help="last working day, YYYY-MM-DD (plan; recorded only)")
    parser.add_argument("--as-of", help="the date to plan and verify against, YYYY-MM-DD (default: the fixture's)")
    parser.add_argument("--as", dest="identity", default="tech-ana", help="technician who proposes (default tech-ana)")
    parser.add_argument(
        "--state",
        default=str(DEFAULT_STATE_DIR),
        help="state folder holding audit/<client>.jsonl, queue.jsonl and tenant/",
    )
    args = parser.parse_args(argv)
    state = Path(args.state)
    out_dir = state / "offboarding"
    queue = open_queue(state)
    audit = queue.runner.audit
    # B-42: verify pins, and reconcile verifies, the client's own chain (audit/<client>.jsonl), never another's.
    chain = audit.path_for(args.client) if isinstance(audit, AuditRouter) else audit.path
    try:
        if args.command == "plan":
            built = plan(
                queue.runner, args.client, args.upn, args.identity, args.manager, args.leave_at, args.as_of, queue
            )
            if built.outcome == "planned":
                target = record_path(out_dir, args.client, args.upn, "plan")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(summary(built), indent=2) + "\n", encoding="utf-8")
            print(json.dumps(summary(built), indent=2))
            return 0 if built.outcome == "planned" and not any(s.status == "refused" for s in built.steps) else 2
        if args.command == "verify":
            plan_data = _load(record_path(out_dir, args.client, args.upn, "plan"))
            record = verify(plan_data, queue.runner.tenant, chain, args.as_of, out_dir)
            print(json.dumps(record, indent=2))
            return 0 if record["complete"] else 2
        record = _load(record_path(out_dir, args.client, args.upn, "completion"))
        outcome = reconcile(record, chain)
        print(json.dumps(outcome, indent=2))
        return 0 if outcome["ok"] else 2
    except (OffboardingError, TenantError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
