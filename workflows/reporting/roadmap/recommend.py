"""Roadmap recommendations from one client's own findings (B-73, specs/B-73.md; W-RPT-04; C-21).

Deterministic: the same fixtures and the same price list give the same list in the same order. Each rule below turns
one finding into one recommendation and cites it (report, field, value, source files with SHA-256). A finding that
does not fire a rule produces nothing, and ``Recommendation`` refuses to exist without a cited finding. No model is
called and nothing is changed anywhere.

Reads, for one client only: the B-71 health report (tickets, baseline, patching, backup jobs, awareness), the B-75
licensing report, the B-64 device reports and the B-70 backup coverage report. A source the client has no data for is
named in ``gaps``; it is never filled from another client.

Every figure is fixture-based. The thresholds and wording are stand-ins (UNVERIFIED against any real client's needs).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.paths import REPO_ROOT
from workflows.backup_coverage import BackupCoverageError
from workflows.backup_coverage import build_report as build_backup
from workflows.device_reports import ReportError as DeviceReportError
from workflows.device_reports import build_client_report as build_devices
from workflows.licensing import LicensingError
from workflows.licensing import build_report as build_licensing
from workflows.reporting.health import HealthError, HealthReport
from workflows.reporting.health import build_report as build_health
from workflows.reporting.health.sources import (
    check_client,
    check_date,
    digest,
    display_name,
    display_path,
    parse_period,
)
from workflows.reporting.roadmap.model import (
    CATEGORIES,
    Budget,
    Evidence,
    FileRef,
    Recommendation,
    Roadmap,
    RoadmapError,
)

DEFAULT_PRICE_LIST = Path(__file__).with_name("data") / "price_list.json"
LICENSING_DIR = REPO_ROOT / "fixtures" / "licensing"
TENANT_DIR = REPO_ROOT / "fixtures" / "tenant"
HEALTH = "health report (B-71)"
LICENCE = "licensing report (B-75)"
DEVICES = "device reports (B-64)"
BACKUP = "backup coverage report (B-70)"

Number = int | float


# -- price list ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Prices:
    currency: str
    hardware: dict[str, tuple[Number, Number, str]]
    server_markers: tuple[str, ...]
    rate: tuple[Number, Number]
    domain: tuple[Number, Number]
    hours: dict[str, tuple[Number, Number]]


def _range(node: Any, where: str) -> tuple[Number, Number]:
    if not isinstance(node, dict):
        raise RoadmapError(f"price list: {where} must be an object with low and high")
    low, high = node.get("low"), node.get("high")
    if (
        isinstance(low, bool)
        or isinstance(high, bool)
        or not isinstance(low, int | float)
        or not isinstance(high, int | float)
        or low < 0
        or high < 0
    ):
        raise RoadmapError(f"price list: {where} needs non-negative numbers")
    if low > high:
        raise RoadmapError(f"price list: {where} has low above high")
    return low, high


def load_prices(path: Path) -> Prices:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RoadmapError(f"cannot read the price list {Path(path).name}: {exc}") from None
    if not isinstance(raw, dict):
        raise RoadmapError("price list is not a JSON object")
    try:
        hardware: dict[str, tuple[Number, Number, str]] = {}
        for kind in ("workstation", "server"):
            node = raw["hardware"][kind]
            low, high = _range(node, f"hardware.{kind}")
            hardware[kind] = (low, high, str(node.get("label", kind)))
        rate = _range(raw["labour"]["hourly_rate"], "labour.hourly_rate")
        domain = _range(raw["domain_renewal_annual"], "domain_renewal_annual")
        hours: dict[str, tuple[Number, Number]] = {}
        for key, node in raw["items"].items():
            h_low, h_high = node["hours_low"], node["hours_high"]
            if not 0 <= h_low <= h_high:
                raise RoadmapError(f"price list: items.{key} hours must satisfy 0 <= low <= high")
            hours[key] = (h_low, h_high)
        markers = tuple(str(m).upper() for m in raw["server_hostname_markers"])
        currency = str(raw["currency"])
    except (KeyError, TypeError, AttributeError) as exc:
        raise RoadmapError(f"price list is missing or malformed: {type(exc).__name__} {exc}") from None
    return Prices(currency, hardware, markers, rate, domain, hours)


def _labour_budget(prices: Prices, item: str) -> Budget:
    if item not in prices.hours:
        raise RoadmapError(f"price list has no hours for {item}")
    h_low, h_high = prices.hours[item]
    basis = f"price list: {h_low} to {h_high} hours at {prices.rate[0]} to {prices.rate[1]} {prices.currency} per hour"
    return Budget(h_low * prices.rate[0], h_high * prices.rate[1], "one-time", basis)


def _file(path: Path) -> FileRef:
    return FileRef(display_path(path), digest(path))


# -- rule tables --------------------------------------------------------------------------------------------------
# rule id -> (category, title, action, effort, risk, metric keys to cite). Effort is the work to do it; risk is what
# leaving the finding alone could cost. Both are stand-ins a person adjusts.
HEALTH_RULES: dict[str, tuple[str, str, str, str, str, tuple[str, ...]]] = {
    "baseline.high": (
        "security",
        "Close the high-severity tenant baseline findings",
        "Work through the open high-severity baseline findings, highest first; a person approves each change.",
        "medium",
        "high",
        ("baseline.high", "baseline.findings"),
    ),
    "baseline.ca-changed": (
        "security",
        "Confirm the Conditional Access changes were intended",
        "A person checks each Conditional Access change against a change request and reverts any that were not.",
        "low",
        "medium",
        ("baseline.ca_changes",),
    ),
    "patching.critical": (
        "security",
        "Install the waiting critical updates",
        "Schedule the critical updates for the devices that still need them, servers in an agreed window.",
        "medium",
        "high",
        ("patching.critical_pending_devices", "patching.devices"),
    ),
    "patching.stale": (
        "security",
        "Bring long-unpatched devices current",
        "Find out why these devices are not patching (offline, excluded, broken agent) and fix the cause.",
        "medium",
        "medium",
        ("patching.not_patched_30d",),
    ),
    "backup.failed": (
        "backup",
        "Fix the failing backup jobs",
        "Find the cause of each failed job, fix it, and watch the next run.",
        "medium",
        "high",
        ("backup.failed", "backup.jobs"),
    ),
    "backup.missed": (
        "backup",
        "Find out why backup jobs never started",
        "Check schedules, agents and credentials for the jobs that did not start.",
        "low",
        "high",
        ("backup.missed", "backup.jobs"),
    ),
    "backup.boot-check": (
        "backup",
        "Repair backups whose test restore failed",
        "A person re-runs the test restore, finds the cause and records the result.",
        "high",
        "high",
        ("backup.boot_check_failed",),
    ),
    "awareness.clicks": (
        "security",
        "Run phishing awareness training",
        "Hold a short training session and repeat the simulation to see whether the click rate falls.",
        "low",
        "medium",
        ("phish.clicked", "phish.sent"),
    ),
    "awareness.vault-score": (
        "security",
        "Raise the password vault audit score",
        "Work through the vault's audit findings (weak, reused and old passwords).",
        "medium",
        "medium",
        ("vault.audit_score",),
    ),
    "awareness.vault-mfa": (
        "security",
        "Turn on multi-factor sign-in for the password vault",
        "Enforce MFA for every vault user.",
        "low",
        "high",
        ("vault.mfa_enforced",),
    ),
    "awareness.vault-enrolment": (
        "security",
        "Enrol everyone in the password vault",
        "Invite the people who are not enrolled and help them set up.",
        "low",
        "medium",
        ("vault.users_enrolled", "vault.users_total"),
    ),
}
LIFECYCLE_RISK = {"past": "high", "ending-soon": "medium"}


# -- builders -----------------------------------------------------------------------------------------------------
def _hardware(client: str, report: dict[str, Any], prices: Prices) -> list[Recommendation]:
    out: list[Recommendation] = []
    ref = _file(LICENSING_DIR / f"{client}.json")
    for row in report["hardware"]:
        state = row["lifecycle"]
        if state not in LIFECYCLE_RISK:
            continue
        host = row["hostname"]
        kind = "server" if any(m in host.upper() for m in prices.server_markers) else "workstation"
        low, high, label = prices.hardware[kind]
        if state == "past":
            title = f"Replace {host}: past its planned lifecycle"
            action = f"Replace {host} now; plan the move of its data and roles with the client."
        else:
            title = f"Plan the replacement of {host}: lifecycle ends {row['lifecycle_ends_on']}"
            action = f"Put {host} in the next budget and book the replacement before its lifecycle ends."
        if row.get("warranty_ends_on"):
            action += f" Its warranty ended or ends {row['warranty_ends_on']}."
        out.append(
            Recommendation(
                id=f"hw-{host.lower()}",
                category="hardware",
                rule=f"hardware.lifecycle-{state}",
                title=title,
                action=action,
                effort="medium",
                risk=LIFECYCLE_RISK[state],
                budget=Budget(low, high, "one-time", f"price list: {label}, {low} to {high} {prices.currency}"),
                evidence=(
                    Evidence(LICENCE, f"hardware[{host}].lifecycle", state, (ref,)),
                    Evidence(LICENCE, f"hardware[{host}].lifecycle_ends_on", row["lifecycle_ends_on"], (ref,)),
                ),
            )
        )
    return out


def _licence(client: str, report: dict[str, Any], prices: Prices) -> list[Recommendation]:
    out: list[Recommendation] = []
    fixture_path = LICENSING_DIR / f"{client}.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    unit_prices: dict[str, float] = fixture.get("unit_prices_monthly", {})
    ref = _file(fixture_path)
    seat_files = (
        ref,
        *(
            _file(p)
            for p in (TENANT_DIR / client / "licenses.json", TENANT_DIR / client / "signins.json")
            if p.exists()
        ),
    )
    seats = {s["sku"]: s for s in report["seats"]}
    for sku, seat in seats.items():
        if seat["reducible"] <= 0:
            continue
        out.append(
            Recommendation(
                id=f"lic-seats-{sku.lower()}",
                category="licence",
                rule="licence.reducible-seats",
                title=f"Right-size {sku}: {seat['reducible']} seats could go",
                action=(
                    f"Confirm with the client that the {seat['reducible']} unused, duplicate or orphaned seats are "
                    "not needed, then reduce at the next renewal. Nothing is cancelled until a person approves."
                ),
                effort="low",
                risk="low",
                budget=Budget(
                    0,
                    0,
                    "one-time",
                    f"no spend; the licensing report puts the saving at {seat['monthly_saving']:.2f} "
                    f"{prices.currency} per month at the fixture's unit prices",
                ),
                evidence=(
                    Evidence(LICENCE, f"seats[{sku}].reducible", seat["reducible"], seat_files),
                    Evidence(LICENCE, f"seats[{sku}].purchased", seat["purchased"], seat_files),
                    Evidence(LICENCE, f"seats[{sku}].monthly_saving", seat["monthly_saving"], seat_files),
                ),
            )
        )
    for renewal in report["renewals"]:
        kind, status = renewal["kind"], renewal["status"]
        if kind not in ("subscription", "domain") or status not in ("due", "lapsed"):
            continue
        rid, name = renewal["id"], renewal["name"]
        evidence = [
            Evidence(LICENCE, f"renewals[{rid}].ends_on", renewal["ends_on"], (ref,)),
            Evidence(LICENCE, f"renewals[{rid}].status", status, (ref,)),
        ]
        if kind == "domain":
            low, high = prices.domain
            budget = Budget(
                low, high, "per year", f"price list: domain renewal, {low} to {high} {prices.currency} per year"
            )
            title = f"Confirm the renewal of the domain {name}"
            action = "Check the registrar record and auto-renew with the client's contact before the end date."
            prefix = "lic-domain"
        else:
            seat = seats.get(name)
            price = unit_prices.get(name)
            if seat is None or price is None:
                budget = Budget(0, 0, "per year", "no seat count or unit price for this item in the licensing fixture")
            else:
                kept = seat["purchased"] - seat["reducible"]
                budget = Budget(
                    kept * price * 12,
                    seat["purchased"] * price * 12,
                    "per year",
                    f"licensing fixture unit price {price:.2f} {prices.currency} per seat per month, "
                    f"{kept} to {seat['purchased']} seats",
                )
                evidence.append(Evidence(LICENCE, f"unit_prices_monthly[{name}]", price, (ref,)))
                evidence.append(Evidence(LICENCE, f"seats[{name}].purchased", seat["purchased"], seat_files))
            title = f"Plan the {name} renewal ({renewal['ends_on']})"
            action = (
                "Settle the seat count (see the right-sizing item) before the renewal date; a person places the order."
            )
            prefix = "lic-renew"
        out.append(
            Recommendation(
                id=f"{prefix}-{rid.lower()}",
                category="licence",
                rule=f"licence.{kind}-{status}",
                title=title,
                action=action,
                effort="low",
                risk="high" if status == "lapsed" else "medium",
                budget=budget,
                evidence=tuple(evidence),
            )
        )
    return out


def _health(report: HealthReport, prices: Prices) -> list[Recommendation]:
    out: list[Recommendation] = []
    for section in report.sections:
        if not section.available:
            continue
        for rule_id in section.reasons:
            spec = HEALTH_RULES.get(rule_id)
            if spec is None:  # a rule with no roadmap meaning (for example tickets.open-share)
                continue
            category, title, action, effort, risk, keys = spec
            files = tuple(FileRef(s.path, s.sha256) for s in section.sources)
            evidence = tuple(
                Evidence(HEALTH, key, section.metrics[key], files) for key in keys if key in section.metrics
            )
            ident = (
                "sec-" + rule_id.replace(".", "-") if category == "security" else "bak-job-" + rule_id.split(".", 1)[1]
            )
            out.append(
                Recommendation(
                    id=ident,
                    category=category,
                    rule=rule_id,
                    title=title,
                    action=action,
                    effort=effort,
                    risk=risk,
                    budget=_labour_budget(prices, rule_id.replace(".", "-")),
                    evidence=evidence,
                )
            )
    return out


def _backup(body: dict[str, Any], prices: Prices) -> list[Recommendation]:
    out: list[Recommendation] = []
    files = tuple(_file(REPO_ROOT / s["path"]) for s in body["sources"])
    counts = body["counts"]
    if counts["objects_uncovered"] > 0:
        out.append(
            Recommendation(
                id="bak-coverage",
                category="backup",
                rule="backup.uncovered-objects",
                title=f"Extend backup coverage: {counts['objects_uncovered']} in-scope items are not covered",
                action="Add the uncovered mailboxes, drives and sites to a policy, or note why they are out of scope.",
                effort="low",
                risk="high",
                budget=_labour_budget(prices, "bak-coverage"),
                evidence=(
                    Evidence(BACKUP, "counts.objects_uncovered", counts["objects_uncovered"], files),
                    Evidence(BACKUP, "counts.objects_in_scope", counts["objects_in_scope"], files),
                ),
            )
        )
    for row in body["policies"]["rows"]:
        issues = row["issues"]
        if not issues:
            continue
        pid = row["id"]
        out.append(
            Recommendation(
                id=f"bak-policy-{pid.lower()}",
                category="backup",
                rule="backup.policy-issue",
                title=f"Fix backup policy {pid} ({row['name']}): {', '.join(issues)}",
                action="Change the policy to meet the client's retention and immutability need, or record why not.",
                effort="low",
                risk="high" if "not-immutable" in issues else "medium",
                budget=_labour_budget(prices, "bak-policy"),
                evidence=(Evidence(BACKUP, f"policies[{pid}].issues", ", ".join(issues), files),),
            )
        )
    if counts["dr_sections_stale"] > 0:
        out.append(
            Recommendation(
                id="bak-dr-stale",
                category="backup",
                rule="backup.dr-plan-stale",
                title=f"Review the disaster recovery plan: {counts['dr_sections_stale']} sections are out of date",
                action="A person reviews each stale section with the client and records the review date.",
                effort="medium",
                risk="medium",
                budget=_labour_budget(prices, "bak-dr-stale"),
                evidence=(
                    Evidence(BACKUP, "counts.dr_sections_stale", counts["dr_sections_stale"], files),
                    Evidence(BACKUP, "counts.dr_sections_total", counts["dr_sections_total"], files),
                ),
            )
        )
    return out


def _devices(report: dict[str, Any], prices: Prices) -> list[Recommendation]:
    out: list[Recommendation] = []
    files = tuple(_file(REPO_ROOT / s["path"]) for s in report["sources"])
    counts = report["counts"]

    def item(rid: str, title: str, action: str, effort: str, risk: str, fields: dict[str, int]) -> None:
        out.append(
            Recommendation(
                id=rid,
                category="devices",
                rule=f"devices.{rid.removeprefix('dev-')}",
                title=title,
                action=action,
                effort=effort,
                risk=risk,
                budget=_labour_budget(prices, rid),
                evidence=tuple(Evidence(DEVICES, f, v, files) for f, v in fields.items()),
            )
        )

    comp = counts["compliance"]
    bad = comp.get("non-compliant", 0) + comp.get("stale", 0)
    if bad > 0:
        item(
            "dev-not-compliant",
            f"Bring {bad} non-compliant or stale devices back into compliance",
            "Find why each device fails its compliance policy or has stopped checking in, and fix or retire it.",
            "medium",
            "high",
            {
                "counts.compliance.non-compliant": comp.get("non-compliant", 0),
                "counts.compliance.stale": comp.get("stale", 0),
            },
        )
    if comp.get("not-in-intune", 0) > 0:
        n = comp["not-in-intune"]
        item(
            "dev-not-in-intune",
            f"Enrol {n} devices that Intune does not manage",
            "Enrol each device, or record why it stays out (for example a server or a retired machine).",
            "medium",
            "medium",
            {"counts.compliance.not-in-intune": n},
        )
    enc = counts["encryption"]
    if enc.get("not-encrypted", 0) > 0:
        item(
            "dev-unencrypted",
            f"Encrypt {enc['not-encrypted']} devices whose disks are not encrypted",
            "Turn on disk encryption and store the recovery key in the vault; a person does the key step.",
            "low",
            "high",
            {"counts.encryption.not-encrypted": enc["not-encrypted"]},
        )
    laps = counts["laps"]
    laps_bad = laps.get("not-backed-up", 0) + laps.get("stale-backup", 0)
    if laps_bad > 0:
        item(
            "dev-laps",
            f"Fix local-admin password backup on {laps_bad} devices",
            "Check the LAPS policy and each device's last backup; only status is read here, never a password.",
            "low",
            "medium",
            {
                "counts.laps.not-backed-up": laps.get("not-backed-up", 0),
                "counts.laps.stale-backup": laps.get("stale-backup", 0),
            },
        )
    return out


# -- assembling ---------------------------------------------------------------------------------------------------
def _gathered(name: str, fn: Callable[[], Any], errors: tuple[type[Exception], ...], gaps: list[str]) -> Any:
    try:
        return fn()
    except errors as exc:
        gaps.append(f"{name}: not available for this client ({exc})")
        return None


def _totals(items: tuple[Recommendation, ...]) -> dict[str, int | float]:
    one = [r.budget for r in items if r.budget.unit == "one-time"]
    yearly = [r.budget for r in items if r.budget.unit == "per year"]
    return {
        "items": len(items),
        "one_time_low": sum(b.low for b in one),
        "one_time_high": sum(b.high for b in one),
        "per_year_low": sum(b.low for b in yearly),
        "per_year_high": sum(b.high for b in yearly),
    }


def build_roadmap(
    client: str,
    period: str,
    *,
    generated_on: str,
    price_list: Path = DEFAULT_PRICE_LIST,
) -> Roadmap:
    """The draft roadmap for one client. Reads that client's files and the price list; writes nothing."""
    try:
        check_client(client)
        parse_period(period)
        check_date(generated_on, "generated_on")
    except HealthError as exc:
        raise RoadmapError(str(exc)) from None
    prices = load_prices(price_list)
    try:
        health = build_health(client, period, generated_on=generated_on)
    except HealthError as exc:
        raise RoadmapError(str(exc)) from None
    gaps: list[str] = []
    lic = _gathered("licensing", lambda: build_licensing(client, generated_on), (LicensingError,), gaps)
    cov = _gathered("backup coverage", lambda: build_backup(client, as_of=generated_on), (BackupCoverageError,), gaps)
    dev = _gathered("device reports", lambda: build_devices(client), (DeviceReportError,), gaps)
    if lic is None and cov is None and dev is None and not any(s.available for s in health.sections):
        raise RoadmapError(f"no data for client {client!r}")
    items: list[Recommendation] = []
    if lic is not None:
        items += _hardware(client, lic, prices) + _licence(client, lic, prices)
    items += _health(health, prices)
    if cov is not None:
        items += _backup(cov.body, prices)
    if dev is not None:
        items += _devices(dev, prices)
    ids = [r.id for r in items]
    if len(ids) != len(set(ids)):
        raise RoadmapError("two recommendations got the same id")
    ordered = tuple(sorted(items, key=lambda r: (CATEGORIES.index(r.category), r.id)))
    return Roadmap(
        client=client,
        display_name=display_name(client),
        period=period,
        generated_on=generated_on,
        recommendations=ordered,
        totals=_totals(ordered),
        gaps=tuple(gaps),
        currency=prices.currency,
    )
