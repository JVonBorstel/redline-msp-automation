"""Roadmap and proof numbers read from a snapshot of the repository. Read-only: it only reads files.

Standard library only. The output is sanitised for a public page: wave names and goals come from content/blueprint.json
(written for the public), item titles come from the roadmap, and any title that contains a word on the banned list
fails the build instead of being silently rewritten.

The banned list is stored ROT13-encoded so that this file does not itself contain the words it forbids.
"""

from __future__ import annotations

import codecs
import json
import re
from pathlib import Path
from typing import Any

_BANNED_ROT13 = r"tb[\f-]*jrfg|tbjrfg|\otj\o|vagreivrj|rzcyblre|uvevat|erpehvg|fnynel|bssre yrggre|pbzcrafngvba|xvgpura|nhgbgnfx|pnerre|pnaqvqngr|wbo[\f-]*uhag|zl[\f-]+erfhzr|erfhzr[\f-]+(?:cqs|svyr|yvax)|eéfhzé|pynhqr"
BANNED = re.compile(codecs.decode(_BANNED_ROT13, "rot13"), re.IGNORECASE)
STATUS_ORDER = ("built", "specced", "planned")
SKIP_DIRS = {".git", ".venv", "__pycache__", ".tmp", "node_modules"}


def clean(text: str, where: str) -> str:
    if BANNED.search(text):
        raise SystemExit(f"stats failed: a banned word is in {where}: add a title override in content/blueprint.json")
    return text


def list_files(root: Path) -> list[str]:
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and not any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            out.append(p.relative_to(root).as_posix())
    return out


def collect(root: Path, blueprint: dict[str, Any], sha: str, commit_date: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Roadmap and proof numbers from the files under root (a snapshot of the repository at commit sha)."""
    paths = set(list_files(root))
    roadmap = json.loads((root / "map" / "roadmap.json").read_text(encoding="utf-8"))
    overrides: dict[str, str] = blueprint.get("title_overrides", {})
    names: dict[str, dict[str, str]] = blueprint["waves"]

    waves = []
    totals = {"built": 0, "specced": 0, "planned": 0}
    for w in roadmap["waves"]:
        shown = names[w["id"]]
        items = []
        for it in w["items"]:
            iid = it["id"]
            if f"docs/changes/{iid}.md" in paths:
                status = "built"
            elif f"specs/{iid}.md" in paths:
                status = "specced"
            else:
                status = "planned"
            title = clean(overrides.get(iid, it["title"]), f"title of {iid}")
            items.append({"id": iid, "title": title, "size": it.get("size", ""), "status": status})
            totals[status] += 1
        counts = {s: sum(1 for i in items if i["status"] == s) for s in STATUS_ORDER}
        waves.append(
            {
                "id": w["id"],
                "name": clean(shown["name"], w["id"]),
                "goal": clean(shown["goal"], w["id"]),
                "items": items,
                "counts": counts,
            }
        )
    not_now = [{"id": n["id"], "what": clean(n["what"], n["id"])} for n in roadmap["not_now"] if n["id"] != "NN-11"]
    roadmap_out = {
        "ref": sha[:12],
        "commit_date": commit_date,
        "waves": waves,
        "not_now": not_now,
        "totals": {**totals, "items": sum(totals.values())},
    }

    per_file = []
    for rel in sorted(paths):
        if rel.startswith("tests/") and rel.endswith((".py", ".ps1", ".mjs")):
            n = sum(
                1
                for line in (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
                if "def test_" in line
            )
            if n:
                per_file.append(n)
    decisions = len(
        re.findall(r"^## D-\d+", (root / "docs" / "DECISIONS.md").read_text(encoding="utf-8"), re.MULTILINE)
    )
    unverified = len(
        re.findall(r"^\| U-\d+", (root / "docs" / "UNVERIFIED.md").read_text(encoding="utf-8"), re.MULTILINE)
    )
    levers = sum(1 for p in paths if re.fullmatch(r"levers/registry\.d/.+\.json", p))
    proof_out = {
        "ref": sha[:12],
        "commit_date": commit_date,
        "test_functions": sum(per_file),
        "test_files": len(per_file),
        "decisions": decisions,
        "unverified_claims": unverified,
        "specs": sum(1 for p in paths if re.fullmatch(r"specs/B-\d+\.md", p)),
        "change_notes": sum(1 for p in paths if re.fullmatch(r"docs/changes/B-\d+\.md", p)),
        "lever_fragments": levers,
    }
    return roadmap_out, proof_out
