"""Write the item blocks of docs/ROADMAP.md from map/roadmap.json, so owns, acceptance and standards are typed once.

Each wave's blocks sit between `<!-- gen:items:start -->` and `<!-- gen:items:end -->` (one pair per wave, in wave
order). Everything outside the markers is left byte-identical, including the file's line endings.

    uv run --frozen python tools/gen_roadmap_md.py            # rewrite docs/ROADMAP.md
    uv run --frozen python tools/gen_roadmap_md.py --check    # exit 1 if it is out of date, write nothing
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
START = "<!-- gen:items:start -->"
END = "<!-- gen:items:end -->"
FIX_COMMAND = "uv run --frozen python tools/gen_roadmap_md.py"
_ACCEPTANCE = re.compile(r"(B\d{2}-\d+): (.+)", re.S)
_PAIR = re.compile(re.escape(START) + r"\n(.*?)\n" + re.escape(END), re.S)


def render_item(item: dict[str, Any]) -> str:
    """One item block. A malformed acceptance line raises, naming the item; it is never skipped."""
    lines = []
    for line in item["acceptance"]:
        match = _ACCEPTANCE.fullmatch(line)
        if not match:
            raise ValueError(f"{item['id']}: acceptance line is not 'B<nn>-<k>: text': {line!r}")
        lines.append(f"  - **{match[1]}** {match[2]}")
    owner = " (owner only: protected files, the owner applies)" if item.get("owner_only") else ""
    owns = ", ".join(f"`{p}`" for p in item["owns"])
    head = [
        f"**`{item['id']}` {item['title']}**{owner}",
        f"- Why: {item['why']}",
        f"- Owns: {owns}",
        f"- Standards: {', '.join(item['standards'])}",
        "- Acceptance:",
    ]
    return "\n".join([*head, *lines])


def render_waves(roadmap: dict[str, Any]) -> list[str]:
    """One text per wave: its item blocks, a blank line apart."""
    return ["\n\n".join(render_item(i) for i in wave["items"]) for wave in roadmap["waves"]]


def splice(text: str, blocks: list[str]) -> str:
    """Replace what sits between each marker pair with the matching block. Text uses \\n line endings."""
    pairs = _PAIR.findall(text)
    if not (text.count(START) == text.count(END) == len(pairs) == len(blocks)) or any(START in p for p in pairs):
        raise ValueError(
            f"need {len(blocks)} well-formed marker pairs (one per wave), found {text.count(START)} start and "
            f"{text.count(END)} end markers"
        )
    todo = iter(blocks)
    return _PAIR.sub(lambda _: f"{START}\n{next(todo)}\n{END}", text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("root", nargs="?", default=str(REPO_ROOT), help="repo root (default: this repo)")
    parser.add_argument("--check", action="store_true", help="exit 1 if docs/ROADMAP.md is out of date; write nothing")
    args = parser.parse_args(argv)
    root = Path(args.root)
    path = root / "docs" / "ROADMAP.md"
    try:
        roadmap = json.loads((root / "map" / "roadmap.json").read_text(encoding="utf-8"))
        raw = path.read_bytes().decode("utf-8")
        old = raw.replace("\r\n", "\n")
        new = splice(old, render_waves(roadmap))
    except (OSError, ValueError, KeyError) as exc:
        print(f"gen_roadmap_md: cannot generate: {exc}")
        return 2
    if new == old:
        print("docs/ROADMAP.md: unchanged")
        return 0
    if args.check:
        print(f"docs/ROADMAP.md: item blocks differ from map/roadmap.json; fix with: {FIX_COMMAND}")
        return 1
    eol = "\r\n" if "\r\n" in raw else "\n"
    path.write_bytes(new.replace("\n", eol).encode("utf-8"))
    print("docs/ROADMAP.md: wrote the item blocks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
