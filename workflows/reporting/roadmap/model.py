"""The typed shapes of a technology roadmap draft (B-73). Building one without a cited finding raises."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LEVELS = ("low", "medium", "high")
CATEGORIES = ("hardware", "licence", "security", "backup", "devices")
UNITS = ("one-time", "per year")


class RoadmapError(ValueError):
    """The input is bad (client, period, date, price list, policy, template); nothing was written."""


class VerifyError(ValueError):
    """A draft does not match what the sources give today, or an item has no usable citation."""


@dataclass(frozen=True)
class FileRef:
    """A source file the finding was read from, repo-relative, with the SHA-256 of its content (CRLF read as LF)."""

    path: str
    sha256: str


@dataclass(frozen=True)
class Evidence:
    """One finding: which report it came from, the field in that report, its value, and the files behind it."""

    source: str
    field: str
    value: Any
    files: tuple[FileRef, ...]


@dataclass(frozen=True)
class Budget:
    """A range in the price list's currency. ``basis`` says where the figures come from."""

    low: int | float
    high: int | float
    unit: str
    basis: str

    def __post_init__(self) -> None:
        if self.unit not in UNITS:
            raise RoadmapError(f"budget unit must be one of {UNITS}")
        if not 0 <= self.low <= self.high:
            raise RoadmapError("budget range must satisfy 0 <= low <= high")
        if not self.basis:
            raise RoadmapError("a budget must say what it is based on")


@dataclass(frozen=True)
class Recommendation:
    id: str
    category: str
    rule: str
    title: str
    action: str
    effort: str  # how much work to do it: low | medium | high
    risk: str  # how much risk if the finding is left alone: low | medium | high
    budget: Budget
    evidence: tuple[Evidence, ...]

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise RoadmapError(f"{self.id}: unknown category {self.category!r}")
        if self.effort not in LEVELS or self.risk not in LEVELS:
            raise RoadmapError(f"{self.id}: effort and risk must each be one of {LEVELS}")
        if not self.evidence:
            raise RoadmapError(f"{self.id}: no recommendation without a cited finding")
        for item in self.evidence:
            if not item.source or not item.field or not item.files:
                raise RoadmapError(f"{self.id}: every finding needs a source, a field and at least one source file")


@dataclass(frozen=True)
class Roadmap:
    client: str
    display_name: str
    period: str
    generated_on: str
    recommendations: tuple[Recommendation, ...]
    totals: dict[str, int | float]
    gaps: tuple[str, ...]
    currency: str = "USD"
    status: str = "draft"
    reviewed_by: str | None = None
    reviewed_on: str | None = None
    label: str = field(
        default="fixture-based, synthetic (invented tenants, devices and prices); not a real client's results"
    )
