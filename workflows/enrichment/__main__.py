"""Enrich one user alert, or review risky users (B-44). Reads the mock tenant; runs no write lever.

    uv run --frozen python -m workflows.enrichment pack <client> <upn> [--as tech-ana] [--prompt]
    uv run --frozen python -m workflows.enrichment review <client> [--as tech-ana]

Prints JSON (the technician view holds times and places), or with --prompt only the text that may go to a model.
Exit 0 = ran, 2 = refused or bad input.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from types import SimpleNamespace

from core.audit import AuditLog
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, LeverRunner, MockTenant, Registry
from workflows.enrichment.enrichment import EnrichmentError, enrich, prompt_text, review_risky_users


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.enrichment", description="Alert enrichment and risky-user review (synthetic)."
    )
    parser.add_argument("command", choices=("pack", "review"))
    parser.add_argument("client")
    parser.add_argument("upn", nargs="?")
    parser.add_argument("--as", dest="identity", default="tech-ana", help="technician identity (default tech-ana)")
    parser.add_argument("--prompt", action="store_true", help="print only the model-safe text")
    parser.add_argument("--audit", default=".tmp/enrichment-audit.jsonl", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    runner = LeverRunner(Registry.load(), IdentityStore.load(), MockTenant(DEFAULT_TENANT_DIR), AuditLog(args.audit))
    try:
        if args.command == "review":
            out = json.dumps(dataclasses.asdict(review_risky_users(runner, args.client, args.identity)), indent=2)
        else:
            if not args.upn:
                print("error: pack needs a user principal name", file=sys.stderr)
                return 2
            alert = SimpleNamespace(id="A-0000", client=args.client, entity_kind="user", entity_id=args.upn)
            pack = enrich(runner, args.client, alert, args.identity)
            out = prompt_text(pack) if args.prompt else json.dumps(dataclasses.asdict(pack), indent=2)
    except EnrichmentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
