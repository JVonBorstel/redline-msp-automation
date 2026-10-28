"""Audit chain verifier CLI.

    uv run python -m core.audit.verify <log> [--head <file>]

Exit 0: the chain is intact (and matches the head pin). Exit 1: broken, naming the first
broken seq. Exit 2: the log cannot be read. Without --head, the default head file next to the
log (<log>.head) is used when it exists; with no head pin at all, truncation of the newest
records cannot be detected and the output says so. The OK line counts v1 and v2 records
(B-17): a v1 prefix followed by v2 records is accepted, a v1 record after a v2 one is not.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.audit.chain import head_path_for, verify_chain


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.audit.verify", description="Verify a hash-chained audit log.")
    parser.add_argument("log", type=Path, help="audit log (JSONL)")
    parser.add_argument("--head", type=Path, default=None, help="head pin file (default: <log>.head if present)")
    args = parser.parse_args(argv)

    log: Path = args.log
    head: Path | None = args.head
    if head is None and head_path_for(log).exists():
        head = head_path_for(log)
    try:
        result = verify_chain(log, head)
    except OSError as exc:
        print(f"ERROR: cannot read {log}: {exc}", file=sys.stderr)
        return 2

    if result.ok:
        print(f"OK: {result.records} records, {result.reason} ({result.v1_records} v1, {result.v2_records} v2)")
        if head is None:
            print("WARNING: no head pin; deleting the newest records would not be detected", file=sys.stderr)
        return 0
    print(f"BROKEN at seq {result.broken_seq}: {result.reason} ({result.records} records verified before it)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
