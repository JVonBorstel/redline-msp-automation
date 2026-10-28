"""Scheduled restore test for one client (B-69). Restores one synthetic item to a mock alternate location.

    uv run --frozen python -m workflows.restore_tests run contoso-dental --as-of 2026-10-21 [--seed s] [--item RI-1001]
    uv run --frozen python -m workflows.restore_tests verify build/restore-tests/contoso-dental/2026-10-21.json

`run` writes `<out>/<client>/<date>.json` and its `.sha256` and pins the hash in the client's audit chain. It never
touches an original location and changes no tenant state. Exit 0 = the test passed (verify: intact), 1 = the test
failed (evidence still written; verify: mismatch), 2 = bad input, refused, or not run.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from adapters.base import AdapterError
from workflows.restore_tests.catalog import DEFAULT_CATALOG_DIR, RestoreCatalog
from workflows.restore_tests.restore import (
    DEFAULT_AUDIT_DIR,
    DEFAULT_OUT_DIR,
    RestoreError,
    VerifyError,
    run_restore_test,
    verify_evidence,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.restore_tests",
        description="Scheduled restore test for one client (synthetic data; mock restore to an alternate location).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="restore one item to the alternate test location and record the evidence")
    run.add_argument("client", help="client id, e.g. contoso-dental")
    run.add_argument("--as-of", default=None, help="ISO date (default: today, UTC)")
    run.add_argument("--seed", default="", help="vary the pseudo-random pick")
    run.add_argument("--item", default=None, help="test this item instead of picking one")
    run.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    run.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT_DIR)
    run.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_DIR, help=argparse.SUPPRESS)
    ver = sub.add_parser("verify", help="re-hash an evidence file against its .sha256")
    ver.add_argument("path", type=Path)
    ver.add_argument("--audit-dir", type=Path, default=None, help="also check the hash is pinned in this audit chain")
    args = parser.parse_args(argv)
    if args.command == "verify":
        try:
            digest = verify_evidence(args.path, args.audit_dir)
        except VerifyError as exc:
            print(f"MISMATCH: {exc}", file=sys.stderr)
            return 1
        print(f"OK {digest}  {args.path.name}")
        return 0
    try:
        catalog = RestoreCatalog.for_fixture(args.client, args.catalog)
        record = run_restore_test(
            catalog,
            args.as_of or datetime.now(UTC).date().isoformat(),
            out_dir=args.out,
            audit_dir=args.audit_dir,
            seed=args.seed,
            item_id=args.item,
        )
    except (AdapterError, RestoreError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "client": record.client,
                "result": record.result,
                "item": record.item_id,
                "path": str(record.path),
                "sha256": record.sha256,
                "reason": record.reason,
            },
            indent=2,
        )
    )
    return {"passed": 0, "failed": 1}.get(record.result, 2)


if __name__ == "__main__":
    sys.exit(main())
