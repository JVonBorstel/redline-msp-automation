"""Offline demo CLI for the lever runner (mock tenant, synthetic data).

    uv run python -m core.levers list
    uv run python -m core.levers invoke user.reset-mfa --as tech-ana --client contoso-dental \
        -p upn=ana.lopez@contosodental.example
    uv run python -m core.levers invoke user.reset-mfa --as tech-ana --client contoso-dental \
        -p upn=ana.lopez@contosodental.example --execute --approved-by lead-lee --verified callback-on-file
    uv run python -m core.levers pause user.reset-mfa [--client contoso-dental] --as lead-lee --reason "..."
    uv run python -m core.levers resume user.reset-mfa [--client contoso-dental] --as lead-lee [--reason "..."]
    uv run python -m core.levers paused
    uv run python -m core.levers verify                       # every audit chain on its own; exit 1 if any is broken
    uv run python -m core.levers export --client contoso-dental --out DIR   # one client's chain and head, nothing else
    uv run python -m core.levers reviews                      # open second reviews; exit 1 if any is overdue
    uv run python -m core.levers complete-review REVIEW_ID --as lead-lee

B-42: `--clients FILE` loads client records (a JSON object of client id to record) and turns on the B-28/B-42 rules:
business-hours and maintenance windows, and pre-authorized containment (`invoke ... --execute --on-call`).
`--window-override NAME` records a named override of a window on the approval.

`--verified <method>` records how the requester was verified out of band (C-30); levers marked
`verification: "requester"` (user.reset-mfa, user.disable) refuse to execute without it. The
verifier defaults to the approving lead (`--verified-by` to name someone else) and the time is now.

State lives in .tmp/demo (gitignored): the tenant is copied there from fixtures/tenant on first
use, so executing never edits the committed fixtures; the audit chains live in .tmp/demo/audit (one
`<client>.jsonl` per client plus `_msp.jsonl`) and so do the pauses (pauses.json). Exit 0 when the call is ok,
1 when it is denied or fails, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

from pydantic import ValidationError

from core.audit import AuditError
from core.audit.router import AuditRouter
from core.identity import IdentityStore
from core.levers.caps import ReviewError
from core.levers.models import Approval, InvokeResult, Verification, VerificationMethod
from core.levers.registry import Registry
from core.levers.runner import LeverRunner, PolicyError, RunnerPolicy
from core.levers.tenant import DEFAULT_TENANT_DIR, MockTenant

DEMO_DIR = Path(__file__).resolve().parents[2] / ".tmp" / "demo"


def _parse_params(pairs: list[str], registry: Registry, lever: str) -> dict[str, Any]:
    spec = registry.get(lever)
    params: dict[str, Any] = {}
    for pair in pairs:
        name, sep, raw = pair.partition("=")
        if not sep:
            raise SystemExit(f"param {pair!r} must look like name=value")
        kind = spec.params[name].type if spec and name in spec.params else "string"
        value: Any = raw
        if kind == "integer" and raw.lstrip("-").isdigit():
            value = int(raw)
        elif kind == "boolean" and raw.lower() in ("true", "false"):
            value = raw.lower() == "true"
        params[name] = value
    return params


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m core.levers",
        description="Offline demo CLI for the lever runner (mock tenant, synthetic data only).",
    )
    parser.add_argument("--state", type=Path, default=DEMO_DIR, help="demo state folder (default .tmp/demo)")
    parser.add_argument("--clients", type=Path, help="JSON file: client id -> client record (windows, containment)")
    parser.add_argument("--demo", action="store_true", help="with --clients: accept the demo approver pick (STD-ID-7)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list registered levers")
    sub.add_parser("paused", help="list active lever pauses")
    sub.add_parser("verify", help="verify every audit chain on its own (exit 1 if any is broken)")
    sub.add_parser("reviews", help="list open second reviews (exit 1 if any is overdue)")
    exp = sub.add_parser("export", help="copy one client's audit chain and head pin, and nothing else")
    exp.add_argument("--client", required=True)
    exp.add_argument("--out", type=Path, required=True, help="folder to write into")
    done = sub.add_parser("complete-review", help="complete a second review (a lead who did not request or approve)")
    done.add_argument("review_id")
    done.add_argument("--as", dest="identity", required=True, help="lead id from config/identities.json")

    inv = sub.add_parser("invoke", help="invoke a lever (dry-run unless --execute)")
    inv.add_argument("lever")
    inv.add_argument("--as", dest="identity", required=True, help="identity id from config/identities.json")
    inv.add_argument("--client", required=True)
    inv.add_argument("-p", "--param", action="append", default=[], help="name=value (repeatable)")
    inv.add_argument("--execute", action="store_true", help="execute instead of dry-run")
    inv.add_argument("--approved-by", help="lead id; builds an approval record bound to this exact call")
    inv.add_argument(
        "--verified",
        choices=get_args(VerificationMethod),
        help="how the requester was verified out of band (C-30); needs --approved-by",
    )
    inv.add_argument("--verified-by", help="identity that verified the requester (default: the approver)")
    inv.add_argument("--verified-ref", default="", help="short reference: call-log, ticket or finding id")
    inv.add_argument("--on-call", action="store_true", help="the approver is on call (pre-authorized containment)")
    inv.add_argument("--window-override", help="name of an override of the lever's window, recorded on the approval")

    for name, verb in (("pause", "pause"), ("resume", "resume")):
        cmd = sub.add_parser(name, help=f"{verb} a lever for all clients or one client (lead only, no approval)")
        cmd.add_argument("lever")
        cmd.add_argument("--as", dest="identity", required=True, help="lead id from config/identities.json")
        cmd.add_argument("--client", default=None, help="one client id; omit for every client")
        cmd.add_argument("--reason", required=(name == "pause"), default="resumed", help="one line, for the audit")
    return parser


def _verification(args: argparse.Namespace) -> Verification | None:
    if args.verified is None:
        if args.verified_by or args.verified_ref:
            raise ValueError("--verified-by and --verified-ref need --verified <method>")
        return None
    if not args.approved_by:
        raise ValueError("--verified records part of an approval; add --approved-by <lead>")
    by = args.verified_by or args.approved_by
    return Verification(method=args.verified, by=by, at=datetime.now(UTC), ref=args.verified_ref)


def _policy(clients: Path | None, demo: bool) -> RunnerPolicy | None:
    """The B-28/B-42 rules, on only when client records are given (otherwise the W1 behaviour)."""
    if clients is None:
        return None
    records = json.loads(clients.read_text(encoding="utf-8"))
    if not isinstance(records, dict):
        raise ValueError("the clients file must be a JSON object of client id to record")
    return RunnerPolicy(demo=demo, client_records=records)


def _runner(state: Path, registry: Registry, policy: RunnerPolicy | None = None) -> LeverRunner:
    tenant_dir = state / "tenant"
    if not tenant_dir.exists():
        shutil.copytree(DEFAULT_TENANT_DIR, tenant_dir)
    # One router for the CLI, the page and the queue: a chain per client plus _msp (B42-2, B42-3).
    audit = AuditRouter(state / "audit")
    return LeverRunner(registry, IdentityStore.load(), MockTenant(tenant_dir), audit, policy=policy)


def _report(result: InvokeResult, runner: LeverRunner) -> int:
    print(json.dumps(result.model_dump(mode="json"), indent=2))
    assert isinstance(runner.audit, AuditRouter)
    chain = runner.audit.path_for(None if result.client == "*" else result.client)
    print(f"audit: {chain} (seq {result.audit_seq})", file=sys.stderr)
    return 0 if result.ok else 1


def _verify(router: AuditRouter) -> int:
    results = router.verify_all()
    for name, result in results.items():
        broken = f"BROKEN at seq {result.broken_seq}: {result.reason}"
        print(f"{name:24} {f'OK ({result.records} records)' if result.ok else broken}")
    if not results:
        print("no audit chains yet")
    return 0 if all(r.ok for r in results.values()) else 1


def _reviews(runner: LeverRunner) -> int:
    """Audit what is overdue (once each), list what is open; exit 1 when anything is overdue."""
    try:
        overdue = {r.id for r in runner.check_reviews()}
        open_reviews = runner.reviews.open_reviews()
    except (ReviewError, AuditError) as exc:
        print(f"reviews cannot be checked: {exc}", file=sys.stderr)
        return 1
    for review in open_reviews:
        flag = "OVERDUE" if review.id in overdue else "open"
        print(f"{review.id:44} {flag:8} {review.client:20} {review.lever:20} due {review.due.isoformat()}")
    if not open_reviews:
        print("no open second reviews")
    return 1 if overdue else 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    registry = Registry.load()
    if args.command == "list":
        for name in registry.names():
            lever = registry.get(name)
            assert lever is not None
            verify = " verify=requester" if lever.verification else ""
            print(
                f"{name:16} {lever.lever_class:5} {lever.risk_class or '-':2} approval={lever.approval:4} "
                f"role={lever.required_role.value}{verify}"
            )
        return 0

    try:
        policy = _policy(args.clients, args.demo)
    except (OSError, ValueError, PolicyError) as exc:
        print(f"usage error: --clients: {exc}", file=sys.stderr)
        return 2
    runner = _runner(args.state, registry, policy)
    assert isinstance(runner.audit, AuditRouter)
    if args.command == "verify":
        return _verify(runner.audit)
    if args.command == "export":
        try:
            log, head = runner.audit.export_client(args.client, args.out)
        except AuditError as exc:
            print(f"export refused: {exc}", file=sys.stderr)
            return 1
        print(f"exported {log} and {head}")
        return 0
    if args.command == "reviews":
        return _reviews(runner)
    if args.command == "complete-review":
        return _report(runner.complete_review(args.review_id, args.identity), runner)
    if args.command == "paused":
        pauses = runner.pauses.all()
        for pause in pauses:
            print(f"{pause.lever:16} {pause.scope:28} by {pause.by} at {pause.at.isoformat()}: {pause.reason}")
        if not pauses:
            print("no levers are paused")
        return 0
    if args.command in ("pause", "resume"):
        act = runner.pause if args.command == "pause" else runner.resume
        return _report(act(args.lever, args.identity, args.reason, client=args.client), runner)

    params = _parse_params(args.param, registry, args.lever)
    try:
        verification = _verification(args)
        approval = (
            Approval(
                approver=args.approved_by,
                lever=args.lever,
                client=args.client,
                params=params,
                verification=verification,
                on_call=args.on_call,
                window_override=args.window_override,
                demo=args.demo and policy is not None,
            )
            if args.approved_by
            else None
        )
    except (ValueError, ValidationError) as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return 2
    mode = "execute" if args.execute else "dry-run"
    result = runner.invoke(args.lever, params, args.identity, args.client, mode=mode, approval=approval)
    return _report(result, runner)


if __name__ == "__main__":
    sys.exit(main())
