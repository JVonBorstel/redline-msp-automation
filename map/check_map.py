"""Map integrity check for the mapping documents (stdlib only, no network, reads files only).

Run from the repo root:  uv run --frozen python map/check_map.py
Exit 0 = every cross-reference resolves; exit 1 = problems, one per line; exit 2 = a map file is missing or not JSON.

What it proves (the rules are listed in docs/map/README.md, section 6):
  inventory -> impact: every inventory item with an automation pattern (anything but none-keep-human) has exactly one
    impact chain, every chain points at a real inventory id, and leverage ranks 1-10 are each used once;
  controls: every C-nn named in impact.json, roadmap.json or a map document exists in controls.json, and a safeguard
    line that quotes a control uses its exact name and status;
  roadmap: every item names real inventory ids, control ids and STANDARDS sections; every inventory id is covered by an
    item or a not-now entry; dependencies resolve, point to the same or an earlier wave, and have no cycle; no two
    items in one wave create the same new path (or a path inside another item's folder);
  documents: the Markdown twins list exactly the ids in the JSON (01 = inventory, 02 = impact, ROADMAP = roadmap);
    the item blocks of docs/ROADMAP.md equal what tools/gen_roadmap_md.py generates from map/roadmap.json; every W-,
    B-, C-, STD-, ARC/TEN/SL/DR and wave step id cited in a map document exists; every map document starts with a
    strict status line (STD-DC-1).

Warnings (never change the exit code): an inventory risk_class that differs from the governance class (B06-6); two
items in one wave owning an existing file (the build automation runs same-file orders one after another).

Synthetic planning data only; this checks consistency, not truth.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

JsonObj = dict[str, Any]

MAP_FILES = ("inventory", "impact", "controls", "roadmap")
DOCS = (
    "docs/map/README.md",
    "docs/map/01-work-inventory.md",
    "docs/map/02-impact-chains.md",
    "docs/map/03-architecture-target.md",
    "docs/map/04-repo-organization.md",
    "docs/map/05-governance.md",
    "docs/map/06-decisions.md",
    "docs/map/07-msp-profile.md",
    "docs/STANDARDS.md",
    "docs/ROADMAP.md",
)
STATUS_WORDS = ("built", "mocked", "document-only", "planned", "skeleton", "outline")
PATTERNS = {"agent-triage", "read-lever", "write-lever-approval", "report", "eval", "none-keep-human"}
RISK_CLASSES = {"R0", "R1", "R2", "R3"}

# Risk classes docs/map/05-governance.md section 6.1 states for an inventory item (user.reset-mfa is R2, so W-IDM-02).
# UNVERIFIED hand-kept mapping: the registry gets a machine-readable risk_class only in B-01 (RQ-01); replace it then.
GOVERNANCE_RISK = {"W-IDM-02": "R2"}

RX_INVENTORY = re.compile(r"^W-[A-Z0-9]+-\d{2}$")
RX_CONTROL = re.compile(r"^C-\d{2}$")
RX_ITEM = re.compile(r"^B-\d{2}$")
RX_WAVE = re.compile(r"^W\d{1,2}$")
RX_NOT_NOW = re.compile(r"^NN-\d{2}$")

# Citations inside free text. The lookbehinds stop "W-SEC-04" from also reading as "C-04".
CITE_INVENTORY = re.compile(r"(?<![A-Za-z0-9-])W-[A-Z0-9]+-\d{2}\b")
CITE_CONTROL = re.compile(r"(?<![A-Za-z0-9-])C-\d{2}\b")
CITE_ITEM = re.compile(r"(?<![A-Za-z0-9-])B-\d{2}\b")
CITE_STD = re.compile(r"(?<![A-Za-z0-9-])STD-[A-Z]{2}(?:-\d+[a-z]?)?\b")
CITE_ARCH = re.compile(r"(?<![A-Za-z0-9-])(?:ARC|TEN|SL|DR)-\d{2}\b")
CITE_STEP = re.compile(r"(?<![A-Za-z0-9-])W(\d{1,2})-([EX])(\d+)\b")
SAFEGUARD = re.compile(r"^(C-\d{2}) (.+) \((built|partial|planned)\)$")


@dataclass(frozen=True, slots=True)
class MapData:
    """The four machine-readable maps, as loaded from map/*.json."""

    inventory: list[JsonObj]
    impact: list[JsonObj]
    controls: list[JsonObj]
    roadmap: JsonObj

    def items(self) -> list[tuple[int, JsonObj]]:
        """Every roadmap item with the index (0-based) of the wave it belongs to."""
        return [(n, item) for n, wave in enumerate(self.roadmap["waves"]) for item in wave["items"]]


class MapLoadError(Exception):
    """A map file is missing or is not valid JSON."""


def load(root: Path = REPO_ROOT) -> MapData:
    """Load map/*.json under root. Raises MapLoadError naming the file."""
    loaded: dict[str, Any] = {}
    for name in MAP_FILES:
        path = root / "map" / f"{name}.json"
        try:
            loaded[name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MapLoadError(f"map/{name}.json: {exc}") from exc
    return MapData(loaded["inventory"], loaded["impact"], loaded["controls"], loaded["roadmap"])


def control_status(control: JsonObj) -> str:
    """built, partial or planned, read from the honest implemented_in field."""
    where = str(control.get("implemented_in", ""))
    if where.startswith("planned"):
        return "planned"
    if where.startswith("partial"):
        return "partial"
    return "built"


def automatable(item: JsonObj) -> bool:
    """True when the item has an automation pattern other than none-keep-human."""
    return any(p != "none-keep-human" for p in item.get("automation_pattern", []))


def _dupes(values: list[str]) -> list[str]:
    return sorted(v for v, n in Counter(values).items() if n > 1)


def check_ids(data: MapData) -> list[str]:
    """Ids are unique and match their patterns; enumerated fields use known values (B06-1)."""
    problems: list[str] = []
    groups: list[tuple[str, list[str], re.Pattern[str]]] = [
        ("inventory", [str(i.get("id")) for i in data.inventory], RX_INVENTORY),
        ("control", [str(c.get("id")) for c in data.controls], RX_CONTROL),
        ("roadmap item", [str(i.get("id")) for _, i in data.items()], RX_ITEM),
        ("wave", [str(w.get("id")) for w in data.roadmap.get("waves", [])], RX_WAVE),
        ("not-now", [str(n.get("id")) for n in data.roadmap.get("not_now", [])], RX_NOT_NOW),
    ]
    for kind, ids, rx in groups:
        problems += [f"duplicate {kind} id {d}" for d in _dupes(ids)]
        problems += [f"{kind} id {i!r} does not match {rx.pattern}" for i in ids if not rx.match(i)]
    waves = [str(w.get("id")) for w in data.roadmap.get("waves", [])]
    if waves != [f"W{n}" for n in range(1, len(waves) + 1)]:
        problems.append(f"waves are not numbered W1..W{len(waves)} in order: {waves}")
    for item in data.inventory:
        bad = sorted(set(item.get("automation_pattern", [])) - PATTERNS)
        if bad or not item.get("automation_pattern"):
            problems.append(f"{item.get('id')}: unknown or empty automation_pattern {bad}")
        if item.get("risk_class") not in RISK_CLASSES:
            problems.append(f"{item.get('id')}: risk_class {item.get('risk_class')!r} is not R0-R3")
    for control in data.controls:
        bad = sorted(set(control.get("applies_to_risk_classes", [])) - RISK_CLASSES)
        if bad:
            problems.append(f"{control.get('id')}: applies_to_risk_classes has unknown {bad}")
    return problems


def check_impact(data: MapData) -> list[str]:
    """Every automatable inventory item has exactly one chain; every chain points at a real item."""
    problems: list[str] = []
    inventory = {str(i["id"]): i for i in data.inventory}
    chains = [str(c.get("inventory_id")) for c in data.impact]
    problems += [f"impact: more than one chain for {d}" for d in _dupes(chains)]
    for cid in chains:
        if cid not in inventory:
            problems.append(f"impact: chain points to unknown inventory id {cid}")
        elif not automatable(inventory[cid]):
            problems.append(f"impact: chain {cid} exists but the item is none-keep-human only")
    have = set(chains)
    for iid, item in inventory.items():
        if automatable(item) and iid not in have:
            problems.append(f"impact: {iid} has an automation pattern but no impact chain")
    ranks = [c["leverage_rank"] for c in data.impact if c.get("leverage_rank") is not None]
    if sorted(ranks) != list(range(1, 11)):
        problems.append(f"impact: leverage_rank must use 1-10 once each, found {sorted(ranks)}")
    return problems


def check_controls(data: MapData, docs: dict[str, str] | None = None) -> list[str]:
    """Every control referenced anywhere exists; quoted safeguard lines match controls.json."""
    problems: list[str] = []
    controls = {str(c["id"]): c for c in data.controls}
    for chain in data.impact:
        for line in chain.get("safeguards", []):
            for cid in CITE_CONTROL.findall(line):
                if cid not in controls:
                    problems.append(f"impact {chain.get('inventory_id')}: safeguard cites undefined control {cid}")
            m = SAFEGUARD.match(line)
            if m and m.group(1) in controls:
                ctl = controls[m.group(1)]
                if m.group(2) != ctl.get("name") or m.group(3) != control_status(ctl):
                    problems.append(
                        f"impact {chain.get('inventory_id')}: safeguard {line!r} disagrees with controls.json "
                        f"({ctl.get('name')!r}, {control_status(ctl)})"
                    )
    for _, item in data.items():
        for cid in item.get("controls", []):
            if cid not in controls:
                problems.append(f"roadmap {item.get('id')}: control {cid} is not in map/controls.json")
    for name, text in (docs or {}).items():
        for cid in sorted(set(CITE_CONTROL.findall(text)) - set(controls)):
            problems.append(f"{name}: cites undefined control {cid}")
    return problems


def _standard_ids(standards_text: str) -> set[str]:
    ids = set(re.findall(r"\((STD-[A-Z]{2})\)", standards_text))
    ids |= set(re.findall(r"\*\*(STD-[A-Z]{2}-\d+[a-z]?)\b", standards_text))
    ids |= set(re.findall(r"\((STD-[A-Z]{2}-\d+[a-z])\)", standards_text))
    return ids


def _owns_overlap(a: str, b: str) -> bool:
    return a == b or (a.endswith("/") and b.startswith(a)) or (b.endswith("/") and a.startswith(b))


def check_roadmap(data: MapData, standards_text: str | None = None, root: Path = REPO_ROOT) -> list[str]:
    """Roadmap items reference real ids, cover the inventory, depend backwards, and never share a path in a wave."""
    problems: list[str] = []
    inventory = {str(i["id"]) for i in data.inventory}
    wave_of = {str(item["id"]): n for n, item in data.items()}
    std = _standard_ids(standards_text) if standards_text is not None else None
    covered: set[str] = set()
    for n, item in data.items():
        iid = str(item["id"])
        if not item.get("inventory_ids"):
            problems.append(f"roadmap {iid}: covers no inventory id")
        for inv in item.get("inventory_ids", []):
            covered.add(inv)
            if inv not in inventory:
                problems.append(f"roadmap {iid}: inventory id {inv} does not exist")
        if not item.get("controls"):
            problems.append(f"roadmap {iid}: names no control")
        for dep in item.get("depends_on", []):
            if dep not in wave_of:
                problems.append(f"roadmap {iid}: depends on unknown item {dep}")
            elif wave_of[dep] > n:
                problems.append(f"roadmap {iid} (W{n + 1}) depends on {dep} in a later wave (W{wave_of[dep] + 1})")
        if std is not None:
            for s in item.get("standards", []):
                if s not in std:
                    problems.append(f"roadmap {iid}: standard {s} is not a section of docs/STANDARDS.md")
        for field in ("specs/{}.md", "docs/changes/{}.md"):
            if field.format(iid) not in item.get("owns", []):
                problems.append(f"roadmap {iid}: does not own {field.format(iid)}")
    for entry in data.roadmap.get("not_now", []):
        for inv in entry.get("inventory_ids", []):
            covered.add(inv)
            if inv not in inventory:
                problems.append(f"not-now {entry.get('id')}: inventory id {inv} does not exist")
    problems += [
        f"inventory {i} is covered by no roadmap item and no not-now entry" for i in sorted(inventory - covered)
    ]
    problems += _cycles({str(i["id"]): list(i.get("depends_on", [])) for _, i in data.items()})
    return [*problems, *_wave_overlaps(data, root)[0]]


def _wave_overlaps(data: MapData, root: Path) -> tuple[list[str], list[str]]:
    """(problems, warnings): two items in a wave owning one path. An existing file is only a warning, because
    the build automation runs same-file orders one after another; a new path or a folder stays a problem."""
    problems: list[str] = []
    warnings: list[str] = []
    for wave in data.roadmap.get("waves", []):
        owners: list[tuple[str, str]] = [(p, str(i["id"])) for i in wave["items"] for p in i.get("owns", [])]
        seen: set[tuple[str, str, bool]] = set()
        for k, (path_a, owner_a) in enumerate(owners):
            for path_b, owner_b in owners[k + 1 :]:
                if owner_a == owner_b or not _owns_overlap(path_a, path_b):
                    continue
                shared = path_b if path_a.endswith("/") and path_b.startswith(path_a) else path_a
                is_file = (root / shared).is_file()
                key = (min(owner_a, owner_b), max(owner_a, owner_b), is_file)
                if key not in seen:
                    seen.add(key)
                    text = f"{wave['id']}: {owner_a} ({path_a}) and {owner_b} ({path_b}) own the same path"
                    if is_file:
                        warnings.append(
                            f"{text} (an existing file; the build automation runs these orders one after another)"
                        )
                    else:
                        problems.append(text)
    return problems, warnings


def roadmap_warnings(data: MapData, root: Path = REPO_ROOT) -> list[str]:
    """Same-wave items sharing an existing file (advisory)."""
    return _wave_overlaps(data, root)[1]


def _cycles(graph: dict[str, list[str]]) -> list[str]:
    state: dict[str, int] = {}
    found: list[str] = []

    def visit(node: str, trail: list[str]) -> None:
        state[node] = 1
        for nxt in graph.get(node, []):
            if nxt not in graph:
                continue
            if state.get(nxt) == 1:
                found.append("roadmap: dependency cycle " + " -> ".join([*trail[trail.index(nxt) :], nxt]))
            elif nxt not in state:
                visit(nxt, [*trail, nxt])
        state[node] = 2

    for node in graph:
        if node not in state:
            visit(node, [node])
    return found


def _generator() -> Any:
    """tools/gen_roadmap_md.py, loaded by path (map/ and tools/ are not packages)."""
    spec = importlib.util.spec_from_file_location("gen_roadmap_md", REPO_ROOT / "tools" / "gen_roadmap_md.py")
    if spec is None or spec.loader is None:
        raise MapLoadError("tools/gen_roadmap_md.py: cannot load")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_docs(root: Path = REPO_ROOT) -> dict[str, str]:
    """The map documents that exist under root, by repo-relative name."""
    return {name: (root / name).read_text(encoding="utf-8") for name in DOCS if (root / name).is_file()}


def _heading_ids(text: str, rx: str) -> list[str]:
    return re.findall(rx, text, flags=re.M)


def check_docs(data: MapData, docs: dict[str, str]) -> list[str]:
    """Markdown twins match the JSON, every cited id resolves, and every document starts with a status line."""
    problems: list[str] = []
    for name in DOCS:
        if name not in docs:
            problems.append(f"{name}: missing")
    inventory = {str(i["id"]) for i in data.inventory}
    items = {str(i["id"]): i for _, i in data.items()}
    twins = [
        ("docs/map/01-work-inventory.md", r"^\*\*`(W-[A-Z0-9]+-\d{2})` ", inventory),
        (
            "docs/map/02-impact-chains.md",
            r"^#### `(W-[A-Z0-9]+-\d{2})` ",
            {str(c["inventory_id"]) for c in data.impact},
        ),
        ("docs/ROADMAP.md", r"^\*\*`(B-\d{2})` ", set(items)),
    ]
    for name, rx, want in twins:
        if name not in docs:
            continue
        got = _heading_ids(docs[name], rx)
        problems += [f"{name}: {d} is described twice" for d in _dupes(got)]
        problems += [f"{name}: no section for {i} (it is in the JSON)" for i in sorted(want - set(got))]
        problems += [f"{name}: section {i} is not in the JSON" for i in sorted(set(got) - want)]
    if "docs/ROADMAP.md" in docs:
        gen = _generator()
        have = docs["docs/ROADMAP.md"]
        try:
            want = gen.splice(have, gen.render_waves(data.roadmap))
        except (ValueError, KeyError) as exc:
            problems.append(f"docs/ROADMAP.md: cannot generate the item blocks: {exc!r}")
        else:
            if want != have:
                wl, hl = want.split("\n"), have.split("\n")
                k = next((n for n, (a, b) in enumerate(zip(wl, hl, strict=False)) if a != b), min(len(wl), len(hl)))
                near = next((m[1] for ln in reversed(wl[: k + 1]) if (m := re.match(r"\*\*`(B-\d{2})` ", ln))), "?")
                problems.append(
                    f"docs/ROADMAP.md: item blocks differ from map/roadmap.json near {near} (line {k + 1}); "
                    f"fix with: {gen.FIX_COMMAND}"
                )
    std = _standard_ids(docs.get("docs/STANDARDS.md", ""))
    arch = set(re.findall(r"(?m)^\| ((?:ARC|TEN|SL|DR)-\d{2}) \|", docs.get("docs/map/03-architecture-target.md", "")))
    steps: dict[str, int] = {}
    for wave in data.roadmap.get("waves", []):
        steps[f"{wave['id']}-E"] = len(wave.get("entry_steps", []))
        steps[f"{wave['id']}-X"] = len(wave.get("exit_steps", []))
    for name, text in docs.items():
        for found, known, kind in (
            (CITE_INVENTORY.findall(text), inventory, "inventory id"),
            (CITE_ITEM.findall(text), set(items), "roadmap item"),
            (CITE_STD.findall(text), std, "standard"),
            (CITE_ARCH.findall(text), arch, "architecture id"),
        ):
            for ref in sorted(set(found) - known):
                problems.append(f"{name}: cites undefined {kind} {ref}")
        for wave_no, kind, k in sorted(set(CITE_STEP.findall(text))):
            if int(k) > steps.get(f"W{wave_no}-{kind}", 0):
                problems.append(f"{name}: cites wave step W{wave_no}-{kind}{k}, which does not exist")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        status = lines[1] if len(lines) > 1 else ""
        if not re.match(r"^Status: \*\*(" + "|".join(STATUS_WORDS) + r")\*\*", status):
            problems.append(f"{name}: second line must be 'Status: **<{'|'.join(STATUS_WORDS)}>**' (STD-DC-1)")
    return problems


def check_risk_classes(data: MapData) -> list[str]:
    """Warnings where an inventory risk_class differs from the governance class (B06-6, RQ-01)."""
    return [
        f"{item.get('id')}: inventory risk_class {item.get('risk_class')} but governance says {GOVERNANCE_RISK[iid]}"
        for item in data.inventory
        if (iid := str(item.get("id"))) in GOVERNANCE_RISK and item.get("risk_class") != GOVERNANCE_RISK[iid]
    ]


def run_warnings(root: Path = REPO_ROOT) -> list[str]:
    """Advisory findings that never fail the check (B06-6)."""
    data = load(root)
    return [*check_risk_classes(data), *roadmap_warnings(data, root)]


def run_all(root: Path = REPO_ROOT) -> list[str]:
    """Every check, in order. An empty list means the map is consistent."""
    data = load(root)
    docs = read_docs(root)
    return [
        *check_ids(data),
        *check_impact(data),
        *check_controls(data, docs),
        *check_roadmap(data, docs.get("docs/STANDARDS.md"), root),
        *check_docs(data, docs),
    ]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]).resolve() if args else REPO_ROOT
    try:
        problems = run_all(root)
    except MapLoadError as exc:
        print(f"map check: cannot load: {exc}")
        return 2
    for problem in problems:
        print(f"PROBLEM: {problem}")
    data = load(root)
    warnings = run_warnings(root)
    for warning in warnings:
        print(f"WARNING: {warning}")
    by_wave: defaultdict[int, int] = defaultdict(int)
    for n, _ in data.items():
        by_wave[n] += 1
    print(
        f"Map check: {len(data.inventory)} inventory items, {len(data.impact)} impact chains, "
        f"{len(data.controls)} controls, {len(data.items())} roadmap items in {len(by_wave)} waves; "
        f"{len(problems)} problem(s), {len(warnings)} warning(s)"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
