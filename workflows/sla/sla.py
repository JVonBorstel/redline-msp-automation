"""SLA breach watch and backlog grooming report (B-24, specs/B-24.md; W-SD-06, W-SD-10; C-27, C-21).

Given an explicit ``as_of`` (STD-PY-9), for each client separately:

* **Breach watch.** Open tickets whose first-response or resolution deadline falls inside the next ``window_hours``
  (``at_risk``), and those already past it (``breached``, never hidden). Deadlines are ``created + hours`` from that
  client's SLA matrix, read through the client's own PSA adapter (``fixtures/psa/`` via ``adapters``, TEN-04).
* **Backlog grooming.** Tickets waiting on the client or on a vendor for longer than ``waiting_hours``, each with a
  follow-up *draft* (starts with the draft label; this package has no send function, HO-9).

Every number in the report is a count of the ticket fixtures. ``validate_report`` recomputes them from the raw JSON
files with separate, simpler code and compares every count and id (C-21), so a later model rephrasing the report
cannot invent a number. No model is called.

Assumptions, all UNVERIFIED against the MSP's real PSA and contract (the real numbers are UNKNOWN):

* Hours are wall-clock hours from ``created``. The matrix names say "8x5" and "7x12", but no business-hour calendar is
  modelled, so a deadline can fall earlier than a business-hours reading: the watch warns early, never late.
* First response: a ``new`` file ticket has had none; a PSA ticket has had one when a note by a resource exists.
  A late response that already happened is history, not a watch item.
* The resolution clock is paused while a ticket is ``waiting-client`` (the client controls the delay); it keeps running
  while ``waiting-vendor``. Paused tickets are counted.
* A waiting ticket's age is ``as_of - updated`` (the last touch is the best stand-in for when waiting started).
* A file ticket carries no SLA id, so it gets its client's SLA only when the client has exactly one active SLA.

Untrusted text (subject, body) is never read into the report or a draft. Gold labels in the files are ignored
(STD-FX-5). Values that reach a draft: ticket id, first name, a day count, the client's contact line.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from string import Template
from typing import Any

from adapters import PsaAdapter, build_adapter
from adapters.binding import CLIENT_ID, DEFAULT_CLIENT_DIR
from adapters.psa.mock import DEFAULT_PSA_DIR
from core.levers import DEFAULT_TENANT_DIR, MockTenant, TenantError
from core.paths import REPO_ROOT
from workflows.notify import DEFAULT_CONTACTS_PATH, DRAFT_HEADER, NotifyError, load_contacts

DEFAULT_TICKETS_DIR = REPO_ROOT / "fixtures" / "tickets"
DEFAULT_WINDOW_HOURS = 4.0
DEFAULT_WAITING_HOURS = 72.0
LABEL = "fixture-based, synthetic; hours are wall-clock and the SLA matrix is a stand-in (UNVERIFIED)"

TICKET_ID = re.compile(r"^T-[0-9]{4}$")
_NAME = re.compile(r"^[A-Za-z][A-Za-z'-]{0,30}$")
_TECH = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
WAITING = ("waiting-client", "waiting-vendor")
# The PSA fixture's numeric status is an invented placeholder (UNVERIFIED); only 1 is used there.
_PSA_STATUS = {1: "new"}


class SlaError(ValueError):
    """The input is bad (as_of, a threshold, an unreadable fixture); nothing was reported."""


@dataclass(frozen=True, slots=True)
class Sla:
    id: int
    name: str
    first_response_hours: float
    resolution_hours: float


@dataclass(frozen=True, slots=True)
class WatchTicket:
    """The ticket fields this workflow reads (no free text)."""

    id: str
    client: str
    status: str
    created: datetime | None
    updated: datetime | None
    technician: str | None
    sla_id: int | None
    responded: bool
    first_name: str
    source: str  # "file" | "psa"


@dataclass(frozen=True, slots=True)
class ClientSource:
    """One client's SLA matrix and PSA tickets, or why there is none."""

    client: str
    slas: tuple[Sla, ...]
    tickets: tuple[WatchTicket, ...]
    reason: str  # "ok" or why the PSA could not be read


# -- time -----------------------------------------------------------------------------------------------------


def parse_time(value: object) -> datetime:
    """An ISO 8601 UTC time. Naive or non-UTC values are refused."""
    if not isinstance(value, str):
        raise SlaError("time must be an ISO 8601 string such as 2026-10-16T23:00:00Z")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise SlaError(f"cannot read time {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise SlaError("time must be UTC (end with Z)")
    return parsed.astimezone(UTC)


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _optional_time(value: object) -> datetime | None:
    return None if value is None else parse_time(value)


# -- loading --------------------------------------------------------------------------------------------------


def _first_name(tenant: MockTenant, client: str, upn: str | None) -> str:
    try:
        users = tenant.load(client).get("users", [])
    except TenantError:
        return "there"
    for user in users:
        if isinstance(user, dict) and user.get("userPrincipalName") == upn:
            words = str(user.get("displayName", "")).split()
            if words and _NAME.fullmatch(words[0]):
                return words[0]
    return "there"


def load_file_tickets(root: Path, tenant: MockTenant) -> list[WatchTicket]:
    """Tickets from ``root/**/*.json`` (ticket fixtures). Labels and free text are ignored. Fails closed."""
    found: dict[str, WatchTicket] = {}
    files = sorted(Path(root).rglob("*.json"))
    if not files:
        raise SlaError(f"no ticket fixtures in {root}")
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            client = str(data["client"])
            if not CLIENT_ID.fullmatch(client):
                raise ValueError("bad client id")
            for raw in data["tickets"]:
                tid = str(raw["id"])
                if not TICKET_ID.fullmatch(tid) or raw.get("client") != client or tid in found:
                    raise ValueError(f"{tid}: bad id, client mismatch or duplicate")
                tech = raw.get("technician")
                created = _optional_time(raw.get("created"))
                updated = _optional_time(raw.get("updated"))
                upn = raw.get("affected_user") or raw.get("requester")
                status = str(raw.get("status") or "unknown")
                found[tid] = WatchTicket(
                    id=tid,
                    client=client,
                    status=status,
                    created=created,
                    updated=updated if updated is not None else created,
                    technician=tech if isinstance(tech, str) and _TECH.fullmatch(tech) else None,
                    sla_id=None,
                    responded=status != "new",
                    first_name=_first_name(tenant, client, upn if isinstance(upn, str) else None),
                    source="file",
                )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise SlaError(f"cannot load tickets from {path.name}: {exc}") from exc
    return [found[key] for key in sorted(found)]


def _slas(rows: Iterable[dict[str, Any]]) -> tuple[Sla, ...]:
    return tuple(
        Sla(int(r["id"]), str(r["name"]), float(r["firstResponseHours"]), float(r["resolutionHours"]))
        for r in rows
        if r.get("isActive")
    )


def _psa_files(root: Path) -> list[Path]:
    """The per-client PSA fixtures in ``root``; B-34's contacts-authorized.json is a list, not a client file."""
    return sorted(p for p in root.glob("*.json") if p.name != "contacts-authorized.json")


def load_client_source(client: str, config_dir: Path, psa_dir: Path | None = None) -> ClientSource:
    """Build this client's own PSA adapter (TEN-04) and read its SLA matrix and tickets. Never raises."""
    built = build_adapter(client, "psa", config_dir=config_dir, fixtures_dir=psa_dir)
    adapter = built.adapter
    if not built.ok or not isinstance(adapter, PsaAdapter):
        return ClientSource(client, (), (), built.reason)
    try:
        sla_result = adapter.get_sla_settings()
        ticket_result = adapter.list_tickets()
        contact_result = adapter.list_contacts()
        for result in (sla_result, ticket_result, contact_result):
            if not result.ok:
                return ClientSource(client, (), (), result.reason)
        names = {c["id"]: str(c.get("firstName", "")) for c in contact_result.data or []}
        tickets: list[WatchTicket] = []
        for raw in ticket_result.data or []:
            notes = adapter.list_ticket_notes(str(raw["ticketNumber"]))
            responded = notes.ok and any(n.get("creatorResourceID") is not None for n in notes.data or [])
            name = names.get(raw.get("contactID"), "")
            created = _optional_time(raw.get("createDate"))
            tickets.append(
                WatchTicket(
                    id=str(raw["ticketNumber"]),
                    client=client,
                    status=_PSA_STATUS.get(int(raw.get("status", 0)), "unknown"),
                    created=created,
                    updated=created,
                    technician=None,
                    sla_id=raw.get("serviceLevelAgreementID"),
                    responded=responded,
                    first_name=name if _NAME.fullmatch(name) else "there",
                    source="psa",
                )
            )
        return ClientSource(client, _slas(sla_result.data or []), tuple(tickets), "ok")
    except (KeyError, TypeError, ValueError) as exc:
        return ClientSource(client, (), (), f"PSA data unreadable ({type(exc).__name__})")


# -- the computation ------------------------------------------------------------------------------------------


def _classify(t: WatchTicket, as_of: datetime) -> str:
    """Exactly one bucket per ticket: untimed, then after-as-of, then resolved, then open."""
    if t.created is None:
        return "untimed"
    if t.created > as_of:
        return "created_after_as_of"
    if t.status == "resolved":
        return "resolved"
    return "open"


def _sla_for(t: WatchTicket, slas: tuple[Sla, ...]) -> Sla | None:
    if t.sla_id is not None:
        return next((s for s in slas if s.id == t.sla_id), None)
    return slas[0] if len(slas) == 1 else None


def _entry(t: WatchTicket, kind: str, deadline: datetime, as_of: datetime) -> dict[str, Any]:
    return {
        "ticket": t.id,
        "kind": kind,
        "deadline": iso(deadline),
        "minutes_from_as_of": int((deadline - as_of).total_seconds() // 60),
        "status": t.status,
        "technician": t.technician,
    }


COUNT_KEYS = (
    "tickets_read",
    "resolved",
    "created_after_as_of",
    "untimed",
    "open",
    "open_no_sla",
    "open_assessed",
    "resolution_clock_paused",
    "breached_first_response",
    "breached_resolution",
    "at_risk_first_response",
    "at_risk_resolution",
    "waiting_client",
    "waiting_vendor",
    "stale_waiting_client",
    "stale_waiting_vendor",
    "followup_drafts",
)


def _followup(t: WatchTicket, days: int, contact: Any | None) -> str:
    client_wait = t.status == "waiting-client"
    waiting_on = "a reply from you" if client_wait else "an outside vendor"
    ask = (
        "Is this still a problem? Please reply and tell us, or tell us it can be closed."
        if client_wait
        else "A technician has been asked to chase the vendor. Tell us if it has become urgent."
    )
    way = (
        f"If it is urgent, call {contact.fast_phone} ({contact.hours})." if contact else "If it is urgent, reply here."
    )
    body = Template("Your ticket $ticket has been waiting on $waiting for about $days days.\n$ask\n$way\n").substitute(
        ticket=t.id, waiting=waiting_on, days=days, ask=ask, way=way
    )
    return f"{DRAFT_HEADER}\n\nHi {t.first_name},\n\n{body}"


def build_report(
    tickets: Iterable[WatchTicket],
    sources: dict[str, ClientSource],
    *,
    as_of: datetime,
    window_hours: float = DEFAULT_WINDOW_HOURS,
    waiting_hours: float = DEFAULT_WAITING_HOURS,
    contacts_path: Path = DEFAULT_CONTACTS_PATH,
) -> dict[str, Any]:
    """The report as a JSON-ready dict. ``drafts`` (ticket id to draft text) is kept apart from the counts."""
    if window_hours <= 0 or waiting_hours <= 0:
        raise SlaError("window_hours and waiting_hours must be positive")
    try:
        contacts = load_contacts(contacts_path)
    except NotifyError as exc:
        raise SlaError(str(exc)) from exc
    window_end = as_of + timedelta(hours=window_hours)
    by_client: dict[str, list[WatchTicket]] = {}
    for t in tickets:
        by_client.setdefault(t.client, []).append(t)
    for client, src in sources.items():  # PSA tickets join the same per-client pool
        by_client.setdefault(client, []).extend(x for x in src.tickets if x.client == client)
    clients: dict[str, Any] = {}
    drafts: dict[str, str] = {}
    for client in sorted(by_client):
        src = sources.get(client) or ClientSource(client, (), (), "no PSA binding checked")
        counts = dict.fromkeys(COUNT_KEYS, 0)
        breached: list[dict[str, Any]] = []
        at_risk: list[dict[str, Any]] = []
        stale: list[tuple[float, dict[str, Any]]] = []
        for t in sorted(by_client[client], key=lambda x: x.id):
            counts["tickets_read"] += 1
            bucket = _classify(t, as_of)
            counts[bucket] += 1
            if bucket != "open" or t.created is None:
                continue
            if t.status in WAITING:
                key = t.status.replace("-", "_")
                counts[key] += 1
                age = (as_of - (t.updated or t.created)).total_seconds() / 3600
                if age > waiting_hours:
                    counts["stale_" + key] += 1
                    counts["followup_drafts"] += 1
                    row = {"ticket": t.id, "status": t.status, "waiting_hours": int(age), "technician": t.technician}
                    stale.append((age, row))
                    drafts[t.id] = _followup(t, int(age // 24), contacts.get(client))
            sla = _sla_for(t, src.slas)
            if sla is None:
                counts["open_no_sla"] += 1
                continue
            counts["open_assessed"] += 1
            deadlines: list[tuple[str, datetime]] = []
            if not t.responded:
                deadlines.append(("first-response", t.created + timedelta(hours=sla.first_response_hours)))
            if t.status == "waiting-client":
                counts["resolution_clock_paused"] += 1
            else:
                deadlines.append(("resolution", t.created + timedelta(hours=sla.resolution_hours)))
            for kind, deadline in deadlines:
                key = kind.replace("-", "_")
                if deadline <= as_of:
                    counts["breached_" + key] += 1
                    breached.append(_entry(t, kind, deadline, as_of))
                elif deadline <= window_end:
                    counts["at_risk_" + key] += 1
                    at_risk.append(_entry(t, kind, deadline, as_of))
        at_risk.sort(key=lambda e: (e["deadline"], e["ticket"], e["kind"]))
        breached.sort(key=lambda e: (e["deadline"], e["ticket"], e["kind"]))
        stale.sort(key=lambda pair: (-pair[0], pair[1]["ticket"]))
        clients[client] = {
            "sla": [
                {
                    "id": s.id,
                    "name": s.name,
                    "first_response_hours": s.first_response_hours,
                    "resolution_hours": s.resolution_hours,
                }
                for s in src.slas
            ],
            "sla_source": src.reason,
            "counts": counts,
            "at_risk": at_risk,
            "breached": breached,
            "stale_waiting": [row for _, row in stale],
        }
    totals = dict.fromkeys(COUNT_KEYS, 0)
    for entry in clients.values():
        for key, value in entry["counts"].items():
            totals[key] += value
    return {
        "_note": "Synthetic. A person reads this and decides; nothing is sent. Not real SLA performance.",
        "label": LABEL,
        "as_of": iso(as_of),
        "window_hours": window_hours,
        "waiting_hours": waiting_hours,
        "clients": clients,
        "totals": totals,
        "drafts": drafts,
    }


def collect(
    *,
    as_of: datetime,
    tickets_dir: Path = DEFAULT_TICKETS_DIR,
    config_dir: Path = DEFAULT_CLIENT_DIR,
    psa_dir: Path | None = None,
    tenant_dir: Path = DEFAULT_TENANT_DIR,
    window_hours: float = DEFAULT_WINDOW_HOURS,
    waiting_hours: float = DEFAULT_WAITING_HOURS,
    contacts_path: Path = DEFAULT_CONTACTS_PATH,
) -> dict[str, Any]:
    """Load every ticket fixture and each client's own PSA adapter, then build the report."""
    file_tickets = load_file_tickets(tickets_dir, MockTenant(tenant_dir))
    psa_root = psa_dir if psa_dir is not None else DEFAULT_PSA_DIR
    clients = {t.client for t in file_tickets} | {p.stem for p in _psa_files(Path(psa_root))}
    sources = {c: load_client_source(c, config_dir, psa_dir) for c in sorted(clients)}
    return build_report(
        file_tickets,
        sources,
        as_of=as_of,
        window_hours=window_hours,
        waiting_hours=waiting_hours,
        contacts_path=contacts_path,
    )


# -- the validator (C-21, B24-3) ------------------------------------------------------------------------------


def _raw_rows(tickets_dir: Path, psa_root: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[Any]]]:
    """Plain dict reads of the fixtures, with no adapter and no workflow code."""
    rows: dict[str, list[dict[str, Any]]] = {}
    slas: dict[str, list[Any]] = {}
    for path in sorted(Path(tickets_dir).rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        slas.setdefault(data["client"], [])
        for t in data["tickets"]:
            rows.setdefault(data["client"], []).append(
                {
                    "id": t["id"],
                    "status": t.get("status"),
                    "created": t.get("created"),
                    "updated": t.get("updated"),
                    "responded": t.get("status") != "new",
                    "sla": None,
                }
            )
    for path in sorted(_psa_files(psa_root)):
        data = json.loads(path.read_text(encoding="utf-8"))
        client = data["client"]
        slas[client] = [s for s in data.get("slaSettings", []) if s.get("isActive")]
        noted = {n["ticketID"] for n in data.get("ticketNotes", []) if n.get("creatorResourceID") is not None}
        for t in data.get("tickets", []):
            rows.setdefault(client, []).append(
                {
                    "id": t["ticketNumber"],
                    "status": "new" if t.get("status") == 1 else "unknown",
                    "created": t.get("createDate"),
                    "updated": t.get("createDate"),
                    "responded": t["id"] in noted,
                    "sla": t.get("serviceLevelAgreementID"),
                }
            )
    return rows, slas


def validate_report(
    report: dict[str, Any],
    *,
    tickets_dir: Path = DEFAULT_TICKETS_DIR,
    psa_dir: Path | None = None,
) -> list[str]:
    """Recompute every count and id from the raw JSON files and compare. An empty list means it reconciles.

    Checks the per-client counts, the listed ticket ids, the arithmetic identities, that totals equal the sum of the
    clients, and that one draft exists per stale waiting ticket.
    """
    try:
        as_of = parse_time(report["as_of"])
        window = timedelta(hours=float(report["window_hours"]))
        wait_h = float(report["waiting_hours"])
        report_clients: dict[str, Any] = report["clients"]
        report_totals: dict[str, int] = report["totals"]
        report_drafts: Any = report["drafts"]
    except (KeyError, SlaError, ValueError, TypeError) as exc:
        return [f"report unreadable: {exc}"]
    psa_root = Path(psa_dir) if psa_dir is not None else DEFAULT_PSA_DIR
    rows, slas = _raw_rows(tickets_dir, psa_root)
    problems: list[str] = []
    if set(rows) != set(report_clients):
        problems.append(f"clients differ: report {sorted(report_clients)} vs fixtures {sorted(rows)}")
    summed: Counter[str] = Counter()
    draft_ids: set[str] = set()
    for client, tickets in rows.items():
        entry = report_clients.get(client)
        if entry is None:
            continue
        want: Counter[str] = Counter()
        want_ids: dict[str, set[tuple[str, str]]] = {"breached": set(), "at_risk": set()}
        want_stale: set[str] = set()
        for r in tickets:
            want["tickets_read"] += 1
            if not r["created"]:
                want["untimed"] += 1
                continue
            created = parse_time(r["created"])
            if created > as_of:
                want["created_after_as_of"] += 1
                continue
            if r["status"] == "resolved":
                want["resolved"] += 1
                continue
            want["open"] += 1
            if r["status"] in WAITING:
                suffix = str(r["status"]).replace("-", "_")
                want[suffix] += 1
                if (as_of - parse_time(r["updated"] or r["created"])).total_seconds() / 3600 > wait_h:
                    want["stale_" + suffix] += 1
                    want["followup_drafts"] += 1
                    want_stale.add(r["id"])
            pool = slas.get(client, [])
            if r["sla"] is not None:
                sla = next((s for s in pool if s["id"] == r["sla"]), None)
            else:
                sla = pool[0] if len(pool) == 1 else None
            if sla is None:
                want["open_no_sla"] += 1
                continue
            want["open_assessed"] += 1
            due: list[tuple[str, datetime]] = []
            if not r["responded"]:
                due.append(("first_response", created + timedelta(hours=float(sla["firstResponseHours"]))))
            if r["status"] == "waiting-client":
                want["resolution_clock_paused"] += 1
            else:
                due.append(("resolution", created + timedelta(hours=float(sla["resolutionHours"]))))
            for kind, deadline in due:
                if deadline <= as_of:
                    want["breached_" + kind] += 1
                    want_ids["breached"].add((r["id"], kind))
                elif deadline <= as_of + window:
                    want["at_risk_" + kind] += 1
                    want_ids["at_risk"].add((r["id"], kind))
        got: dict[str, int] = entry["counts"]
        for key in sorted(set(want) | set(got)):
            if got.get(key, 0) != want.get(key, 0):
                problems.append(f"{client} {key}: report {got.get(key, 0)} vs fixtures {want.get(key, 0)}")
        summed.update(got)
        for listing in ("breached", "at_risk"):
            listed = [(e["ticket"], e["kind"].replace("-", "_")) for e in entry[listing]]
            if set(listed) != want_ids[listing] or len(listed) != len(set(listed)):
                problems.append(f"{client} {listing}: listed tickets differ from the fixtures")
        if {e["ticket"] for e in entry["stale_waiting"]} != want_stale:
            problems.append(f"{client} stale_waiting: listed tickets differ from the fixtures")
        draft_ids |= want_stale
        if got["tickets_read"] != got["untimed"] + got["created_after_as_of"] + got["resolved"] + got["open"]:
            problems.append(f"{client}: tickets_read is not the sum of its buckets")
        if got["open"] != got["open_assessed"] + got["open_no_sla"]:
            problems.append(f"{client}: open is not open_assessed + open_no_sla")
        if got["followup_drafts"] != got["stale_waiting_client"] + got["stale_waiting_vendor"]:
            problems.append(f"{client}: followup_drafts is not the stale waiting count")
    for key, value in summed.items():
        if report_totals.get(key) != value:
            problems.append(f"totals {key}: report {report_totals.get(key)} vs sum of clients {value}")
    shown = set(report_drafts) if isinstance(report_drafts, (dict, list)) else set()
    if shown != draft_ids:
        problems.append("the drafts do not match the stale waiting tickets")
    return problems


# -- output ---------------------------------------------------------------------------------------------------


def render_markdown(report: dict[str, Any]) -> str:
    out = [
        "# SLA breach watch and backlog grooming",
        "",
        f"Status: {report['label']}. As of {report['as_of']}; watch window {report['window_hours']:g} h; "
        f"waiting threshold {report['waiting_hours']:g} h. A person reads this; nothing is sent.",
        "",
    ]
    t = report["totals"]
    out.append(
        f"Totals: {t['tickets_read']} tickets read, {t['open']} open "
        f"({t['open_assessed']} with an SLA, {t['open_no_sla']} without), "
        f"{t['breached_first_response'] + t['breached_resolution']} breached deadlines, "
        f"{t['at_risk_first_response'] + t['at_risk_resolution']} deadlines about to breach, "
        f"{t['followup_drafts']} stale waiting tickets with a follow-up draft."
    )
    for client, entry in report["clients"].items():
        c = entry["counts"]
        sla = ", ".join(
            f"{s['name']}: first response {s['first_response_hours']:g} h, resolution {s['resolution_hours']:g} h"
            for s in entry["sla"]
        )
        out += [
            "",
            f"## {client}",
            "",
            f"SLA matrix: {sla or 'none (' + entry['sla_source'] + ')'}.",
            f"Read {c['tickets_read']}: {c['resolved']} resolved, {c['untimed']} without timestamps, "
            f"{c['created_after_as_of']} created after as_of, {c['open']} open "
            f"({c['open_no_sla']} cannot be judged: no SLA matrix).",
            "",
            f"Deadlines inside the next {report['window_hours']:g} h: {len(entry['at_risk'])}. "
            f"Deadlines already passed: {len(entry['breached'])}. "
            f"Stale waiting tickets: {len(entry['stale_waiting'])}.",
        ]
        for title, listing in (("About to breach", entry["at_risk"]), ("Already breached", entry["breached"])):
            if listing:
                out += ["", f"**{title}**", "", "| Ticket | Deadline | Minutes from as_of | Status | Technician |"]
                out.append("|---|---|---|---|---|")
                out += [
                    f"| {e['ticket']} | {e['kind']} {e['deadline']} | {e['minutes_from_as_of']} | {e['status']} "
                    f"| {e['technician'] or '-'} |"
                    for e in listing
                ]
        if entry["stale_waiting"]:
            out += [
                "",
                "**Waiting too long (draft written, not sent)**",
                "",
                "| Ticket | Waiting on | Hours | Technician |",
            ]
            out.append("|---|---|---|---|")
            out += [
                f"| {e['ticket']} | {e['status'].removeprefix('waiting-')} | {e['waiting_hours']} "
                f"| {e['technician'] or '-'} |"
                for e in entry["stale_waiting"]
            ]
    return "\n".join(out) + "\n"


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(path)


def write_report(report: dict[str, Any], state_dir: Path) -> Path:
    """Write ``<state>/sla/report.json``, ``report.md`` and ``drafts/<ticket>.followup.md``. Returns the folder."""
    out = Path(state_dir) / "sla"
    public = {k: v for k, v in report.items() if k != "drafts"}
    public["drafts"] = sorted(report["drafts"])
    _write_atomic(out / "report.json", json.dumps(public, indent=2) + "\n")
    _write_atomic(out / "report.md", render_markdown(report))
    for ticket, text in report["drafts"].items():
        _write_atomic(out / "drafts" / f"{ticket}.followup.md", text)
    return out


def write_demo_bindings(config_dir: Path, psa_dir: Path | None = None) -> None:
    """Write synthetic mock PSA bindings (one per PSA fixture) for a run where config/clients is not there yet."""
    psa_root = Path(psa_dir) if psa_dir is not None else DEFAULT_PSA_DIR
    for path in sorted(_psa_files(psa_root)):
        data = json.loads(path.read_text(encoding="utf-8"))
        client, company = str(data["client"]), str(data["company"]["id"])
        binding = {"implementation": "mock", "external_id": company, "credential_ref": f"client-{client}-psa"}
        cfg = {
            "version": 1,
            "_note": "Synthetic demo binding written by workflows.sla; not the owner's config.",
            "id": client,
            "display_name": client,
            "psa_company_id": company,
            "industry": "other",
            "regimes": [],
            "model_processing": "none",
            "retention_class": "standard",
            "enabled_levers": [],
            "bindings": {"psa": binding},
        }
        _write_atomic(Path(config_dir) / f"{client}.json", json.dumps(cfg, indent=2) + "\n")
