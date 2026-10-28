"""Discovery pack and migration pre-flight for one client (B-77). Read-only: changes nothing, executes nothing.

    uv run --frozen python -m workflows.client_lifecycle discover  --client contoso-dental [--as-of DATE] [--out DIR]
    uv run --frozen python -m workflows.client_lifecycle preflight --client contoso-dental [--plan FILE]

Each command prints JSON. ``discover`` writes ``<out>/<client>/discovery.json`` (and the baseline's own report beside
it) and lists every gap. ``preflight`` lists every problem per check and ``ready``.
Exit 0 = ran (gaps and failed checks are results, listed in the output). Exit 2 = bad input; nothing ran.
There is no execute command: executing migrations is NN-04 (not now).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from workflows.client_lifecycle.discovery import DiscoveryError, discover, summary
from workflows.client_lifecycle.preflight import PreflightError, preflight

DEFAULT_OUT = Path(".tmp") / "discovery"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.client_lifecycle",
        description="Client discovery pack and migration pre-flight checks (synthetic data; read-only).",
    )
    parser.add_argument("command", choices=("discover", "preflight"))
    parser.add_argument("--client", required=True, help="client id, e.g. contoso-dental")
    parser.add_argument("--as-of", help="discover: the date to report against, YYYY-MM-DD (default: the baseline's)")
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help="discover: output folder (default .tmp/discovery)"
    )
    parser.add_argument("--plan", type=Path, help="preflight: migration plan file (default: data/migrations/<client>)")
    args = parser.parse_args(argv)
    try:
        if args.command == "discover":
            print(json.dumps(summary(discover(args.client, args.out, as_of=args.as_of)), indent=2))
        else:
            print(json.dumps(preflight(args.client, args.plan).to_dict(), indent=2))
    except (DiscoveryError, PreflightError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
