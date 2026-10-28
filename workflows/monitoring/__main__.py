"""CLI: ``python -m workflows.monitoring evaluate --snapshot <file> [--rules <file>]`` and ``check-rules``.

Exit codes: 0 no alerts (or rules valid), 1 at least one alert, 2 an input could not be read or is invalid.
Alerts are printed as JSON; nothing is sent anywhere.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from workflows.monitoring.evaluator import evaluate, load_snapshot
from workflows.monitoring.rules import RulesError, load_rules


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.monitoring", description="Evaluate monitoring alert rules."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    ev = sub.add_parser("evaluate", help="evaluate the rules over a snapshot file")
    ev.add_argument("--snapshot", type=Path, required=True)
    ev.add_argument("--rules", type=Path, default=None)
    ck = sub.add_parser("check-rules", help="validate a rule file")
    ck.add_argument("--rules", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        rules = load_rules(args.rules)
        if args.command == "check-rules":
            print(f"OK: {len(rules.rules)} rules, version {rules.version}")
            return 0
        alerts = evaluate(rules, load_snapshot(args.snapshot))
    except RulesError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, ValidationError) as exc:
        print(f"ERROR: cannot use the snapshot: {exc.__class__.__name__}", file=sys.stderr)
        return 2
    print(json.dumps([a.model_dump(mode="json") for a in alerts], indent=2, sort_keys=True))
    return 1 if alerts else 0


if __name__ == "__main__":
    sys.exit(main())
