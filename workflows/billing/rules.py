"""Explainable billing classification (B-76, B76-1). Rules, no model; a suggestion for a human, never an invoice change.

Every time entry is placed in one of four categories by the first contract clause it matches, in the clause order the
contract fixture lists them. The result names the clause (its id and text) and says why it matched, so a lead can
check it against the contract. An entry no clause matches is ``unclassified``: it is handed to a human, never guessed.

Only structured fields decide the category: work type, after-hours flag, project id and hours. The free-text note is
untrusted input and never changes a category (docs/BLUEPRINT.md zero trust); an instruction inside a note is flagged
instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

CATEGORIES: tuple[str, ...] = ("billable", "contract-covered", "project", "non-billable")
UNCLASSIFIED = "unclassified"
# PSA billing codes (as the fixture spells them) mapped to the categories above.
PSA_CODE_TO_CATEGORY: dict[str, str] = {
    "billable": "billable",
    "contract": "contract-covered",
    "project": "project",
    "non-billable": "non-billable",
}
_INSTRUCTION = re.compile(
    r"\b(ignore (all |any |the )?(previous|prior|above) (rules|instructions)|disregard (the )?(rules|instructions)"
    r"|mark (this|all|every)[a-z ]{0,20} as|classify (this|all|every)[a-z ]{0,20} as|system prompt|you must now)\b",
    re.IGNORECASE,
)


class BillingError(ValueError):
    """Bad input or a refused caller; nothing was written except the audit record of a refusal."""


@dataclass(frozen=True)
class Classification:
    entry_id: str
    category: str
    clause_id: str | None
    clause_text: str | None
    reasons: list[str]
    flags: list[str] = field(default_factory=list)
    covered_hours: float | None = None
    billable_hours: float | None = None


def _clauses(contract: dict[str, Any]) -> list[dict[str, Any]]:
    clauses = contract.get("clauses")
    if not isinstance(clauses, list) or not clauses:
        raise BillingError("contract has no clauses")
    for c in clauses:
        when = c.get("when") if isinstance(c, dict) else None
        if (
            not isinstance(c, dict)
            or not isinstance(c.get("id"), str)
            or c.get("category") not in CATEGORIES
            or not isinstance(c.get("text"), str)
            or not isinstance(when, dict)
            or not when
            or not set(when) <= {"work_types", "after_hours", "has_project"}
        ):
            raise BillingError(f"malformed contract clause: {str(c)[:80]}")
    return list(clauses)


def _matches(when: dict[str, Any], entry: dict[str, Any], has_project: bool) -> list[str] | None:
    """The reasons a clause's conditions hold for the entry, or None when any condition fails."""
    why: list[str] = []
    if "work_types" in when:
        if entry.get("work_type") not in when["work_types"]:
            return None
        why.append(f"work type {entry.get('work_type')!r} is listed")
    if "after_hours" in when:
        if bool(entry.get("after_hours")) != bool(when["after_hours"]):
            return None
        why.append(f"after-hours flag is {bool(entry.get('after_hours'))}")
    if "has_project" in when:
        if has_project != bool(when["has_project"]):
            return None
        why.append(f"entry carries project {entry.get('project_id')!r}, which the contract lists")
    return why


def _hours(entry: dict[str, Any]) -> float:
    value = entry.get("hours")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return 0.0
    return float(value)


def classify_entries(
    contract: dict[str, Any], tickets: dict[str, dict[str, Any]], entries: list[dict[str, Any]]
) -> dict[str, Classification]:
    """Classify every entry; ``monthly_cap_hours`` is applied in (date, id) order, so the result does not depend on
    the order the entries are listed in."""
    clauses = _clauses(contract)
    projects = {p["id"] for p in contract.get("projects", [])}
    used: dict[tuple[str, str], float] = {}
    out: dict[str, Classification] = {}
    for entry in sorted(entries, key=lambda e: (str(e.get("date")), str(e.get("id")))):
        eid = str(entry["id"])
        project_id = entry.get("project_id")
        has_project = project_id in projects
        flags: list[str] = []
        if project_id and not has_project:
            flags.append("unknown-project")
        ticket = tickets.get(str(entry.get("ticket")))
        if ticket and ticket.get("ticket_type") == "project" and not project_id:
            flags.append("project-ticket-without-project-id")
        if _INSTRUCTION.search(str(entry.get("note", ""))):
            flags.append("instruction-in-note")
        out[eid] = _one(entry, clauses, has_project, flags, used)
    return out


def _one(
    entry: dict[str, Any],
    clauses: list[dict[str, Any]],
    has_project: bool,
    flags: list[str],
    used: dict[tuple[str, str], float],
) -> Classification:
    eid = str(entry["id"])
    for clause in clauses:
        why = _matches(clause["when"], entry, has_project)
        if why is None:
            continue
        cid, text, category = str(clause["id"]), str(clause["text"]), str(clause["category"])
        reasons = [f"clause {cid} matched: " + "; ".join(why)]
        covered: float | None = None
        billable: float | None = None
        cap = clause.get("monthly_cap_hours")
        if cap is not None:
            hours = _hours(entry)
            key = (cid, str(entry.get("date", ""))[:7])
            room = max(0.0, float(cap) - used.get(key, 0.0))
            covered = min(hours, room)
            billable = hours - covered
            used[key] = used.get(key, 0.0) + covered
            reasons.append(
                f"monthly cap {cap:g} h: {covered:g} h covered, {billable:g} h over the cap "
                f"({key[1]}, {used[key]:g} h of {cap:g} h used after this entry)"
            )
            if billable > 0:
                category = str(clause.get("overflow", {}).get("category", "billable"))
                reasons.append(f"hours over the cap are {category} under clause {cid}")
                flags.append("over-cap")
        return Classification(eid, category, cid, text, reasons, flags, covered, billable)
    reasons = [f"no contract clause covers work type {entry.get('work_type')!r}; a person must classify it"]
    return Classification(eid, UNCLASSIFIED, None, None, reasons, flags)
