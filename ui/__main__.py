"""Serve the approval queue and audit viewer on 127.0.0.1 (synthetic data, mock tenant).

    uv run python -m core.queue seed --demo
    uv run python -m ui --state .tmp/demo --demo [--port 8765]          # demo picker, synthetic
    uv run python -m ui --state .tmp/demo --auth-config FILE [--port N]  # Entra ID tokens (B-89)

Exactly one of --demo or --auth-config is required (B89-1): the demo identity picker is not
authentication (STD-ID-7) and is never the silent default. Exit 2 when neither or both are given,
when the auth config does not load, or when the host is anything but 127.0.0.1 (SC-3); nothing is
bound or created then.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.auth import AuthConfigError, TokenValidator, load_auth_config
from core.identity import IdentityConfigError, IdentityStore
from core.queue import DEFAULT_STATE_DIR, open_queue
from ui.app import LOOPBACK, App, check_host, make_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ui", description="Local approval queue and audit viewer.")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_DIR, help="demo state folder (default .tmp/demo)")
    parser.add_argument("--host", default=LOOPBACK, help="must be 127.0.0.1; anything else is refused")
    parser.add_argument("--port", type=int, default=8765)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true", help="demo identity picker over synthetic leads (not sign-in)")
    mode.add_argument("--auth-config", type=Path, help="Entra ID token settings (JSON); approvals need a valid token")
    args = parser.parse_args(argv)
    try:
        check_host(args.host)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if not args.demo and args.auth_config is None:
        print("ERROR: choose --demo (synthetic picker, not sign-in) or --auth-config FILE (Entra ID)", file=sys.stderr)
        return 2
    validator: TokenValidator | None = None
    if args.auth_config is not None:
        try:
            validator = TokenValidator(load_auth_config(args.auth_config), IdentityStore.load())
        except (AuthConfigError, IdentityConfigError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    server = make_server(App(open_queue(args.state), auth=validator), args.host, args.port)
    print(f"Approval queue on http://{LOOPBACK}:{server.server_port}/ (synthetic data; Ctrl+C to stop)")
    if validator is None:
        print("Sign-in: demo identity picker (--demo); synthetic, not authentication")
    else:
        print("Sign-in: Entra ID token required for every listing and decision (B-89)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
