"""B-31 LicenseOps: assign and remove from free stock only (specs/B-31.md).

Acceptance ids B31-1 to B31-3. Every test is offline and works on private copies of the synthetic mock tenant in
tmp_path; committed files are never modified. Tests that start `pwsh` skip when PowerShell 7.4+ is not installed.
Run: uv run --frozen pytest tests/py/levers/test_b31_license.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from core.audit import AuditLog
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, Approval, LeverRunner, MockTenant, Registry, RegistryError
from core.levers.handlers import HANDLERS
from workflows.notify.notify import missing_templates

REPO = Path(__file__).resolve().parents[3]
MODULE = REPO / "levers" / "powershell" / "LicenseOps" / "LicenseOps.psd1"
FRAGMENT = REPO / "levers" / "registry.d" / "license.json"
PWSH = shutil.which("pwsh")
needs_pwsh = pytest.mark.skipif(PWSH is None, reason="pwsh (PowerShell 7.4+) is not installed")

CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
PREMIUM, ESSENTIALS = "O365_BUSINESS_PREMIUM", "O365_BUSINESS_ESSENTIALS"
PRIYA = "priya.nair@contosodental.example"  # no Essentials yet; Essentials has 2 free seats
LENA = "lena.fischer@contosodental.example"  # holds Essentials
ANA = "ana.lopez@contosodental.example"  # active user holding Premium; Premium has 0 free seats
PAT = "pat.ellis@contosodental.example"  # departed; Premium retention ended 2026-09-15 (before any real run date)
MO = "mo.reyes@contosodental.example"  # departed; Essentials retention ends 2099-12-31 (synthetic far future)
NO_SEAT = (
    "no free seat: a purchase needs the client's consent (W-VND-02)"  # the exact text in the roadmap's acceptance line
)


@dataclass
class Env:
    runner: LeverRunner
    tenant_dir: Path
    audit_path: Path

    def family_bytes(self, client: str = CONTOSO) -> bytes:
        return (self.tenant_dir / client / "licenses.json").read_bytes()

    def family(self, client: str = CONTOSO) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(self.family_bytes(client))
        return loaded

    def holders(self, sku: str, client: str = CONTOSO) -> set[str]:
        return {a["userPrincipalName"] for a in self.family(client)["assignments"] if a["skuPartNumber"] == sku}


def make_env(tmp_path: Path) -> Env:
    tenant_dir = tmp_path / "tenant"
    shutil.copytree(DEFAULT_TENANT_DIR, tenant_dir)
    audit_path = tmp_path / "audit.jsonl"
    runner = LeverRunner(Registry.load(), IdentityStore.load(), MockTenant(tenant_dir), AuditLog(audit_path))
    return Env(runner, tenant_dir, audit_path)


def dry(env: Env, lever: str, upn: str, sku: str) -> Any:
    return env.runner.invoke(lever, {"upn": upn, "sku": sku}, "triage-bot", CONTOSO)


def execute(env: Env, lever: str, upn: str, sku: str) -> Any:
    params = {"upn": upn, "sku": sku}
    given = Approval(approver="lead-lee", lever=lever, client=CONTOSO, params=params)
    return env.runner.invoke(lever, params, "tech-ana", CONTOSO, mode="execute", approval=given)


def module_call(tenant_dir: Path, function: str, client: str, upn: str, sku: str, as_of: str, whatif: bool) -> Any:
    """Call a LicenseOps function directly with an explicit as-of date; returns its JSON result."""
    assert PWSH is not None
    flag = " -WhatIf" if whatif else ""
    script = (
        f"$env:REDLINE_MOCK_TENANT_DIR = '{tenant_dir}'; Import-Module '{MODULE}' -Force; "
        f"{function} -Upn '{upn}' -Sku '{sku}' -Client '{client}' -AsOf '{as_of}'{flag} "
        "| ConvertTo-Json -Depth 8 -Compress"
    )
    done = subprocess.run(  # noqa: S603 - fixed local pwsh, script text built in this file from constants
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])  # -WhatIf prints a "What if:" line first


# -- the fragment and the fixtures ------------------------------------------------------------------------------


def test_b31_0_both_levers_load_as_powershell_write_levers_with_the_roadmap_risk_classes() -> None:
    registry = Registry.load()
    assert registry.runtime("license.add") == registry.runtime("license.remove") == "powershell"
    add, remove = registry.get("license.add"), registry.get("license.remove")
    assert add is not None and remove is not None
    assert (add.risk_class, remove.risk_class) == ("R1", "R2")
    assert remove.undo == "license.add"
    assert missing_templates(registry) == [], "write lever without workflows/notify/templates/<lever>.md"


@pytest.mark.parametrize("client", [CONTOSO, FABRIKAM])
def test_b31_0_fixtures_are_synthetic_self_labelled_and_name_their_client(client: str) -> None:
    data = json.loads((DEFAULT_TENANT_DIR / client / "licenses.json").read_text(encoding="utf-8"))
    assert data["_meta"]["client"] == client
    assert "Synthetic" in data["_meta"]["note"] and "UNVERIFIED" in data["_meta"]["note"]
    by_id = {s["skuId"]: s for s in data["skus"]}
    for assignment in data["assignments"]:
        assert (
            assignment["skuId"] in by_id and by_id[assignment["skuId"]]["skuPartNumber"] == assignment["skuPartNumber"]
        )
    for sku in data["skus"]:
        used = sum(1 for a in data["assignments"] if a["skuId"] == sku["skuId"])
        assert used <= sku["prepaidUnits"]["enabled"], f"{sku['skuPartNumber']} uses more seats than it owns"


# -- B31-1: license.add only from a free seat ------------------------------------------------------------------


@needs_pwsh
def test_b31_1_add_dry_run_with_a_free_seat_proposes_the_assignment_and_writes_nothing(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    before = env.family_bytes()
    result = dry(env, "license.add", PRIYA, ESSENTIALS)
    assert result.status == "ok", result.reason
    assert [(c.op, c.path) for c in result.diff] == [("add", f"/licenses/{PRIYA}/{ESSENTIALS}")]
    assert result.diff[0].after["skuPartNumber"] == ESSENTIALS
    assert result.data["outcome"] == "assign" and result.data["seatsFree"] == 1
    assert env.family_bytes() == before


@needs_pwsh
def test_b31_1_add_with_no_free_seat_says_a_purchase_needs_consent_and_proposes_nothing(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    before = env.family_bytes()
    result = dry(env, "license.add", LENA, PREMIUM)
    assert result.status == "ok"
    assert result.diff == ()
    assert result.data["outcome"] == "refused"
    assert result.data["message"] == NO_SEAT
    assert result.data["seatsFree"] == 0
    # An approved execute of the same call applies nothing either.
    done = execute(env, "license.add", LENA, PREMIUM)
    assert done.diff == () and done.data["message"] == NO_SEAT
    assert env.family_bytes() == before


@needs_pwsh
def test_b31_1_execute_assigns_once_the_second_run_is_empty_and_the_pool_runs_dry(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    first = execute(env, "license.add", PRIYA, ESSENTIALS)
    assert first.status == "ok" and first.audit_seq is not None and len(first.diff) == 1
    assert PRIYA in env.holders(ESSENTIALS)
    again = execute(env, "license.add", PRIYA, ESSENTIALS)
    assert again.status == "ok" and again.diff == () and again.reason == "no change: already in the desired state"
    assert len(env.holders(ESSENTIALS)) == 3
    # Essentials owns 4 seats: one more person fits (the 4th), then the pool is empty.
    assert execute(env, "license.add", ANA, ESSENTIALS).status == "ok"
    refused = execute(env, "license.add", "sam.patel@contosodental.example", ESSENTIALS)
    assert refused.diff == () and refused.data["message"] == NO_SEAT
    assert len(env.holders(ESSENTIALS)) == 4


@needs_pwsh
def test_b31_1_add_refuses_an_unknown_user_sku_or_another_clients_user_without_changing_anything(
    tmp_path: Path,
) -> None:
    env = make_env(tmp_path)
    before = env.family_bytes()
    for upn, sku, message in (
        ("nobody@contosodental.example", ESSENTIALS, "no such user for this client"),
        ("morgan.reyes@fabrikamcapital.example", ESSENTIALS, "no such user for this client"),
        (PRIYA, "NO_SUCH_SKU", "no such SKU NO_SUCH_SKU for this client"),
    ):
        result = execute(env, "license.add", upn, sku)
        assert result.diff == () and result.data["message"] == message
    assert env.family_bytes() == before


def test_b31_1_an_agent_cannot_execute_and_a_missing_approval_is_denied(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    before = env.family_bytes()
    params = {"upn": PRIYA, "sku": ESSENTIALS}
    assert env.runner.invoke("license.add", params, "triage-bot", CONTOSO, mode="execute").status == "denied"
    assert env.runner.invoke("license.add", params, "tech-ana", CONTOSO, mode="execute").status == "denied"
    assert env.family_bytes() == before


# -- B31-2: license.remove only after the retention window -----------------------------------------------------


@needs_pwsh
def test_b31_2_remove_after_the_window_shows_the_sku_and_the_date_the_window_ended(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    before = env.family_bytes()
    result = dry(env, "license.remove", PAT, PREMIUM)
    assert result.status == "ok", result.reason
    assert [(c.op, c.path) for c in result.diff] == [("remove", f"/licenses/{PAT}/{PREMIUM}")]
    assert result.diff[0].before["skuPartNumber"] == PREMIUM
    assert result.diff[0].before["retentionEndsOn"] == "2026-09-15"
    assert "2026-09-15" in result.data["message"] and PREMIUM in result.data["message"]
    assert env.family_bytes() == before


@needs_pwsh
def test_b31_2_remove_executes_frees_the_seat_and_is_convergent(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    done = execute(env, "license.remove", PAT, PREMIUM)
    assert done.status == "ok" and done.audit_seq is not None and len(done.diff) == 1
    assert PAT not in env.holders(PREMIUM)
    assert len(env.holders(PREMIUM)) == 5
    again = execute(env, "license.remove", PAT, PREMIUM)
    assert again.diff == () and again.reason == "no change: already in the desired state"
    # The freed seat can now be assigned: removal and add work together, and still nothing was bought.
    assert execute(env, "license.add", LENA, PREMIUM).status == "ok"


@needs_pwsh
def test_b31_2_remove_refuses_while_the_window_is_open_or_when_none_is_recorded(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    before = env.family_bytes()
    open_window = execute(env, "license.remove", MO, ESSENTIALS)
    assert open_window.diff == () and open_window.data["outcome"] == "refused"
    assert "2099-12-31" in open_window.data["message"] and "not over" in open_window.data["message"]
    active = execute(env, "license.remove", ANA, PREMIUM)
    assert active.diff == () and "no retention window is recorded" in active.data["message"]
    assert env.family_bytes() == before


@needs_pwsh
def test_b31_2_the_window_ends_on_its_last_day_and_removal_is_allowed_the_day_after(tmp_path: Path) -> None:
    work = tmp_path / "tenant"
    shutil.copytree(DEFAULT_TENANT_DIR, work)
    args = (work, "Remove-LicenseAssignment", CONTOSO, PAT, PREMIUM)
    last_day = module_call(*args, as_of="2026-09-15", whatif=True)
    assert last_day["diff"] == [] and last_day["data"]["outcome"] == "refused"
    day_after = module_call(*args, as_of="2026-09-16", whatif=True)
    assert day_after["data"]["outcome"] == "remove" and day_after["applied"] is False
    assert day_after["diff"][0]["before"]["retentionEndsOn"] == "2026-09-15"
    assert PAT in (work / CONTOSO / "licenses.json").read_text(encoding="utf-8")  # -WhatIf wrote nothing


@needs_pwsh
def test_b31_2_one_client_never_sees_anothers_licenses(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    before = env.family_bytes(FABRIKAM)
    quinn = "quinn.ford@fabrikamcapital.example"
    # Quinn's window ended 2026-10-01 at Fabrikam; Contoso has no such assignment, so nothing is found or changed.
    result = execute(env, "license.remove", quinn, PREMIUM)
    assert result.diff == () and "does not hold" in result.data["message"]
    assert env.family_bytes(FABRIKAM) == before


# -- B31-3: no purchase lever can load ----------------------------------------------------------------------


def _fragment_with_lever_named(name: str, tmp_path: Path) -> Path:
    raw = json.loads(FRAGMENT.read_text(encoding="utf-8"))
    lever = {k: v for k, v in raw["levers"][0].items() if k not in ("runtime", "entry")}
    lever["name"] = name
    folder = tmp_path / "registry.d"
    folder.mkdir()
    (folder / "x.json").write_text(json.dumps({"version": 1, "levers": [lever]}), encoding="utf-8")
    return folder


@pytest.mark.parametrize(
    "name",
    [
        "license.purchase",
        "license.purchase-seats",
        "license.order",
        "license.buy",
        "license.buy-seats",
        "license.subscribe",
        "license.add-seats",
        "license.increase",
        "license.reduce",
        "license.cancel",
    ],
)
def test_b31_3_a_purchase_or_similar_lever_cannot_load(name: str, tmp_path: Path) -> None:
    folder = _fragment_with_lever_named(name, tmp_path)
    with pytest.raises(RegistryError, match="never automated"):
        Registry.load(handlers={**HANDLERS, name: HANDLERS["ticket.get"]}, fragments_dir=folder)


def test_b31_3_the_live_registry_has_no_purchase_lever_and_the_module_has_no_purchase_function() -> None:
    names = set(Registry.load().names())
    assert {"license.add", "license.remove"} <= names
    assert not [n for n in names if n.startswith("license.") and n not in ("license.add", "license.remove")]
    exported = MODULE.read_text(encoding="utf-8")
    assert "Add-LicenseAssignment" in exported and "Remove-LicenseAssignment" in exported
    for word in ("Purchase", "Buy", "Order", "Subscribe"):
        assert word not in exported, f"the manifest names a {word} function"
