"""KB drafts and stale/conflict detection (B-58). Writes review files; publishes nothing, writes to no KB.

    uv run --frozen python -m workflows.kb_drafts drafts contoso-dental [--out build/kb-drafts]
    uv run --frozen python -m workflows.kb_drafts detect contoso-dental [--as-of 2026-10-23] [--max-age-days 365]

Exit 0 = done, 2 = bad input.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from workflows.kb_drafts.detect import (
    DEFAULT_MAX_AGE_DAYS,
    DetectError,
    detect_report,
    write_detect_report,
)
from workflows.kb_drafts.detect import DEFAULT_OUT_DIR as DETECT_OUT
from workflows.kb_drafts.drafts import DEFAULT_OUT_DIR as DRAFTS_OUT
from workflows.kb_drafts.drafts import DraftError, build_drafts, write_drafts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m workflows.kb_drafts", description="KB drafts (B-58).")
    sub = parser.add_subparsers(dest="command", required=True)
    drafts = sub.add_parser("drafts", help="write DRAFT articles from one client's resolved tickets")
    drafts.add_argument("client")
    drafts.add_argument("--out", type=Path, default=DRAFTS_OUT)
    detect = sub.add_parser("detect", help="list stale and conflicting articles (and drafts that conflict)")
    detect.add_argument("client")
    detect.add_argument("--as-of", default=None, help="ISO date (default: the review fixture's pinned date)")
    detect.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    detect.add_argument("--out", type=Path, default=DETECT_OUT)
    args = parser.parse_args(argv)
    try:
        if args.command == "drafts":
            draft_set = build_drafts(args.client)
            written = write_drafts(draft_set, args.out)
            print(
                f"{args.client}: {len(draft_set.drafts)} DRAFT articles, {len(draft_set.withheld)} withheld, "
                f"{len(draft_set.skipped)} skipped, {len(draft_set.rejected)} rejected. "
                f"Nothing was published; a person publishes each draft by hand ({written[0].parent})"
            )
        else:
            report = detect_report(
                args.client,
                as_of=args.as_of,
                max_age_days=args.max_age_days,
                drafts=build_drafts(args.client).drafts,
            )
            written = write_detect_report(report, args.out)
            print(
                f"{args.client} as of {report.as_of}: stale {len(report.stale)}, conflicts {len(report.conflicts)}, "
                f"draft conflicts {len(report.draft_conflicts)} (read-only; nothing was published; {written[1]})"
            )
    except (DraftError, DetectError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
