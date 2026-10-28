"""Print the roadmap items of a wave as `gh issue create` commands or an Azure Boards CSV.

This tool only prints. It never runs `gh`, never calls a network and writes no file.
Source of truth: map/roadmap.json (same ids and fields as docs/ROADMAP.md).

    uv run python tools/roadmap_issues.py --wave W1
    uv run python tools/roadmap_issues.py --wave W1 --format ado-csv
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import shlex
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROADMAP = REPO_ROOT / "map" / "roadmap.json"
ADO_WORK_ITEM_TYPE = "User Story"
ADO_COLUMNS = ["Work Item Type", "Title", "Tags", "Iteration Path", "Description"]


def load_items(roadmap: Path, wave: str | None, item: str | None) -> list[dict[str, Any]]:
    """Return the roadmap items (each with its wave id added) matching the filters."""
    data = json.loads(roadmap.read_text(encoding="utf-8"))
    waves = data["waves"]
    known = [w["id"] for w in waves]
    if wave is not None and wave not in known:
        raise SystemExit(f"unknown wave {wave!r}; known waves: {', '.join(known)}")
    items: list[dict[str, Any]] = []
    for w in waves:
        if wave is not None and w["id"] != wave:
            continue
        for entry in w["items"]:
            if item is None or entry["id"] == item:
                items.append({**entry, "wave": w["id"], "wave_name": w["name"]})
    if not items:
        raise SystemExit("no roadmap items match the filters")
    return items


def labels_for(item: dict[str, Any]) -> list[str]:
    """Labels of one item: wave, size and (when set) owner-only."""
    labels = [f"wave:{item['wave']}", f"size:{item['size']}"]
    if item["owner_only"]:
        labels.append("owner-only")
    return labels


def title_for(item: dict[str, Any]) -> str:
    return f"{item['id']}: {item['title']}"


def _join(values: list[str]) -> str:
    return ", ".join(values) if values else "-"


def body_for(item: dict[str, Any]) -> str:
    """Issue body holding every roadmap field of the item."""
    lines = [
        f"Wave: {item['wave']} ({item['wave_name']})",
        f"Size: {item['size']}",
        f"Owner only: {'yes' if item['owner_only'] else 'no'}",
        f"Why: {item['why']}",
        f"Inventory ids: {_join(item['inventory_ids'])}",
        f"Controls: {_join(item['controls'])}",
        f"Depends on: {_join(item['depends_on'])}",
        f"Standards: {_join(item['standards'])}",
        "Owns:",
        *[f"- {path}" for path in item["owns"]],
        "Acceptance:",
        *[f"- {text}" for text in item["acceptance"]],
    ]
    return "\n".join(lines)


def gh_command(item: dict[str, Any]) -> str:
    parts = ["gh", "issue", "create", "--title", title_for(item)]
    for label in labels_for(item):
        parts += ["--label", label]
    parts += ["--milestone", item["wave"], "--body", body_for(item)]
    return " ".join(shlex.quote(p) for p in parts)


def ado_csv(items: list[dict[str, Any]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(ADO_COLUMNS)
    for item in items:
        writer.writerow(
            [
                ADO_WORK_ITEM_TYPE,
                title_for(item),
                "; ".join(labels_for(item)),
                item["wave"],
                body_for(item),
            ]
        )
    return out.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--wave", help="wave id such as W1 (default: every wave)")
    parser.add_argument("--item", help="a single item id such as B-09")
    parser.add_argument("--format", choices=["gh", "ado-csv"], default="gh")
    parser.add_argument("--roadmap", type=Path, default=DEFAULT_ROADMAP)
    args = parser.parse_args(argv)
    items = load_items(args.roadmap, args.wave, args.item)
    if args.format == "ado-csv":
        sys.stdout.write(ado_csv(items))
    else:
        for item in items:
            print(gh_command(item))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
