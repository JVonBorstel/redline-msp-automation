"""Copilot readiness (B-53, specs/B-53.md; W-M365-07, W-PRJ-04, W-M365-08; C-25, C-21, C-20).

For one client this reads a SharePoint/OneDrive sharing fixture (never the network) and scores how ready the tenant is
for Microsoft 365 Copilot: Everyone and anyone links, shares to outside guests, and sensitive sites with no label.

The score is a fixed formula (``FORMULA``) over per-kind weights (``WEIGHTS``): every deducted point belongs to one
finding that names the site, so nothing is deducted without a reason (B53-1). Label and DLP gaps are
recommendations a person reads, with no points and no action behind them (B53-2). The formula, the weights and the
counts are printed with the report and reconcile to the fixture (B53-3).

It only reports. The module imports no lever runner and has no write path.

Isolation (C-20). The entry point takes the client explicitly and opens only that client's file; a file whose
``client`` field differs from its name is refused. A field that could hold a secret value is refused at load.

Dates come from ``as_of`` (the fixture's pinned date by default), never the wall clock (STD-TS-4, STD-FX-6).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE_DIR = REPO_ROOT / "fixtures" / "sharepoint"
REPORT_NOTE = "Report only: nothing was changed. Label and DLP gaps are recommendations for a person to weigh."
CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# Field names that may hold a credential; the list is split from words so no assignment looks like a literal one.
_RISKY_FIELDS = frozenset("secrettext secret value password privatekey key".split())

SITE_KINDS = ("site", "onedrive")
SENSITIVE = ("health", "finance", "legal")  # categories whose files Copilot must not over-share
SENSITIVITIES = (*SENSITIVE, "general")
LINK_SCOPES = ("anyone", "everyone-except-external", "organization", "specific")
BROAD_SCOPES = ("anyone", "everyone-except-external")
RECIPIENT_TYPES = ("guest", "internal")

# Points deducted per finding of each kind. Invented for this fixture-based pipeline check, not calibrated on real
# tenants. A recommendation kind has weight 0: it is advice, never a deduction.
WEIGHTS: dict[str, int] = {
    "everyone-link": 15,
    "external-share": 10,
    "unlabelled-sensitive-site": 20,
    "label-gap": 0,
    "dlp-gap": 0,
}
FINDING_KINDS = ("everyone-link", "external-share", "unlabelled-sensitive-site")
RECOMMENDATION_KINDS = ("label-gap", "dlp-gap")
SEVERITY = {"everyone-link": "high", "external-share": "medium", "unlabelled-sensitive-site": "high"}
FORMULA = "score = max(0, 100 - sum(points of every finding)); points of a finding = WEIGHTS[kind]"
EMPTY_NOTE = "no sites in fixture"


class ReadinessError(ValueError):
    """The input is bad (client id, file, field); nothing was scored."""


@dataclass(frozen=True)
class Finding:
    """One scored problem (B53-1): where it is, how bad, and the points it costs."""

    client: str
    id: str
    kind: str  # everyone-link | external-share | unlabelled-sensitive-site
    site: str
    severity: str
    points: int
    detail: str

    def row(self) -> dict[str, Any]:
        return {
            "client": self.client,
            "id": self.id,
            "kind": self.kind,
            "site": self.site,
            "severity": self.severity,
            "points": self.points,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class Recommendation:
    """One label or DLP gap (B53-2). Advice for a person; it carries no points and nothing acts on it."""

    client: str
    id: str
    kind: str  # label-gap | dlp-gap
    category: str
    detail: str

    def row(self) -> dict[str, Any]:
        return {
            "client": self.client,
            "id": self.id,
            "kind": self.kind,
            "category": self.category,
            "points": WEIGHTS[self.kind],
            "detail": self.detail,
            "action": "recommendation-only",
        }


@dataclass(frozen=True)
class ReadinessReport:
    client: str
    as_of: str
    score: int
    totals: dict[str, int]  # sites, links, shares as counted in the fixture
    findings: tuple[Finding, ...]
    recommendations: tuple[Recommendation, ...]
    notes: tuple[str, ...]

    @property
    def counts(self) -> dict[str, int]:
        return {k: sum(1 for f in self.findings if f.kind == k) for k in FINDING_KINDS}

    @property
    def points_by_kind(self) -> dict[str, int]:
        return {k: sum(f.points for f in self.findings if f.kind == k) for k in FINDING_KINDS}

    def to_dict(self) -> dict[str, Any]:
        return {
            "client": self.client,
            "as_of": self.as_of,
            "score": self.score,
            "formula": FORMULA,
            "weights": dict(WEIGHTS),
            "totals": dict(self.totals),
            "counts": self.counts,
            "points": self.points_by_kind,
            "findings": [f.row() for f in self.findings],
            "recommendations": [r.row() for r in self.recommendations],
            "notes": [REPORT_NOTE, *self.notes],
        }


# --------------------------------------------------------------------------------------------------- loading


def _client(client: str) -> str:
    if not isinstance(client, str) or not CLIENT_ID.match(client):
        raise ReadinessError("client id must be a slug like 'contoso-dental'")
    return client


def _forbid_secrets(node: object, where: str) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() in _RISKY_FIELDS:
                raise ReadinessError(f"{where}: field {key!r} could hold a secret value; fixtures carry metadata only")
            _forbid_secrets(value, where)
    elif isinstance(node, list):
        for item in node:
            _forbid_secrets(item, where)


def _load_json(path: Path, client: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReadinessError(f"no fixture for client {client!r}: {path.name}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(data, dict) or data.get("client") != client:
        raise ReadinessError(f"{path.name}: 'client' must equal {client!r}")
    _forbid_secrets(data, path.name)
    return data


def _day(text: object, where: str) -> str:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).astimezone(UTC).date().isoformat()
    except ValueError as exc:
        raise ReadinessError(f"{where}: not an ISO date: {text!r}") from exc


def _items(node: dict[str, Any], field: str, where: str) -> list[dict[str, Any]]:
    items = node.get(field, [])
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise ReadinessError(f"{where}: {field!r} must be a list of objects")
    return items


def _text(node: dict[str, Any], field: str, where: str) -> str:
    value = node.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ReadinessError(f"{where}: {field!r} must be a non-empty string")
    return value


def _choice(node: dict[str, Any], field: str, allowed: tuple[str, ...], where: str) -> str:
    value = node.get(field)
    if value not in allowed:
        raise ReadinessError(f"{where}: {field!r} must be one of {', '.join(allowed)}")
    return str(value)


def _covered(policies: list[dict[str, Any]], where: str) -> set[str]:
    covered: set[str] = set()
    for policy in policies:
        _text(policy, "name", where)
        categories = policy.get("covers", [])
        if not isinstance(categories, list) or not all(c in SENSITIVITIES for c in categories):
            raise ReadinessError(f"{where}: 'covers' must list categories from {', '.join(SENSITIVITIES)}")
        covered.update(categories)
    return covered


# --------------------------------------------------------------------------------------------------- the report


def build_report(
    client: str,
    *,
    as_of: str | None = None,
    fixture_dir: Path = DEFAULT_FIXTURE_DIR,
) -> ReadinessReport:
    """Readiness of ONE client's SharePoint and OneDrive sharing. Reads that client's file only."""
    client = _client(client)
    name = f"{client}.json"
    data = _load_json(Path(fixture_dir) / name, client)
    day = _day(as_of or data.get("as_of"), "as_of")
    sites = _items(data, "sites", name)
    tenant = data.get("tenant", {})
    if not isinstance(tenant, dict):
        raise ReadinessError(f"{name}: 'tenant' must be an object")
    labelled = _covered(_items(tenant, "labels", f"{name} tenant"), f"{name} tenant labels")
    protected = _covered(_items(tenant, "dlpPolicies", f"{name} tenant"), f"{name} tenant dlpPolicies")

    findings: list[Finding] = []
    seen_sites: set[str] = set()
    links = shares = 0

    def add(kind: str, site_id: str, site_name: str, suffix: str, detail: str) -> None:
        fid = f"{kind}/{site_id}/{suffix}" if suffix else f"{kind}/{site_id}"
        findings.append(Finding(client, fid, kind, site_name, SEVERITY[kind], WEIGHTS[kind], detail))

    for site in sites:
        where = f"{name} site"
        site_id, site_name = _text(site, "id", where), _text(site, "name", where)
        if site_id in seen_sites:
            raise ReadinessError(f"{name}: duplicate site id {site_id!r}")
        seen_sites.add(site_id)
        _choice(site, "kind", SITE_KINDS, f"{where} {site_name}")
        sensitivity = _choice(site, "sensitivity", SENSITIVITIES, f"{where} {site_name}")
        label = site.get("label")
        for link in _items(site, "links", f"{where} {site_name}"):
            links += 1
            scope = _choice(link, "scope", LINK_SCOPES, f"{where} {site_name} link")
            if scope in BROAD_SCOPES:
                detail = f"{scope} link on {link.get('target')!s}; anyone in that audience can open it"
                add("everyone-link", site_id, site_name, _text(link, "id", f"{where} {site_name} link"), detail)
        for share in _items(site, "shares", f"{where} {site_name}"):
            shares += 1
            who = _choice(share, "recipientType", RECIPIENT_TYPES, f"{where} {site_name} share")
            if who == "guest":
                detail = f"shared with outside guest {share.get('recipient')!s} on {share.get('target')!s}"
                add("external-share", site_id, site_name, _text(share, "id", f"{where} {site_name} share"), detail)
        if sensitivity in SENSITIVE and not (isinstance(label, str) and label.strip()):
            add("unlabelled-sensitive-site", site_id, site_name, "", f"{sensitivity} content with no sensitivity label")

    present = sorted({str(s["sensitivity"]) for s in sites if s["sensitivity"] in SENSITIVE})
    recommendations: list[Recommendation] = []
    for category in present:
        if category not in labelled:
            detail = f"no sensitivity label covers {category} content; consider defining one before Copilot rollout"
            recommendations.append(Recommendation(client, f"label-gap/{category}", "label-gap", category, detail))
        if category not in protected:
            detail = f"no DLP policy covers {category} content; consider adding one before Copilot rollout"
            recommendations.append(Recommendation(client, f"dlp-gap/{category}", "dlp-gap", category, detail))

    findings.sort(key=lambda f: (-f.points, f.kind, f.id))
    score = max(0, 100 - sum(f.points for f in findings))
    notes = () if sites else (EMPTY_NOTE,)
    totals = {"sites": len(sites), "links": links, "shares": shares}
    return ReadinessReport(client, day, score, totals, tuple(findings), tuple(recommendations), notes)


def render_markdown(report: ReadinessReport) -> str:
    """A plain report a person reads: the formula and weights first, then the findings that add up to the score."""
    counts, points = report.counts, report.points_by_kind
    lines = [
        f"# Copilot readiness: {report.client} (as of {report.as_of})",
        "",
        f"> Fixture-based, synthetic. {REPORT_NOTE}",
        "",
        f"**Score: {report.score} / 100**",
        "",
        "## How the score is worked out",
        "",
        f"`{FORMULA}`",
        "",
        "| Kind | Count | Weight | Points |",
        "| --- | --- | --- | --- |",
    ]
    lines += [f"| {k} | {counts[k]} | {WEIGHTS[k]} | {points[k]} |" for k in FINDING_KINDS]
    lines += [
        f"| total | {sum(counts.values())} | - | {sum(points.values())} |",
        "",
        f"Counted in the fixture: {report.totals['sites']} site(s), {report.totals['links']} link(s), "
        f"{report.totals['shares']} share(s).",
    ]
    lines += ["", *[f"- {n}" for n in report.notes]] if report.notes else []
    lines += ["", "## Findings", "", "| Id | Site | Severity | Points | Detail |", "| --- | --- | --- | --- | --- |"]
    lines += [f"| {f.id} | {f.site} | {f.severity} | {f.points} | {f.detail} |" for f in report.findings]
    if not report.findings:
        lines.append("| - | - | - | 0 | nothing oversharing found |")
    lines += ["", "## Recommendations (no points, for a person to weigh)", "", "| Id | Detail |", "| --- | --- |"]
    lines += [f"| {r.id} | {r.detail} |" for r in report.recommendations]
    if not report.recommendations:
        lines.append("| - | no label or DLP gap |")
    return "\n".join(lines) + "\n"
