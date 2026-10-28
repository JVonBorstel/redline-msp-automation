"""Device reconciliation across RMM, Intune and PSA assets for one client (B-61, specs/B-61.md; W-EP-01; C-27, C-21).

For one client this reads three lists through that client's own adapters (RMM devices with their hardware audit, Intune
managed devices, PSA configuration items) and builds one device list:

1. records whose serial is usable are matched by serial (case and spaces ignored; placeholder serials such as
   ``To be filled by O.E.M.`` count as no serial, ``config.json``);
2. a record without a usable serial is then matched by name (case ignored, DNS suffix dropped) when exactly one
   device carries that name; two records whose serials differ are never merged because their names agree.

Every record lands in exactly one device, so the counts reconcile to the adapters' lists (B61-2). Each mismatch is
listed: ``only-in-one-system`` (a device that one system knows and the other two do not), ``stale`` (an RMM or Intune
record not seen for ``stale_days``, or with no readable time) and ``duplicate`` (one system holds a device twice).

Isolation (C-27). The three adapters must belong to the same client, and the RMM site's PSA company id (when it names
one) must be the PSA reader's company; otherwise nothing is compared (``ReconcileError``). Each adapter already drops
every record of another site, tenant or company. Read-only: nothing here writes, runs or changes a device.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from adapters.binding import DEFAULT_CLIENT_DIR
from adapters.intune import DEFAULT_INTUNE_DIR, IntuneAdapter, build_intune_adapter
from adapters.rmm import DEFAULT_RMM_DIR, RmmAdapter, build_rmm_adapter
from workflows.device_reconcile.psa_assets import DEFAULT_PSA_ASSETS_DIR, PsaAssetsMock, build_psa_assets

DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.json")

System = Literal["rmm", "intune", "psa"]
SYSTEMS: tuple[System, ...] = ("rmm", "intune", "psa")
MismatchType = Literal["only-in-one-system", "stale", "duplicate"]
MISMATCH_TYPES: tuple[MismatchType, ...] = ("only-in-one-system", "stale", "duplicate")
NOT_RUN = "listed read-only; not vetted into the lever registry, so the program never runs it (D6-26)"


class ReconcileError(ValueError):
    """The input is bad (config, as-of time, adapters of different clients, a failed read); nothing was compared."""


class ReconcileConfig(BaseModel):
    """The workflow's configuration; unknown keys fail the load (STD-CF-3)."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    version: Literal[1]
    note: str = Field(default="", alias="_note")
    stale_days: int = Field(ge=1, le=365)
    placeholder_serials: tuple[str, ...]


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> ReconcileConfig:
    try:
        return ReconcileConfig.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        raise ReconcileError(f"cannot load device reconcile config from {path}: {exc}") from exc


def utc(value: str) -> datetime:
    """Parse an ISO 8601 timestamp (``Z`` allowed) as UTC."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ReconcileError(f"{value!r} is not an ISO 8601 timestamp") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _seen(value: Any) -> datetime | None:
    """A last-seen time as UTC: ISO 8601 text or epoch milliseconds (RMM format UNVERIFIED); None if unreadable."""
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, int | float):
            return datetime.fromtimestamp(value / 1000, tz=UTC)
        if isinstance(value, str) and value:
            return utc(value)
    except (ReconcileError, OverflowError, OSError, ValueError):
        return None
    return None


def norm_name(value: Any) -> str:
    """``XRAY-WS01.contosodental.example`` and ``xray-ws01`` are one name."""
    return str(value or "").strip().split(".")[0].casefold()


def norm_serial(value: Any, placeholders: frozenset[str]) -> str | None:
    """Upper-case serial without spaces, or None when it is empty or a placeholder."""
    text = str(value or "").strip()
    if not text or text.casefold() in placeholders:
        return None
    return "".join(text.split()).upper()


@dataclass(frozen=True, slots=True)
class DeviceRecord:
    system: System
    record_id: str
    name: str
    serial: str | None
    last_seen: str | None
    stale: bool


@dataclass(frozen=True, slots=True)
class Finding:
    type: MismatchType
    system: System
    device: str
    record_ids: tuple[str, ...]
    detail: str


@dataclass(slots=True)
class Device:
    key: str
    matched_by: Literal["serial", "name"]
    records: list[DeviceRecord] = field(default_factory=list)

    @property
    def systems(self) -> tuple[System, ...]:
        present = {r.system for r in self.records}
        return tuple(s for s in SYSTEMS if s in present)

    def names(self) -> set[str]:
        return {norm_name(r.name) for r in self.records}


@dataclass(frozen=True, slots=True)
class Reconciliation:
    client: str
    as_of: datetime
    inputs: Mapping[System, int]
    devices: tuple[Device, ...]
    findings: tuple[Finding, ...]

    def counts(self) -> dict[str, Any]:
        placed = Counter(r.system for d in self.devices for r in d.records)
        by_type = Counter(f.type for f in self.findings)
        return {
            "records": {s: self.inputs[s] for s in SYSTEMS},
            "placed": {s: placed[s] for s in SYSTEMS},
            "devices": len(self.devices),
            "in_all_three": sum(1 for d in self.devices if len(d.systems) == len(SYSTEMS)),
            "findings": {t: by_type[t] for t in MISMATCH_TYPES},
            "reconciles": all(placed[s] == self.inputs[s] for s in SYSTEMS),
        }


def _ok(result: Any, what: str) -> Any:
    if not result.ok:
        raise ReconcileError(f"{what}: {result.reason}")
    return result.data


def collect(
    rmm: RmmAdapter, intune: IntuneAdapter, psa: PsaAssetsMock, as_of: datetime, config: ReconcileConfig
) -> list[DeviceRecord]:
    """Read the three lists of one client and normalise them. Refuses adapters of different clients (C-27)."""
    if not (rmm.client == intune.client == psa.client):
        raise ReconcileError("adapters belong to different clients; nothing is compared (C-27)")
    site = _ok(rmm.get_site(), "rmm site")
    linked = site.get("autotaskCompanyId")
    if linked not in (None, "") and str(linked) != psa.company_id:
        raise ReconcileError("the RMM site is linked to another PSA company; nothing is compared (C-27)")
    placeholders = frozenset(p.casefold() for p in config.placeholder_serials)
    cutoff = as_of - timedelta(days=config.stale_days)
    out: list[DeviceRecord] = []

    def record(system: System, rid: Any, name: Any, serial: Any, seen: Any, ages: bool) -> None:
        when = _seen(seen)
        stale = ages and (when is None or when < cutoff)
        last = when.isoformat().replace("+00:00", "Z") if when else None
        out.append(DeviceRecord(system, str(rid), str(name or ""), norm_serial(serial, placeholders), last, stale))

    for d in _ok(rmm.list_devices(), "rmm devices"):
        audit = rmm.get_device_audit(str(d.get("uid")))
        serial = (audit.data or {}).get("bios", {}).get("serialNumber") if audit.ok else None
        record("rmm", d.get("uid"), d.get("hostname"), serial, d.get("lastSeen"), True)
    for d in _ok(intune.list_managed_devices(), "intune devices"):
        record("intune", d.get("id"), d.get("deviceName"), d.get("serialNumber"), d.get("lastSyncDateTime"), True)
    for ci in _ok(psa.list_configuration_items(), "psa configuration items"):
        record("psa", ci.get("id"), ci.get("referenceTitle"), ci.get("serialNumber"), None, False)
    return out


def match(records: list[DeviceRecord]) -> list[Device]:
    """Serial first, then name (see the module docstring). Deterministic: input order does not change the result."""
    ordered = sorted(records, key=lambda r: (SYSTEMS.index(r.system), r.record_id))
    devices: dict[str, Device] = {}
    for r in ordered:
        if r.serial is not None:
            devices.setdefault(f"serial:{r.serial}", Device(f"serial:{r.serial}", "serial")).records.append(r)
    for r in ordered:
        if r.serial is not None:
            continue
        name = norm_name(r.name)
        candidates = [d for d in devices.values() if name and name in d.names()]
        if len(candidates) == 1:
            candidates[0].records.append(r)
            continue
        key = f"name:{name or r.system + ':' + r.record_id}"
        if len(candidates) > 1:
            key = f"{key}#{r.system}:{r.record_id}"  # ambiguous: never guess which device it is
        devices.setdefault(key, Device(key, "name")).records.append(r)
    return sorted(devices.values(), key=lambda d: d.key)


def findings(devices: list[Device]) -> list[Finding]:
    out: list[Finding] = []
    for d in devices:
        systems = d.systems
        if len(systems) == 1:
            only = systems[0]
            missing = ", ".join(s for s in SYSTEMS if s != only)
            ids = tuple(r.record_id for r in d.records)
            out.append(Finding("only-in-one-system", only, d.key, ids, f"only in {only}; not in {missing}"))
        per_system: dict[System, list[DeviceRecord]] = defaultdict(list)
        for r in d.records:
            per_system[r.system].append(r)
        for s, rows in per_system.items():
            if len(rows) > 1:
                ids = tuple(r.record_id for r in rows)
                out.append(Finding("duplicate", s, d.key, ids, f"{s} holds this device {len(rows)} times"))
        for r in d.records:
            if r.stale:
                seen = f"last seen {r.last_seen}" if r.last_seen else "no readable last-seen time"
                out.append(Finding("stale", r.system, d.key, (r.record_id,), seen))
    order = {t: i for i, t in enumerate(MISMATCH_TYPES)}
    return sorted(out, key=lambda f: (order[f.type], f.device, SYSTEMS.index(f.system), f.record_ids))


def reconcile(
    rmm: RmmAdapter, intune: IntuneAdapter, psa: PsaAssetsMock, as_of: datetime, config: ReconcileConfig
) -> Reconciliation:
    """One client's device list and every mismatch (B61-1, B61-2)."""
    records = collect(rmm, intune, psa, as_of, config)
    devices = match(records)
    inputs = Counter(r.system for r in records)
    return Reconciliation(rmm.client, as_of, {s: inputs[s] for s in SYSTEMS}, tuple(devices), tuple(findings(devices)))


@dataclass(frozen=True, slots=True)
class Sources:
    rmm: RmmAdapter
    intune: IntuneAdapter
    psa: PsaAssetsMock


@dataclass(frozen=True, slots=True)
class SourcesResult:
    """Outcome of ``build_sources`` (STD-ER-1): never raises; ``sources`` is set only when ``ok``."""

    ok: bool
    reason: str
    sources: Sources | None = None


def build_sources(
    client: str,
    *,
    config_dir: Path = DEFAULT_CLIENT_DIR,
    rmm_dir: Path = DEFAULT_RMM_DIR,
    intune_dir: Path = DEFAULT_INTUNE_DIR,
    psa_dir: Path = DEFAULT_PSA_ASSETS_DIR,
) -> SourcesResult:
    """Select the three adapters from the client's bindings. Any non-mock binding fails closed (B61-3)."""
    rmm = build_rmm_adapter(client, config_dir=config_dir, fixtures_dir=rmm_dir)
    intune = build_intune_adapter(client, config_dir=config_dir, fixtures_dir=intune_dir)
    psa = build_psa_assets(client, config_dir=config_dir, fixtures_dir=psa_dir)
    for name, built in (("rmm", rmm), ("intune", intune), ("psa", psa)):
        if not built.ok:
            return SourcesResult(False, f"{name}: {built.reason}")
    if not (
        isinstance(rmm.adapter, RmmAdapter)
        and isinstance(intune.adapter, IntuneAdapter)
        and isinstance(psa.adapter, PsaAssetsMock)
    ):
        return SourcesResult(False, "adapter of an unexpected type; nothing built")
    return SourcesResult(True, "ok", Sources(rmm.adapter, intune.adapter, psa.adapter))


def component_inventory(rmm: RmmAdapter) -> list[dict[str, Any]]:
    """The RMM account's existing components, read-only (B61-4, D6-26). Nothing here can run one."""
    rows = _ok(rmm.list_components(), "rmm components")
    return [
        {
            "uid": c.get("uid"),
            "name": c.get("name"),
            "categoryCode": c.get("categoryCode"),
            "credentialsRequired": c.get("credentialsRequired"),
            "variables": [v.get("name") for v in c.get("variables") or [] if isinstance(v, dict)],
            "vetted": False,
            "run_by_program": False,
            "status": NOT_RUN,
        }
        for c in rows
    ]


def summary(rec: Reconciliation, components: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """JSON-ready view of one reconciliation (the CLI prints this)."""
    return {
        "client": rec.client,
        "as_of": rec.as_of.isoformat().replace("+00:00", "Z"),
        "counts": rec.counts(),
        "devices": [
            {
                "device": d.key,
                "matched_by": d.matched_by,
                "systems": list(d.systems),
                "records": [
                    {
                        "system": r.system,
                        "id": r.record_id,
                        "name": r.name,
                        "serial": r.serial,
                        "last_seen": r.last_seen,
                    }
                    for r in d.records
                ],
            }
            for d in rec.devices
        ],
        "findings": [
            {"type": f.type, "system": f.system, "device": f.device, "records": list(f.record_ids), "detail": f.detail}
            for f in rec.findings
        ],
        "rmm_components": components or [],
    }
