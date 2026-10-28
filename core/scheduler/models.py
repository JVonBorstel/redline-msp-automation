"""Scheduler data shapes (B-81): job config, the unit a workflow receives, what it may return, what is stored.

A workflow returns a `UnitResult`: a one-line report and zero or more `ProposedAction`s. Nothing here can run a
lever. A proposal is a request for a person to look at, not a write.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

from core.levers.models import ClientId

Every = Literal["daily", "weekly", "monthly", "quarterly"]
JobName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,62}$")]
Status = Literal["running", "ok", "failed"]
REPORT_MAX = 200
DEFAULT_CONFIG = Path(__file__).resolve().parent / "jobs.example.json"


class SchedulerError(RuntimeError):
    """The config, a time or a wiring choice is unusable. Raised before any unit runs."""


class JobConfig(BaseModel):
    """One scheduled job: what runs, how often, for which clients, and how many units it may start per tick."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: JobName
    workflow: JobName
    every: Every
    # The job is not due before this UTC hour of the day.
    not_before_hour: int = Field(default=0, ge=0, le=23)
    # "all" or a list: the clients this job is enabled for. `disabled_clients` always wins.
    clients: Literal["all"] | tuple[ClientId, ...] = "all"
    disabled_clients: tuple[ClientId, ...] = ()
    # Most units of this job started in one tick (None: no per-job cap).
    job_cap: int | None = Field(default=None, ge=1)


class SchedulerConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    jobs: tuple[JobConfig, ...] = Field(min_length=1)
    # Most units started in one tick, over all jobs and clients.
    global_cap: int = Field(default=50, ge=1)
    # Most units started for one client in one tick, over all jobs.
    per_client_cap: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _unique_names(self) -> SchedulerConfig:
        names = [j.name for j in self.jobs]
        if len(names) != len(set(names)):
            raise ValueError("job names must be unique")
        return self


def load_config(path: Path = DEFAULT_CONFIG) -> SchedulerConfig:
    """Read `{"version": 1, "global_cap": n, "per_client_cap": n, "jobs": [...]}`; any problem is a SchedulerError."""
    try:
        raw: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SchedulerError(f"scheduler config {Path(path).name} cannot be read: {type(exc).__name__}") from exc
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise SchedulerError("scheduler config must be an object with version 1")
    body = {k: v for k, v in raw.items() if k != "version"}
    try:
        return SchedulerConfig.model_validate(body)
    except ValidationError as exc:
        raise SchedulerError(f"scheduler config invalid: {exc.error_count()} problem(s)") from exc


def period_for(every: Every, now: datetime) -> str:
    """The period label a time falls in: day, ISO week, month or quarter. `now` must be timezone-aware UTC."""
    if now.utcoffset() != timedelta(0):
        raise SchedulerError("scheduler time must be timezone-aware UTC")
    now = now.astimezone(UTC)
    if every == "daily":
        return now.strftime("%Y-%m-%d")
    if every == "weekly":
        year, week, _ = now.isocalendar()
        return f"{year}-W{week:02d}"
    if every == "monthly":
        return now.strftime("%Y-%m")
    return f"{now.year}-Q{(now.month - 1) // 3 + 1}"


def job_key(job: str, client: str, period: str) -> str:
    """The idempotency key of one unit: `job/client/period`."""
    return f"{job}/{client}/{period}"


@dataclass(frozen=True)
class Unit:
    """One job for one client in one period. This is all a workflow is told."""

    key: str
    job: str
    client: str
    period: str
    as_of: datetime


@dataclass(frozen=True)
class ProposedAction:
    """A lever a workflow would like a person to consider for this client. Never run by the scheduler."""

    lever: str
    params: dict[str, Any]
    reason: str


@dataclass(frozen=True)
class UnitResult:
    report: str = ""
    proposals: tuple[ProposedAction, ...] = field(default=())


class UnitRecord(BaseModel):
    """What the job store keeps for a key. `detail` is a short code or an error class name, never error text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    job: str
    client: str
    period: str
    status: Status
    at: str
    detail: str = ""
    report: str = Field(default="", max_length=REPORT_MAX)
    proposal_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TickReport:
    """What one tick did, in order. Lists of keys, except `not_due` (job names) and the two client lists."""

    ran: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    not_due: list[str] = field(default_factory=list)
    invalid_clients: list[str] = field(default_factory=list)
    unknown_clients: list[str] = field(default_factory=list)
