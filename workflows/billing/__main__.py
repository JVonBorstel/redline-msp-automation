"""Billing classification and note-quality review (B-76). Writes review files; changes no invoice, code or entry.

    uv run --frozen python -m workflows.billing export contoso-dental --as lead-lee --as-of 2026-10-27
    uv run --frozen python -m workflows.billing verify build/billing/contoso-dental.json

Exit 0 = done (verify: matches), 1 = verify mismatch, 2 = bad input or refused (the refusal is audited).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from workflows.billing.report import DEFAULT_AUDIT_DIR, DEFAULT_OUT_DIR, VerifyError, export, verify
from workflows.billing.rules import BillingError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m workflows.billing", description="Billing review (read-only).")
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export", help="write the review (JSON, .sha256, Markdown) for one client")
    exp.add_argument("client")
    exp.add_argument("--as", dest="identity", required=True, help="lead id from config/identities.json")
    exp.add_argument("--as-of", default=None, help="ISO date (default: today, UTC)")
    exp.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    exp.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT_DIR)
    ver = sub.add_parser("verify", help="re-hash a review against its .sha256")
    ver.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    if args.command == "verify":
        try:
            digest = verify(args.path)
        except VerifyError as exc:
            print(f"MISMATCH: {exc}", file=sys.stderr)
            return 1
        print(f"OK {digest}  {args.path.name}")
        return 0
    try:
        written = export(
            args.client,
            as_of=args.as_of or datetime.now(UTC).date().isoformat(),
            by=args.identity,
            out_dir=args.out,
            audit_dir=args.audit_dir,
        )
    except BillingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"json": str(written.json_path), "md": str(written.md_path), "sha256": written.sha256}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
