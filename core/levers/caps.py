"""Blast-radius caps, client time windows and second reviews for the lever runner (B-42).

- Caps (HO-6): each write lever carries `caps` in the registry (targets per run, executes per client per hour,
  clients per day). A lever without its own gets the default for its risk class (`DEFAULT_CAPS`), so a new lever is
  never uncapped. `CapLedger` counts from the audit chains themselves, so the count survives a restart and is the
  same in the CLI and the page. A denied call is not an execute and is not counted.
- Windows (D6-08, RQ-13): `ClientRules` reads `business_hours`, `time_zone`, `maintenance_window` and
  `containment_preauthorized` from the client record. A client with no window, or one that does not parse, is
  refused, never defaulted. Public holidays are not modelled: a "business day" is a day listed in `business_hours`.
- Second reviews (D6-08): a contain-first action leaves a review that is due the end of the next business day.
  `SecondReviewStore` keeps them in `_reviews.jsonl` beside the audit chains; the last line for an id wins.

Client record keys (parsed here because schemas/client.schema.json does not know them yet):
    "time_zone": "America/Los_Angeles"            an IANA name, or a fixed offset such as "UTC-08:00"
    "business_hours": {"days": ["mon", ...], "start": "08:00", "end": "17:00"}
    "maintenance_window": {"days": ["sun"], "start": "22:00", "end": "02:00"}     may run past midnight
    "containment_preauthorized": true
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, StrictStr, StringConstraints, ValidationError

from core.audit.router import AuditRouter, file_lock
from core.levers.models import ClientId, LeverCaps, LeverDef, LeverName

REVIEWS_FILE = "_reviews.jsonl"
DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WINDOW_KEYS = {"business-hours": "business_hours", "maintenance": "maintenance_window"}
WINDOW_LABELS = {"business-hours": "business hours", "maintenance": "maintenance window"}

# Used when a write lever declares no caps of its own. Looser for low risk, tight for R3.
DEFAULT_CAPS: dict[str, LeverCaps] = {
    "R1": LeverCaps(targets_per_run=25, executes_per_client_per_hour=60, clients_per_day=50),
    "R2": LeverCaps(targets_per_run=10, executes_per_client_per_hour=30, clients_per_day=25),
    "R3": LeverCaps(targets_per_run=5, executes_per_client_per_hour=10, clients_per_day=10),
}
HOUR = timedelta(hours=1)


class CapError(RuntimeError):
    """The audit chains cannot be read to count executes; the runner denies the call (fail closed)."""


class ReviewError(RuntimeError):
    """The second-review file cannot be read or written."""


def caps_for(spec: LeverDef) -> tuple[LeverCaps, Literal["registry", "default"]]:
    """The caps that apply to `spec` and where they came from."""
    if spec.caps is not None:
        return spec.caps, "registry"
    return DEFAULT_CAPS[spec.risk_class or "R1"], "default"


def count_targets(params: Mapping[str, Any]) -> int:
    """Targets in one call: the length of the longest list parameter, else 1."""
    longest = max((len(v) for v in params.values() if isinstance(v, list | tuple | set | frozenset)), default=1)
    return max(1, longest)


# -- the ledger ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class CapDenial:
    reason: str
    detail: dict[str, Any]


def _parse_ts(stamp: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(stamp))
    except ValueError:
        return None


class CapLedger:
    """Counts executes from the audit chains: per client for the hour, per lever across clients for the day."""

    def __init__(self, audit: Any) -> None:
        self.audit = audit

    def _paths(self, client: str | None) -> list[Path]:
        if isinstance(self.audit, AuditRouter):
            return [self.audit.path_for(client)] if client is not None else list(self.audit.client_paths().values())
        return [Path(self.audit.path)]

    def _executes(
        self, lever: str, since: datetime, client: str | None, skip_idle: bool = False
    ) -> Iterator[tuple[str | None, datetime]]:
        needle = f'"lever":"{lever}"'.encode()
        for path in self._paths(client):
            try:
                if not path.exists() or (skip_idle and path.stat().st_mtime < since.timestamp()):
                    continue
                lines = path.read_bytes().splitlines()
            except OSError as exc:
                raise CapError(f"{path.name} cannot be read to count executes: {type(exc).__name__}") from exc
            for line in lines:
                if needle not in line:
                    continue
                try:
                    record = json.loads(line)
                    result = record["result"]
                    if record["mode"] != "execute" or result["status"] == "denied":
                        continue
                except (ValueError, KeyError, TypeError):
                    continue
                stamp = _parse_ts(record.get("ts"))
                if stamp is None or stamp < since or (client is not None and record.get("client") != client):
                    continue
                yield record.get("client"), stamp

    def executes_in_hour(self, lever: str, client: str, now: datetime) -> int:
        """Executes of `lever` for `client` in the hour up to `now` (later records count too)."""
        return sum(1 for _ in self._executes(lever, now - HOUR, client))

    def clients_today(self, lever: str, now: datetime) -> set[str]:
        """Clients `lever` has executed for since the start of `now`'s UTC day."""
        start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        return {c for c, _ in self._executes(lever, start, None, skip_idle=True) if c}

    def check(self, spec: LeverDef, client: str, params: Mapping[str, Any], now: datetime) -> CapDenial | None:
        """Why this execute would pass a cap (HO-6), or None. Reads the audit, so call it under the client lock."""
        caps, source = caps_for(spec)
        targets = count_targets(params)
        if targets > caps.targets_per_run:
            return self._denial(spec, "targets_per_run", caps.targets_per_run, source, f"{targets} targets in one run")
        done = self.executes_in_hour(spec.name, client, now)
        if done >= caps.executes_per_client_per_hour:
            return self._denial(
                spec,
                "executes_per_client_per_hour",
                caps.executes_per_client_per_hour,
                source,
                f"{done} executes for {client} in the last hour",
            )
        clients = self.clients_today(spec.name, now)
        if client not in clients and len(clients) >= caps.clients_per_day:
            return self._denial(
                spec, "clients_per_day", caps.clients_per_day, source, f"{len(clients)} clients already today"
            )
        return None

    @staticmethod
    def _denial(spec: LeverDef, cap: str, limit: int, source: str, seen: str) -> CapDenial:
        reason = f"{spec.name} cap {cap} = {limit} ({source}) reached: {seen} (HO-6)"
        return CapDenial(reason, {"kind": "cap-denied", "cap": cap, "limit": limit, "cap_source": source})


# -- client time windows ------------------------------------------------------------------------

_CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_OFFSET = re.compile(r"^UTC([+-])(\d{2}):(\d{2})$")


def parse_zone(name: Any) -> tzinfo:
    """An IANA time zone name, `UTC`, or a fixed `UTC+HH:MM` / `UTC-HH:MM`. Raises ValueError with a plain reason."""
    if not isinstance(name, str) or not name:
        raise ValueError("time_zone must be a name such as America/Los_Angeles or an offset such as UTC-08:00")
    if name == "UTC":
        return UTC
    offset = _OFFSET.fullmatch(name)
    if offset:
        hours, minutes = int(offset[2]), int(offset[3])
        if hours > 14 or minutes > 59:
            raise ValueError(f"time_zone {name!r} is not a valid offset")
        delta = timedelta(hours=hours, minutes=minutes)
        return timezone(-delta if offset[1] == "-" else delta)
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError(f"time_zone {name!r} is not known on this machine") from None


@dataclass(frozen=True)
class Window:
    """Days of the week and a daily start and end. An end before the start runs past midnight into the next day."""

    days: frozenset[int]
    start: time
    end: time

    @classmethod
    def parse(cls, raw: Any, overnight: bool) -> Window:
        if not isinstance(raw, Mapping) or set(raw) != {"days", "start", "end"}:
            raise ValueError('must be {"days": [...], "start": "HH:MM", "end": "HH:MM"}')
        days = raw["days"]
        known = isinstance(days, list) and all(isinstance(d, str) and d in DAY_NAMES for d in days)
        if not known or not days or len(set(days)) != len(days):
            raise ValueError(f"days must be a non-empty list of distinct names from {', '.join(DAY_NAMES)}")
        clock: list[time] = []
        for key in ("start", "end"):
            match = _CLOCK.fullmatch(raw[key]) if isinstance(raw[key], str) else None
            if match is None:
                raise ValueError(f"{key} must look like 08:00 (24-hour)")
            clock.append(time(int(match[1]), int(match[2])))
        start, end = clock
        if start == end:
            raise ValueError("start and end must differ")
        if end < start and not overnight:
            raise ValueError("end must be after start")
        return cls(frozenset(DAY_NAMES.index(d) for d in days), start, end)

    def contains(self, local: datetime) -> bool:
        at, today = local.time().replace(second=0, microsecond=0), local.weekday()
        if self.start < self.end:
            return today in self.days and self.start <= at < self.end
        return (today in self.days and at >= self.start) or ((today - 1) % 7 in self.days and at < self.end)


@dataclass(frozen=True)
class ClientRules:
    """What a client record says about time. Anything missing or invalid is kept as a reason and refused at use."""

    containment_preauthorized: bool = False
    zone: tzinfo | None = None
    windows: Mapping[str, Window] = field(default_factory=dict)
    problems: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> ClientRules:
        problems: dict[str, str] = {}
        zone: tzinfo | None = None
        windows: dict[str, Window] = {}
        if "time_zone" in record:
            try:
                zone = parse_zone(record["time_zone"])
            except ValueError as exc:
                problems["time_zone"] = str(exc)
        for kind, key in WINDOW_KEYS.items():
            if key in record:
                try:
                    windows[key] = Window.parse(record[key], overnight=kind == "maintenance")
                except ValueError as exc:
                    problems[key] = f"{key} {exc}"
        flag = record.get("containment_preauthorized", False)
        if type(flag) is not bool:
            raise ValueError("containment_preauthorized must be true or false")
        return cls(flag, zone, windows, problems)

    def window_refusal(self, kind: str, now: datetime) -> str:
        """Why a lever flagged `window: kind` may not run at `now`, or "" when it may. Never defaults a window."""
        key, label = WINDOW_KEYS[kind], WINDOW_LABELS[kind]
        for name in (key, "time_zone"):
            if name in self.problems:
                return f"client record: {self.problems[name]}; refused, not defaulted"
        window = self.windows.get(key)
        if window is None:
            return f"client has no {label} defined on its record; refused, not defaulted (D6-08)"
        if self.zone is None:
            return "client has no time_zone on its record; refused, not defaulted (D6-08)"
        local = now.astimezone(self.zone)
        if window.contains(local):
            return ""
        return f"outside the client's {label} (it is {local:%a %H:%M} there; D6-08)"

    def containment_blocker(self) -> str:
        """Why pre-authorized containment cannot be used for this client, or "" when it can."""
        if not self.containment_preauthorized:
            return "the client record does not set containment_preauthorized"
        for name in ("business_hours", "time_zone"):
            if name in self.problems:
                return f"client record: {self.problems[name]}"
        if "business_hours" not in self.windows or self.zone is None:
            return "the second review needs business_hours and time_zone on the client record"
        return ""

    def next_business_day_due(self, now: datetime) -> datetime:
        """The end of business hours on the first business day after `now`'s date there, in UTC."""
        window, zone = self.windows["business_hours"], self.zone
        assert zone is not None
        day: date = now.astimezone(zone).date()
        for _ in range(8):
            day += timedelta(days=1)
            if day.weekday() in window.days:
                return datetime.combine(day, window.end, tzinfo=zone).astimezone(UTC)
        raise ValueError("business_hours lists no day")


# -- second reviews -----------------------------------------------------------------------------

ReviewStatus = Literal["open", "completed", "void"]
SlugId = Annotated[str, StringConstraints(min_length=1, max_length=64)]


class Review(BaseModel):
    """One second-review item opened by a pre-authorized containment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Annotated[str, StringConstraints(pattern=r"^rev-[A-Za-z0-9-]{1,64}$")]
    client: ClientId
    lever: LeverName
    params: dict[str, StrictStr | int | bool]
    requester: SlugId
    on_call_approver: SlugId
    opened_at: AwareDatetime
    due: AwareDatetime
    status: ReviewStatus = "open"
    overdue_audited: bool = False
    completed_by: SlugId | None = None
    completed_at: AwareDatetime | None = None


class SecondReviewStore:
    """Reviews as locked-append JSON lines; the last line for an id wins."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()

    @classmethod
    def beside(cls, audit_path: Path) -> SecondReviewStore:
        return cls(Path(audit_path).resolve().with_name(REVIEWS_FILE))

    def all(self) -> dict[str, Review]:
        current: dict[str, Review] = {}
        if not self.path.exists():
            return current
        try:
            lines = self.path.read_bytes().splitlines()
        except OSError as exc:
            raise ReviewError(f"{self.path.name} cannot be read: {type(exc).__name__}") from exc
        for number, line in enumerate(lines, start=1):
            try:
                review = Review.model_validate_json(line)
            except ValidationError as exc:
                raise ReviewError(f"{self.path.name} line {number} is not a valid review") from exc
            current[review.id] = review
        return current

    def get(self, review_id: str) -> Review | None:
        return self.all().get(review_id)

    def open_reviews(self) -> list[Review]:
        return [r for r in self.all().values() if r.status == "open"]

    def overdue(self, now: datetime) -> list[Review]:
        return [r for r in self.open_reviews() if r.due <= now]

    def add(self, review: Review) -> Review:
        with file_lock(self.path):
            if review.id in self.all():
                raise ReviewError(f"review {review.id} already exists")
            self._write(review)
        return review

    def update(self, review_id: str, **changes: Any) -> Review:
        with file_lock(self.path):
            current = self.all().get(review_id)
            if current is None:
                raise ReviewError(f"no review {review_id!r}")
            updated = Review.model_validate({**current.model_dump(), **changes})
            self._write(updated)
        return updated

    def _write(self, review: Review) -> None:
        try:
            with self.path.open("ab") as fh:
                fh.write(review.model_dump_json().encode("utf-8") + b"\n")
                fh.flush()
        except OSError as exc:
            raise ReviewError(f"{self.path.name} cannot be written: {type(exc).__name__}") from exc
