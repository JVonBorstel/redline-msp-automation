"""Monthly patch pack for one client (B-67, specs/B-67.md; W-PAT-01, -02, -03, -06, -07; C-21, C-05, C-37).

For one client this reads the cycle's released updates, the client's per-device update state and network firmware
versions (``fixtures/patches/``) and the client's own device list through the RMM adapter (B-61), and builds one pack:

1. a review pack: every released update by ring with its known issues and a proposed action, for a person to approve;
2. compliance: each RMM device of the client in exactly one status, counts that reconcile to the fixtures;
3. failed-patch triage: failures grouped by error code with a suggested remediation lever (a name, never run here);
4. server windows: the client's declared window, per server, and a notice draft that nobody has sent;
5. a firmware version report: network devices are never upgraded by automation.

Read-only and proposal-only: nothing here approves, deploys, schedules, sends or upgrades, and the module imports no
process, network or lever-runner code. The date is the fixtures' ``as_of``, never the clock. Free text from the
fixtures (known-issue summaries) goes through the injection guard; error text is never copied. Patch records of a
device that is not in this client's RMM site are counted and dropped, never looked up elsewhere (C-27).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from adapters.base import AdapterError
from adapters.rmm import DEFAULT_RMM_DIR, RmmMock
from core.guard import detect_injection
from core.guard.classify import DataClass
from core.levers.registry import Registry, RegistryError
from core.paths import REPO_ROOT

DEFAULT_FIXTURES_DIR = REPO_ROOT / "fixtures" / "patches"
DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.json")
DEFAULT_OUT_DIR = REPO_ROOT / "build" / "patching"
RELEASES_FILE = "releases.json"
KIND = "patch-pack"
VERSION = 1
CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ().-]{0,80}$")
ERROR_CODE = re.compile(r"^0x[0-9A-Fa-f]{8}$")
VERSION_TEXT = re.compile(r"^\d+(\.\d+){0,3}$")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
DECISION_OPTIONS = ["approve", "hold", "defer"]
WITHHELD = "(text withheld: injection signs)"
NAME_WITHHELD = "(name withheld)"
NOT_REGISTERED = "proposed (not in registry)"
NOTE = (
    "Synthetic data (fixture-based). A review pack and drafts only: nothing was approved, deployed, scheduled, "
    "sent or upgraded. A person decides."
)
UNVERIFIED = [
    "UNVERIFIED: how a real RMM or Intune reports patch state, update classification, rings and install errors; the "
    "fixtures use a neutral shape of this repo (fixtures/patches/SOURCES.md).",
    "UNVERIFIED: the meaning of each error code in the table (workflows/patching/config.json) is written from general "
    "knowledge, no vendor page was opened.",
    "UNVERIFIED: firmware versions, advisory fix versions and latest versions are fixture facts, not read from a "
    "vendor or a device.",
    "Suggested levers are names only. None can run here, and none is in the registry unless its lever_status says "
    "registered.",
    "Server windows use a fixed UTC offset from the fixture: no daylight saving, holiday or business-hours check.",
]


class PatchingError(ValueError):
    """Bad input or missing data; nothing was written."""


class VerifyError(ValueError):
    """A file does not match its sidecar hash."""


@dataclass(frozen=True)
class Written:
    json_path: Path
    md_path: Path
    json_sha256: str
    md_sha256: str


# -- fixture and config models (unknown keys fail the load, STD-CF-3) -------------------------------------------------
class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


Name = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._ (),-]{0,62}$")]
Kb = Annotated[str, StringConstraints(pattern=r"^KB-[A-Z0-9-]{1,30}$")]
Hostname = Annotated[str, StringConstraints(pattern=SAFE_NAME.pattern)]
Hhmm = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
Offset = Annotated[str, StringConstraints(pattern=r"^[+-]([01]\d|2[0-3]):[0-5]\d$")]


class ProductMap(_Model):
    os_contains: str
    product: str


class ErrorCodeInfo(_Model):
    meaning: str
    lever: str


class Config(_Model):
    note: str = Field(default="", alias="_note")
    version: Literal[1]
    grace_days: int = Field(ge=0, le=90)
    stale_days: int = Field(ge=1, le=365)
    notice_lead_days: int = Field(ge=0, le=60)
    required_classifications: tuple[str, ...]
    products: tuple[ProductMap, ...]
    error_codes: dict[str, ErrorCodeInfo]


class KnownIssue(_Model):
    id: str
    summary: str
    status: Literal["open", "fixed"]
    fixed_in: Kb | None


class Update(_Model):
    kb: Kb
    title: str
    classification: str
    severity: str
    product: str
    released: date
    known_issues: tuple[KnownIssue, ...]


class Ring(_Model):
    id: str
    order: int
    products: tuple[str, ...]
    soak_days: int = Field(ge=0)


class Releases(_Model):
    note: str = Field(alias="_note")
    as_of: str
    cycle: str
    patch_tuesday: date
    rings: tuple[Ring, ...]
    updates: tuple[Update, ...]


class UpdateState(_Model):
    kb: Kb
    state: Literal["installed", "pending", "failed"]
    error_code: str | None = None
    error_text: str | None = None
    last_attempt: str | None = None


class DeviceRecord(_Model):
    uid: str
    ring: str
    reboot_required: bool = False
    post_checks: tuple[Name, ...] = ()
    updates: tuple[UpdateState, ...]


class ServerWindow(_Model):
    weekday: Literal["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    start_local: Hhmm
    duration_hours: int = Field(ge=1, le=24)
    utc_offset: Offset
    label: Name


class NetworkDevice(_Model):
    hostname: Hostname
    kind: Literal["firewall", "switch", "access-point"]
    vendor: Name
    model: Name
    current_version: str
    latest_known_version: str
    advisory_id: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9-]{1,40}$")] | None
    advisory_fixed_version: str | None


class ClientPatches(_Model):
    note: str = Field(alias="_note")
    client: str
    as_of: str
    cycle: str
    server_window: ServerWindow
    devices: tuple[DeviceRecord, ...]
    network_devices: tuple[NetworkDevice, ...]


# -- hashing -------------------------------------------------------------------------------------------------------
def canonical_bytes(body: dict[str, Any]) -> bytes:
    """The exact bytes the JSON is written as: sorted keys, two-space indent, ASCII, one trailing newline."""
    return (json.dumps(body, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sidecar_for(path: Path) -> Path:
    return path.with_name(path.name + ".sha256")


def _source(path: Path) -> dict[str, str]:
    path = Path(path).resolve()
    try:
        shown = path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        shown = path.name
    return {"path": shown, "sha256": sha256_hex(path.read_bytes())}


# -- loading -------------------------------------------------------------------------------------------------------
def _problem(path: Path, exc: ValidationError) -> PatchingError:
    # Location and message only: the error's `input` could echo untrusted text.
    first = exc.errors()[0]
    where = ".".join(str(p) for p in first["loc"])
    return PatchingError(f"{path.name}: {where}: {first['msg']}")


def _load[M: BaseModel](path: Path, model: type[M]) -> M:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PatchingError(f"cannot read {Path(path).name}: {type(exc).__name__}") from None
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise _problem(Path(path), exc) from None


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    config = _load(path, Config)
    bad = [c for c in config.error_codes if not ERROR_CODE.fullmatch(c) or c != "0x" + c[2:].upper()]
    if bad:
        raise PatchingError(f"{Path(path).name}: error code keys must be 0x plus eight upper-case hex digits: {bad}")
    return config


def list_clients(fixtures_dir: Path = DEFAULT_FIXTURES_DIR) -> list[str]:
    """Clients that have patch fixtures, in name order."""
    return sorted(p.stem for p in Path(fixtures_dir).glob("*.json") if p.name != RELEASES_FILE)


def _client_id(client: str) -> str:
    if not isinstance(client, str) or not CLIENT_ID.fullmatch(client):
        raise PatchingError(f"{client!r} is not a client id")
    return client


def _instant(text: str) -> datetime:
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        raise PatchingError(f"not an ISO time: {text!r}") from None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _safe_name(value: object) -> str:
    return value if isinstance(value, str) and SAFE_NAME.fullmatch(value) else NAME_WITHHELD


def _normal_code(code: str | None) -> str:
    if code is None or not ERROR_CODE.fullmatch(code):
        raise PatchingError("a failed update row needs an error_code like 0x80070005")
    return "0x" + code[2:].upper()


# -- review pack (B67-1) -------------------------------------------------------------------------------------------
class _Guard:
    """Passes fixture free text through the injection guard and counts what it withheld."""

    def __init__(self) -> None:
        self.withheld = 0

    def text(self, value: str) -> tuple[str, bool]:
        if detect_injection(value).flagged:
            self.withheld += 1
            return WITHHELD, True
        return value, False


def _review_pack(
    releases: Releases,
    config: Config,
    records: list[tuple[DeviceRecord, str | None]],
    guard: _Guard,
) -> dict[str, Any]:
    listed = {u.kb for u in releases.updates}
    rings = sorted(releases.rings, key=lambda r: r.order)
    required = set(config.required_classifications)
    rows: list[dict[str, Any]] = []
    for upd in sorted(releases.updates, key=lambda u: u.kb):
        issues: list[dict[str, Any]] = []
        open_issue = False
        for issue in upd.known_issues:
            summary, flagged = guard.text(issue.summary)
            resolved = issue.status == "fixed" and issue.fixed_in in listed and not flagged
            open_issue = open_issue or not resolved
            issues.append({"id": issue.id, "summary": summary, "status": issue.status, "fixed_in": issue.fixed_in})
        targets = [r for r in rings if upd.product in r.products]
        if upd.classification not in required:
            reason, first, later = "not a security or servicing-stack update; optional", "defer", "defer"
        elif open_issue:
            reason, first, later = (
                "a known issue is open or its fix is not in this release list; read it first",
                ("hold"),
                "hold",
            )
        else:
            reason = "required update with no open known issue"
            first, later = "approve-first-ring", "promote-after-soak"
        actions = [
            {"ring": r.id, "proposed_action": first if i == 0 else later, "soak_days": r.soak_days}
            for i, r in enumerate(targets)
        ]
        have = [rec for rec, product in records if product == upd.product]
        states = Counter(next((u.state for u in rec.updates if u.kb == upd.kb), "not-reported") for rec in have)
        rows.append(
            {
                "kb": upd.kb,
                "title": upd.title,
                "classification": upd.classification,
                "severity": upd.severity,
                "product": upd.product,
                "released": upd.released.isoformat(),
                "known_issues": issues,
                "rings": [r.id for r in targets],
                "ring_actions": actions,
                "reason": reason,
                "client_devices": {
                    "installed": states["installed"],
                    "pending": states["pending"],
                    "failed": states["failed"],
                    "not_reported": states["not-reported"],
                },
                "decision": None,
                "approver": None,
            }
        )
    return {
        "patch_tuesday": releases.patch_tuesday.isoformat(),
        "decision_options": DECISION_OPTIONS,
        "deployed": False,
        "updates": rows,
        "by_ring": {r.id: sorted(u.kb for u in releases.updates if u.product in r.products) for r in rings},
        "withheld_texts": guard.withheld,
    }


# -- compliance (B67-1) --------------------------------------------------------------------------------------------
def _product_for(os_name: object, config: Config) -> str | None:
    if not isinstance(os_name, str):
        return None
    return next((m.product for m in config.products if m.os_contains in os_name), None)


def _compliance(
    devices: list[dict[str, Any]],
    by_uid: dict[str, DeviceRecord],
    releases: Releases,
    config: Config,
    as_of: datetime,
    unmatched: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    today = as_of.date()
    required: dict[str, set[str]] = defaultdict(set)
    for upd in releases.updates:
        if upd.classification in config.required_classifications and (today - upd.released).days >= config.grace_days:
            required[upd.product].add(upd.kb)
    cutoff = as_of - timedelta(days=config.stale_days)
    rows: list[dict[str, Any]] = []
    for dev in devices:
        uid = str(dev.get("uid"))
        record = by_uid.get(uid)
        product = _product_for(dev.get("operatingSystem"), config)
        try:
            seen: datetime | None = _instant(str(dev.get("lastSeen")))
        except PatchingError:
            seen = None
        missing: list[str] = []
        if seen is None or seen < cutoff:
            status = "stale"
        elif record is None or product is None:
            status = "no-patch-data"
        else:
            installed = {u.kb for u in record.updates if u.state == "installed"}
            missing = sorted(required[product] - installed)
            status = "non-compliant" if missing else "compliant"
        rows.append(
            {
                "uid": uid,
                "hostname": _safe_name(dev.get("hostname")),
                "ring": record.ring if record else None,
                "product": product,
                "status": status,
                "missing": missing,
            }
        )
    rows.sort(key=lambda r: (r["hostname"], r["uid"]))
    counts = Counter(r["status"] for r in rows)
    evaluated = counts["compliant"] + counts["non-compliant"]
    block = {
        "grace_days": config.grace_days,
        "stale_days": config.stale_days,
        "required_updates": sorted(kb for kbs in required.values() for kb in kbs),
        "counts": {
            "rmm_devices": len(rows),
            "compliant": counts["compliant"],
            "non_compliant": counts["non-compliant"],
            "stale": counts["stale"],
            "no_patch_data": counts["no-patch-data"],
            "patch_records_unmatched": unmatched,
        },
        "evaluated": evaluated,
        "compliance_percent": round(100 * counts["compliant"] / evaluated, 1) if evaluated else None,
        "devices": rows,
    }
    return block, rows


# -- failed-patch triage (B67-2) -----------------------------------------------------------------------------------
@dataclass
class _Group:
    count: int = 0
    devices: set[str] = field(default_factory=set)
    kbs: set[str] = field(default_factory=set)


def _failed(
    rows: list[dict[str, Any]],
    by_uid: dict[str, DeviceRecord],
    config: Config,
    lever_names: Collection[str],
) -> dict[str, Any]:
    groups: dict[str, _Group] = {}
    left_out = 0
    for row in rows:
        record = by_uid.get(row["uid"])
        if record is None:
            continue
        for upd in record.updates:
            if upd.state != "failed":
                continue
            code = _normal_code(upd.error_code)
            if row["status"] not in ("compliant", "non-compliant"):
                left_out += 1
                continue
            group = groups.setdefault(code, _Group())
            group.count += 1
            group.devices.add(row["hostname"])
            group.kbs.add(upd.kb)
    out: list[dict[str, Any]] = []
    for code, group in groups.items():
        info = config.error_codes.get(code)
        lever = info.lever if info else None
        out.append(
            {
                "error_code": code,
                "count": group.count,
                "devices": sorted(group.devices),
                "kbs": sorted(group.kbs),
                "meaning": info.meaning if info else "Not in the error-code table: manual triage.",
                "suggested_lever": lever,
                "lever_status": "none" if lever is None else ("registered" if lever in lever_names else NOT_REGISTERED),
                "next_step": "a technician approves any retry per batch" if lever else "a technician looks at it",
                "deployed": False,
                "approval": None,
            }
        )
    out.sort(key=lambda g: (-int(g["count"]), str(g["error_code"])))
    return {
        "total_failed_rows": sum(int(g["count"]) for g in out),
        "left_out_stale_or_no_data_rows": left_out,
        "groups": out,
    }


# -- server windows (B67-2) ----------------------------------------------------------------------------------------
def _next_weekday(start: date, weekday: str) -> date:
    day = start
    while WEEKDAYS[day.weekday()] != weekday:
        day += timedelta(days=1)
    return day


def _server_windows(
    client_name: str,
    servers: list[dict[str, Any]],
    rows: dict[str, dict[str, Any]],
    by_uid: dict[str, DeviceRecord],
    window: ServerWindow,
    config: Config,
    as_of: datetime,
) -> dict[str, Any]:
    if not servers:
        return {"servers": [], "window": None, "scheduled": False, "notice_draft": None}
    day = _next_weekday(as_of.date() + timedelta(days=config.notice_lead_days), window.weekday)
    start_h, start_m = (int(x) for x in window.start_local.split(":"))
    end_total = start_h * 60 + start_m + window.duration_hours * 60
    end_local = f"{(end_total // 60) % 24:02d}:{end_total % 60:02d}"
    block = {
        "date": day.isoformat(),
        "weekday": window.weekday,
        "start_local": window.start_local,
        "end_local": end_local,
        "ends_next_day": end_total >= 24 * 60,
        "duration_hours": window.duration_hours,
        "utc_offset": window.utc_offset,
        "label": window.label,
    }
    entries: list[dict[str, Any]] = []
    for dev in sorted(servers, key=lambda d: (_safe_name(d.get("hostname")), str(d.get("uid")))):
        uid = str(dev.get("uid"))
        record = by_uid.get(uid)
        entries.append(
            {
                "hostname": _safe_name(dev.get("hostname")),
                "uid": uid,
                "status": rows[uid]["status"],
                "missing_updates": rows[uid]["missing"],
                "reboot_expected": record.reboot_required if record else None,
                "post_checks": list(record.post_checks) if record else [],
            }
        )
    lines = ["Hello,", "", "We plan to install security updates on these servers during a maintenance window:"]
    for e in entries:
        restart = {True: "restart expected", False: "no restart expected", None: "restart not known"}[
            e["reboot_expected"]
        ]
        lines.append(f"- {e['hostname']} ({restart})")
    end_note = " (the next day)" if block["ends_next_day"] else ""
    lines += [
        "",
        f"Window: {block['weekday']} {block['date']}, {block['start_local']} to {block['end_local']}{end_note}, "
        f"UTC{block['utc_offset']} ({block['label']}).",
        "These servers may be unavailable for a short time while the work is done.",
    ]
    checks = sorted({c for e in entries for c in e["post_checks"]})
    if checks:
        lines.append("Afterwards we will check that these services are running: " + ", ".join(checks) + ".")
    lines += ["Please tell us if this window does not suit you.", "", "Thank you."]
    notice = {
        "status": "draft - not sent",
        "sent": False,
        "requires": "lead approval, then a person sends it",
        "subject": f"Planned server maintenance on {block['date']} for {client_name}",
        "body": "\n".join(lines),
    }
    return {"servers": entries, "window": block, "scheduled": False, "notice_draft": notice}


# -- firmware (B67-3) ----------------------------------------------------------------------------------------------
def _version(text: str | None) -> tuple[int, ...] | None:
    return tuple(int(p) for p in text.split(".")) if text is not None and VERSION_TEXT.fullmatch(text) else None


def _firmware(devices: tuple[NetworkDevice, ...]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for dev in sorted(devices, key=lambda d: d.hostname):
        cur, latest = _version(dev.current_version), _version(dev.latest_known_version)
        fixed = _version(dev.advisory_fixed_version)
        if cur is None or latest is None or (dev.advisory_fixed_version is not None and fixed is None):
            status = "unknown"
        elif fixed is not None and cur < fixed:
            status = "advisory-open"
        elif cur < latest:
            status = "behind"
        else:
            status = "current"
        rows.append(
            {
                "hostname": dev.hostname,
                "kind": dev.kind,
                "vendor": dev.vendor,
                "model": dev.model,
                "installed": dev.current_version,
                "latest_known": dev.latest_known_version,
                "advisory_id": dev.advisory_id,
                "advisory_fixed": dev.advisory_fixed_version,
                "status": status,
                "next_step": None
                if status == "current"
                else "a person plans and performs the upgrade; automation never upgrades network devices",
            }
        )
    counts = Counter(r["status"] for r in rows)
    return {
        "automation": "none",
        "upgrades_by_automation": False,
        "counts": {s: counts[s] for s in ("advisory-open", "behind", "current", "unknown")} | {"total": len(rows)},
        "devices": rows,
    }


# -- the pack ------------------------------------------------------------------------------------------------------
def build_pack(
    client: str,
    *,
    fixtures_dir: Path = DEFAULT_FIXTURES_DIR,
    rmm_dir: Path = DEFAULT_RMM_DIR,
    config_path: Path = DEFAULT_CONFIG_PATH,
    lever_names: Collection[str] | None = None,
) -> dict[str, Any]:
    """The pack for one client as a dict. Reads fixtures and the client's RMM mock; writes nothing."""
    _client_id(client)
    client_file = Path(fixtures_dir) / f"{client}.json"
    if not client_file.is_file():
        raise PatchingError(f"no patch fixtures for client {client!r}")
    config = load_config(config_path)
    releases = _load(Path(fixtures_dir) / RELEASES_FILE, Releases)
    patches = _load(client_file, ClientPatches)
    if patches.client != client:
        raise PatchingError(f"{client_file.name} is for client {patches.client!r}, not {client!r}")
    if patches.as_of != releases.as_of or patches.cycle != releases.cycle:
        raise PatchingError(f"{client_file.name} and {RELEASES_FILE} disagree on as_of or cycle")
    as_of = _instant(releases.as_of)
    ring_ids = {r.id for r in releases.rings}
    uids = [r.uid for r in patches.devices]
    if len(set(uids)) != len(uids):
        raise PatchingError(f"{client_file.name}: a device has two patch records")
    if any(r.ring not in ring_ids for r in patches.devices):
        raise PatchingError(f"{client_file.name}: a device names a ring that releases.json does not define")
    if lever_names is None:
        try:
            lever_names = set(Registry.load().names())
        except RegistryError as exc:
            raise PatchingError(str(exc)) from None

    try:
        rmm = RmmMock.for_fixture(client, Path(rmm_dir))
    except AdapterError as exc:
        raise PatchingError(str(exc)) from None
    listed = rmm.list_devices()
    site = rmm.get_site()
    if not listed.ok or listed.data is None or not site.ok or site.data is None:
        raise PatchingError(f"RMM read failed: {listed.reason if not listed.ok else site.reason}")
    devices = listed.data
    rmm_uids = {str(d.get("uid")) for d in devices}
    by_uid = {r.uid: r for r in patches.devices if r.uid in rmm_uids}
    unmatched = sum(1 for r in patches.devices if r.uid not in rmm_uids)

    guard = _Guard()
    matched = [
        (by_uid[str(d.get("uid"))], _product_for(d.get("operatingSystem"), config))
        for d in devices
        if str(d.get("uid")) in by_uid
    ]
    review = _review_pack(releases, config, matched, guard)
    compliance, rows = _compliance(devices, by_uid, releases, config, as_of, unmatched)
    row_by_uid = {r["uid"]: r for r in rows}
    servers = [
        d for d in devices if isinstance(d.get("deviceType"), dict) and d["deviceType"].get("category") == "Server"
    ]
    site_name = str(site.data.get("name", ""))
    client_name = re.sub(r" \(synthetic\)$", "", site_name) if NAME_RE.fullmatch(site_name) else client
    return {
        "kind": KIND,
        "version": VERSION,
        "client": client,
        "cycle": releases.cycle,
        "as_of": releases.as_of,
        "data_class": DataClass.DC2.label,
        "read_only": True,
        "proposal_only": True,
        "note": NOTE,
        "sources": [
            _source(Path(fixtures_dir) / RELEASES_FILE),
            _source(client_file),
            _source(Path(rmm_dir) / f"{client}.json"),
            _source(config_path),
        ],
        "unverified": list(UNVERIFIED),
        "review_pack": review,
        "compliance": compliance,
        "failed_patches": _failed(rows, by_uid, config, lever_names),
        "server_windows": _server_windows(
            client_name, servers, row_by_uid, by_uid, patches.server_window, config, as_of
        ),
        "firmware": _firmware(patches.network_devices),
    }


# -- Markdown ------------------------------------------------------------------------------------------------------
def _cell(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "/").replace("\r", " ").replace("\n", " ")


def _table(header: list[str], body: list[list[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in body]
    return lines


def render_markdown(pack: dict[str, Any], json_sha256: str) -> str:
    """The pack as Markdown for a person to read. It ends with the SHA-256 of the JSON it was rendered from."""
    review, comp = pack["review_pack"], pack["compliance"]
    failed, srv, fw = pack["failed_patches"], pack["server_windows"], pack["firmware"]
    c = comp["counts"]
    out = [
        f"# Patch pack: {pack['client']}, cycle {pack['cycle']}",
        "",
        f"As of {pack['as_of']}. Data class {pack['data_class']}. {pack['note']}",
        "",
        "## 1. Monthly review pack (for a person to approve)",
        "",
        f"Patch Tuesday {review['patch_tuesday']}. Decision options: {', '.join(review['decision_options'])}. "
        "Nothing is deployed; promotion to a later ring is an engineer's decision.",
        "",
    ]
    for ring, kbs in review["by_ring"].items():
        out += [f"### Ring: {ring}", ""]
        rows = [u for u in review["updates"] if u["kb"] in kbs]
        out += _table(
            [
                "Update",
                "Title",
                "Class",
                "Released",
                "Proposed",
                "Known issues",
                "Installed/pending/failed/not reported",
            ],
            [
                [
                    u["kb"],
                    u["title"],
                    u["classification"],
                    u["released"],
                    next(a["proposed_action"] for a in u["ring_actions"] if a["ring"] == ring),
                    "; ".join(f"{k['id']} ({k['status']}): {k['summary']}" for k in u["known_issues"]) or "none",
                    "/".join(str(u["client_devices"][k]) for k in ("installed", "pending", "failed", "not_reported")),
                ]
                for u in rows
            ],
        )
        out.append("")
    out += [
        "## 2. Compliance",
        "",
        f"{c['compliant']} of {comp['evaluated']} evaluated devices are compliant "
        f"({comp['compliance_percent']} percent). RMM devices: {c['rmm_devices']} = {c['compliant']} compliant + "
        f"{c['non_compliant']} non-compliant + {c['stale']} stale + {c['no_patch_data']} without patch data. "
        f"Patch records dropped because the device is not in this client's RMM site: {c['patch_records_unmatched']}.",
        "",
    ]
    out += _table(
        ["Device", "Ring", "Status", "Missing"],
        [[d["hostname"], d["ring"], d["status"], ", ".join(d["missing"])] for d in comp["devices"]],
    )
    out += ["", "## 3. Failed patches by error code", ""]
    if failed["groups"]:
        out += _table(
            ["Error code", "Rows", "Devices", "Updates", "Suggested lever", "Lever status", "Meaning"],
            [
                [
                    g["error_code"],
                    g["count"],
                    ", ".join(g["devices"]),
                    ", ".join(g["kbs"]),
                    g["suggested_lever"] or "none",
                    g["lever_status"],
                    g["meaning"],
                ]
                for g in failed["groups"]
            ],
        )
    else:
        out.append("No failed updates on evaluated devices.")
    out += ["", f"Failed rows left out (stale or no patch data): {failed['left_out_stale_or_no_data_rows']}.", ""]
    out += ["## 4. Server windows and client notice (draft, not sent)", ""]
    if srv["window"] is None:
        out.append("This client has no server in its RMM site: no window, no notice.")
    else:
        w = srv["window"]
        out += [
            f"Window: {w['weekday']} {w['date']}, {w['start_local']} to {w['end_local']}, UTC{w['utc_offset']} "
            f"({w['label']}). Not scheduled.",
            "",
        ]
        out += _table(
            ["Server", "Status", "Missing updates", "Restart expected", "Post-checks (read-only)"],
            [
                [
                    s["hostname"],
                    s["status"],
                    ", ".join(s["missing_updates"]),
                    s["reboot_expected"],
                    ", ".join(s["post_checks"]),
                ]
                for s in srv["servers"]
            ],
        )
        n = srv["notice_draft"]
        out += ["", f"Notice ({n['status']}; {n['requires']}):", "", f"Subject: {n['subject']}", ""]
        out += [f"> {line}" if line else ">" for line in n["body"].splitlines()]
    out += [
        "",
        "## 5. Network firmware (version report only)",
        "",
        "Automation: none. Network devices are never upgraded by automation.",
        "",
    ]
    out += _table(
        ["Device", "Kind", "Model", "Installed", "Latest known", "Advisory fix", "Status"],
        [
            [
                d["hostname"],
                d["kind"],
                d["model"],
                d["installed"],
                d["latest_known"],
                d["advisory_fixed"] or "",
                d["status"],
            ]
            for d in fw["devices"]
        ],
    )
    out += ["", "## Not verified", ""] + [f"- {item}" for item in pack["unverified"]]
    out += ["", f"Source JSON SHA-256: {json_sha256}", ""]
    return "\n".join(out)


# -- write and verify ----------------------------------------------------------------------------------------------
def _write(path: Path, data: bytes) -> str:
    digest = sha256_hex(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    # sha256sum format, so `sha256sum -c` (or Get-FileHash) re-checks it without this code.
    sidecar_for(path).write_text(f"{digest}  {path.name}\n", encoding="ascii", newline="\n")
    return digest


def write_pack(client: str, out_dir: Path = DEFAULT_OUT_DIR, **kwargs: Any) -> Written:
    """Build the pack and write ``<out>/<cycle>/<client>.json`` and ``.md`` with a ``.sha256`` sidecar each."""
    pack = build_pack(client, **kwargs)
    folder = Path(out_dir) / str(pack["cycle"])
    json_path, md_path = folder / f"{client}.json", folder / f"{client}.md"
    json_digest = _write(json_path, canonical_bytes(pack))
    md_digest = _write(md_path, render_markdown(pack, json_digest).encode("utf-8"))
    return Written(json_path, md_path, json_digest, md_digest)


def verify(path: Path) -> str:
    """Re-hash a written file against its sidecar; returns the SHA-256 or raises VerifyError."""
    path = Path(path)
    sidecar = sidecar_for(path)
    try:
        data = path.read_bytes()
        line = sidecar.read_text(encoding="ascii").strip()
    except OSError:
        raise VerifyError(f"{path.name} or its sidecar cannot be read: no sidecar means no proof") from None
    expected, _, name = line.partition("  ")
    if name != path.name or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise VerifyError(f"{sidecar.name} is not a sha256sum line for {path.name}")
    actual = sha256_hex(data)
    if actual != expected:
        raise VerifyError(f"{path.name} does not match its sidecar (file {actual}, sidecar {expected})")
    return actual
