"""Vulnerability, advisory and emergency-patch relevance (B-47; W-SEC-06, W-SEC-08, W-PAT-05; C-21, C-27).

Reads a CISA-KEV-shaped feed, each client's synthetic software inventory, a Nessus-shaped scan export and a
vPenTest-shaped findings report (all fixtures under ``fixtures/advisories``). It answers one question per CVE: which of
this client's devices are probably affected, and in what order should a person look at them.

Report only. Nothing here calls a lever, an adapter, an RMM or a network; the emergency list holds *proposed* change
windows taken from the windows each client's fixture declares, and a lead decides (R2 work stays a human decision).

Isolation (C-27). Every entry point takes the client explicitly. A file whose ``client`` differs from the requested one
is refused, and one client's inventory and findings are never joined to another's. Cross-client views only collect
results that were each produced for one client.

No invented numbers (C-21). The order of the list is the sort of the shown factors (exposure, criticality, ransomware
use, KEV due date); ``rank`` is a position in that order, not a score. Every count is computed from the rows and
reconciled in ``summary``. The KEV feed has no version range, so the match is product level only and every row says
``version_checked: false``. Scanner and pen-test text (names, plugin output) is never copied into a result: only ids.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURES_DIR = REPO_ROOT / "fixtures" / "advisories"

CLIENT_ID = r"^[a-z0-9][a-z0-9-]{0,62}$"
CVE_ID = r"^CVE-\d{4}-\d{4,}$"
_CLIENT_RE = re.compile(CLIENT_ID)
_CVE_RE = re.compile(CVE_ID)
_SPACE = re.compile(r"\s+")

Exposure = Literal["internet", "internal", "unknown"]
Criticality = Literal["critical", "high", "medium", "low", "unknown"]
Source = Literal["inventory", "nessus", "vpentest"]
_EXPOSURE_ORDER: dict[str, int] = {"internet": 0, "internal": 1, "unknown": 2}
_CRITICALITY_ORDER: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3, "unknown": 4}
_SOURCE_ORDER: tuple[Source, ...] = ("inventory", "nessus", "vpentest")
EMERGENCY_RULE = "KEV listed and (internet exposed or known ransomware use)"
NOT_DEPLOYED = "report only: nothing is deployed; a lead approves any change"


class AdvisoriesError(ValueError):
    """The input is bad (a fixture, a client id, a mismatch); nothing was matched."""


def utc(text: str) -> datetime:
    """Parse an ISO 8601 UTC time ending in Z (or an offset) into an aware datetime."""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdvisoriesError(f"not a time: {text!r}") from exc
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def key(text: str) -> str:
    """Case-folded, whitespace-collapsed key used to match vendors, products and host names."""
    return _SPACE.sub(" ", text.strip()).casefold()


# --- fixture models (strict: a changed shape fails the load) -------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class KevEntry(_Strict):
    """One KEV feed entry. Field names verified against the live feed on 2026-10-21 (see SOURCES.md)."""

    cve_id: Annotated[str, StringConstraints(pattern=CVE_ID)] = Field(alias="cveID")
    vendor_project: str = Field(alias="vendorProject", min_length=1)
    product: str = Field(min_length=1)
    vulnerability_name: str = Field(alias="vulnerabilityName")
    date_added: str = Field(alias="dateAdded", pattern=r"^\d{4}-\d{2}-\d{2}$")
    short_description: str = Field(alias="shortDescription")
    required_action: str = Field(alias="requiredAction")
    due_date: str = Field(alias="dueDate", pattern=r"^\d{4}-\d{2}-\d{2}$")
    ransomware: Literal["Known", "Unknown"] = Field(alias="knownRansomwareCampaignUse")
    forensic_triage: Literal["Yes", "No"] = Field(alias="forensicTriage")
    notes: str
    cwes: tuple[str, ...]


class KevFeed(_Strict):
    title: str
    catalog_version: str = Field(alias="catalogVersion")
    date_released: str = Field(alias="dateReleased")
    count: int
    vulnerabilities: tuple[KevEntry, ...]
    as_of: str

    @model_validator(mode="after")
    def _reconciles(self) -> KevFeed:
        ids = [v.cve_id for v in self.vulnerabilities]
        if self.count != len(ids):
            raise ValueError(f"count {self.count} does not match {len(ids)} entries")
        if len(set(ids)) != len(ids):
            raise ValueError("a CVE id appears twice in the feed")
        return self

    def entry(self, cve: str) -> KevEntry | None:
        return next((v for v in self.vulnerabilities if v.cve_id == cve), None)


class Software(_Strict):
    vendor: str = Field(min_length=1)
    product: str = Field(min_length=1)
    version: str


class Device(_Strict):
    id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,30}$")]
    hostname: str = Field(min_length=1)
    kind: str
    criticality: Literal["critical", "high", "medium", "low"]
    exposure: Literal["internet", "internal"]
    software: tuple[Software, ...]


class ChangeWindow(_Strict):
    label: str
    start: str
    end: str


class Inventory(_Strict):
    client: Annotated[str, StringConstraints(pattern=CLIENT_ID)]
    display_name: str
    as_of: str
    change_windows: tuple[ChangeWindow, ...]
    devices: tuple[Device, ...]


class NessusRow(_Strict):
    """A row of a Nessus CSV-style export. Column names UNVERIFIED (see SOURCES.md)."""

    plugin_id: str = Field(alias="Plugin ID")
    cve: str = Field(alias="CVE")
    cvss: str = Field(alias="CVSS v2.0 Base Score")
    risk: str = Field(alias="Risk")
    host: str = Field(alias="Host", min_length=1)
    protocol: str = Field(alias="Protocol")
    port: str = Field(alias="Port")
    name: str = Field(alias="Name")

    def cves(self) -> tuple[str, ...]:
        found = tuple(part.strip() for part in self.cve.split(",") if part.strip())
        for item in found:
            if not _CVE_RE.match(item):
                raise AdvisoriesError(f"bad CVE id in a scan row: {item!r}")
        return found


class NessusExport(_Strict):
    client: Annotated[str, StringConstraints(pattern=CLIENT_ID)]
    as_of: str
    rows: tuple[NessusRow, ...]


class PentestFinding(_Strict):
    """A vPenTest-style finding. Every field name is UNVERIFIED (see SOURCES.md)."""

    id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9-]{1,30}$")]
    title: str
    severity: str
    affected_assets: tuple[str, ...]
    cves: tuple[Annotated[str, StringConstraints(pattern=CVE_ID)], ...]
    status: str


class PentestReport(_Strict):
    client: Annotated[str, StringConstraints(pattern=CLIENT_ID)]
    as_of: str
    report: dict[str, str]
    findings: tuple[PentestFinding, ...]


# --- loading -------------------------------------------------------------------------------------------------------


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdvisoriesError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise AdvisoriesError(f"{path.name} must be a JSON object")
    if not str(data.pop("_note", "")).startswith("SYNTHETIC"):
        raise AdvisoriesError(f"{path.name} must carry a _note that says SYNTHETIC (STD-FX-3)")
    return data


def _check_client(client: str) -> str:
    if not _CLIENT_RE.match(client):
        raise AdvisoriesError(f"not a client id: {client!r}")
    return client


def fixture_path(base: Path, *parts: str, client: str) -> Path:
    """The one resolver that turns a client id into a path (STD-ID-4)."""
    return base.joinpath(*parts, f"{_check_client(client)}.json")


def _validated[T: BaseModel](model: type[T], data: Mapping[str, Any], name: str) -> T:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise AdvisoriesError(f"{name} does not have the expected shape: {exc.error_count()} problem(s)") from exc


def load_kev(base: Path = DEFAULT_FIXTURES_DIR) -> KevFeed:
    return _validated(KevFeed, _read(base / "kev-feed.json"), "kev-feed.json")


def _load_for[T: Inventory | NessusExport | PentestReport](
    model: type[T], base: Path, parts: tuple[str, ...], client: str
) -> T:
    path = fixture_path(base, *parts, client=client)
    loaded = _validated(model, _read(path), path.name)
    if loaded.client != client:
        raise AdvisoriesError(f"{path.name} is for another client: refused (C-27)")
    return loaded


def load_inventory(client: str, base: Path = DEFAULT_FIXTURES_DIR) -> Inventory:
    return _load_for(Inventory, base, ("inventory",), client)


def load_nessus(client: str, base: Path = DEFAULT_FIXTURES_DIR) -> NessusExport:
    return _load_for(NessusExport, base, ("scans", "nessus"), client)


def load_pentest(client: str, base: Path = DEFAULT_FIXTURES_DIR) -> PentestReport:
    return _load_for(PentestReport, base, ("scans", "vpentest"), client)


def list_clients(base: Path = DEFAULT_FIXTURES_DIR) -> list[str]:
    folder = base / "inventory"
    return sorted(p.stem for p in folder.glob("*.json") if _CLIENT_RE.match(p.stem)) if folder.is_dir() else []


# --- matching ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Exposed:
    """One CVE on one device of one client, with every fact that put it on the list."""

    client: str
    cve: str
    device: str
    kind: str
    exposure: Exposure
    criticality: Criticality
    in_inventory: bool
    evidence: tuple[Source, ...]
    installed_version: str | None
    nessus_plugin_ids: tuple[str, ...]
    nessus_risk: tuple[str, ...]
    pentest_ids: tuple[str, ...]
    kev_added: str
    kev_due: str
    ransomware: str
    emergency: bool
    rank: int = 0


@dataclass(frozen=True)
class Proposal:
    """A proposed change window for one emergency row. A proposal is not a change; a lead decides."""

    client: str
    cve: str
    device: str
    window_label: str | None
    window_start: str | None
    window_end: str | None
    before_kev_due: bool
    reason: str


@dataclass(frozen=True)
class ClientMatch:
    client: str
    as_of: datetime
    rows: tuple[Exposed, ...]
    proposals: tuple[Proposal, ...]
    kev_without_match: tuple[str, ...]
    scanner_hosts_not_in_inventory: tuple[str, ...]
    counts: Mapping[str, int]


@dataclass
class _Facts:
    host: str
    evidence: set[str]
    version: str | None = None
    plugins: set[str] | None = None
    risks: set[str] | None = None
    pentest: set[str] | None = None

    def __post_init__(self) -> None:
        self.plugins, self.risks, self.pentest = set(), set(), set()


def _sort_key(row: Exposed) -> tuple[Any, ...]:
    return (
        _EXPOSURE_ORDER[row.exposure],
        _CRITICALITY_ORDER[row.criticality],
        0 if row.ransomware == "Known" else 1,
        row.kev_due,
        row.cve,
        key(row.device),
    )


def _due_end(due: str) -> datetime:
    return datetime.fromisoformat(due).replace(tzinfo=UTC) + timedelta(days=1)


def propose_window(row: Exposed, inventory: Inventory, as_of: datetime) -> Proposal:
    """The first declared window that starts after ``as_of`` and ends before the KEV due date is over."""
    limit = _due_end(row.kev_due)
    later = sorted((w for w in inventory.change_windows if utc(w.start) >= as_of), key=lambda w: utc(w.start))
    for window in later:
        if utc(window.end) <= limit:
            return Proposal(
                row.client,
                row.cve,
                row.device,
                window.label,
                window.start,
                window.end,
                True,
                "first declared window that ends before the KEV due date",
            )
    if later:
        w = later[0]
        return Proposal(
            row.client,
            row.cve,
            row.device,
            w.label,
            w.start,
            w.end,
            False,
            "the next declared window is after the KEV due date: a lead decides whether to go sooner",
        )
    return Proposal(
        row.client,
        row.cve,
        row.device,
        None,
        None,
        None,
        False,
        "no declared window after the as-of time: a lead sets one",
    )


def match_client(
    client: str,
    feed: KevFeed,
    inventory: Inventory,
    nessus: NessusExport,
    pentest: PentestReport,
    as_of: datetime | None = None,
) -> ClientMatch:
    """Match the KEV feed to one client's inventory and join that client's scan and pen-test findings by CVE."""
    for label, owner in (
        ("inventory", inventory.client),
        ("nessus export", nessus.client),
        ("pen-test report", pentest.client),
    ):
        if owner != client:
            raise AdvisoriesError(f"the {label} is for {owner!r}, not {client!r}: refused (C-27)")
    moment = as_of or utc(feed.as_of)
    by_product: dict[tuple[str, str], list[KevEntry]] = defaultdict(list)
    for entry in feed.vulnerabilities:
        by_product[(key(entry.vendor_project), key(entry.product))].append(entry)
    devices = {key(d.hostname): d for d in inventory.devices}

    facts: dict[tuple[str, str], _Facts] = {}

    def slot(cve: str, host: str) -> _Facts:
        return facts.setdefault((cve, key(host)), _Facts(host, set()))

    for device in inventory.devices:
        for software in device.software:
            for entry in by_product.get((key(software.vendor), key(software.product)), []):
                item = slot(entry.cve_id, device.hostname)
                item.evidence.add("inventory")
                item.version = software.version
    nessus_hosts: set[str] = set()
    nessus_kev = nessus_other = nessus_no_cve = 0
    for scan in nessus.rows:
        nessus_hosts.add(scan.host)
        cves = scan.cves()
        if not cves:
            nessus_no_cve += 1
            continue
        hits = [c for c in cves if feed.entry(c)]
        if hits:
            nessus_kev += 1
        else:
            nessus_other += 1
        for cve in hits:
            item = slot(cve, scan.host)
            item.evidence.add("nessus")
            assert item.plugins is not None and item.risks is not None
            item.plugins.add(scan.plugin_id)
            item.risks.add(scan.risk)
    pentest_hosts: set[str] = set()
    pentest_kev = pentest_other = 0
    for finding in pentest.findings:
        pentest_hosts.update(finding.affected_assets)
        hits = [c for c in finding.cves if feed.entry(c)]
        if hits:
            pentest_kev += 1
        else:
            pentest_other += 1
        for cve in hits:
            for asset in finding.affected_assets:
                item = slot(cve, asset)
                item.evidence.add("vpentest")
                assert item.pentest is not None
                item.pentest.add(finding.id)

    rows: list[Exposed] = []
    for (cve, host_key), item in facts.items():
        kev_entry = feed.entry(cve)
        assert kev_entry is not None  # only KEV ids are ever put in `facts`
        dev = devices.get(host_key)
        exposure: Exposure = dev.exposure if dev else "unknown"
        criticality: Criticality = dev.criticality if dev else "unknown"
        assert item.plugins is not None and item.risks is not None and item.pentest is not None
        rows.append(
            Exposed(
                client=client,
                cve=cve,
                device=dev.id if dev else item.host,
                kind=dev.kind if dev else "unknown",
                exposure=exposure,
                criticality=criticality,
                in_inventory=dev is not None,
                evidence=tuple(s for s in _SOURCE_ORDER if s in item.evidence),
                installed_version=item.version,
                nessus_plugin_ids=tuple(sorted(item.plugins)),
                nessus_risk=tuple(sorted(item.risks)),
                pentest_ids=tuple(sorted(item.pentest)),
                kev_added=kev_entry.date_added,
                kev_due=kev_entry.due_date,
                ransomware=kev_entry.ransomware,
                emergency=exposure == "internet" or kev_entry.ransomware == "Known",
            )
        )
    rows.sort(key=_sort_key)
    ranked = tuple(replace(r, rank=i) for i, r in enumerate(rows, start=1))
    proposals = tuple(propose_window(r, inventory, moment) for r in ranked if r.emergency)
    matched = {r.cve for r in ranked}
    inventory_hosts = {key(d.hostname) for d in inventory.devices}
    stray = tuple(sorted({h for h in nessus_hosts | pentest_hosts if key(h) not in inventory_hosts}, key=key))
    counts = {
        "kev_entries": len(feed.vulnerabilities),
        "kev_entries_matched": len(matched),
        "kev_entries_without_match": len(feed.vulnerabilities) - len(matched),
        "exposed_rows": len(ranked),
        "devices_exposed": len({key(r.device) for r in ranked}),
        "emergency_rows": sum(r.emergency for r in ranked),
        "proposals": len(proposals),
        "nessus_rows": len(nessus.rows),
        "nessus_rows_kev": nessus_kev,
        "nessus_rows_not_kev": nessus_other,
        "nessus_rows_no_cve": nessus_no_cve,
        "pentest_findings": len(pentest.findings),
        "pentest_findings_kev": pentest_kev,
        "pentest_findings_not_kev": pentest_other,
    }
    unmatched = tuple(sorted(e.cve_id for e in feed.vulnerabilities if e.cve_id not in matched))
    return ClientMatch(client, moment, ranked, proposals, unmatched, stray, counts)


def match_one(client: str, base: Path = DEFAULT_FIXTURES_DIR, as_of: datetime | None = None) -> ClientMatch:
    """Load one client's fixtures and match them. The client is explicit; nothing else is read."""
    return match_client(
        client,
        load_kev(base),
        load_inventory(client, base),
        load_nessus(client, base),
        load_pentest(client, base),
        as_of,
    )


# --- report --------------------------------------------------------------------------------------------------------


def _row_dict(row: Exposed) -> dict[str, Any]:
    return {
        "rank": row.rank,
        "cve": row.cve,
        "device": row.device,
        "kind": row.kind,
        "factors": {
            "kev_listed": True,
            "exposure": row.exposure,
            "criticality": row.criticality,
            "ransomware_use": row.ransomware,
            "kev_due": row.kev_due,
        },
        "evidence": list(row.evidence),
        "in_inventory": row.in_inventory,
        "installed_version": row.installed_version,
        "version_checked": False,
        "nessus_plugin_ids": list(row.nessus_plugin_ids),
        "nessus_risk": list(row.nessus_risk),
        "pentest_finding_ids": list(row.pentest_ids),
        "emergency": row.emergency,
    }


def _proposal_dict(p: Proposal) -> dict[str, Any]:
    window = None if p.window_start is None else {"label": p.window_label, "start": p.window_start, "end": p.window_end}
    return {
        "client": p.client,
        "cve": p.cve,
        "device": p.device,
        "proposed_window": window,
        "before_kev_due": p.before_kev_due,
        "reason": p.reason,
        "deployed": False,
    }


def build_report(matches: Iterable[ClientMatch], feed: KevFeed) -> dict[str, Any]:
    """Collect per-client results (each made under one client) into one report; counts are reconciled."""
    ordered = sorted(matches, key=lambda m: m.client)
    by_cve: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for match in ordered:
        for row in match.rows:
            by_cve[row.cve][row.client].append(row.device)
    cve_list: list[dict[str, Any]] = []
    for cve in sorted(by_cve):
        entry = feed.entry(cve)
        assert entry is not None
        cve_list.append(
            {
                "cve": cve,
                "vendor": entry.vendor_project,
                "product": entry.product,
                "ransomware_use": entry.ransomware,
                "kev_due": entry.due_date,
                "clients": [{"client": c, "devices": sorted(d, key=key)} for c, d in sorted(by_cve[cve].items())],
            }
        )
    emergency = [
        {**_row_dict(r), "client": m.client, "proposal": _proposal_dict(p)}
        for m in ordered
        for r, p in zip((r for r in m.rows if r.emergency), m.proposals, strict=True)
    ]
    summary = {
        "clients_checked": len(ordered),
        "clients_with_exposure": sum(1 for m in ordered if m.rows),
        "kev_entries": len(feed.vulnerabilities),
        "kev_entries_matched_anywhere": len(by_cve),
        "exposed_rows": sum(len(m.rows) for m in ordered),
        "emergency_rows": sum(m.counts["emergency_rows"] for m in ordered),
        "proposals": sum(len(m.proposals) for m in ordered),
    }
    listed = sum(len(c["devices"]) for e in cve_list for c in e["clients"])
    if summary["exposed_rows"] != listed:
        raise AdvisoriesError("counts do not reconcile: exposed rows differ from the per-CVE device lists")
    if summary["emergency_rows"] != len(emergency) or summary["proposals"] != len(emergency):
        raise AdvisoriesError("counts do not reconcile: emergency rows differ from the emergency list")
    return {
        "label": "SYNTHETIC fixtures; fixture-based result; report and proposed windows only",
        "as_of": stamp(ordered[0].as_of) if ordered else feed.as_of,
        "mode": NOT_DEPLOYED,
        "emergency_rule": EMERGENCY_RULE,
        "rank_note": "rank is a position in the sort, not a score",
        "match_note": (
            "product-level match only: the KEV feed has no version range, "
            "so each row needs a person to check the installed version"
        ),
        "summary": summary,
        "by_cve": cve_list,
        "clients": {
            m.client: {
                "counts": dict(m.counts),
                "rows": [_row_dict(r) for r in m.rows],
                "kev_entries_without_match": list(m.kev_without_match),
                "scanner_hosts_not_in_inventory": list(m.scanner_hosts_not_in_inventory),
            }
            for m in ordered
        },
        "emergency_patch_list": emergency,
    }


def report_for(
    clients: Iterable[str] | None = None, base: Path = DEFAULT_FIXTURES_DIR, as_of: datetime | None = None
) -> dict[str, Any]:
    feed = load_kev(base)
    names = list(clients) if clients is not None else list_clients(base)
    return build_report([match_one(c, base, as_of) for c in names], feed)
