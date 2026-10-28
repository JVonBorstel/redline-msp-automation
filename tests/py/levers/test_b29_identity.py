"""B-29 IdentityOps levers: revoke sessions, enable (undo of disable), mover property changes (specs/B-29.md).

Acceptance ids B29-1 to B29-3. Every test is offline and works on private copies of the synthetic mock tenant in
tmp_path; committed fixtures are never modified. Tests that start `pwsh` skip when PowerShell 7.4+ is not installed.
The PowerShell side has its own plain-script tests
(levers/powershell/IdentityOps/tests/IdentityOps.Tests.ps1, STD-PS-9),
which include the Graph-permission (scope) denial, because the bridge gives the child process a scrubbed environment.
Run: uv run --frozen pytest tests/py/levers/test_b29_identity.py
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from core.audit import AuditLog
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, Approval, LeverRunner, MockTenant, Registry
from core.levers.bridge import PowerShellEntry
from core.levers.models import Verification
from core.levers.tenant import JsonDict
from workflows.notify import missing_templates

REPO = Path(__file__).resolve().parents[3]
MODULE = REPO / "levers" / "powershell" / "IdentityOps"
CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
ANA = "ana.lopez@contosodental.example"
SAM = "sam.patel@contosodental.example"
JAMIE = "jamie.chen@contosodental.example"
ALEX = "alex.ward@fabrikamcapital.example"  # a Guest in fabrikam-capital/sessions.json
MORGAN = "morgan.reyes@fabrikamcapital.example"
AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
VERIFIED = Verification(method="callback-on-file", by="lead-lee", at=AT, ref="CALL-2901")
NEW_LEVERS = ("user.revoke-sessions", "user.enable", "user.set-properties")
SCOPES = {
    "user.revoke-sessions": ("User.RevokeSessions.All",),
    "user.enable": ("User.EnableDisableAccount.All",),
    "user.set-properties": ("User.ReadWrite.All",),
}
needs_pwsh = pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh (PowerShell 7.4+) is not installed")


@dataclass
class Env:
    runner: LeverRunner
    tenant_dir: Path
    audit_path: Path

    def path(self, rel: str) -> Path:
        return self.tenant_dir / rel

    def bytes_of(self, rel: str) -> bytes:
        return self.path(rel).read_bytes()

    def user(self, upn: str, client: str = CONTOSO) -> JsonDict:
        state: JsonDict = json.loads(self.path(f"{client}.json").read_bytes())
        for user in state["users"]:
            if user["userPrincipalName"] == upn:
                found: JsonDict = user
                return found
        raise AssertionError(upn)

    def sessions(self, upn: str, client: str = CONTOSO) -> JsonDict:
        data: JsonDict = json.loads(self.path(f"{client}/sessions.json").read_bytes())
        for entry in data["value"]:
            if entry["userPrincipalName"] == upn:
                found: JsonDict = entry
                return found
        raise AssertionError(upn)

    def run(self, lever: str, params: dict[str, Any], client: str = CONTOSO, *, execute: bool = False) -> Any:
        if not execute:
            return self.runner.invoke(lever, params, "triage-bot", client)
        approval = Approval(approver="lead-lee", lever=lever, client=client, params=params, verification=VERIFIED)
        return self.runner.invoke(lever, params, "tech-ana", client, mode="execute", approval=approval)


@pytest.fixture
def env(tmp_path: Path) -> Env:
    tenant_dir = tmp_path / "tenant"
    shutil.copytree(DEFAULT_TENANT_DIR, tenant_dir)
    audit_path = tmp_path / "audit.jsonl"
    runner = LeverRunner(Registry.load(), IdentityStore.load(), MockTenant(tenant_dir), AuditLog(audit_path))
    return Env(runner, tenant_dir, audit_path)


# -- registry and layout ----------------------------------------------------------------------------------------


def test_b29_registry_lists_the_three_powershell_levers_with_scopes_and_risk_classes() -> None:
    registry = Registry.load()
    entries = {
        "user.revoke-sessions": PowerShellEntry("IdentityOps", "Revoke-UserSessions"),
        "user.enable": PowerShellEntry("IdentityOps", "Enable-UserAccount"),
        "user.set-properties": PowerShellEntry("IdentityOps", "Set-UserProperty"),
    }
    for name in NEW_LEVERS:
        spec = registry.get(name)
        assert spec is not None and spec.lever_class == "write"
        assert registry.runtime(name) == "powershell" and registry.powershell_entry(name) == entries[name]
        assert spec.risk_class == "R2" and spec.dry_run is True and spec.approval == "lead"
        assert spec.graph_scopes == SCOPES[name]
        assert spec.impact is not None and all(getattr(spec.impact, f"L{i}") for i in range(1, 5))


def test_b29_scopes_in_the_registry_match_the_ones_the_module_checks() -> None:
    text = (MODULE / "IdentityOps.psm1").read_text(encoding="utf-8")
    table = dict(re.findall(r"'([A-Z][a-z]+-[A-Za-z]+)'\s*=\s*'([A-Za-z.]+)'", text))
    registry = Registry.load()
    for name in NEW_LEVERS:
        function = registry.powershell_entry(name)
        assert function is not None
        assert (table[function.function],) == registry.get(name).graph_scopes  # type: ignore[union-attr]


def test_b29_every_new_write_lever_has_a_notice_template() -> None:
    assert missing_templates(Registry.load()) == []
    for name in NEW_LEVERS:
        assert (REPO / "workflows" / "notify" / "templates" / f"{name}.md").is_file()


def test_b29_the_module_is_laid_out_like_the_standards_say() -> None:
    for name in ("IdentityOps.psd1", "IdentityOps.psm1", "README.md", "tests/IdentityOps.Tests.ps1"):
        assert (MODULE / name).is_file(), name


# -- B29-1: revoke sessions --------------------------------------------------------------------------------------


def test_b29_1_the_readme_states_the_lag_and_that_guest_users_are_not_covered() -> None:
    text = " ".join((MODULE / "README.md").read_text(encoding="utf-8").split()).lower()
    assert "user.revoke-sessions" in text and "user.revokesessions.all" in text
    assert "lag" in text and "guest" in text and "does not apply to guest" in text


@needs_pwsh
def test_b29_1_revoke_dry_run_shows_a_diff_and_writes_nothing(env: Env) -> None:
    before = env.bytes_of(f"{CONTOSO}/sessions.json")
    result = env.run("user.revoke-sessions", {"upn": ANA})
    assert result.status == "ok" and result.applied is False and result.reason == "dry-run: nothing applied"
    assert [(c.op, c.before, c.after) for c in result.diff] == [("replace", 3, 0)]
    assert result.diff[0].path.endswith("/activeSessionCount") and "lag" in result.data
    assert env.bytes_of(f"{CONTOSO}/sessions.json") == before
    assert env.bytes_of(f"{CONTOSO}.json") == (DEFAULT_TENANT_DIR / f"{CONTOSO}.json").read_bytes()


@needs_pwsh
def test_b29_1_revoke_execute_applies_the_diff_once_and_a_repeat_changes_nothing(env: Env) -> None:
    dry = env.run("user.revoke-sessions", {"upn": ANA})
    done = env.run("user.revoke-sessions", {"upn": ANA}, execute=True)
    assert done.status == "ok" and done.applied is True and list(done.diff) == list(dry.diff)
    assert env.sessions(ANA)["activeSessionCount"] == 0
    assert env.sessions(SAM)["activeSessionCount"] == 2  # nobody else changed
    again = env.run("user.revoke-sessions", {"upn": ANA}, execute=True)
    assert again.status == "ok" and again.applied is False and again.reason == "no change: already in the desired state"


@needs_pwsh
def test_b29_1_a_guest_user_is_refused_and_nothing_is_written(env: Env) -> None:
    before = env.bytes_of(f"{FABRIKAM}/sessions.json")
    result = env.run("user.revoke-sessions", {"upn": ALEX}, FABRIKAM)
    assert result.status == "error" and "crashed" in result.reason and result.applied is False
    assert env.bytes_of(f"{FABRIKAM}/sessions.json") == before


@needs_pwsh
def test_b29_1_a_user_of_another_client_is_refused(env: Env) -> None:
    # (A client with no sessions file, litware-legal, is covered by the PowerShell tests: no identity is scoped to it.)
    assert env.run("user.revoke-sessions", {"upn": MORGAN}).status == "error"


def test_b29_1_a_malformed_upn_is_refused_before_powershell_runs(env: Env) -> None:
    result = env.run("user.revoke-sessions", {"upn": "x'; Remove-Item *"})
    assert result.status == "denied"


# -- B29-2: enable is the undo of disable -------------------------------------------------------------------------


def test_b29_2_enable_is_the_registered_undo_of_disable_and_back() -> None:
    registry = Registry.load()
    disable, enable = registry.get("user.disable"), registry.get("user.enable")
    assert disable is not None and enable is not None
    assert disable.undo == "user.enable" and enable.undo == "user.disable" and enable.undo_of == "user.disable"
    assert enable.lever_class == "write" and enable.verification == "requester"


@needs_pwsh
def test_b29_2_disable_then_enable_returns_the_fixture_to_byte_identical_state(env: Env) -> None:
    # The committed file is hand-formatted; the first write by the Python MockTenant lays it out canonically (with the
    # platform's line ending). The baseline is that canonical form of the original, so the comparison is exact.
    tenant = MockTenant(env.tenant_dir)
    tenant.save(CONTOSO, tenant.load(CONTOSO))
    baseline = env.bytes_of(f"{CONTOSO}.json")
    sessions_baseline = env.bytes_of(f"{CONTOSO}/sessions.json")
    original = json.loads((DEFAULT_TENANT_DIR / f"{CONTOSO}.json").read_bytes())
    assert json.loads(baseline) == original  # same data, only the layout differs

    off = env.run("user.disable", {"upn": JAMIE, "reason": "IR-2901 leaver"}, execute=True)
    assert off.status == "ok" and off.applied is True
    assert env.user(JAMIE)["accountEnabled"] is False and env.bytes_of(f"{CONTOSO}.json") != baseline

    dry = env.run("user.enable", {"upn": JAMIE})
    assert [(c.op, c.before, c.after) for c in dry.diff] == [("replace", False, True)]
    assert env.user(JAMIE)["accountEnabled"] is False  # a dry-run writes nothing

    on = env.run("user.enable", {"upn": JAMIE}, execute=True)
    assert on.status == "ok" and on.applied is True
    assert env.bytes_of(f"{CONTOSO}.json") == baseline
    assert env.bytes_of(f"{CONTOSO}/sessions.json") == sessions_baseline


@needs_pwsh
def test_b29_2_enable_is_idempotent_and_needs_the_requester_verification(env: Env) -> None:
    again = env.run("user.enable", {"upn": ANA}, execute=True)  # already enabled
    assert again.status == "ok" and again.applied is False and again.reason == "no change: already in the desired state"
    off = env.run("user.disable", {"upn": JAMIE, "reason": "IR-2901 leaver"}, execute=True)
    assert off.status == "ok"
    bare = Approval(approver="lead-lee", lever="user.enable", client=CONTOSO, params={"upn": JAMIE})
    denied = env.runner.invoke("user.enable", {"upn": JAMIE}, "tech-ana", CONTOSO, mode="execute", approval=bare)
    assert denied.status == "denied" and env.user(JAMIE)["accountEnabled"] is False


# -- B29-3: set mover properties ----------------------------------------------------------------------------------


def test_b29_3_the_field_param_is_a_closed_enum() -> None:
    spec = Registry.load().get("user.set-properties")
    assert spec is not None
    assert spec.params["field"].enum == ("department", "jobTitle", "manager")
    assert set(spec.params) == {"upn", "field", "value"}


@needs_pwsh
def test_b29_3_dry_run_execute_and_idempotency_for_each_field(env: Env) -> None:
    cases = [
        ("department", "Front Office", "add"),
        ("jobTitle", "Practice Director", "replace"),
        ("manager", SAM, "add"),
    ]
    for field, value, op in cases:
        params = {"upn": ANA, "field": field, "value": value}
        before = env.bytes_of(f"{CONTOSO}.json")
        dry = env.run("user.set-properties", params)
        assert dry.status == "ok" and dry.applied is False and [c.op for c in dry.diff] == [op]
        assert dry.diff[0].path.endswith(f"/{field}") and dry.diff[0].after == value
        assert env.bytes_of(f"{CONTOSO}.json") == before
        done = env.run("user.set-properties", params, execute=True)
        assert done.status == "ok" and done.applied is True and list(done.diff) == list(dry.diff)
        assert env.user(ANA)[field] == value
        repeat = env.run("user.set-properties", params, execute=True)
        assert repeat.status == "ok" and repeat.applied is False and repeat.diff == ()
    after = env.user(ANA)
    original = next(
        u
        for u in json.loads((DEFAULT_TENANT_DIR / f"{CONTOSO}.json").read_bytes())["users"]
        if u["userPrincipalName"] == ANA
    )
    changed = {k for k in set(after) | set(original) if after.get(k) != original.get(k)}
    assert changed == {"department", "jobTitle", "manager"}  # nothing else moved
    assert env.user(SAM) == next(
        u
        for u in json.loads((DEFAULT_TENANT_DIR / f"{CONTOSO}.json").read_bytes())["users"]
        if u["userPrincipalName"] == SAM
    )


@pytest.mark.parametrize("field", ["accountEnabled", "userPrincipalName", "id", "authentication", "Department", ""])
def test_b29_3_any_other_field_is_refused_before_powershell_runs(env: Env, field: str) -> None:
    result = env.run("user.set-properties", {"upn": ANA, "field": field, "value": "x"})
    assert result.status == "denied"
    assert env.bytes_of(f"{CONTOSO}.json") == (DEFAULT_TENANT_DIR / f"{CONTOSO}.json").read_bytes()


@needs_pwsh
def test_b29_3_a_manager_must_be_another_user_of_the_same_client(env: Env) -> None:
    before = env.bytes_of(f"{CONTOSO}.json")
    for value in (MORGAN, ANA):
        result = env.run("user.set-properties", {"upn": ANA, "field": "manager", "value": value})
        assert result.status == "error" and result.applied is False
    assert env.bytes_of(f"{CONTOSO}.json") == before
