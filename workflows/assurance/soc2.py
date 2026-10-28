"""SOC 2 control mapping (B-95, B95-3): this system's controls as claims against SOC 2 criteria, with what backs each.

Three inputs, so the page cannot drift: ``map/controls.json`` (the controls, their objectives, status and the SOC 2
criterion ids in ``framework_refs``), ``governance/soc2_mapping.json`` (for each control: the tests and files that back
it, and what is not demonstrated), and the repo itself. ``check_mapping`` fails when a mapped control cites a test or a
file that does not exist. The page claims nothing beyond what those tests show on fixtures: it is not a
certification and not an attestation, and no auditor has seen it.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from core.paths import REPO_ROOT

MAPPING_PATH = "governance/soc2_mapping.json"
CONTROLS_PATH = "map/controls.json"
HEADER = (
    "# SOC 2 control mapping",
    "",
    "Status: **document-only** (generated claims with backing; the tests it cites are built, the mapping is not an "
    "audit)",
    "",
    "> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only.",
    "",
)


def load_controls(root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    data = json.loads((root / CONTROLS_PATH).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{CONTROLS_PATH} must be a list")
    return data


def load_mapping(root: Path = REPO_ROOT) -> dict[str, Any]:
    data = json.loads((root / MAPPING_PATH).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("controls"), dict):
        raise ValueError(f"{MAPPING_PATH} must be an object with version 1 and a controls object")
    return data


def control_status(control: dict[str, Any]) -> str:
    """built, partial or planned, read from the honest implemented_in field (same rule as map/check_map.py)."""
    where = str(control.get("implemented_in", ""))
    if where.startswith("planned"):
        return "planned"
    if where.startswith("partial"):
        return "partial"
    return "built"


def soc2_criteria(control: dict[str, Any]) -> list[str]:
    return [ref.split(":", 1)[1] for ref in control.get("framework_refs", []) if ref.startswith("SOC2:")]


def _inside(root: Path, rel: str) -> Path | None:
    if not rel or Path(rel).is_absolute():
        return None
    target = (root / rel).resolve()
    return target if target.is_relative_to(root.resolve()) else None


def _defines(source: str, name: str) -> bool:
    return re.search(rf"^[ \t]*(?:async[ \t]+)?def[ \t]+{re.escape(name)}[ \t]*\(", source, flags=re.M) is not None


def check_mapping(mapping: dict[str, Any], controls: list[dict[str, Any]], root: Path = REPO_ROOT) -> list[str]:
    """Problems found, one per line; empty when every cited test and file exists and every control is explained."""
    problems: list[str] = []
    entries: dict[str, Any] = mapping.get("controls", {})
    known = {c["id"]: c for c in controls}
    for cid in sorted(known):
        if cid not in entries:
            problems.append(f"{cid}: no mapping entry")
    for cid in sorted(entries):
        if cid not in known:
            problems.append(f"{cid}: mapped but not a control in {CONTROLS_PATH}")
            continue
        entry = entries[cid]
        tests, files, notes = entry.get("tests", []), entry.get("files", []), entry.get("not_demonstrated", [])
        if not all(isinstance(x, str) for x in (*tests, *files, *notes)):
            problems.append(f"{cid}: tests, files and not_demonstrated must be lists of strings")
            continue
        for ref in tests:
            path, _, name = ref.partition("::")
            target = _inside(root, path)
            if target is None:
                problems.append(f"{cid}: test path {path!r} is outside the repo")
            elif not target.is_file():
                problems.append(f"{cid}: test file {path} does not exist")
            elif name:
                if not path.endswith(".py"):
                    problems.append(f"{cid}: {ref} names a test inside a file that is not Python")
                elif not _defines(target.read_text(encoding="utf-8"), name):
                    problems.append(f"{cid}: test {name} is not defined in {path}")
        for rel in files:
            target = _inside(root, rel)
            if target is None:
                problems.append(f"{cid}: path {rel!r} is outside the repo")
            elif not target.exists():
                problems.append(f"{cid}: file {rel} does not exist")
        if control_status(known[cid]) != "planned" and not notes:
            problems.append(f"{cid}: a built or partial control needs at least one not demonstrated line")
    return problems


def _cell(text: str) -> str:
    return text.replace("|", "&#124;").replace("\n", " ").strip()


def _has_test(entry: dict[str, Any]) -> bool:
    return bool(entry.get("tests")) or any(str(f).startswith("tests/") for f in entry.get("files", []))


def _derived_gaps(status: str, entry: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    if status == "planned":
        gaps.append(
            "Not built (map status planned): nothing here shows it operating; anything cited is related evidence only."
        )
    elif status == "partial":
        gaps.append("Partly built: the missing part is named in `implemented_in` of map/controls.json.")
    if status != "planned" and not _has_test(entry):
        gaps.append("No test in this repo backs this control.")
    return gaps


def _backing(entry: dict[str, Any]) -> str:
    parts = [f"`{t}`" for t in entry.get("tests", [])]
    tests_dir = [f for f in entry.get("files", []) if str(f).startswith("tests/")]
    others = [f for f in entry.get("files", []) if f not in tests_dir]
    parts += [f"`{f}` (test script)" for f in tests_dir]
    parts += [f"`{f}`" for f in others]
    return "<br>".join(parts) if parts else "none cited"


def render_mapping(controls: list[dict[str, Any]], mapping: dict[str, Any]) -> str:
    entries: dict[str, Any] = mapping["controls"]
    lines = list(HEADER)
    lines += [
        "This page is generated by `uv run --frozen python -m workflows.assurance generate --write` from "
        "`map/controls.json`, `governance/soc2_mapping.json` and the repo. Do not edit it by hand; `check` fails when "
        "it "
        "drifts or when a cited test or file does not exist.",
        "",
        "**This is not a certification, not an attestation and not an audit result.** Each row is a claim this system "
        "makes "
        "about one control, with the tests and files that back it on synthetic fixtures, and an explicit list of what "
        "is not "
        "demonstrated. No auditor has seen it. Whether the MSP holds any SOC report is UNVERIFIED (docs/UNVERIFIED.md "
        "U-01).",
        "",
        "## How to read it",
        "",
        "- Status is `built`, `partial` or `planned` exactly as `map/controls.json` derives it. A control built after "
        "the map "
        "was last updated still reads as the map says (see RR-4 in `governance/RISK_REGISTER.md`); that understates, "
        "never "
        "overstates.",
        "- Criterion ids are copied from the `SOC2:` entries of `framework_refs` in the map. The AICPA criteria text "
        "is not in "
        "this repo and was not consulted, so whether each id fits its control is the map author's judgement "
        "(UNVERIFIED).",
        "- A test is cited as `path::name`. The checker confirms the file exists and defines that test; it does not "
        "run the "
        "test. The test suite does that, on fixtures, with mock providers and no real tenant.",
        "- A SOC 2 Type II report concerns operation over a period. Nothing here covers a period, a population, a "
        "sample or "
        "a real client: **operating effectiveness is not demonstrated for any control.**",
        "",
        "## Controls as claims",
        "",
        "| Control | Name | Status | SOC 2 criteria (claimed) | Claim | Backed by | Not demonstrated |",
        "|---|---|---|---|---|---|---|",
    ]
    by_criterion: dict[str, list[tuple[str, str, bool]]] = defaultdict(list)
    for control in controls:
        cid = control["id"]
        entry = entries[cid]
        status = control_status(control)
        criteria = soc2_criteria(control)
        for criterion in criteria:
            by_criterion[criterion].append((cid, status, _has_test(entry)))
        gaps = _derived_gaps(status, entry) + list(entry.get("not_demonstrated", []))
        lines.append(
            "| "
            + " | ".join(
                [
                    cid,
                    _cell(control["name"]),
                    status,
                    ", ".join(f"`{c}`" for c in criteria) or "none mapped in the map",
                    _cell(control["objective"]),
                    _cell(_backing(entry)),
                    _cell("<br>".join(_cell(g) for g in gaps)),
                ]
            )
            + " |"
        )
    lines += [
        "",
        "## By criterion",
        "",
        "| Criterion | Mapped controls | Built | Partial | Planned | Controls with a cited test |",
        "|---|---|---|---|---|---|",
    ]
    for criterion in sorted(by_criterion, key=_criterion_key):
        rows = by_criterion[criterion]
        count = {s: sum(1 for _, st, _ in rows if st == s) for s in ("built", "partial", "planned")}
        tested = [cid for cid, _, has in rows if has]
        lines.append(
            f"| `{criterion}` | {', '.join(cid for cid, _, _ in rows)} | {count['built']} | {count['partial']} | "
            f"{count['planned']} | {', '.join(tested) or 'none'} |"
        )
    lines += [
        "",
        "A criterion that is not listed has no control mapped to it here. This page does not claim to cover the "
        "criteria set; "
        "the full list was not consulted.",
        "",
        "## Not demonstrated, for every row",
        "",
        "- Operation over a period (Type II), sampling, populations, and any test by an independent party.",
        "- Anything at a real client or tenant: all data is synthetic, all providers are mocks, and the identity file "
        "is static.",
        "- People and process controls (training, vendor review, access reviews by a named person): the roles are "
        "proposals and "
        "who holds them is unknown (GQ-01).",
        "- That a later change keeps a cited test meaningful: the checker proves the test exists, not that it still "
        "tests the claim.",
        "",
    ]
    return "\n".join(lines)


def _criterion_key(criterion: str) -> tuple[str, int, int]:
    match = re.fullmatch(r"([A-Z]+)(\d+)\.(\d+)", criterion)
    if match is None:
        return (criterion, 0, 0)
    return (match.group(1), int(match.group(2)), int(match.group(3)))
