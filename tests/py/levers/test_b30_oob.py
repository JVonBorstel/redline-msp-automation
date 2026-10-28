"""B-30 password reset and Temporary Access Pass with out-of-band delivery (specs/B-30.md).

Acceptance ids B30-1 to B30-4. Every test is offline and works on private copies under tmp_path: the synthetic mock
tenant, the audit log, the proposal queue and the out-of-band folder (REDLINE_OOB_DIR). Committed files are never
modified. Tests that start `pwsh` skip when PowerShell 7.4+ is not installed; the Python side (oob.py, registry,
templates) runs everywhere. The generated values are random; tests read them from the out-of-band file and never
print them.
Run: uv run --frozen pytest tests/py/levers/test_b30_oob.py
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from core.audit import AuditLog, verify_chain
from core.identity import Identity, IdentityStore, Role
from core.levers import DEFAULT_TENANT_DIR, Approval, InvokeResult, LeverRunner, MockTenant, Registry
from core.levers.bridge import PowerShellBridge, parse_entry
from core.levers.models import ContactConfirmation, Verification
from core.levers.oob import (
    OobError,
    delivery_path,
    find_secret_shapes,
    oob_root,
    read_delivery,
    scan_for_value,
)
from core.levers.runner import RunnerPolicy
from core.queue import Proposal, open_queue
from workflows.notify import TEMPLATES_DIR, draft_notice, load_contacts, missing_templates

PWSH = shutil.which("pwsh")
needs_pwsh = pytest.mark.skipif(PWSH is None, reason="pwsh (PowerShell 7.4+) is not installed")
CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
ANA = "ana.lopez@contosodental.example"
JAMIE = "jamie.chen@contosodental.example"
NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
CONTACT = "contact-office-manager"
RESET, TAP = "user.reset-password", "user.new-tap"
CALLBACK = Verification(method="callback-on-file", by="lead-lee", at=NOW, ref="number-on-file:psa-contact")
CONFIRMED = ContactConfirmation(by="tech-ana", at=NOW, contact=CONTACT)
OOB_DATA_KEYS = {"target_id", "credential_type", "expiry_minutes", "delivery"}


def ident(id_: str, role: Role, *clients: str) -> Identity:
    return Identity(id=id_, display_name=f"{id_} (synthetic)", role=role, clients=clients)


IDENTITIES = IdentityStore(
    [
        ident("tech-ana", Role.TECHNICIAN, CONTOSO),
        ident("tech-cy", Role.TECHNICIAN, CONTOSO),
        ident("tech-ben", Role.TECHNICIAN, FABRIKAM),
        ident("lead-lee", Role.LEAD, CONTOSO, FABRIKAM),
        ident("lead-fay", Role.LEAD, CONTOSO),
        ident("triage-bot", Role.AGENT, CONTOSO, FABRIKAM),
    ]
)


@dataclass
class Env:
    runner: LeverRunner
    tenant_dir: Path
    audit_path: Path
    oob_dir: Path
    queue_dir: Path

    def records(self) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        return [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines()]

    def tenant(self, client: str = CONTOSO) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads((self.tenant_dir / f"{client}.json").read_text(encoding="utf-8"))
        return loaded

    def write_tenant(self, data: dict[str, Any], client: str = CONTOSO) -> None:
        (self.tenant_dir / f"{client}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def user(self, upn: str = ANA) -> dict[str, Any]:
        return next(u for u in self.tenant()["users"] if u["userPrincipalName"] == upn)

    def oob_file(self, upn: str, kind: str) -> Path:
        return delivery_path(CONTOSO, self.user(upn)["id"], kind, self.oob_dir)

    def secret(self, upn: str, kind: str) -> str:
        """Peek at the issued value for a test (the file is left in place)."""
        record = json.loads(self.oob_file(upn, kind).read_text(encoding="utf-8"))
        value: str = record["value"]
        return value

    def approvals(self, lever: str, upn: str = ANA, **kw: Any) -> list[Approval]:
        params = {"upn": upn}
        fields: dict[str, Any] = {"verification": CALLBACK, "contact_verification": CONFIRMED}
        fields.update(kw)
        first = Approval(approver="lead-lee", lever=lever, client=CONTOSO, params=params, demo=True, **fields)
        second = Approval(approver="lead-fay", lever=lever, client=CONTOSO, params=params, demo=True)
        return [first, second]

    def run(
        self, lever: str, upn: str = ANA, who: str = "tech-ana", approvals: list[Approval] | None = None
    ) -> InvokeResult:
        given = self.approvals(lever, upn) if approvals is None else approvals
        return self.runner.invoke(lever, {"upn": upn}, who, CONTOSO, mode="execute", approval=given)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    tenant_dir = tmp_path / "tenant"
    shutil.copytree(DEFAULT_TENANT_DIR, tenant_dir)
    oob_dir = tmp_path / "oob"
    monkeypatch.setenv("REDLINE_OOB_DIR", str(oob_dir))
    audit_path = tmp_path / "audit.jsonl"
    policy = RunnerPolicy(demo=True, client_records={CONTOSO: {"authorized_contacts": [CONTACT]}})
    runner = LeverRunner(
        Registry.load(),
        IDENTITIES,
        MockTenant(tenant_dir),
        AuditLog(audit_path),
        policy=policy,
        clock=lambda: NOW,
    )
    return Env(runner, tenant_dir, audit_path, oob_dir, tmp_path / "queue")


# -- B30-1 R3, verification, value only out of band -----------------------------------------------------


@pytest.mark.parametrize("name", [RESET, TAP])
def test_b30_1_both_levers_are_registered_r3_write_levers_that_need_verification(name: str) -> None:
    spec = Registry.load().get(name)
    assert spec is not None
    assert spec.risk_class == "R3" and spec.lever_class == "write" and spec.approval == "lead"
    assert Registry.load().powershell_entry(name) is not None
    assert spec.verification == "requester+contact"
    assert spec.dry_run is True


@needs_pwsh
@pytest.mark.parametrize("name", [RESET, TAP])
def test_b30_1_without_the_callback_and_contact_records_nothing_is_issued(env: Env, name: str) -> None:
    no_records = [
        Approval(approver=a, lever=name, client=CONTOSO, params={"upn": ANA}, demo=True)
        for a in ("lead-lee", "lead-fay")
    ]
    result = env.run(name, approvals=no_records)
    assert result.status == "denied"
    assert not env.oob_dir.exists() or not any(env.oob_dir.rglob("*.json"))
    assert "pendingCredentials" not in env.user() and env.tenant() == json.loads(
        (DEFAULT_TENANT_DIR / f"{CONTOSO}.json").read_text(encoding="utf-8")
    )


@needs_pwsh
@pytest.mark.parametrize("name", [RESET, TAP])
def test_b30_1_one_approver_is_not_enough_for_r3(env: Env, name: str) -> None:
    result = env.run(name, approvals=env.approvals(name)[:1])
    assert result.status == "denied" and "distinct leads" in result.reason
    assert not env.oob_dir.exists() or not any(env.oob_dir.rglob("*.json"))


@needs_pwsh
@pytest.mark.parametrize("name,kind", [(RESET, "password"), (TAP, "tap")])
def test_b30_1_the_value_goes_only_to_the_out_of_band_file(env: Env, name: str, kind: str) -> None:
    result = env.run(name)
    assert result.ok and result.applied, result.reason
    value = env.secret(ANA, kind)
    assert len(value) >= 8
    dumped = result.model_dump_json()
    assert scan_for_value([dumped, json.dumps(env.tenant()), env.audit_path.read_text(encoding="utf-8")], value) == 0
    assert "value" not in json.dumps(result.data) and "value" not in json.dumps([c.model_dump() for c in result.diff])


@needs_pwsh
def test_b30_1_a_dry_run_issues_nothing(env: Env) -> None:
    before = (env.tenant_dir / f"{CONTOSO}.json").read_bytes()
    result = env.runner.invoke(RESET, {"upn": ANA}, "triage-bot", CONTOSO, mode="dry-run")
    assert result.ok and not result.applied and result.diff
    assert (env.tenant_dir / f"{CONTOSO}.json").read_bytes() == before
    assert not env.oob_dir.exists() or not any(env.oob_dir.rglob("*.json"))


@needs_pwsh
def test_b30_1_the_requesting_technician_reads_it_once_and_nobody_else_can(env: Env) -> None:
    assert env.run(RESET).applied
    target = env.user()["id"]
    ben, cy, bot, lee = (IDENTITIES.get(i) for i in ("tech-ben", "tech-cy", "triage-bot", "lead-lee"))
    for outsider in (ben, bot):
        with pytest.raises(OobError):
            read_delivery(outsider, CONTOSO, target, "password", root=env.oob_dir, now=NOW)
    with pytest.raises(OobError, match="only the technician who requested"):
        read_delivery(cy, CONTOSO, target, "password", requester="tech-ana", root=env.oob_dir, now=NOW)
    assert env.oob_file(ANA, "password").is_file()  # refusals left it alone
    expected = env.secret(ANA, "password")
    ana = IDENTITIES.get("tech-ana")
    got = read_delivery(ana, CONTOSO, target, "password", requester="tech-ana", root=env.oob_dir, now=datetime.now(UTC))
    assert got == expected and lee is not None
    with pytest.raises(OobError):  # single-use: the read removed it
        read_delivery(ana, CONTOSO, target, "password", root=env.oob_dir, now=datetime.now(UTC))


def test_b30_1_an_expired_or_malformed_delivery_is_refused_and_a_path_cannot_escape(tmp_path: Path) -> None:
    ana = IDENTITIES.get("tech-ana")
    path = delivery_path(CONTOSO, "abc-123", "tap", tmp_path)
    path.parent.mkdir(parents=True)
    record = {"client": CONTOSO, "target_id": "abc-123", "type": "tap", "single_use": True, "value": "Zq7Kp3Wm"}
    path.write_text(json.dumps({**record, "expires_at": (NOW - timedelta(minutes=1)).isoformat()}), encoding="utf-8")
    with pytest.raises(OobError, match="expired"):
        read_delivery(ana, CONTOSO, "abc-123", "tap", root=tmp_path, now=NOW)
    assert not path.exists()
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(OobError, match="malformed"):
        read_delivery(ana, CONTOSO, "abc-123", "tap", root=tmp_path, now=NOW)
    for bad in ("../x", "a/b", "", "a" * 65):
        with pytest.raises(OobError):
            delivery_path(CONTOSO, bad, "tap", tmp_path)
    with pytest.raises(OobError):
        delivery_path("../contoso", "abc", "tap", tmp_path)
    with pytest.raises(OobError):
        delivery_path(CONTOSO, "abc", "pin", tmp_path)


def test_b30_1_the_default_root_is_the_git_ignored_tmp_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDLINE_OOB_DIR", raising=False)
    assert oob_root().parts[-2:] == (".tmp", "oob")


# -- B30-2 sweep ----------------------------------------------------------------------------------------


@needs_pwsh
def test_b30_2_sweep_finds_no_secret_in_audit_proposal_result_notice_or_log(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    results = [
        env.run(RESET),
        env.run(TAP),
        env.run(RESET, JAMIE, approvals=env.approvals(RESET, JAMIE)),
        env.run(TAP, JAMIE, approvals=env.approvals(TAP, JAMIE)),
    ]
    assert all(r.ok and r.applied for r in results), [r.reason for r in results]
    secrets = [env.secret(u, k) for u in (ANA, JAMIE) for k in ("password", "tap")]
    assert len(set(secrets)) == 4

    queue = open_queue(env.queue_dir)
    texts = [r.model_dump_json() for r in results]
    for lever, upn in ((RESET, ANA), (TAP, JAMIE)):
        proposal = Proposal.new(
            source="triage",
            ref="T-3101",
            lever=lever,
            client=CONTOSO,
            params={"upn": upn},
            requested_by="tech-ana",
            reason=f"{lever} for a locked-out user",
        )
        queue.add(proposal)
        executed = proposal.model_copy(
            update={"status": "executed", "decided_by": "lead-lee", "decided_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ")}
        )
        texts.append(
            draft_notice(
                executed,
                registry=Registry.load(),
                identities=IDENTITIES,
                tenant=MockTenant(env.tenant_dir),
                contacts=load_contacts(),
            ).text
        )
    texts.append(queue.path.read_text(encoding="utf-8"))
    texts.append(env.audit_path.read_text(encoding="utf-8"))
    texts.extend(p.read_text(encoding="utf-8") for p in env.tenant_dir.rglob("*.json"))
    texts.append(caplog.text)
    texts.append(json.dumps([r.model_dump(mode="json") for r in results]))
    texts.extend(json.dumps(rec) for rec in env.records())

    for secret in secrets:
        assert scan_for_value(texts, secret) == 0
    for text in texts:
        cleaned = re.sub(r"[0-9a-f]{64}", "", text)
        assert find_secret_shapes(cleaned) == []  # audit chain hashes are not secrets
    # the out-of-band files are the one place the values live
    for upn, kind in ((ANA, "password"), (ANA, "tap"), (JAMIE, "password"), (JAMIE, "tap")):
        assert env.oob_file(upn, kind).is_file()


def test_b30_2_the_shape_finder_catches_the_shapes_it_claims_to() -> None:
    assert find_secret_shapes("Authorization: Bearer abcdefghijklmnop1234") == ["bearer"]
    assert "jwt" in find_secret_shapes("eyJhbGciOiJSUzI1NiJ9." + "abcdefghijk" + ".sig1234")
    assert find_secret_shapes("a plain sentence about a reset and a pass") == []


# -- B30-3 audit records that a credential was issued, nothing more ------------------------------------


@needs_pwsh
@pytest.mark.parametrize("name,kind,minutes", [(RESET, "password", 60), (TAP, "tap", 10)])
def test_b30_3_the_audit_holds_type_expiry_and_target_id_only(env: Env, name: str, kind: str, minutes: int) -> None:
    first = env.run(name)
    assert first.applied
    applied = [r for r in env.records() if r["lever"] == name and r["result"].get("applied") is True]
    assert len(applied) == 1
    target = env.user()["id"]
    markers = [c for c in applied[0]["result"]["changes"] if c["path"] == f"/users/{target}/pendingCredentials/{kind}"]
    assert len(markers) == 1, "the audit names the target id and the credential type in the marker's path"
    assert markers[0]["after"] == {"type": kind, "singleUse": True, "expiryMinutes": minutes}
    # nothing else about the credential: no value, no oob location, no delivery detail anywhere in the record
    text = json.dumps(applied[0])
    assert env.secret(ANA, kind) not in text and str(env.oob_dir) not in text and "out-of-band" not in text
    assert set(first.data) == OOB_DATA_KEYS and first.data == {
        "target_id": target,
        "credential_type": kind,
        "expiry_minutes": minutes,
        "delivery": "out-of-band",
    }
    assert verify_chain(env.audit_path, env.audit_path.with_name("audit.jsonl.head")).ok
    # the OOB record carries the same expiry as an absolute time
    record = json.loads(env.oob_file(ANA, kind).read_text(encoding="utf-8"))
    issued, expires = (datetime.fromisoformat(record[k]) for k in ("issued_at", "expires_at"))
    assert expires - issued == timedelta(minutes=minutes)


@needs_pwsh
def test_b30_3_a_second_issue_while_one_is_pending_changes_nothing(env: Env) -> None:
    bridge = PowerShellBridge(tenant_dir=env.tenant_dir)
    entry = parse_entry("CredentialOps\\New-UserTap")

    def call() -> Any:
        return bridge.call(
            lever=TAP,
            lever_version=1,
            client=CONTOSO,
            mode="execute",
            params={"upn": ANA},
            entry=entry,
            timeout_s=15,
            request_id="req-b30-3-0001",
        )

    first = call()
    assert first.ok and first.applied
    file = env.oob_file(ANA, "tap")
    stamp = file.read_bytes()
    second = call()
    assert second.ok and not second.applied and not second.diff
    assert file.read_bytes() == stamp


# -- B30-4 declared verification, privileged refusal, single-use shortest lifetime ---------------------


@needs_pwsh
@pytest.mark.parametrize("name", [RESET, TAP])
def test_b30_4_a_privileged_account_is_refused_by_the_runner(env: Env, name: str) -> None:
    data = env.tenant()
    data["directoryRoles"] = [{"displayName": "Helpdesk Administrator", "members": [{"userPrincipalName": ANA}]}]
    env.write_tenant(data)
    result = env.run(name)
    assert result.status == "denied" and "privileged" in result.reason
    assert not env.oob_dir.exists() or not any(env.oob_dir.rglob("*.json"))


@needs_pwsh
@pytest.mark.parametrize("function", ["Reset-UserPassword", "New-UserTap"])
def test_b30_4_the_module_refuses_a_privileged_account_even_if_called_directly(env: Env, function: str) -> None:
    data = env.tenant()
    data["directoryRoles"] = [{"displayName": "Global Administrator", "members": [{"userPrincipalName": JAMIE}]}]
    env.write_tenant(data)
    result = PowerShellBridge(tenant_dir=env.tenant_dir).call(
        lever="user.x",
        lever_version=1,
        client=CONTOSO,
        mode="execute",
        params={"upn": JAMIE},
        entry=parse_entry(f"CredentialOps\\{function}"),
        timeout_s=15,
        request_id="req-b30-4-0001",
    )
    assert result.status == "error" and "crashed" in result.reason
    assert not env.oob_dir.exists() or not any(env.oob_dir.rglob("*.json"))


@needs_pwsh
def test_b30_4_a_tap_is_single_use_with_the_default_shortest_lifetime(env: Env) -> None:
    assert env.run(TAP).applied
    methods = [
        m
        for m in env.user()["authentication"]["methods"]
        if m["@odata.type"].endswith("temporaryAccessPassAuthenticationMethod")
    ]
    assert len(methods) == 1
    assert methods[0]["isUsableOnce"] is True and methods[0]["lifetimeInMinutes"] == 10
    assert set(methods[0]) == {"@odata.type", "id", "isUsableOnce", "lifetimeInMinutes"}


@needs_pwsh
def test_b30_4_a_tap_follows_the_tenant_policy_minimum(env: Env) -> None:
    data = env.tenant()
    data["authenticationMethodsPolicy"] = {"temporaryAccessPass": {"state": "enabled", "minimumLifetimeInMinutes": 25}}
    env.write_tenant(data)
    result = env.run(TAP)
    assert result.ok and result.data["expiry_minutes"] == 25
    assert env.user()["authentication"]["methods"][-1]["lifetimeInMinutes"] == 25


@needs_pwsh
def test_b30_4_a_tap_is_refused_when_the_tenant_policy_has_it_switched_off(env: Env) -> None:
    data = env.tenant()
    data["authenticationMethodsPolicy"] = {"temporaryAccessPass": {"state": "disabled"}}
    env.write_tenant(data)
    result = env.run(TAP)
    assert result.status == "error"
    assert not env.oob_dir.exists() or not any(env.oob_dir.rglob("*.json"))


@needs_pwsh
def test_b30_4_a_password_reset_forces_a_change_and_stores_no_value(env: Env) -> None:
    assert env.run(RESET).applied
    user = env.user()
    assert user["passwordProfile"]["forceChangePasswordNextSignIn"] is True
    assert user["pendingCredentials"]["password"] == {"type": "password", "singleUse": True, "expiryMinutes": 60}
    assert env.secret(ANA, "password") not in json.dumps(user)


# -- notice templates (B-04 contract) -------------------------------------------------------------------


@pytest.mark.parametrize("name", [RESET, TAP])
def test_b30_1_each_lever_has_a_notice_template_that_never_names_the_value(name: str) -> None:
    assert missing_templates(Registry.load()) == []
    text = (TEMPLATES_DIR / f"{name}.md").read_text(encoding="utf-8")
    assert "$first_name" in text and "$approver" in text and "$team" in text
    assert "separately" in text and "never in this message" in text
    assert "$value" not in text and "$password" not in text and "$pass" not in text
