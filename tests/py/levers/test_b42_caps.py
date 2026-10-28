"""B-42 runner: blast-radius caps, per-client audit chains, windows and pre-authorized containment.

Acceptance ids B42-1 to B42-5 are defined in specs/B-42.md. Every test is offline and works on a private copy of the
mock tenant and its own audit folder under tmp_path; committed files are never modified. Clients, identities and
levers are synthetic. Containment and window tests pin the runner clock in March 2025 (a fixed UTC-08:00 client, so
no daylight-saving rule is involved); the cap tests use the real clock because audit timestamps are real.
Run: uv run --frozen pytest tests/py/levers/test_b42_caps.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from core.audit import AuditError, AuditLog, verify_chain
from core.audit.router import MSP_LOG, AuditRouter, file_lock
from core.identity import Identity, IdentityStore, Role
from core.levers import DEFAULT_TENANT_DIR, Approval, LeverDef, LeverRunner, MockTenant, Registry
from core.levers.__main__ import _runner, main
from core.levers.caps import DEFAULT_CAPS, CapLedger, ClientRules, caps_for, count_targets, parse_zone
from core.levers.models import LeverCaps
from core.levers.runner import PolicyError, RunnerPolicy
from core.queue import ProposalQueue, open_queue
from ui.app import App

CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
HOST = {"host": "127.0.0.1:8765"}

# Wed 2025-03-05 10:00 at a fixed UTC-08:00 client.
WED_10 = datetime(2025, 3, 5, 18, 0, tzinfo=UTC)
WED_NIGHT = datetime(2025, 3, 5, 5, 0, tzinfo=UTC)  # Tue 21:00 there
WED_CLOSING = datetime(2025, 3, 6, 1, 0, tzinfo=UTC)  # Wed 17:00 there: the end is outside
SAT_10 = datetime(2025, 3, 8, 18, 0, tzinfo=UTC)
FRI_10 = datetime(2025, 3, 7, 18, 0, tzinfo=UTC)
SUN_2230 = datetime(2025, 3, 10, 6, 30, tzinfo=UTC)  # Sun 22:30 there: inside the maintenance window
MON_0100 = datetime(2025, 3, 10, 9, 0, tzinfo=UTC)  # Mon 01:00 there: the window runs past midnight
DUE_AFTER_WED = datetime(2025, 3, 7, 1, 0, tzinfo=UTC)  # Thu 17:00 there
DUE_AFTER_FRI = datetime(2025, 3, 11, 1, 0, tzinfo=UTC)  # Mon 17:00 there

WORKWEEK = {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "08:00", "end": "17:00"}
CONTOSO_RECORD: dict[str, Any] = {
    "time_zone": "UTC-08:00",
    "business_hours": WORKWEEK,
    "maintenance_window": {"days": ["sun"], "start": "22:00", "end": "02:00"},
    "containment_preauthorized": True,
}


def ident(id_: str, role: Role) -> Identity:
    return Identity(id=id_, display_name=f"{id_} (synthetic)", role=role, clients=(CONTOSO, FABRIKAM))


IDENTITIES = IdentityStore(
    [
        ident("tech-ana", Role.TECHNICIAN),
        ident("lead-lee", Role.LEAD),
        ident("lead-fay", Role.LEAD),
        ident("lead-gus", Role.LEAD),
    ]
)


def lever(name: str, risk: str = "R1", **extra: Any) -> LeverDef:
    base: dict[str, Any] = {
        "name": name,
        "description": "A write lever for B-42 tests.",
        "client_scope": "any",
        "required_role": "technician",
        "dry_run_role": "agent",
        "class": "write",
        "approval": "lead",
        "idempotency_keys": ["n"],
        "params": {"n": {"type": "integer", "required": True}},
        "dry_run": True,
        "timeout_s": 5,
        "risk_class": risk,
    }
    return LeverDef.model_validate({**base, **extra})


def set_flag(state: dict[str, Any], params: Mapping[str, Any]) -> Any:
    state["flag"] = params["n"]
    return {"flag": params["n"]}


def make_registry() -> Registry:
    levers = [
        lever("test.hourly", caps={"targets_per_run": 1, "executes_per_client_per_hour": 2, "clients_per_day": 10}),
        lever("test.daily", caps={"targets_per_run": 1, "executes_per_client_per_hour": 10, "clients_per_day": 1}),
        lever("test.targets", caps={"targets_per_run": 2, "executes_per_client_per_hour": 10, "clients_per_day": 10}),
        lever("test.default"),
        lever("test.bh", window="business-hours"),
        lever("test.mw", window="maintenance"),
        lever("test.contain", "R3", preauthorized_containment=True),
        lever("test.plain3", "R3"),
        lever("test.purge", "R3", reversibility="irreversible"),
    ]
    return Registry(levers, {spec.name: set_flag for spec in levers})


def make_runner(
    tmp_path: Path,
    *,
    clock: Callable[[], datetime] | None = None,
    records: Mapping[str, Mapping[str, Any]] | None = None,
    policy: bool = True,
    audit: AuditLog | AuditRouter | None = None,
    registry: Registry | None = None,
) -> LeverRunner:
    tenant_dir = tmp_path / "tenant"
    if not tenant_dir.exists():
        shutil.copytree(DEFAULT_TENANT_DIR, tenant_dir)
    the_policy = (
        RunnerPolicy(demo=True, client_records={CONTOSO: CONTOSO_RECORD} if records is None else records)
        if policy
        else None
    )
    return LeverRunner(
        registry or make_registry(),
        IDENTITIES,
        MockTenant(tenant_dir),
        audit if audit is not None else AuditRouter(tmp_path / "audit"),
        policy=the_policy,
        clock=clock,
    )


def at(moment: datetime) -> Callable[[], datetime]:
    return lambda: moment


def approval(name: str, params: Mapping[str, Any], client: str = CONTOSO, who: str = "lead-lee", **kw: Any) -> Approval:
    return Approval(approver=who, lever=name, client=client, params=dict(params), demo=True, **kw)


def execute(
    runner: LeverRunner, name: str, n: int, approvals: list[Approval] | None = None, client: str = CONTOSO
) -> Any:
    params = {"n": n}
    given = approvals if approvals is not None else [approval(name, params, client)]
    return runner.invoke(name, params, "tech-ana", client, mode="execute", approval=given)


def two_leads(name: str, n: int) -> list[Approval]:
    return [approval(name, {"n": n}), approval(name, {"n": n}, who="lead-fay")]


def chain(tmp_path: Path, name: str = CONTOSO) -> list[dict[str, Any]]:
    path = tmp_path / "audit" / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def flag(tmp_path: Path, client: str = CONTOSO) -> Any:
    return json.loads((tmp_path / "tenant" / f"{client}.json").read_text(encoding="utf-8")).get("flag")


# -- B42-1 caps come from the registry; the N+1th execute is denied and audited -----------------------------


def test_b42_1_caps_come_from_registry() -> None:
    registry = Registry.load()
    expected = {
        "user.disable": (1, 10, 20),
        "user.revoke-sessions": (1, 20, 40),
        "user.enable": (1, 20, 30),
        "user.set-properties": (1, 30, 40),
        # B-62 device levers carry their own caps (one device per call)
        "device.restart-spooler": (1, 10, 25),
        "device.repair-mapped-drive": (1, 10, 25),
        "device.reset-outlook-profile": (1, 5, 25),
        "device.cleanup-temp": (1, 5, 25),
        "device.restart-service": (1, 3, 25),
        "device.reboot": (1, 6, 25),
        "device.reboot-server": (1, 2, 10),
    }
    for name, numbers in expected.items():
        spec = registry.get(name)
        assert spec is not None
        caps, source = caps_for(spec)
        assert source == "registry"
        assert (caps.targets_per_run, caps.executes_per_client_per_hour, caps.clients_per_day) == numbers

    # every other write lever falls back to the default for its risk class, and says so
    on_default = []
    for name in registry.names():
        spec = registry.get(name)
        assert spec is not None
        if spec.lever_class != "write" or name in expected:
            continue
        caps, source = caps_for(spec)
        assert source == "default" and caps == DEFAULT_CAPS[spec.risk_class or "R1"]
        on_default.append(name)
    assert on_default, "the default path is exercised by at least one real write lever"


@pytest.mark.parametrize(
    "bad",
    [
        {"targets_per_run": 0, "executes_per_client_per_hour": 1, "clients_per_day": 1},
        {"targets_per_run": 1, "executes_per_client_per_hour": -3, "clients_per_day": 1},
        {"targets_per_run": 1, "executes_per_client_per_hour": 1},
        {"targets_per_run": 1, "executes_per_client_per_hour": 1, "clients_per_day": 1, "per_week": 4},
        {"targets_per_run": "5", "executes_per_client_per_hour": 1, "clients_per_day": 1},
    ],
)
def test_b42_1_bad_caps_fail_the_load(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        lever("test.bad", caps=bad)


def test_b42_1_caps_apply_to_write_levers_only() -> None:
    read = {
        "name": "test.read",
        "description": "A read lever.",
        "client_scope": "any",
        "required_role": "agent",
        "class": "read",
        "approval": "none",
        "params": {},
        "dry_run": True,
        "timeout_s": 5,
    }
    LeverDef.model_validate(read)
    one = {"targets_per_run": 1, "executes_per_client_per_hour": 1, "clients_per_day": 1}
    with pytest.raises(ValidationError):
        LeverDef.model_validate({**read, "caps": one})


def test_b42_1_nplus1_execute_in_hour_is_denied_and_audited(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)
    assert execute(runner, "test.hourly", 1).applied and execute(runner, "test.hourly", 2).applied
    third = execute(runner, "test.hourly", 3)
    assert third.status == "denied" and not third.applied
    assert "executes_per_client_per_hour = 2 (registry)" in third.reason and "HO-6" in third.reason
    assert flag(tmp_path) == 2  # the denied call changed nothing

    denial = chain(tmp_path)[-1]
    assert denial["mode"] == "execute" and denial["result"]["status"] == "denied"
    assert denial["result"]["kind"] == "cap-denied" and denial["result"]["cap"] == "executes_per_client_per_hour"
    assert (denial["result"]["limit"], denial["result"]["cap_source"]) == (2, "registry")

    # a denied call is not an execute: the count stays 2, and another client is not affected
    now = datetime.now(UTC)
    assert runner.ledger.executes_in_hour("test.hourly", CONTOSO, now) == 2
    assert execute(runner, "test.hourly", 1, client=FABRIKAM).applied

    # an hour later the window has moved on
    later = make_runner(tmp_path, clock=at(now + timedelta(minutes=61)))
    assert execute(later, "test.hourly", 4).applied


def test_b42_1_a_lever_without_caps_gets_its_risk_class_default(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)
    spec = runner.registry.get("test.default")
    assert spec is not None and spec.caps is None
    assert caps_for(spec) == (DEFAULT_CAPS["R1"], "default")
    limit = DEFAULT_CAPS["R1"].executes_per_client_per_hour
    ledger_over = CapLedger(runner.audit)
    for n in range(limit):
        assert execute(runner, "test.default", n).ok
    assert ledger_over.executes_in_hour("test.default", CONTOSO, datetime.now(UTC)) == limit
    over = execute(runner, "test.default", limit)
    assert over.status == "denied" and "(default)" in over.reason
    assert chain(tmp_path)[-1]["result"]["cap_source"] == "default"


def test_b42_1_clients_per_day_cap(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)
    assert execute(runner, "test.daily", 1).applied
    blocked = execute(runner, "test.daily", 1, client=FABRIKAM)
    assert blocked.status == "denied" and "clients_per_day = 1 (registry)" in blocked.reason
    assert chain(tmp_path, FABRIKAM)[-1]["result"]["cap"] == "clients_per_day"
    assert flag(tmp_path, FABRIKAM) is None
    # a client already counted today may go on
    assert execute(runner, "test.daily", 2).applied


def test_b42_1_targets_per_run_cap(tmp_path: Path) -> None:
    # ParamSpec has no list type yet, so every real call is one target; the count and the check are proved on the
    # ledger directly so a bulk-capable lever added later is held to its cap.
    runner = make_runner(tmp_path)
    spec = runner.registry.get("test.targets")
    assert spec is not None
    assert count_targets({"n": 3}) == 1 and count_targets({"upns": ["a", "b", "c"], "x": 1}) == 3
    now = datetime.now(UTC)
    assert runner.ledger.check(spec, CONTOSO, {"upns": ["a", "b"]}, now) is None
    denial = runner.ledger.check(spec, CONTOSO, {"upns": ["a", "b", "c"]}, now)
    assert denial is not None and denial.detail["cap"] == "targets_per_run" and denial.detail["limit"] == 2
    assert "3 targets" in denial.reason


def test_b42_1_caps_hold_on_a_plain_audit_log_too(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, audit=AuditLog(tmp_path / "audit.jsonl"))
    assert execute(runner, "test.hourly", 1).applied and execute(runner, "test.hourly", 2).applied
    assert execute(runner, "test.hourly", 3).status == "denied"
    assert verify_chain(tmp_path / "audit.jsonl", tmp_path / "audit.jsonl.head").ok


# -- B42-2 one chain per client plus _msp ---------------------------------------------------------------------


def test_b42_2_records_split_per_client_and_msp(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)
    assert execute(runner, "test.default", 1).applied
    assert execute(runner, "test.default", 2, client=FABRIKAM).applied
    assert runner.pause("test.default", "lead-lee", "B-42 test pause", client=None).ok

    audit_dir = tmp_path / "audit"
    assert {p.name for p in audit_dir.glob("*.jsonl")} == {f"{CONTOSO}.jsonl", f"{FABRIKAM}.jsonl", f"{MSP_LOG}.jsonl"}
    assert {r["client"] for r in chain(tmp_path, CONTOSO)} == {CONTOSO}
    assert {r["client"] for r in chain(tmp_path, FABRIKAM)} == {FABRIKAM}
    assert [r["mode"] for r in chain(tmp_path, MSP_LOG)] == ["pause"] and chain(tmp_path, MSP_LOG)[0]["client"] is None

    for name in (CONTOSO, FABRIKAM, MSP_LOG):  # each chain verifies alone, against its own head pin
        log = audit_dir / f"{name}.jsonl"
        assert verify_chain(log, log.with_name(log.name + ".head")).ok
    assert all(result.ok for result in runner.audit.verify_all().values())  # type: ignore[union-attr]

    # tampering with one chain breaks that chain and no other
    contoso_log = audit_dir / f"{CONTOSO}.jsonl"
    contoso_log.write_bytes(contoso_log.read_bytes().replace(b'"agent":"tech-ana"', b'"agent":"tech-eve"'))
    results = runner.audit.verify_all()  # type: ignore[union-attr]
    assert not results[CONTOSO].ok and results[FABRIKAM].ok and results[MSP_LOG].ok


def test_b42_2_hostile_client_ids_never_become_file_names(tmp_path: Path) -> None:
    router = AuditRouter(tmp_path / "audit")
    for hostile in ("../escape", "con", "CON", "Contoso", "", "a/b", "x" * 80, "nul", "_msp", "..", "a.b"):
        denied = {"status": "denied"}
        router.append(agent="x", client=hostile, lever="test.default", params={}, mode="dry-run", result=denied)
    found = {p.name for p in (tmp_path / "audit").iterdir()}
    assert {n for n in found if n.endswith(".jsonl")} == {"_msp.jsonl"}
    assert not (tmp_path / "escape.jsonl").exists()
    assert len(chain(tmp_path, MSP_LOG)) == 11  # nothing was dropped: the raw value stays in the record
    assert verify_chain(router.path, router.path.with_name("_msp.jsonl.head")).ok


def test_b42_2_exported_client_chain_reveals_no_other_client(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)
    assert execute(runner, "test.default", 1).applied
    assert execute(runner, "test.default", 2, client=FABRIKAM).applied
    router = runner.audit
    assert isinstance(router, AuditRouter)
    log, head = router.export_client(CONTOSO, tmp_path / "out")
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [f"{CONTOSO}.jsonl", f"{CONTOSO}.jsonl.head"]
    assert FABRIKAM.encode() not in log.read_bytes() + head.read_bytes()
    assert verify_chain(log, head).ok  # the export verifies on its own, away from the audit folder
    with pytest.raises(AuditError):
        router.export_client("never-seen", tmp_path / "out2")
    with pytest.raises(AuditError):
        router.export_client("../audit", tmp_path / "out3")
    assert not (tmp_path / "out2").exists() and not (tmp_path / "out3").exists()


def test_b42_2_cli_verify_and_export(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    state = tmp_path / "state"
    args = ["--state", str(state)]
    assert main([*args, "invoke", "ticket.get", "--as", "tech-ana", "--client", CONTOSO, "-p", "ticket_id=T-1001"]) == 0
    assert (state / "audit" / f"{CONTOSO}.jsonl").exists() and not (state / "audit.jsonl").exists()
    assert main([*args, "verify"]) == 0
    assert main([*args, "export", "--client", CONTOSO, "--out", str(tmp_path / "out")]) == 0
    assert main([*args, "export", "--client", "never-seen", "--out", str(tmp_path / "out2")]) == 1
    log = state / "audit" / f"{CONTOSO}.jsonl"
    log.write_bytes(log.read_bytes().replace(b"tech-ana", b"tech-eve"))
    assert main([*args, "verify"]) == 1
    assert f"{CONTOSO}" in capsys.readouterr().out


# -- B42-3 cross-process lock; the UI and the CLI construct the router ----------------------------------------


REPO = Path(__file__).resolve().parents[3]
CHILD_ENV = {**os.environ, "PYTHONPATH": str(REPO)}
APPEND_CODE = """
import sys
from pathlib import Path
from core.audit.router import AuditRouter
router = AuditRouter(Path(sys.argv[1]))
for i in range(25):
    router.append(agent="proc-" + sys.argv[2], client="contoso-dental", lever="test.default", params={"i": i},
                  mode="dry-run", result={"status": "ok", "reason": "", "applied": False, "changes": []})
"""
HOLD_CODE = """
import sys, time
from pathlib import Path
from core.audit.router import file_lock
target, ready, release = (Path(a) for a in sys.argv[1:4])
with file_lock(target):
    ready.write_text("ready")
    deadline = time.monotonic() + 60
    while not release.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
"""


def child(code: str, *args: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen([sys.executable, "-c", code, *args], cwd=REPO, env=CHILD_ENV)  # noqa: S603


def test_b42_3_cross_process_append_keeps_chain_intact(tmp_path: Path) -> None:
    procs = [child(APPEND_CODE, str(tmp_path / "audit"), str(who)) for who in range(4)]
    assert [proc.wait(timeout=180) for proc in procs] == [0, 0, 0, 0]
    records = chain(tmp_path)
    assert [r["seq"] for r in records] == list(range(1, 101))
    log = tmp_path / "audit" / f"{CONTOSO}.jsonl"
    assert verify_chain(log, log.with_name(log.name + ".head")).ok


def test_b42_3_lock_timeout_fails_closed(tmp_path: Path) -> None:
    router = AuditRouter(tmp_path / "audit", lock_timeout_s=0.3)
    router.append(agent="x", client=CONTOSO, lever="test.default", params={}, mode="dry-run", result={"status": "ok"})

    def try_append(into: list[BaseException]) -> None:
        try:
            router.append(agent="y", client=CONTOSO, lever="test.default", params={}, mode="dry-run", result={})
        except BaseException as exc:
            into.append(exc)

    # held by another thread of this process
    errors: list[BaseException] = []
    with file_lock(router.path_for(CONTOSO)):
        worker = threading.Thread(target=try_append, args=(errors,))
        worker.start()
        worker.join(10)
    assert len(errors) == 1 and isinstance(errors[0], AuditError) and "failing closed" in str(errors[0])

    # held by another process
    ready, release = tmp_path / "ready.flag", tmp_path / "release.flag"
    holder = child(HOLD_CODE, str(router.path_for(CONTOSO)), str(ready), str(release))
    try:
        deadline = time.monotonic() + 60
        while not ready.exists() and time.monotonic() < deadline and holder.poll() is None:
            time.sleep(0.05)
        assert ready.exists(), "the child process never took the lock"
        with pytest.raises(AuditError, match="locked by another process"):
            router.append(agent="z", client=CONTOSO, lever="test.default", params={}, mode="dry-run", result={})
    finally:
        release.write_text("go")
        assert holder.wait(timeout=60) == 0
    assert len(chain(tmp_path)) == 1  # nothing was written while the lock was held
    router.append(agent="after", client=CONTOSO, lever="test.default", params={}, mode="dry-run", result={})
    assert len(chain(tmp_path)) == 2


def test_b42_3_ui_and_cli_construct_the_router(tmp_path: Path) -> None:
    queue = open_queue(tmp_path / "queue-state")
    assert isinstance(queue.runner.audit, AuditRouter)
    assert isinstance(_runner(tmp_path / "cli-state", Registry.load()).audit, AuditRouter)

    for client, who in ((CONTOSO, "marker-contoso"), (FABRIKAM, "marker-fabrikam")):
        queue.runner.audit.append(
            agent=who,
            client=client,
            lever="ticket.get",
            params={"ticket_id": "T-1"},
            mode="dry-run",
            result={"status": "ok"},
        )
    app = App(queue)
    page = app.handle("GET", f"/audit?client={CONTOSO}", HOST)
    text = page.body.decode()
    assert page.status == 200 and "marker-contoso" in text and "marker-fabrikam" not in text
    assert "marker-fabrikam" in app.handle("GET", f"/audit?client={FABRIKAM}", HOST).body.decode()
    assert f'<option value="{CONTOSO}" selected>' in text and f'<option value="{FABRIKAM}">' in text
    verified = app.handle("GET", f"/audit?client={CONTOSO}&verify=1", HOST).body.decode()
    assert "OK: 1 records" in verified
    assert app.handle("GET", "/audit?client=no-such-client", HOST).status == 404
    assert app.handle("GET", "/audit?client=..%2Fx", HOST).status == 404


# -- B42-4 windows -------------------------------------------------------------------------------------------


def test_b42_4_refused_outside_business_hours_and_maintenance(tmp_path: Path) -> None:
    for name, moment in (
        ("test.bh", WED_NIGHT),
        ("test.bh", WED_CLOSING),
        ("test.bh", SAT_10),
        ("test.mw", WED_10),
        ("test.mw", SUN_2230 - timedelta(hours=1, minutes=45)),  # Sun 20:45 there, before the window opens
    ):
        runner = make_runner(tmp_path, clock=at(moment))
        result = execute(runner, name, 1)
        assert result.status == "denied" and not result.applied, (name, moment)
        label = "business hours" if name == "test.bh" else "maintenance window"
        assert f"outside the client's {label}" in result.reason and "named window override" in result.reason
        assert chain(tmp_path)[-1]["result"]["kind"] == "window-denied"
    assert flag(tmp_path) is None  # nothing was applied by any of them


def test_b42_4_allowed_inside(tmp_path: Path) -> None:
    cases = (
        ("test.bh", WED_10),
        ("test.bh", FRI_10),
        ("test.mw", SUN_2230),
        ("test.mw", MON_0100),  # the window opened Sunday evening and runs past midnight
    )
    for n, (name, moment) in enumerate(cases, start=1):  # a new value each time, so none is a no-change repeat
        result = execute(make_runner(tmp_path, clock=at(moment)), name, n)
        assert result.ok and result.applied, (name, moment, result.reason)
    assert "window_override" not in chain(tmp_path)[-1]["result"]


def test_b42_4_no_window_defined_is_refused_not_defaulted(tmp_path: Path) -> None:
    cases: list[tuple[str, Mapping[str, Mapping[str, Any]] | None, bool, str]] = [
        ("no business hours on the record", {CONTOSO: {"time_zone": "UTC-08:00"}}, True, "no business hours defined"),
        ("no time zone", {CONTOSO: {"business_hours": WORKWEEK}}, True, "no time_zone"),
        ("no record at all for the client", {FABRIKAM: CONTOSO_RECORD}, True, "no business hours defined"),
        ("no maintenance window", {CONTOSO: {**CONTOSO_RECORD, "maintenance_window": None}}, True, "not defaulted"),
        (
            "end before start",
            {CONTOSO: {**CONTOSO_RECORD, "business_hours": {**WORKWEEK, "start": "17:00", "end": "08:00"}}},
            True,
            "end must be after start",
        ),
        ("unknown time zone", {CONTOSO: {**CONTOSO_RECORD, "time_zone": "Mars/Olympus"}}, True, "not known on this"),
        ("a runner with no client records at all", None, False, "no business hours defined"),
    ]
    for label, records, policy, words in cases:
        runner = make_runner(tmp_path, clock=at(WED_10), records=records, policy=policy)
        result = execute(runner, "test.bh" if "maintenance" not in label else "test.mw", 1)
        assert result.status == "denied" and words in result.reason, (label, result.reason)
        assert "refused, not defaulted" in result.reason or "no business hours defined" in result.reason
    assert flag(tmp_path) is None


def test_b42_4_client_record_keys_are_checked() -> None:
    with pytest.raises(PolicyError, match="containment_preauthorized"):
        RunnerPolicy(client_records={CONTOSO: {"containment_preauthorized": "yes"}})
    rules = ClientRules.from_record({"business_hours": {"days": ["funday"], "start": "8", "end": "17:00"}})
    assert "business_hours" in rules.problems
    for bad in ("UTC+25:00", "UTC-08:99", "", "../../etc/passwd", 5):
        with pytest.raises(ValueError, match="time_zone"):
            parse_zone(bad)
    assert parse_zone("UTC-08:00").utcoffset(None) == timedelta(hours=-8)
    try:  # IANA names need tzdata on this machine; either it resolves or the refusal is plain
        parse_zone("America/Los_Angeles")
    except ValueError as exc:
        assert "not known on this machine" in str(exc)


def test_b42_4_override_recorded_in_audit(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, clock=at(WED_NIGHT))
    params = {"n": 5}
    named = approval("test.bh", params, window_override="after-hours-ir")
    result = execute(runner, "test.bh", 5, [named])
    assert result.ok and result.applied
    record = chain(tmp_path)[-1]
    override = record["result"]["window_override"]
    assert override["name"] == "after-hours-ir" and override["window"] == "business-hours"
    assert "outside the client's business hours" in override["bypassed"]
    assert record["approver"] == "lead-lee"

    # the same call without the override stays refused; a client with no window is let through only by a named override
    assert execute(runner, "test.bh", 6).status == "denied"
    bare = make_runner(tmp_path, clock=at(WED_NIGHT), records={})
    assert execute(bare, "test.bh", 7).status == "denied"
    assert execute(bare, "test.bh", 7, [approval("test.bh", {"n": 7}, window_override="client-has-no-window")]).applied

    # an override is a short name, never free text
    for text in ("Please let this through!", "x" * 41, "", "UPPER"):
        with pytest.raises(ValidationError):
            approval("test.bh", params, window_override=text)


def test_b42_4_unflagged_lever_ignores_window(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, clock=at(SAT_10), records={})
    result = execute(runner, "test.default", 1)
    assert result.ok and result.applied
    assert "window_override" not in chain(tmp_path)[-1]["result"]


# -- B42-5 pre-authorized containment ------------------------------------------------------------------------


def on_call(name: str, n: int, who: str = "lead-lee") -> Approval:
    return approval(name, {"n": n}, who=who, on_call=True)


def test_b42_5_preauthorized_containment_one_on_call_approval(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, clock=at(WED_10))
    result = execute(runner, "test.contain", 1, [on_call("test.contain", 1)])
    assert result.ok and result.applied
    records = chain(tmp_path)
    executed = [r for r in records if r["mode"] == "execute"][-1]
    assert executed["result"]["containment"] == {"kind": "pre-authorized", "on_call_approver": "lead-lee"}
    assert executed["result"]["approvers_required"] == 1 and executed["approver"] == "lead-lee"

    reviews = runner.reviews.open_reviews()
    assert len(reviews) == 1 and reviews[0].due == DUE_AFTER_WED  # end of business hours, next business day
    assert executed["result"]["second_review"]["id"] == reviews[0].id
    opened = [r for r in records if r["result"].get("kind") == "second-review-opened"]
    assert len(opened) == 1 and opened[0]["mode"] == "approve" and opened[0]["result"]["review_id"] == reviews[0].id

    # Friday afternoon: the next business day is Monday
    friday = make_runner(tmp_path, clock=at(FRI_10))
    assert execute(friday, "test.contain", 2, [on_call("test.contain", 2)]).applied
    assert max(r.due for r in friday.reviews.open_reviews()) == DUE_AFTER_FRI


@pytest.mark.parametrize(
    ("label", "records", "name", "words"),
    [
        ("lever not flagged", {CONTOSO: CONTOSO_RECORD}, "test.plain3", "needs approvals from 2 distinct leads"),
        (
            "client does not set the flag",
            {CONTOSO: {**CONTOSO_RECORD, "containment_preauthorized": False}},
            "test.contain",
            "does not set containment_preauthorized",
        ),
        (
            "no business hours for the review date",
            {CONTOSO: {"containment_preauthorized": True}},
            "test.contain",
            "needs business_hours and time_zone",
        ),
        ("no client record", {}, "test.contain", "does not set containment_preauthorized"),
    ],
)
def test_b42_5_without_every_condition_the_normal_approval_count_stands(
    tmp_path: Path, label: str, records: Mapping[str, Mapping[str, Any]], name: str, words: str
) -> None:
    runner = make_runner(tmp_path, clock=at(WED_10), records=records)
    result = execute(runner, name, 1, [on_call(name, 1)])
    assert result.status == "denied" and "2 distinct leads" in result.reason and words in result.reason, label
    assert flag(tmp_path) is None and runner.reviews.open_reviews() == []


def test_b42_5_no_on_call_mark_means_two_approvals(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, clock=at(WED_10))
    assert execute(runner, "test.contain", 1).status == "denied"  # one plain approval
    both = execute(runner, "test.contain", 1, two_leads("test.contain", 1))
    assert both.ok and both.applied and runner.reviews.open_reviews() == []  # two leads: no containment, no review


def test_b42_5_irreversible_never_uses_path(tmp_path: Path) -> None:
    real = Registry.load()
    for name in real.names():  # nothing in the real registry combines the two
        spec = real.get(name)
        assert spec is not None and not (spec.reversibility == "irreversible" and spec.preauthorized_containment)

    runner = make_runner(tmp_path, clock=at(WED_10))
    fresh = datetime(2025, 3, 5, 17, 0, tzinfo=UTC)
    one = approval("test.purge", {"n": 1}, on_call=True, approved_at=fresh)
    result = execute(runner, "test.purge", 1, [one])
    assert result.status == "denied" and "2 distinct leads" in result.reason

    # the flag on an irreversible lever loads (the registry cannot know), and the runner refuses it in code
    purge = runner.registry.get("test.purge")
    assert purge is not None
    forced = lever("test.purge", "R3", reversibility="irreversible", preauthorized_containment=True)
    hacked = make_runner(tmp_path, clock=at(WED_10), registry=Registry([forced], {"test.purge": set_flag}))
    refused = execute(hacked, "test.purge", 1, [one])
    assert refused.status == "denied" and "irreversible levers never use this path" in refused.reason
    assert flag(tmp_path) is None and hacked.reviews.open_reviews() == []


def test_b42_5_overdue_review_is_audited_once_and_alerts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runner = make_runner(tmp_path, clock=at(WED_10))
    assert execute(runner, "test.contain", 1, [on_call("test.contain", 1)]).applied
    review = runner.reviews.open_reviews()[0]

    assert runner.check_reviews(DUE_AFTER_WED - timedelta(minutes=1)) == []  # not due yet: no alert, no record
    assert not (tmp_path / "audit" / f"{MSP_LOG}.jsonl").exists()
    late = DUE_AFTER_WED + timedelta(hours=1)
    assert [r.id for r in runner.check_reviews(late)] == [review.id]
    assert [r.id for r in runner.check_reviews(late + timedelta(hours=5))] == [review.id]  # still overdue, listed again
    msp = chain(tmp_path, MSP_LOG)
    assert len(msp) == 1  # ... but audited once
    assert msp[0]["result"]["kind"] == "second-review-overdue" and msp[0]["result"]["status"] == "error"
    assert msp[0]["client"] is None and msp[0]["params"] == {"client": CONTOSO, "review_id": review.id}

    # the CLI exits 1 and the page shows a banner while it is overdue (the real clock is long past March 2025)
    clients = tmp_path / "clients.json"
    clients.write_text(json.dumps({CONTOSO: CONTOSO_RECORD}), encoding="utf-8")
    cli = ["--state", str(tmp_path), "--clients", str(clients), "--demo"]
    # the CLI keeps its audit under <state>/audit, the same folder the runner here wrote to
    assert main([*cli, "reviews"]) == 1 and "OVERDUE" in capsys.readouterr().out
    live = make_runner(tmp_path)  # real clock
    queue = ProposalQueue(tmp_path / "queue.jsonl", live)
    banner = "Second review overdue"
    assert banner in App(queue).handle("GET", "/", HOST).body.decode()
    assert banner in App(queue).handle("GET", f"/audit?client={CONTOSO}", HOST).body.decode()

    # completing it clears the alert; the on-call approver and the requester cannot complete it
    assert live.complete_review(review.id, "lead-lee").status == "denied"
    assert live.complete_review(review.id, "tech-ana").status == "denied"
    assert live.complete_review("rev-nope", "lead-fay").status == "denied"
    done = live.complete_review(review.id, "lead-fay")
    assert done.ok and done.approver == "lead-fay"
    assert live.complete_review(review.id, "lead-gus").status == "denied"  # already completed
    kinds = [r["result"].get("kind") for r in chain(tmp_path)]
    assert kinds.count("second-review-completed") == 1
    assert live.check_reviews() == []
    assert main([*cli, "reviews"]) == 0 and "no open second reviews" in capsys.readouterr().out
    assert banner not in App(queue).handle("GET", "/", HOST).body.decode()


def test_b42_5_a_no_change_containment_voids_its_review(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, clock=at(WED_10))
    assert execute(runner, "test.contain", 1, [on_call("test.contain", 1)]).applied
    again = execute(runner, "test.contain", 1, [on_call("test.contain", 1)])  # already in the desired state
    assert again.ok and not again.applied
    statuses = sorted(r.status for r in runner.reviews.all().values())
    assert statuses == ["open", "void"]
    assert [r["result"].get("kind") for r in chain(tmp_path)].count("second-review-void") == 1


def test_b42_5_caps_still_apply_to_containment(tmp_path: Path) -> None:
    caps = {"targets_per_run": 1, "executes_per_client_per_hour": 1, "clients_per_day": 5}
    capped = lever("test.contain", "R3", preauthorized_containment=True, caps=caps)
    registry = Registry([capped], {"test.contain": set_flag})
    runner = make_runner(tmp_path, clock=at(datetime.now(UTC)), registry=registry)
    assert execute(runner, "test.contain", 1, [on_call("test.contain", 1)]).applied
    second = execute(runner, "test.contain", 2, [on_call("test.contain", 2)])
    assert second.status == "denied" and "executes_per_client_per_hour" in second.reason
    assert len(runner.reviews.open_reviews()) == 1  # the denied call opened no review


def test_b42_registry_caps_model_is_frozen() -> None:
    caps = LeverCaps(targets_per_run=1, executes_per_client_per_hour=1, clients_per_day=1)
    with pytest.raises(ValidationError):
        caps.targets_per_run = 5  # type: ignore[misc]
