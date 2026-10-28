"""Draft answers for a synthetic questionnaire (B-60). Writes files only; sends and approves nothing.

    uv run --frozen python -m workflows.questionnaires draft fixtures/questionnaires/security_questionnaire.json \
        --owner "Dana Whitfield" --out build/questionnaires

`--owner` is the named person who must review the draft (required). Without `--out` the markdown goes to stdout.
Exit 0 = drafted, 2 = bad input (unreadable or unlabelled questionnaire, unusable client, unnamed owner).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from workflows.questionnaires.drafts import (
    NEEDS_PERSON,
    QuestionnaireError,
    build_context,
    check_draft,
    draft_questionnaire,
    load_questionnaire,
    questionnaire_json,
    render_questionnaire,
    validate_owner,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m workflows.questionnaires", description="Draft cited answers.")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("draft", help="draft answers for one synthetic questionnaire file")
    cmd.add_argument("file", type=Path)
    cmd.add_argument("--owner", required=True, help="the named person who must review the draft")
    cmd.add_argument("--out", type=Path, help="directory for <name>.md and <name>.json (default: markdown to stdout)")
    args = parser.parse_args(argv)
    try:
        owner = validate_owner(args.owner)
        q = load_questionnaire(args.file)
        ctx = build_context()
        drafts = draft_questionnaire(ctx, q, owner)
        problems = [f"{d.item_id}: {p}" for d in drafts for p in check_draft(ctx, q.client, d)]
        if problems:
            raise QuestionnaireError("a draft failed its own evidence check: " + "; ".join(problems))
    except QuestionnaireError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    markdown = render_questionnaire(q, drafts, owner)
    answered = sum(not d.refused for d in drafts)
    summary = f"{len(drafts)} items: {answered} answered (DRAFT), {len(drafts) - answered} {NEEDS_PERSON}."
    if args.out is None:
        print(markdown)
        print(summary, file=sys.stderr)
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{args.file.stem}.md").write_text(markdown + "\n", encoding="utf-8")
    payload = json.dumps(questionnaire_json(q, drafts, owner), indent=2, sort_keys=True)
    (args.out / f"{args.file.stem}.json").write_text(payload + "\n", encoding="utf-8")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
