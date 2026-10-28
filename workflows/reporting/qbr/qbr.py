"""Quarterly business review draft (B-72, specs/B-72.md; W-RPT-02; C-21, C-45).

For one client and one calendar quarter this builds the client's monthly health reports with B-71's public
``build_report`` (one per month, the quarter and the one before it), puts the quarter beside the previous quarter, shows
the months side by side as a trend, and lists wins, risks and suggestions that follow from those figures by fixed rules
(``policy.RULES``). Before anything is written, ``reconcile.reconcile_html`` recomputes every figure from the raw source
files by a second code path and compares it with what the page shows (C-21). A mismatch writes nothing.

A draft, never a delivery. The page says DRAFT first, carries no reviewer, and this package has no way to send, post or
queue it: an account manager reads it, changes it and decides what happens next. No model is called.

Isolation (C-27). One client at a time, through B-71, which refuses a source file that names another client. There is
no MSP-wide review.

Every figure is fixture-based and says so. Nothing in the page claims a saving, a cost or an avoided incident.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from core.guard.classify import DataClass
from core.paths import REPO_ROOT
from workflows.reporting.health import HealthError, Mismatch, SourceRef, build_report
from workflows.reporting.health.sources import check_client, check_date, display_name
from workflows.reporting.qbr import policy
from workflows.reporting.qbr.policy import Context, Metric, QbrError
from workflows.reporting.qbr.reconcile import reconcile_html
from workflows.reporting.qbr.sources import DEFAULT_QBR_SOURCES, QbrSources

DEFAULT_OUT_DIR = REPO_ROOT / "build" / "qbr"
DATA_CLASS = f"DC-{DataClass.DC2.value}"  # counts about one client's service; no names or ticket text
BASIS = "fixture-based"
LABEL = "fixture-based, synthetic (invented tenants, devices, tickets and campaigns); not a real client's results"
BANNER = "DRAFT. Not sent. A person reviews this review before it goes anywhere."
PROTOTYPE = "Independently built prototype. Not affiliated with any vendor's or real company's systems."
DRAFT_NOTE = (
    "This draft has not been reviewed. Nothing was sent; a person decides whether and how it goes to the client."
)
SCHEMA_VERSION = 1


class VerifyError(ValueError):
    """A draft does not match its record, or a number in it differs from its source."""


@dataclass(frozen=True, slots=True)
class MonthSource:
    month: str
    ref: SourceRef


@dataclass(frozen=True, slots=True)
class Item:
    id: str
    text: str  # plain text, figures filled in


@dataclass(frozen=True, slots=True)
class Qbr:
    client: str
    display_name: str
    quarter: str
    previous_quarter: str
    generated_on: str
    months: tuple[str, ...]  # the months of ``quarter``
    values: dict[str, Metric]  # every figure on the page, keyed as in ``policy`` (q.*, m.*, d.*, cov.*)
    wins: tuple[str, ...]
    risks: tuple[str, ...]
    suggestions: tuple[str, ...]
    sources: tuple[MonthSource, ...]
    status: str = "draft"
    reviewed_by: str | None = None
    reviewed_on: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


# -- arithmetic -----------------------------------------------------------------------------------------------------
def _pct(part: int, whole: int) -> float | None:
    if whole == 0:
        return None
    return float((Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _as_int(value: Metric) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise QbrError(f"expected a whole number from the health report, got {value!r}")
    return value


# -- months and quarters --------------------------------------------------------------------------------------------
# month -> section -> metrics (only the sections that have data in that month)
Months = dict[str, dict[str, dict[str, Any]]]


def _read_months(
    client: str, months: Sequence[str], last: str, generated_on: str, sources: QbrSources
) -> tuple[Months, list[MonthSource]]:
    per_month: Months = {}
    refs: list[MonthSource] = []
    for month in months:
        if month > last:
            continue  # a month after the date the draft is prepared has not happened yet
        try:
            report = build_report(client, month, generated_on=generated_on, sources=sources.for_month(month))
        except HealthError as exc:
            if str(exc).startswith("no source data for client"):
                continue
            raise
        live = {s.key: s.metrics for s in report.sections if s.available}
        if live:
            per_month[month] = live
        refs.extend(MonthSource(month, ref) for s in report.sections if s.available for ref in s.sources)
    return per_month, refs


def _aggregate(per_month: Months) -> tuple[dict[str, Metric], dict[str, int]]:
    """(figure -> value, section -> months with data) for one quarter's months."""
    months = {s: [m for m in sorted(per_month) if s in per_month[m]] for s in policy.SECTIONS}
    cov = {s: len(v) for s, v in months.items()}
    values: dict[str, Metric] = {}
    for spec in policy.SPECS:
        have = months[spec.section]
        if spec.kind == "flow":
            values[spec.key] = sum(_as_int(per_month[m][spec.section][spec.key]) for m in have) if have else None
        elif spec.kind == "point":
            values[spec.key] = per_month[have[-1]][spec.section][spec.key] if have else None
    for spec in policy.SPECS:
        if spec.kind == "derived":
            num, den = values.get(spec.numerator), values.get(spec.denominator)
            values[spec.key] = _pct(_as_int(num), _as_int(den)) if num is not None and den is not None else None
    return values, cov


def parse_quarter_inputs(quarter: str, generated_on: str) -> tuple[tuple[str, ...], str]:
    months = policy.months_of(quarter)
    try:
        prepared = check_date(generated_on, "generated_on")
    except HealthError as exc:
        raise QbrError(str(exc)) from None
    if (prepared.year, prepared.month) < (int(months[0][:4]), int(months[0][5:])):
        raise QbrError(f"generated_on {generated_on} is before the quarter {quarter}")
    return months, f"{prepared.year}-{prepared.month:02d}"


def build_qbr(
    client: str,
    quarter: str,
    *,
    generated_on: str,
    sources: QbrSources = DEFAULT_QBR_SOURCES,
) -> Qbr:
    """The draft review for one client and one quarter. Reads that client's files only; writes nothing.

    ``generated_on`` is the date the draft is prepared (never the wall clock); months after it are not read.
    """
    check_client(client)
    months, last = parse_quarter_inputs(quarter, generated_on)
    previous = policy.previous_quarter(quarter)
    cur_months, cur_refs = _read_months(client, months, last, generated_on, sources)
    prev_months, prev_refs = _read_months(client, policy.months_of(previous), last, generated_on, sources)
    if not cur_months and not prev_months:
        raise QbrError(f"no source data for client {client!r} in {previous} or {quarter}")
    cur, cur_cov = _aggregate(cur_months)
    prev, prev_cov = _aggregate(prev_months)
    values: dict[str, Metric] = {}
    delta: dict[str, Metric] = {}
    for spec in policy.SPECS:
        values[policy.q_key(quarter, spec.key)] = cur[spec.key]
        values[policy.q_key(previous, spec.key)] = prev[spec.key]
        same = policy.comparable(spec, cur_cov[spec.section], prev_cov[spec.section])
        delta[spec.key] = policy.difference(cur[spec.key], prev[spec.key]) if same else None
        values[policy.d_key(spec.key)] = delta[spec.key]
    for section in policy.SECTIONS:
        values[policy.cov_key(quarter, section)] = cur_cov[section]
        values[policy.cov_key(previous, section)] = prev_cov[section]
    for month, live in cur_months.items():
        for spec in policy.SPECS:
            if spec.section in live:
                values[policy.m_key(month, spec.key)] = live[spec.section][spec.key]
    wins, risks, suggestions = policy.evaluate(Context(cur, delta, cur_cov))
    # one row per source actually used, in a fixed order
    used = sorted(cur_refs + prev_refs, key=lambda r: (r.month, policy.SECTIONS.index(r.ref.section)))
    return Qbr(
        client=client,
        display_name=display_name(client),
        quarter=quarter,
        previous_quarter=previous,
        generated_on=generated_on,
        months=months,
        values=values,
        wins=wins,
        risks=risks,
        suggestions=suggestions,
        sources=tuple(used),
    )


def item_text(report: Qbr, item_id: str) -> str:
    return policy.fill_item(item_id, report.quarter, report.values, policy.plain)


# -- render ---------------------------------------------------------------------------------------------------------
_CSS = (
    "body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f6f7f9;color:#1d2330}"
    "main{max-width:960px;margin:0 auto;padding:16px}"
    ".banner{background:#fff4ce;border:2px solid #b58900;padding:10px 14px;font-weight:600;margin:0 0 16px}"
    "section{background:#fff;border:1px solid #d5d9e0;border-radius:6px;padding:12px 16px;margin:0 0 14px;"
    "overflow-x:auto}"
    "h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.1rem;margin:0 0 8px}"
    "table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:4px 8px;border-bottom:1px solid #e6e9ee;"
    "font-size:.92rem;vertical-align:top;word-break:break-word}"
    ".note{color:#4a5160;font-size:.85rem}.gap{color:#444}"
    "@media (prefers-color-scheme:dark){body{background:#14171c;color:#e6e8ec}"
    "section{background:#1d2128;border-color:#323843}"
    "td,th{border-color:#323843}.note{color:#a8afbd}.banner{background:#4a3d00;color:#fff}}"
)


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _span(key: str, value: Metric) -> str:
    text = policy.signed(value) if key.startswith("d.") else policy.show(value)
    return f'<span data-metric="{_esc(key)}">{_esc(text)}</span>'


def _html_render(key: str | None, value: Metric | str) -> str:
    if key is None:
        return _esc(str(value))
    assert not isinstance(value, str)
    return _span(key, value)


def _list(name: str, ids: Sequence[str], report: Qbr, empty: str) -> str:
    rows = "".join(
        f'<li data-item="{_esc(i)}">{policy.fill_item(i, report.quarter, report.values, _html_render)}</li>'
        for i in ids
    )
    note = "" if ids else f'<p class="note">{_esc(empty)}</p>'
    return f'<ul data-list="{name}">{rows}</ul>{note}'


def _comparison_table(report: Qbr) -> str:
    q, p = report.quarter, report.previous_quarter
    rows = "".join(
        f'<tr><th scope="row">{_esc(spec.label)}</th>'
        f"<td>{_span(policy.q_key(q, spec.key), report.values[policy.q_key(q, spec.key)])}</td>"
        f"<td>{_span(policy.q_key(p, spec.key), report.values[policy.q_key(p, spec.key)])}</td>"
        f"<td>{_span(policy.d_key(spec.key), report.values[policy.d_key(spec.key)])}</td></tr>"
        for spec in policy.SPECS
    )
    return (
        f"<table><tr><th>Figure</th><th>{_esc(q)}</th><th>{_esc(p)}</th><th>Change</th></tr>{rows}</table>"
        '<p class="note">Counts (tickets, backup jobs, simulated emails) add up the months that have data. Latest-run '
        "figures (baseline findings, devices, vault score) are the last month with data. A change is shown only when "
        "both quarters have data for that part and, for counts, the same number of months; otherwise it says n/a.</p>"
    )


def _coverage_table(report: Qbr) -> str:
    q, p = report.quarter, report.previous_quarter
    rows = "".join(
        f'<tr><th scope="row">{_esc(policy.SECTION_TITLES[s])}</th>'
        f"<td>{_span(policy.cov_key(q, s), report.values[policy.cov_key(q, s)])}</td>"
        f"<td>{_span(policy.cov_key(p, s), report.values[policy.cov_key(p, s)])}</td></tr>"
        for s in policy.SECTIONS
    )
    return f"<table><tr><th>Months with data (of 3)</th><th>{_esc(q)}</th><th>{_esc(p)}</th></tr>{rows}</table>"


def _trend_table(report: Qbr) -> str:
    head = "".join(f"<th>{_esc(m)}</th>" for m in report.months)
    rows: list[str] = []
    for spec in policy.SPECS:
        cells = []
        for month in report.months:
            key = policy.m_key(month, spec.key)
            if key in report.values:
                cells.append(f"<td>{_span(key, report.values[key])}</td>")
            else:
                cells.append(f'<td data-nodata="m.{_esc(month)}" data-key="{_esc(key)}">no data</td>')
        rows.append(f'<tr><th scope="row">{_esc(spec.label)}</th>{"".join(cells)}</tr>')
    return f"<table><tr><th>Figure</th>{head}</tr>{''.join(rows)}</table>"


def render_html(report: Qbr) -> str:
    """One self-contained HTML page: no script, no link, no external resource."""
    data_sources = "".join(
        f'<tr data-source="{_esc(ms.month)}:{_esc(ms.ref.section)}"><td>{_esc(ms.ref.path)}</td>'
        f"<td>{ms.ref.sha256}</td><td>{_esc(ms.ref.as_of)}</td><td>{_esc(ms.ref.label)}</td></tr>"
        for ms in report.sources
    )
    title = f"Quarterly business review - {_esc(report.display_name)} - {_esc(report.quarter)}"
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>DRAFT - {title}</title>"
        f"<style>{_CSS}</style></head><body>\n"
        f'<main data-client="{_esc(report.client)}" data-quarter="{_esc(report.quarter)}" '
        f'data-generated-on="{_esc(report.generated_on)}" data-report-status="{report.status}">\n'
        f'<p class="banner">{_esc(BANNER)}</p>\n'
        f"<h1>Quarterly business review: {_esc(report.display_name)}, {_esc(report.quarter)}</h1>\n"
        f'<p class="note">Quarter {_esc(report.quarter)} compared with {_esc(report.previous_quarter)}. '
        f"Prepared {_esc(report.generated_on)}. Data classification {DATA_CLASS}. All figures are {BASIS} and "
        f"synthetic; a quarter still in progress only has the months that have data. {_esc(PROTOTYPE)}</p>\n"
        '<section data-section="comparison"><h2>This quarter against the last</h2>'
        f"{_comparison_table(report)}</section>\n"
        f'<section data-section="coverage"><h2>Which months have data</h2>{_coverage_table(report)}</section>\n'
        f'<section data-section="trend"><h2>Month by month</h2>{_trend_table(report)}</section>\n'
        '<section data-section="wins"><h2>Wins</h2>'
        + _list(
            "wins", report.wins, report, "No figure moved the right way by the rules, or there is nothing to compare."
        )
        + "</section>\n"
        '<section data-section="risks"><h2>Risks and gaps</h2>'
        + _list("risks", report.risks, report, "No risk or gap by the rules.")
        + "</section>\n"
        '<section data-section="recommendations"><h2>Suggestions to discuss</h2>'
        '<p class="note">Topics for the account manager to raise, one per risk above. They are not commitments and '
        "not predictions of results.</p>"
        + _list("recommendations", report.suggestions, report, "Nothing to raise by the rules.")
        + "</section>\n"
        '<section data-section="sources"><h2>Sources</h2>'
        '<p class="note">Everything above is computed from these files (health report inputs, one row per month and '
        "part that has data). A figure that cannot be traced to one of them does not belong in this review.</p>"
        "<table><tr><th>File</th><th>SHA-256</th><th>Dated</th><th>Basis</th></tr>"
        f"{data_sources}</table></section>\n"
        f'<p class="note">{_esc(DRAFT_NOTE)} Reviewed by: nobody yet.</p>\n'
        "</main></body></html>\n"
    )


def qbr_to_dict(report: Qbr) -> dict[str, Any]:
    """The review as plain data (for the JSON record)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "status": report.status,
        "reviewed_by": report.reviewed_by,
        "reviewed_on": report.reviewed_on,
        "client": report.client,
        "display_name": report.display_name,
        "quarter": report.quarter,
        "previous_quarter": report.previous_quarter,
        "generated_on": report.generated_on,
        "data_class": DATA_CLASS,
        "data_basis": BASIS,
        "label": LABEL,
        "values": dict(report.values),
        "wins": [{"id": i, "text": item_text(report, i)} for i in report.wins],
        "risks": [{"id": i, "text": item_text(report, i)} for i in report.risks],
        "suggestions": [{"id": i, "text": item_text(report, i)} for i in report.suggestions],
        "sources": [
            {
                "month": s.month,
                "section": s.ref.section,
                "path": s.ref.path,
                "sha256": s.ref.sha256,
                "as_of": s.ref.as_of,
                "label": s.ref.label,
            }
            for s in report.sources
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
    return "; ".join(f"{m.key}: expected {m.expected!r}, report shows {m.shown!r}" for m in found[:6])


def create_draft(
    client: str,
    quarter: str,
    *,
    generated_on: str,
    out_dir: Path = DEFAULT_OUT_DIR,
    sources: QbrSources = DEFAULT_QBR_SOURCES,
) -> Draft:
    """Build, render, reconcile, then write ``<out>/<quarter>/<client>.draft.html`` and ``.draft.json``.

    If any number differs from its source, nothing is written and ``QbrError`` names the figures.
    """
    report = build_qbr(client, quarter, generated_on=generated_on, sources=sources)
    page = render_html(report)
    found = reconcile_html(page, sources)
    if found:
        raise QbrError(f"review does not reconcile with its sources, nothing written: {_problems(found)}")
    data = page.encode("utf-8")
    digest_hex = _sha(data)
    body = qbr_to_dict(report) | {"html_sha256": digest_hex, "note": DRAFT_NOTE}
    folder = Path(out_dir) / quarter
    folder.mkdir(parents=True, exist_ok=True)
    html_path = folder / f"{client}.draft.html"
    json_path = folder / f"{client}.draft.json"
    html_path.write_bytes(data)
    json_path.write_bytes(_json_bytes(body))
    return Draft(html_path, json_path, digest_hex)


def verify_draft(html_path: Path, *, sources: QbrSources = DEFAULT_QBR_SOURCES) -> None:
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
        raise VerifyError(f"review does not reconcile with its sources: {_problems(found)}")


# -- command line ---------------------------------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.reporting.qbr", description="Quarterly business review (draft)."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="write a draft review for one client")
    build.add_argument("client", help="client id, e.g. contoso-dental")
    build.add_argument("--quarter", required=True, help="YYYY-Qn, e.g. 2026-Q4")
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
        on = args.generated_on or datetime.now(UTC).date().isoformat()
        draft = create_draft(args.client, args.quarter, generated_on=on, out_dir=args.out)
        print(
            json.dumps({"client": args.client, "html": str(draft.html_path), "sha256": draft.sha256, "status": "draft"})
        )
    except HealthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
