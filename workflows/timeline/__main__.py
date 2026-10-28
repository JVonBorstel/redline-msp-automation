"""Print one client's incident timeline or one fact pack (B-48). Reads only; registers nothing; proposes nothing.

    uv run --frozen python -m workflows.timeline export --client contoso-dental --audit-dir state/audit [--text]
    uv run --frozen python -m workflows.timeline pack recovery-point --client contoso-dental

The export is format incident-timeline/1 (JSON Lines, header first; the format B-46 defined); --text prints the same
timeline as Markdown for a person. Exit 0 = printed, 2 = bad input or a missing source, 3 = the audit chain did not
verify (nothing printed). Declaration and notification decisions belong to the client and its counsel.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from workflows.timeline.timeline import (
    PACK_KINDS,
    ChainNotVerified,
    TimelineError,
    build_pack,
    build_timeline,
    render,
    render_text,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.timeline",
        description="Read-only incident timeline and fact packs for one client (synthetic data).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser(
        "export",
        help="JSON Lines timeline (--text: Markdown) from the verified audit chain, alerts, firewall log, ticket ids",
    )
    export.add_argument("--audit-dir", type=Path, required=True, help="the audit folder holding <client>.jsonl")
    export.add_argument("--ticket", action="append", default=[], help="a ticket id of this client (repeatable)")
    export.add_argument("--incident", help="incident id, 1-40 letters, digits or dashes (default: derived)")
    export.add_argument("--text", action="store_true", help="Markdown for a person instead of JSON Lines")
    pack = sub.add_parser("pack", help="JSON fact pack: facts and gaps only")
    pack.add_argument("kind", choices=tuple(PACK_KINDS))
    pack.add_argument("--audit-dir", type=Path, help="the audit folder (needed for 'breach')")
    for cmd in (export, pack):
        cmd.add_argument("--client", required=True, help="client id, e.g. contoso-dental")
        cmd.add_argument(
            "--since", help="ISO time with a zone; rows at or after it (not for recovery-point or dns packs)"
        )
        cmd.add_argument(
            "--until",
            help="ISO time with a zone; rows at or before it (recovery-point: the cutoff; not for the dns pack)",
        )
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            timeline = build_timeline(
                args.client,
                args.audit_dir,
                since=args.since,
                until=args.until,
                tickets=args.ticket,
                incident=args.incident,
            )
            out = render_text(timeline) if args.text else render(timeline)
        else:
            facts = build_pack(args.kind, args.client, audit_dir=args.audit_dir, since=args.since, until=args.until)
            out = json.dumps(facts, indent=2) + "\n"
    except ChainNotVerified as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except TimelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
