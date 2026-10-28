"""B-28 runner v3: replay guard, per-client lock, audit v2 fields, R2/R3 approval rules, requester+contact.

Acceptance ids B28-1 to B28-8 are defined in specs/B-28.md. Every test is offline. The "Entra tenant" is the
mock issuer from B-89 (an RSA key made in memory from a fixed seed), every tenant, app and object id is a synthetic
GUID built at run time, time is a pinned clock, and each test works on a private copy of the mock tenant and its own
audit log under tmp_path. Committed files are never modified.
Run: uv run --frozen pytest tests/py/levers/test_b28_runner3.py
"""

from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from core.audit import AuditLog, verify_chain
from core.auth import AuthConfig, TokenValidator
from core.auth.mock_issuer import MockIssuer
from core.identity import Identity, IdentityStore, Role
from core.levers import DEFAULT_TENANT_DIR, Approval, LeverDef, LeverRunner, MockTenant, Registry, RegistryError
from core.levers.handlers import user_disable, user_reset_mfa
from core.levers.models import ContactConfirmation, Verification
from core.levers.runner import PolicyError, RunnerPolicy, undo_notice
from ui.app import NO_UNDO

CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
ANA = "ana.lopez@contosodental.example"
JAMIE = "jamie.chen@contosodental.example"
MORGAN = "morgan.reyes@fabrikamcapital.example"
NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
CONTACT = "contact-office-manager"


def guid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://example.invalid/b28/{name}"))


TENANT, APP_ID = guid("tenant"), guid("approval-page")
OIDS = {name: guid(name) for name in ("lead-lee", "lead-fay", "lead-gus", "tech-ana")}


def ident(id_: str, role: Role, *clients: str) -> Identity:
    return Identity(id=id_, display_name=f"{id_} (synthetic)", role=role, clients=clients)


IDENTITIES = IdentityStore(
    [
        ident("tech-ana", Role.TECHNICIAN, CONTOSO),
        ident("tech-ben", Role.TECHNICIAN, FABRIKAM),
        ident("lead-lee", Role.LEAD, CONTOSO, FABRIKAM),
        ident("lead-fay", Role.LEAD, CONTOSO),
        ident("lead-gus", Role.LEAD, CONTOSO),
        ident("lead-zed", Role.LEAD, FABRIKAM),
        ident("triage-bot", Role.AGENT, CONTOSO, FABRIKAM),
    ]
)


def lever(name: str, risk: str, **extra: Any) -> LeverDef:
    base: dict[str, Any] = {
        "name": name,
        "description": "A write lever for B-28 tests.",
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


UPN_PARAM = {"upn": {"type": "string", "required": True, "max_length": 113}}
SLOW_LOCK = threading.Lock()
SLOW_STATE = {"active": 0, "max_active": 0}
BARRIER = {"b": threading.Barrier(2, timeout=3)}


def slow(state: dict[str, Any], params: Mapping[str, Any]) -> Any:
    with SLOW_LOCK:
        SLOW_STATE["active"] += 1
        SLOW_STATE["max_active"] = max(SLOW_STATE["max_active"], SLOW_STATE["active"])
    try:
        if params["n"] == 1:
            BARRIER["b"].wait()  # both clients must be inside the handler at once
        else:
            time.sleep(0.2)
        state["flag"] = params["n"]
    finally:
        with SLOW_LOCK:
            SLOW_STATE["active"] -= 1
    return {"flag": params["n"]}


def make_registry() -> Registry:
    levers = [
        lever("test.r1", "R1"),
        lever("test.r2", "R2"),
        lever("test.r3", "R3"),
        lever("test.r3-more", "R3", min_approvers=3),
        lever("test.purge", "R3", reversibility="irreversible"),
        lever("test.slow", "R1", idempotency_keys=[]),
        lever(
            "test.contact",
            "R3",
            params=UPN_PARAM,
            idempotency_keys=["upn"],
            verification="requester+contact",
        ),
        lever("test.disable", "R3", params=UPN_PARAM, idempotency_keys=["upn"], verification="requester"),
    ]
    handlers = {
        "test.r1": set_flag,
        "test.r2": set_flag,
        "test.r3": set_flag,
        "test.r3-more": set_flag,
        "test.purge": set_flag,
        "test.slow": slow,
        "test.contact": user_reset_mfa,
        "test.disable": user_disable,
    }
    return Registry(levers, handlers)


@pytest.fixture(scope="module")
def issuer() -> MockIssuer:
    return MockIssuer(TENANT, seed=28)


@dataclass
class Env:
    runner: LeverRunner
    tenant_dir: Path
    audit_path: Path
    issuer: MockIssuer
    now: datetime = NOW

    def records(self) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        return [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines()]

    def last(self) -> dict[str, Any]:
        return self.records()[-1]

    def tenant_bytes(self, client: str = CONTOSO) -> bytes:
        return (self.tenant_dir / f"{client}.json").read_bytes()

    def token(self, approver: str, now: datetime | None = None) -> str:
        claims = self.issuer.claims(audience=APP_ID, oid=OIDS[approver], now=now or self.now)
        return self.issuer.sign(claims)

    def approval(
        self, approver: str, name: str, params: Mapping[str, Any], client: str = CONTOSO, **kw: Any
    ) -> Approval:
        fields: dict[str, Any] = {"token": self.token(approver)}
        fields.update(kw)
        return Approval(approver=approver, lever=name, client=client, params=dict(params), **fields)


def make_env(
    tmp_path: Path,
    issuer: MockIssuer,
    *,
    demo: bool = False,
    client_records: Mapping[str, Mapping[str, Any]] | None = None,
    policy: bool = True,
    registry: Registry | None = None,
) -> Env:
    tenant_dir = tmp_path / "tenant"
    if not tenant_dir.exists():
        shutil.copytree(DEFAULT_TENANT_DIR, tenant_dir)
    audit_path = tmp_path / "audit.jsonl"
    config = AuthConfig.model_validate(
        {
            "version": 1,
            "tenant_id": TENANT,
            "client_id": APP_ID,
            "keys": [issuer.jwk()],
            "approvers": {OIDS["lead-lee"]: "lead-lee", OIDS["lead-fay"]: "lead-fay", OIDS["lead-gus"]: "lead-gus"},
        }
    )
    records = client_records if client_records is not None else {CONTOSO: {"authorized_contacts": [CONTACT]}}
    the_policy = RunnerPolicy(TokenValidator(config, IDENTITIES), demo=demo, client_records=records) if policy else None
    runner = LeverRunner(
        registry or make_registry(),
        IDENTITIES,
        MockTenant(tenant_dir),
        AuditLog(audit_path),
        policy=the_policy,
        clock=lambda: NOW,
    )
    return Env(runner, tenant_dir, audit_path, issuer)


@pytest.fixture
def env(tmp_path: Path, issuer: MockIssuer) -> Env:
    return make_env(tmp_path, issuer)


def run(
    env: Env,
    name: str,
    params: Mapping[str, Any],
    approvals: list[Approval],
    who: str = "tech-ana",
    client: str = CONTOSO,
):
    return env.runner.invoke(name, params, who, client, mode="execute", approval=approvals)


# -- B28-1 replay guard ---------------------------------------------------------------------------------


def test_b28_1_a_second_approval_for_an_applied_key_is_denied_and_audited(env: Env) -> None:
    params = {"n": 7}
    first = run(
        env,
        "test.r3",
        params,
        [env.approval("lead-lee", "test.r3", params), env.approval("lead-fay", "test.r3", params)],
    )
    assert first.ok and first.applied
    applied = env.last()
    assert applied["result"]["applied"] is True and applied["result"]["idempotency"] == "test.r3/contoso-dental/n=7"

    before = len(env.records())
    other = run(
        env,
        "test.r3",
        params,
        [env.approval("lead-lee", "test.r3", params), env.approval("lead-gus", "test.r3", params)],
    )
    assert other.status == "denied" and "already applied under another approval" in other.reason
    assert len(env.records()) == before + 1
    denial = env.last()
    assert (denial["result"]["status"], denial["result"]["applied"]) == ("denied", False)
    assert denial["result"]["idempotency"] == applied["result"]["idempotency"]


def test_b28_1_the_same_approval_may_be_presented_again(env: Env) -> None:
    params = {"n": 8}
    approvals = [env.approval("lead-lee", "test.r3", params), env.approval("lead-fay", "test.r3", params)]
    assert run(env, "test.r3", params, approvals).applied
    again = run(env, "test.r3", params, approvals)
    assert again.ok and not again.applied and again.reason == "no change: already in the desired state"


def test_b28_1_a_different_key_is_not_blocked(env: Env) -> None:
    for n in (1, 2):
        params = {"n": n}
        approvals = [env.approval("lead-lee", "test.r3", params), env.approval("lead-fay", "test.r3", params)]
        assert run(env, "test.r3", params, approvals).applied


# -- B28-2 per-client lock ------------------------------------------------------------------------------


def _both(env: Env, jobs: list[tuple[str, str, dict[str, Any]]]) -> list[Any]:
    results: list[Any] = [None] * len(jobs)

    def go(i: int) -> None:
        who, client, params = jobs[i]
        ap = Approval(approver="lead-lee", lever="test.slow", client=client, params=params)
        results[i] = env.runner.invoke("test.slow", params, who, client, mode="execute", approval=ap)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(len(jobs))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    return results


def test_b28_2_executes_for_two_clients_run_at_the_same_time(tmp_path: Path, issuer: MockIssuer) -> None:
    env = make_env(tmp_path, issuer, policy=False)
    BARRIER["b"] = threading.Barrier(2, timeout=3)  # a serialised runner would break this barrier
    results = _both(env, [("tech-ana", CONTOSO, {"n": 1}), ("tech-ben", FABRIKAM, {"n": 1})])
    assert [r.status for r in results] == ["ok", "ok"]
    assert all(r.applied for r in results)


def test_b28_2_two_executes_for_one_client_serialise(tmp_path: Path, issuer: MockIssuer) -> None:
    env = make_env(tmp_path, issuer, policy=False)
    SLOW_STATE.update(active=0, max_active=0)
    results = _both(env, [("tech-ana", CONTOSO, {"n": 2}), ("tech-ana", CONTOSO, {"n": 3})])
    assert [r.status for r in results] == ["ok", "ok"]
    assert SLOW_STATE["max_active"] == 1
    # Neither write was lost: the second load saw the first save (load-modify-save did not interleave).
    flag = json.loads(env.tenant_bytes()).get("flag")
    assert flag in (2, 3)
    assert sum(1 for r in env.records() if r["result"]["applied"]) == 2


# -- B28-3 R3 dual approval -----------------------------------------------------------------------------


def test_b28_3_r3_with_two_distinct_leads_executes(env: Env) -> None:
    params = {"n": 1}
    result = run(
        env,
        "test.r3",
        params,
        [env.approval("lead-lee", "test.r3", params), env.approval("lead-fay", "test.r3", params)],
    )
    assert result.ok and result.applied and result.approver == "lead-lee,lead-fay"
    assert env.last()["approver"] == "lead-lee,lead-fay"


def test_b28_3_one_approval_is_denied_and_audited(env: Env) -> None:
    params = {"n": 1}
    before = env.tenant_bytes()
    result = run(env, "test.r3", params, [env.approval("lead-lee", "test.r3", params)])
    assert result.status == "denied" and "needs approvals from 2 distinct leads" in result.reason
    assert env.last()["result"]["status"] == "denied" and env.tenant_bytes() == before


@pytest.mark.parametrize("case", ["same-lead-twice", "requester-approves", "other-client-lead", "agent-approver"])
def test_b28_3_the_second_approval_must_be_a_different_eligible_lead(env: Env, case: str) -> None:
    params = {"n": 1}
    who = "tech-ana"
    first = env.approval("lead-lee", "test.r3", params)
    second = {
        "same-lead-twice": env.approval("lead-lee", "test.r3", params),
        "requester-approves": env.approval("lead-fay", "test.r3", params),
        "other-client-lead": Approval(approver="lead-zed", lever="test.r3", client=CONTOSO, params=params, demo=True),
        "agent-approver": Approval(approver="triage-bot", lever="test.r3", client=CONTOSO, params=params, demo=True),
    }[case]
    if case == "requester-approves":
        who = "lead-fay"
    before = env.tenant_bytes()
    result = run(env, "test.r3", params, [first, second], who=who)
    assert result.status == "denied" and not result.applied
    assert env.tenant_bytes() == before
    assert env.last()["result"]["status"] == "denied"


def test_b28_3_the_shipped_identity_levers_need_two_leads_too(tmp_path: Path, issuer: MockIssuer) -> None:
    env = make_env(tmp_path, issuer, registry=Registry.load())
    params = {"upn": JAMIE, "reason": "Left the practice (ticket T-1002)"}
    cb = Verification(method="callback-on-file", by="lead-lee", at=NOW, ref="number-on-file:psa-contact")
    one = env.approval("lead-lee", "user.disable", params, verification=cb)
    denied = run(env, "user.disable", params, [one])
    assert denied.status == "denied" and "needs approvals from 2" in denied.reason
    two = [one, env.approval("lead-fay", "user.disable", params)]
    assert run(env, "user.disable", params, two).applied


# -- B28-4 audit v2 fields ------------------------------------------------------------------------------


def test_b28_4_every_record_carries_request_id_actor_kind_and_lever_version(env: Env) -> None:
    params = {"n": 4}
    env.runner.invoke("test.r3", params, "triage-bot", CONTOSO)  # agent dry-run
    env.runner.invoke("test.r3", params, "tech-ana", CONTOSO, mode="execute")  # denied: no approval
    run(
        env,
        "test.r3",
        params,
        [env.approval("lead-lee", "test.r3", params), env.approval("lead-fay", "test.r3", params)],
    )
    env.runner.pause("test.r3", "lead-lee", "stop")
    env.runner.invoke("test.r3", params, "tech-ana", CONTOSO)  # denied: paused
    records = env.records()
    assert len(records) == 5
    for record in records:
        assert record["request_id"].startswith("req-") and len(record["request_id"]) > 20
        assert record["actor_kind"] in ("agent", "human")
        assert record["lever_version"] == 1
    assert [r["actor_kind"] for r in records[:2]] == ["agent", "human"]
    assert len({r["request_id"] for r in records}) == 5
    assert verify_chain(env.audit_path, env.audit_path.with_name("audit.jsonl.head")).ok


def test_b28_4_an_unregistered_lever_and_unknown_identity_stay_honest(env: Env) -> None:
    env.runner.invoke("no.such", {}, "nobody", CONTOSO)
    record = env.last()
    assert record["request_id"].startswith("req-")
    assert (record["actor_kind"], record["lever_version"]) == ("unknown", None)


def test_b28_4_a_powershell_free_python_lever_also_gets_a_request_id_per_call(env: Env) -> None:
    for _ in range(2):
        env.runner.invoke("test.r1", {"n": 1}, "tech-ana", CONTOSO)
    first, second = env.records()
    assert first["request_id"] != second["request_id"]


# -- B28-5 irreversible levers --------------------------------------------------------------------------


def purge(env: Env, age: timedelta | None, n: int = 5) -> Any:
    params = {"n": n}
    stamp = None if age is None else NOW - age
    approvals = [env.approval(who, "test.purge", params, approved_at=stamp) for who in ("lead-lee", "lead-fay")]
    return run(env, "test.purge", params, approvals)


def test_b28_5_an_approval_younger_than_24_hours_executes(env: Env) -> None:
    assert purge(env, timedelta(hours=23, minutes=59)).applied


@pytest.mark.parametrize("age", [timedelta(hours=24), timedelta(hours=25), timedelta(days=3), None])
def test_b28_5_an_old_or_untimed_approval_is_denied_and_audited(env: Env, age: timedelta | None) -> None:
    before = env.tenant_bytes()
    result = purge(env, age)
    assert result.status == "denied" and not result.applied and env.tenant_bytes() == before
    assert env.last()["result"]["status"] == "denied"
    assert "irreversible" in result.reason


def test_b28_5_an_approval_dated_in_the_future_is_denied(env: Env) -> None:
    assert purge(env, -timedelta(hours=2)).status == "denied"


def test_b28_5_the_page_text_says_no_undo(env: Env) -> None:
    purge_spec = env.runner.registry.get("test.purge")
    reversible = env.runner.registry.get("test.r3")
    assert purge_spec is not None and reversible is not None
    assert undo_notice(purge_spec) == "no undo" and undo_notice(reversible) == ""
    assert "no undo" in NO_UNDO  # the approval page's own line (ui/app.py) for a lever with no undo


# -- B28-6 authenticated approvers ----------------------------------------------------------------------


def two_tokens(env: Env, name: str, params: Mapping[str, Any]) -> list[Approval]:
    return [env.approval("lead-lee", name, params), env.approval("lead-fay", name, params)]


def test_b28_6_an_approval_with_no_sign_in_is_denied(env: Env) -> None:
    params = {"n": 6}
    bare = Approval(approver="lead-lee", lever="test.r2", client=CONTOSO, params=params)
    result = run(env, "test.r2", params, [bare])
    assert result.status == "denied" and "not authenticated" in result.reason


def test_b28_6_a_valid_token_is_accepted_for_r2_and_recorded(env: Env) -> None:
    params = {"n": 6}
    result = run(env, "test.r2", params, [env.approval("lead-lee", "test.r2", params)])
    assert result.ok and result.applied
    entry = env.last()["result"]["approvals"][0]
    assert (entry["approver"], entry["auth"], entry["demo"]) == ("lead-lee", "entra-id-token", False)
    assert entry["sid"]


def test_b28_6_the_token_never_reaches_the_audit_log(env: Env) -> None:
    params = {"n": 6}
    approval = env.approval("lead-lee", "test.r2", params)
    token = approval.token
    assert token and token not in repr(approval) and "token" not in approval.model_dump()
    run(env, "test.r2", params, [approval])
    assert token not in env.audit_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("flaw", ["expired", "wrong-audience", "tampered", "other-identity", "garbage"])
def test_b28_6_a_token_the_validator_refuses_is_denied(env: Env, flaw: str) -> None:
    params = {"n": 6}
    claims = env.issuer.claims(audience=APP_ID, oid=OIDS["lead-lee"], now=NOW)
    if flaw == "expired":
        claims = env.issuer.claims(audience=APP_ID, oid=OIDS["lead-lee"], now=NOW - timedelta(hours=3))
    if flaw == "wrong-audience":
        claims["aud"] = guid("some-other-app")
    token = env.issuer.sign(claims)
    if flaw == "tampered":
        head, body, sig = token.split(".")
        token = ".".join([head, body[:-3] + ("AAA" if body[-3:] != "AAA" else "BBB"), sig])
    if flaw == "garbage":
        token = "-".join(["not", "a", "jwt"])
    approver = "lead-lee"
    if flaw == "other-identity":
        approver = "lead-fay"  # lee's token on fay's approval
    approval = Approval(approver=approver, lever="test.r2", client=CONTOSO, params=params, token=token)
    result = run(env, "test.r2", params, [approval])
    assert result.status == "denied" and not result.applied
    assert "sign-in refused" in result.reason or "different identity" in result.reason
    assert token not in env.audit_path.read_text(encoding="utf-8")


def test_b28_6_a_token_with_no_validator_configured_fails_closed(tmp_path: Path, issuer: MockIssuer) -> None:
    env = make_env(tmp_path, issuer)
    env.runner.policy = RunnerPolicy(demo=False)
    params = {"n": 6}
    result = run(env, "test.r2", params, [env.approval("lead-lee", "test.r2", params)])
    assert result.status == "denied" and "no token validator" in result.reason


def test_b28_6_the_demo_picker_works_only_behind_demo_and_is_marked(tmp_path: Path, issuer: MockIssuer) -> None:
    params = {"n": 6}
    off = make_env(tmp_path / "off", issuer, demo=False)
    pick = Approval(approver="lead-lee", lever="test.r2", client=CONTOSO, params=params, demo=True)
    refused = run(off, "test.r2", params, [pick])
    assert refused.status == "denied" and "--demo" in refused.reason

    on = make_env(tmp_path / "on", issuer, demo=True)
    accepted = run(on, "test.r2", params, [pick])
    assert accepted.ok and accepted.applied
    entry = on.last()["result"]["approvals"][0]
    assert (entry["auth"], entry["demo"]) == ("demo-picker", True)


def test_b28_6_an_r1_lever_needs_no_sign_in(env: Env) -> None:
    params = {"n": 1}
    plain = Approval(approver="lead-lee", lever="test.r1", client=CONTOSO, params=params)
    assert run(env, "test.r1", params, [plain]).applied


def test_b28_6_an_approval_cannot_carry_both_a_token_and_a_demo_pick() -> None:
    with pytest.raises(ValidationError):
        Approval(approver="lead-lee", lever="x.y", client=CONTOSO, params={}, token="x" * 3, demo=True)


# -- B28-7 minimums can be raised, never lowered --------------------------------------------------------


def test_b28_7_a_lever_may_raise_the_minimum(env: Env) -> None:
    params = {"n": 9}
    two = two_tokens(env, "test.r3-more", params)
    denied = run(env, "test.r3-more", params, two)
    assert denied.status == "denied" and "needs approvals from 3 distinct leads" in denied.reason
    three = [*two, env.approval("lead-gus", "test.r3-more", params)]
    assert run(env, "test.r3-more", params, three).applied


@pytest.mark.parametrize(("risk", "lowered"), [("R3", 1), ("R2", 0)])
def test_b28_7_a_lever_cannot_lower_the_minimum(risk: str, lowered: int) -> None:
    raw: dict[str, Any] = {
        "name": "test.low",
        "description": "x",
        "client_scope": "any",
        "required_role": "technician",
        "class": "write",
        "approval": "lead",
        "params": {},
        "dry_run": True,
        "timeout_s": 2,
        "risk_class": risk,
        "min_approvers": lowered,
    }
    with pytest.raises(ValidationError):
        LeverDef.model_validate(raw)


def test_b28_7_a_lowered_lever_value_fails_the_registry_load(tmp_path: Path) -> None:
    entry = json.loads(json.dumps(json.loads(Path("levers/registry.json").read_text(encoding="utf-8"))))
    for item in entry["levers"]:
        if item["name"] == "user.disable":
            item["min_approvers"] = 1
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(entry), encoding="utf-8")
    with pytest.raises(RegistryError):
        Registry.load(path, fragments_dir=tmp_path / "none")


def test_b28_7_a_client_record_may_raise_the_minimum(tmp_path: Path, issuer: MockIssuer) -> None:
    env = make_env(tmp_path, issuer, client_records={CONTOSO: {"approver_minimum": {"R2": 2}}})
    params = {"n": 9}
    one = run(env, "test.r2", params, [env.approval("lead-lee", "test.r2", params)])
    assert one.status == "denied" and "needs approvals from 2 distinct leads" in one.reason
    assert run(env, "test.r2", params, two_tokens(env, "test.r2", params)).applied
    # Another client's record does not apply here.
    other = {"n": 10}
    fab = Approval(approver="lead-lee", lever="test.r1", client=FABRIKAM, params=other)
    assert env.runner.invoke("test.r1", other, "tech-ben", FABRIKAM, mode="execute", approval=[fab]).ok


@pytest.mark.parametrize(
    "record",
    [
        {"approver_minimum": {"R3": 1}},
        {"approver_minimum": {"R2": 0}},
        {"approver_minimum": {"R9": 2}},
        {"approver_minimum": {"R2": True}},
        {"approver_minimum": {"R2": "2"}},
        {"approver_minimum": [2]},
        {"authorized_contacts": "contact-1"},
    ],
)
def test_b28_7_a_lowered_or_malformed_client_value_fails_the_load(record: dict[str, Any]) -> None:
    with pytest.raises(PolicyError):
        RunnerPolicy(client_records={CONTOSO: record})


# -- B28-8 requester+contact ----------------------------------------------------------------------------

CALLBACK = Verification(method="callback-on-file", by="lead-lee", at=NOW, ref="number-on-file:psa-contact")
CONFIRMED = ContactConfirmation(by="tech-ana", at=NOW, contact=CONTACT)


def contact_run(
    env: Env, upn: str = ANA, callback: Verification | None = CALLBACK, contact: ContactConfirmation | None = CONFIRMED
) -> Any:
    params = {"upn": upn}
    first = env.approval("lead-lee", "test.contact", params, verification=callback, contact_verification=contact)
    return run(env, "test.contact", params, [first, env.approval("lead-fay", "test.contact", params)])


def test_b28_8_both_records_present_executes_and_both_are_audited(env: Env) -> None:
    result = contact_run(env)
    assert result.ok and result.applied
    stored = env.last()["result"]
    assert stored["verification"]["method"] == "callback-on-file"
    assert stored["verification"]["ref"] == "number-on-file:psa-contact"
    assert stored["contact_verification"]["contact"] == CONTACT


def test_b28_8_no_phone_number_reaches_the_audit_log(env: Env) -> None:
    numbers = []
    for path in DEFAULT_TENANT_DIR.glob("*.json"):
        for user in json.loads(path.read_text(encoding="utf-8")).get("users", []):
            numbers += [
                m["phoneNumber"] for m in user.get("authentication", {}).get("methods", []) if "phoneNumber" in m
            ]
    assert numbers
    contact_run(env)
    log = env.audit_path.read_text(encoding="utf-8")
    assert not any(number in log for number in numbers)


def test_b28_8_the_callback_record_alone_is_not_enough(env: Env) -> None:
    before = env.tenant_bytes()
    result = contact_run(env, contact=None)
    assert result.status == "denied" and "authorized contact" in result.reason
    assert env.tenant_bytes() == before and env.last()["result"]["status"] == "denied"


def test_b28_8_the_contact_confirmation_alone_is_not_enough(env: Env) -> None:
    result = contact_run(env, callback=None)
    assert result.status == "denied" and "verification" in result.reason


@pytest.mark.parametrize("ref", ["", "CALL-3101", "number-on-file:somewhere-else"])
def test_b28_8_a_callback_must_name_where_the_number_came_from(env: Env, ref: str) -> None:
    bad = Verification(method="callback-on-file", by="lead-lee", at=NOW, ref=ref)
    assert contact_run(env, callback=bad).status == "denied"


def test_b28_8_a_knowledge_check_style_method_is_not_a_callback(env: Env) -> None:
    other = Verification(method="manager-confirmed", by="lead-lee", at=NOW, ref="number-on-file:psa-contact")
    assert contact_run(env, callback=other).status == "denied"


def test_b28_8_the_contact_must_be_on_the_client_record(env: Env) -> None:
    stranger = ContactConfirmation(by="tech-ana", at=NOW, contact="contact-someone-else")
    result = contact_run(env, contact=stranger)
    assert result.status == "denied" and "not an authorized contact" in result.reason


def test_b28_8_an_agent_cannot_record_a_verification(env: Env) -> None:
    bot = ContactConfirmation(by="triage-bot", at=NOW, contact=CONTACT)
    assert contact_run(env, contact=bot).status == "denied"


def test_b28_8_a_target_with_a_directory_role_is_refused(tmp_path: Path, issuer: MockIssuer) -> None:
    env = make_env(tmp_path, issuer)
    path = env.tenant_dir / f"{CONTOSO}.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["directoryRoles"] = [
        {"displayName": "Global Administrator", "members": [{"userPrincipalName": ANA.upper()}]},
    ]
    path.write_text(json.dumps(state), encoding="utf-8")
    before = env.tenant_bytes()
    result = contact_run(env)
    assert result.status == "denied" and "privileged directory role" in result.reason
    assert env.tenant_bytes() == before
    assert contact_run(env, upn=JAMIE).status == "ok"  # an ordinary user in the same tenant passes the check


def test_b28_8_without_a_policy_the_contact_rule_fails_closed(tmp_path: Path, issuer: MockIssuer) -> None:
    env = make_env(tmp_path, issuer, policy=False)
    params = {"upn": ANA}
    first = Approval(
        approver="lead-lee",
        lever="test.contact",
        client=CONTOSO,
        params=params,
        verification=CALLBACK,
        contact_verification=CONFIRMED,
    )
    result = env.runner.invoke("test.contact", params, "tech-ana", CONTOSO, mode="execute", approval=first)
    assert result.status == "denied" and "not an authorized contact" in result.reason
