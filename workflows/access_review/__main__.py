"""Quarterly access review (B-49). Writes review files; changes no role, identity or tenant.

    uv run --frozen python -m workflows.access_review export contoso-dental --as lead-lee --as-of 2026-10-23
    uv run --frozen python -m workflows.access_review export --msp --as lead-lee --as-of 2026-10-23
    uv run --frozen python -m workflows.access_review decide build/access-review/2026-Q4/contoso-dental.json \
        --as lead-lee --on 2026-10-24 --decisions decisions.json
    uv run --frozen python -m workflows.access_review verify build/access-review/2026-Q4/contoso-dental.json

`--decisions` is a JSON object {row_id: "keep" | "remove" | "investigate"}; every row needs one.
Exit 0 = done (verify: matches), 1 = verify mismatch, 2 = bad input or refused (the refusal is audited).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from workflows.access_review.review import (
    DEFAULT_AUDIT_DIR,
    DEFAULT_OUT_DIR,
    AccessReviewError,
    VerifyError,
    decide,
    export,
    verify,
)


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m workflows.access_review", description="Quarterly access review.")
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export", help="write a client export (or --msp) and its .sha256")
    exp.add_argument("client", nargs="?", help="client id, e.g. contoso-dental")
    exp.add_argument("--msp", action="store_true", help="every repo identity with its client list")
    exp.add_argument("--as", dest="identity", required=True, help="lead id from config/identities.json")
    exp.add_argument("--as-of", default=None, help="ISO date (default: today, UTC)")
    exp.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    exp.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT_DIR)
    dec = sub.add_parser("decide", help="record a lead's decision on every row of an export")
    dec.add_argument("export", type=Path)
    dec.add_argument("--as", dest="identity", required=True, help="lead id from config/identities.json")
    dec.add_argument("--on", default=None, help="ISO date of the decision (default: today, UTC)")
    dec.add_argument("--decisions", type=Path, required=True, help="JSON {row_id: keep|remove|investigate}")
    dec.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT_DIR)
    ver = sub.add_parser("verify", help="re-hash an export or decided file against its .sha256")
    ver.add_argument("path", type=Path)
    ver.add_argument("--audit-dir", type=Path, default=None, help="also check the hash is pinned in this audit chain")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            try:
                digest = verify(args.path, args.audit_dir)
            except VerifyError as exc:
                print(f"MISMATCH: {exc}", file=sys.stderr)
                return 1
            print(f"OK {digest}  {args.path.name}")
            return 0
        if args.command == "export":
            if args.msp == (args.client is not None):
                print("error: give a client id or --msp, not both", file=sys.stderr)
                return 2
            written = export(
                None if args.msp else args.client,
                as_of=args.as_of or _today(),
                by=args.identity,
                out_dir=args.out,
                audit_dir=args.audit_dir,
            )
        else:
            try:
                decisions = json.loads(args.decisions.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                print(f"error: cannot read decisions: {exc}", file=sys.stderr)
                return 2
            if not isinstance(decisions, dict):
                print("error: decisions must be a JSON object", file=sys.stderr)
                return 2
            written = decide(
                args.export,
                {str(k): str(v) for k, v in decisions.items()},
                by=args.identity,
                decided_on=args.on or _today(),
                audit_dir=args.audit_dir,
            )
    except AccessReviewError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"path": str(written.path), "sha256": written.sha256, "rows": written.rows}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
