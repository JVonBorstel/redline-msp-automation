"""Monthly client health report with reconciliation (B-71, specs/B-71.md; W-RPT-01, W-SEC-10; C-21, C-27, C-41).

For one client and one calendar month this reads the client's own synthetic tickets, tenant baseline, patch status,
backup jobs and security-awareness figures, computes plain counts from them, and writes one HTML draft and a JSON
record. Before anything is written, ``reconcile.reconcile_html`` recomputes every number from the raw source files by a
second, separate code path and compares it with what the HTML shows (C-21). A mismatch fails the run and nothing is
written.

A draft, never a delivery. The report says DRAFT, carries no reviewer, and this module has no way to send, post or
queue it: a person reads it and decides what happens next. Nothing here changes a ticket, tenant, device or backup.

Isolation (C-27). One client at a time. Every source file must name the client being reported, and a ticket that names
another client refuses the run. Backup jobs go through that client's adapter, which already drops other organizations'
rows. There is no MSP-wide report.

Untrusted text. Ticket subjects, bodies, requesters and labels are never read. The only free text that reaches the HTML
is fixed wording, the client's display name, and a rephrased summary, which is escaped and accepted only if it
keeps every computed figure (``policy.check_rephrase``).

Every figure is fixture-based and says so.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

from adapters.backup import BackupMock
from adapters.base import AdapterError
from core.gateway import Gateway
from core.guard.classify import DataClass
from core.paths import REPO_ROOT
from workflows.reporting.health import policy
from workflows.reporting.health.policy import Metric, Metrics
from workflows.reporting.health.reconcile import Mismatch, reconcile_html
from workflows.reporting.health.sources import (
    DEFAULT_SOURCES,
    HealthError,
    Sources,
    check_client,
    check_date,
    digest,
    display_name,
    display_path,
    parse_period,
    period_label,
    read_json,
)

DEFAULT_OUT_DIR = REPO_ROOT / "build" / "client-health"
DATA_CLASS = f"DC-{DataClass.DC2.value}"  # counts about one client's service; no names or ticket text
BASIS = "fixture-based"
LABEL = "fixture-based, synthetic (invented tenants, devices, tickets and campaigns); not a real client's results"
BANNER = "DRAFT. Not sent. A person reviews this report before it goes anywhere."
PROTOTYPE = "Independently built prototype. Not affiliated with any vendor's or real company's systems."
DRAFT_NOTE = (
    "This draft has not been reviewed. Nothing was sent; a person decides whether and how it goes to the client."
)
SCHEMA_VERSION = 1
AGENT = "health-report"


class VerifyError(ValueError):
    """A draft does not match its record, or a number in it differs from its source."""


@dataclass(frozen=True, slots=True)
class SourceRef:
    section: str
    path: str
    sha256: str
    as_of: str
    label: str


@dataclass(frozen=True, slots=True)
class Section:
    key: str
    title: str
    available: bool
    status: str  # healthy | attention | no-data
    metrics: dict[str, Metric]
    reasons: tuple[str, ...]  # ids of the policy rules that fired
    notes: tuple[str, ...]
    sources: tuple[SourceRef, ...]
    unavailable: str = ""


@dataclass(frozen=True, slots=True)
class Summary:
    text: str
    origin: str  # computed | rephrased
    computed_text: str
    facts: tuple[str, ...]
    note: str


@dataclass(frozen=True, slots=True)
class HealthReport:
    client: str
    display_name: str
    period: str
    generated_on: str
    sections: tuple[Section, ...]
    summary: Summary
    status: str = "draft"
    reviewed_by: str | None = None
    reviewed_on: str | None = None

    @property
    def period_label(self) -> str:
        return period_label(self.period)


@dataclass(frozen=True, slots=True)
class Draft:
    html_path: Path
    json_path: Path
    sha256: str


SECTION_KEYS = policy.SECTION_KEYS
METRIC_LABELS = policy.METRIC_LABELS


# -- small arithmetic -----------------------------------------------------------------------------------------------
def _pct(part: int, whole: int) -> float | None:
    """Percentage to one decimal, half up; None when there is nothing to divide by."""
    if whole == 0:
        return None
    return float((Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _median_hours(seconds: list[int]) -> float | None:
    if not seconds:
        return None
    ordered = sorted(seconds)
    mid = len(ordered) // 2
    middle = Fraction(ordered[mid]) if len(ordered) % 2 else Fraction(ordered[mid - 1] + ordered[mid], 2)
    hours = middle / 3600
    return _round1(hours)


def _round1(value: Fraction) -> float:
    tenths = (value * 10 + Fraction(1, 2)) // 1
    return int(tenths) / 10


def _when(value: Any, what: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise HealthError(f"{what}: {value!r} is not an ISO 8601 time") from None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _month(value: Any, what: str) -> str:
    return _when(value, what).strftime("%Y-%m")


def _int(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HealthError(f"{what} must be a whole number of 0 or more, got {value!r}")
    return value


def _list(data: dict[str, Any], key: str, what: str) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list):
        raise HealthError(f"{what}: {key!r} must be a list")
    return value


def _dict(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HealthError(f"{what} must be an object")
    return value


# -- sections -------------------------------------------------------------------------------------------------------
def _ref(section: str, path: Path, as_of: str, label: str) -> SourceRef:
    return SourceRef(section, display_path(path), digest(path), as_of, label)


def _empty(key: str, why: str, sources: tuple[SourceRef, ...] = ()) -> Section:
    return Section(key, policy.SECTION_TITLES[key], False, "no-data", {}, (), (), sources, why)


def _finish(key: str, metrics: dict[str, Metric], notes: tuple[str, ...], ref: SourceRef) -> Section:
    return Section(
        key,
        policy.SECTION_TITLES[key],
        True,
        policy.status_of(key, metrics),
        metrics,
        policy.firing(key, metrics),
        notes,
        (ref,),
    )


def _open_source(
    key: str, client: str, period: str, sources: Sources, as_of_key: str
) -> tuple[dict[str, Any], Path, str] | Section:
    """The client's source file, or the "no data" section that explains why there is none (missing, other period)."""
    path = sources.path_for(key, client)
    if not path.is_file():
        return _empty(key, f"no source file for this client ({path.name})")
    data = read_json(path)
    if data.get("client") != client:
        raise HealthError(
            f"{path.name} belongs to another client ({data.get('client')!r}), not {client!r}; nothing was reported"
        )
    as_of = str(data.get(as_of_key, ""))
    if _month(as_of, f"{path.name} {as_of_key}") != period:
        ref = _ref(key, path, as_of, LABEL)
        return _empty(key, f"source dated {as_of} is outside the period {period}", (ref,))
    return data, path, as_of


def _tickets(client: str, period: str, sources: Sources) -> Section:
    opened = _open_source("tickets", client, period, sources, "as_of")
    if isinstance(opened, Section):
        return opened
    data, path, as_of = opened
    rows = []
    for raw in _list(data, "tickets", path.name):
        ticket = _dict(raw, "a ticket")
        if ticket.get("client") != client:
            raise HealthError(f"{path.name} holds a ticket of another client; nothing was reported")
        if _month(ticket.get("created"), "ticket created") == period:
            rows.append(ticket)
    done = [t for t in rows if t.get("status") == "resolved"]
    seconds = [
        int((_when(t["updated"], "ticket updated") - _when(t["created"], "ticket created")).total_seconds())
        for t in done
    ]
    metrics: dict[str, Metric] = {
        "tickets.opened": len(rows),
        "tickets.resolved": len(done),
        "tickets.open": len(rows) - len(done),
        "tickets.resolved_pct": _pct(len(done), len(rows)),
        "tickets.median_hours_to_resolve": _median_hours(seconds),
    }
    for channel, n in sorted(Counter(str(t.get("source")) for t in rows).items()):
        metrics[f"{policy.CHANNEL_PREFIX}{channel}"] = n
    notes = (
        "Counted by the date each ticket was opened. The last update of a resolved ticket stands in for the PSA "
        "completed date. Ticket text and people are not used.",
    )
    return _finish("tickets", metrics, notes, _ref("tickets", path, as_of, LABEL))


def _baseline(client: str, period: str, sources: Sources) -> Section:
    opened = _open_source("baseline", client, period, sources, "as_of")
    if isinstance(opened, Section):
        return opened
    data, path, as_of = opened
    findings = [_dict(f, "a finding") for f in _list(data, "findings", path.name)]
    drift = _dict(data.get("drift"), "drift")
    severity = Counter(str(f.get("Severity")) for f in findings)
    ca = _dict(drift.get("ca"), "drift.ca")
    metrics: dict[str, Metric] = {
        "baseline.findings": len(findings),
        "baseline.high": severity["High"],
        "baseline.medium": severity["Medium"],
        "baseline.low": severity["Low"],
        "baseline.new": len(_list(drift, "new", "drift")),
        "baseline.resolved": len(_list(drift, "resolved", "drift")),
        "baseline.unchanged": len(_list(drift, "unchanged", "drift")),
        "baseline.ca_changes": sum(
            len(_list(ca, k, "drift.ca")) for k in ("added", "removed", "state_changed", "assignments_changed")
        ),
    }
    notes = (
        f"From the tenant baseline run of {as_of}, compared with the run of {drift.get('compared_to')}. Conditional "
        "Access "
        "changes are reported for a person to confirm; they are never proposed as fixes.",
    )
    return _finish("baseline", metrics, notes, _ref("baseline", path, as_of, LABEL))


def _patching(client: str, period: str, sources: Sources) -> Section:
    opened = _open_source("patching", client, period, sources, "as_of")
    if isinstance(opened, Section):
        return opened
    data, path, as_of = opened
    devices = [_dict(d, "a device") for d in _list(data, "devices", path.name)]
    today = _when(as_of, "patching as_of").date()
    clean = critical = updates = stale = 0
    for dev in devices:
        pending_critical = _int(dev.get("pending_critical"), "pending_critical")
        pending_other = _int(dev.get("pending_other"), "pending_other")
        if pending_critical == 0 and pending_other == 0:
            clean += 1
        critical += 1 if pending_critical else 0
        updates += pending_critical
        age = (today - check_date(str(dev.get("last_patched")), "last_patched")).days
        stale += 1 if age > policy.PATCH_STALE_DAYS else 0
    metrics: dict[str, Metric] = {
        "patching.devices": len(devices),
        "patching.up_to_date": clean,
        "patching.up_to_date_pct": _pct(clean, len(devices)),
        "patching.critical_pending_devices": critical,
        "patching.critical_pending_updates": updates,
        "patching.not_patched_30d": stale,
    }
    notes = (
        "Patch status in a neutral shape of this repository's own; no patch tool or RMM format is claimed "
        "(UNVERIFIED).",
    )
    return _finish("patching", metrics, notes, _ref("patching", path, as_of, LABEL))


def _backup(client: str, period: str, sources: Sources) -> Section:
    path = sources.path_for("backup", client)
    if not path.is_file():
        return _empty("backup", f"no source file for this client ({path.name})")
    try:
        adapter = BackupMock.for_fixture(client, sources.backup_dir)
    except AdapterError as exc:
        raise HealthError(f"backup source for {client!r} refused: {exc}") from None
    as_of = adapter.as_of
    ref = _ref("backup", path, as_of, LABEL)
    if _month(as_of, "backup asOf") != period:
        return _empty("backup", f"source dated {as_of} is outside the period {period}", (ref,))
    result = adapter.list_jobs()
    if not result.ok or result.data is None:
        raise HealthError(f"cannot list backup jobs for {client!r}: {result.reason}")
    jobs = [j for j in result.data if _month(j.get("scheduledStart"), "backup job") == period]
    status = Counter(str(j.get("status")) for j in jobs)
    boot_failed = sum(
        1 for j in jobs if isinstance(j.get("bootCheck"), dict) and j["bootCheck"].get("status") == "failed"
    )
    ok = status["success"]
    metrics: dict[str, Metric] = {
        "backup.jobs": len(jobs),
        "backup.success": ok,
        "backup.failed": status["failed"],
        "backup.missed": status["missed"],
        "backup.other": len(jobs) - ok - status["failed"] - status["missed"],
        "backup.boot_check_failed": boot_failed,
        "backup.success_pct": _pct(ok, len(jobs)),
    }
    notes = (
        "Jobs scheduled in the month, read through this client's backup adapter. The vendor's field names are "
        "UNVERIFIED.",
    )
    return _finish("backup", metrics, notes, ref)


def _awareness(client: str, period: str, sources: Sources) -> Section:
    opened = _open_source("awareness", client, period, sources, "as_of")
    if isinstance(opened, Section):
        return opened
    data, path, as_of = opened
    if data.get("level") != "service":
        raise HealthError(f"{path.name} must be service-level (level 'service'), not {data.get('level')!r}")
    services = _dict(data.get("services"), "services")
    phish = _dict(services.get("phishing_simulation"), "phishing_simulation")
    vault = _dict(services.get("password_vault"), "password_vault")
    for name, svc in (("phishing_simulation", phish), ("password_vault", vault)):
        if svc.get("vendor") != "UNVERIFIED":
            raise HealthError(f"{path.name}: the {name} vendor must stay UNVERIFIED (U-04), got {svc.get('vendor')!r}")
    month_campaigns = [
        _dict(c, "a campaign")
        for c in _list(phish, "campaigns", "phishing_simulation")
        if _month(f"{c.get('launched')}T00:00:00Z", "campaign launched") == period
    ]
    sent = sum(_int(c.get("sent"), "sent") for c in month_campaigns)
    clicked = sum(_int(c.get("clicked"), "clicked") for c in month_campaigns)
    reported = sum(_int(c.get("reported"), "reported") for c in month_campaigns)
    total = _int(vault.get("users_total"), "users_total")
    enrolled = _int(vault.get("users_enrolled"), "users_enrolled")
    metrics: dict[str, Metric] = {
        "phish.campaigns": len(month_campaigns),
        "phish.sent": sent,
        "phish.clicked": clicked,
        "phish.reported": reported,
        "phish.click_pct": _pct(clicked, sent),
        "phish.report_pct": _pct(reported, sent),
        "vault.audit_score": _int(vault.get("audit_score"), "audit_score"),
        "vault.users_total": total,
        "vault.users_enrolled": enrolled,
        "vault.enrolled_pct": _pct(enrolled, total),
        "vault.mfa_enforced": "yes" if vault.get("mfa_enforced") is True else "no",
    }
    notes = (
        "Service-level figures for the phishing simulation (MP-24) and the password vault (MP-23). The vendors are "
        "UNVERIFIED and no vendor export format is assumed. Campaigns are counted by launch date.",
    )
    return _finish(
        "awareness", metrics, notes, _ref("awareness", path, as_of, "service-level, vendor UNVERIFIED; " + LABEL)
    )


_BUILDERS = {
    "tickets": _tickets,
    "baseline": _baseline,
    "patching": _patching,
    "backup": _backup,
    "awareness": _awareness,
}


# -- summary --------------------------------------------------------------------------------------------------------
def _prompt(name: str, label: str, computed: str, facts: tuple[str, ...]) -> str:
    phrases = "\n".join(f'- "{f}"' for f in facts)
    return (
        f"Rewrite the draft below in plain, friendly English for the owner of {name}, for {label}. Do not add, "
        "remove or "
        "change any figure, and do not write any figure out in words. Keep each of these phrases exactly as written:\n"
        f"{phrases}\nReply with one paragraph and nothing else.\nDRAFT:\n{computed}"
    )


def _summary(name: str, label: str, sections: tuple[Section, ...], gateway: Gateway | None) -> Summary:
    live = {s.key: s.metrics for s in sections if s.available}
    facts = policy.facts_for(live)
    computed = policy.computed_summary(
        name,
        label,
        facts,
        tuple(s.key for s in sections if s.status == "attention"),
        tuple(s.key for s in sections if s.status == "healthy"),
        tuple(s.key for s in sections if not s.available),
    )
    if gateway is None:
        return Summary(computed, "computed", computed, facts, "Built from the computed counts.")
    try:
        done = gateway.complete(
            "summarize", _prompt(name, label, computed, facts), data_class=DataClass.DC2, agent=AGENT
        )
    except Exception as exc:  # a model double or adapter bug must not stop a report that has its own computed text
        return Summary(
            computed, "computed", computed, facts, f"rephrase skipped: {type(exc).__name__}; computed text kept."
        )
    if not done.ok:
        why = " ".join(str(done.error).split())[:160]
        return Summary(computed, "computed", computed, facts, f"rephrase skipped: {why}; computed text kept.")
    problem = policy.check_rephrase(done.text, computed, facts, label)
    if problem is not None:
        return Summary(computed, "computed", computed, facts, f"rephrase rejected: {problem}; computed text kept.")
    note = (
        f"Rephrased through the model gateway ({done.provider}); every figure was checked against the computed summary."
    )
    return Summary(done.text.strip(), "rephrased", computed, facts, note)


# -- build ----------------------------------------------------------------------------------------------------------
def build_report(
    client: str,
    period: str,
    *,
    generated_on: str,
    sources: Sources = DEFAULT_SOURCES,
    gateway: Gateway | None = None,
) -> HealthReport:
    """The draft report for one client and one month. Reads that client's files only; writes nothing.

    ``generated_on`` is the date the draft is prepared (never the wall clock). ``gateway``, when given, may rephrase the
    summary; the rephrase is kept only if it carries exactly the computed figures.
    """
    check_client(client)
    year, month = parse_period(period)
    prepared = check_date(generated_on, "generated_on")
    if (prepared.year, prepared.month) < (year, month):
        raise HealthError(f"generated_on {generated_on} is before the period {period}")
    sections = tuple(_BUILDERS[key](client, period, sources) for key in SECTION_KEYS)
    if not any(s.sources for s in sections):
        raise HealthError(f"no source data for client {client!r}")
    name = display_name(client)
    return HealthReport(
        client=client,
        display_name=name,
        period=period,
        generated_on=generated_on,
        sections=sections,
        summary=_summary(name, period_label(period), sections, gateway),
    )


# -- render ---------------------------------------------------------------------------------------------------------
_CSS = (
    "body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f6f7f9;color:#1d2330}"
    "main{max-width:880px;margin:0 auto;padding:16px}"
    ".banner{background:#fff4ce;border:2px solid #b58900;padding:10px 14px;font-weight:600;margin:0 0 16px}"
    "section{background:#fff;border:1px solid #d5d9e0;border-radius:6px;padding:12px 16px;margin:0 0 14px}"
    "h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.1rem;margin:0 0 8px}"
    "table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:4px 8px;border-bottom:1px solid #e6e9ee;"
    "font-size:.92rem;vertical-align:top;word-break:break-word}"
    ".pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:.8rem;font-weight:600}"
    ".healthy{background:#dff3e3;color:#1b5e2b}.attention{background:#fde2e0;color:#8a1c14}.no-data{background:#e8e8e8;color:#444}"
    ".note{color:#4a5160;font-size:.85rem}"
    "@media (prefers-color-scheme:dark){body{background:#14171c;color:#e6e8ec}"
    "section{background:#1d2128;border-color:#323843}"
    "td,th{border-color:#323843}.note{color:#a8afbd}.banner{background:#4a3d00;color:#fff}}"
)


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _span(key: str, value: Metric) -> str:
    return f'<span data-metric="{_esc(key)}">{_esc(policy.show(value))}</span>'


def _templated(template: str, metrics: Metrics) -> str:
    out: list[str] = []
    last = 0
    for match in re.finditer(r"\{([a-z_0-9.]+)\}", template):
        out.append(_esc(template[last : match.start()]))
        out.append(_span(match.group(1), metrics.get(match.group(1))))
        last = match.end()
    out.append(_esc(template[last:]))
    return "".join(out)


def _section_html(section: Section) -> str:
    head = (
        f'<section data-section="{section.key}" data-status="{section.status}">'
        f'<h2>{_esc(section.title)} <span class="pill {section.status}">{section.status.replace("-", " ")}</span></h2>'
    )
    if not section.available:
        return (
            head
            + f'<p class="note" data-unavailable>No data for this period: {_esc(section.unavailable)}.</p></section>'
        )
    rows = "".join(
        f'<tr><th scope="row">{_esc(policy.label_for(key))}</th><td>{_span(key, value)}</td></tr>'
        for key, value in section.metrics.items()
    )
    reasons = "".join(
        f'<li data-reason="{rid}">{_templated(policy.RULES_BY_ID[rid].template, section.metrics)}</li>'
        for rid in section.reasons
    )
    why = f"<ul>{reasons}</ul>" if reasons else '<p class="note">No concerns from the rules below.</p>'
    notes = "".join(f'<p class="note">{_esc(n)}</p>' for n in section.notes)
    return head + f"<table>{rows}</table>{why}{notes}</section>"


def render_html(report: HealthReport) -> str:
    """One self-contained HTML page: no script, no link, no external resource."""
    data_sources = "".join(
        f'<tr data-source="{ref.section}"><td>{_esc(ref.path)}</td><td>{ref.sha256}</td><td>{_esc(ref.as_of)}</td>'
        f"<td>{_esc(ref.label)}</td></tr>"
        for section in report.sections
        for ref in section.sources
    )
    summary = report.summary
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Client health report - {_esc(report.display_name)} - {_esc(report.period)}</title>"
        f"<style>{_CSS}</style></head><body>\n"
        f'<main data-client="{_esc(report.client)}" data-period="{_esc(report.period)}" '
        f'data-generated-on="{_esc(report.generated_on)}" data-report-status="{report.status}">\n'
        f'<p class="banner">{_esc(BANNER)}</p>\n'
        f"<h1>Client health report: {_esc(report.display_name)}, {_esc(report.period_label)}</h1>\n"
        f'<p class="note">Period {_esc(report.period)} ({_esc(report.period_label)}). '
        f"Prepared {_esc(report.generated_on)}. "
        f"Data classification {DATA_CLASS}. All figures are {BASIS} and synthetic. {_esc(PROTOTYPE)}</p>\n"
        '<section data-section="summary"><h2>Summary</h2>'
        f'<p data-summary="{summary.origin}">{_esc(summary.text)}</p>'
        f'<p class="note" data-summary-note>{_esc(summary.note)}</p></section>\n'
        + "\n".join(_section_html(s) for s in report.sections)
        + '\n<section data-section="sources"><h2>Sources and period</h2>'
        f'<p class="note">Everything above is computed from these files for the period {_esc(report.period)}. '
        "A figure that cannot be traced to one of them does not belong in this report.</p>"
        "<table><tr><th>File</th><th>SHA-256</th><th>Dated</th><th>Basis</th></tr>"
        f"{data_sources}</table></section>\n"
        f'<p class="note">{_esc(DRAFT_NOTE)} Reviewed by: nobody yet.</p>\n'
        "</main></body></html>\n"
    )


def report_to_dict(report: HealthReport) -> dict[str, Any]:
    """The report as plain data (for the JSON record and for other workflows that build on it)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "status": report.status,
        "reviewed_by": report.reviewed_by,
        "reviewed_on": report.reviewed_on,
        "client": report.client,
        "display_name": report.display_name,
        "period": report.period,
        "period_label": report.period_label,
        "generated_on": report.generated_on,
        "data_class": DATA_CLASS,
        "data_basis": BASIS,
        "label": LABEL,
        "summary": {
            "text": report.summary.text,
            "origin": report.summary.origin,
            "computed_text": report.summary.computed_text,
            "facts": list(report.summary.facts),
            "note": report.summary.note,
        },
        "sections": [
            {
                "key": s.key,
                "title": s.title,
                "available": s.available,
                "status": s.status,
                "reasons": list(s.reasons),
                "metrics": dict(s.metrics),
                "notes": list(s.notes),
                "unavailable": s.unavailable,
                "sources": [
                    {"path": r.path, "sha256": r.sha256, "as_of": r.as_of, "label": r.label} for r in s.sources
                ],
            }
            for s in report.sections
        ],
    }


# -- write and verify -----------------------------------------------------------------------------------------------
def _json_bytes(body: dict[str, Any]) -> bytes:
    return (json.dumps(body, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def _problems(found: Sequence[Mismatch]) -> str:
    return "; ".join(f"{m.key}: expected {m.expected!r}, report shows {m.shown!r}" for m in found[:6])


def create_draft(
    client: str,
    period: str,
    *,
    generated_on: str,
    out_dir: Path = DEFAULT_OUT_DIR,
    sources: Sources = DEFAULT_SOURCES,
    gateway: Gateway | None = None,
) -> Draft:
    """Build, render, reconcile, then write ``<out>/<period>/<client>.draft.html`` and ``.draft.json``.

    The reconciliation runs on the final HTML (after any rephrase). If any number differs from its source, nothing is
    written and ``HealthError`` names the figures.
    """
    report = build_report(client, period, generated_on=generated_on, sources=sources, gateway=gateway)
    page = render_html(report)
    found = reconcile_html(page, sources)
    if found:
        raise HealthError(f"report does not reconcile with its sources, nothing written: {_problems(found)}")
    data = page.encode("utf-8")
    digest_hex = _sha(data)
    body = report_to_dict(report) | {"html_sha256": digest_hex, "note": DRAFT_NOTE}
    folder = Path(out_dir) / period
    folder.mkdir(parents=True, exist_ok=True)
    html_path = folder / f"{client}.draft.html"
    json_path = folder / f"{client}.draft.json"
    html_path.write_bytes(data)
    json_path.write_bytes(_json_bytes(body))
    return Draft(html_path, json_path, digest_hex)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_draft(html_path: Path, *, sources: Sources = DEFAULT_SOURCES) -> None:
    """Re-check a draft: its bytes against its record, then every number and source hash against the source files."""
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
        raise VerifyError(f"report does not reconcile with its sources: {_problems(found)}")


# -- command line ---------------------------------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.reporting.health", description="Monthly client health report (draft)."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser(
        "build", help="write a draft report for one client, or --all clients with data (one report each)"
    )
    build.add_argument("client", nargs="?", help="client id, e.g. contoso-dental")
    build.add_argument("--all", action="store_true", help="every client in the ticket folder, each reported alone")
    build.add_argument("--period", required=True, help="YYYY-MM")
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
            draft = create_draft(client, args.period, generated_on=on, out_dir=args.out)
            print(
                json.dumps({"client": client, "html": str(draft.html_path), "sha256": draft.sha256, "status": "draft"})
            )
    except HealthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
