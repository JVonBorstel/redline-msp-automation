"""Risk register (B-95, B95-3): the AI-specific risks of docs/map/05-governance.md section 5, each with an
owner role and a treatment, plus the risks of this tooling itself.

The risk text, the controls that answer it and the residual line are read from the AIR table of the governance map,
and the state of each control from ``map/controls.json``, so the register cannot drift from either. Only the
owner role, the treatment, its rationale and the next step are written by hand, in
``governance/risk_register.json``. Owners are roles (D6-17), never people. No likelihood or impact rating is given:
there is no incident or loss data to base one on.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from core.paths import REPO_ROOT
from workflows.assurance.soc2 import control_status, load_controls

REGISTER_PATH = "governance/risk_register.json"
GOVERNANCE_MAP = "docs/map/05-governance.md"
ROADMAP_PATH = "map/roadmap.json"
AIR_ROW = re.compile(r"^\| `(AIR-\d+)` \| (.+) \|$")
CONTROL_ID = re.compile(r"\bC-\d{2}\b")
HEADER = (
    "# AI risk register",
    "",
    "Status: **document-only** (generated register; owners and treatments are proposals)",
    "",
    "> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only.",
    "",
)


def load_register(root: Path = REPO_ROOT) -> dict[str, Any]:
    data = json.loads((root / REGISTER_PATH).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError(f"{REGISTER_PATH} must be an object with version 1")
    return data


def parse_air_table(text: str) -> list[dict[str, Any]]:
    """The AIR rows of the governance map: id, risk, how it shows up, controls cited, residual risk and status."""
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = AIR_ROW.match(line)
        if match is None:
            continue
        cells = [c.strip() for c in match.group(2).split(" | ")]
        if len(cells) != 4:
            raise ValueError(f"{match.group(1)}: expected 4 cells after the id, found {len(cells)}")
        controls: list[str] = []
        for cid in CONTROL_ID.findall(cells[2]):
            if cid not in controls:
                controls.append(cid)
        rows.append(
            {"id": match.group(1), "risk": cells[0], "shows": cells[1], "controls": controls, "residual": cells[3]}
        )
    return rows


def _owner_problems(rid: str, entry: dict[str, Any], treatments: list[str]) -> list[str]:
    problems: list[str] = []
    if not str(entry.get("owner_role", "")).strip():
        problems.append(f"{rid}: owner_role is empty")
    if entry.get("treatment") not in treatments:
        problems.append(f"{rid}: treatment {entry.get('treatment')!r} is not one of {', '.join(treatments)}")
    for field in ("rationale", "next_step"):
        if not str(entry.get(field, "")).strip():
            problems.append(f"{rid}: {field} is empty")
    return problems


def check_register(register: dict[str, Any], air: list[dict[str, Any]], controls: list[dict[str, Any]]) -> list[str]:
    """Problems found, one per line; empty when the register matches the governance map and the control list."""
    problems: list[str] = []
    known = {c["id"] for c in controls}
    treatments: list[str] = list(register.get("treatments", []))
    entries: dict[str, Any] = register.get("air", {})
    in_map = {row["id"] for row in air}
    for rid in sorted(in_map - set(entries), key=_num):
        problems.append(f"{rid}: in the governance map but not in the register")
    for rid in sorted(set(entries) - in_map, key=_num):
        problems.append(f"{rid}: in the register but not in the governance map")
    for row in air:
        for cid in row["controls"]:
            if cid not in known:
                problems.append(f"{row['id']}: governance map cites unknown control {cid}")
        if row["id"] in entries:
            problems += _owner_problems(row["id"], entries[row["id"]], treatments)
    seen: set[str] = set()
    for extra in register.get("extra", []):
        rid = str(extra.get("id", ""))
        if not re.fullmatch(r"RR-\d+", rid) or rid in seen:
            problems.append(f"{rid or '(no id)'}: extra risk id must be a unique RR-n")
        seen.add(rid)
        for field in ("risk", "how_it_shows", "residual"):
            if not str(extra.get(field, "")).strip():
                problems.append(f"{rid}: {field} is empty")
        for cid in extra.get("controls", []):
            if cid not in known:
                problems.append(f"{rid}: cites unknown control {cid}")
        problems += _owner_problems(rid, extra, treatments)
    for rid, entry in entries.items():
        for cid in CONTROL_ID.findall(str(entry.get("next_step", "")) + str(entry.get("rationale", ""))):
            if cid not in known:
                problems.append(f"{rid}: text cites unknown control {cid}")
    return problems


def _num(rid: str) -> int:
    match = re.search(r"\d+", rid)
    return int(match.group()) if match else 0


def _cell(text: str) -> str:
    return text.replace("|", "&#124;").replace("\n", " ").strip()


def _roadmap_items(root: Path) -> list[dict[str, Any]]:
    data = json.loads((root / ROADMAP_PATH).read_text(encoding="utf-8"))
    return [item for wave in data["waves"] for item in wave["items"]]


def render_register(root: Path = REPO_ROOT) -> str:
    register = load_register(root)
    controls = load_controls(root)
    air = parse_air_table((root / GOVERNANCE_MAP).read_text(encoding="utf-8"))
    status = {c["id"]: control_status(c) for c in controls}
    items = _roadmap_items(root)

    def control_cell(ids: list[str]) -> str:
        return ", ".join(f"{cid} ({status.get(cid, '?')})" for cid in ids)

    def state_cell(ids: list[str]) -> str:
        counts = {s: sum(1 for i in ids if status.get(i) == s) for s in ("built", "partial", "planned")}
        return f"{counts['built']} built, {counts['partial']} partial, {counts['planned']} planned"

    def roadmap_cell(ids: list[str]) -> str:
        open_ids = {i for i in ids if status.get(i) != "built"}
        found = [str(it["id"]) for it in items if open_ids & set(it.get("controls", []))]
        return ", ".join(found) if found else "none"

    lines = list(HEADER)
    lines += [
        "This page is generated by `uv run --frozen python -m workflows.assurance generate --write` from the AIR table "
        "of "
        "`docs/map/05-governance.md` (risk, controls, residual), `map/controls.json` (control state), "
        "`map/roadmap.json` and "
        "`governance/risk_register.json` (owner role, treatment, next step). Do not edit it by hand; `check` fails "
        "when it drifts.",
        "",
        f"As of {register['as_of']}. " + str(register["label"]),
        "",
        "Treatments: `mitigate` (reduce with controls), `avoid` (do not do the risky thing), `accept` (live with the "
        "residual), `transfer` (move to a vendor or insurer). Every treatment here is a proposal until the compliance "
        "owner "
        "role accepts it. Control states are `built`, `partial` or `planned` as in `map/controls.json`.",
        "",
        "| Id | Risk | Controls (state) | State | Residual per the governance map | Owner role | Treatment | Why | "
        "Next step | "
        "Roadmap items listing an unbuilt cited control |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in air:
        entry = register["air"][row["id"]]
        lines.append(
            "| "
            + " | ".join(
                [
                    row["id"],
                    _cell(row["risk"]),
                    control_cell(row["controls"]),
                    state_cell(row["controls"]),
                    _cell(row["residual"]),
                    _cell(entry["owner_role"]),
                    entry["treatment"],
                    _cell(entry["rationale"]),
                    _cell(entry["next_step"]),
                    roadmap_cell(row["controls"]),
                ]
            )
            + " |"
        )
    for extra in register.get("extra", []):
        lines.append(
            "| "
            + " | ".join(
                [
                    extra["id"],
                    _cell(extra["risk"]),
                    control_cell(extra["controls"]),
                    state_cell(extra["controls"]),
                    _cell(extra["residual"]),
                    _cell(extra["owner_role"]),
                    extra["treatment"],
                    _cell(extra["rationale"]),
                    _cell(extra["next_step"]),
                    roadmap_cell(extra["controls"]),
                ]
            )
            + " |"
        )
    lines += [
        "",
        "`RR-n` rows are risks of this tooling, written by hand; `AIR-n` rows come from the governance map.",
        "",
        "## Limits",
        "",
        "- No likelihood or impact rating is given; a rating without incident or loss data would be invented.",
        "- Who holds each owner role at the MSP is unknown (GQ-01); the register does not name anyone.",
        "- The roadmap column lists items that mention an unbuilt control; it does not say whether the item is built.",
        "- Control states follow the map, which can lag the code (RR-4).",
        "",
    ]
    return "\n".join(lines)
