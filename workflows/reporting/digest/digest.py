"""Weekly "what we did for you" digest draft (B-72, specs/B-72.md; W-RPT-03; C-21, C-45).

For one client and one ISO week this lists the tickets closed that week, the tenant changes a baseline run found that
week, and the backup jobs scheduled that week, in plain words and with counts. A closed ticket is shown by its id, the
channel it arrived by, the day it was opened, the day it was closed and the hours between: never its subject, body,
requester, technician or labels (ticket text is untrusted input and is not read). Before anything is written,
``reconcile.reconcile_html`` recomputes every figure and every listed ticket from the raw source files by a second code
path and compares it with the page (C-21). A mismatch writes nothing.

A draft, never a delivery. The page says DRAFT first, carries no reviewer, and this package has no way to send, post or
queue it; an Outlook draft is a later step (W9) that a person reviews. No model is called.

It is built on B-71's inputs: the same ``Sources`` folders, the same per-client file checks and the same backup adapter.
The page is a list of records, not a measure of value: it makes no claim about money saved or incidents avoided.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

from adapters.backup import BackupMock
from adapters.base import AdapterError
from core.guard.classify import DataClass
from core.paths import REPO_ROOT
from workflows.reporting.digest.reconcile import reconcile_html
from workflows.reporting.digest.window import CHANNEL, TICKET_ID, DigestError, Metric, show, week_bounds
from workflows.reporting.health import DEFAULT_SOURCES, HealthError, Mismatch, SourceRef, Sources
from workflows.reporting.health.sources import check_client, check_date, digest, display_name, display_path, read_json

DEFAULT_OUT_DIR = REPO_ROOT / "build" / "digest"
DATA_CLASS = f"DC-{DataClass.DC2.value}"  # ids, channels, dates and counts about one client's service; no ticket text
BASIS = "fixture-based"
LABEL = "fixture-based, synthetic (invented tenants, devices and tickets); not a real client's records"
BANNER = "DRAFT. Not sent. A person reviews this digest before it goes anywhere."
PROTOTYPE = "Independently built prototype. Not affiliated with any vendor's or real company's systems."
DRAFT_NOTE = (
    "This draft has not been reviewed. Nothing was sent; a person decides whether and how it goes to the client."
)
SCHEMA_VERSION = 1
SECTIONS = ("tickets", "changes", "backup")
TITLES = {"tickets": "Tickets we closed", "changes": "Changes we found", "backup": "Backup jobs"}


class VerifyError(ValueError):
    """A draft does not match its record, or a number in it differs from its source."""


@dataclass(frozen=True, slots=True)
class ClosedTicket:
    id: str
    channel: str
    opened: str  # ISO date (UTC)
    closed: str  # ISO date (UTC); the ticket's last update stands in for the PSA completed date
    hours: float


@dataclass(frozen=True, slots=True)
class Digest:
    client: str
    display_name: str
    week: str
    week_start: str
    week_end: str
    generated_on: str
    available: dict[str, bool]
    has_backup: bool  # this client has a backup source file at all
    partial: dict[str, bool]  # the source is dated before the week ends, so later days are not included
    values: dict[str, Metric]
    tickets: tuple[ClosedTicket, ...]
    sources: tuple[SourceRef, ...]
    status: str = "draft"
    reviewed_by: str | None = None
    reviewed_on: str | None = None


# -- small helpers --------------------------------------------------------------------------------------------------
def _when(value: Any, what: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise HealthError(f"{what}: {value!r} is not an ISO 8601 time") from None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _round1(value: Fraction) -> float:
    return int((value * 10 + Fraction(1, 2)) // 1) / 10


def _ref(section: str, path: Path, as_of: str) -> SourceRef:
    return SourceRef(section, display_path(path), digest(path), as_of, LABEL)


def _own_file(sources: Sources, section: str, client: str) -> tuple[dict[str, Any], Path] | None:
    path = sources.path_for(section, client)
    if not path.is_file():
        return None
    data = read_json(path)
    if data.get("client") != client:
        raise HealthError(
            f"{path.name} belongs to another client ({data.get('client')!r}), not {client!r}; nothing was reported"
        )
    return data, path


# -- build ----------------------------------------------------------------------------------------------------------
def build_digest(client: str, week: str, *, generated_on: str, sources: Sources = DEFAULT_SOURCES) -> Digest:
    """The draft digest for one client and one ISO week. Reads that client's files only; writes nothing.

    ``generated_on`` is the date the draft is prepared (never the wall clock) and may not be before the week starts.
    """
    check_client(client)
    monday, sunday = week_bounds(week)
    try:
        prepared = check_date(generated_on, "generated_on")
    except HealthError as exc:
        raise DigestError(str(exc)) from None
    if prepared < monday:
        raise DigestError(f"generated_on {generated_on} is before the week {week}")
    values: dict[str, Metric] = {}
    available = {s: False for s in SECTIONS}
    partial = {s: False for s in SECTIONS}
    refs: list[SourceRef] = []
    closed: list[ClosedTicket] = []

    # tickets closed this week
    found = _own_file(sources, "tickets", client)
    if found is not None:
        data, path = found
        as_of = str(data.get("as_of", ""))
        as_of_day = _when(as_of, f"{path.name} as_of").date()
        if as_of_day >= monday:
            available["tickets"] = True
            partial["tickets"] = as_of_day < sunday
            rows: list[tuple[datetime, str, ClosedTicket]] = []
            seconds: list[int] = []
            for raw in data.get("tickets", []):
                if not isinstance(raw, dict) or raw.get("client") != client:
                    raise HealthError(f"{path.name} holds a ticket of another client; nothing was reported")
                if raw.get("status") != "resolved":
                    continue
                done = _when(raw.get("updated"), "ticket updated")
                if not monday <= done.date() <= sunday:
                    continue
                ticket_id, channel = raw.get("id"), raw.get("source")
                if not isinstance(ticket_id, str) or not TICKET_ID.fullmatch(ticket_id):
                    raise DigestError("a closed ticket has an id that is not a plain ticket id; nothing was reported")
                if not isinstance(channel, str) or not CHANNEL.fullmatch(channel):
                    raise DigestError("a closed ticket has a channel that is not a plain word; nothing was reported")
                opened = _when(raw.get("created"), "ticket created")
                elapsed = int((done - opened).total_seconds())
                seconds.append(elapsed)
                hours = _round1(Fraction(elapsed, 3600))
                rows.append(
                    (
                        done,
                        ticket_id,
                        ClosedTicket(ticket_id, channel, opened.date().isoformat(), done.date().isoformat(), hours),
                    )
                )
            closed = [t for _, _, t in sorted(rows, key=lambda r: (r[0], r[1]))]
            values["closed.count"] = len(closed)
            for channel, n in sorted(Counter(t.channel for t in closed).items()):
                values[f"closed.channel.{channel}"] = n
            values["closed.median_hours"] = _median_hours(sorted(seconds))
            for t in closed:
                values[f"row.{t.id}.hours"] = t.hours
            refs.append(_ref("tickets", path, as_of))

    # changes a baseline run found this week
    found = _own_file(sources, "baseline", client)
    if found is not None:
        data, path = found
        as_of = str(data.get("as_of", ""))
        if monday <= _when(as_of, f"{path.name} as_of").date() <= sunday:
            available["changes"] = True
            drift = data["drift"]
            ca = drift["ca"]
            values["chg.new"] = len(drift["new"])
            values["chg.resolved"] = len(drift["resolved"])
            values["chg.ca_changes"] = sum(
                len(ca[k]) for k in ("added", "removed", "state_changed", "assignments_changed")
            )
            refs.append(_ref("baseline", path, as_of))

    # backup jobs scheduled this week, through this client's adapter
    path = sources.path_for("backup", client)
    if path.is_file():
        try:
            adapter = BackupMock.for_fixture(client, sources.backup_dir)
        except AdapterError as exc:
            raise HealthError(f"backup source for {client!r} refused: {exc}") from None
        as_of = adapter.as_of
        as_of_day = _when(as_of, "backup asOf").date()
        if as_of_day >= monday:
            available["backup"] = True
            partial["backup"] = as_of_day < sunday
            result = adapter.list_jobs()
            if not result.ok or result.data is None:
                raise HealthError(f"cannot list backup jobs for {client!r}: {result.reason}")
            jobs = [j for j in result.data if monday <= _when(j.get("scheduledStart"), "backup job").date() <= sunday]
            count = Counter(str(j.get("status")) for j in jobs)
            values["backup.jobs"] = len(jobs)
            values["backup.success"] = count["success"]
            values["backup.failed"] = count["failed"]
            values["backup.missed"] = count["missed"]
            values["backup.other"] = len(jobs) - count["success"] - count["failed"] - count["missed"]
            refs.append(_ref("backup", path, as_of))

    if not any(sources.path_for(s, client).is_file() for s in ("tickets", "baseline", "backup")):
        raise DigestError(f"no source data for client {client!r}")
    return Digest(
        client=client,
        display_name=display_name(client),
        week=week,
        week_start=monday.isoformat(),
        week_end=sunday.isoformat(),
        generated_on=generated_on,
        available=available,
        has_backup=sources.path_for("backup", client).is_file(),
        partial=partial,
        values=values,
        tickets=tuple(closed),
        sources=tuple(refs),
    )


def _median_hours(seconds: list[int]) -> float | None:
    if not seconds:
        return None
    n = len(seconds)
    mid = Fraction(seconds[n // 2]) if n % 2 else Fraction(seconds[n // 2 - 1] + seconds[n // 2], 2)
    return _round1(mid / 3600)


# -- render ---------------------------------------------------------------------------------------------------------
_CSS = (
    "body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f6f7f9;color:#1d2330}"
    "main{max-width:880px;margin:0 auto;padding:16px}"
    ".banner{background:#fff4ce;border:2px solid #b58900;padding:10px 14px;font-weight:600;margin:0 0 16px}"
    "section{background:#fff;border:1px solid #d5d9e0;border-radius:6px;padding:12px 16px;margin:0 0 14px;"
    "overflow-x:auto}"
    "h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.1rem;margin:0 0 8px}"
    "table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:4px 8px;border-bottom:1px solid #e6e9ee;"
    "font-size:.92rem;vertical-align:top;word-break:break-word}"
    ".note{color:#4a5160;font-size:.85rem}"
    "@media (prefers-color-scheme:dark){body{background:#14171c;color:#e6e8ec}"
    "section{background:#1d2128;border-color:#323843}"
    "td,th{border-color:#323843}.note{color:#a8afbd}.banner{background:#4a3d00;color:#fff}}"
)


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _span(key: str, value: Metric) -> str:
    return f'<span data-metric="{_esc(key)}">{_esc(show(value))}</span>'


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _day(value: str) -> str:
    return date.fromisoformat(value).strftime("%d %b %Y").lstrip("0")


def _tickets_html(d: Digest) -> str:
    if not d.available["tickets"]:
        return (
            "<p>No ticket data for this week: the ticket export is dated before the week starts, so nothing is "
            "reported.</p>"
        )
    count = int(d.values["closed.count"] or 0)
    if count == 0:
        body = "<p>No tickets were closed this week.</p>"
    else:
        channels = ", ".join(
            f"{_span(k, v)} by {_esc(k.removeprefix('closed.channel.'))}"
            for k, v in d.values.items()
            if k.startswith("closed.channel.")
        )
        rows = "".join(
            f'<tr data-ticket="{_esc(t.id)}" data-channel="{_esc(t.channel)}" data-opened="{t.opened}" '
            f'data-closed="{t.closed}"><td>{_esc(t.id)}</td><td>{_esc(t.channel)}</td><td>{_day(t.opened)}</td>'
            f"<td>{_day(t.closed)}</td><td>{_span(f'row.{t.id}.hours', t.hours)}</td></tr>"
            for t in d.tickets
        )
        body = (
            f"<p>Closed tickets arrived: {channels}. Median hours from opened to closed: "
            f"{_span('closed.median_hours', d.values['closed.median_hours'])}.</p>"
            "<table><tr><th>Ticket</th><th>Arrived by</th><th>Opened</th><th>Closed</th><th>Hours to close</th></tr>"
            f"{rows}</table>"
            '<p class="note">Tickets are listed by number only. What each one was about is in the ticket system; '
            "its text is not copied here.</p>"
        )
    head = f"<p>We closed {_span('closed.count', count)} {_plural(count, 'ticket', 'tickets')} this week.</p>"
    note = (
        '<p class="note">The ticket export ends before the end of the week, so tickets closed after it are not '
        "included.</p>"
        if d.partial["tickets"]
        else ""
    )
    return head + body + note


def _changes_html(d: Digest) -> str:
    if not d.available["changes"]:
        return "<p>No tenant baseline run was recorded this week, so no changes are reported.</p>"
    return (
        "<p>The tenant baseline run this week, compared with the run before it, found "
        f"{_span('chg.new', d.values['chg.new'])} new findings, {_span('chg.resolved', d.values['chg.resolved'])} "
        f"resolved findings and {_span('chg.ca_changes', d.values['chg.ca_changes'])} Conditional Access changes "
        "for a person to confirm.</p>"
    )


def _backup_html(d: Digest) -> str:
    if not d.available["backup"]:
        if not d.has_backup:
            return "<p>There is no backup data for this client.</p>"
        return "<p>No backup data for this week: the backup source is dated before the week starts.</p>"
    v = d.values
    note = (
        '<p class="note">The backup source ends before the end of the week, so later jobs are not included.</p>'
        if d.partial["backup"]
        else ""
    )
    return (
        f"<p>Backup jobs scheduled this week: {_span('backup.jobs', v['backup.jobs'])}. "
        f"Succeeded {_span('backup.success', v['backup.success'])}, "
        f"failed {_span('backup.failed', v['backup.failed'])}, "
        f"missed {_span('backup.missed', v['backup.missed'])}, running or not yet due "
        f"{_span('backup.other', v['backup.other'])}.</p>{note}"
    )


def render_html(d: Digest) -> str:
    """One self-contained HTML page: no script, no link, no external resource."""
    parts = {"tickets": _tickets_html(d), "changes": _changes_html(d), "backup": _backup_html(d)}

    def attrs(s: str) -> str:
        if not d.available[s]:
            return ' data-status="no-data"'
        extra = "" if s == "changes" else f' data-partial="{"yes" if d.partial[s] else "no"}"'
        return f' data-status="data"{extra}'

    sections = "\n".join(
        f'<section data-section="{s}"{attrs(s)}><h2>{_esc(TITLES[s])}</h2>{parts[s]}</section>' for s in SECTIONS
    )
    rows = "".join(
        f'<tr data-source="{_esc(r.section)}"><td>{_esc(r.path)}</td><td>{r.sha256}</td><td>{_esc(r.as_of)}</td>'
        f"<td>{_esc(r.label)}</td></tr>"
        for r in d.sources
    )
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>DRAFT - What we did for you - {_esc(d.display_name)} - {_esc(d.week)}</title>"
        f"<style>{_CSS}</style></head><body>\n"
        f'<main data-client="{_esc(d.client)}" data-week="{_esc(d.week)}" data-generated-on="{_esc(d.generated_on)}" '
        f'data-report-status="{d.status}">\n'
        f'<p class="banner">{_esc(BANNER)}</p>\n'
        f"<h1>What we did for you this week: {_esc(d.display_name)}, {_esc(d.week)}</h1>\n"
        f'<p class="note">Week {_esc(d.week)}, {_day(d.week_start)} to {_day(d.week_end)}. Prepared '
        f"{_esc(d.generated_on)}. Data classification {DATA_CLASS}. All figures are {BASIS} and synthetic. This is a "
        f"list of records, not a measure of value. {_esc(PROTOTYPE)}</p>\n"
        f"{sections}\n"
        '<section data-section="sources"><h2>Sources</h2>'
        '<p class="note">Everything above is computed from these files. Sources dated outside the week are not '
        "listed because nothing is taken from them.</p>"
        "<table><tr><th>File</th><th>SHA-256</th><th>Dated</th><th>Basis</th></tr>"
        f"{rows}</table></section>\n"
        f'<p class="note">{_esc(DRAFT_NOTE)} Reviewed by: nobody yet.</p>\n'
        "</main></body></html>\n"
    )


def digest_to_dict(d: Digest) -> dict[str, Any]:
    """The digest as plain data (for the JSON record)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "status": d.status,
        "reviewed_by": d.reviewed_by,
        "reviewed_on": d.reviewed_on,
        "client": d.client,
        "display_name": d.display_name,
        "week": d.week,
        "week_start": d.week_start,
        "week_end": d.week_end,
        "generated_on": d.generated_on,
        "data_class": DATA_CLASS,
        "data_basis": BASIS,
        "label": LABEL,
        "available": dict(d.available),
        "partial": dict(d.partial),
        "values": dict(d.values),
        "closed_tickets": [
            {"id": t.id, "channel": t.channel, "opened": t.opened, "closed": t.closed, "hours": t.hours}
            for t in d.tickets
        ],
        "sources": [
            {"section": r.section, "path": r.path, "sha256": r.sha256, "as_of": r.as_of, "label": r.label}
            for r in d.sources
        ],
    }


# -- write and verify -----------------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Draft:
    html_path: Path
    json_path: Path
    sha256: str


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(body: dict[str, Any]) -> bytes:
    return (json.dumps(body, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def _problems(found: Sequence[Mismatch]) -> str:
    return "; ".join(f"{m.key}: expected {m.expected!r}, digest shows {m.shown!r}" for m in found[:6])


def create_draft(
    client: str,
    week: str,
    *,
    generated_on: str,
    out_dir: Path = DEFAULT_OUT_DIR,
    sources: Sources = DEFAULT_SOURCES,
) -> Draft:
    """Build, render, reconcile, then write ``<out>/<week>/<client>.draft.html`` and ``.draft.json``.

    If any number or listed ticket differs from its source, nothing is written and ``DigestError`` names the figures.
    """
    item = build_digest(client, week, generated_on=generated_on, sources=sources)
    page = render_html(item)
    found = reconcile_html(page, sources)
    if found:
        raise DigestError(f"digest does not reconcile with its sources, nothing written: {_problems(found)}")
    data = page.encode("utf-8")
    digest_hex = _sha(data)
    body = digest_to_dict(item) | {"html_sha256": digest_hex, "note": DRAFT_NOTE}
    folder = Path(out_dir) / week
    folder.mkdir(parents=True, exist_ok=True)
    html_path = folder / f"{client}.draft.html"
    json_path = folder / f"{client}.draft.json"
    html_path.write_bytes(data)
    json_path.write_bytes(_json_bytes(body))
    return Draft(html_path, json_path, digest_hex)


def verify_draft(html_path: Path, *, sources: Sources = DEFAULT_SOURCES) -> None:
    """Re-check a draft: its bytes against its record, then every number, ticket and source hash against the files."""
    html_path = Path(html_path)
    json_path = html_path.with_name(html_path.name.removesuffix(".html") + ".json")
    try:
        data = html_path.read_bytes()
        record = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VerifyError(f"cannot read the draft or its record: {exc}") from None
    if not isinstance(record, dict) or record.get("html_sha256") != _sha(data):
        raise VerifyError("the draft's hash does not match its record: the file was changed after it was written")
    found = reconcile_html(data.decode("utf-8"), sources)
    if found:
        raise VerifyError(f"digest does not reconcile with its sources: {_problems(found)}")


# -- command line ---------------------------------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.reporting.digest", description="Weekly 'what we did for you' digest (draft)."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="write a draft digest for one client, or --all clients (one digest each)")
    build.add_argument("client", nargs="?", help="client id, e.g. contoso-dental")
    build.add_argument("--all", action="store_true", help="every client in the ticket folder, each digested alone")
    build.add_argument("--week", required=True, help="ISO week, e.g. 2026-W42")
    build.add_argument("--generated-on", default=None, help="ISO date the draft is prepared (default: today, UTC)")
    build.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    ver = sub.add_parser("verify", help="re-check a written draft against its record and its source files")
    ver.add_argument("draft", type=Path, help="path to <client>.draft.html")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            if not args.draft.is_file():
                print(f"error: no such draft: {args.draft}", file=sys.stderr)
                return 2
            try:
                verify_draft(args.draft)
            except VerifyError as exc:
                print(f"MISMATCH: {exc}", file=sys.stderr)
                return 1
            print(f"OK {args.draft.name}")
            return 0
        if args.all == (args.client is not None):
            print("error: give a client id or --all, not both", file=sys.stderr)
            return 2
        on = args.generated_on or datetime.now(UTC).date().isoformat()
        clients = sorted(p.stem for p in DEFAULT_SOURCES.tickets_dir.glob("*.json")) if args.all else [args.client]
        for client in clients:
            draft = create_draft(client, args.week, generated_on=on, out_dir=args.out)
            print(
                json.dumps({"client": client, "html": str(draft.html_path), "sha256": draft.sha256, "status": "draft"})
            )
    except HealthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
