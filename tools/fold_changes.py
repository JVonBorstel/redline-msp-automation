"""Fold a wave's change fragments (docs/changes/B-nn.md) into the shared ledgers.

A fragment has one `## <LEDGER>` section per ledger it changes: DECISIONS, COVERAGE,
CHANGELOG, RUNBOOKS (see docs/changes/README.md). Each folded block is preceded by a marker
comment `<!-- fold:B-nn:LEDGER -->`; a block whose marker is already in the ledger is skipped,
so a second run changes nothing.

    uv run python tools/fold_changes.py --wave W1 --dry-run
    uv run python tools/fold_changes.py --wave W1
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGERS = {
    "DECISIONS": "docs/DECISIONS.md",
    "COVERAGE": "docs/COVERAGE.md",
    "CHANGELOG": "CHANGELOG.md",
    "RUNBOOKS": "docs/RUNBOOKS.md",
}
_HEADING = re.compile(r"^## +(\S+)\s*$")


def wave_item_ids(roadmap: Path, wave: str) -> list[str]:
    data = json.loads(roadmap.read_text(encoding="utf-8"))
    for w in data["waves"]:
        if w["id"] == wave:
            return [item["id"] for item in w["items"]]
    raise SystemExit(f"unknown wave {wave!r}")


def parse_fragment(text: str) -> dict[str, str]:
    """Map ledger name to the section text; sections that are empty or say `none` are dropped."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            current = match.group(1).upper()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    result: dict[str, str] = {}
    for name, lines in sections.items():
        body = "\n".join(lines).strip()
        if name in LEDGERS and body and body.lower().rstrip(".") != "none":
            result[name] = body
    return result


def marker(item_id: str, ledger: str) -> str:
    return f"<!-- fold:{item_id}:{ledger} -->"


def plan_edits(root: Path, wave: str, roadmap: Path) -> list[tuple[str, str, str]]:
    """Return (item id, ledger name, block) for every block not yet in its ledger."""
    edits: list[tuple[str, str, str]] = []
    for item_id in wave_item_ids(roadmap, wave):
        fragment = root / "docs" / "changes" / f"{item_id}.md"
        if not fragment.is_file():
            continue
        for ledger, body in parse_fragment(fragment.read_text(encoding="utf-8")).items():
            path = root / LEDGERS[ledger]
            existing = path.read_text(encoding="utf-8") if path.is_file() else ""
            if marker(item_id, ledger) not in existing:
                edits.append((item_id, ledger, f"{marker(item_id, ledger)}\n{body}"))
    return edits


def apply_edits(root: Path, edits: list[tuple[str, str, str]]) -> None:
    for _item_id, ledger, block in edits:
        path = root / LEDGERS[ledger]
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_bytes().decode("utf-8") if path.is_file() else ""
        eol = "\r\n" if "\r\n" in existing else "\n"
        lead = ""
        if existing:
            lead = eol if existing.endswith("\n") else eol * 2
        text = lead + block.replace("\n", eol) + eol
        with path.open("ab") as handle:
            handle.write(text.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--wave", required=True, help="wave id such as W1")
    parser.add_argument("--dry-run", action="store_true", help="print the edits, change nothing")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--roadmap", type=Path, default=None)
    args = parser.parse_args(argv)
    roadmap = args.roadmap or args.root / "map" / "roadmap.json"
    edits = plan_edits(args.root, args.wave, roadmap)
    verb = "would append" if args.dry_run else "append"
    for item_id, ledger, block in edits:
        print(f"{verb} to {LEDGERS[ledger]} ({item_id}):")
        print(block)
        print()
    if not edits:
        print("nothing to fold")
    elif not args.dry_run:
        apply_edits(args.root, edits)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
