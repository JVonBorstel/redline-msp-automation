"""Coverage audit (B-98): what the repo really has versus what the map says it has.

Reads map/roadmap.json, map/inventory.json and map/controls.json, then looks at the actual repo: change notes
(docs/changes), specs, tests, the lever registry (levers/registry.json and levers/registry.d) and the workflow folders.
For every roadmap item, inventory item, control, lever and workflow folder it computes a status from files, never from
the map's own words, and lists every place where the map and the code disagree. Nothing is hidden or rounded up.

    uv run --frozen python tools/coverage_audit.py --headline   # one line, e.g. "Roadmap: 98 of 98 items built ..."
    uv run --frozen python tools/coverage_audit.py --write      # regenerate the report, the README block, the patch
    uv run --frozen python tools/coverage_audit.py --check      # exit 1 when any of those three is out of date
    uv run --frozen python tools/coverage_audit.py --json       # headline numbers and every finding as JSON

Status words (the same four everywhere; a fifth, "not planned", is for rows the map keeps out on purpose):
  built             the files exist, a change note and a spec exist, and a test points at it. For a roadmap item the
                    note's own word (built, mocked, document-only) is kept as its "kind".
  partial           something exists but a named file, spec, note or test is missing.
  planned           nothing exists yet.
  not demonstrated  the files exist but no test is tied to them, or the note says nothing was run.
A "built" here means "the evidence files are there"; it does not re-run the tests. The test suites do that.

Stdlib only, no network, reads files only (writes only with --write). Synthetic planning data; this checks
consistency between documents and files, not truth about any real system. Exit 0 = ok, 1 = stale or invalid, 2 = a
required map file is missing.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LABEL = "Independently built prototype. Not affiliated with any vendor's or real company's systems."
REPORT_REL = "docs/COVERAGE_AUDIT.md"
PATCH_REL = "docs/changes/B-98-map-status.patch"
README_REL = "README.md"
README_START = "<!-- audit:status:start -->"
README_END = "<!-- audit:status:end -->"
STATUSES = ("built", "partial", "planned", "not demonstrated")
# Top-level folders this repo is laid out around (docs/ARCHITECTURE.md). A path in a map sentence that starts with one
# of these must exist, even in a checkout where the folder itself is gone.
CONVENTIONAL_ROOTS = (
    "adapters", "config", "core", "docs", "evals", "fixtures", "governance", "infra", "levers", "map", "mcp",
    "prompts", "rag", "schemas", "scripts", "specs", "tests", "tools", "ui", "workflows", ".github",
)  # fmt: skip
SKIP_DIRS = {".git", ".venv", "__pycache__", ".tmp", "node_modules", ".mypy_cache", ".ruff_cache", ".pytest_cache"}

# kind -> (severity, one line meaning). Severity: error = the map claims more than the files show; stale = the map
# claims less than the files show; gap = a file the process requires is missing; info = worth knowing.
KINDS: dict[str, tuple[str, str]] = {
    "ITEM-NO-NOTE": ("gap", "roadmap item has no docs/changes/B-nn.md"),
    "ITEM-NO-SPEC": ("gap", "roadmap item has no specs/B-nn.md"),
    "ITEM-MISSING-OWNED": ("gap", "a path the item owns does not exist"),
    "ITEM-NO-TEST": ("gap", "no test file is tied to the item (owned, named bNN, or named in its first lines)"),
    "ITEM-NOTE-SAYS-BUILT": (
        "error",
        "the change note says built/mocked/document-only but the files say partial/planned",
    ),
    "ITEM-NOT-DEMONSTRATED": ("info", "files exist but the note says nothing was compiled, validated or run"),
    "ITEM-NO-STATUS-LINE": ("info", "the change note has no Status line"),
    "NOTE-NO-ITEM": ("gap", "a change note exists for an id that is not in the roadmap"),
    "INV-STALE-PLANNED": ("stale", "inventory row says planned/proposed but roadmap items covering it are built"),
    "INV-UNSUPPORTED": ("error", "inventory row says exists/partial but no covering roadmap item is built"),
    "INV-MISSING-PATH": ("error", "inventory row cites a path (as existing) that is not in the repo"),
    "INV-UNCOVERED": ("gap", "inventory row is covered by no roadmap item and no not_now entry"),
    "INV-BY-DESIGN-BUILT": ("info", "inventory row is kept out by design but a built roadmap item covers it"),
    "CTL-MISSING-PATH": ("error", "control cites an implementation path that is not in the repo"),
    "CTL-MISSING-TEST-FILE": ("error", "control cites a test file that is not in the repo"),
    "CTL-MISSING-TEST-NAME": ("error", "control cites a test function that is not in its file"),
    "CTL-NO-EVIDENCE": ("gap", "control claims to be implemented but cites no evidence"),
    "CTL-STALE-PLANNED": ("stale", "control says planned but its paths and cited tests exist"),
    "CTL-ITEM-BUILT-CONTROL-PLANNED": (
        "stale",
        "a built roadmap item cites the control but the control is still planned",
    ),
    "CTL-ORPHAN": ("info", "no roadmap item cites the control"),
    "LEVER-NO-TEST": ("gap", "no test file mentions the lever by name"),
    "LEVER-NO-OWNER": ("info", "the lever's registry fragment is owned by no roadmap item"),
    "WF-UNOWNED": ("gap", "workflow folder is owned by no roadmap item"),
    "WF-NO-SPEC": ("gap", "workflow folder has no spec (its owner's specs/B-nn.md is missing, or it has no owner)"),
    "WF-NO-TEST": ("gap", "no test imports or names the workflow folder"),
    "WF-NO-README": ("info", "workflow folder has no README.md (STD-DC-7)"),
    "COV-COUNT-MISMATCH": ("error", "docs/COVERAGE.md states counts that differ from its own table"),
    "COV-MISSING-PATH": ("error", "a docs/COVERAGE.md row marked built/mocked cites a path that is not in the repo"),
}
SEVERITY_ORDER = ("error", "stale", "gap", "info")


@dataclass(frozen=True)
class Finding:
    kind: str
    subject: str
    detail: str

    @property
    def severity(self) -> str:
        return KINDS[self.kind][0]


@dataclass(frozen=True)
class ItemRow:
    id: str
    title: str
    status: str
    kind: str  # the change note's own word: built, mocked, document-only, source-only, partial, unstated, none
    owner_only: bool
    problems: tuple[str, ...]


@dataclass(frozen=True)
class InvRow:
    id: str
    name: str
    map_class: str  # exists, partial, planned, by-design, unstated
    map_text: str
    status: str
    items: tuple[str, ...]


@dataclass(frozen=True)
class CtlRow:
    id: str
    name: str
    map_class: str  # claimed, partial, planned
    status: str
    problems: tuple[str, ...]


@dataclass(frozen=True)
class LeverRow:
    id: str
    status: str
    source: str
    test_files: int


@dataclass(frozen=True)
class WfRow:
    id: str
    status: str
    owner: str
    spec: bool
    test_files: int


@dataclass
class Audit:
    root: Path
    items: list[ItemRow] = field(default_factory=list)
    inventory: list[InvRow] = field(default_factory=list)
    controls: list[CtlRow] = field(default_factory=list)
    levers: list[LeverRow] = field(default_factory=list)
    workflows: list[WfRow] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    stale_inventory: dict[str, tuple[str, ...]] = field(default_factory=dict)  # inventory id -> built item ids

    def add(self, kind: str, subject: str, detail: str) -> None:
        self.findings.append(Finding(kind, subject, detail))

    def headline(self) -> dict[str, int]:
        def count(rows: list[Any], status: str) -> int:
            return sum(1 for r in rows if r.status == status)

        head: dict[str, int] = {}
        for name, rows in (("items", self.items), ("inventory", self.inventory), ("controls", self.controls)):
            head[f"{name}_total"] = len(rows)
            for status in STATUSES:
                head[f"{name}_{status.replace(' ', '_')}"] = count(rows, status)
        head["items_note_claims_built"] = sum(1 for r in self.items if r.kind in ("built", "mocked", "document-only"))
        head["inventory_not_planned"] = count(self.inventory, "not planned")
        head["levers_total"] = len(self.levers)
        head["levers_without_test"] = sum(1 for r in self.levers if r.test_files == 0)
        head["workflows_total"] = len(self.workflows)
        head["workflows_without_spec"] = sum(1 for r in self.workflows if not r.spec)
        head["findings_total"] = len(self.findings)
        for severity in SEVERITY_ORDER:
            head[f"findings_{severity}"] = sum(1 for f in self.findings if f.severity == severity)
        return head


# -- reading the repo ----------------------------------------------------------------------------------------------


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _read_exact(path: Path) -> str:
    """Text with CRLF turned into LF, so a Windows checkout (autocrlf) compares equal to the generated file."""
    try:
        return path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError):
        return ""


def _load_json(root: Path, rel: str) -> Any:
    path = root / rel
    if not path.is_file():
        raise FileNotFoundError(rel)
    return json.loads(path.read_text(encoding="utf-8"))


def _walk(root: Path) -> list[str]:
    found: list[str] = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        base = Path(folder).relative_to(root)
        found += [(base / f).as_posix() for f in sorted(files)]
    return found


_TEST_FILE = re.compile(r"(^|/)(test_[^/]*\.py|Test-[^/]*\.ps1|[^/]*\.Tests\.ps1)$")


def _is_test_file(rel: str) -> bool:
    return bool(_TEST_FILE.search(rel))


def _is_test_path(rel: str) -> bool:
    return rel.startswith("tests/") or "/tests/" in rel or _is_test_file(rel)


class TestIndex:
    """Every test file in the repo with its text, read once."""

    __test__ = False  # not a pytest class

    def __init__(self, root: Path, files: list[str]) -> None:
        self.texts: dict[str, str] = {f: _read(root / f) for f in files if _is_test_file(f)}

    def mentioning(self, pattern: re.Pattern[str]) -> list[str]:
        return sorted(f for f, text in self.texts.items() if pattern.search(text))

    def tied_to(self, item_id: str) -> list[str]:
        """Test files named for the item (bNN in the file name) or naming it in the first 400 characters."""
        number = item_id.split("-", 1)[1]
        by_name = re.compile(rf"(?<![0-9])b{number}(?![0-9])", re.I)
        in_head = re.compile(rf"\bB-{number}\b|\bB{number}-\d")
        return sorted(
            f for f, text in self.texts.items() if by_name.search(f.rsplit("/", 1)[-1]) or in_head.search(text[:400])
        )


# -- text parsing --------------------------------------------------------------------------------------------------

_PATH = re.compile(r"(?<![\w/.:-])((?:\.?[\w-]+/)+[\w.-]*)")
_TEST_REF = re.compile(r"((?:\.?[\w-]+/)+[\w.-]+\.(?:py|ps1))((?:\s*,?\s*::\w+)*)")


def _paths_in(text: str, top: set[str]) -> list[str]:
    """Repo-looking paths in free text: they contain a slash and start at a top-level name of this repo."""
    out: list[str] = []
    for match in _PATH.finditer(text):
        path = match.group(1).rstrip(".,;:)")
        if path.split("/", 1)[0] not in top or any(c in path for c in "*<>{}"):
            continue
        if path not in out:
            out.append(path)
    return out


def _exists(root: Path, rel: str) -> bool:
    return (root / rel.rstrip("/")).exists()


def _note_status(note: Path) -> tuple[str, str]:
    """(kind, raw words) from the change note's Status line within its first lines."""
    for line in _read(note).splitlines()[:12]:
        match = re.match(r"\s*Status:\s*(.*)", line, re.I)
        if not match:
            continue
        words = match.group(1).lower()
        if "source and static checks only" in words or "nothing compiled" in words:
            return "source-only", words
        if words.startswith("**partial") or words.startswith("partial"):
            return "partial", words
        if "mocked" in words[:30]:
            return "mocked", words
        if "document-only" in words[:30]:
            return "document-only", words
        if "built" in words[:30]:
            return "built", words
        return "unstated", words
    return "none", ""


# -- the checks ----------------------------------------------------------------------------------------------------


def _audit_items(audit: Audit, roadmap: dict[str, Any], files: set[str], tests: TestIndex) -> dict[str, ItemRow]:
    root = audit.root
    rows: dict[str, ItemRow] = {}
    for wave in roadmap["waves"]:
        for item in wave["items"]:
            item_id = item["id"]
            note, spec = root / "docs" / "changes" / f"{item_id}.md", root / "specs" / f"{item_id}.md"
            kind, _ = _note_status(note) if note.is_file() else ("none", "")
            note_rel, spec_rel = f"docs/changes/{item_id}.md", f"specs/{item_id}.md"
            others = [o for o in item["owns"] if o not in (note_rel, spec_rel)]
            missing = [o for o in others if not _exists(root, o)]
            tied = set(tests.tied_to(item_id))
            tied |= {o for o in others if _is_test_path(o) and _exists(root, o)}
            problems: list[str] = []
            if not note.is_file():
                audit.add("ITEM-NO-NOTE", item_id, f"no {note_rel}")
                problems.append("no change note")
            if not spec.is_file():
                audit.add("ITEM-NO-SPEC", item_id, f"no {spec_rel}")
                problems.append("no spec")
            if missing:
                audit.add("ITEM-MISSING-OWNED", item_id, "missing: " + ", ".join(f"`{m}`" for m in missing))
                problems.append(f"{len(missing)} owned path(s) missing")
            if note.is_file() and not tied:
                audit.add("ITEM-NO-TEST", item_id, "no test file tied to this item")
                problems.append("no test")
            if note.is_file() and kind == "none":
                audit.add("ITEM-NO-STATUS-LINE", item_id, f"{note_rel} has no Status line")
            nothing_owned = len(missing) == len(others)
            if not note.is_file() and not spec.is_file() and nothing_owned:
                status = "planned"
            elif problems and (not note.is_file() or not spec.is_file() or missing):
                status = "partial"
            elif kind == "partial":
                status = "partial"
            elif kind == "source-only" or not tied:
                status = "not demonstrated"
                if kind == "source-only":
                    audit.add("ITEM-NOT-DEMONSTRATED", item_id, "the change note says nothing was compiled or run")
            else:
                status = "built"
            if kind in ("built", "mocked", "document-only") and status in ("partial", "planned"):
                audit.add(
                    "ITEM-NOTE-SAYS-BUILT", item_id, f"note says {kind}; files say {status} ({'; '.join(problems)})"
                )
            rows[item_id] = ItemRow(item_id, item["title"], status, kind, bool(item.get("owner_only")), tuple(problems))
            audit.items.append(rows[item_id])
    for rel in sorted(f for f in files if re.fullmatch(r"docs/changes/B-\d+\.md", f)):
        note_id = rel.rsplit("/", 1)[1][:-3]
        if note_id not in rows:
            audit.add("NOTE-NO-ITEM", note_id, f"`{rel}` has no item in map/roadmap.json")
    return rows


def _map_class(text: str) -> str:
    low = text.strip().lower()
    if low.startswith("not planned"):
        return "by-design"
    if low.startswith(("exists", "built", "mocked")):
        return "exists"
    if low.startswith("partial"):
        return "partial"
    if low.startswith(("planned", "proposed", "not in blueprint")):
        return "planned"
    return "unstated"


def _claimed_part(text: str) -> str:
    """The part of a map status that says what exists now (before 'planned', 'missing' or the next clause)."""
    body = re.sub(r"^\s*(exists|partial|built|mocked)\s*(\([^)]*\))?\s*:?", "", text, flags=re.I)
    return re.split(r";|\bplanned\b|\bproposed\b|\bmissing\b|\bnot yet\b", body, maxsplit=1, flags=re.I)[0]


def _derive(statuses: list[str]) -> str:
    if statuses and all(s == "built" for s in statuses):
        return "built"
    if any(s in ("built", "partial") for s in statuses):
        return "partial"
    if any(s == "not demonstrated" for s in statuses):
        return "not demonstrated"
    return "planned"


def _audit_inventory(audit: Audit, roadmap: dict[str, Any], items: dict[str, ItemRow], top: set[str]) -> None:
    covering: dict[str, list[str]] = {}
    for wave in roadmap["waves"]:
        for item in wave["items"]:
            for inv_id in item["inventory_ids"]:
                covering.setdefault(inv_id, []).append(item["id"])
    not_now = {i for entry in roadmap.get("not_now", []) for i in entry.get("inventory_ids", [])}
    for entry in _load_json(audit.root, "map/inventory.json"):
        inv_id, text = entry["id"], str(entry.get("repo_status", ""))
        klass = _map_class(text)
        ids = tuple(covering.get(inv_id, []))
        if not ids and inv_id in not_now:
            status = "not planned"
        elif not ids:
            status = "planned"
            audit.add("INV-UNCOVERED", inv_id, "no roadmap item and no not_now entry covers it")
        else:
            status = _derive([items[i].status for i in ids])
        if klass == "planned" and status in ("built", "partial"):
            built = tuple(i for i in ids if items[i].status == "built")
            audit.add("INV-STALE-PLANNED", inv_id, f"map: {text[:90]!r}; evidence: {status} via {', '.join(ids)}")
            if status == "built":
                audit.stale_inventory[inv_id] = built
        if klass in ("exists", "partial") and status in ("planned", "not demonstrated"):
            audit.add(
                "INV-UNSUPPORTED", inv_id, f"map says {klass}; covering items {', '.join(ids) or 'none'} are {status}"
            )
        if klass in ("exists", "partial"):
            for path in _paths_in(_claimed_part(text), top):
                if not _exists(audit.root, path):
                    audit.add("INV-MISSING-PATH", inv_id, f"cites `{path}`, which is not in the repo")
        if klass == "by-design" and status == "built":
            audit.add("INV-BY-DESIGN-BUILT", inv_id, f"kept out by design; built items {', '.join(ids)} cover it")
        audit.inventory.append(InvRow(inv_id, str(entry.get("name", "")), klass, text, status, ids))


def _audit_controls(audit: Audit, roadmap: dict[str, Any], items: dict[str, ItemRow], top: set[str]) -> None:
    root = audit.root
    cited_by: dict[str, list[str]] = {}
    for wave in roadmap["waves"]:
        for item in wave["items"]:
            for control_id in item["controls"]:
                cited_by.setdefault(control_id, []).append(item["id"])
    for entry in _load_json(root, "map/controls.json"):
        cid = entry["id"]
        impl, evidence = str(entry.get("implemented_in", "")), str(entry.get("evidence", ""))
        low = impl.strip().lower()
        stated = "planned" if low.startswith("planned") else "partial" if low.startswith("partial") else "claimed"
        impl_paths = _paths_in(impl, top)
        impl_ok = [p for p in impl_paths if _exists(root, p)]
        impl_missing = [p for p in impl_paths if not _exists(root, p)]
        refs = [(m.group(1), re.findall(r"::(\w+)", m.group(2))) for m in _TEST_REF.finditer(evidence)]
        ev_paths = _paths_in(evidence, top)
        test_ok = [p for p, _ in refs if _exists(root, p)] + [
            p for p in ev_paths if _is_test_path(p) and _exists(root, p)
        ]
        problems: list[str] = []
        if stated != "planned":
            for path in impl_missing:
                audit.add("CTL-MISSING-PATH", cid, f"implemented_in cites `{path}`, which is not in the repo")
                problems.append(f"missing {path}")
            for path, names in refs:
                if not _exists(root, path):
                    audit.add("CTL-MISSING-TEST-FILE", cid, f"evidence cites `{path}`, which is not in the repo")
                    problems.append(f"missing test file {path}")
                    continue
                text = _read(root / path)
                for name in names:
                    if path.endswith(".py") and not re.search(rf"def {re.escape(name)}\b", text):
                        audit.add("CTL-MISSING-TEST-NAME", cid, f"evidence cites `{path}::{name}`; no such function")
                        problems.append(f"missing test {name}")
            if not ev_paths and not refs:
                audit.add("CTL-NO-EVIDENCE", cid, "claims to be implemented but cites no evidence")
                problems.append("no evidence")
        citing = cited_by.get(cid, [])
        built_citing = [i for i in citing if items[i].status == "built"]
        if stated == "planned":
            status = "built" if impl_ok and test_ok else "not demonstrated" if built_citing else "planned"
            if status == "built":
                audit.add("CTL-STALE-PLANNED", cid, f"map says planned; `{impl_ok[0]}` and `{test_ok[0]}` exist")
        elif problems and (impl_ok or test_ok):
            status = "partial"
        elif problems:
            status = "planned"
        elif impl_ok and test_ok:
            status = "built"
        elif impl_ok:
            status = "not demonstrated"
        else:
            status = "planned"
        if stated == "planned" and status != "built" and built_citing:
            audit.add("CTL-ITEM-BUILT-CONTROL-PLANNED", cid, "cited by built " + ", ".join(built_citing[:6]))
        if not citing:
            audit.add("CTL-ORPHAN", cid, "no roadmap item lists this control")
        audit.controls.append(CtlRow(cid, str(entry.get("name", "")), stated, status, tuple(problems)))


def _lever_names(root: Path) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    sources = ["levers/registry.json"]
    folder = root / "levers" / "registry.d"
    if folder.is_dir():
        sources += [f"levers/registry.d/{p.name}" for p in sorted(folder.glob("*.json"))]
    for rel in sources:
        path = root / rel
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for lever in data.get("levers", []) if isinstance(data, dict) else []:
            if isinstance(lever, dict) and isinstance(lever.get("name"), str):
                found.append((lever["name"], rel))
    return found


def _audit_levers(audit: Audit, roadmap: dict[str, Any], tests: TestIndex) -> None:
    owned = {o for w in roadmap["waves"] for i in w["items"] for o in i["owns"]}
    seen: set[str] = set()
    for name, source in _lever_names(audit.root):
        if name in seen:
            continue
        seen.add(name)
        pattern = re.compile(rf"(?<![\w.-]){re.escape(name)}(?![\w-])")
        hits = tests.mentioning(pattern)
        if not hits:
            audit.add("LEVER-NO-TEST", name, f"no test file mentions it ({source})")
        if source != "levers/registry.json" and source not in owned:
            audit.add("LEVER-NO-OWNER", name, f"`{source}` is owned by no roadmap item")
        audit.levers.append(LeverRow(name, "built" if hits else "not demonstrated", source, len(hits)))


def _audit_workflows(audit: Audit, roadmap: dict[str, Any], tests: TestIndex) -> None:
    root = audit.root
    folder = root / "workflows"
    if not folder.is_dir():
        return
    for path in sorted(p for p in folder.iterdir() if p.is_dir() and p.name not in SKIP_DIRS):
        name = path.name
        rel = f"workflows/{name}"
        owner = next(
            (
                i["id"]
                for w in roadmap["waves"]
                for i in w["items"]
                if any(o.rstrip("/") == rel or o.startswith(rel + "/") for o in i["owns"])
            ),
            "",
        )
        has_spec = bool(owner) and (root / "specs" / f"{owner}.md").is_file()
        hits = tests.mentioning(re.compile(rf"workflows[./]{re.escape(name)}\b"))
        if not owner:
            audit.add("WF-UNOWNED", rel, "no roadmap item owns this folder")
        if not has_spec:
            audit.add("WF-NO-SPEC", rel, f"owner {owner or 'none'}: no specs/{owner or 'B-nn'}.md")
        if not hits:
            audit.add("WF-NO-TEST", rel, "no test file imports or names it")
        if not (path / "README.md").is_file():
            audit.add("WF-NO-README", rel, "no README.md in the folder")
        status = "built" if owner and has_spec and hits else "partial"
        audit.workflows.append(WfRow(rel, status, owner, has_spec, len(hits)))


def _audit_coverage_md(audit: Audit, top: set[str]) -> None:
    text = _read(audit.root / "docs" / "COVERAGE.md")
    rows = re.findall(
        r"^\|\s*([A-Z]+\d+)\s*\|(.*)\|\s*(built|mocked|planned|document-only|not-planned)\s*\|\s*$", text, re.M
    )
    if not rows:
        return
    counts = {s: sum(1 for r in rows if r[2] == s) for s in ("built", "mocked", "planned")}
    stated = re.search(r"(\d+) rows; (\d+) built, (\d+) mocked, (\d+) planned", text)
    if stated and tuple(int(g) for g in stated.groups()) != (
        len(rows),
        counts["built"],
        counts["mocked"],
        counts["planned"],
    ):
        audit.add(
            "COV-COUNT-MISMATCH",
            "docs/COVERAGE.md",
            f"says {stated.group(0)!r}; its table has {len(rows)} rows: {counts['built']} built, "
            f"{counts['mocked']} mocked, {counts['planned']} planned",
        )
    for row_id, body, status in rows:
        if status not in ("built", "mocked"):
            continue
        for path in _paths_in(body, top):
            if not _exists(audit.root, path):
                audit.add("COV-MISSING-PATH", row_id, f"row marked {status} cites `{path}`, which is not in the repo")


def run_audit(root: Path) -> Audit:
    """Audit the repo at `root`. Raises FileNotFoundError when a map file is missing."""
    audit = Audit(root=root)
    roadmap = _load_json(root, "map/roadmap.json")
    files = _walk(root)
    top = (
        set(CONVENTIONAL_ROOTS)
        | {p.split("/", 1)[0] for p in files}
        | {p.name for p in root.iterdir() if p.is_dir() and p.name not in SKIP_DIRS}
    )
    tests = TestIndex(root, files)
    items = _audit_items(audit, roadmap, set(files), tests)
    _audit_inventory(audit, roadmap, items, top)
    _audit_controls(audit, roadmap, items, top)
    _audit_levers(audit, roadmap, tests)
    _audit_workflows(audit, roadmap, tests)
    _audit_coverage_md(audit, top)
    return audit


# -- the patch for the owner ---------------------------------------------------------------------------------------


def propose_patch(root: Path, audit: Audit) -> str:
    """A unified diff of map/inventory.json for the clear cases only: map says planned, every covering item is built."""
    path = root / "map" / "inventory.json"
    old = _read_exact(path)
    text = old
    by_id = {r.id: r for r in audit.items}
    for inv_id, built in sorted(audit.stale_inventory.items()):
        anchor = text.find(f'"id": "{inv_id}"')
        key = text.find('"repo_status": ', anchor) if anchor >= 0 else -1
        if key < 0:
            continue
        start = key + len('"repo_status": ')
        previous, end = json.JSONDecoder().raw_decode(text, start)
        kinds = {by_id[i].kind for i in built}
        label = (
            "exists (mocked)"
            if kinds & {"mocked"}
            else "exists (document-only)"
            if kinds == {"document-only"}
            else "exists"
        )
        new = f"{label}: built by {', '.join(built)} (evidence in docs/COVERAGE_AUDIT.md); the map said: {previous}"
        ascii_style = text[start:end] == json.dumps(previous, ensure_ascii=True)
        text = text[:start] + json.dumps(new, ensure_ascii=ascii_style) + text[end:]
    if text == old:
        return ""
    diff = difflib.unified_diff(
        old.splitlines(keepends=True), text.splitlines(keepends=True), "a/map/inventory.json", "b/map/inventory.json"
    )
    return "".join(diff)


# -- rendering -----------------------------------------------------------------------------------------------------


def headline_line(audit: Audit) -> str:
    h = audit.headline()
    return (
        f"Roadmap: {h['items_built']} of {h['items_total']} items built, {h['items_partial']} partial, "
        f"{h['items_not_demonstrated']} not demonstrated, {h['items_planned']} planned "
        f"({h['items_note_claims_built']} change notes say built, mocked or document-only). "
        f"Inventory: {h['inventory_built']} of {h['inventory_total']} built, {h['inventory_partial']} partial, "
        f"{h['inventory_planned']} planned, {h['inventory_not_demonstrated']} not demonstrated, "
        f"{h['inventory_not_planned']} not planned by design. "
        f"Controls: {h['controls_built']} of {h['controls_total']} built, {h['controls_partial']} partial, "
        f"{h['controls_planned']} planned, {h['controls_not_demonstrated']} not demonstrated. "
        f"Map-versus-code disagreements: {h['findings_total']} "
        f"({h['findings_error']} error, {h['findings_stale']} stale, {h['findings_gap']} gap, "
        f"{h['findings_info']} info)."
    )


def readme_block(audit: Audit) -> str:
    return (
        f"{headline_line(audit)}\n\n"
        "Computed by `tools/coverage_audit.py` from the map and the files in this checkout (fixture-based; "
        '"built" means the files, a spec, a change note and a tied test exist, not that the tests were re-run). '
        "The full per-item report with every disagreement is `docs/COVERAGE_AUDIT.md`.\n"
    )


def _cell(text: str, limit: int = 110) -> str:
    one = " ".join(text.split()).replace("|", "/")
    return one if len(one) <= limit else one[: limit - 3] + "..."


def render_report(audit: Audit) -> str:
    h = audit.headline()
    out: list[str] = [
        "# Coverage audit",
        "",
        "Status: **generated** by `tools/coverage_audit.py` (B-98). Do not edit by hand: rerun "
        "`uv run --frozen python tools/coverage_audit.py --write`; a test fails when this file is out of date.",
        "",
        f"> {LABEL} Synthetic data only.",
        "",
        "## What this is",
        "The map (`map/inventory.json`, `map/controls.json`, `map/roadmap.json`) says what is planned, partial or "
        "built. This report recomputes each status from the files that exist in this checkout and lists every place "
        'the two disagree. It is fixture-based and static: it reads files and never re-runs a test, so "built" means '
        "the evidence files are present, not that the suites passed today (the test suites say that).",
        "",
        "## Headline",
        headline_line(audit),
        "",
        "| Level | Total | Built | Partial | Not demonstrated | Planned | Not planned (by design) |",
        "|---|---|---|---|---|---|---|",
    ]
    for label, key in (("Roadmap items", "items"), ("Inventory rows", "inventory"), ("Controls", "controls")):
        by_design = h["inventory_not_planned"] if key == "inventory" else 0
        out.append(
            f"| {label} | {h[key + '_total']} | {h[key + '_built']} | {h[key + '_partial']} | "
            f"{h[key + '_not_demonstrated']} | {h[key + '_planned']} | {by_design} |"
        )
    out += [
        "",
        f"Levers: {h['levers_total']}, of which {h['levers_without_test']} have no test naming them. "
        f"Workflow folders: {h['workflows_total']}, of which {h['workflows_without_spec']} have no spec.",
        "",
        "## How a status is decided",
        "- **Roadmap item**: built when `docs/changes/B-nn.md` and `specs/B-nn.md` exist, every other path it owns "
        "exists, and a test file is tied to it (owned, named `bNN`, or naming `B-nn` in its first 400 characters). "
        "Partial when a note, spec or owned path is missing. Planned when none exist. Not demonstrated when the "
        "files exist but no test is tied to them or the note says nothing was compiled or run. The note's own word "
        "(built, mocked, document-only) is shown as its kind.",
        "- **Inventory row**: derived from the roadmap items that list it: built when all are built, partial when some "
        "are built or partial, planned when none are. This is an upper bound: an item may cover only part of a row.",
        "- **Control**: from `implemented_in` and `evidence`. Built when the cited paths exist and a cited test file "
        "exists with every named test function in it. Partial when something cited is missing. Not demonstrated when "
        "paths exist but no test is cited. Planned when the map says planned and nothing proves otherwise.",
        "- **Lever**: built when a test file names the lever. **Workflow folder**: built when a roadmap item owns it, "
        "that item has a spec, and a test imports it.",
        "",
        "## Disagreements and gaps",
        "Severity: **error** = the map claims more than the files show; **stale** = the map claims less than the "
        "files show; **gap** = a file the process requires is missing; **info** = worth knowing.",
        "",
        "| Kind | Severity | Count | Meaning |",
        "|---|---|---|---|",
    ]
    for kind, (severity, meaning) in sorted(KINDS.items(), key=lambda kv: (SEVERITY_ORDER.index(kv[1][0]), kv[0])):
        count = sum(1 for f in audit.findings if f.kind == kind)
        out.append(f"| {kind} | {severity} | {count} | {meaning} |")
    for kind, (severity, meaning) in sorted(KINDS.items(), key=lambda kv: (SEVERITY_ORDER.index(kv[1][0]), kv[0])):
        group = [f for f in audit.findings if f.kind == kind]
        if not group:
            continue
        out += ["", f"### {kind} ({severity}, {len(group)})", meaning + ".", ""]
        out += [f"- {f.subject}: {_cell(f.detail, 220)}" for f in group]
    out += ["", "## Roadmap items", "", "| Id | Title | Status | Kind | Problems |", "|---|---|---|---|---|"]
    for r in audit.items:
        kind = r.kind + (" (owner)" if r.owner_only else "")
        out.append(f"| {r.id} | {_cell(r.title, 70)} | {r.status} | {kind} | {_cell('; '.join(r.problems))} |")
    out += ["", "## Controls", "", "| Id | Name | Map says | Evidence says | Problems |", "|---|---|---|---|---|"]
    for c in audit.controls:
        out.append(f"| {c.id} | {_cell(c.name, 60)} | {c.map_class} | {c.status} | {_cell('; '.join(c.problems))} |")
    out += [
        "",
        "## Inventory",
        "",
        "| Id | Name | Map says | Evidence says | Covering items |",
        "|---|---|---|---|---|",
    ]
    for v in audit.inventory:
        out.append(
            f"| {v.id} | {_cell(v.name, 55)} | {v.map_class} | {v.status} | {_cell(', '.join(v.items) or 'none', 60)} |"
        )
    out += ["", "## Workflow folders", "", "| Folder | Status | Owner | Spec | Test files |", "|---|---|---|---|---|"]
    for w in audit.workflows:
        out.append(f"| {w.id} | {w.status} | {w.owner or 'none'} | {'yes' if w.spec else 'no'} | {w.test_files} |")
    out += ["", "## Levers", "", "| Lever | Status | Registry file | Test files naming it |", "|---|---|---|---|"]
    for lever in audit.levers:
        out.append(f"| {lever.id} | {lever.status} | {lever.source} | {lever.test_files} |")
    out += [
        "",
        "## Proposed fix for the owner",
        f"`{PATCH_REL}` is a patch for `map/inventory.json` that rewrites only the rows where the map says planned and "
        "every covering roadmap item is built. Review it, then `git apply` it from the repo root. The audit does not "
        "edit `map/` itself. Rows covered by a mix of built and unbuilt items are listed above but not patched.",
        "",
    ]
    return "\n".join(out)


# -- command line --------------------------------------------------------------------------------------------------


def _splice_readme(text: str, block: str) -> str | None:
    if text.count(README_START) != 1 or text.count(README_END) != 1:
        return None
    head, rest = text.split(README_START, 1)
    tail = rest.split(README_END, 1)[1]
    return f"{head}{README_START}\n{block}{README_END}{tail}"


def _outputs(root: Path, audit: Audit) -> dict[str, str]:
    outputs = {REPORT_REL: render_report(audit), PATCH_REL: propose_patch(root, audit)}
    readme = root / README_REL
    if readme.is_file():
        spliced = _splice_readme(_read(readme), readme_block(audit))
        if spliced is not None:
            outputs[README_REL] = spliced
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tools/coverage_audit.py", description=__doc__.split("\n\n")[0] if __doc__ else ""
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repo root to audit (default: this repo)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="write the report, the README status block and the patch")
    mode.add_argument("--check", action="store_true", help="exit 1 when any generated file is out of date")
    mode.add_argument("--headline", action="store_true", help="print the one-line headline")
    mode.add_argument("--json", action="store_true", help="print headline numbers and findings as JSON")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        audit = run_audit(root)
    except FileNotFoundError as exc:
        print(f"error: missing map file {exc}", file=sys.stderr)
        return 2
    if args.json:
        payload = {
            "headline": audit.headline(),
            "findings": [f.__dict__ | {"severity": f.severity} for f in audit.findings],
        }
        print(json.dumps(payload, indent=2))
        return 0
    if args.write or args.check:
        outputs = _outputs(root, audit)
        stale = [rel for rel, text in outputs.items() if _read_exact(root / rel) != text]
        if args.check:
            for rel in stale:
                print(f"stale: {rel} is out of date; run: uv run --frozen python tools/coverage_audit.py --write")
            if not stale:
                print("coverage audit outputs are current")
            return 1 if stale else 0
        for rel in stale:
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(outputs[rel].encode("utf-8"))
            print(f"wrote {rel}")
        print(headline_line(audit))
        return 0
    print(headline_line(audit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
