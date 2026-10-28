"""Regulatory evidence pack (B-52). Dry run unless --write; writes files only, changes no tenant, role or identity.

    uv run --frozen python -m workflows.regpacks build contoso-dental --as lead-lee --as-of 2026-10-27
    uv run --frozen python -m workflows.regpacks build fabrikam-capital --as lead-lee --write
    uv run --frozen python -m workflows.regpacks verify build/regpacks/2026-10-27/contoso-dental [--audit-dir DIR]

Exit 0 = done (verify: matches), 1 = verify mismatch, 2 = bad input or refused (the refusal is audited).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from workflows.regpacks.pack import (
    DEFAULT_AUDIT_DIR,
    DEFAULT_OUT_DIR,
    RegpackError,
    VerifyError,
    build_pack,
    verify_pack,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m workflows.regpacks", description="Regulatory evidence pack.")
    sub = parser.add_subparsers(dest="command", required=True)
    bld = sub.add_parser("build", help="build a client pack; a dry run unless --write")
    bld.add_argument("client", help="client id, e.g. contoso-dental")
    bld.add_argument("--as", dest="identity", required=True, help="lead id from config/identities.json")
    bld.add_argument("--as-of", default=None, help="ISO date (default: today, UTC)")
    bld.add_argument("--write", action="store_true", help="write the files (default: print the manifest hash only)")
    bld.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    bld.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT_DIR)
    ver = sub.add_parser("verify", help="re-hash a pack folder against its manifest")
    ver.add_argument("path", type=Path)
    ver.add_argument("--audit-dir", type=Path, default=None, help="also check the manifest hash is pinned in the chain")
    args = parser.parse_args(argv)
    if args.command == "verify":
        try:
            digest = verify_pack(args.path, args.audit_dir)
        except VerifyError as exc:
            print(f"MISMATCH: {exc}", file=sys.stderr)
            return 1
        print(f"OK {digest}  {args.path.name}")
        return 0
    try:
        pack = build_pack(
            args.client,
            as_of=args.as_of or datetime.now(UTC).date().isoformat(),
            by=args.identity,
            write=args.write,
            out_dir=args.out,
            audit_dir=args.audit_dir,
        )
    except RegpackError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "path": str(pack.target),
                "sha256": pack.manifest_sha256,
                "files": len(pack.manifest["files"]),
                "gaps": pack.manifest["gaps"],
                "written": pack.written,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
