"""Use-case intake and the deterministic, explainable score (B-95, B95-1; W-TOOL-13).

An intake is a small typed form (``UseCaseIntake``) filled by a person. ``score`` is a pure function of the intake, the
rubric file, the ROI fixture rows and the never-automate list: no clock, no model, no randomness. It returns the risk
class (R0-R3), the data sensitivity band, the value band, a priority when one can honestly be computed, a verdict, and
``reasons``: one line per rule that fired, each starting with the rule id from governance/USE_CASE_INTAKE.md.

What it does not do: it reads the declared fields only. The never-automate check matches the declared lever names and
inventory ids (the same list and matcher the lever registry uses), not the free-text problem statement, so a person
reviews every intake. The score ranks ideas for a conversation; it approves nothing.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from core.levers.registry import NeverAutomate
from workflows.assurance.roi import RoiRow
from workflows.assurance.rubric import (
    RISK_ORDER,
    DataClassId,
    Effect,
    RiskClass,
    Rubric,
    class_rank,
    monthly_hours,
    priority,
    value_band,
)

Verdict = Literal[
    "blocked",
    "design-review-required",
    "needs-inventory-mapping",
    "needs-measurement",
    "below-acceptance-bar",
    "candidate",
]
LEVER_NAME = r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+$"
CLIENT_ID = r"^[a-z][a-z0-9-]{1,40}$"


class IntakeError(ValueError):
    """An intake file is unreadable or invalid, or it names an ROI row that does not exist."""


class UseCaseIntake(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = Field(description="Intake format version.")
    data_basis: Literal["synthetic"] = Field(description="Must be synthetic: no real client or ticket data.")
    id: str = Field(pattern=r"^UC-\d{3}$", description="Intake id, UC-nnn.")
    title: str = Field(min_length=1, max_length=120, description="Short name of the idea.")
    submitter_role: str = Field(
        min_length=1, max_length=80, description="Role of the submitter, never a person's name."
    )
    client_scope: Literal["msp-internal", "one-client", "many-clients"] = Field(
        description="Whose work or data the idea touches."
    )
    client: str | None = Field(
        pattern=CLIENT_ID, description="Synthetic client id; required for one-client, else null."
    )
    problem: str = Field(
        min_length=1, max_length=600, description="The work today and what would change. Free text, read by a person."
    )
    effect: Effect = Field(description="What the automation would do to state: the base of the risk class.")
    data_classes: tuple[DataClassId, ...] = Field(
        min_length=1, description="Every data class the idea touches (DC-0 to DC-6)."
    )
    model_route: Literal["none", "local", "hosted"] = Field(description="Where any model call would run.")
    proposed_levers: tuple[str, ...] = Field(description="Lever names the idea would use or add.")
    inventory_ids: tuple[str, ...] = Field(description="Work inventory ids (W-AREA-nn) the idea automates.")
    minutes_per_run: float = Field(gt=0, le=1440, description="ASSUMED minutes of human work per occurrence.")
    runs_per_month: int = Field(ge=1, le=1_000_000, description="ASSUMED occurrences per month.")
    effort_days: float = Field(gt=0, le=365, description="ASSUMED build effort in days.")
    roi_row: str | None = Field(
        description="Id of a row in governance/roi_fixtures.json whose fixture rate applies; null if unmeasured."
    )

    @model_validator(mode="after")
    def _shape(self) -> UseCaseIntake:
        if self.client_scope == "one-client" and self.client is None:
            raise ValueError("client_scope one-client needs a client id")
        if self.client_scope != "one-client" and self.client is not None:
            raise ValueError("client must be null unless client_scope is one-client")
        for lever in self.proposed_levers:
            if not re.fullmatch(LEVER_NAME, lever):
                raise ValueError(f"{lever!r} is not a lever name (lowercase, dotted, e.g. user.disable)")
        for inventory_id in self.inventory_ids:
            if not re.fullmatch(r"W-[A-Z0-9]+-\d{2}", inventory_id):
                raise ValueError(f"{inventory_id!r} is not an inventory id (W-AREA-nn)")
        return self


@dataclass(frozen=True)
class Scored:
    id: str
    title: str
    risk_class: RiskClass
    sensitivity: str
    hours_per_month: float
    value_band: str
    acceptance: float | None
    priority: float | None
    verdict: Verdict
    blocked: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "risk_class": self.risk_class,
            "sensitivity": self.sensitivity,
            "hours_per_month_assumed": self.hours_per_month,
            "value_band": self.value_band,
            "acceptance_fixture": None if self.acceptance is None else round(self.acceptance, 4),
            "priority": self.priority,
            "verdict": self.verdict,
            "blocked": self.blocked,
            "reasons": list(self.reasons),
        }


def load_intake(path: Path) -> UseCaseIntake:
    try:
        return UseCaseIntake.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        raise IntakeError(f"{Path(path).name}: {exc}") from exc


def load_intakes(folder: Path) -> list[UseCaseIntake]:
    return [load_intake(p) for p in sorted(Path(folder).glob("*.json"))]


def _raise(a: RiskClass, b: RiskClass) -> RiskClass:
    return a if RISK_ORDER.index(a) >= RISK_ORDER.index(b) else b


def _risk_class(intake: UseCaseIntake, rubric: Rubric, reasons: list[str]) -> RiskClass:
    risk = rubric.effect_base[intake.effect]
    reasons.append(f"RC-1: effect '{intake.effect}' sets the base risk class {risk}.")
    if intake.client_scope == "many-clients" and intake.effect != "read-only":
        risk = _raise(risk, "R3")
        reasons.append(
            "RC-2: a change across many clients is at least R3 (governance map section 6.1: bulk operations)."
        )
    if "DC-6" in intake.data_classes:
        risk = _raise(risk, "R3")
        reasons.append("RC-3: anything touching DC-6 secrets is R3 (governance map section 6.1).")
    return risk


def score(intake: UseCaseIntake, *, rubric: Rubric, roi: Mapping[str, RoiRow], never: NeverAutomate) -> Scored:
    reasons: list[str] = []
    risk = _risk_class(intake, rubric, reasons)
    top = max(intake.data_classes, key=class_rank)
    sensitivity = rubric.sensitivity[top]
    reasons.append(f"DS-1: highest data class named is {top}, sensitivity '{sensitivity}'.")
    hours = monthly_hours(intake.minutes_per_run, intake.runs_per_month)
    band = value_band(hours, rubric)
    reasons.append(f"VB-1: {hours:g} assumed hours per month, value band '{band}' (assumed, unadjusted).")

    acceptance: float | None = None
    if intake.roi_row is not None:
        row = roi.get(intake.roi_row)
        if row is None:
            raise IntakeError(f"{intake.id}: roi_row {intake.roi_row!r} is not a row of the ROI fixtures")
        acceptance = row.acceptance
        reasons.append(
            f"AC-1: fixture acceptance {row.numerator}/{row.denominator} = {acceptance * 100:.1f}% from "
            f"{row.report} (author-written gold labels)."
        )

    blocks: list[str] = []
    for lever in intake.proposed_levers:
        hit = never.match(lever)
        if hit is not None:
            entry, pattern = hit
            blocks.append(
                f"BL-NEVER: lever '{lever}' matches never-automate pattern '{pattern}' ({entry.inventory_id} "
                f"{entry.name})."
            )
    listed = set(never.inventory_ids())
    for inventory_id in intake.inventory_ids:
        if inventory_id in listed:
            blocks.append(f"BL-NEVER: inventory id {inventory_id} is on the never-automate list.")
    if "DC-6" in intake.data_classes:
        blocks.append("BL-DC6: secrets never enter a prompt, a log or a model route (governance map section 1).")
    if intake.model_route == "hosted" and class_rank(top) >= class_rank(rubric.hosted_refused_from_class):
        blocks.append(
            f"BL-HOSTED: a hosted model route with {top} data is refused until provider terms are approved (C-28, "
            f"planned)."
        )
    reasons.extend(blocks)

    verdict: Verdict
    if blocks:
        verdict = "blocked"
        reasons.append("VD-BLOCK: blocked; no priority is computed and the idea is not ranked.")
    elif risk == "R3":
        verdict = "design-review-required"
        reasons.append("VD-R3: R3 needs a written change plan, two approvers and never runs unattended (HO-2 to HO-5).")
    elif not intake.inventory_ids and not intake.proposed_levers:
        verdict = "needs-inventory-mapping"
        reasons.append(
            "VD-MAP: no lever and no inventory id is named, so the never-automate check had nothing to read."
        )
    elif acceptance is None:
        verdict = "needs-measurement"
        reasons.append("VD-MEASURE: no fixture acceptance rate is linked, so no priority is computed.")
    elif acceptance < rubric.acceptance_bar:
        verdict = "below-acceptance-bar"
        reasons.append(
            f"VD-BAR: fixture acceptance {acceptance * 100:.1f}% is under the {rubric.acceptance_bar * 100:.0f}% bar."
        )
    else:
        verdict = "candidate"
        reasons.append(f"VD-OK: at or over the {rubric.acceptance_bar * 100:.0f}% fixture bar and not blocked.")

    value: float | None = None
    if verdict != "blocked" and acceptance is not None:
        value = priority(
            hours=hours, acceptance=acceptance, effort_days=intake.effort_days, weight=rubric.risk_weights[risk]
        )
        reasons.append(
            f"PR-1: ({hours:g} h x {acceptance:.4f}) / ({intake.effort_days:g} d x weight {rubric.risk_weights[risk]}) "
            f"= {value:.2f}."
        )
    return Scored(
        id=intake.id,
        title=intake.title,
        risk_class=risk,
        sensitivity=sensitivity,
        hours_per_month=hours,
        value_band=band,
        acceptance=acceptance,
        priority=value,
        verdict=verdict,
        blocked=verdict == "blocked",
        reasons=tuple(reasons),
    )


def rank(scored: Iterable[Scored]) -> list[Scored]:
    """Scored ideas that have a priority, highest first; ties by id. Blocked and unmeasured ideas are left out."""
    ranked = [s for s in scored if s.priority is not None and not s.blocked]
    return sorted(ranked, key=lambda s: (-(s.priority or 0.0), s.id))
