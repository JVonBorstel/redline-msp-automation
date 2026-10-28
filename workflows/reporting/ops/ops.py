"""Operations metrics and Power BI exports (B-74, specs/B-74.md; W-RPT-06, W-SD-13, W-SD-14, W-TRN-03, W-TRN-04).

For one client, or for the whole MSP, this reads synthetic tickets and two synthetic overlays (first response and
reopen events, a mock CSAT-tool export) and writes flat CSV and JSON tables for Power BI, a data dictionary and a
manifest of SHA-256 hashes. It changes nothing: no ticket, PSA record or tenant, and it creates no problem record (it
only proposes one).

Isolation (TEN-04). Each client is loaded alone. An overlay row for a ticket that is not that client's refuses the
export before anything is written. A client export carries rows of that client only and no MSP-wide row.

Nobody is ranked (NN-03, W-TRN-04). The ticket's technician field is never read, so no table can carry it, and
``assert_no_person_columns`` refuses any table whose column name looks like a person.

Untrusted text (C-12). Subject, body and CSAT comments are matched against plain word lists and never copied into an
export. A ticket the injection detector flags stays in the counts but is left out of problem clusters.

Every figure is fixture-based and says so (the ``data_basis`` column, the manifest label). No model is called.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import statistics
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from core.guard.classify import DataClass
from core.paths import REPO_ROOT
from workflows.duplicates import DupTicket, classify, load_config, pool_for
from workflows.duplicates.duplicates import DuplicateConfig

DEFAULT_TICKETS_DIR = REPO_ROOT / "fixtures" / "tickets"
DEFAULT_PSA_DIR = REPO_ROOT / "fixtures" / "psa"
DEFAULT_DATA_DIR = Path(__file__).with_name("data")
DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.json")
DEFAULT_OUT_DIR = REPO_ROOT / "build" / "ops-metrics"
MSP_SCOPE = "_msp"
DATA_BASIS = "fixture-based"
LABEL = (
    "fixture-based, synthetic (invented tenants and tickets, not real service-desk results); hours are wall-clock "
    "and the SLA targets are stand-ins (UNVERIFIED)"
)
DATA_CLASS = f"DC-{DataClass.DC2.value}"
CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Column names that look like a person. Exports are never per person (NN-03).
_PERSON = re.compile(
    r"tech|assign|resource|owner|engineer|agent|staff|employee|analyst|requester|email|person|worker", re.I
)
UNCATEGORISED = "uncategorised"
OTHER_THEME = "other"


class OpsError(ValueError):
    """The input is bad (client, date, fixture, overlay); nothing was written."""


class VerifyError(ValueError):
    """An export folder does not match its manifest."""


# -- table schemas (one place: the files and the data dictionary are both built from it) ---------------------------


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    type: str
    unit: str
    description: str
    source: str


def _c(name: str, type_: str, unit: str, description: str, source: str) -> Column:
    return Column(name, type_, unit, description, source)


_CLIENT = _c("client", "text", "", "Client id (invented tenant). Join key to every other table.", "ticket file")
_BASIS = _c(
    "data_basis", "text", "", "Always 'fixture-based': synthetic figures, not real service-desk results.", "constant"
)
_WEEK = "Monday (UTC date) of the week"

TABLES: dict[str, tuple[Column, ...]] = {
    "ticket_facts": (
        _CLIENT,
        _c("ticket_id", "text", "", "Ticket id, T-nnnn. Key of this table.", "ticket file"),
        _c("created_date", "date", "", "UTC date the ticket was created.", "ticket file"),
        _c("week_start", "date", "", f"{_WEEK} the ticket was created.", "derived"),
        _c("channel", "text", "", "How the ticket came in (portal, phone, email).", "ticket file"),
        _c(
            "status",
            "text",
            "",
            "Ticket status at as_of (new, in-progress, waiting-client, waiting-vendor, resolved).",
            "ticket file",
        ),
        _c(
            "category",
            "text",
            "",
            "Category of the best-matching B-23 topic, or 'uncategorised'. From words, not labels.",
            "derived",
        ),
        _c("topic", "text", "", "Best-matching B-23 topic id, empty when none.", "derived"),
        _c(
            "first_response_hours",
            "decimal",
            "hours",
            "First response time minus created time; empty when no response yet.",
            "events overlay",
        ),
        _c(
            "completed_hours",
            "decimal",
            "hours",
            "Completed time minus created time. Completed is the ticket's updated time when status "
            "is resolved (stand-in for the PSA completed date); empty otherwise.",
            "ticket file",
        ),
        _c(
            "user_confirmed_working_hours",
            "decimal",
            "hours",
            "Time until the person said they can work again: PROPOSED 'user confirmed working' "
            "field minus created time. Empty when not recorded or not resolved.",
            "events overlay",
        ),
        _c(
            "sla_first_response_met",
            "0/1",
            "",
            "1 when first_response_hours is within the client's SLA "
            "first-response target; empty without a response or an SLA.",
            "derived",
        ),
        _c(
            "sla_resolution_met",
            "0/1",
            "",
            "1 when completed_hours is within the client's SLA resolution target; empty when not resolved or no SLA.",
            "derived",
        ),
        _c("reopen_count", "integer", "count", "Times the ticket was reopened after being resolved.", "events overlay"),
        _c(
            "csat_score",
            "integer",
            "1-5",
            "Score from the mock CSAT-tool export; empty when no answer by as_of.",
            "csat overlay",
        ),
        _c(
            "csat_theme",
            "text",
            "",
            "Theme of the CSAT comment (word list), 'other' when none matches; the comment itself is never exported.",
            "derived",
        ),
        _BASIS,
    ),
    "weekly_metrics": (
        _CLIENT,
        _c("week_start", "date", "", f"{_WEEK} tickets were created (cohort basis).", "derived"),
        _c("tickets_created", "integer", "count", "Tickets created that week.", "ticket file"),
        _c("resolved", "integer", "count", "Of those, tickets with status resolved at as_of.", "ticket file"),
        _c("reopened", "integer", "count", "Of those, tickets reopened at least once.", "events overlay"),
        _c(
            "mean_first_response_hours",
            "decimal",
            "hours",
            "Mean first response time; empty when none.",
            "events overlay",
        ),
        _c(
            "mean_completed_hours",
            "decimal",
            "hours",
            "Mean created-to-completed time of resolved tickets; empty when none.",
            "ticket file",
        ),
        _BASIS,
    ),
    "summary": (
        _CLIENT,
        _c(
            "tickets",
            "integer",
            "count",
            "Tickets created up to as_of. The client 'ALL' (MSP export only) pools every client.",
            "ticket file",
        ),
        _c("open", "integer", "count", "Tickets not resolved.", "ticket file"),
        _c("resolved", "integer", "count", "Tickets with status resolved.", "ticket file"),
        _c("with_first_response", "integer", "count", "Tickets that have a first response.", "events overlay"),
        _c("mean_first_response_hours", "decimal", "hours", "Mean time to first response.", "events overlay"),
        _c("median_first_response_hours", "decimal", "hours", "Median time to first response.", "events overlay"),
        _c("mean_completed_hours", "decimal", "hours", "Mean time to resolution (resolved tickets).", "ticket file"),
        _c(
            "median_completed_hours", "decimal", "hours", "Median time to resolution (resolved tickets).", "ticket file"
        ),
        _c(
            "sla_status",
            "text",
            "",
            "'ok', or 'no-sla' when the client has no single active SLA in its PSA mock (SLA cells are then empty). "
            "For ALL: 'ok' when at least one client has an SLA, and ALL's SLA figures cover only those clients.",
            "psa mock",
        ),
        _c(
            "sla_first_response_checked",
            "integer",
            "count",
            "Tickets with a first response, checked against the SLA.",
            "derived",
        ),
        _c("sla_first_response_met", "integer", "count", "Of those, within the SLA first-response target.", "derived"),
        _c("sla_first_response_attainment", "decimal", "ratio 0-1", "met / checked.", "derived"),
        _c("sla_resolution_checked", "integer", "count", "Resolved tickets, checked against the SLA.", "derived"),
        _c("sla_resolution_met", "integer", "count", "Of those, within the SLA resolution target.", "derived"),
        _c("sla_resolution_attainment", "decimal", "ratio 0-1", "met / checked.", "derived"),
        _c("reopened", "integer", "count", "Tickets reopened at least once.", "events overlay"),
        _c(
            "ever_resolved",
            "integer",
            "count",
            "Tickets resolved now or reopened (they were resolved once).",
            "derived",
        ),
        _c("reopen_rate", "decimal", "ratio 0-1", "reopened / ever_resolved.", "derived"),
        _c("csat_responses", "integer", "count", "CSAT answers submitted by as_of.", "csat overlay"),
        _c("csat_mean", "decimal", "score 1-5", "Mean CSAT score.", "csat overlay"),
        _c("csat_response_rate", "decimal", "ratio", "csat_responses / resolved tickets.", "derived"),
        _c(
            "problem_clusters", "integer", "count", "Repeat-problem clusters with a proposed problem record.", "derived"
        ),
        _BASIS,
    ),
    "volume_by_category": (
        _CLIENT,
        _c("category", "text", "", "Ticket category (see ticket_facts.category).", "derived"),
        _c("tickets", "integer", "count", "Tickets in the category.", "ticket file"),
        _c("resolved", "integer", "count", "Resolved tickets in the category.", "ticket file"),
        _c("open", "integer", "count", "Tickets in the category not resolved.", "ticket file"),
        _BASIS,
    ),
    "problem_clusters": (
        _CLIENT,
        _c("cluster_id", "text", "", "CL-<client>-<topic>. Key of this table.", "derived"),
        _c("topic", "text", "", "B-23 topic id the tickets share.", "derived"),
        _c("category", "text", "", "Category of the topic.", "derived"),
        _c("tickets", "integer", "count", "Tickets in the cluster (resolved included).", "ticket file"),
        _c("resolved_tickets", "integer", "count", "Of those, resolved.", "ticket file"),
        _c(
            "distinct_askers",
            "integer",
            "count",
            "Different people who raised them (a count, never names).",
            "ticket file",
        ),
        _c("first_created", "date", "", "UTC date of the earliest ticket.", "ticket file"),
        _c("last_created", "date", "", "UTC date of the latest ticket.", "ticket file"),
        _c(
            "proposed_problem_id",
            "text",
            "",
            "PROPOSED problem record id, PRB-PROPOSED-<client>-<topic>. Nothing creates it.",
            "derived",
        ),
        _c("proposed_title", "text", "", "PROPOSED problem title, built from the topic id.", "derived"),
        _c("root_cause", "text", "", "Always empty: a person finds the cause.", "constant"),
        _c("status", "text", "", "Always 'proposed'.", "constant"),
        _BASIS,
    ),
    "problem_cluster_tickets": (
        _CLIENT,
        _c("cluster_id", "text", "", "Join to problem_clusters.cluster_id.", "derived"),
        _c("ticket_id", "text", "", "Join to ticket_facts.ticket_id.", "ticket file"),
        _BASIS,
    ),
    "csat_weekly": (
        _CLIENT,
        _c("week_start", "date", "", f"{_WEEK} the answer was submitted.", "csat overlay"),
        _c("responses", "integer", "count", "CSAT answers that week.", "csat overlay"),
        _c("mean_score", "decimal", "score 1-5", "Mean score.", "csat overlay"),
        _c("satisfied_share", "decimal", "ratio 0-1", "Share of answers scoring 4 or 5.", "csat overlay"),
        _BASIS,
    ),
    "csat_themes": (
        _CLIENT,
        _c("theme", "text", "", "Theme of the comment (word list in config.json), or 'other'.", "derived"),
        _c("responses", "integer", "count", "Answers with that theme.", "csat overlay"),
        _c("mean_score", "decimal", "score 1-5", "Mean score of those answers.", "csat overlay"),
        _BASIS,
    ),
}
DICTIONARY_COLUMNS = ("table", "column", "type", "unit", "description", "source")


def assert_no_person_columns(table: str, columns: Sequence[str]) -> None:
    """Refuse a table with a column that looks like a technician or any other person (NN-03, B74-3)."""
    for name in columns:
        if _PERSON.search(name):
            raise OpsError(f"table {table}: column {name!r} looks like a person column; exports are never per person")


for _name, _cols in TABLES.items():
    assert_no_person_columns(_name, [c.name for c in _cols])


# -- small helpers ------------------------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalised(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def _shown(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return f"{path.parent.name}/{path.name}"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OpsError(f"cannot read {path.name}: {exc}") from exc


def _time(value: object, what: str) -> datetime:
    if not isinstance(value, str):
        raise OpsError(f"{what}: time must be an ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise OpsError(f"{what}: cannot read time {value!r}") from exc
    if parsed.tzinfo is None:
        raise OpsError(f"{what}: time must be UTC (end with Z)")
    return parsed.astimezone(UTC)


def _end_of(as_of: str) -> datetime:
    if not isinstance(as_of, str) or not _DATE.match(as_of):
        raise OpsError(f"as_of must be an ISO date (YYYY-MM-DD), got {as_of!r}")
    try:
        day = date.fromisoformat(as_of)
    except ValueError:
        raise OpsError(f"as_of must be an ISO date (YYYY-MM-DD), got {as_of!r}") from None
    return datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(days=1)


def _week(moment: datetime) -> str:
    day = moment.date()
    return (day - timedelta(days=day.weekday())).isoformat()


def _hours(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 3600


def _round(value: float | None, places: int = 2) -> float | None:
    return None if value is None else round(value, places)


def _mean(values: Sequence[float]) -> float | None:
    return round(statistics.fmean(values), 2) if values else None


def _median(values: Sequence[float]) -> float | None:
    return round(statistics.median(values), 2) if values else None


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


# -- per-client loading ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Fact:
    """One ticket's metrics. Hours are unrounded here; rows round them. No technician, no requester."""

    ticket_id: str
    created: datetime
    channel: str
    status: str
    category: str
    topic: str
    first_response: float | None
    completed: float | None
    working: float | None
    reopen_count: int
    csat_score: int | None
    csat_theme: str | None


@dataclass(frozen=True, slots=True)
class Cluster:
    topic: str
    category: str
    ticket_ids: tuple[str, ...]
    resolved: int
    requesters: int
    first: datetime
    last: datetime


@dataclass(frozen=True, slots=True)
class ClientData:
    client: str
    facts: tuple[Fact, ...]
    csat: tuple[tuple[datetime, int, str], ...]  # submitted, score, theme (comment text is dropped here)
    clusters: tuple[Cluster, ...]
    sla: tuple[float, float] | None
    sources: tuple[Path, ...]


def _load_config(path: Path) -> dict[str, Any]:
    doc = _read_json(path)
    try:
        return {
            "min_tickets": int(doc["cluster_min_tickets"]),
            "min_requesters": int(doc["cluster_min_requesters"]),
            "satisfied": int(doc["satisfied_min_score"]),
            "themes": [(str(t["id"]), [str(w).lower() for w in t["words"]]) for t in doc["csat_themes"]],
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise OpsError(f"bad ops config {path.name}: {exc}") from exc


def _theme(comment: str, themes: list[tuple[str, list[str]]]) -> str:
    low = comment.lower()
    for theme_id, words in themes:
        if any(word in low for word in words):
            return theme_id
    return OTHER_THEME


def _single_sla(psa_path: Path, client: str) -> tuple[float, float] | None:
    if not psa_path.is_file():
        return None
    doc = _read_json(psa_path)
    if doc.get("client") != client:
        raise OpsError(f"{psa_path.name}: client mismatch")
    active = [s for s in doc.get("slaSettings", []) if isinstance(s, dict) and s.get("isActive")]
    if len(active) != 1:
        return None
    try:
        return float(active[0]["firstResponseHours"]), float(active[0]["resolutionHours"])
    except (KeyError, TypeError, ValueError) as exc:
        raise OpsError(f"{psa_path.name}: bad SLA settings: {exc}") from exc


def _overlay(path: Path, client: str, key: str, own_ids: set[str]) -> list[dict[str, Any]]:
    doc = _read_json(path)
    if doc.get("client") != client or not isinstance(doc.get(key), list):
        raise OpsError(f"{path.name}: not a {client} overlay file (client mismatch)")
    seen: set[str] = set()
    for row in doc[key]:
        tid = row.get("ticket_id") if isinstance(row, dict) else None
        if tid not in own_ids:
            raise OpsError(f"{path.name}: ticket {tid!r} is not this client's ({client}); export refused")
        if tid in seen:
            raise OpsError(f"{path.name}: ticket {tid} appears twice")
        seen.add(tid)
    return list(doc[key])


def _is_dated(path: Path) -> bool:
    """A ticket file whose tickets carry created times (the older files without them cannot be measured)."""
    try:
        tickets = json.loads(path.read_text(encoding="utf-8")).get("tickets")
    except (OSError, ValueError, AttributeError):
        return False
    return isinstance(tickets, list) and bool(tickets) and all(isinstance(t, dict) and "created" in t for t in tickets)


def _ticket_file(root: Path, client: str) -> Path:
    found = [p for p in sorted(Path(root).rglob(f"{client}.json")) if _is_dated(p)]
    if len(found) != 1:
        raise OpsError(f"expected one dated ticket file for client {client!r} under {root}, found {len(found)}")
    return found[0]


def _client_names(root: Path) -> list[str]:
    return sorted({p.stem for p in Path(root).rglob("*.json") if _is_dated(p)})


def _load_client(
    client: str, end: datetime, tickets_dir: Path, psa_dir: Path, data_dir: Path, cfg_path: Path
) -> ClientData:
    if not CLIENT_ID.fullmatch(client):
        raise OpsError(f"invalid client id {client!r}")
    ops_cfg = _load_config(cfg_path)
    dup_cfg: DuplicateConfig = load_config()
    ticket_path = _ticket_file(tickets_dir, client)
    doc = _read_json(ticket_path)
    if doc.get("client") != client or not isinstance(doc.get("tickets"), list):
        raise OpsError(f"{ticket_path.name}: client mismatch (expected {client})")
    raws: dict[str, dict[str, Any]] = {}
    for raw in doc["tickets"]:
        if raw.get("client") != client:
            raise OpsError(f"{ticket_path.name}: ticket {raw.get('id')} has a different client")
        if raw["id"] in raws:
            raise OpsError(f"{ticket_path.name}: duplicate ticket id {raw['id']}")
        raws[raw["id"]] = raw
    events = {
        row["ticket_id"]: row for row in _overlay(data_dir / f"{client}.events.json", client, "events", set(raws))
    }
    answers = {
        row["ticket_id"]: row for row in _overlay(data_dir / f"{client}.csat.json", client, "responses", set(raws))
    }
    try:
        parsed = {tid: DupTicket.model_validate(raw) for tid, raw in raws.items()}
    except ValidationError as exc:
        raise OpsError(f"{ticket_path.name}: bad ticket: {exc}") from exc
    kept = {tid: t for tid, t in parsed.items() if t.created < end}
    facts: list[Fact] = []
    csat: list[tuple[datetime, int, str]] = []
    for tid in sorted(kept):
        t = kept[tid]
        hit = classify(t, dup_cfg)
        ev = events.get(tid, {})
        first = _optional_hours(ev.get("first_response_at"), t.created, f"{tid} first_response_at")
        resolved = t.status == "resolved"
        completed = _hours(t.created, t.updated) if resolved else None
        working = _optional_hours(ev.get("user_confirmed_working_at"), t.created, f"{tid} user_confirmed_working_at")
        if completed is not None and completed < 0:
            raise OpsError(f"{tid}: updated is before created")
        if working is not None:
            if completed is None:
                working = None  # only a resolved ticket has a confirmed-working time
            elif working < completed:
                raise OpsError(f"{tid}: user_confirmed_working_at is before the ticket was completed")
        score: int | None = None
        theme: str | None = None
        answer = answers.get(tid)
        if answer is not None:
            submitted = _time(answer.get("submitted_at"), f"{tid} submitted_at")
            value = answer.get("score")
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5:
                raise OpsError(f"{tid}: CSAT score must be an integer 1-5")
            if submitted < end:
                score = value
                theme = _theme(str(answer.get("comment", "")), ops_cfg["themes"])
                csat.append((submitted, value, theme))
        reopen = ev.get("reopen_count", 0)
        if not isinstance(reopen, int) or isinstance(reopen, bool) or reopen < 0:
            raise OpsError(f"{tid}: reopen_count must be a non-negative integer")
        facts.append(
            Fact(
                tid,
                t.created,
                str(raws[tid].get("source", "")),
                t.status,
                hit.category if hit else UNCATEGORISED,
                hit.topic if hit else "",
                first,
                completed,
                working,
                reopen,
                score,
                theme,
            )
        )
    pool = pool_for(client, kept.values(), open_only=False)
    by_topic: dict[str, list[DupTicket]] = defaultdict(list)
    topic_category: dict[str, str] = {}
    for t in pool.tickets:
        hit = classify(t, dup_cfg)
        if hit:
            by_topic[hit.topic].append(t)
            topic_category[hit.topic] = hit.category
    clusters = tuple(
        Cluster(
            topic,
            topic_category[topic],
            tuple(sorted(i.id for i in items)),
            sum(i.status == "resolved" for i in items),
            len({i.requester.lower() for i in items}),
            min(i.created for i in items),
            max(i.created for i in items),
        )
        for topic, items in sorted(by_topic.items())
        if len(items) >= ops_cfg["min_tickets"]
        and len({i.requester.lower() for i in items}) >= ops_cfg["min_requesters"]
    )
    psa_path = psa_dir / f"{client}.json"
    sources = [ticket_path, data_dir / f"{client}.events.json", data_dir / f"{client}.csat.json", cfg_path]
    if psa_path.is_file():
        sources.append(psa_path)
    return ClientData(client, tuple(facts), tuple(csat), clusters, _single_sla(psa_path, client), tuple(sources))


def _optional_hours(value: object, created: datetime, what: str) -> float | None:
    if value is None:
        return None
    hours = _hours(created, _time(value, what))
    if hours < 0:
        raise OpsError(f"{what} is before the ticket was created")
    return hours


# -- metrics ------------------------------------------------------------------------------------------------


def _sla_flag(hours: float | None, limit: float | None) -> int | None:
    return None if hours is None or limit is None else int(hours <= limit)


def _fact_row(client: str, f: Fact, sla: tuple[float, float] | None) -> dict[str, Any]:
    first_limit, done_limit = (sla[0], sla[1]) if sla else (None, None)
    return {
        "client": client,
        "ticket_id": f.ticket_id,
        "created_date": f.created.date().isoformat(),
        "week_start": _week(f.created),
        "channel": f.channel,
        "status": f.status,
        "category": f.category,
        "topic": f.topic,
        "first_response_hours": _round(f.first_response),
        "completed_hours": _round(f.completed),
        "user_confirmed_working_hours": _round(f.working),
        "sla_first_response_met": _sla_flag(f.first_response, first_limit),
        "sla_resolution_met": _sla_flag(f.completed, done_limit),
        "reopen_count": f.reopen_count,
        "csat_score": f.csat_score,
        "csat_theme": f.csat_theme,
        "data_basis": DATA_BASIS,
    }


def _summary_row(
    label: str,
    facts: Sequence[Fact],
    csat: Sequence[tuple[datetime, int, str]],
    clusters: int,
    sla_of: dict[str, tuple[float, float] | None],
    owner: dict[str, str],
) -> dict[str, Any]:
    firsts = [f.first_response for f in facts if f.first_response is not None]
    dones = [f.completed for f in facts if f.completed is not None]
    resolved = sum(f.status == "resolved" for f in facts)
    reopened = sum(f.reopen_count >= 1 for f in facts)
    ever = sum(f.status == "resolved" or f.reopen_count >= 1 for f in facts)
    first_checked: list[bool] = []
    done_checked: list[bool] = []
    for f in facts:
        sla = sla_of[owner[f.ticket_id]]
        if sla is None:
            continue
        if f.first_response is not None:
            first_checked.append(f.first_response <= sla[0])
        if f.completed is not None:
            done_checked.append(f.completed <= sla[1])
    has_sla = any(sla_of[c] is not None for c in set(owner.values()))
    scores = [s for _, s, _ in csat]

    def count(flags: list[bool]) -> int | None:
        return len(flags) if has_sla else None

    def met(flags: list[bool]) -> int | None:
        return sum(flags) if has_sla else None

    return {
        "client": label,
        "tickets": len(facts),
        "open": len(facts) - resolved,
        "resolved": resolved,
        "with_first_response": len(firsts),
        "mean_first_response_hours": _mean(firsts),
        "median_first_response_hours": _median(firsts),
        "mean_completed_hours": _mean(dones),
        "median_completed_hours": _median(dones),
        "sla_status": "ok" if has_sla else "no-sla",
        "sla_first_response_checked": count(first_checked),
        "sla_first_response_met": met(first_checked),
        "sla_first_response_attainment": _ratio(sum(first_checked), len(first_checked)) if has_sla else None,
        "sla_resolution_checked": count(done_checked),
        "sla_resolution_met": met(done_checked),
        "sla_resolution_attainment": _ratio(sum(done_checked), len(done_checked)) if has_sla else None,
        "reopened": reopened,
        "ever_resolved": ever,
        "reopen_rate": _ratio(reopened, ever),
        "csat_responses": len(scores),
        "csat_mean": _mean(scores),
        "csat_response_rate": _ratio(len(scores), resolved),
        "problem_clusters": clusters,
        "data_basis": DATA_BASIS,
    }


def _client_tables(data: ClientData, satisfied_min: int) -> dict[str, list[dict[str, Any]]]:
    client = data.client
    owner = {f.ticket_id: client for f in data.facts}
    sla_of = {client: data.sla}
    weekly: dict[str, list[Fact]] = defaultdict(list)
    by_category: dict[str, list[Fact]] = defaultdict(list)
    for f in data.facts:
        weekly[_week(f.created)].append(f)
        by_category[f.category].append(f)
    csat_weeks: dict[str, list[int]] = defaultdict(list)
    csat_themes: dict[str, list[int]] = defaultdict(list)
    for submitted, score, theme in data.csat:
        csat_weeks[_week(submitted)].append(score)
        csat_themes[theme].append(score)
    theme_order = [t for t in csat_themes]
    return {
        "ticket_facts": [_fact_row(client, f, data.sla) for f in data.facts],
        "weekly_metrics": [
            {
                "client": client,
                "week_start": week,
                "tickets_created": len(items),
                "resolved": sum(f.status == "resolved" for f in items),
                "reopened": sum(f.reopen_count >= 1 for f in items),
                "mean_first_response_hours": _mean([f.first_response for f in items if f.first_response is not None]),
                "mean_completed_hours": _mean([f.completed for f in items if f.completed is not None]),
                "data_basis": DATA_BASIS,
            }
            for week, items in sorted(weekly.items())
        ],
        "summary": [_summary_row(client, data.facts, data.csat, len(data.clusters), sla_of, owner)],
        "volume_by_category": [
            {
                "client": client,
                "category": category,
                "tickets": len(items),
                "resolved": sum(f.status == "resolved" for f in items),
                "open": sum(f.status != "resolved" for f in items),
                "data_basis": DATA_BASIS,
            }
            for category, items in sorted(by_category.items())
        ],
        "problem_clusters": [
            {
                "client": client,
                "cluster_id": f"CL-{client}-{c.topic}",
                "topic": c.topic,
                "category": c.category,
                "tickets": len(c.ticket_ids),
                "resolved_tickets": c.resolved,
                "distinct_askers": c.requesters,
                "first_created": c.first.date().isoformat(),
                "last_created": c.last.date().isoformat(),
                "proposed_problem_id": f"PRB-PROPOSED-{client}-{c.topic}",
                "proposed_title": f"Recurring {c.topic.replace('-', ' ')} issues ({c.category})",
                "root_cause": "",
                "status": "proposed",
                "data_basis": DATA_BASIS,
            }
            for c in data.clusters
        ],
        "problem_cluster_tickets": [
            {"client": client, "cluster_id": f"CL-{client}-{c.topic}", "ticket_id": tid, "data_basis": DATA_BASIS}
            for c in data.clusters
            for tid in c.ticket_ids
        ],
        "csat_weekly": [
            {
                "client": client,
                "week_start": week,
                "responses": len(scores),
                "mean_score": _mean(scores),
                "satisfied_share": _ratio(sum(s >= satisfied_min for s in scores), len(scores)),
                "data_basis": DATA_BASIS,
            }
            for week, scores in sorted(csat_weeks.items())
        ],
        "csat_themes": [
            {
                "client": client,
                "theme": theme,
                "responses": len(csat_themes[theme]),
                "mean_score": _mean(csat_themes[theme]),
                "data_basis": DATA_BASIS,
            }
            for theme in theme_order
        ],
    }


# -- files --------------------------------------------------------------------------------------------------


def _csv_bytes(columns: Sequence[str], rows: Sequence[dict[str, Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if row[c] is None else str(row[c]) for c in columns])
    return buffer.getvalue().encode("utf-8")


def _json_bytes(columns: Sequence[str], rows: Sequence[dict[str, Any]]) -> bytes:
    flat = [{c: row[c] for c in columns} for row in rows]
    return (json.dumps(flat, indent=1, ensure_ascii=True) + "\n").encode("ascii")


def _files_for(tables: dict[str, list[dict[str, Any]]]) -> dict[str, tuple[bytes, int]]:
    """Every table plus the dictionary as {file name: (bytes, row count)}. Checks the shape first."""
    files: dict[str, tuple[bytes, int]] = {}
    for name, columns in TABLES.items():
        names = [c.name for c in columns]
        assert_no_person_columns(name, names)
        rows = tables.get(name, [])
        for row in rows:
            if list(row) != names:
                raise OpsError(f"table {name}: row does not match the schema")
        files[f"{name}.csv"] = (_csv_bytes(names, rows), len(rows))
        files[f"{name}.json"] = (_json_bytes(names, rows), len(rows))
    dictionary = [
        dict(zip(DICTIONARY_COLUMNS, (table, c.name, c.type, c.unit, c.description, c.source), strict=True))
        for table, columns in TABLES.items()
        for c in columns
    ]
    files["data_dictionary.csv"] = (_csv_bytes(DICTIONARY_COLUMNS, dictionary), len(dictionary))
    files["data_dictionary.json"] = (_json_bytes(DICTIONARY_COLUMNS, dictionary), len(dictionary))
    return files


def _manifest(scope: str, as_of: str, files: dict[str, tuple[bytes, int]], sources: Sequence[Path]) -> bytes:
    body = {
        "kind": "ops-metrics-export",
        "version": 1,
        "scope": scope,
        "as_of": as_of,
        "label": LABEL,
        "data_class": DATA_CLASS,
        "files": [
            {"path": name, "sha256": _sha256(data), "rows": rows} for name, (data, rows) in sorted(files.items())
        ],
        "sources": sorted(
            ({"path": _shown(p), "sha256": _sha256(_normalised(p))} for p in set(sources)), key=lambda s: s["path"]
        ),
    }
    return (json.dumps(body, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def _write(
    folder: Path, scope: str, as_of: str, tables: dict[str, list[dict[str, Any]]], sources: Sequence[Path]
) -> Path:
    files = _files_for(tables)
    manifest = _manifest(scope, as_of, files, sources)
    folder.mkdir(parents=True, exist_ok=True)
    for name, (data, _) in files.items():
        (folder / name).write_bytes(data)
    (folder / "manifest.json").write_bytes(manifest)
    # sha256sum format, so `sha256sum -c` or Get-FileHash re-checks it without this code.
    (folder / "manifest.json.sha256").write_text(
        f"{_sha256(manifest)}  manifest.json\n", encoding="ascii", newline="\n"
    )
    return folder


# -- entry points -------------------------------------------------------------------------------------------


def export_client(
    client: str,
    as_of: str,
    out_dir: Path = DEFAULT_OUT_DIR,
    *,
    tickets_dir: Path = DEFAULT_TICKETS_DIR,
    psa_dir: Path = DEFAULT_PSA_DIR,
    data_dir: Path = DEFAULT_DATA_DIR,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> Path:
    """Write ``<out_dir>/<client>/``: only that client's rows. Returns the folder."""
    end = _end_of(as_of)
    data = _load_client(client, end, tickets_dir, psa_dir, data_dir, config_path)
    tables = _client_tables(data, _load_config(config_path)["satisfied"])
    return _write(Path(out_dir) / client, client, as_of, tables, data.sources)


def export_msp(
    as_of: str,
    out_dir: Path = DEFAULT_OUT_DIR,
    *,
    clients: Sequence[str] | None = None,
    tickets_dir: Path = DEFAULT_TICKETS_DIR,
    psa_dir: Path = DEFAULT_PSA_DIR,
    data_dir: Path = DEFAULT_DATA_DIR,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> Path:
    """Write ``<out_dir>/_msp/``: every client's rows plus an ``ALL`` summary row. Returns the folder."""
    end = _end_of(as_of)
    names = list(clients) if clients is not None else _client_names(tickets_dir)
    if not names:
        raise OpsError(f"no ticket fixtures in {tickets_dir}")
    satisfied = _load_config(config_path)["satisfied"]
    loaded = [_load_client(c, end, tickets_dir, psa_dir, data_dir, config_path) for c in names]
    merged: dict[str, list[dict[str, Any]]] = {name: [] for name in TABLES}
    for data in loaded:
        for name, rows in _client_tables(data, satisfied).items():
            merged[name].extend(rows)
    facts = [f for d in loaded for f in d.facts]
    owner = {f.ticket_id: d.client for d in loaded for f in d.facts}
    if len(owner) != len(facts):
        raise OpsError("a ticket id appears in more than one client")
    all_row = _summary_row(
        "ALL",
        facts,
        [c for d in loaded for c in d.csat],
        sum(len(d.clusters) for d in loaded),
        {d.client: d.sla for d in loaded},
        owner,
    )
    merged["summary"].append(all_row)
    return _write(Path(out_dir) / MSP_SCOPE, MSP_SCOPE, as_of, merged, [p for d in loaded for p in d.sources])


def verify(folder: Path) -> str:
    """Re-hash every file against the manifest and the manifest against its sidecar. Returns the manifest's SHA-256."""
    folder = Path(folder)
    try:
        manifest_bytes = (folder / "manifest.json").read_bytes()
        sidecar = (folder / "manifest.json.sha256").read_text(encoding="ascii").split()
        manifest = json.loads(manifest_bytes)
    except (OSError, ValueError) as exc:
        raise VerifyError(f"{folder}: cannot read manifest or sidecar: {exc}") from exc
    digest = _sha256(manifest_bytes)
    if sidecar != [digest, "manifest.json"]:
        raise VerifyError(f"{folder}: manifest.json does not match its .sha256 (got {digest})")
    listed = {entry["path"]: entry["sha256"] for entry in manifest.get("files", [])}
    present = {p.name for p in folder.iterdir() if p.is_file()} - {"manifest.json", "manifest.json.sha256"}
    if present != set(listed):
        raise VerifyError(f"{folder}: files differ from the manifest: {sorted(present ^ set(listed))}")
    for name, expected in listed.items():
        if _sha256((folder / name).read_bytes()) != expected:
            raise VerifyError(f"{folder / name}: hash does not match the manifest")
    return digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m workflows.reporting.ops", description="Operations metrics export.")
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export", help="write a client export (or --msp) with data dictionary and manifest")
    exp.add_argument("client", nargs="?", help="client id, e.g. contoso-dental")
    exp.add_argument("--msp", action="store_true", help="every client plus an ALL summary row")
    exp.add_argument("--as-of", required=True, help="ISO date (YYYY-MM-DD); the wall clock is never read")
    exp.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    ver = sub.add_parser("verify", help="re-hash an export folder against its manifest")
    ver.add_argument("folder", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            try:
                digest = verify(args.folder)
            except VerifyError as exc:
                print(f"MISMATCH: {exc}", file=sys.stderr)
                return 1
            print(f"ok {digest}")
            return 0
        if args.msp == bool(args.client):
            raise OpsError("give exactly one of a client id or --msp")
        folder = export_msp(args.as_of, args.out) if args.msp else export_client(args.client, args.as_of, args.out)
    except OpsError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {folder} (fixture-based, synthetic)")
    return 0
