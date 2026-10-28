"""B-95 command line. Dry run unless --write; nothing but the generated governance files is ever written.

    uv run --frozen python -m workflows.assurance check
    uv run --frozen python -m workflows.assurance generate [--write]
    uv run --frozen python -m workflows.assurance score [FILE ...] [--json]
    uv run --frozen python -m workflows.assurance briefs check
    uv run --frozen python -m workflows.assurance briefs ranking [--write]

Exit 0 = fine, 1 = a check failed, 2 = bad input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.levers.registry import NeverAutomate, RegistryError
from core.paths import REPO_ROOT
from workflows.assurance import briefs
from workflows.assurance.intake import IntakeError, Scored, load_intake, rank, score
from workflows.assurance.render import check_all, drift, generate_all, ordered, score_examples
from workflows.assurance.roi import RoiError, load_roi
from workflows.assurance.rubric import RubricError, load_rubric


def _table(scored: list[Scored]) -> str:
    position = {s.id: n for n, s in enumerate(rank(scored), start=1)}
    lines = ["rank  id      risk  sensitivity  priority  verdict"]
    for s in ordered(scored):
        pri = "-" if s.priority is None else f"{s.priority:.2f}"
        lines.append(
            f"{position.get(s.id, '-')!s:<5} {s.id:<7} {s.risk_class:<5} {s.sensitivity:<12} {pri:<9} {s.verdict}"
        )
        lines += [f"        {r}" for r in s.reasons]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.assurance", description="Use-case intake and assurance pages."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="run every check; exit 1 on a problem")
    gen = sub.add_parser("generate", help="regenerate the governance pages; a dry run unless --write")
    gen.add_argument("--write", action="store_true", help="write the files (default: only list what differs)")
    sc = sub.add_parser("score", help="score intake files (default: the synthetic examples)")
    sc.add_argument("files", nargs="*", type=Path)
    sc.add_argument("--json", action="store_true", help="print JSON with the full reasons")
    br = sub.add_parser("briefs", help="B-97: check the radar, brief, plan and review; refresh the ranking table")
    br_sub = br.add_subparsers(dest="briefs_command", required=True)
    br_sub.add_parser("check", help="run the B-97 checks; exit 1 on a problem")
    rk = br_sub.add_parser("ranking", help="compare (or with --write, refresh) the ranking table in the brief")
    rk.add_argument("--write", action="store_true", help="rewrite the table (default: only report)")
    args = parser.parse_args(argv)
    try:
        if args.command == "briefs":
            if args.briefs_command == "check":
                problems = briefs.check_all(REPO_ROOT)
                for problem in problems:
                    print(problem)
                print("B-97 checks: ok" if not problems else f"B-97 checks: {len(problems)} problem(s)")
                return 1 if problems else 0
            in_sync = briefs.ranking_block(
                (REPO_ROOT / briefs.PAGES["brief"]).read_text(encoding="utf-8")
            ) == briefs.render_ranking(REPO_ROOT)
            if args.write:
                briefs.write_ranking(REPO_ROOT)
                print("ranking table written" if not in_sync else "ranking table already in sync")
            else:
                print("ranking table is in sync (dry run)" if in_sync else "ranking table differs (dry run)")
            return 0
        if args.command == "check":
            problems = check_all(REPO_ROOT)
            for problem in problems:
                print(problem)
            print("B-95 checks: ok" if not problems else f"B-95 checks: {len(problems)} problem(s)")
            return 1 if problems else 0
        if args.command == "generate":
            outputs = generate_all(REPO_ROOT)
            differing = drift(REPO_ROOT, outputs)
            if not args.write:
                print("\n".join(differing) if differing else f"{len(outputs)} generated files are in sync (dry run)")
                return 0
            for rel, text in outputs.items():
                (REPO_ROOT / rel).write_bytes(text.encode("utf-8"))
            print(f"wrote {len(outputs)} files")
            return 0
        if args.files:
            rubric = load_rubric()
            roi = {row.id: row for row in load_roi()}
            never = NeverAutomate.load()
            scored = [score(load_intake(f), rubric=rubric, roi=roi, never=never) for f in args.files]
        else:
            scored = score_examples(REPO_ROOT)
        if args.json:
            print(json.dumps([s.as_dict() for s in ordered(scored)], indent=2))
        else:
            print(_table(scored))
        return 0
    except (IntakeError, RoiError, RubricError, RegistryError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
