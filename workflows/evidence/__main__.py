"""Monthly evidence bundle (B-51). Dry run unless --write; writes files only, changes no tenant, role or identity.

    uv run --frozen python -m workflows.evidence bundle contoso-dental --period 2026-10 --as lead-lee --as-of 2026-11-02
    uv run --frozen python -m workflows.evidence bundle --msp --period 2026-10 --as lead-lee --write
    uv run --frozen python -m workflows.evidence verify build/evidence/2026-10/contoso-dental [--audit-dir DIR]

Exit 0 = done (verify: matches), 1 = verify mismatch, 2 = bad input or refused (the refusal is audited).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from core.paths import REPO_ROOT
from workflows.evidence.bundle import (
    DEFAULT_AUDIT_DIR,
    DEFAULT_OUT_DIR,
    DEFAULT_REVIEW_DIR,
    EvidenceError,
    VerifyError,
    build_bundle,
    verify_bundle,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m workflows.evidence", description="Monthly evidence bundle.")
    sub = parser.add_subparsers(dest="command", required=True)
    bun = sub.add_parser("bundle", help="build a client (or --msp) bundle; a dry run unless --write")
    bun.add_argument("client", nargs="?", help="client id, e.g. contoso-dental")
    bun.add_argument("--msp", action="store_true", help="the MSP bundle (change records, full registry)")
    bun.add_argument("--period", required=True, help="YYYY-MM")
    bun.add_argument("--as", dest="identity", required=True, help="lead id from config/identities.json")
    bun.add_argument("--as-of", default=None, help="ISO date (default: today, UTC)")
    bun.add_argument("--write", action="store_true", help="write the files (default: print the manifest only)")
    bun.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    bun.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT_DIR)
    bun.add_argument("--access-review-dir", type=Path, default=DEFAULT_REVIEW_DIR)
    bun.add_argument("--git-repo", type=Path, default=REPO_ROOT, help="repo whose git log lists merged changes (--msp)")
    bun.add_argument("--no-git", action="store_true", help="do not read a git log (the gap is listed)")
    ver = sub.add_parser("verify", help="re-hash a bundle folder against its manifest")
    ver.add_argument("path", type=Path)
    ver.add_argument("--audit-dir", type=Path, default=None, help="also check the manifest hash is pinned in the chain")
    args = parser.parse_args(argv)
    if args.command == "verify":
        try:
            digest = verify_bundle(args.path, args.audit_dir)
        except VerifyError as exc:
            print(f"MISMATCH: {exc}", file=sys.stderr)
            return 1
        print(f"OK {digest}  {args.path.name}")
        return 0
    if args.msp == (args.client is not None):
        print("error: give a client id or --msp, not both", file=sys.stderr)
        return 2
    try:
        bundle = build_bundle(
            None if args.msp else args.client,
            period=args.period,
            as_of=args.as_of or datetime.now(UTC).date().isoformat(),
            by=args.identity,
            write=args.write,
            out_dir=args.out,
            audit_dir=args.audit_dir,
            access_review_dir=args.access_review_dir,
            git_repo=None if args.no_git else args.git_repo,
        )
    except EvidenceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "path": str(bundle.target),
                "sha256": bundle.manifest_sha256,
                "files": len(bundle.manifest["files"]),
                "gaps": bundle.manifest["gaps"],
                "written": bundle.written,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
