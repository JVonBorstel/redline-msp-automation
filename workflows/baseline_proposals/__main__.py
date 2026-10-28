"""Propose user.disable for stale members and expired guests from a baseline findings.json (B-38). Executes nothing.

    uv run --frozen python -m workflows.baseline_proposals --client contoso-dental
        --findings out/findings.json [--state .tmp/demo] [--as-of 2026-10-01]

Prints the result as JSON: proposals queued (each dry-run first), those already queued, the ones deferred by the
per-client cap, and the accounts skipped with the reason. Exit 0 = proposed, nothing to do, or deferred; 2 = bad input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.queue import DEFAULT_STATE_DIR, open_queue
from workflows.baseline_proposals.baseline_proposals import BaselineProposalsError, plan, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.baseline_proposals",
        description="Propose user.disable from baseline findings and guest fixtures (synthetic).",
    )
    parser.add_argument("--client", required=True, help="client id, e.g. contoso-dental")
    parser.add_argument("--findings", required=True, help="findings.json written by Invoke-TenantBaseline")
    parser.add_argument("--as-of", dest="as_of", default=None, help="override the findings' asOf date (YYYY-MM-DD)")
    parser.add_argument(
        "--state",
        default=str(DEFAULT_STATE_DIR),
        help="state folder holding audit/<client>.jsonl, queue.jsonl and tenant/",
    )
    args = parser.parse_args(argv)
    state = Path(args.state)
    try:
        queue = open_queue(state)
        result = plan(args.client, Path(args.findings), queue, tenant_dir=state / "tenant", as_of=args.as_of)
    except BaselineProposalsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary(result), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
