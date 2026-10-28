"""Draft the affected-person notice for one executed proposal (B-04). Synthetic data only; nothing is sent.

    uv run --frozen python -m workflows.notify P-0123456789ab --state .tmp/demo

Writes <state>/notices/<proposal-id>.md and prints the draft. A person reviews and sends it (HO-9).
Exit 0 = draft written, 1 = refused (the proposal is not executed), 2 = unknown proposal or bad input.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from workflows.notify.notify import NotifyError, NotifyRefused, notice_for

DEFAULT_STATE = Path(__file__).resolve().parents[2] / ".tmp" / "demo"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.notify",
        description="Draft the notice for the person affected by one executed proposal (synthetic data; never sends).",
    )
    parser.add_argument("proposal_id", help="proposal id from the approval queue, e.g. P-0123456789ab")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE, help="state folder with queue.jsonl (.tmp/demo)")
    args = parser.parse_args(argv)
    try:
        path = notice_for(args.state, args.proposal_id)
    except NotifyRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    except NotifyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(path.read_text(encoding="utf-8"), end="")
    print(f"draft: {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
