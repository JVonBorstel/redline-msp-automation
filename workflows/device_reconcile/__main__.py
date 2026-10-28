"""Device reconciliation for one client (B-61). Reads fixtures; writes nothing; runs nothing.

    uv run --frozen python -m workflows.device_reconcile contoso-dental [--as-of 2026-10-22T12:00:00Z]

Prints JSON: counts, one entry per device with the systems that know it, every mismatch (only in one system, stale,
duplicate) and the RMM account's components, listed read-only. Exit 0 = ran, 2 = bad input or an adapter that is not
configured (``--clients`` selects adapters from config/clients/<id>.json bindings; a non-mock binding fails closed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from adapters.base import AdapterError
from adapters.intune import IntuneMock
from adapters.rmm import RmmMock
from workflows.device_reconcile.psa_assets import PsaAssetsMock
from workflows.device_reconcile.reconcile import (
    DEFAULT_CONFIG_PATH,
    ReconcileError,
    Sources,
    build_sources,
    component_inventory,
    load_config,
    reconcile,
    summary,
    utc,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.device_reconcile",
        description="Match one client's devices across RMM, Intune and PSA assets (synthetic data; read-only).",
    )
    parser.add_argument("client", help="client id, e.g. contoso-dental")
    parser.add_argument("--as-of", help="reconcile as at this UTC time (default: the RMM fixture's pinned time)")
    parser.add_argument("--clients", type=Path, help="select adapters from the bindings in this config/clients folder")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.clients is not None:
            built = build_sources(args.client, config_dir=args.clients)
            if built.sources is None:
                print(f"error: {built.reason}", file=sys.stderr)
                return 2
            sources = built.sources
        else:
            sources = Sources(
                RmmMock.for_fixture(args.client),
                IntuneMock.for_fixture(args.client),
                PsaAssetsMock.for_fixture(args.client),
            )
        as_of: str | None = args.as_of or (sources.rmm.as_of if isinstance(sources.rmm, RmmMock) else None)
        if as_of is None:
            print("error: --as-of is required for this adapter", file=sys.stderr)
            return 2
        config = load_config(args.config)
        rec = reconcile(sources.rmm, sources.intune, sources.psa, utc(as_of), config)
        components = component_inventory(sources.rmm)
    except (AdapterError, ReconcileError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary(rec, components), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
