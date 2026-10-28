"""B-96 command line.

    uv run --frozen python -m workflows.training check [--root DIR]

Exit 0 = every cited file and test exists and every claim is tagged, 1 = a check failed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.paths import REPO_ROOT
from workflows.training.claims import check_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m workflows.training", description="Check the B-96 pages.")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="fail when a cited file or test does not exist or a claim has no tag")
    check.add_argument("--root", type=Path, default=REPO_ROOT, help="repo folder to check (default: this repo)")
    args = parser.parse_args(argv)
    problems = check_all(args.root)
    for problem in problems:
        print(problem)
    print("B-96 checks: ok" if not problems else f"B-96 checks: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
