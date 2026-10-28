"""Monthly patch pack (B-67). Writes report files and drafts; approves, deploys, schedules, sends and upgrades nothing.

    uv run --frozen python -m workflows.patching build contoso-dental [--out build/patching]
    uv run --frozen python -m workflows.patching verify build/patching/2026-10/contoso-dental.json
    uv run --frozen python -m workflows.patching clients

Exit 0 = done (verify: matches), 1 = verify mismatch, 2 = bad input (unknown client, changed fixture shape).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from workflows.patching.patching import (
    DEFAULT_OUT_DIR,
    PatchingError,
    VerifyError,
    list_clients,
    verify,
    write_pack,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m workflows.patching", description="Monthly patch pack per client.")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="write <client>.json and <client>.md with .sha256 sidecars")
    build.add_argument("client", help="client id, e.g. contoso-dental")
    build.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    ver = sub.add_parser("verify", help="re-hash a written file against its .sha256")
    ver.add_argument("path", type=Path)
    sub.add_parser("clients", help="list the clients that have patch fixtures")
    args = parser.parse_args(argv)
    if args.command == "clients":
        print("\n".join(list_clients()))
        return 0
    if args.command == "verify":
        try:
            digest = verify(args.path)
        except VerifyError as exc:
            print(f"MISMATCH: {exc}", file=sys.stderr)
            return 1
        print(f"OK {digest}  {args.path.name}")
        return 0
    try:
        written = write_pack(args.client, args.out)
    except PatchingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "json": str(written.json_path),
                "md": str(written.md_path),
                "json_sha256": written.json_sha256,
                "md_sha256": written.md_sha256,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
