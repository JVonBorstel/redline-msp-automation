"""B-16 Python bridge and runner dispatch by runtime (specs/B-16.md).

Acceptance ids B16-1 to B16-3. Every test is offline and works on private copies in tmp_path: the synthetic mock
tenant, the audit log and (for the timeout and environment tests) small fixture PowerShell modules. Committed files
are never modified. Tests that start `pwsh` skip when PowerShell 7.4+ is not installed; the dispatch logic is also
tested with a fake bridge that needs no PowerShell.
Run: uv run --frozen pytest tests/py/levers/test_b16_bridge.py
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from core.audit import AuditLog, verify_chain
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, Approval, LeverDef, LeverRunner, MockTenant, Registry, RegistryError
from core.levers import bridge as bridge_module
from core.levers.bridge import (
    FUNCTION_RE,
    MODULE_RE,
    REQUEST_ID_RE,
    TENANT_DIR_ENV,
    BridgeResult,
    EntryFormatError,
    PowerShellBridge,
    PowerShellEntry,
    parse_entry,
)
from core.levers.diff import json_diff
from core.levers.handlers import LeverFailed
from core.levers.models import Change
from core.levers.tenant import JsonDict

REPO = Path(__file__).resolve().parents[3]
SAMPLE_FRAGMENT = REPO / "levers" / "powershell" / "Sample" / "Sample.registry.json"
CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
ANA = "ana.lopez@contosodental.example"
JAMIE = "jamie.chen@contosodental.example"
MORGAN = "morgan.reyes@fabrikamcapital.example"
TITLE = "Practice Director"
SET_TITLE = {"upn": ANA, "title": TITLE}
PWSH = shutil.which("pwsh")
needs_pwsh = pytest.mark.skipif(PWSH is None, reason="pwsh (PowerShell 7.4+) is not installed")
FIXTURE_IMPACT = {
    "L1": "One synthetic person is affected in a test.",
    "L2": "One synthetic client is affected in a test.",
    "L3": "The MSP sees the call in the audit.",
    "L4": "Nothing leaves the test.",
}


# -- helpers --------------------------------------------------------------------------------------


@dataclass
class Env:
    runner: LeverRunner
    tenant_dir: Path
    audit_path: Path
    registry: Registry

    def records(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines()]

    def tenant_bytes(self, client: str = CONTOSO) -> bytes:
        return (self.tenant_dir / f"{client}.json").read_bytes()

    def tenant(self, client: str = CONTOSO) -> JsonDict:
        loaded: JsonDict = json.loads(self.tenant_bytes(client))
        return loaded

    def chain_ok(self) -> bool:
        return verify_chain(self.audit_path, self.audit_path.with_name("audit.jsonl.head")).ok


def sample_registry(tmp_path: Path) -> Registry:
    fragments = tmp_path / "registry.d"
    fragments.mkdir(exist_ok=True)
    shutil.copy(SAMPLE_FRAGMENT, fragments / "sample.json")
    return Registry.load(fragments_dir=fragments)


def make_env(
    tmp_path: Path,
    registry: Registry | None = None,
    bridge: PowerShellBridge | None = None,
    modules_root: Path | None = None,
) -> Env:
    tenant_dir = tmp_path / "tenant"
    if not tenant_dir.exists():
        shutil.copytree(DEFAULT_TENANT_DIR, tenant_dir)
    audit_path = tmp_path / "audit.jsonl"
    reg = registry or sample_registry(tmp_path)
    if bridge is None and modules_root is not None:
        bridge = PowerShellBridge(modules_root=modules_root, tenant_dir=tenant_dir)
    runner = LeverRunner(reg, IdentityStore.load(), MockTenant(tenant_dir), AuditLog(audit_path), bridge=bridge)
    return Env(runner, tenant_dir, audit_path, reg)


def approval(lever: str, params: Mapping[str, Any], client: str = CONTOSO, approver: str = "lead-lee") -> Approval:
    return Approval(approver=approver, lever=lever, client=client, params=dict(params))


def execute_set_title(env: Env, params: Mapping[str, Any] = SET_TITLE) -> Any:
    return env.runner.invoke(
        "sampleuser.set-title",
        params,
        "tech-ana",
        CONTOSO,
        mode="execute",
        approval=approval("sampleuser.set-title", params),
    )


def user_of(state: JsonDict, upn: str) -> JsonDict:
    for user in state["users"]:
        if user["userPrincipalName"] == upn:
            found: JsonDict = user
            return found
    raise AssertionError(upn)


def python_twin_registry() -> Registry:
    """The same write as a Python lever (no PowerShell): the reference for 'same diff shape' (B16-3)."""

    def set_title(state: JsonDict, params: Mapping[str, Any]) -> Any:
        for user in state["users"]:
            if user["userPrincipalName"].lower() == params["upn"].lower():
                user["jobTitle"] = params["title"]
                return {"user": user["userPrincipalName"], "jobTitle": params["title"]}
        raise LeverFailed("no such user")

    raw = json.loads(SAMPLE_FRAGMENT.read_text(encoding="utf-8"))["levers"][1]
    raw = {k: v for k, v in raw.items() if k not in ("runtime", "entry")}
    raw["name"] = "pytwin.set-title"
    return Registry([LeverDef.model_validate(raw)], {"pytwin.set-title": set_title})


class RecordingBridge(PowerShellBridge):
    """The real bridge, counting calls and keeping every request's mode (to prove what never reached PowerShell)."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.modes: list[str] = []

    def call(self, **kwargs: Any) -> BridgeResult:
        self.modes.append(kwargs["mode"])
        return super().call(**kwargs)


class FakeBridge(PowerShellBridge):
    """A bridge that answers from a script instead of starting pwsh. `answers` maps mode to a result factory."""

    def __init__(self, answers: dict[str, Callable[[dict[str, Any]], BridgeResult]]) -> None:
        super().__init__()
        self.answers = answers
        self.calls: list[dict[str, Any]] = []
        self.on_call: Callable[[dict[str, Any]], None] | None = None

    def call(self, **kwargs: Any) -> BridgeResult:
        self.calls.append(kwargs)
        if self.on_call is not None:
            self.on_call(kwargs)
        return self.answers[kwargs["mode"]](kwargs)


def result_for(call: dict[str, Any], **fields: Any) -> BridgeResult:
    base: dict[str, Any] = {"status": "ok", "lever": call["lever"], "client": call["client"], "mode": call["mode"]}
    return BridgeResult.model_validate({**base, **fields})


TITLE_CHANGE = {"op": "replace", "path": "/users/u1/jobTitle", "before": "Old", "after": "New"}


def fake_env(tmp_path: Path, **answers: Callable[[dict[str, Any]], BridgeResult]) -> tuple[Env, FakeBridge]:
    fake = FakeBridge(answers=dict(answers))
    return make_env(tmp_path, bridge=fake), fake


# -- B16-1: dispatch by runtime; every runner check happens in Python first ----------------------------------


def test_b16_1_the_fragment_loads_with_runtime_powershell_and_the_four_python_levers_stay_python(
    tmp_path: Path,
) -> None:
    registry = sample_registry(tmp_path)
    assert registry.runtime("sampleuser.get") == "powershell"
    assert registry.runtime("sampleuser.set-title") == "powershell"
    assert registry.powershell_entry("sampleuser.set-title") == PowerShellEntry("Sample", "Set-SampleUserTitle")
    for name in ("kb.search", "ticket.get", "user.disable", "user.reset-mfa"):
        assert registry.runtime(name) == "python"
        assert registry.powershell_entry(name) is None
    shipped = Registry.load()
    # Later items add Python levers (B-23 ticket.link); the originals remain.
    assert {"kb.search", "ticket.get", "user.disable", "user.reset-mfa"} <= set(shipped.names())
    # PowerShell levers (B-29 to B-33) are declared runtime "powershell" in registry.d; the rest are Python.
    declared = {}
    for fragment in sorted((Path(__file__).resolve().parents[3] / "levers" / "registry.d").glob("*.json")):
        for lever in json.loads(fragment.read_text(encoding="utf-8"))["levers"]:
            declared[lever["name"]] = lever.get("runtime", "python")
    for name in shipped.names():
        assert shipped.runtime(name) == declared.get(name, "python")
        assert (shipped.powershell_entry(name) is not None) == (declared.get(name, "python") == "powershell")


def test_b16_1_the_live_registry_does_not_list_the_sample_levers() -> None:
    assert "sampleuser.get" not in Registry.load()
    assert not (REPO / "levers" / "registry.d" / "Sample.registry.json").exists()


@pytest.mark.parametrize(
    "entry",
    [
        "Sample",
        "Sample/Get-SampleUser",
        "..\\Evil\\Get-Thing",
        "sample\\Get-SampleUser",
        "Sample\\getSampleUser",
        7,
        None,
    ],
)
def test_b16_1_a_malformed_powershell_entry_is_refused_at_load(entry: object) -> None:
    with pytest.raises(EntryFormatError):
        parse_entry(entry)


def test_b16_1_registry_load_refuses_a_bad_or_missing_powershell_entry(tmp_path: Path) -> None:
    raw = json.loads(SAMPLE_FRAGMENT.read_text(encoding="utf-8"))
    cases = {
        "Sample": "runtime 'powershell'",
        "Nope\\Get-Thing": "module Nope is not installed",
        "..\\X\\Get-Y": "must look like",
    }
    for index, (entry, message) in enumerate(cases.items()):
        broken = copy.deepcopy(raw)
        broken["levers"][0]["entry"] = entry
        folder = tmp_path / f"case{index}"
        folder.mkdir()
        (folder / "f.json").write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(RegistryError, match=message):
            Registry.load(fragments_dir=folder)
    missing = copy.deepcopy(raw)
    del missing["levers"][0]["entry"]
    folder = tmp_path / "noentry"
    folder.mkdir()
    (folder / "f.json").write_text(json.dumps(missing), encoding="utf-8")
    with pytest.raises(RegistryError, match="runtime 'powershell'"):
        Registry.load(fragments_dir=folder)


def test_b16_1_a_powershell_lever_may_not_reuse_a_registered_name(tmp_path: Path) -> None:
    raw = json.loads(SAMPLE_FRAGMENT.read_text(encoding="utf-8"))
    raw["levers"][0]["name"] = "ticket.get"
    folder = tmp_path / "dup"
    folder.mkdir()
    (folder / "f.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RegistryError, match="registered twice"):
        Registry.load(fragments_dir=folder)


def test_b16_1_the_bridge_patterns_match_the_committed_request_schema() -> None:
    schema = json.loads((REPO / "schemas" / "lever-request.schema.json").read_text(encoding="utf-8"))
    entry = schema["properties"]["entry"]["properties"]
    assert MODULE_RE.pattern == entry["module"]["pattern"]
    assert FUNCTION_RE.pattern == entry["function"]["pattern"]
    assert REQUEST_ID_RE.pattern == schema["properties"]["request_id"]["pattern"]


@needs_pwsh
def test_b16_1_a_powershell_lever_runs_through_pwsh_noprofile_noninteractive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[dict[str, Any]] = []
    real_popen = subprocess.Popen

    def spy(argv: list[str], **kwargs: Any) -> Any:
        started.append({"argv": list(argv), "env": dict(kwargs["env"])})
        return real_popen(argv, **kwargs)

    monkeypatch.setattr(bridge_module.subprocess, "Popen", spy)
    env = make_env(tmp_path)
    result = env.runner.invoke("sampleuser.get", {"upn": ANA}, "triage-bot", CONTOSO)
    assert (result.status, result.data["userPrincipalName"]) == ("ok", ANA)
    assert len(started) == 1
    argv = started[0]["argv"]
    assert argv[1:3] == ["-NoProfile", "-NonInteractive"]
    assert Path(argv[argv.index("-File") + 1]).name == "Invoke-LeverRequest.ps1"
    assert started[0]["env"][TENANT_DIR_ENV] == str(env.tenant_dir)


@needs_pwsh
def test_b16_1_the_child_gets_a_scrubbed_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret_name = "REDLINE_TEST_" + "TOKEN"  # built at runtime: a secret-shaped variable name, not a real secret
    monkeypatch.setenv(secret_name, "not-a-real-value")
    modules = probe_modules(tmp_path)
    env = make_env(tmp_path, registry=probe_registry(tmp_path, modules), modules_root=modules)
    result = env.runner.invoke("probe.get-env", {}, "triage-bot", CONTOSO)
    assert result.status == "ok", result.reason
    names = set(result.data)
    assert secret_name not in names
    assert TENANT_DIR_ENV in names
    assert "path" in {name.lower() for name in names}


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"identity": "nobody"}, "unknown identity"),
        ({"identity": "tech-ben"}, "not scoped to client"),
        ({"lever": "sampleuser.nope"}, "is not registered"),
        ({"params": {"upn": "not-an-email"}}, "invalid params"),
        ({"params": {"upn": ANA, "title": "x"}}, "invalid params"),
        ({"mode": "wipe"}, "mode must be one of"),
    ],
)
def test_b16_1_denials_happen_in_python_before_any_process_starts(
    tmp_path: Path, kwargs: dict[str, Any], expected: str
) -> None:
    recording = RecordingBridge()
    env = make_env(tmp_path, bridge=recording)
    before = env.tenant_bytes()
    call: dict[str, Any] = {
        "lever": "sampleuser.get",
        "params": {"upn": ANA},
        "identity": "triage-bot",
        "client": CONTOSO,
    }
    call.update(kwargs)
    result = env.runner.invoke(
        call["lever"], call["params"], call["identity"], call["client"], mode=call.get("mode", "dry-run")
    )
    assert result.status == "denied" and expected in result.reason
    assert recording.modes == []
    assert env.tenant_bytes() == before
    last = env.records()[-1]
    assert (last["result"]["status"], last["mode"] in ("dry-run", "invalid")) == ("denied", True)


def test_b16_1_write_gates_are_checked_in_python_role_approval_four_eyes_and_params(tmp_path: Path) -> None:
    recording = RecordingBridge()
    env = make_env(tmp_path, bridge=recording)
    before = env.tenant_bytes()
    lever = "sampleuser.set-title"
    good = approval(lever, SET_TITLE)

    cases: list[tuple[str, Any, str]] = [
        ("triage-bot", good, "cannot execute"),  # an agent may propose, never execute
        ("tech-ana", None, "needs a lead approval record"),
        ("tech-ana", approval(lever, SET_TITLE, approver="tech-ben"), "is not a lead"),
        ("tech-ana", approval(lever, {"upn": ANA, "title": "Other"}), "does not match this lever, client and params"),
        ("tech-ana", approval(lever, SET_TITLE, client=FABRIKAM), "does not match this lever, client and params"),
        ("lead-lee", good, "four-eyes"),
    ]
    for identity, given, expected in cases:
        result = env.runner.invoke(lever, SET_TITLE, identity, CONTOSO, mode="execute", approval=given)
        assert result.status == "denied" and expected in result.reason, (identity, result.reason)
    assert env.runner.pause(lever, "lead-lee", "stop, test").ok
    paused = env.runner.invoke(lever, SET_TITLE, "tech-ana", CONTOSO, mode="execute", approval=good)
    assert paused.status == "denied" and paused.reason.startswith("lever paused by lead-lee")
    assert recording.modes == []  # nothing above reached PowerShell
    assert env.tenant_bytes() == before
    assert env.chain_ok()


@needs_pwsh
def test_b16_1_an_allowed_call_writes_one_audit_record_with_request_id_and_lever_version(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    result = env.runner.invoke("sampleuser.set-title", SET_TITLE, "triage-bot", CONTOSO)
    assert result.status == "ok"
    (record,) = env.records()
    assert (record["lever"], record["mode"], record["agent"], record["client"]) == (
        "sampleuser.set-title",
        "dry-run",
        "triage-bot",
        CONTOSO,
    )
    assert record["lever_version"] == 1
    assert REQUEST_ID_RE.match(record["request_id"])
    assert record["result"]["changes"][0]["path"].endswith("/jobTitle")
    assert record["result"]["idempotency"] == f"sampleuser.set-title/{CONTOSO}/upn={ANA}/title={TITLE}"
    assert env.chain_ok()


def test_b16_1_the_bridge_sends_the_same_request_id_to_both_calls_of_an_execute(tmp_path: Path) -> None:
    change = Change.model_validate(TITLE_CHANGE)
    env, fake = fake_env(
        tmp_path,
        **{
            "dry-run": lambda c: result_for(c, diff=(change,)),
            "execute": lambda c: result_for(c, diff=(change,), applied=True),
        },
    )
    result = execute_set_title(env)
    assert result.status == "ok" and result.applied
    assert [c["mode"] for c in fake.calls] == ["dry-run", "execute"]
    assert fake.calls[0]["request_id"] == fake.calls[1]["request_id"] == env.records()[0]["request_id"]
    assert fake.calls[0]["entry"] == PowerShellEntry("Sample", "Set-SampleUserTitle")
    assert fake.calls[0]["timeout_s"] == 15


def test_b16_1_a_read_lever_is_sent_to_the_host_as_execute_and_a_change_from_it_is_an_error(tmp_path: Path) -> None:
    change = Change.model_validate(TITLE_CHANGE)
    env, fake = fake_env(tmp_path, execute=lambda c: result_for(c, data={"ok": 1}))
    ok = env.runner.invoke("sampleuser.get", {"upn": ANA}, "triage-bot", CONTOSO)
    assert (ok.status, ok.data, ok.reason) == ("ok", {"ok": 1}, "dry-run: nothing applied")
    assert [c["mode"] for c in fake.calls] == ["execute"]

    (tmp_path / "two").mkdir()
    env2, _ = fake_env(tmp_path / "two", execute=lambda c: result_for(c, diff=(change,)))
    bad = env2.runner.invoke("sampleuser.get", {"upn": ANA}, "triage-bot", CONTOSO)
    assert (bad.status, bad.reason) == ("error", "read lever tried to change state; discarded")
    assert bad.applied is False


@pytest.mark.parametrize(
    ("status", "reason"),
    [("denied", "function Set-SampleUserTitle is not exported by module Sample; nothing ran"), ("error", "boom")],
)
def test_b16_1_a_host_refusal_or_error_becomes_the_runner_result_and_is_audited(
    tmp_path: Path, status: str, reason: str
) -> None:
    env, fake = fake_env(tmp_path, **{"dry-run": lambda c: result_for(c, status=status, reason=reason)})
    result = execute_set_title(env)
    assert (result.status, result.reason, result.applied) == (status, reason, False)
    assert [c["mode"] for c in fake.calls] == ["dry-run"]  # the real call never happened
    (record,) = env.records()
    assert (record["result"]["status"], record["result"]["applied"]) == (status, False)


def test_b16_1_the_audit_record_is_written_before_the_real_call(tmp_path: Path) -> None:
    change = Change.model_validate(TITLE_CHANGE)
    seen: dict[str, Any] = {}
    env, _ = fake_env(
        tmp_path,
        **{
            "dry-run": lambda c: result_for(c, diff=(change,)),
            "execute": lambda c: result_for(c, diff=(change,), applied=True),
        },
    )

    def peek(call: dict[str, Any]) -> None:
        if call["mode"] == "execute":
            seen["records"] = env.records()

    fake = env.runner.bridge
    assert isinstance(fake, FakeBridge)
    fake.on_call = peek
    result = execute_set_title(env)
    assert result.status == "ok"
    assert len(seen["records"]) == 1
    assert seen["records"][0]["result"]["applied"] is True and seen["records"][0]["mode"] == "execute"


def test_b16_1_a_failed_real_call_adds_a_second_record_that_says_so(tmp_path: Path) -> None:
    change = Change.model_validate(TITLE_CHANGE)
    env, _ = fake_env(
        tmp_path,
        **{
            "dry-run": lambda c: result_for(c, diff=(change,)),
            "execute": lambda c: result_for(c, status="error", reason="Sample crashed: IOException"),
        },
    )
    result = execute_set_title(env)
    first, second = env.records()
    assert (first["result"]["applied"], first["result"]["status"]) == (True, "ok")
    assert (second["result"]["applied"], second["result"]["status"]) == (False, "error")
    assert second["result"]["reason"] == f"apply failed after audit seq {first['seq']}: Sample crashed: IOException"
    assert (result.status, result.applied) == ("error", False)
    assert env.chain_ok()


@pytest.mark.parametrize(
    "real",
    [
        lambda c: result_for(c, diff=(Change.model_validate(TITLE_CHANGE),), applied=False),
        lambda c: result_for(c, diff=(), applied=True),
        lambda c: result_for(c, diff=(Change.model_validate({**TITLE_CHANGE, "after": "Different"}),), applied=True),
    ],
)
def test_b16_3_an_execute_that_does_not_match_the_dry_run_diff_is_an_error(
    tmp_path: Path, real: Callable[[dict[str, Any]], BridgeResult]
) -> None:
    change = Change.model_validate(TITLE_CHANGE)
    env, _ = fake_env(tmp_path, **{"dry-run": lambda c: result_for(c, diff=(change,)), "execute": real})
    result = execute_set_title(env)
    assert result.status == "error" and "did not match the dry-run diff" in result.reason
    assert env.records()[-1]["result"]["applied"] is False


def test_b16_1_an_empty_dry_run_diff_applies_nothing_and_never_calls_execute(tmp_path: Path) -> None:
    env, fake = fake_env(tmp_path, **{"dry-run": lambda c: result_for(c)})
    result = execute_set_title(env)
    assert (result.status, result.reason, result.applied) == ("ok", "no change: already in the desired state", False)
    assert [c["mode"] for c in fake.calls] == ["dry-run"]


# -- the bridge on its own: what it does with a bad answer ---------------------------------------------------


def call_bridge(bridge: PowerShellBridge, mode: str = "dry-run", timeout_s: float = 10) -> BridgeResult:
    return bridge.call(
        lever="sampleuser.get",
        lever_version=1,
        client=CONTOSO,
        mode=mode,  # type: ignore[arg-type]
        params={"upn": ANA},
        entry=PowerShellEntry("Sample", "Get-SampleUser"),
        timeout_s=timeout_s,
        request_id="req-00000000-test",
    )


def fake_host(tmp_path: Path, body: str) -> PowerShellBridge:
    script = tmp_path / "Fake-Host.ps1"
    script.write_text(body, encoding="utf-8")
    return PowerShellBridge(host_script=script)


GOOD_LINE = (
    '{"status":"ok","reason":"","lever":"sampleuser.get","client":"contoso-dental","mode":"dry-run",'
    '"data":null,"diff":[],"applied":false}'
)


@needs_pwsh
@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("param($ModulesRoot,$TimeoutSeconds)\nWrite-Output 'this is not json'\nexit 0", "not a lever result"),
        (
            f"param($ModulesRoot,$TimeoutSeconds)\nWrite-Output '{GOOD_LINE}'\nWrite-Output '{GOOD_LINE}'\nexit 0",
            "exactly one JSON",
        ),
        ("param($ModulesRoot,$TimeoutSeconds)\nexit 0", "exactly one JSON"),
        (f"param($ModulesRoot,$TimeoutSeconds)\nWrite-Output '{GOOD_LINE}'\nexit 1", "does not agree"),
        (f"param($ModulesRoot,$TimeoutSeconds)\nWrite-Output '{GOOD_LINE}'\nexit 2", "does not agree"),
        (
            "param($ModulesRoot,$TimeoutSeconds)\nWrite-Output '"
            + GOOD_LINE.replace("contoso-dental", "fabrikam-capital")
            + "'\nexit 0",
            "different lever, client or mode",
        ),
        (
            "param($ModulesRoot,$TimeoutSeconds)\nWrite-Output '"
            + GOOD_LINE.replace('"applied":false', '"applied":true')
            + "'\nexit 0",
            "applied during a dry-run",
        ),
        (
            "param($ModulesRoot,$TimeoutSeconds)\nWrite-Output '"
            + GOOD_LINE.replace('"diff":[]', '"diff":[{"op":"zap","path":"/x"}]')
            + "'\nexit 0",
            "not a lever result",
        ),
        (
            "param($ModulesRoot,$TimeoutSeconds)\nWrite-Output '" + GOOD_LINE[:-1] + ',"stack":"at line 1"}\'\nexit 0',
            "not a lever result",
        ),
    ],
)
def test_b16_1_a_bad_host_answer_is_an_error_never_trusted(tmp_path: Path, script: str, expected: str) -> None:
    result = call_bridge(fake_host(tmp_path, script))
    assert result.status == "error" and expected in result.reason, result.reason
    assert result.applied is False and result.diff == ()


@needs_pwsh
def test_b16_1_a_good_fake_answer_passes_so_the_cases_above_fail_for_the_right_reason(tmp_path: Path) -> None:
    result = call_bridge(
        fake_host(tmp_path, f"param($ModulesRoot,$TimeoutSeconds)\nWrite-Output '{GOOD_LINE}'\nexit 0")
    )
    assert result.status == "ok"


@needs_pwsh
def test_b16_1_a_host_that_dies_with_exit_2_is_an_error_with_no_stack_text(tmp_path: Path) -> None:
    line = GOOD_LINE.replace('"status":"ok"', '"status":"error"').replace("sampleuser.get", "unknown")
    result = call_bridge(fake_host(tmp_path, f"param($ModulesRoot,$TimeoutSeconds)\nWrite-Output '{line}'\nexit 2"))
    assert result.status == "error" and "Traceback" not in result.reason


def test_b16_1_missing_pwsh_is_a_result_not_an_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bridge_module.shutil, "which", lambda _name: None)
    result = call_bridge(PowerShellBridge())
    assert (result.status, "not installed" in result.reason) == ("error", True)
    broken = call_bridge(PowerShellBridge(pwsh=str(Path("no") / "such" / "pwsh.exe")))
    assert broken.status == "error" and "could not start pwsh" in broken.reason


def test_b16_1_an_invalid_entry_or_request_id_never_starts_a_process(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a process was started")

    monkeypatch.setattr(bridge_module.subprocess, "Popen", boom)
    bridge = PowerShellBridge(pwsh="pwsh")
    bad_entry = bridge.call(
        lever="sampleuser.get",
        lever_version=1,
        client=CONTOSO,
        mode="dry-run",
        params={},
        entry=PowerShellEntry("..\\Evil", "Get-Thing"),
        timeout_s=5,
        request_id="req-00000000-test",
    )
    assert bad_entry.status == "error" and "nothing ran" in bad_entry.reason
    bad_id = bridge.call(
        lever="sampleuser.get",
        lever_version=1,
        client=CONTOSO,
        mode="dry-run",
        params={},
        entry=PowerShellEntry("Sample", "Get-SampleUser"),
        timeout_s=5,
        request_id="short",
    )
    assert bad_id.status == "error" and "nothing ran" in bad_id.reason


# -- B16-2: the child is killed at timeout_s --------------------------------------------------------------------

PROBE_MODULES = {
    "Probe": (
        ["Get-ProbeEnv", "Wait-ProbeForever", "Set-ProbeSlow"],
        """Set-StrictMode -Version Latest
function Get-ProbeEnv {
    [CmdletBinding()] param([string] $Client)
    @(Get-ChildItem Env: | ForEach-Object { $_.Name })
}
function Wait-ProbeForever {
    [CmdletBinding(SupportsShouldProcess)] param([string] $Client)
    Start-Sleep -Seconds 120
    [pscustomobject]@{ data = $null; diff = @(); applied = $false }
}
function Set-ProbeSlow {
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')] param([string] $Client)
    $change = [pscustomobject][ordered]@{ op = 'add'; path = '/probe/slow'; after = 'x' }
    if ($PSCmdlet.ShouldProcess('probe', 'slow change')) { Start-Sleep -Seconds 120 }
    [pscustomobject][ordered]@{ data = $null; diff = @($change); applied = $false }
}
""",
    )
}


def probe_modules(tmp_path: Path) -> Path:
    root = tmp_path / "ps-modules"
    for module, (functions, code) in PROBE_MODULES.items():
        folder = root / module
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{module}.psm1").write_text(code, encoding="utf-8")
        exported = ", ".join(f"'{name}'" for name in functions)
        (folder / f"{module}.psd1").write_text(
            f"@{{ RootModule = '{module}.psm1'; ModuleVersion = '0.1.0'; "
            "GUID = '6d1c7a52-0b3e-4f19-8c24-7e5a9b1d3f60'; "
            f"FunctionsToExport = @({exported}); "
            "CmdletsToExport = @(); VariablesToExport = @(); AliasesToExport = @() }\n",
            encoding="utf-8",
        )
    return root


def probe_lever(name: str, entry: str, lever_class: str, timeout_s: float) -> dict[str, Any]:
    lever: dict[str, Any] = {
        "name": name,
        "runtime": "powershell",
        "entry": entry,
        "description": "Test lever over a fixture PowerShell module.",
        "client_scope": "any",
        "required_role": "agent" if lever_class == "read" else "technician",
        "class": lever_class,
        "approval": "none" if lever_class == "read" else "lead",
        "idempotency_keys": [],
        "params": {},
        "dry_run": True,
        "timeout_s": timeout_s,
    }
    if lever_class == "write":
        lever.update({"dry_run_role": "agent", "risk_class": "R1", "impact": FIXTURE_IMPACT})
    return lever


def probe_registry(tmp_path: Path, modules: Path, timeout_s: float = 4) -> Registry:
    folder = tmp_path / "probe.d"
    folder.mkdir(exist_ok=True)
    levers = [
        probe_lever("probe.get-env", "Probe\\Get-ProbeEnv", "read", 10),
        probe_lever("probe.wait", "Probe\\Wait-ProbeForever", "write", timeout_s),
        probe_lever("probe.slow-set", "Probe\\Set-ProbeSlow", "write", timeout_s + 2),
    ]
    (folder / "probe.json").write_text(json.dumps({"version": 1, "levers": levers}), encoding="utf-8")
    return Registry.load(fragments_dir=folder, powershell_root=modules)


class SpyBridge(PowerShellBridge):
    """Keeps the child processes it started, so a test can prove they are gone."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.processes: list[Any] = []

    def call(self, **kwargs: Any) -> BridgeResult:
        real_popen = subprocess.Popen

        def spy(*args: Any, **kw: Any) -> Any:
            process = real_popen(*args, **kw)
            self.processes.append(process)
            return process

        original = bridge_module.subprocess.Popen
        bridge_module.subprocess.Popen = spy  # type: ignore[misc,assignment]
        try:
            return super().call(**kwargs)
        finally:
            bridge_module.subprocess.Popen = original  # type: ignore[misc]


@needs_pwsh
def test_b16_2_a_hung_dry_run_is_killed_at_timeout_s_and_is_an_error_with_nothing_applied(tmp_path: Path) -> None:
    modules = probe_modules(tmp_path)
    spy = SpyBridge(modules_root=modules, tenant_dir=tmp_path / "tenant")
    env = make_env(tmp_path, registry=probe_registry(tmp_path, modules), bridge=spy)
    before = env.tenant_bytes()

    started = time.monotonic()
    result = env.runner.invoke("probe.wait", {}, "triage-bot", CONTOSO)
    elapsed = time.monotonic() - started

    assert result.status == "error" and result.applied is False
    assert "timed out after 4s" in result.reason and "killed" in result.reason
    assert 3.5 <= elapsed < 15, elapsed  # killed at the limit, not at the 120 s the lever wanted
    assert len(spy.processes) == 1 and spy.processes[0].poll() is not None  # the child is gone
    assert env.tenant_bytes() == before
    (record,) = env.records()
    assert (record["result"]["status"], record["result"]["applied"]) == ("error", False)
    assert env.chain_ok()


@needs_pwsh
def test_b16_2_a_hang_during_the_real_call_is_killed_and_the_second_record_says_nothing_was_applied(
    tmp_path: Path,
) -> None:
    modules = probe_modules(tmp_path)
    spy = SpyBridge(modules_root=modules, tenant_dir=tmp_path / "tenant")
    env = make_env(tmp_path, registry=probe_registry(tmp_path, modules), bridge=spy)
    before = env.tenant_bytes()

    result = env.runner.invoke(
        "probe.slow-set", {}, "tech-ana", CONTOSO, mode="execute", approval=approval("probe.slow-set", {})
    )

    assert result.status == "error" and result.applied is False
    assert "apply failed after audit seq 1" in result.reason and "timed out after 6s" in result.reason
    assert [p.poll() is not None for p in spy.processes] == [True, True]  # dry-run exited, real call was killed
    first, second = env.records()
    assert (first["result"]["applied"], second["result"]["applied"], second["result"]["status"]) == (
        True,
        False,
        "error",
    )
    assert env.tenant_bytes() == before
    assert env.chain_ok()


# -- B16-3: a sample read and a sample write, same diff shape as a Python lever ---------------------------------


@needs_pwsh
def test_b16_3_the_sample_read_lever_returns_the_user_without_sign_in_or_contact_details(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    before = env.tenant_bytes()
    result = env.runner.invoke("sampleuser.get", {"upn": ANA}, "triage-bot", CONTOSO)
    assert result.status == "ok" and result.diff == () and result.applied is False
    expected = user_of(env.tenant(), ANA)
    assert result.data == {
        "id": expected["id"],
        "displayName": expected["displayName"],
        "userPrincipalName": ANA,
        "jobTitle": expected["jobTitle"],
        "accountEnabled": expected["accountEnabled"],
    }
    assert "authentication" not in json.dumps(result.data) and "+" not in json.dumps(result.data)
    executed = env.runner.invoke("sampleuser.get", {"upn": ANA}, "tech-ana", CONTOSO, mode="execute")
    assert (executed.status, executed.data, executed.reason) == (
        "ok",
        result.data,
        "no change: already in the desired state",
    )
    assert env.tenant_bytes() == before


@needs_pwsh
def test_b16_3_the_sample_read_lever_cannot_see_another_clients_user(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    result = env.runner.invoke("sampleuser.get", {"upn": MORGAN}, "triage-bot", CONTOSO)
    assert result.status == "error" and result.data is None
    assert "RuntimeException" in result.reason and MORGAN not in result.reason
    other = env.runner.invoke("sampleuser.get", {"upn": MORGAN}, "triage-bot", FABRIKAM)
    assert other.status == "ok" and other.data["userPrincipalName"] == MORGAN


@needs_pwsh
@pytest.mark.parametrize("has_title", [True, False])
def test_b16_3_the_sample_write_dry_run_has_the_same_diff_as_a_python_lever(tmp_path: Path, has_title: bool) -> None:
    env = make_env(tmp_path)
    if not has_title:  # the 'add' case: a user with no jobTitle yet
        state = env.tenant()
        del user_of(state, ANA)["jobTitle"]
        (env.tenant_dir / f"{CONTOSO}.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    before = env.tenant_bytes()

    ps = env.runner.invoke("sampleuser.set-title", SET_TITLE, "triage-bot", CONTOSO)
    twin = LeverRunner(
        python_twin_registry(),
        IdentityStore.load(),
        MockTenant(env.tenant_dir),
        AuditLog(tmp_path / "twin-audit.jsonl"),
    ).invoke("pytwin.set-title", SET_TITLE, "triage-bot", CONTOSO)

    assert ps.status == twin.status == "ok"
    assert len(ps.diff) == 1
    assert [c.model_dump() for c in ps.diff] == [c.model_dump() for c in twin.diff]
    assert ps.diff[0].op == ("replace" if has_title else "add")
    assert ps.diff[0].path.startswith("/users/") and ps.diff[0].path.endswith("/jobTitle")
    assert (ps.applied, ps.reason) == (False, "dry-run: nothing applied")
    assert env.tenant_bytes() == before  # a dry-run writes nothing


@needs_pwsh
def test_b16_3_an_execute_applies_exactly_the_dry_run_diff(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    before_state = env.tenant()
    dry = env.runner.invoke("sampleuser.set-title", SET_TITLE, "tech-ana", CONTOSO)
    assert env.tenant() == before_state

    done = execute_set_title(env)
    after_state = env.tenant()

    assert (done.status, done.applied, done.approver) == ("ok", True, "lead-lee")
    assert [c.model_dump() for c in done.diff] == [c.model_dump() for c in dry.diff]
    # What changed on disk is exactly the dry-run diff, and nothing else (shape, dates, other users, other keys).
    assert json_diff(before_state, after_state) == list(dry.diff)
    expected = copy.deepcopy(before_state)
    user_of(expected, ANA)["jobTitle"] = TITLE
    assert after_state == expected
    assert (env.tenant_dir / f"{FABRIKAM}.json").read_bytes() == (DEFAULT_TENANT_DIR / f"{FABRIKAM}.json").read_bytes()
    assert not list(env.tenant_dir.glob("*.tmp"))
    # One audit record for the dry-run, one for the execute; the execute record holds the same change.
    dry_record, run_record = env.records()
    assert run_record["result"]["applied"] is True and run_record["approver"] == "lead-lee"
    assert run_record["result"]["changes"] == dry_record["result"]["changes"]
    assert env.chain_ok()


@needs_pwsh
def test_b16_3_a_second_execute_is_convergent_and_changes_nothing(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    assert execute_set_title(env).applied
    after_first = env.tenant_bytes()
    again = execute_set_title(env)
    assert (again.status, again.applied, again.diff) == ("ok", False, ())
    assert again.reason == "no change: already in the desired state"
    assert env.tenant_bytes() == after_first


@needs_pwsh
def test_b16_3_the_sample_write_never_touches_another_clients_tenant(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    other_before = env.tenant_bytes(FABRIKAM)
    result = env.runner.invoke(
        "sampleuser.set-title",
        {"upn": MORGAN, "title": TITLE},
        "tech-ana",
        CONTOSO,
        mode="execute",
        approval=approval("sampleuser.set-title", {"upn": MORGAN, "title": TITLE}),
    )
    assert result.status == "error" and result.applied is False
    assert env.tenant_bytes(FABRIKAM) == other_before
    assert env.chain_ok()


@needs_pwsh
def test_b16_3_the_sample_write_rejects_a_hostile_title_before_powershell_runs(tmp_path: Path) -> None:
    recording = RecordingBridge()
    env = make_env(tmp_path, bridge=recording)
    result = env.runner.invoke(
        "sampleuser.set-title", {"upn": ANA, "title": "x'; Remove-Item *"}, "triage-bot", CONTOSO
    )
    assert result.status == "denied" and "invalid params" in result.reason
    assert recording.modes == []


def test_b16_3_the_sample_module_is_laid_out_like_the_standards_say() -> None:
    folder = REPO / "levers" / "powershell" / "Sample"
    manifest = (folder / "Sample.psd1").read_text(encoding="utf-8")
    assert "FunctionsToExport    = @('Get-SampleUser', 'Set-SampleUserTitle')" in manifest
    assert "CmdletsToExport      = @()" in manifest
    source = (folder / "Sample.psm1").read_text(encoding="utf-8")
    assert source.startswith("Set-StrictMode -Version Latest") or "\nSet-StrictMode -Version Latest" in source
    assert "SupportsShouldProcess" in source and "ShouldProcess($Upn" in source
    assert (folder / "README.md").is_file()
