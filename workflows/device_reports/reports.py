"""Device compliance, encryption and LAPS coverage reports and provisioning readiness (B-64, specs/B-64.md; W-EP-05,
W-EP-06, W-EP-11, W-ONB-06; C-20, C-21, C-10).

For one client this takes the device list of the B-61 reconciliation (RMM, Intune and PSA assets matched by serial,
then name) and says, per device:

- **compliance**: ``compliant``, ``non-compliant`` (Intune says so), ``stale`` (Intune has not heard from it for
  ``stale_days``, B-61) or ``not-in-intune`` (no Intune record), each with the reasons;
- **encryption**: ``encrypted`` / ``not-encrypted`` from Intune's ``isEncrypted``, or ``unknown``;
- **LAPS**: ``covered`` (an escrowed local-admin password was backed up within ``laps_max_backup_age_days``),
  ``stale-backup``, ``not-backed-up``, ``not-applicable`` (Intune device that is not Windows) or ``unknown``.

It also lists the client's incoming hires with Autopilot readiness: ``ready`` or what is missing.

Status only (B64-2). The LAPS source is read through ``LAPS_FIELDS``, an allow-list of metadata fields; any other field
(a password, a credential list) is never copied, only counted in ``gaps``. Nothing here asks for a recovery key. A final
check, :func:`find_secrets`, stops the report if any secret-shaped value or secret-named key is in the output.

Read-only and one client per run: the devices come from that client's own adapters (B-61, which refuses a mix), the
overlay file must name the client and the Intune tenant, and a LAPS record that matches no device of this client is
counted in ``gaps`` and never as coverage (C-27). The date is the ``as_of`` argument, never the clock (STD-TS-4).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from adapters.base import AdapterError
from adapters.binding import CLIENT_ID
from adapters.intune import DEFAULT_INTUNE_DIR, IntuneMock
from adapters.rmm import DEFAULT_RMM_DIR, RmmMock
from core.guard.classify import DataClass
from core.paths import REPO_ROOT
from workflows.device_reconcile import (
    DEFAULT_PSA_ASSETS_DIR,
    PsaAssetsMock,
    ReconcileError,
    Sources,
    build_sources,
    reconcile,
)
from workflows.device_reconcile import load_config as load_reconcile_config
from workflows.device_reconcile.reconcile import utc

DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.json")
DEFAULT_OVERLAY_DIR = Path(__file__).with_name("fixtures")
DEFAULT_OUT_DIR = REPO_ROOT / "build" / "device-reports"
KIND = "device-reports"
VERSION = 1
DATA_CLASS = DataClass.DC3  # names the user of each device (UPN): end-user PII
NOTE = (
    "Synthetic data (fixture-based). Status only: no recovery key and no local-admin password is read or shown. "
    "A report: nothing was changed on any device."
)
# The only fields copied from a LAPS record (Graph deviceLocalCredentialInfo, UNVERIFIED). The credentials are not here.
LAPS_FIELDS: tuple[str, ...] = ("id", "deviceName", "lastBackupDateTime", "refreshDateTime")
COMPLIANCE_STATUSES = ("compliant", "non-compliant", "stale", "not-in-intune")
ENCRYPTION_STATUSES = ("encrypted", "not-encrypted", "unknown")
LAPS_STATUSES = ("covered", "stale-backup", "not-backed-up", "not-applicable", "unknown")
READY_PROFILE = "assignedInSync"

UNVERIFIED: tuple[str, ...] = (
    "Intune managedDevice property names are verified (fixtures/intune/SOURCES.md); what complianceState and "
    "isEncrypted mean on every platform, and how fresh they are, is not.",
    "The compliance reason is derived here (Intune's state, a stale sync, no Intune record). The managedDevice "
    "resource carries no reason text; per-setting reasons (compliance policy and setting states) are not modelled.",
    "The LAPS metadata shape (Graph deviceLocalCredentialInfo: id, deviceName, lastBackupDateTime, refreshDateTime), "
    "joining its id to the Entra device id, and the permission a real read needs are written from memory, not checked.",
    "The Autopilot shape (Graph windowsAutopilotDeviceIdentity: serialNumber, groupTag, enrollmentState, "
    "deploymentProfileAssignmentStatus) and the value assignedInSync meaning ready are not checked against "
    "Microsoft's pages.",
    "Where incoming hires come from (HR, PSA ticket, onboarding plan) is open; the hire records are invented.",
    "The 35-day LAPS backup age and the 7-day urgency window are prototype defaults, not measured.",
    "Servers are not told apart from workstations: a server with no Intune record shows as not-in-intune. "
    "Domain-joined "
    "(Active Directory) LAPS is not covered.",
    "No call was made to any real tenant, RMM or PSA; every figure is computed from this repo's fixtures.",
)


class ReportError(ValueError):
    """Bad input, a source that does not belong to the client, a failed verification, or a secret-shaped output."""


class ReportConfig(BaseModel):
    """Report settings; unknown keys fail the load (STD-CF-3)."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    version: Literal[1]
    note: str = Field(default="", alias="_note")
    laps_max_backup_age_days: int = Field(ge=1, le=365)
    starts_soon_days: int = Field(ge=0, le=90)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> ReportConfig:
    try:
        return ReportConfig.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        raise ReportError(f"cannot load device reports config from {path}: {exc}") from exc


def parse_as_of(value: str) -> datetime:
    try:
        return utc(value)
    except ReconcileError as exc:
        raise ReportError(str(exc)) from exc


# -- secret guard --------------------------------------------------------------------------------------------------
_KEY_NAME = re.compile(r'"[^"]*(?:password|recovery|credential|secret|token)[^"]*"\s*:', re.IGNORECASE)
_RECOVERY_KEY = re.compile(r"(?<!\d)\d{6}(?:-\d{6}){7}(?!\d)")
_B64_RUN = re.compile(
    r"(?<![A-Za-z0-9+/=])(?=[A-Za-z0-9+/=]*[A-Z])(?=[A-Za-z0-9+/=]*[a-z])(?=[A-Za-z0-9+/=]*\d)[A-Za-z0-9+/=]{20,}"
    r"(?![A-Za-z0-9+/=])"
)
_PASSWORD_RUN = re.compile(r"[^\s\"',;]{16,}")


def find_secrets(text: str) -> list[str]:
    """What kind of secret-shaped content ``text`` holds (never the content itself). Empty means none was seen.

    Heuristic and biased to over-reporting, like the audit redactor (C-10): a BitLocker-style recovery key (eight groups
    of six digits), a mixed-case run of 20 or more base64 characters, a long run mixing upper, lower, digit and symbol
    (a password), or a JSON key named like a secret. Plain hex (a SHA-256), GUIDs, serials and paths do not match.
    """
    found: list[str] = []
    if _RECOVERY_KEY.search(text):
        found.append("recovery-key-shaped value")
    if _B64_RUN.search(text):
        found.append("long mixed-case base64-shaped value")
    for run in _PASSWORD_RUN.findall(text):
        if (
            any(c.isupper() for c in run)
            and any(c.islower() for c in run)
            and any(c.isdigit() for c in run)
            and any(not c.isalnum() and c not in "-_./:@" for c in run)
        ):
            found.append("password-shaped value")
            break
    if _KEY_NAME.search(text):
        found.append("secret-named key")
    return found


# -- hashing and files ---------------------------------------------------------------------------------------------
def canonical_bytes(body: dict[str, Any]) -> bytes:
    """Sorted keys, two-space indent, ASCII, one trailing newline: the same inputs give the same bytes."""
    return (json.dumps(body, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sidecar(path: Path) -> Path:
    return path.with_name(path.name + ".sha256")


def _source(path: Path) -> dict[str, str]:
    path = Path(path).resolve()
    try:
        shown = path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        shown = path.name
    try:
        return {"path": shown, "sha256": sha256_hex(path.read_bytes())}
    except OSError as exc:
        raise ReportError(f"cannot read source {path.name}: {exc}") from None


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return utc(value)
    except ReconcileError:
        return None


# -- the overlay: LAPS metadata, Autopilot identities, incoming hires -----------------------------------------------
@dataclass(frozen=True, slots=True)
class Overlay:
    laps: dict[str, dict[str, Any]]  # Entra device id -> allow-listed fields of the newest record
    laps_ignored_fields: int
    autopilot: dict[str, dict[str, Any]]  # upper-case serial -> record
    hires: tuple[dict[str, Any], ...]


def _list(data: dict[str, Any], *path: str) -> list[dict[str, Any]]:
    node: Any = data
    for key in path:
        node = node.get(key, {}) if isinstance(node, dict) else {}
    if path and isinstance(node, list):
        return [r for r in node if isinstance(r, dict)]
    return []


def _serial(value: Any) -> str | None:
    text = "".join(str(value or "").split()).upper()
    return text or None


def load_overlay(client: str, tenant_id: str, root: Path) -> Overlay:
    """Read the client's overlay file. It must name this client and this Intune tenant (C-27)."""
    try:
        data = json.loads((Path(root) / f"{client}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReportError(f"no readable device-security fixture for this client ({type(exc).__name__})") from exc
    if not isinstance(data, dict) or data.get("client") != client or data.get("tenantId") != tenant_id:
        raise ReportError("device-security fixture does not belong to this client's tenant; nothing is reported")
    laps: dict[str, dict[str, Any]] = {}
    ignored = 0
    for entry in _list(data, "localCredentials", "value"):
        ignored += len([k for k in entry if k not in LAPS_FIELDS])
        row = {k: entry.get(k) for k in LAPS_FIELDS}
        key = str(row["id"] or "")
        old = laps.get(key)
        if key and (
            old is None
            or (_when(row["lastBackupDateTime"]) or datetime.min.replace(tzinfo=UTC))
            > (_when(old["lastBackupDateTime"]) or datetime.min.replace(tzinfo=UTC))
        ):
            laps[key] = row
    autopilot: dict[str, dict[str, Any]] = {}
    for entry in _list(data, "autopilotDevices", "value"):
        serial = _serial(entry.get("serialNumber"))
        if serial:
            autopilot[serial] = {
                k: entry.get(k) for k in ("serialNumber", "enrollmentState", "deploymentProfileAssignmentStatus")
            }
    hires = tuple(
        {k: h.get(k) for k in ("hireId", "displayName", "userPrincipalName", "startDate", "assignedSerial")}
        for h in _list(data, "incomingHires")
    )
    return Overlay(laps, ignored, autopilot, hires)


# -- building the report -------------------------------------------------------------------------------------------
def _laps_row(intune: dict[str, Any] | None, overlay: Overlay, as_of: datetime, cfg: ReportConfig) -> dict[str, Any]:
    if intune is None or not intune.get("azureADDeviceId"):
        return {"status": "unknown", "last_backup": None}
    if not str(intune.get("operatingSystem") or "").casefold().startswith("windows"):
        return {"status": "not-applicable", "last_backup": None}
    record = overlay.laps.get(str(intune["azureADDeviceId"]))
    backed_up = _when(record["lastBackupDateTime"]) if record else None
    if backed_up is None:
        return {"status": "not-backed-up", "last_backup": None}
    fresh = as_of - backed_up <= timedelta(days=cfg.laps_max_backup_age_days)
    return {"status": "covered" if fresh else "stale-backup", "last_backup": _iso(backed_up)}


def _hire_rows(overlay: Overlay, as_of: datetime, cfg: ReportConfig) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for hire in overlay.hires:
        try:
            start = date.fromisoformat(str(hire["startDate"]))
        except ValueError:
            raise ReportError(f"hire {hire['hireId']!r} has no valid start date") from None
        serial = _serial(hire["assignedSerial"])
        record = overlay.autopilot.get(serial) if serial else None
        status = record["deploymentProfileAssignmentStatus"] if record else None
        if serial is None:
            reasons = ["no-device-assigned"]
        elif record is None:
            reasons = ["serial-not-registered-in-autopilot"]
        elif status != READY_PROFILE:
            reasons = [f"autopilot-profile: {status}"]
        else:
            reasons = []
        days = (start - as_of.date()).days
        rows.append(
            {
                "hire_id": hire["hireId"],
                "display_name": hire["displayName"],
                "user": hire["userPrincipalName"],
                "start_date": start.isoformat(),
                "days_until_start": days,
                "assigned_serial": serial,
                "autopilot_profile": status,
                "readiness": "ready" if not reasons else "not-ready",
                "reasons": reasons,
                "urgent": bool(reasons) and days <= cfg.starts_soon_days,
            }
        )
    return sorted(rows, key=lambda r: (r["start_date"], str(r["hire_id"])))


def _intune_for(device: Any, by_id: dict[str, dict[str, Any]]) -> tuple[Any, dict[str, Any]] | None:
    """The device's newest Intune record (ties: lowest id)."""
    mine = [(r, by_id[r.record_id]) for r in device.records if r.system == "intune" and r.record_id in by_id]
    if not mine:
        return None
    never = datetime.min.replace(tzinfo=UTC)
    return sorted(mine, key=lambda p: (-(_when(p[0].last_seen) or never).timestamp(), p[0].record_id))[0]


def build_report(
    sources: Sources,
    overlay: Overlay,
    as_of: datetime,
    cfg: ReportConfig,
    source_files: list[dict[str, str]],
) -> dict[str, Any]:
    """One client's report as a JSON-ready dict (B64-1 to B64-3). Raises ReportError on a secret-shaped output."""
    rec = reconcile(sources.rmm, sources.intune, sources.psa, as_of, load_reconcile_config())
    listed = sources.intune.list_managed_devices()
    if not listed.ok:
        raise ReportError(f"intune devices: {listed.reason}")
    by_id = {str(r.get("id")): r for r in listed.data or []}
    intune_azure_ids = {str(r.get("azureADDeviceId")) for r in by_id.values() if r.get("azureADDeviceId")}

    devices: list[dict[str, Any]] = []
    attention: list[dict[str, Any]] = []
    for dev in rec.devices:
        found = _intune_for(dev, by_id)
        record, raw = (found[0], found[1]) if found else (None, None)
        reasons: list[str] = []
        if raw is None or record is None:
            compliance = {"status": "not-in-intune", "reasons": ["not-in-intune: no Intune record"]}
            encryption = "unknown"
        else:
            state = raw.get("complianceState")
            if state != "compliant":
                reasons.append(f"intune-state: {state or 'unknown'}")
            if record.stale:
                reasons.append(
                    f"stale-sync: last sync {record.last_seen}"
                    if record.last_seen
                    else "stale-sync: no readable last sync"
                )
            status = "non-compliant" if state != "compliant" else ("stale" if record.stale else "compliant")
            compliance = {"status": status, "reasons": reasons}
            flag = raw.get("isEncrypted")
            encryption = "encrypted" if flag is True else ("not-encrypted" if flag is False else "unknown")
        laps = _laps_row(raw, overlay, as_of, cfg)
        first = dev.records[0]
        row = {
            "device": dev.key,
            "name": first.name,
            "serial": next((r.serial for r in dev.records if r.serial), None),
            "systems": list(dev.systems),
            "user": raw.get("userPrincipalName") if raw else None,
            "compliance": compliance,
            "encryption": encryption,
            "laps": laps,
        }
        devices.append(row)
        why = list(compliance["reasons"])
        if raw is not None:
            if encryption == "not-encrypted":
                why.append("encryption: disk is not encrypted")
            elif encryption == "unknown":
                why.append("encryption: status unknown")
            if laps["status"] == "stale-backup":
                why.append(f"laps: last backup {laps['last_backup']} is older than {cfg.laps_max_backup_age_days} days")
            elif laps["status"] == "not-backed-up":
                why.append("laps: no backup recorded")
            elif laps["status"] == "unknown":
                why.append("laps: coverage unknown")
        if why:
            attention.append({"device": dev.key, "name": first.name, "reasons": why})

    count = {
        "compliance": {s: sum(1 for d in devices if d["compliance"]["status"] == s) for s in COMPLIANCE_STATUSES},
        "encryption": {s: sum(1 for d in devices if d["encryption"] == s) for s in ENCRYPTION_STATUSES},
        "laps": {s: sum(1 for d in devices if d["laps"]["status"] == s) for s in LAPS_STATUSES},
    }
    count["laps"]["applicable"] = sum(count["laps"][s] for s in ("covered", "stale-backup", "not-backed-up"))
    hires = _hire_rows(overlay, as_of, cfg)
    assigned = {h["assigned_serial"] for h in hires if h["assigned_serial"]}
    prov_counts = {
        "hires": len(hires),
        "ready": sum(1 for h in hires if h["readiness"] == "ready"),
        "not-ready": sum(1 for h in hires if h["readiness"] != "ready"),
        "autopilot_devices": len(overlay.autopilot),
        "autopilot_unassigned": len([s for s in overlay.autopilot if s not in assigned]),
    }
    body: dict[str, Any] = {
        "kind": KIND,
        "version": VERSION,
        "client": rec.client,
        "as_of": _iso(as_of),
        "data_class": DATA_CLASS.label,
        "note": NOTE,
        "policy": {
            "stale_days": load_reconcile_config().stale_days,
            "laps_max_backup_age_days": cfg.laps_max_backup_age_days,
            "starts_soon_days": cfg.starts_soon_days,
        },
        "sources": source_files,
        "counts": {"devices": len(devices), "reconcile": rec.counts(), **count},
        "gaps": {
            "orphan_laps_records": len([i for i in overlay.laps if i not in intune_azure_ids]),
            "ignored_laps_fields": overlay.laps_ignored_fields,
        },
        "devices": devices,
        "attention": attention,
        "provisioning": {"counts": prov_counts, "hires": hires},
        "unverified": list(UNVERIFIED),
    }
    found_secrets = find_secrets(canonical_bytes(body).decode("ascii"))
    if found_secrets:
        raise ReportError(f"secret-shaped content in the report ({', '.join(found_secrets)}); nothing is written")
    return body


def build_client_report(
    client: str,
    *,
    as_of: datetime | None = None,
    config_dir: Path | None = None,
    rmm_dir: Path = DEFAULT_RMM_DIR,
    intune_dir: Path = DEFAULT_INTUNE_DIR,
    psa_dir: Path = DEFAULT_PSA_ASSETS_DIR,
    overlay_dir: Path = DEFAULT_OVERLAY_DIR,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> dict[str, Any]:
    """Build one client's report. Without ``config_dir`` the three mocks are built from their fixtures; with it they
    are selected from that folder's bindings and any non-mock binding fails closed (``real adapter not configured``).
    ``as_of`` defaults to the RMM fixture's pinned time."""
    if not isinstance(client, str) or not CLIENT_ID.fullmatch(client):
        raise ReportError(f"{client!r} is not a client id")
    cfg = load_config(config_path)
    try:
        if config_dir is not None:
            built = build_sources(
                client, config_dir=config_dir, rmm_dir=rmm_dir, intune_dir=intune_dir, psa_dir=psa_dir
            )
            if built.sources is None:
                raise ReportError(built.reason)
            sources = built.sources
        else:
            sources = Sources(
                RmmMock.for_fixture(client, rmm_dir),
                IntuneMock.for_fixture(client, intune_dir),
                PsaAssetsMock.for_fixture(client, psa_dir),
            )
        if as_of is None:
            if not isinstance(sources.rmm, RmmMock):
                raise ReportError("as_of is required for this adapter")
            as_of = parse_as_of(sources.rmm.as_of)
        overlay = load_overlay(client, sources.intune.external_id, overlay_dir)
        files = [
            {"system": name, **_source(root / f"{client}.json")}
            for name, root in (
                ("rmm", rmm_dir),
                ("intune", intune_dir),
                ("psa", psa_dir),
                ("device-security", overlay_dir),
            )
        ]
        return build_report(sources, overlay, as_of, cfg, files)
    except (AdapterError, ReconcileError) as exc:
        raise ReportError(str(exc)) from exc


# -- Markdown ------------------------------------------------------------------------------------------------------
def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return ["None.", ""]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return [*lines, ""]


def _cell(value: Any) -> str:
    return str(value if value not in (None, "") else "-").replace("|", "/")


def render_markdown(body: dict[str, Any], json_sha256: str) -> str:
    """The same report as readable Markdown, pinned to the JSON file's hash."""
    counts = body["counts"]
    comp, enc, laps, prov = counts["compliance"], counts["encryption"], counts["laps"], body["provisioning"]
    out = [
        f"# Device reports: {body['client']}, as of {body['as_of']}",
        "",
        f"> {body['note']}",
        "",
        f"Report SHA-256 (JSON): {json_sha256}",
        "",
        f"Data class: {body['data_class']}. Devices: {counts['devices']} (RMM {counts['reconcile']['records']['rmm']}, "
        f"Intune {counts['reconcile']['records']['intune']}, PSA {counts['reconcile']['records']['psa']}; "
        f"reconciles: {counts['reconcile']['reconciles']}).",
        "",
        "## Compliance",
        "",
        "Compliant {compliant}, non-compliant {non-compliant}, stale {stale}, not in Intune {not-in-intune}.".format(
            **comp
        ),
        "",
        *_table(
            ["Device", "User", "Status", "Reasons"],
            [
                [
                    _cell(d["name"]),
                    _cell(d["user"]),
                    d["compliance"]["status"],
                    _cell("; ".join(d["compliance"]["reasons"])),
                ]
                for d in body["devices"]
                if d["compliance"]["status"] != "compliant"
            ],
        ),
        "## Encryption",
        "",
        "Encrypted {encrypted}, not encrypted {not-encrypted}, unknown {unknown} (status only).".format(**enc),
        "",
        *_table(
            ["Device", "Encryption"],
            [[_cell(d["name"]), d["encryption"]] for d in body["devices"] if d["encryption"] != "encrypted"],
        ),
        "## LAPS coverage",
        "",
        f"Covered {laps['covered']} of {laps['applicable']} Windows devices in Intune; "
        f"stale backup {laps['stale-backup']}, "
        f"no backup {laps['not-backed-up']}, not applicable {laps['not-applicable']}, unknown {laps['unknown']} "
        "(status only: no password is read).",
        "",
        *_table(
            ["Device", "LAPS", "Last backup"],
            [
                [_cell(d["name"]), d["laps"]["status"], _cell(d["laps"]["last_backup"])]
                for d in body["devices"]
                if d["laps"]["status"] not in ("covered", "not-applicable")
            ],
        ),
        "## Provisioning readiness",
        "",
        "Incoming hires {hires}: ready {ready}, not ready {not-ready}. Autopilot devices {autopilot_devices}, "
        "not assigned to a hire {autopilot_unassigned}.".format(**prov["counts"]),
        "",
        *_table(
            ["Hire", "Name", "Starts", "Serial", "Readiness", "Missing"],
            [
                [
                    _cell(h["hire_id"]),
                    _cell(h["display_name"]),
                    f"{h['start_date']} ({h['days_until_start']} d)" + (" URGENT" if h["urgent"] else ""),
                    _cell(h["assigned_serial"]),
                    h["readiness"],
                    _cell("; ".join(h["reasons"])),
                ]
                for h in prov["hires"]
            ],
        ),
        "## Not verified",
        "",
        *[f"- {line}" for line in body["unverified"]],
        "",
    ]
    return "\n".join(out)


# -- write and verify ----------------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Written:
    json_path: Path
    md_path: Path
    sha256: str
    md_sha256: str


def _write(path: Path, data: bytes) -> str:
    digest = sha256_hex(data)
    path.write_bytes(data)
    # sha256sum format, so `sha256sum -c` (or Get-FileHash) re-checks it without this code.
    _sidecar(path).write_text(f"{digest}  {path.name}\n", encoding="ascii", newline="\n")
    return digest


def write_report(body: dict[str, Any], out_dir: Path) -> Written:
    """Write ``<out_dir>/<client>/<date>.json`` and ``.md`` with a sidecar each. Refuses secret-shaped content."""
    client = str(body.get("client"))
    if not CLIENT_ID.fullmatch(client):
        raise ReportError(f"{client!r} is not a client id")
    stem = _iso(utc(str(body["as_of"])))[:10]
    data = canonical_bytes(body)
    digest = sha256_hex(data)
    markdown = render_markdown(body, digest)
    leaks = find_secrets(data.decode("ascii")) + find_secrets(markdown)
    if leaks:
        raise ReportError(f"secret-shaped content in the report ({', '.join(sorted(set(leaks)))}); nothing is written")
    folder = Path(out_dir) / client
    folder.mkdir(parents=True, exist_ok=True)
    json_path, md_path = folder / f"{stem}.json", folder / f"{stem}.md"
    _write(json_path, data)
    md_digest = _write(md_path, markdown.encode("utf-8"))
    return Written(json_path, md_path, digest, md_digest)


def _check(path: Path) -> bytes:
    try:
        data = path.read_bytes()
        expected = _sidecar(path).read_text(encoding="ascii").split()[0]
    except (OSError, IndexError, UnicodeDecodeError) as exc:
        raise ReportError(f"{path.name}: file or sidecar unreadable ({type(exc).__name__})") from None
    if sha256_hex(data) != expected:
        raise ReportError(f"{path.name}: hash does not match its sidecar")
    return data


def verify(json_path: Path) -> str:
    """Re-check the JSON and its Markdown twin: each against its sidecar, and the Markdown against the JSON."""
    json_path = Path(json_path)
    data = _check(json_path)
    md_path = json_path.with_suffix(".md")
    md_data = _check(md_path)
    try:
        body = json.loads(data)
    except ValueError:
        raise ReportError(f"{json_path.name}: not valid JSON") from None
    if render_markdown(body, sha256_hex(data)).encode("utf-8") != md_data:
        raise ReportError(f"{md_path.name}: content does not match the report {json_path.name}")
    return f"ok: {json_path.name} {sha256_hex(data)}; {md_path.name} {sha256_hex(md_data)}"
