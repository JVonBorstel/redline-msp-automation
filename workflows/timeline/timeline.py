"""Incident timeline export and incident/recovery fact packs (B-48, specs/B-48.md).

Inventory W-SEC-07, W-BDR-07, W-SEC-09, W-VND-06; controls C-34, C-08, C-27. Depends on B-42 (one chain per client).

Read-only. Nothing here acts: it registers no lever, proposes nothing, imports no runner, queue, approval or notify
code, and writes no file. Declaring an incident, deciding it is a breach, notifying anyone, choosing a recovery point
and changing a firewall, SASE or DNS rule all stay with people (governance/never-automate.json; NN-05).

Order of work for anything that reads the audit trail: verify `<audit-dir>/<client>.jsonl` against its head pin first,
and stop before reading any other source if it does not verify (C-08). Then read the client's alerts (structured fields
only, never title or description), its FortiGate-shaped firewall/SASE log, and ticket ids (never subject or body).

Isolation (C-27). The client is explicit; every source is picked by that client's id; a row that names another client
or another client's device is dropped and counted, never shown.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from adapters import AdapterError, BoundBinding
from adapters.alerts.mock import DEFAULT_ALERTS_DIR, AlertsMock
from adapters.backup.mock import DEFAULT_BACKUP_DIR, BackupMock
from core.audit.chain import head_path_for, verify_chain
from core.audit.router import valid_client_id
from core.guard import detect_injection
from core.paths import REPO_ROOT

HERE = Path(__file__).resolve().parent
DEFAULT_FIREWALL_DIR = HERE / "fixtures" / "fortigate"
DEFAULT_DEVICES_PATH = HERE / "fixtures" / "devices.json"
DEFAULT_TICKETS_DIR = REPO_ROOT / "fixtures" / "tickets"
DEFAULT_DNS_DIR = REPO_ROOT / "fixtures" / "dns"

# The one incident timeline format, defined by B-46 (workflows/bec/config.json) and adopted here unchanged: JSON
# Lines, a header line first (format, notice, client, incident, target, audit_chain), then one event per line
# (at, kind, source, ref, ...), oldest first. B-48 adds header keys (window, tickets, withheld, dropped, rule_changes)
# and event keys; readers of incident-timeline/1 ignore keys they do not know. A test keeps both copies equal.
FORMAT = "incident-timeline/1"
NOTICE = (
    "Facts only. Whether this is a reportable incident or breach, and who is notified, is decided by the client "
    "and its counsel, not by this tool or the MSP."
)
DECISION_LINE = NOTICE
INCIDENT = re.compile(r"^[A-Za-z0-9-]{1,40}$")
HUMAN_ONLY = "human-only (NN-05)"
RULES_STAY_HUMAN = "Firewall, SASE and DNS rule changes stay human (NN-05); this export changed nothing."
WITHHELD = "[withheld: text flagged by the injection detector]"
TICKET_ID = re.compile(r"^T-[0-9]{1,8}$")
DROP_REASONS = {
    "audit": "record of another client",
    "audit-unparsed": "audit record without a usable ts or seq",
    "firewall": "line from another client's device or a device not on file",
    "firewall-unparsed": "log line with no devid, date, time or a bad tz",
    "firewall-duplicate-key": "repeated key in a log line; the first value was kept",
}
NO_TICKET = "no such ticket for this client"

PACK_KINDS: dict[str, str] = {
    "breach": "W-SEC-07",
    "recovery-point": "W-BDR-07",
    "firewall": "W-SEC-09",
    "dns": "W-VND-06",
}
# FortiGate fields kept (names from the FortiOS 7.4.0 Log Message Reference, fixtures/SOURCES.md); the rest are dropped.
FW_FIELDS = ("logid", "subtype", "level", "user", "ui", "action", "cfgpath", "cfgobj", "cfgattr", "tunneltype", "remip")
FW_TEXT = ("logdesc", "msg", "reason")  # free text kept beside FW_FIELDS
# Every string taken from a log goes through _Ctx.text (the injection detector), whichever field it came from.
_KV = re.compile(r'(\w+)=(?:"((?:[^"\\]|\\.)*)"|(\S+))')  # a quoted value may hold \" and \\
_ESCAPE = re.compile(r"\\(.)")


class TimelineError(ValueError):
    """Bad input or a missing source; nothing was exported."""


class ChainNotVerified(TimelineError):
    """The client's audit chain did not verify; nothing was exported."""


@dataclass
class _Ctx:
    withheld: list[str] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)

    def text(self, path: str, value: str) -> str:
        if value and detect_injection(value).flagged:
            self.withheld.append(path)
            return WITHHELD
        return value

    def val(self, path: str, value: Any) -> Any:
        """Any value taken from a source: None stays None, everything else is scanned as text."""
        return None if value is None else self.text(path, value if isinstance(value, str) else str(value))

    def source(self, name: str, status: str, count: int = 0) -> None:
        self.sources[name] = {"status": status, "count": count}

    def drop(self, source: str) -> None:
        self.dropped[source] = self.dropped.get(source, 0) + 1


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TimelineError(f"a source file is not readable: {path.name}") from exc


def _utc(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TimelineError(f"not an ISO 8601 time: {value!r}") from exc
    if moment.tzinfo is None:
        raise TimelineError("times must carry a zone, e.g. 2026-10-20T02:00:00Z")
    return moment.astimezone(UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_client(client: str) -> None:
    if not valid_client_id(client):
        raise TimelineError("client must be a client id such as contoso-dental")


# -- the audit chain: verified first ---------------------------------------------------------------------------------
def verified_chain(client: str, audit_dir: Path) -> tuple[Path, int]:
    """Verify `<audit_dir>/<client>.jsonl` against its head pin; return (path, record count) or raise."""
    _check_client(client)
    path = Path(audit_dir) / f"{client}.jsonl"
    head = head_path_for(path)
    if not path.is_file():
        raise TimelineError("no audit chain for this client; nothing exported")
    if not head.is_file():
        raise ChainNotVerified("the chain has no head pin, so a cut-off end cannot be ruled out; nothing exported")
    result = verify_chain(path, head)
    if not result.ok:
        raise ChainNotVerified(f"audit chain broken at seq {result.broken_seq}: {result.reason}; nothing exported")
    return path, result.records


def _audit_rows(ctx: _Ctx, client: str, path: Path) -> tuple[list[dict[str, Any]], set[str]]:
    rows: list[dict[str, Any]] = []
    tickets: set[str] = set()
    seen = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)  # the chain verified, so every line parses
        if rec.get("client") != client:
            ctx.drop("audit")
            continue
        seen += 1
        try:
            at = _iso(_utc(str(rec["ts"])))
            seq = int(rec["seq"])
        except (KeyError, TypeError, ValueError):  # no ts, a bad ts or no seq: counted, never a crash
            ctx.drop("audit-unparsed")
            continue
        who = f"audit seq {seq}"
        params = rec.get("params") if isinstance(rec.get("params"), dict) else {}
        result = rec.get("result") if isinstance(rec.get("result"), dict) else {}
        ticket = params.get("ticket_id")
        if isinstance(ticket, str) and TICKET_ID.fullmatch(ticket):
            tickets.add(ticket)
        rows.append(
            {
                "at": at,
                "kind": f"lever.{ctx.val(who + '.mode', rec.get('mode'))}",
                "source": "audit",
                "ref": who,
                "execute": rec.get("mode") == "execute",  # decided on the raw mode, before any withholding
                "facts": {
                    "event": ctx.val(who + ".event", rec.get("event", "lever.invoke")),
                    "lever": ctx.val(who + ".lever", rec.get("lever")),
                    "mode": ctx.val(who + ".mode", rec.get("mode")),
                    "status": ctx.val(who + ".status", result.get("status")),
                    "agent": ctx.val(who + ".agent", rec.get("agent")),
                    "actor_kind": ctx.val(who + ".actor_kind", rec.get("actor_kind", "unknown")),
                    "approver": ctx.val(who + ".approver", rec.get("approver")),
                },
            }
        )
    ctx.source("audit", "read", seen)
    return rows, tickets


# -- alerts ----------------------------------------------------------------------------------------------------------
def _alert_rows(ctx: _Ctx, client: str, alerts_dir: Path) -> list[dict[str, Any]]:
    path = Path(alerts_dir) / f"{client}.json"
    if not path.is_file():
        ctx.source("alerts", "absent")
        return []
    account = _read_json(path).get("account_id")
    try:
        adapter = AlertsMock(client, BoundBinding(client, "alerts", "mock", str(account)), Path(alerts_dir))
    except AdapterError as exc:
        raise TimelineError(str(exc)) from exc
    listed = adapter.list_alerts()
    if not listed.ok or listed.data is None:
        raise TimelineError(f"alerts could not be read: {listed.reason}")
    rows: list[dict[str, Any]] = []
    for a in listed.data:
        who = f"alert {a.id}"
        category = ctx.val(who + ".category", a.category)
        rows.append(
            {
                "at": _iso(a.created_at),
                "kind": f"alert.{category}",
                "source": "alert",
                "ref": ctx.val(who + ".id", a.id),
                "facts": {
                    "source_type": ctx.val(who + ".source_type", a.source_type),
                    "severity": ctx.val(who + ".severity", a.severity),
                    "category": category,
                    "entity": ctx.val(who + ".entity", f"{a.entity_kind}:{a.entity_id}"),
                    "soc_case_id": ctx.val(who + ".soc_case_id", a.soc_case_id),
                },
            }
        )
    ctx.source("alerts", "read" if rows else "empty", len(rows))
    return rows


# -- firewall and SASE (FortiGate-shaped log) -----------------------------------------------------------------------
def _fw_time(kv: dict[str, str]) -> datetime:
    tz = kv.get("tz", "+0000")
    if not re.fullmatch(r"[+-][0-9]{4}", tz):
        raise TimelineError("firewall log line has an unreadable tz")
    if "date" not in kv or "time" not in kv:
        raise TimelineError("firewall log line has no date or time")
    return _utc(f"{kv['date']}T{kv['time']}{tz[:3]}:{tz[3:]}")


def _fw_parse(ctx: _Ctx, line: str) -> dict[str, str]:
    """The key=value pairs of one line. A repeated key keeps its first value and is counted."""
    kv: dict[str, str] = {}
    for m in _KV.finditer(line):
        value = _ESCAPE.sub(r"\1", m.group(2)) if m.group(2) is not None else m.group(3)
        if m.group(1) in kv:
            ctx.drop("firewall-duplicate-key")
        else:
            kv[m.group(1)] = value
    return kv


def _fw_kind(role: str, kv: dict[str, str], is_change: bool) -> str:
    if role == "sase":
        return "sase.tunnel-up" if kv.get("action") == "tunnel-up" else "sase.event"
    return "firewall.config-change" if is_change else "firewall.event"


def _firewall_rows(ctx: _Ctx, client: str, fw_dir: Path, devices_path: Path) -> list[dict[str, Any]]:
    path = Path(fw_dir) / f"{client}.log"
    if not path.is_file():
        ctx.source("firewall_log", "absent")
        return []
    devices = (_read_json(devices_path).get("clients") or {}).get(client) or {}
    rows: list[dict[str, Any]] = []
    unparsed = 0
    lines = path.read_bytes().decode("utf-8", errors="replace").splitlines()
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        kv = _fw_parse(ctx, line)
        if "devid" not in kv:
            ctx.drop("firewall-unparsed")
            unparsed += 1
            continue
        role = devices.get(kv["devid"])
        if role not in ("firewall", "sase"):
            ctx.drop("firewall")  # another client's device, or one not on file: never shown
            continue
        try:
            at = _iso(_fw_time(kv))
        except TimelineError:  # unreadable date, time or tz: this line only, counted
            ctx.drop("firewall-unparsed")
            unparsed += 1
            continue
        who = f"firewall line {number}"
        facts: dict[str, Any] = {"device": f"{role}:{kv['devid']}"}
        for key in (*FW_FIELDS, *FW_TEXT):
            if key in kv:
                facts[key] = ctx.text(f"{who}.{key}", kv[key])
        is_change = kv.get("subtype") == "system" and kv.get("cfgpath", "").startswith("firewall.")  # raw: fail safe
        if is_change:
            facts["change"] = HUMAN_ONLY
        rows.append(
            {
                "at": at,
                "kind": _fw_kind(role, kv, is_change),
                "source": "sase" if role == "sase" else "firewall",
                "ref": f"line {number}",
                "facts": facts,
            }
        )
    non_empty = sum(1 for x in lines if x.strip())
    # every non-empty line unparsable: the log is unreadable, not "read" with nothing in it
    status = "empty" if not non_empty else "unreadable" if unparsed == non_empty else "read"
    ctx.source("firewall_log", status, len(rows))
    return rows


# -- tickets: ids only ----------------------------------------------------------------------------------------------
def _ticket_ids(ctx: _Ctx, client: str, tickets_dir: Path, asked: list[str], from_audit: set[str]) -> list[str]:
    path = Path(tickets_dir) / f"{client}.json"
    data = _read_json(path) if path.is_file() else {}
    known = {
        str(t.get("id"))
        for t in data.get("tickets", [])
        if isinstance(t, dict) and t.get("client") == client and data.get("client") == client
    }
    ctx.source("tickets", "read" if path.is_file() else "absent", len(known))
    for ticket in asked:
        if not TICKET_ID.fullmatch(ticket) or ticket not in known:
            raise TimelineError(NO_TICKET)  # absent or another client's: same words
    return sorted(set(asked) | from_audit)


def _in_window(rows: list[dict[str, Any]], start: datetime | None, end: datetime | None) -> list[dict[str, Any]]:
    lo, hi = (_iso(start) if start else None), (_iso(end) if end else None)
    return [r for r in rows if (lo is None or r["at"] >= lo) and (hi is None or r["at"] <= hi)]


def _position(ref: str) -> int:
    """The number at the end of a ref ('audit seq 10', 'line 3', 'A-1001'), so ties sort by number, not as text."""
    m = re.search(r"([0-9]+)$", ref)
    return int(m.group(1)) if m else 0


def _sources(ctx: _Ctx, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per source: status (read, empty, absent), rows read (`count`) and rows left in the window (`in_window`)."""
    home = {"audit": "audit", "alert": "alerts", "firewall": "firewall_log", "sase": "firewall_log"}
    kept: dict[str, int] = {}
    for r in rows:
        kept[home[r["source"]]] = kept.get(home[r["source"]], 0) + 1
    out: dict[str, dict[str, Any]] = {}
    for name in ("audit", "alerts", "firewall_log", "tickets"):
        info = dict(ctx.sources.get(name, {"status": "absent", "count": 0}))
        if name != "tickets":
            info["in_window"] = kept.get(name, 0)
        out[name] = info
    return out


# -- export ----------------------------------------------------------------------------------------------------------
def build_timeline(
    client: str,
    audit_dir: Path,
    *,
    since: str | None = None,
    until: str | None = None,
    tickets: list[str] | None = None,
    incident: str | None = None,
    alerts_dir: Path = DEFAULT_ALERTS_DIR,
    firewall_dir: Path = DEFAULT_FIREWALL_DIR,
    devices_path: Path = DEFAULT_DEVICES_PATH,
    tickets_dir: Path = DEFAULT_TICKETS_DIR,
) -> dict[str, Any]:
    """One client's timeline as plain data. The chain is verified before any other source is opened."""
    chain, records = verified_chain(client, audit_dir)
    if incident is not None and not INCIDENT.fullmatch(incident):
        raise TimelineError("incident id must be 1-40 letters, digits or dashes")
    start, end = (_utc(since) if since else None), (_utc(until) if until else None)
    ctx = _Ctx()
    audit_rows, audit_tickets = _audit_rows(ctx, client, chain)
    rows = audit_rows + _alert_rows(ctx, client, alerts_dir) + _firewall_rows(ctx, client, firewall_dir, devices_path)
    rows = _in_window(rows, start, end)
    rows.sort(key=lambda r: (r["at"], r["source"], _position(r["ref"]), r["ref"]))
    ticket_ids = _ticket_ids(ctx, client, tickets_dir, list(tickets or []), audit_tickets)
    window = f"{client}|{_iso(start) if start else ''}|{_iso(end) if end else ''}"
    return {
        "decision": DECISION_LINE,
        "client": client,
        "incident": incident or "INC-" + hashlib.sha256(window.encode()).hexdigest()[:10],
        "chain": {"file": chain.name, "verified": True, "records": records},
        "window": {"since": _iso(start) if start else None, "until": _iso(end) if end else None},
        "tickets": ticket_ids,
        "sources": _sources(ctx, rows),
        "rows": rows,
        "withheld": sorted(ctx.withheld),
        "dropped": dict(sorted(ctx.dropped.items())),
    }


def _cell(value: Any) -> str:
    return str(value).replace("|", "/").replace("\n", " ")


def render(timeline: dict[str, Any]) -> str:
    """The export in format incident-timeline/1 (JSON Lines). Line 1 is the header holding the notice (B48-3)."""
    header = {
        "format": FORMAT,
        "notice": NOTICE,
        "client": timeline["client"],
        "incident": timeline["incident"],
        "target": None,  # client-wide; B-46 sets one user here
        "audit_chain": {"verified": True, "records": timeline["chain"]["records"]},
        "window": timeline["window"],
        "tickets": timeline["tickets"],
        "sources": timeline["sources"],
        "withheld": timeline["withheld"],
        "dropped": timeline["dropped"],
        "rule_changes": RULES_STAY_HUMAN,
    }
    events = [
        {"at": r["at"], "kind": r["kind"], "source": r["source"], "ref": r["ref"], **r["facts"]}
        for r in timeline["rows"]
    ]
    return "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in (header, *events))


def render_text(timeline: dict[str, Any]) -> str:
    """The same timeline as Markdown for a person to read. Line 1 is the notice (B48-3)."""
    window = timeline["window"]
    lines = [
        DECISION_LINE,
        "",
        f"# Incident timeline: {timeline['client']} (synthetic, fixture-based)",
        "",
        f"- Audit chain `{timeline['chain']['file']}`: verified against its head pin, {timeline['chain']['records']}"
        " records.",
        f"- Window: {window['since'] or 'start'} to {window['until'] or 'end'} (UTC).",
        f"- Tickets (ids only): {', '.join(timeline['tickets']) or 'none'}.",
        "- Sources: "
        + "; ".join(
            f"{k} {v['status']} ({v['count']} read" + (f", {v['in_window']} in window)" if "in_window" in v else ")")
            for k, v in timeline["sources"].items()
        )
        + ".",
        f"- Incident: {timeline['incident']}; format of the export: {FORMAT}.",
        "",
        "| at (UTC) | source | ref | facts |",
        "| --- | --- | --- | --- |",
    ]
    for row in timeline["rows"]:
        facts = "; ".join(f"{k}={_cell(v)}" for k, v in row["facts"].items() if v is not None)
        lines.append(f"| {row['at']} | {row['source']} | {_cell(row['ref'])} | {facts} |")
    lines.append("")
    if timeline["withheld"]:
        lines.append(f"- Dropped or withheld: flagged text withheld at {', '.join(timeline['withheld'])}.")
    if timeline["dropped"]:
        lines.append("- Dropped or withheld, by reason:")
        for key, count in timeline["dropped"].items():
            lines.append(f"  - {key}: {count} ({DROP_REASONS.get(key, 'dropped')})")
    lines.append(f"- {RULES_STAY_HUMAN}")
    return "\n".join(lines) + "\n"


# -- fact packs ------------------------------------------------------------------------------------------------------
def build_pack(
    kind: str,
    client: str,
    *,
    audit_dir: Path | None = None,
    since: str | None = None,
    until: str | None = None,
    alerts_dir: Path = DEFAULT_ALERTS_DIR,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    firewall_dir: Path = DEFAULT_FIREWALL_DIR,
    devices_path: Path = DEFAULT_DEVICES_PATH,
    dns_dir: Path = DEFAULT_DNS_DIR,
) -> dict[str, Any]:
    """A read-only fact pack: facts and gaps, no recommendation, no lever."""
    if kind not in PACK_KINDS:
        raise TimelineError(f"unknown kind {kind!r}; choose one of {', '.join(PACK_KINDS)}")
    _check_client(client)
    ctx = _Ctx()
    gaps: list[str] = []
    if kind == "breach":
        if audit_dir is None:
            raise TimelineError("the breach pack reads the audit chain: pass --audit-dir")
        tl = build_timeline(
            client,
            audit_dir,
            since=since,
            until=until,
            alerts_dir=alerts_dir,
            firewall_dir=firewall_dir,
            devices_path=devices_path,
        )
        facts = _breach(tl)
        ctx.withheld += tl["withheld"]  # what the timeline withheld or dropped is shown in the pack too
        for reason, count in tl["dropped"].items():
            ctx.dropped[reason] = ctx.dropped.get(reason, 0) + count
        gaps += ["what data was accessed or taken: no source here", "whether this is a breach: the client and counsel"]
    elif kind == "recovery-point":
        if since:
            raise TimelineError(
                "the recovery-point pack cannot honour --since: it lists the points as of a cutoff, so use --until"
            )
        facts = _recovery(client, backup_dir, until)
        gaps.append("restore test results beyond the boot check: no source here")
    elif kind == "firewall":
        start, end = (_utc(since) if since else None), (_utc(until) if until else None)
        rows = _in_window(_firewall_rows(ctx, client, firewall_dir, devices_path), start, end)
        facts = {
            "changes": [r for r in rows if r["facts"].get("change")],
            "saseTunnels": [r for r in rows if r["source"] == "sase"],
            "changesStayHuman": HUMAN_ONLY,
        }
        gaps.append("the documented intended rule set: no source here")
    else:
        if since or until:
            raise TimelineError(
                "the dns pack cannot honour --since or --until: it lists the records as of the fixture date"
            )
        facts = _dns(client, dns_dir)
        gaps.append("registrar change history and registrar account holders: no source here")
    return {
        "kind": kind,
        "client": client,
        "inventoryId": PACK_KINDS[kind],
        "decision": DECISION_LINE,
        "readOnly": True,
        "leversRegistered": [],
        "proposals": [],
        "facts": facts,
        "gaps": gaps,
        "withheld": sorted(ctx.withheld),
        "dropped": dict(sorted(ctx.dropped.items())),
    }


def _breach(tl: dict[str, Any]) -> dict[str, Any]:
    alerts = [r for r in tl["rows"] if r["source"] == "alert"]
    by_severity: dict[str, int] = {}
    entities: dict[str, dict[str, Any]] = {}
    for r in alerts:
        f = r["facts"]
        by_severity[f["severity"]] = by_severity.get(f["severity"], 0) + 1
        e = entities.setdefault(
            f["entity"], {"entity": f["entity"], "first": r["at"], "last": r["at"], "categories": []}
        )
        e["last"] = r["at"]
        if f["category"] not in e["categories"]:
            e["categories"].append(f["category"])
    executes = [r for r in tl["rows"] if r["source"] == "audit" and r["execute"]]
    return {
        "chain": tl["chain"],
        "alertsBySeverity": dict(sorted(by_severity.items())),
        "entities": sorted(entities.values(), key=lambda e: (e["first"], e["entity"])),
        "socCaseIds": sorted({r["facts"]["soc_case_id"] for r in alerts if r["facts"]["soc_case_id"]}),
        "leverExecutes": [{"at": r["at"], "ref": r["ref"], **r["facts"]} for r in executes],
        "tickets": tl["tickets"],
    }


def _recovery(client: str, backup_dir: Path, until: str | None) -> dict[str, Any]:
    try:
        adapter = BackupMock.for_fixture(client, Path(backup_dir))
    except AdapterError as exc:
        raise TimelineError(str(exc)) from exc
    listed = adapter.list_jobs()
    if not listed.ok or listed.data is None:
        raise TimelineError(f"backup jobs could not be read: {listed.reason}")
    cutoff = _iso(_utc(until)) if until else None
    assets: dict[str, dict[str, Any]] = {}
    for job in listed.data:
        a = assets.setdefault(str(job.get("assetName")), {"asset": job.get("assetName"), "points": [], "failures": []})
        boot = job.get("bootCheck") if isinstance(job.get("bootCheck"), dict) else None
        entry = {"jobId": job.get("id"), "finishedAt": job.get("finishedAt"), "status": job.get("status")}
        if job.get("status") == "success" and (cutoff is None or str(job.get("finishedAt")) <= cutoff):
            a["points"].append({**entry, "bootCheck": boot.get("status") if boot else None})
        elif job.get("status") != "success" and (cutoff is None or str(job.get("scheduledStart")) <= cutoff):
            a["failures"].append({**entry, "scheduledStart": job.get("scheduledStart")})
    for a in assets.values():
        a["points"].sort(key=lambda p: (str(p["finishedAt"]), str(p["jobId"])))  # latest = last to finish
        latest = a["points"][-1] if a["points"] else None
        a["latestPoint"] = latest
        a["failuresAfterLatest"] = [
            f["jobId"] for f in a["failures"] if latest is None or str(f["scheduledStart"]) > str(latest["finishedAt"])
        ]
    return {"asOf": adapter.as_of, "until": cutoff, "assets": sorted(assets.values(), key=lambda a: str(a["asset"]))}


def _dns(client: str, dns_dir: Path) -> dict[str, Any]:
    data = _read_json(Path(dns_dir) / f"{client}.json")
    if not isinstance(data, dict) or data.get("client") != client:
        raise TimelineError("DNS fixture does not belong to this client")
    domains = []
    for d in data.get("domains", []):
        dmarc = d.get("dmarc") or ""
        policy = re.search(r"\bp=([a-z]+)", dmarc)
        domains.append(
            {
                "domain": d.get("domain"),
                "owner": d.get("owner"),
                "spfPresent": bool(d.get("spf")),
                "dmarcPolicy": policy.group(1) if policy else None,
                "dkimSelectorsPublished": sorted(k["selector"] for k in d.get("dkim", []) if k.get("published")),
            }
        )
    return {"asOf": data.get("as_of"), "domains": domains, "changesStayHuman": HUMAN_ONLY}
