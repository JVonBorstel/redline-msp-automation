"""Assemble the facts for one human-only identity decision (B-37). Reads fixtures; registers nothing; proposes nothing.

    uv run --frozen python -m workflows.factpack termination --client contoso-dental --target <upn>
    uv run --frozen python -m workflows.factpack policy --client contoso-dental --target "Require MFA for all users"

Kinds: termination, caller, role (one person) and policy (one Conditional Access policy). Prints JSON.
Exit 0 = ran, 2 = bad input or a target that is not in this client's data. The decision stays with a named human.
"""

from __future__ import annotations

import argparse
import json
import sys

from workflows.factpack.factpack import KINDS, FactpackError, build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.factpack",
        description="Read-only fact pack for a human-only identity decision (synthetic data).",
    )
    parser.add_argument("kind", choices=KINDS)
    parser.add_argument("--client", required=True, help="client id, e.g. contoso-dental")
    parser.add_argument("--target", required=True, help="a user principal name or id; for 'policy' a policy id or name")
    args = parser.parse_args(argv)
    try:
        pack = build(args.kind, args.client, args.target)
    except FactpackError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(pack, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
