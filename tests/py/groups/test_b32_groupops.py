"""B-32 GroupOps: group.add-member and group.remove-member (specs/B-32.md).

Acceptance ids B32-1 to B32-3. Offline: every test works on a private copy of the synthetic mock tenant in tmp_path.
Tests that start `pwsh` skip when PowerShell 7.4+ is not installed.
Run: uv run --frozen pytest tests/py/groups/test_b32_groupops.py
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from core.audit import AuditLog, verify_chain
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, Approval, LeverRunner, MockTenant, Registry
from workflows.notify import missing_templates

CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
TOM = "tom.baker@contosodental.example"  # in All Staff only
PRIYA = "priya.nair@contosodental.example"  # in no group
MORGAN = "morgan.reyes@fabrikamcapital.example"
G_FRONT_DESK = "c1000000-0000-4000-8000-000000000001"  # data access
G_ALL_STAFF = "c1000000-0000-4000-8000-000000000003"  # distribution only
G_ROLE = "c1000000-0000-4000-8000-000000000004"  # isAssignableToRole
G_LISTED = "c1000000-0000-4000-8000-000000000005"  # on the client's privileged list by name
G_FAB_PRIV = "f1000000-0000-4000-8000-000000000003"
ADD, REMOVE = "group.add-member", "group.remove-member"
needs_pwsh = pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh (PowerShell 7.4+) is not installed")


@dataclass
class Env:
    runner: LeverRunner
    tenant_dir: Path
    audit_path: Path

    def groups_file(self, client: str = CONTOSO) -> Path:
        return self.tenant_dir / client / "groups.json"

    def groups(self, client: str = CONTOSO) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(self.groups_file(client).read_text(encoding="utf-8"))
        return loaded

    def members(self, group_id: str, client: str = CONTOSO) -> list[str]:
        for group in self.groups(client)["value"]:
            if group["id"] == group_id:
                return [m["userPrincipalName"] for m in group["members"]]
        raise AssertionError(group_id)

    def records(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines()]

    def tree(self) -> dict[str, bytes]:
        return {str(p.relative_to(self.tenant_dir)): p.read_bytes() for p in sorted(self.tenant_dir.rglob("*.json"))}


@pytest.fixture
def env(tmp_path: Path) -> Env:
    tenant_dir = tmp_path / "tenant"
    shutil.copytree(DEFAULT_TENANT_DIR, tenant_dir)
    audit_path = tmp_path / "audit.jsonl"
    runner = LeverRunner(Registry.load(), IdentityStore.load(), MockTenant(tenant_dir), AuditLog(audit_path))
    return Env(runner, tenant_dir, audit_path)


def params(upn: str, group_id: str) -> dict[str, str]:
    return {"upn": upn, "group_id": group_id}


def dry(env: Env, lever: str, upn: str, group_id: str, who: str = "triage-bot", client: str = CONTOSO) -> Any:
    return env.runner.invoke(lever, params(upn, group_id), who, client)


def execute(env: Env, lever: str, upn: str, group_id: str, client: str = CONTOSO, tech: str = "tech-ana") -> Any:
    p = params(upn, group_id)
    approval = Approval(approver="lead-lee", lever=lever, client=client, params=p)
    return env.runner.invoke(lever, p, tech, client, mode="execute", approval=approval)


# -- B32-1: two write levers; risk class from the group attribute ----------------------------------------------


def test_b32_1_both_levers_are_registered_powershell_write_levers_with_lead_approval() -> None:
    registry = Registry.load()
    for name in (ADD, REMOVE):
        spec = registry.get(name)
        assert spec.lever_class == "write" and spec.approval == "lead" and spec.dry_run
        assert registry.runtime(name) == "powershell"
        assert spec.impact is not None and set(spec.impact.model_dump()) == {"L1", "L2", "L3", "L4"}
    assert Registry.load().get(ADD).risk_class == "R2"  # the stricter of the two; R1 per call is in the data


def test_b32_1_each_lever_has_a_notice_template() -> None:
    assert not {ADD, REMOVE} & set(missing_templates(Registry.load()))


@needs_pwsh
def test_b32_1_a_data_access_group_is_r2(env: Env) -> None:
    result = dry(env, ADD, PRIYA, G_FRONT_DESK)
    assert result.status == "ok", result.reason
    assert result.data["riskClass"] == "R2" and result.data["accessClass"] == "data"


@needs_pwsh
def test_b32_1_a_distribution_only_group_is_r1(env: Env) -> None:
    result = dry(env, ADD, PRIYA, G_ALL_STAFF)
    assert result.status == "ok", result.reason
    assert result.data["riskClass"] == "R1" and result.data["accessClass"] == "distribution"


@needs_pwsh
def test_b32_1_dry_run_shows_the_diff_and_changes_nothing(env: Env) -> None:
    before = env.tree()
    result = dry(env, ADD, PRIYA, G_FRONT_DESK)
    assert [(c.op, c.path) for c in result.diff] == [
        ("add", f"/groups/{G_FRONT_DESK}/members/afbbebce-68b5-530e-b8f7-49957cbac346")
    ]
    assert not result.applied and env.tree() == before


@needs_pwsh
def test_b32_1_execute_adds_the_member_with_an_approval_and_an_audit_record(env: Env) -> None:
    result = execute(env, ADD, PRIYA, G_FRONT_DESK)
    assert result.status == "ok" and result.applied, result.reason
    assert PRIYA in env.members(G_FRONT_DESK)
    last = env.records()[-1]
    assert last["lever"] == ADD and last["mode"] == "execute" and last["approver"] == "lead-lee"
    assert last["result"]["applied"] is True
    assert verify_chain(env.audit_path, env.audit_path.with_name("audit.jsonl.head")).ok


@needs_pwsh
def test_b32_1_execute_without_an_approval_is_denied_and_changes_nothing(env: Env) -> None:
    before = env.tree()
    result = env.runner.invoke(ADD, params(PRIYA, G_FRONT_DESK), "tech-ana", CONTOSO, mode="execute")
    assert result.status == "denied" and env.tree() == before


# -- B32-2: privileged groups are refused, with the W-IDM-07 reason --------------------------------------------


@needs_pwsh
@pytest.mark.parametrize("group_id", [G_ROLE, G_LISTED])
def test_b32_2_a_privileged_group_is_refused_in_dry_run_with_the_w_idm_07_reason(env: Env, group_id: str) -> None:
    before = env.tree()
    result = dry(env, ADD, PRIYA, group_id)
    assert result.status == "denied" and not result.applied and not result.diff
    assert "W-IDM-07" in result.reason and "never by automation" in result.reason
    assert env.tree() == before
    last = env.records()[-1]
    assert last["mode"] == "dry-run" and last["result"]["status"] == "denied" and "W-IDM-07" in last["result"]["reason"]


@needs_pwsh
def test_b32_2_the_reason_names_which_rule_fired(env: Env) -> None:
    assert "directory role" in dry(env, ADD, PRIYA, G_ROLE).reason
    assert "privileged group list" in dry(env, ADD, PRIYA, G_LISTED).reason


@needs_pwsh
@pytest.mark.parametrize("lever", [ADD, REMOVE])
def test_b32_2_execute_with_a_valid_approval_is_still_refused_for_a_privileged_group(env: Env, lever: str) -> None:
    before = env.tree()
    result = execute(env, lever, PRIYA, G_ROLE)
    assert result.status == "denied" and "W-IDM-07" in result.reason and not result.applied
    assert env.tree() == before


@needs_pwsh
def test_b32_2_the_clients_list_is_matched_by_name_regardless_of_case(env: Env) -> None:
    data = env.groups()
    data["redlinePrivilegedGroups"] = ["front DESK staff"]
    env.groups_file().write_text(json.dumps(data), encoding="utf-8")
    assert "W-IDM-07" in dry(env, ADD, PRIYA, G_FRONT_DESK).reason


@needs_pwsh
def test_b32_2_a_group_or_user_of_another_client_answers_like_an_absent_one(env: Env) -> None:
    before = env.tree()
    other_group = dry(env, ADD, PRIYA, G_FAB_PRIV, who="tech-ana")
    assert other_group.status == "denied" and "No group" in other_group.reason and "W-IDM-07" not in other_group.reason
    other_user = dry(env, ADD, MORGAN, G_FRONT_DESK)
    assert other_user.status == "denied" and "No user" in other_user.reason
    assert env.tree() == before


def test_b32_2_a_bad_group_id_is_rejected_before_powershell_runs(env: Env) -> None:
    result = dry(env, ADD, PRIYA, "..\\..\\x")
    assert result.status == "denied" and not result.applied


# -- B32-3: idempotent, and each is the other's undo --------------------------------------------------------------


@needs_pwsh
def test_b32_3_add_twice_second_run_is_an_empty_diff(env: Env) -> None:
    assert execute(env, ADD, PRIYA, G_FRONT_DESK).applied
    again = execute(env, ADD, PRIYA, G_FRONT_DESK)
    assert again.status == "ok" and not again.applied and not again.diff
    assert again.reason == "no change: already in the desired state"
    assert env.members(G_FRONT_DESK).count(PRIYA) == 1
    assert env.records()[-1]["result"]["idempotency"] == f"{ADD}/{CONTOSO}/upn={PRIYA}/group_id={G_FRONT_DESK}"


@needs_pwsh
def test_b32_3_remove_twice_second_run_is_an_empty_diff(env: Env) -> None:
    assert execute(env, REMOVE, TOM, G_ALL_STAFF).applied
    again = execute(env, REMOVE, TOM, G_ALL_STAFF)
    assert again.status == "ok" and not again.applied and not again.diff
    assert TOM not in env.members(G_ALL_STAFF)


@needs_pwsh
def test_b32_3_remove_undoes_add_and_add_undoes_remove(env: Env) -> None:
    start = env.groups()
    assert execute(env, ADD, PRIYA, G_FRONT_DESK).applied
    assert env.groups() != start
    assert execute(env, REMOVE, PRIYA, G_FRONT_DESK).applied
    assert env.groups() == start
    assert execute(env, REMOVE, TOM, G_ALL_STAFF).applied
    assert execute(env, ADD, TOM, G_ALL_STAFF).applied
    assert sorted(env.members(G_ALL_STAFF)) == sorted(
        start["value"][2]["members"][i]["userPrincipalName"] for i in range(3)
    )


def test_b32_3_the_registry_names_each_as_the_others_undo() -> None:
    registry = Registry.load()
    assert registry.get(ADD).undo == REMOVE and registry.get(REMOVE).undo == ADD


@needs_pwsh
def test_b32_3_a_change_in_one_client_does_not_touch_the_other(env: Env) -> None:
    other = (env.tenant_dir / FABRIKAM / "groups.json").read_bytes()
    assert execute(env, ADD, PRIYA, G_FRONT_DESK).applied
    assert (env.tenant_dir / FABRIKAM / "groups.json").read_bytes() == other


# -- fixtures --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("client", [CONTOSO, FABRIKAM])
def test_b32_fixture_groups_are_synthetic_and_belong_to_their_client(client: str) -> None:
    data = json.loads((DEFAULT_TENANT_DIR / client / "groups.json").read_text(encoding="utf-8"))
    assert data["_meta"]["client"] == client and "Synthetic" in data["_meta"]["note"]
    users = {
        u["userPrincipalName"] for u in json.loads((DEFAULT_TENANT_DIR / f"{client}.json").read_text("utf-8"))["users"]
    }
    classes = {g["redlineAccessClass"] for g in data["value"]}
    assert classes == {"data", "distribution"}
    assert any(g["isAssignableToRole"] for g in data["value"]) and data["redlinePrivilegedGroups"]
    for group in data["value"]:
        assert {m["userPrincipalName"] for m in group["members"]} <= users
