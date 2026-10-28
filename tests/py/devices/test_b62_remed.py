"""B-62 device remediation script levers (specs/B-62.md).

Acceptance ids B62-1 to B62-4. Every test is offline and works in a private folder (tmp_path) with a copy of the
synthetic mock RMM device state; committed fixtures are never modified. Tests that start `pwsh` skip when PowerShell
7.4+ is not installed. Run: uv run --frozen pytest -p no:cacheprovider tests/py/devices/test_b62_remed.py
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import string
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from adapters.rmm.mock import RmmMock
from core.audit import AuditLog
from core.audit.router import AuditRouter
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, Approval, LeverRunner, MockTenant, Registry
from core.levers.bridge import PowerShellBridge
from core.levers.runner import RunnerPolicy

REPO = Path(__file__).resolve().parents[3]
MODULE = REPO / "levers" / "powershell" / "DeviceOps"
MOCK = MODULE / "mock"
TEMPLATES = REPO / "workflows" / "notify" / "templates"
CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
PWSH = shutil.which("pwsh")
needs_pwsh = pytest.mark.skipif(PWSH is None, reason="pwsh (PowerShell 7.4+) is not installed")
NO_CHANGE = "no change: already in the desired state"

C = "c0000000-0000-4000-8000-0000000d"
D1, D2, D3, D4, D6, D9 = (f"{C}{n}" for n in ("0001", "0002", "0003", "0004", "0006", "0009"))
DECOY = f"{C}0900"  # a device of the other client's RMM site that sits in the Contoso file on purpose
F1 = "f0000000-0000-4000-8000-0000000d0001"
UNKNOWN = f"{C}0777"

LEVERS = (
    "device.restart-spooler",
    "device.repair-mapped-drive",
    "device.reset-outlook-profile",
    "device.cleanup-temp",
    "device.restart-service",
    "device.reboot",
    "device.reboot-server",
)
FAULT_KEY = {
    "device.restart-spooler": "spooler-fails",
    "device.repair-mapped-drive": "drive-fails",
    "device.reset-outlook-profile": "outlook-fails",
    "device.cleanup-temp": "temp-fails",
    "device.restart-service": "service-fails",
    "device.reboot": "reboot-fails",
}

# Thu 2026-10-22 10:00 at a fixed UTC-08:00 client; the evening before; Sun 22:30 there.
THU_10 = datetime(2026, 10, 22, 18, 0, tzinfo=UTC)
WED_NIGHT = datetime(2026, 10, 22, 5, 0, tzinfo=UTC)
SUN_2230 = datetime(2026, 10, 26, 6, 30, tzinfo=UTC)
RECORD: dict[str, Any] = {
    "time_zone": "UTC-08:00",
    "business_hours": {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "08:00", "end": "17:00"},
    "maintenance_window": {"days": ["sun"], "start": "22:00", "end": "02:00"},
}


@dataclass
class Env:
    runner: LeverRunner
    tenant_dir: Path
    audit_dir: Path | None

    def path(self, client: str = CONTOSO, name: str = "devices.json") -> Path:
        return self.tenant_dir / client / name

    def raw(self, client: str = CONTOSO) -> bytes:
        return self.path(client).read_bytes()

    def device(self, uid: str, client: str = CONTOSO) -> dict[str, Any]:
        state = json.loads(self.raw(client))
        found: dict[str, Any] = next(d for d in state["devices"] if d["uid"] == uid)
        return found

    def dry(self, lever: str, params: dict[str, Any], client: str = CONTOSO, who: str = "triage-bot") -> Any:
        return self.runner.invoke(lever, params, who, client)

    def run(
        self, lever: str, params: dict[str, Any], client: str = CONTOSO, who: str = "tech-ana", **approval: Any
    ) -> Any:
        given = Approval(
            approver="lead-lee", lever=lever, client=client, params=dict(params), demo=self.audit_dir is not None
        )
        if approval:
            given = given.model_copy(update=approval)
        return self.runner.invoke(lever, params, who, client, mode="execute", approval=given)

    def chain(self, client: str = CONTOSO) -> list[dict[str, Any]]:
        assert self.audit_dir is not None
        path = self.audit_dir / f"{client}.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def make_env(
    tmp_path: Path,
    *,
    policy: bool = False,
    clock: Callable[[], datetime] | None = None,
    records: dict[str, dict[str, Any]] | None = None,
    modules_root: Path | None = None,
) -> Env:
    tenant_dir = tmp_path / "tenant"
    shutil.copytree(DEFAULT_TENANT_DIR, tenant_dir)
    for client in (CONTOSO, FABRIKAM):
        for name in ("devices.json", "remote-sessions.json"):
            if (MOCK / client / name).is_file():
                shutil.copyfile(MOCK / client / name, tenant_dir / client / name)
    if modules_root is None:
        bridge = PowerShellBridge(tenant_dir=tenant_dir)
    else:
        bridge = PowerShellBridge(tenant_dir=tenant_dir, modules_root=modules_root)
    if policy:
        the_policy = RunnerPolicy(demo=True, client_records={CONTOSO: RECORD} if records is None else records)
        runner = LeverRunner(
            Registry.load(),
            IdentityStore.load(),
            MockTenant(tenant_dir),
            AuditRouter(tmp_path / "audit"),
            bridge=bridge,
            policy=the_policy,
            clock=clock,
        )
        return Env(runner, tenant_dir, tmp_path / "audit")
    runner = LeverRunner(
        Registry.load(), IdentityStore.load(), MockTenant(tenant_dir), AuditLog(tmp_path / "audit.jsonl"), bridge=bridge
    )
    return Env(runner, tenant_dir, None)


def device_levers() -> list[str]:
    return sorted(n for n in Registry.load().names() if n.startswith("device."))


def catalog() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((MODULE / "vetted-scripts.json").read_text(encoding="utf-8"))
    return loaded


def script_digest(entry: dict[str, Any]) -> str:
    text = "\n".join([entry["script_id"], str(entry["version"]), *entry["steps"]])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dev(uid: str) -> dict[str, Any]:
    return {"device": uid}


P = "/devices/"
Diff = list[tuple[str, str, Any, Any]]


def _spooler_after(d: dict[str, Any]) -> None:
    assert d["services"]["Spooler"] == {"status": "Running", "health": "Ok"}
    assert d["printQueue"] == {"stuckJobs": 0}


def _drive_after(d: dict[str, Any]) -> None:
    assert d["mappedDrives"]["S"] == {"path": "\\\\DENTAL-SRV01\\Shared", "state": "Connected"}


def _outlook_after(d: dict[str, Any]) -> None:
    assert d["outlookProfiles"]["ana.lopez"] == {"state": "Reset", "backup": "Outlook-ana.lopez.bak-20261022"}


def _temp_after(d: dict[str, Any]) -> None:
    assert (d["tempBytes"], d["tempStaleBytes"], d["tempQuarantineBytes"]) == (700000000, 0, 4100000000)


def _service_after(d: dict[str, Any]) -> None:
    assert d["services"]["W32Time"] == {"status": "Running", "health": "Ok"}


def _reboot_after(d: dict[str, Any]) -> None:
    assert (d["lastBoot"], d["pendingReboot"]) == ("2026-10-22T12:00:00Z", False)


# lever -> (params, expected diff as (op, path, before, after), check of the device record after execute)
CASES: dict[str, tuple[dict[str, Any], Diff, Callable[[dict[str, Any]], None]]] = {
    "device.restart-spooler": (
        dev(D1),
        [
            ("replace", f"{P}{D1}/printQueue/stuckJobs", 3, 0),
            ("replace", f"{P}{D1}/services/Spooler/health", "Hung", "Ok"),
        ],
        _spooler_after,
    ),
    "device.repair-mapped-drive": (
        {**dev(D1), "drive": "S"},
        [("replace", f"{P}{D1}/mappedDrives/S/state", "Disconnected", "Connected")],
        _drive_after,
    ),
    "device.reset-outlook-profile": (
        {**dev(D1), "user": "ana.lopez"},
        [
            ("add", f"{P}{D1}/outlookProfiles/ana.lopez/backup", None, "Outlook-ana.lopez.bak-20261022"),
            ("replace", f"{P}{D1}/outlookProfiles/ana.lopez/state", "Corrupt", "Reset"),
        ],
        _outlook_after,
    ),
    "device.cleanup-temp": (
        dev(D1),
        [
            ("replace", f"{P}{D1}/tempBytes", 4800000000, 700000000),
            ("replace", f"{P}{D1}/tempQuarantineBytes", 0, 4100000000),
            ("replace", f"{P}{D1}/tempStaleBytes", 4100000000, 0),
        ],
        _temp_after,
    ),
    "device.restart-service": (
        {**dev(D1), "service": "W32Time"},
        [("replace", f"{P}{D1}/services/W32Time/health", "Hung", "Ok")],
        _service_after,
    ),
    "device.reboot": (
        dev(D1),
        [
            ("replace", f"{P}{D1}/lastBoot", "2026-10-12T07:30:00Z", "2026-10-22T12:00:00Z"),
            ("replace", f"{P}{D1}/pendingReboot", True, False),
        ],
        _reboot_after,
    ),
    "device.reboot-server": (
        dev(D3),
        [
            ("replace", f"{P}{D3}/lastBoot", "2026-10-04T02:00:00Z", "2026-10-22T12:00:00Z"),
            ("replace", f"{P}{D3}/pendingReboot", True, False),
        ],
        _reboot_after,
    ),
}


def as_tuples(diff: Any) -> Diff:
    return [(c.op, c.path, c.before, c.after) for c in diff]


# -- B62-1: vetted scripts named in the registry, no free-form script parameter ---------------------------------


def test_b62_1_the_seven_levers_are_registered_as_powershell_writes_with_lead_approval() -> None:
    registry = Registry.load()
    assert set(LEVERS) <= set(device_levers())  # other items (B-63, B-65) also register device.* levers
    for name in LEVERS:
        spec = registry.get(name)
        assert spec is not None
        assert registry.runtime(name) == "powershell"
        assert (spec.lever_class, spec.approval, spec.dry_run) == ("write", "lead", True)
        assert spec.risk_class in {"R1", "R2"}
        assert spec.dry_run_role == "agent" and spec.required_role == "technician"
        assert spec.impact is not None and spec.client_scope == "any"
        assert spec.caps is not None, name
        assert list(spec.idempotency_keys) == list(spec.params)
        assert spec.timeout_s <= 30


def test_b62_1_every_lever_names_an_exported_function_of_the_module() -> None:
    registry = Registry.load()
    manifest = (MODULE / "DeviceOps.psd1").read_text(encoding="utf-8")
    exported = set(
        re.findall(r"'([A-Z][A-Za-z]+-[A-Za-z]+)'", manifest.split("FunctionsToExport", 1)[1].split(")", 1)[0])
    )
    entries = [registry.powershell_entry(n) for n in LEVERS]
    assert None not in entries
    assert {e.function for e in entries if e is not None} == exported
    assert len(exported) == len(LEVERS)
    assert {e.module for e in entries if e is not None} == {"DeviceOps"}


def test_b62_1_no_lever_takes_a_script_command_or_path_and_every_param_is_bounded() -> None:
    registry = Registry.load()
    forbidden = re.compile(r"script|command|cmd|code|shell|exec|args|arguments|path|file|url|uri|expression", re.I)
    for name in LEVERS:
        spec = registry.get(name)
        assert spec is not None
        assert "device" in spec.params
        for pname, p in spec.params.items():
            assert not forbidden.search(pname), (name, pname)
            assert p.type == "string" and p.required
            assert p.enum is not None or (p.pattern is not None and p.max_length is not None), (name, pname)


def test_b62_1_the_catalog_of_vetted_scripts_matches_the_registry_one_to_one_and_each_hash_verifies() -> None:
    data = catalog()
    assert data["version"] == 1
    scripts = data["scripts"]
    assert sorted(scripts) == sorted(LEVERS)
    ids = [s["script_id"] for s in scripts.values()]
    assert len(set(ids)) == len(ids)
    for lever, entry in scripts.items():
        assert entry["steps"] and all(isinstance(s, str) and s for s in entry["steps"]), lever
        assert entry["sha256"] == script_digest(entry), f"{lever}: pinned hash does not match its steps"
        assert entry["version"] >= 1


@needs_pwsh
@pytest.mark.parametrize("extra", ["script", "command", "args", "path"])
def test_b62_1_a_free_form_parameter_is_refused_before_anything_runs(tmp_path: Path, extra: str) -> None:
    env = make_env(tmp_path)
    before = env.raw()
    result = env.dry("device.restart-spooler", {**dev(D1), extra: "Get-Process"})
    assert result.status != "ok" and not result.diff
    assert env.raw() == before


@needs_pwsh
def test_b62_1_a_script_whose_steps_no_longer_match_its_pinned_hash_does_not_run(tmp_path: Path) -> None:
    modules = tmp_path / "modules"
    shutil.copytree(MODULE, modules / "DeviceOps", ignore=shutil.ignore_patterns("mock", "tests"))
    path = modules / "DeviceOps" / "vetted-scripts.json"
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["scripts"]["device.restart-spooler"]["steps"].append("Run anything else")
    path.write_text(json.dumps(tampered, indent=2), encoding="utf-8")
    env = make_env(tmp_path, modules_root=modules)
    before = env.raw()
    result = env.dry("device.restart-spooler", dev(D1))
    assert result.status == "denied" and "vetted" in result.reason and not result.diff
    assert env.run("device.restart-spooler", dev(D1)).status != "ok"
    assert env.raw() == before
    # the catalog is one file: a tampered entry stops the others too
    assert env.dry("device.restart-service", {**dev(D1), "service": "W32Time"}).status == "denied"


def _code(path: Path) -> str:
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")
    )


def test_b62_1_the_module_contains_no_network_shell_or_free_form_execution() -> None:
    code = _code(MODULE / "DeviceOps.psm1")
    for banned in (
        "Invoke-Expression",
        "iex ",
        "Invoke-Command",
        "Invoke-RestMethod",
        "Invoke-WebRequest",
        "Start-Process",
        "Net.Http",
        "WebClient",
        "Invoke-Item",
        "[scriptblock]::Create",
        "Add-Type",
    ):
        assert banned not in code, banned


# -- B62-2: dry-run says what would run and where; reboot windows are the runner's rule -------------------------


@needs_pwsh
@pytest.mark.parametrize("lever", LEVERS)
def test_b62_2_a_dry_run_returns_what_would_run_and_on_which_device(tmp_path: Path, lever: str) -> None:
    env = make_env(tmp_path)
    params = CASES[lever][0]
    before = env.raw()
    dry = env.dry(lever, params)
    assert dry.status == "ok", dry.reason
    assert not dry.applied and dry.diff
    assert env.raw() == before, "a dry-run must write nothing"
    entry = catalog()["scripts"][lever]
    data = dry.data
    assert data["lever"] == lever and data["mode"] == "planned"
    assert data["script"] == {"id": entry["script_id"], "version": entry["version"], "digest": entry["sha256"][:16]}
    assert data["would_run"] == entry["steps"]
    uid = params["device"]
    assert data["device"] == {
        "uid": uid,
        "hostname": {D1: "FRONTDESK-01", D3: "DENTAL-SRV01"}[uid],
        "class": "server" if uid == D3 else "workstation",
    }
    assert data["verification"]["status"] == "planned" and data["verification"]["checks"]


def test_b62_2_only_the_two_reboot_levers_carry_a_window_and_servers_use_maintenance() -> None:
    registry = Registry.load()
    windows = {}
    for name in LEVERS:
        spec = registry.get(name)
        assert spec is not None
        windows[name] = spec.window
    assert windows["device.reboot"] == "business-hours"
    assert windows["device.reboot-server"] == "maintenance"
    assert [n for n, w in windows.items() if w is None] == [n for n in LEVERS if "reboot" not in n]


def test_b62_2_the_module_holds_no_time_logic_of_its_own() -> None:
    code = _code(MODULE / "DeviceOps.psm1")
    for banned in (
        "Get-Date",
        "UtcNow",
        "::Now",
        "DayOfWeek",
        "Start-Sleep",
        "Get-TimeZone",
        "business",
        "maintenance",
    ):
        assert banned not in code, banned


@needs_pwsh
def test_b62_2_the_runner_refuses_a_reboot_outside_the_window_and_an_override_lets_it_through(tmp_path: Path) -> None:
    env = make_env(tmp_path, policy=True, clock=lambda: WED_NIGHT)
    params = CASES["device.reboot"][0]
    before = env.raw()
    refused = env.run("device.reboot", params)
    assert refused.status == "denied" and "outside the client's business hours" in refused.reason
    assert "named window override" in refused.reason
    assert env.chain()[-1]["result"]["kind"] == "window-denied"
    assert env.raw() == before
    overridden = env.run("device.reboot", params, window_override="user-asked-for-it")
    assert (overridden.status, overridden.applied) == ("ok", True), overridden.reason
    assert env.chain()[-1]["result"]["window_override"]["name"] == "user-asked-for-it"
    assert env.device(D1)["pendingReboot"] is False


@needs_pwsh
def test_b62_2_inside_the_window_a_workstation_reboots_and_a_server_waits_for_maintenance(tmp_path: Path) -> None:
    env = make_env(tmp_path, policy=True, clock=lambda: THU_10)
    assert env.run("device.reboot", CASES["device.reboot"][0]).applied
    server = env.run("device.reboot-server", CASES["device.reboot-server"][0])
    assert server.status == "denied" and "outside the client's maintenance window" in server.reason
    assert env.device(D3)["pendingReboot"] is True
    night = make_env(tmp_path / "sun", policy=True, clock=lambda: SUN_2230)
    done = night.run("device.reboot-server", CASES["device.reboot-server"][0])
    assert (done.status, done.applied) == ("ok", True), done.reason


@needs_pwsh
def test_b62_2_a_client_with_no_window_is_refused_not_defaulted(tmp_path: Path) -> None:
    env = make_env(tmp_path, policy=True, clock=lambda: THU_10, records={})
    result = env.run("device.reboot", CASES["device.reboot"][0])
    assert result.status == "denied" and "not defaulted" in result.reason


@needs_pwsh
def test_b62_2_a_workstation_lever_refuses_a_server_and_the_server_lever_refuses_a_workstation(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    before = env.raw()
    wrong_way = env.dry("device.reboot", dev(D3))
    assert wrong_way.status == "denied" and "device.reboot-server" in wrong_way.reason
    other = env.dry("device.reboot-server", dev(D1))
    assert other.status == "denied" and "device.reboot" in other.reason
    assert env.raw() == before


@needs_pwsh
def test_b62_2_an_offline_device_is_refused_with_a_plain_reason(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    before = env.raw()
    result = env.dry("device.restart-spooler", dev(D4))
    assert result.status == "denied" and "offline" in result.reason and not result.diff
    assert env.raw() == before


# -- B62-3: golden tests on mock RMM output; caps; approval binding; verification; rollback -----------------------


@needs_pwsh
@pytest.mark.parametrize("lever", LEVERS)
def test_b62_3_golden_the_dry_run_diff_is_exactly_the_documented_change(tmp_path: Path, lever: str) -> None:
    env = make_env(tmp_path)
    dry = env.dry(lever, CASES[lever][0])
    assert dry.status == "ok", dry.reason
    assert as_tuples(dry.diff) == CASES[lever][1]


@needs_pwsh
@pytest.mark.parametrize("lever", LEVERS)
def test_b62_3_golden_execute_applies_the_same_diff_once_and_converges(tmp_path: Path, lever: str) -> None:
    if lever == "device.reboot":  # the runner's window rule needs the client record and a clock inside the window
        env = make_env(tmp_path, policy=True, clock=lambda: THU_10)
    elif lever == "device.reboot-server":
        env = make_env(tmp_path, policy=True, clock=lambda: SUN_2230)
    else:
        env = make_env(tmp_path)
    params, diff, check_after = CASES[lever]
    uid = params["device"]
    others = {u for u in (D1, D2, D3, D6, D9) if u != uid}
    others_before = {u: env.device(u) for u in others}
    dry = env.dry(lever, params)
    done = env.run(lever, params)
    assert (done.status, done.applied) == ("ok", True), done.reason
    assert as_tuples(done.diff) == as_tuples(dry.diff) == diff, "dry-run diff must be identical to execute"
    check_after(env.device(uid))
    assert {u: env.device(u) for u in others} == others_before, "only the named device changes"
    again = env.run(lever, params)
    assert (again.status, again.reason, again.applied, again.diff) == ("ok", NO_CHANGE, False, ())


@needs_pwsh
def test_b62_3_a_healthy_device_is_a_no_change_and_the_file_is_not_rewritten(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    before = env.raw()
    for lever, params in (
        ("device.restart-spooler", dev(D2)),
        ("device.repair-mapped-drive", {**dev(D2), "drive": "S"}),
        ("device.cleanup-temp", dev(D2)),
        ("device.restart-service", {**dev(D1), "service": "Dnscache"}),
    ):
        result = env.run(lever, params)
        assert (result.status, result.reason, result.applied) == ("ok", NO_CHANGE, False), lever
    assert env.raw() == before


@needs_pwsh
def test_b62_3_a_stopped_service_is_started_and_an_absent_or_unlisted_one_is_refused(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    stopped = env.run("device.restart-service", {**dev(D2), "service": "BITS"})
    assert as_tuples(stopped.diff) == [("replace", f"{P}{D2}/services/BITS/status", "Stopped", "Running")]
    absent = env.dry("device.restart-service", {**dev(D2), "service": "wuauserv"})  # approved name, not on this device
    assert absent.status == "denied" and "not present" in absent.reason
    unlisted = env.dry("device.restart-service", {**dev(D1), "service": "WinDefend"})  # not in the registry list
    assert unlisted.status != "ok" and not unlisted.diff


@needs_pwsh
def test_b62_3_a_missing_drive_or_profile_is_refused(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    before = env.raw()
    assert env.dry("device.repair-mapped-drive", {**dev(D1), "drive": "Z"}).status == "denied"
    assert env.dry("device.reset-outlook-profile", {**dev(D1), "user": "nobody.here"}).status == "denied"
    assert env.dry("device.repair-mapped-drive", {**dev(D1), "drive": "C"}).status != "ok"  # C: is not allowed
    assert env.raw() == before


@needs_pwsh
def test_b62_3_caps_per_client_per_hour_apply_and_the_extra_execute_is_audited_as_denied(tmp_path: Path) -> None:
    spec = Registry.load().get("device.restart-service")
    assert spec is not None and spec.caps is not None
    limit = spec.caps.executes_per_client_per_hour
    assert limit == 3
    env = make_env(tmp_path, policy=True, clock=lambda: THU_10)
    calls = [(D1, "W32Time"), (D9, "wuauserv"), (D9, "LanmanWorkstation"), (D9, "BITS")]
    assert len(calls) == limit + 1
    for uid, service in calls[:limit]:
        assert env.run("device.restart-service", {**dev(uid), "service": service}).applied
    uid, service = calls[limit]
    before = env.raw()
    capped = env.run("device.restart-service", {**dev(uid), "service": service})
    assert capped.status == "denied" and not capped.applied
    assert env.chain()[-1]["result"]["kind"] == "cap-denied"
    assert env.raw() == before


def test_b62_3_every_cap_is_one_device_per_call_and_small_and_server_reboots_are_tightest() -> None:
    registry = Registry.load()
    for name in LEVERS:
        spec = registry.get(name)
        assert spec is not None and spec.caps is not None
        assert spec.caps.targets_per_run == 1, "one device per call"
        assert 1 <= spec.caps.executes_per_client_per_hour <= 10
    server = registry.get("device.reboot-server")
    assert server is not None and server.caps is not None and server.caps.executes_per_client_per_hour <= 2


@needs_pwsh
def test_b62_3_an_approval_is_bound_to_the_exact_device_and_parameters(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    before = env.raw()
    lever = "device.restart-spooler"
    for wrong in (
        Approval(approver="lead-lee", lever=lever, client=CONTOSO, params=dev(D2)),  # another device
        Approval(approver="lead-lee", lever="device.cleanup-temp", client=CONTOSO, params=dev(D1)),  # another lever
        Approval(approver="lead-lee", lever=lever, client=FABRIKAM, params=dev(D1)),  # another client
    ):
        result = env.runner.invoke(lever, dev(D1), "tech-ana", CONTOSO, mode="execute", approval=wrong)
        assert result.status == "denied" and not result.applied
    letter = Approval(
        approver="lead-lee", lever="device.repair-mapped-drive", client=CONTOSO, params={**dev(D1), "drive": "S"}
    )
    other = env.runner.invoke(
        "device.repair-mapped-drive", {**dev(D1), "drive": "P"}, "tech-ana", CONTOSO, mode="execute", approval=letter
    )
    assert other.status == "denied"
    assert env.raw() == before


@needs_pwsh
def test_b62_3_an_agent_may_propose_but_never_execute_and_no_approval_means_no_change(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    before = env.raw()
    lever, params = "device.restart-spooler", dev(D1)
    assert env.dry(lever, params).status == "ok"  # triage-bot proposes
    assert env.runner.invoke(lever, params, "tech-ana", CONTOSO, mode="execute").status != "ok"
    approval = Approval(approver="lead-lee", lever=lever, client=CONTOSO, params=params)
    assert env.runner.invoke(lever, params, "triage-bot", CONTOSO, mode="execute", approval=approval).status != "ok"
    own = Approval(approver="tech-ana", lever=lever, client=CONTOSO, params=params)
    assert env.runner.invoke(lever, params, "tech-ana", CONTOSO, mode="execute", approval=own).status != "ok"
    assert env.raw() == before


@needs_pwsh
def test_b62_3_the_plan_digest_pins_script_device_and_diff(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    lever, params = "device.restart-spooler", dev(D1)
    digest = env.dry(lever, params).data["plan_digest"]
    assert digest == env.dry(lever, params).data["plan_digest"] and re.fullmatch(r"[0-9a-f]{24}", digest)
    assert env.dry(lever, dev(D6)).data["plan_digest"] != digest
    assert env.dry("device.cleanup-temp", dev(D1)).data["plan_digest"] != digest
    assert env.run(lever, params).applied
    assert env.dry(lever, params).data["plan_digest"] != digest  # the device is fixed, so the plan is different


@needs_pwsh
@pytest.mark.parametrize("lever", LEVERS)
def test_b62_3_every_proposal_carries_verification_and_a_rollback_proposal(tmp_path: Path, lever: str) -> None:
    env = make_env(tmp_path)
    data = env.dry(lever, CASES[lever][0]).data
    checks = data["verification"]["checks"]
    assert checks and all({"check", "expected"} <= set(c) for c in checks)
    rollback = data["rollback"]
    assert rollback["automated"] is False and rollback["undo_lever"] is None
    expected_kind = {
        "device.reset-outlook-profile": "restore-from-backup",
        "device.cleanup-temp": "restore-from-backup",
        "device.reboot": "cannot-undo",
        "device.reboot-server": "cannot-undo",
    }.get(lever, "none-needed")
    assert rollback["kind"] == expected_kind
    assert rollback["proposal"] and all(isinstance(line, str) and line for line in rollback["proposal"])
    if rollback["kind"] == "restore-from-backup":
        assert any("20261022" in line for line in rollback["proposal"])


@needs_pwsh
@pytest.mark.parametrize("lever", sorted(FAULT_KEY))
def test_b62_3_a_failed_verification_is_an_error_after_the_audit_record_and_names_the_rollback(
    tmp_path: Path, lever: str
) -> None:
    env = make_env(tmp_path, policy=True, clock=lambda: THU_10)
    params = dict(CASES[lever][0])
    params["device"] = D6
    assert FAULT_KEY[lever] in env.device(D6)["faults"]
    result = env.run(lever, params)
    assert result.status == "error" and not result.applied, result.reason
    assert "Verification failed" in result.reason
    chain = env.chain()
    assert chain[-2]["result"]["applied"] is True, "the audit record is written before the change is applied"
    assert chain[-1]["result"]["status"] == "error"


@needs_pwsh
def test_b62_3_the_audit_record_keeps_the_exact_changes_and_the_approver(tmp_path: Path) -> None:
    env = make_env(tmp_path, policy=True, clock=lambda: THU_10)
    done = env.run("device.cleanup-temp", dev(D1))
    assert done.applied
    record = env.chain()[-1]
    assert record["lever"] == "device.cleanup-temp" and record["client"] == CONTOSO
    assert record["approver"] == "lead-lee" and record["params"] == dev(D1)
    assert [c["path"] for c in record["result"]["changes"]] == [c[1] for c in CASES["device.cleanup-temp"][1]]


@needs_pwsh
def test_b62_3_a_failed_dry_run_or_a_refused_execute_leaves_the_file_byte_identical(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    before = env.raw()
    for lever, params in (
        ("device.restart-spooler", dev(UNKNOWN)),
        ("device.reboot", dev(D4)),
        ("device.reboot", dev(D3)),
        ("device.restart-service", {**dev(D2), "service": "wuauserv"}),
    ):
        assert env.dry(lever, params).status != "ok"
        assert env.run(lever, params).status != "ok"
    assert env.raw() == before


# -- per-client scope --------------------------------------------------------------------------------------------


@needs_pwsh
def test_b62_3_another_clients_device_answers_exactly_like_an_absent_one(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    other = env.dry("device.restart-spooler", dev(F1))  # a Fabrikam uid, asked for as Contoso
    decoy = env.dry("device.restart-spooler", dev(DECOY))  # the other site's device sitting in the Contoso file
    absent = env.dry("device.restart-spooler", dev(UNKNOWN))
    assert other.status == decoy.status == absent.status == "denied"
    assert other.reason == decoy.reason == absent.reason
    assert "FAB-" not in str(other) and "FAB-" not in str(decoy)
    assert env.device(DECOY)["services"]["Spooler"]["health"] == "Hung"


@needs_pwsh
def test_b62_3_a_write_to_one_clients_file_never_touches_the_other(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    fabrikam, sessions = env.raw(FABRIKAM), env.path(CONTOSO, "remote-sessions.json").read_bytes()
    tenant_state = (env.tenant_dir / f"{CONTOSO}.json").read_bytes()
    assert env.run("device.restart-spooler", dev(D1)).applied
    assert env.raw(FABRIKAM) == fabrikam
    assert env.path(CONTOSO, "remote-sessions.json").read_bytes() == sessions
    assert (env.tenant_dir / f"{CONTOSO}.json").read_bytes() == tenant_state


@needs_pwsh
def test_b62_3_the_runner_keeps_an_identity_to_its_own_clients(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    before = env.raw(FABRIKAM)
    result = env.run("device.restart-spooler", dev(F1), FABRIKAM, "tech-ana")  # tech-ana holds Contoso only
    assert result.status == "denied" and not result.applied
    assert env.raw(FABRIKAM) == before
    own = env.dry("device.restart-spooler", dev(F1), FABRIKAM)
    assert own.status == "ok" and own.data["device"]["hostname"] == "FAB-WS01"


def test_b62_3_the_mock_state_belongs_to_the_clients_rmm_site_and_matches_the_rmm_fixture() -> None:
    for client in (CONTOSO, FABRIKAM):
        state = json.loads((MOCK / client / "devices.json").read_text(encoding="utf-8"))
        rmm = RmmMock.for_fixture(client)
        site = rmm.get_site().data
        assert site is not None
        assert state["_meta"]["client"] == client and state["_meta"]["siteUid"] == site["uid"]
        assert state["_meta"]["as_of"] == rmm.as_of
        listed = {d["uid"]: d for d in (rmm.list_devices().data or [])}
        for item in state["devices"]:
            if item["siteUid"] != site["uid"]:
                assert item["uid"] == DECOY, "the only foreign-site device is the planted decoy"
                continue
            assert item["uid"] in listed, item["uid"]
            assert item["hostname"] == listed[item["uid"]]["hostname"]
            assert item["online"] == listed[item["uid"]]["online"]
            assert item["deviceType"] == listed[item["uid"]]["deviceType"]


def test_b62_3_the_committed_mock_state_is_synthetic_and_carries_no_secret() -> None:
    files = list(MOCK.rglob("*.json"))
    assert len(files) == 4
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert re.search(r"password|secret|token|api[_-]?key|BEGIN [A-Z ]*KEY", text, re.I) is None, path
        assert re.search(r"\b\d{3}-\d{2}-\d{4}\b", text) is None, path


# -- B62-4: the remote-support session link ------------------------------------------------------------------------


@needs_pwsh
def test_b62_4_a_proposal_links_the_latest_remote_support_session_for_that_device(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    session = env.dry("device.restart-spooler", dev(D1)).data["remote_session"]
    assert session == {
        "session_id": "SESS-C-0003",
        "technician": "tech-session-a",
        "started": "2026-10-21T15:02:00Z",
        "ended": "2026-10-21T15:19:00Z",
        "computer_name": "FRONTDESK-01",
        "source": "remote-sessions.json",
    }
    server = env.dry("device.reboot-server", dev(D3)).data["remote_session"]
    assert server is not None and server["session_id"] == "SESS-C-0001"


@needs_pwsh
def test_b62_4_no_session_means_null_and_a_session_after_the_as_of_moment_is_not_linked(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    assert env.dry("device.restart-spooler", dev(D2)).data["remote_session"] is None
    sessions = json.loads(env.path(CONTOSO, "remote-sessions.json").read_text(encoding="utf-8"))
    future = [s["session_id"] for s in sessions["sessions"] if s["end_time"] > sessions["_meta"]["as_of"]]
    assert future == ["SESS-C-0004"], "the fixture plants one session that ends after the as-of moment"
    linked = env.dry("device.restart-spooler", dev(D1)).data["remote_session"]
    assert linked is not None and linked["session_id"] not in future


@needs_pwsh
def test_b62_4_a_session_of_another_client_is_never_linked(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    fab = env.dry("device.restart-spooler", dev(F1), FABRIKAM).data["remote_session"]
    assert fab is not None and fab["session_id"].startswith("SESS-F-")
    contoso = env.dry("device.restart-spooler", dev(D1)).data["remote_session"]
    assert contoso is not None and contoso["session_id"].startswith("SESS-C-")


@needs_pwsh
def test_b62_4_the_session_file_is_read_only_for_every_lever(tmp_path: Path) -> None:
    env = make_env(tmp_path, policy=True, clock=lambda: THU_10)
    before = env.path(CONTOSO, "remote-sessions.json").read_bytes()
    for lever in LEVERS:
        if lever != "device.reboot-server":
            assert env.run(lever, CASES[lever][0]).applied, lever
    assert env.path(CONTOSO, "remote-sessions.json").read_bytes() == before


def test_b62_4_every_session_field_is_marked_unverified_in_sources_and_gw13_is_cited() -> None:
    sources = (MODULE / "SOURCES.md").read_text(encoding="utf-8")
    assert "MP-13" in sources and "Splashtop" in sources
    seen: set[str] = set()
    for client in (CONTOSO, FABRIKAM):
        state = json.loads((MOCK / client / "remote-sessions.json").read_text(encoding="utf-8"))
        assert state["_meta"]["client"] == client
        for row in state["sessions"]:
            seen |= set(row)
    assert seen
    for name in sorted(seen):
        lines = [x for x in sources.splitlines() if f"`{name}`" in x]
        assert lines, f"{name} is not described in SOURCES.md"
        assert any("UNVERIFIED" in x for x in lines), name
    assert "Verified 20" not in sources


# -- notices, docs --------------------------------------------------------------------------------------------------


def test_b62_notice_templates_exist_for_every_lever_with_only_trusted_placeholders() -> None:
    allowed = {"first_name", "request", "approver", "team", "fast_phone", "hours"}
    for name in LEVERS:
        path = TEMPLATES / f"{name}.md"
        assert path.is_file(), name
        text = path.read_text(encoding="utf-8")
        used = {
            m.group("named") or m.group("braced")
            for m in string.Template.pattern.finditer(text)
            if m.group("named") or m.group("braced")
        }
        assert used <= allowed, (name, used - allowed)
        assert {"first_name", "approver", "request"} <= used
        string.Template(text).substitute({k: "x" for k in allowed})
        for heading in ("What changed:", "Why:", "Who approved it:", "How to undo it:"):
            assert heading in text, (name, heading)


def test_b62_docs_exist_and_state_what_is_not_verified() -> None:
    spec = (REPO / "specs" / "B-62.md").read_text(encoding="utf-8")
    change = (REPO / "docs" / "changes" / "B-62.md").read_text(encoding="utf-8")
    for acceptance in ("B62-1", "B62-2", "B62-3", "B62-4"):
        assert acceptance in spec
    assert "UNVERIFIED" in spec and "UNVERIFIED" in change
    assert "Not affiliated" in spec
