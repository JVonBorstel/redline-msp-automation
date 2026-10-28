"""The scoring rubric file (governance/intake_rubric.json) and the one formula every score uses (B-95, B95-1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.paths import REPO_ROOT

RUBRIC_PATH = REPO_ROOT / "governance" / "intake_rubric.json"
RiskClass = Literal["R0", "R1", "R2", "R3"]
Effect = Literal[
    "read-only",
    "reversible-one-object",
    "reversible-access-or-many",
    "irreversible-or-identity-or-tenant-wide",
]
DataClassId = Literal["DC-0", "DC-1", "DC-2", "DC-3", "DC-4", "DC-5", "DC-6"]
DATA_CLASSES: tuple[DataClassId, ...] = ("DC-0", "DC-1", "DC-2", "DC-3", "DC-4", "DC-5", "DC-6")
RISK_ORDER: tuple[RiskClass, ...] = ("R0", "R1", "R2", "R3")


class RubricError(ValueError):
    """The rubric file is missing or invalid."""


class Rubric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1]
    label: str
    risk_weights: dict[RiskClass, int]
    effect_base: dict[Effect, RiskClass]
    sensitivity: dict[DataClassId, Literal["low", "moderate", "high", "prohibited"]]
    value_bands_hours_per_month: dict[Literal["high", "medium"], float]
    acceptance_bar: float = Field(gt=0, le=1)
    hosted_refused_from_class: DataClassId


def load_rubric(path: Path = RUBRIC_PATH) -> Rubric:
    try:
        rubric = Rubric.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        raise RubricError(f"cannot load rubric {path}: {exc}") from exc
    if set(rubric.risk_weights) != set(RISK_ORDER) or set(rubric.effect_base) != set(get_args(Effect)):
        raise RubricError("rubric must weight R0-R3 and map every effect")
    if set(rubric.sensitivity) != set(DATA_CLASSES):
        raise RubricError("rubric must band every data class DC-0 to DC-6")
    return rubric


def monthly_hours(minutes_per_run: float, runs_per_month: float) -> float:
    """Assumed hours per month. An assumption of the submitter, never a measurement."""
    return round(minutes_per_run * runs_per_month / 60, 4)


def priority(*, hours: float, acceptance: float, effort_days: float, weight: int) -> float:
    """(monthly hours x acceptance rate) / (effort x risk weight), rounded to 2 places."""
    return round(hours * acceptance / (effort_days * weight), 2)


def value_band(hours: float, rubric: Rubric) -> Literal["high", "medium", "low"]:
    bands = rubric.value_bands_hours_per_month
    if hours >= bands["high"]:
        return "high"
    if hours >= bands["medium"]:
        return "medium"
    return "low"


def class_rank(data_class: DataClassId) -> int:
    return DATA_CLASSES.index(data_class)
