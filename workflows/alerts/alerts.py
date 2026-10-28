"""Security-alert grouping and the on-call summary (B-43, specs/B-43.md).

Inventory W-SEC-01, W-SD-12, W-EP-02; controls C-12, C-13, C-27, C-41.

On-call engineers should wake up to five grouped events, not fifty alerts. This groups ONE client's alerts by entity
inside a time window and builds a summary ordered by severity. It reads and suggests; it never closes, contains or
acknowledges an alert (that would be a lever, approved by a person).

Isolation (C-27, B43-1). Every entry point takes the client explicitly. Alerts of any other client are dropped in
``pool_for`` before anything is keyed, compared or counted, and a group belongs to exactly one client, so two clients
that each have a host called ``SRV-FILE-01`` can never land in one group.

Untrusted text (C-12, B43-2). Grouping reads only structured, pattern-checked fields (source type, severity, category,
entity, time, case id), never ``title`` or ``description``. The summary includes alert text only inside
``wrap_untrusted`` blocks, and withholds it entirely for an alert the injection detector flags (the alert is still
grouped, so a hostile description can hide nothing). Text can never change a group, a severity or a lever.

External SOC (D6-04, B43-4). When an alert carries a SOC case id, its group carries that id and the summary says the
SOC is the responder. This program groups and enriches; it does not replace or contradict the SOC's containment.

No model is called: the rules are plain configuration a reviewer can read (D-022).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator, model_validator

from adapters.alerts import SEVERITY_ORDER, Alert, AlertsAdapter
from core.guard import detect_injection, wrap_untrusted
from core.levers import Registry

DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.json")
CLIENT_ID = r"^[a-z0-9][a-z0-9-]{0,62}$"
GroupType = Literal["incident", "health"]
Responder = Literal["external-soc", "on-call"]
_LEVER_NAME = re.compile(r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9-]*)+$")


class AlertsError(ValueError):
    """The input is bad (config, client id, adapter failure); nothing was grouped."""


class BusinessHours(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    start_hour_utc: int = Field(ge=0, le=23)
    end_hour_utc: int = Field(ge=1, le=24)
    weekdays_only: bool = True

    @model_validator(mode="after")
    def _ordered(self) -> BusinessHours:
        if self.end_hour_utc <= self.start_hour_utc:
            raise ValueError("end_hour_utc must be after start_hour_utc")
        return self


class AlertsConfig(BaseModel):
    """The workflow's configuration; unknown keys fail the load (STD-CF-3)."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    version: Literal[1]
    note: str = Field(default="", alias="_note")
    window_minutes: int = Field(gt=0, le=1440)
    health_categories: tuple[Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{1,40}$")], ...] = Field(
        min_length=1
    )
    business_hours: BusinessHours
    enrichment: dict[str, tuple[str, ...]]  # entity kind -> lever names that would enrich a group

    @field_validator("enrichment")
    @classmethod
    def _lever_names(cls, value: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
        for names in value.values():
            if len(set(names)) != len(names) or not all(len(n) <= 64 and _LEVER_NAME.fullmatch(n) for n in names):
                raise ValueError("enrichment must list unique lever names")
        return value

    @property
    def window(self) -> timedelta:
        return timedelta(minutes=self.window_minutes)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> AlertsConfig:
    try:
        return AlertsConfig.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        raise AlertsError(f"cannot load alerts config from {path}: {exc}") from exc


# -- isolation: the only way alerts enter -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Pool:
    """One client's alerts, oldest first. ``flagged`` are alerts whose text the injection detector flags."""

    client: str
    alerts: tuple[Alert, ...]
    flagged: tuple[str, ...]


def pool_for(
    client: str, alerts: Iterable[Alert], *, since: datetime | None = None, until: datetime | None = None
) -> Pool:
    """Keep only ``client``'s alerts (others are dropped here, before any keying) inside [since, until]."""
    if not re.fullmatch(CLIENT_ID, client):
        raise AlertsError(f"invalid client id {client!r}")
    kept = sorted(
        (
            a
            for a in alerts
            if a.client == client
            and (since is None or a.created_at >= since)
            and (until is None or a.created_at <= until)
        ),
        key=lambda a: (a.created_at, a.id),
    )
    flagged = tuple(a.id for a in kept if detect_injection(a.title + "\n\n" + a.description).flagged)
    return Pool(client, tuple(kept), flagged)


def pool_from_adapter(adapter: AlertsAdapter, *, since: datetime | None = None, until: datetime | None = None) -> Pool:
    """The adapter's own client's alerts. A failed adapter call raises ``AlertsError`` naming the reason."""
    result = adapter.list_alerts(since, until)
    if not result.ok or result.data is None:
        raise AlertsError(f"alerts adapter failed: {result.reason}")
    return pool_for(adapter.client, result.data, since=since, until=until)


# -- groups -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AlertGroup:
    id: str
    client: str
    group_type: GroupType
    entity_kind: str
    entity_id: str
    source_types: tuple[str, ...]
    severity: str
    alert_ids: tuple[str, ...]
    first_at: datetime
    last_at: datetime
    soc_case_ids: tuple[str, ...]

    @property
    def responder(self) -> Responder:
        return "external-soc" if self.soc_case_ids else "on-call"


def group_type_of(alert: Alert, config: AlertsConfig) -> GroupType:
    """RMM agent and endpoint sensor health alerts form their own group type (B43-3)."""
    return "health" if alert.category in config.health_categories else "incident"


def _worst(severities: Iterable[str]) -> str:
    return min(severities, key=SEVERITY_ORDER.index)


def group_alerts(pool: Pool, config: AlertsConfig) -> tuple[AlertGroup, ...]:
    """Group one client's pool by (type, entity) where neighbours in time are within the window (B43-1).

    A lone alert is a group of one, so nothing is hidden. Reads no alert text. Most severe groups come first.
    """
    by_key: dict[tuple[GroupType, str, str], list[Alert]] = defaultdict(list)
    for alert in pool.alerts:
        by_key[(group_type_of(alert, config), alert.entity_kind, alert.entity_id.lower())].append(alert)
    groups: list[AlertGroup] = []
    for (gtype, kind, _), items in by_key.items():
        runs: list[list[Alert]] = []
        for alert in items:  # the pool is sorted by time
            if runs and alert.created_at - runs[-1][-1].created_at <= config.window:
                runs[-1].append(alert)
            else:
                runs.append([alert])
        for run in runs:
            first = run[0]
            groups.append(
                AlertGroup(
                    id=f"G-{pool.client}-{gtype}-{first.id}",
                    client=pool.client,
                    group_type=gtype,
                    entity_kind=kind,
                    entity_id=first.entity_id,
                    source_types=tuple(sorted({a.source_type for a in run})),
                    severity=_worst(a.severity for a in run),
                    alert_ids=tuple(a.id for a in run),
                    first_at=first.created_at,
                    last_at=run[-1].created_at,
                    soc_case_ids=tuple(sorted({a.soc_case_id for a in run if a.soc_case_id})),
                )
            )
    groups.sort(key=lambda g: (SEVERITY_ORDER.index(g.severity), g.first_at, g.id))
    return tuple(groups)


# -- the on-call summary ------------------------------------------------------------------------------------------


def is_after_hours(moment: datetime, config: AlertsConfig) -> bool:
    hours = config.business_hours
    when = moment.astimezone(UTC)
    if hours.weekdays_only and when.weekday() >= 5:
        return True
    return not hours.start_hour_utc <= when.hour < hours.end_hour_utc


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _enrichment(kind: str, config: AlertsConfig, registry: Registry) -> dict[str, list[str]]:
    """Read levers that would enrich a group. Only a registered ``read`` lever is offered as available."""
    available: list[str] = []
    planned: list[str] = []
    for name in config.enrichment.get(kind, ()):
        lever = registry.get(name)
        (available if lever is not None and lever.lever_class == "read" else planned).append(name)
    return {"available": available, "planned_not_built": planned}


def _facts(group: AlertGroup, by_id: dict[str, Alert]) -> list[str]:
    alerts = [by_id[i] for i in group.alert_ids]
    facts = [
        f"{len(alerts)} alert(s) from {len(group.source_types)} source type(s): {', '.join(group.source_types)}",
        f"entity: {group.entity_kind} {group.entity_id}",
        f"first {_stamp(group.first_at)}, last {_stamp(group.last_at)}",
        f"categories: {', '.join(sorted({a.category for a in alerts}))}",
        f"highest severity: {group.severity}",
    ]
    if group.soc_case_ids:
        facts.append(f"external SOC case: {', '.join(group.soc_case_ids)}")
    return facts


def build_summary(
    client: str,
    alerts: Iterable[Alert],
    config: AlertsConfig,
    *,
    registry: Registry | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    after_hours_only: bool = False,
) -> dict[str, Any]:
    """The on-call summary for one client: groups by severity, the facts used, the read levers that would enrich them.

    Alert text appears only inside ``wrap_untrusted`` blocks (B43-2) and is withheld for flagged alerts. With
    ``after_hours_only`` a group is kept when its first alert fell outside business hours (the config's placeholder).
    """
    pool = pool_for(client, alerts, since=since, until=until)
    reg = registry if registry is not None else Registry.load()
    by_id = {a.id: a for a in pool.alerts}
    groups = group_alerts(pool, config)
    if after_hours_only:
        groups = tuple(g for g in groups if is_after_hours(g.first_at, config))
    out: list[dict[str, Any]] = []
    for g in groups:
        rows: list[dict[str, Any]] = []
        for alert_id in g.alert_ids:
            a = by_id[alert_id]
            withheld = alert_id in pool.flagged
            rows.append(
                {
                    "id": a.id,
                    "source_type": a.source_type,
                    "severity": a.severity,
                    "category": a.category,
                    "created_at": _stamp(a.created_at),
                    "text": None if withheld else wrap_untrusted("alert", f"{a.title}\n{a.description}"),
                    "text_withheld": withheld,
                }
            )
        out.append(
            {
                "id": g.id,
                "group_type": g.group_type,
                "severity": g.severity,
                "entity": {"kind": g.entity_kind, "id": g.entity_id},
                "source_types": list(g.source_types),
                "responder": g.responder,
                "soc_case_ids": list(g.soc_case_ids),
                "responder_note": (
                    f"The external SOC is the responder (case {', '.join(g.soc_case_ids)}); this program only "
                    "groups and enriches and does not contain or contradict the SOC."
                    if g.soc_case_ids
                    else "No external SOC case is recorded: on-call is the responder."
                ),
                "facts": _facts(g, by_id),
                "enrichment_levers": _enrichment(g.entity_kind, config, reg),
                "alerts": rows,
            }
        )
    return {
        "client": client,
        "window_minutes": config.window_minutes,
        "alert_count": len(pool.alerts),
        "group_count": len(out),
        "after_hours_only": after_hours_only,
        "needs_a_person_to_read": list(pool.flagged),
        "groups": out,
    }


def render_text(summary: dict[str, Any]) -> str:
    """The summary as plain text for a phone. Alert text is left out; the wrapped blocks live in the JSON form."""
    lines = [
        f"On-call alert summary for {summary['client']}: {summary['alert_count']} alert(s) in "
        f"{summary['group_count']} group(s)."
    ]
    for g in summary["groups"]:
        lines.append(
            f"- [{g['severity'].upper()}] {g['group_type']} on {g['entity']['kind']} {g['entity']['id']} "
            f"({len(g['alerts'])} alert(s); {', '.join(g['source_types'])}). {g['responder_note']}"
        )
        info = g["enrichment_levers"]
        if info["available"]:
            lines.append(f"    read levers to enrich: {', '.join(info['available'])}")
        if info["planned_not_built"]:
            lines.append(f"    not built yet: {', '.join(info['planned_not_built'])}")
    if summary["needs_a_person_to_read"]:
        lines.append("Text withheld, a person must read: " + ", ".join(summary["needs_a_person_to_read"]) + ".")
    return "\n".join(lines)


def utc(value: str) -> datetime:
    """Parse an ISO 8601 timestamp (``Z`` allowed) as UTC."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AlertsError(f"{value!r} is not an ISO 8601 timestamp") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
