"""Discovery pack for a new MSP client (B-77, B77-1; specs/B-77.md; W-PRJ-01; C-20, C-27, C-45).

For one client this runs three read-only steps and lists every gap it finds:

1. ``baseline``: the Slice B TenantBaseline module (``Invoke-TenantBaseline``) in a child ``pwsh``. The command text
   is fixed; the client id and the output folder reach it as environment values, so no input becomes code. Its
   ``findings.json`` is read with the B-38 reader, which refuses a file written for another tenant.
2. ``devices``: the B-61 device reconciliation over the client's RMM, Intune and PSA mocks, imported at run time.
   While B-61 is not on this branch the step is ``not-run`` and says so.
3. ``licences``: seats per SKU and licence gaps from the client's own licence and directory fixtures.

A step that cannot run is listed as ``not-run`` or ``failed`` with the reason and becomes a High gap itself: missing
data is a gap, never an all clear. Error text never copies a child process's output, which can name other clients
(ISO-6). Nothing here imports the lever runner, the approval queue or an audit writer; the only files written are
the pack and the baseline's own report, both under the caller's output folder.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import subprocess
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.audit.router import valid_client_id
from core.guard.classify import classify
from core.levers.tenant import DEFAULT_TENANT_DIR
from workflows.baseline_proposals import BaselineProposalsError, read_findings

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.json")
BASELINE_DIR = ROOT / "levers" / "powershell" / "TenantBaseline"
BASELINE_MODULE = BASELINE_DIR / "TenantBaseline.psd1"
BASELINE_CONFIG_PATH = BASELINE_DIR / "TenantBaseline.config.json"
PACK_FORMAT = "client-discovery/1"
STEPS = ("baseline", "devices", "licences")
NOT_ON_BRANCH = "device reconciliation (B-61, workflows/device_reconcile) is not on this branch; nothing was compared"
NO_CHILD_TEXT = "its error output is not copied here because it can name other clients (ISO-6)"

Severity = Literal["High", "Medium", "Low"]
SEVERITIES: tuple[Severity, ...] = ("High", "Medium", "Low")
Status = Literal["ran", "not-run", "failed"]

# What the child pwsh may inherit: enough to start on Windows or Linux, nothing that holds a secret.
_ENV_ALLOWED = (
    "PATH",
    "SystemRoot",
    "SystemDrive",
    "windir",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "LOCALAPPDATA",
    "APPDATA",
    "ProgramFiles",
    "ProgramData",
    "LANG",
    "LC_ALL",
)
_ENV_FIXED = {"POWERSHELL_TELEMETRY_OPTOUT": "1", "POWERSHELL_UPDATECHECK": "Off", "DOTNET_NOLOGO": "1"}
_BASELINE_COMMAND = (
    "$ErrorActionPreference = 'Stop'; Import-Module -Force -Name $env:B77_MODULE; "
    "Invoke-TenantBaseline -Tenant $env:B77_TENANT -OutDir $env:B77_OUT | Out-Null"
)
_DEVICE_SEVERITY: dict[str, Severity] = {"only-in-one-system": "Medium", "duplicate": "Medium", "stale": "Low"}
_DEVICE_CODE = {"only-in-one-system": "ONLYONE", "duplicate": "DUP", "stale": "STALE"}


class DiscoveryError(ValueError):
    """The input is bad (client id, config, as-of date); nothing ran."""


class LifecycleConfig(BaseModel):
    """The workflow's configuration; unknown keys fail the load (STD-CF-3)."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    version: Literal[1]
    note: str = Field(default="", alias="_note")
    baseline_timeout_s: int = Field(ge=5, le=900)
    migrations_dir: str = Field(min_length=1, max_length=200)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> LifecycleConfig:
    try:
        return LifecycleConfig.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        raise DiscoveryError(f"cannot load client lifecycle config from {path}: {exc}") from exc


def check_client(client: str) -> str:
    if not valid_client_id(client):
        raise DiscoveryError(
            "the client id must be lower-case letters, digits and hyphens (for example contoso-dental)"
        )
    return client


def default_as_of() -> str:
    """The baseline config's pinned ``asOf``: discovery never reads the clock (STD-TS-4)."""
    try:
        value = json.loads(BASELINE_CONFIG_PATH.read_text(encoding="utf-8"))["asOf"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DiscoveryError(f"cannot read asOf from {BASELINE_CONFIG_PATH}: {exc}") from exc
    return parse_date(str(value)).isoformat()


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DiscoveryError(f"{value!r} is not a date (YYYY-MM-DD)") from exc


@dataclass(frozen=True, slots=True)
class Gap:
    id: str
    source: str
    severity: Severity
    title: str
    subject: str
    evidence: str
    next_step: str


@dataclass(frozen=True, slots=True)
class Step:
    name: str
    status: Status
    reason: str
    counts: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StepOutcome:
    step: Step
    gaps: tuple[Gap, ...] = ()


@dataclass(frozen=True, slots=True)
class Context:
    """What every step gets: one client, one date, one output folder."""

    client: str
    as_of: date
    out_dir: Path
    tenant_dir: Path
    config: LifecycleConfig
    pwsh: str | None = None


StepRunner = Callable[[Context], StepOutcome]


def _not_run(name: str, reason: str, status: Status = "not-run") -> StepOutcome:
    gap = Gap(
        id=f"DISC-{name.upper()}",
        source="discovery",
        severity="High",
        title=f"{name} step {status}: this part of the client is not yet known",
        subject=name,
        evidence=reason,
        next_step="collect this data before the client's baseline is signed off",
    )
    return StepOutcome(Step(name, status, reason), (gap,))


# --- step 1: baseline --------------------------------------------------------------------------


def run_baseline(ctx: Context) -> StepOutcome:
    """The read-only TenantBaseline for this client; each finding is a gap (fix shown as a proposal only)."""
    pwsh = ctx.pwsh or shutil.which("pwsh")
    if pwsh is None:
        return _not_run("baseline", "pwsh (PowerShell 7.4 or newer) is not installed; the baseline did not run")
    out = ctx.out_dir / "baseline"
    out.mkdir(parents=True, exist_ok=True)
    env = {k: os.environ[k] for k in _ENV_ALLOWED if k in os.environ}
    env.update(_ENV_FIXED)
    env.update({"B77_MODULE": str(BASELINE_MODULE), "B77_TENANT": ctx.client, "B77_OUT": str(out)})
    argv = [pwsh, "-NoProfile", "-NonInteractive", "-Command", _BASELINE_COMMAND]
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv and command text; values arrive as environment values
            argv, capture_output=True, text=True, timeout=ctx.config.baseline_timeout_s, env=env, check=False
        )
    except subprocess.TimeoutExpired:
        return _not_run("baseline", f"the baseline did not finish in {ctx.config.baseline_timeout_s} s", "failed")
    except OSError as exc:
        return _not_run("baseline", f"pwsh could not start ({type(exc).__name__})", "failed")
    if done.returncode != 0:
        reason = f"the baseline exited with code {done.returncode}; {NO_CHILD_TEXT}"
        return _not_run("baseline", reason, "failed")
    try:
        baseline_as_of, findings = read_findings(out / "findings.json", ctx.client)
    except BaselineProposalsError:
        return _not_run("baseline", "the baseline output could not be read for this client", "failed")
    gaps = tuple(
        Gap(
            id=f.id,
            source="baseline",
            severity=f.severity,
            title=f.title,
            subject=f.subject,
            evidence=f.evidence,
            next_step=(
                f"proposal only: {f.fix_lever} as a dry-run for a lead to approve"
                if f.fix_lever
                else "a person decides; no lever"
            ),
        )
        for f in findings
    )
    counts = {"as_of": baseline_as_of, "findings": len(findings), **_by_severity(gaps)}
    return StepOutcome(
        Step("baseline", "ran", "read-only TenantBaseline over the client's Graph fixtures", counts), gaps
    )


# --- step 2: devices ---------------------------------------------------------------------------


def _b61() -> dict[str, Any] | None:
    """The B-61 pieces this step needs, or None while B-61 is not on this branch."""
    try:
        reconcile = importlib.import_module("workflows.device_reconcile.reconcile")
        rmm = importlib.import_module("adapters.rmm")
        intune = importlib.import_module("adapters.intune")
        psa = importlib.import_module("workflows.device_reconcile.psa_assets")
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.split(".")[0] in ("workflows", "adapters"):
            return None
        raise
    return {
        "reconcile": reconcile.reconcile,
        "load_config": reconcile.load_config,
        "utc": reconcile.utc,
        "errors": (reconcile.ReconcileError,),
        "rmm": rmm.RmmMock,
        "intune": intune.IntuneMock,
        "psa": psa.PsaAssetsMock,
    }


def run_devices(ctx: Context) -> StepOutcome:
    """B-61 device reconciliation for this client; each mismatch is a gap."""
    b61 = _b61()
    if b61 is None:
        return _not_run("devices", NOT_ON_BRANCH)
    try:
        rmm = b61["rmm"].for_fixture(ctx.client)
        intune = b61["intune"].for_fixture(ctx.client)
        psa = b61["psa"].for_fixture(ctx.client)
        as_of = str(rmm.as_of)  # B-61's own pinned time: stale ages are measured against the RMM snapshot
        rec = b61["reconcile"](rmm, intune, psa, b61["utc"](as_of), b61["load_config"]())
    except (*b61["errors"], OSError, ValueError, KeyError, TypeError) as exc:
        return _not_run("devices", f"no usable RMM, Intune or PSA asset data for this client ({type(exc).__name__})")
    numbers: Counter[str] = Counter()
    gaps: list[Gap] = []
    for f in rec.findings:
        numbers[f.type] += 1
        gaps.append(
            Gap(
                id=f"DEV-{_DEVICE_CODE.get(f.type, 'OTHER')}-{numbers[f.type]:02d}",
                source="devices",
                severity=_DEVICE_SEVERITY.get(f.type, "Medium"),
                title=f"device {f.type} ({f.system})",
                subject=str(f.device),
                evidence=str(f.detail),
                next_step="a technician checks the device in each system; nothing is changed by discovery",
            )
        )
    counts = {"as_of": as_of, **rec.counts(), **_by_severity(gaps)}
    return StepOutcome(Step("devices", "ran", "B-61 reconciliation of RMM, Intune and PSA assets", counts), tuple(gaps))


# --- step 3: licences --------------------------------------------------------------------------


def _client_file(path: Path, client: str, what: str) -> dict[str, Any] | None:
    """A fixture file of this client, None when absent. A file that names another client is refused (C-27)."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DiscoveryError(f"the {what} file for this client is unreadable ({type(exc).__name__})") from exc
    meta = data.get("_meta") if isinstance(data, dict) else None
    if not isinstance(meta, dict) or meta.get("client") != client:
        raise DiscoveryError(f"the {what} file does not belong to this client; nothing was read")
    checked: dict[str, Any] = data
    return checked


def _name(record: Mapping[str, Any]) -> str:
    """A record's lower-cased user name, "" when it has none (so None never becomes the text 'None')."""
    value = record.get("userPrincipalName")
    return value.strip().lower() if isinstance(value, str) else ""


def _window_end(value: Any) -> date | None:
    try:
        return parse_date(str(value))
    except DiscoveryError:
        return None


def _seat_count(units: Any) -> int | None:
    """The bought seat count, or None when it is missing or not a whole number >= 0 (never guessed as 0)."""
    value = units.get("enabled") if isinstance(units, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def licence_report(client: str, as_of: date, tenant_dir: Path = DEFAULT_TENANT_DIR) -> StepOutcome:
    """Seats per SKU and licence gaps for one client, from its own fixtures only."""
    try:
        licences = _client_file(Path(tenant_dir) / client / "licenses.json", client, "licence")
        directory = _client_file(Path(tenant_dir) / f"{client}.json", client, "directory")
    except DiscoveryError as exc:
        return _not_run("licences", str(exc), "failed")
    if licences is None:
        return _not_run("licences", "no licence data for this client (fixtures/tenant/<client>/licenses.json)")
    if directory is None:
        return _not_run("licences", "no directory data for this client (fixtures/tenant/<client>.json)")
    skus = {str(s.get("skuId")): s for s in licences.get("skus", []) if isinstance(s, dict)}
    assignments = [a for a in licences.get("assignments", []) if isinstance(a, dict)]
    entries = [u for u in directory.get("users", []) if isinstance(u, dict)]
    users = {_name(u): u for u in entries if _name(u)}
    found: list[tuple[str, Severity, str, str, str, str]] = []

    def gap(kind: str, severity: Severity, title: str, subject: str, evidence: str, next_step: str) -> None:
        found.append((kind, severity, title, subject, evidence, next_step))

    seats: list[dict[str, Any]] = []
    for sku_id, sku in skus.items():
        name = str(sku.get("skuPartNumber", sku_id))
        enabled = _seat_count(sku.get("prepaidUnits"))
        assigned = sum(1 for a in assignments if str(a.get("skuId")) == sku_id)
        if enabled is None:
            seats.append({"sku": name, "enabled": None, "assigned": assigned, "free": None})
            gap(
                "SEATS",
                "High",
                "seat count unknown: prepaidUnits.enabled is missing or not a whole number",
                name,
                f"assigned={assigned}; the bought count was not guessed",
                "the account manager reads the bought seats from the subscription",
            )
            continue
        seats.append({"sku": name, "enabled": enabled, "assigned": assigned, "free": enabled - assigned})
        if assigned > enabled:
            gap(
                "OVER",
                "High",
                "more licences assigned than bought",
                name,
                f"enabled={enabled}; assigned={assigned}",
                "the account manager checks the subscription before the next invoice",
            )
        elif assigned < enabled:
            gap(
                "UNUSED",
                "Low",
                "seats bought but not assigned",
                name,
                f"enabled={enabled}; assigned={assigned}",
                "the account manager asks the client whether the seats are still needed",
            )
    for n, u in enumerate(entries, start=1):
        if not _name(u):
            gap(
                "NOUPN",
                "Medium",
                "directory entry with no user name",
                f"directory entry #{n}",
                "userPrincipalName is missing",
                "a technician checks the entry in the admin portal",
            )
    for a in assignments:
        if not _name(a):
            gap(
                "NOUPN",
                "Medium",
                "licence assignment with no user name",
                f"SKU {a.get('skuPartNumber', a.get('skuId'))}",
                "userPrincipalName is missing",
                "a technician checks the assignment in the admin portal",
            )
            continue
        upn = str(a["userPrincipalName"])
        sku_id = str(a.get("skuId"))
        name = str(a.get("skuPartNumber", sku_id))
        if sku_id not in skus:
            gap(
                "UNKNOWNSKU",
                "Medium",
                "assignment to a SKU the tenant does not list",
                upn,
                f"sku={name}",
                "a technician checks the assignment in the admin portal",
            )
        user = users.get(_name(a))
        if user is None:
            ends = a.get("retentionEndsOn")
            if not ends:
                gap(
                    "ORPHAN",
                    "Medium",
                    "licence held by an account not in the directory",
                    upn,
                    f"sku={name}; no retention window recorded",
                    "a person confirms who this was before any change",
                )
            elif (window_end := _window_end(ends)) is None:
                gap(
                    "BADDATE",
                    "High",
                    "retention window date is not readable",
                    upn,
                    f"sku={name}; retentionEndsOn={str(ends)[:40]!r} is not YYYY-MM-DD",
                    "a person confirms the retention window before any change",
                )
            elif window_end < as_of:
                gap(
                    "ORPHAN",
                    "Medium",
                    "licence held after its retention window ended",
                    upn,
                    f"sku={name}; retentionEndsOn={ends}",
                    "a lead decides whether to reclaim it (license.remove)",
                )
            else:
                gap(
                    "ORPHAN",
                    "Low",
                    "licence kept inside a retention window",
                    upn,
                    f"sku={name}; retentionEndsOn={ends}",
                    "nothing until the window ends",
                )
        elif user.get("accountEnabled") is False:
            gap(
                "DISABLED",
                "Medium",
                "licence held by a disabled account",
                upn,
                f"sku={name}",
                "a lead decides whether the licence is still needed",
            )
    licensed = {_name(a) for a in assignments}
    for key, user in users.items():
        if not isinstance(user.get("accountEnabled"), bool):
            gap(
                "ACCOUNTSTATE",
                "Medium",
                "account state unknown: accountEnabled is missing or not true/false",
                str(user["userPrincipalName"]),
                "it was not assumed to be enabled",
                "a technician checks whether the account is enabled",
            )
        elif user["accountEnabled"] and key not in licensed:
            gap(
                "UNLICENSED",
                "Low",
                "enabled account with no licence",
                str(user["userPrincipalName"]),
                "no assignment in licenses.json",
                "a technician checks whether this account needs a licence",
            )
    numbers: Counter[str] = Counter()
    gaps: list[Gap] = []
    for kind, severity, title, subject, evidence, next_step in found:
        numbers[kind] += 1
        gaps.append(Gap(f"LIC-{kind}-{numbers[kind]:02d}", "licences", severity, title, subject, evidence, next_step))
    counts = {
        "as_of": as_of.isoformat(),
        "skus": len(skus),
        "assignments": len(assignments),
        "directory_users": len(users),
        "seats": seats,
        **_by_severity(gaps),
    }
    return StepOutcome(Step("licences", "ran", "licence report from the client's own fixtures", counts), tuple(gaps))


def run_licences(ctx: Context) -> StepOutcome:
    return licence_report(ctx.client, ctx.as_of, ctx.tenant_dir)


# --- the pack ----------------------------------------------------------------------------------


def _by_severity(gaps: tuple[Gap, ...] | list[Gap]) -> dict[str, int]:
    tally = Counter(g.severity for g in gaps)
    return {s: tally[s] for s in SEVERITIES}


def _canonical(body: Mapping[str, Any]) -> bytes:
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def body_sha256(pack: Mapping[str, Any]) -> str:
    """sha256 over the pack without its own ``sha256`` field."""
    return hashlib.sha256(_canonical({k: v for k, v in pack.items() if k != "sha256"})).hexdigest()


@dataclass(frozen=True, slots=True)
class Pack:
    client: str
    as_of: str
    steps: tuple[Step, ...]
    gaps: tuple[Gap, ...]
    path: Path

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "format": PACK_FORMAT,
            "client": self.client,
            "as_of": self.as_of,
            "read_only": True,
            "label": "fixture-based: synthetic data; independently built prototype",
            "steps": [{**asdict(s), "counts": dict(s.counts)} for s in self.steps],
            "gaps": [asdict(g) for g in self.gaps],
            "gap_counts": _by_severity(self.gaps),
        }
        verdict = classify(_canonical(body).decode("utf-8"))
        body["data_class"] = verdict.data_class.label
        body["data_class_basis"] = verdict.basis
        body["sha256"] = body_sha256(body)
        return body


def discover(
    client: str,
    out_dir: Path,
    *,
    as_of: str | None = None,
    tenant_dir: Path = DEFAULT_TENANT_DIR,
    config: LifecycleConfig | None = None,
    pwsh: str | None = None,
    steps: Mapping[str, StepRunner] | None = None,
) -> Pack:
    """Run every discovery step for one client (read-only) and write ``<out_dir>/<client>/discovery.json``."""
    check_client(client)
    when = parse_date(as_of) if as_of else parse_date(default_as_of())
    runners: dict[str, StepRunner] = {"baseline": run_baseline, "devices": run_devices, "licences": run_licences}
    if steps:
        unknown = set(steps) - set(STEPS)
        if unknown:
            raise DiscoveryError(f"unknown discovery step(s): {sorted(unknown)}")
        runners.update(steps)
    target = Path(out_dir) / client
    ctx = Context(client, when, target, Path(tenant_dir), config or load_config(), pwsh)
    target.mkdir(parents=True, exist_ok=True)
    outcomes = [runners[name](ctx) for name in STEPS]
    pack = Pack(
        client=client,
        as_of=when.isoformat(),
        steps=tuple(o.step for o in outcomes),
        gaps=tuple(g for o in outcomes for g in o.gaps),
        path=target / "discovery.json",
    )
    pack.path.write_text(json.dumps(pack.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return pack


def summary(pack: Pack) -> dict[str, Any]:
    """What the CLI prints: each step, the gap counts and every gap's id, severity and title."""
    return {
        "client": pack.client,
        "as_of": pack.as_of,
        "read_only": True,
        "pack": str(pack.path),
        "steps": [{"name": s.name, "status": s.status, "reason": s.reason} for s in pack.steps],
        "gap_counts": _by_severity(pack.gaps),
        "gaps": [{"id": g.id, "severity": g.severity, "title": g.title, "subject": g.subject} for g in pack.gaps],
    }
