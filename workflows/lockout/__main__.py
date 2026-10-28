"""Explain why one person cannot sign in (B-39). Reads the mock sign-in log; runs no write lever.

    uv run --frozen python -m workflows.lockout <client> <upn> [--as tech-ana] [--prompt]

Prints the technician view as JSON (it contains IP addresses and places), or with --prompt only the text that may go
to a model. Exit 0 = ran, 2 = refused or bad input.
"""

from __future__ import annotations

import argparse
import json
import sys

from core.audit import AuditLog
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, LeverRunner, MockTenant, Registry
from workflows.lockout.lockout import LockoutError, investigate, prompt_text, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.lockout", description="Sign-in failure investigation (synthetic)."
    )
    parser.add_argument("client")
    parser.add_argument("upn")
    parser.add_argument("--as", dest="identity", default="tech-ana", help="technician identity (default tech-ana)")
    parser.add_argument("--prompt", action="store_true", help="print only the model-safe text")
    parser.add_argument("--audit", default=".tmp/lockout-audit.jsonl", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    runner = LeverRunner(Registry.load(), IdentityStore.load(), MockTenant(DEFAULT_TENANT_DIR), AuditLog(args.audit))
    try:
        inv = investigate(runner, args.client, args.upn, args.identity)
    except LockoutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(prompt_text(inv) if args.prompt else json.dumps(summary(inv), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
