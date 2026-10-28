"""Run the lever MCP server on stdio (B-87). Nothing here opens a socket.

    uv run --frozen python -m mcp --as triage-bot
    uv run --frozen python -m mcp --as triage-bot --include-writes
    B87_MCP_TOKEN=<id token> uv run --frozen python -m mcp --auth-config config/mcp-auth.json

Exactly one of `--as` (a fixed identity from config/identities.json; the process owner is trusted to choose it) and
`--auth-config` (the caller is whoever the Entra ID token in the environment proves; audience, issuer, tenant and
expiry are checked on every call). Protocol messages go to stdout; diagnostics go to stderr. Exit 2 on a usage error.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from core.audit.router import AuditRouter
from core.auth import AuthConfigError, TokenValidator, load_auth_config
from core.identity import IdentityConfigError, IdentityStore
from core.levers import DEFAULT_TENANT_DIR, LeverRunner, MockTenant, Registry, RegistryError
from mcp.server import LeverMcpServer

DEMO_DIR = Path(__file__).resolve().parents[1] / ".tmp" / "demo"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m mcp", description="MCP server over registered levers (stdio).")
    parser.add_argument("--as", dest="identity", help="fixed caller identity from config/identities.json")
    parser.add_argument("--auth-config", type=Path, help="Entra ID token validation settings (JSON); token mode")
    parser.add_argument("--token-env", default="B87_MCP_TOKEN", help="environment variable holding the token")
    parser.add_argument("--include-writes", action="store_true", help="also list write levers, as proposals only")
    parser.add_argument("--state", type=Path, default=DEMO_DIR, help="state folder (default .tmp/demo)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if (args.identity is None) == (args.auth_config is None):
        print("usage error: give exactly one of --as and --auth-config", file=sys.stderr)
        return 2
    try:
        identities = IdentityStore.load()
        registry = Registry.load()
        validator = TokenValidator(load_auth_config(args.auth_config), identities) if args.auth_config else None
        tenant_dir = args.state / "tenant"
        if not tenant_dir.exists():
            shutil.copytree(DEFAULT_TENANT_DIR, tenant_dir)
        runner = LeverRunner(registry, identities, MockTenant(tenant_dir), AuditRouter(args.state / "audit"))
        server = LeverMcpServer(
            runner,
            identity=args.identity,
            validator=validator,
            token=os.environ.get(args.token_env) if validator else None,
            include_writes=args.include_writes,
        )
    except (IdentityConfigError, RegistryError, AuthConfigError, ValueError, OSError) as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return 2
    server.serve(sys.stdin.buffer, sys.stdout.buffer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
