"""Serve the approval queue and audit viewer on 127.0.0.1 (synthetic data, mock tenant).

    uv run python -m core.queue seed --demo
    uv run python -m ui --state .tmp/demo --demo [--port 8765]          # demo picker, synthetic
    uv run python -m ui --state .tmp/demo --auth-config FILE [--port N]  # Entra ID tokens (B-89)
    ... [--client-records FILE]   # optional: client records (authorized contacts, hours, minimums)

Exactly one of --demo or --auth-config is required (B89-1): the demo identity picker is not
authentication (STD-ID-7) and is never the silent default. Exit 2 when neither or both are given,
when the auth config or the client records do not load, or when the host is anything but 127.0.0.1
(SC-3); nothing is bound or created then.

B-28: the page always runs the lever runner under a `RunnerPolicy`: R2 and R3 approvals must be
signed in (a token, or a demo pick that is accepted only with --demo and marked `demo` in the audit),
and an R3 lever needs two different leads; the first approval waits for the second. `--client-records`
is a JSON object mapping a client id to its record (`authorized_contacts`, `approver_minimum`,
`time_zone`, `business_hours`, `maintenance_window`); without it, levers that need an authorized
contact or a time window are refused (fail closed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from core.auth import AuthConfigError, TokenValidator, load_auth_config
from core.identity import IdentityConfigError, IdentityStore
from core.levers.runner import PolicyError, RunnerPolicy
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
    parser.add_argument("--client-records", type=Path, help="client records (JSON object: client id to record)")
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
    try:
        records = load_client_records(args.client_records)
        policy = RunnerPolicy(validator=validator, demo=bool(args.demo), client_records=records)
    except (OSError, ValueError) as exc:  # PolicyError and json errors are ValueErrors
        print(f"ERROR: client records: {exc}", file=sys.stderr)
        return 2

    server = make_server(App(open_queue(args.state, policy=policy), auth=validator), args.host, args.port)
    print(f"Approval queue on http://{LOOPBACK}:{server.server_port}/ (synthetic data; Ctrl+C to stop)")
    if validator is None:
        print("Sign-in: demo identity picker (--demo); synthetic, not authentication")
    else:
        print("Sign-in: Entra ID token required for every listing and decision (B-89)")
    print("Approvals: R3 levers need two different leads; the first approval waits for the second (B-28)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def load_client_records(path: Path | None) -> dict[str, dict[str, Any]]:
    """The client records file, or none. Raises ValueError (or OSError) when it is not a JSON object of objects."""
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(isinstance(k, str) and isinstance(v, dict) for k, v in raw.items()):
        raise PolicyError("expected a JSON object mapping each client id to its record object")
    return raw


if __name__ == "__main__":
    sys.exit(main())
