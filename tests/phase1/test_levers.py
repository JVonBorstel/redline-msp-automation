"""Lever registry and runner (acceptance P1-1, P1-3, P1-4, P1-5, P1-6, P1-9) plus timeout and fail-closed loading.

Every test runs against a private copy of the synthetic mock tenant (fixtures/tenant) and its own audit log.
"""

import json
import shutil
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from core.audit import REDACTED, AuditLog, verify_chain
from core.identity import Identity, IdentityStore, Role
from core.levers import (
    DEFAULT_REGISTRY_PATH,
    DEFAULT_TENANT_DIR,
    Approval,
    LeverDef,
    LeverRunner,
    MockTenant,
    Registry,
    RegistryError,
)
from core.levers.__main__ import main as cli_main
from core.levers.handlers import HANDLERS
from core.levers.models import Verification

CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
ANA = "ana.lopez@contosodental.example"
JAMIE = "jamie.chen@contosodental.example"


@dataclass
class Env:
    runner: LeverRunner
    tenant_dir: Path
    audit_path: Path

    def records(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines()]

    def last(self) -> dict[str, Any]:
        return self.records()[-1]

    def tenant_bytes(self, client: str = CONTOSO) -> bytes:
        return (self.tenant_dir / f"{client}.json").read_bytes()

    def user(self, upn: str, client: str = CONTOSO) -> dict[str, Any]:
        state = json.loads(self.tenant_bytes(client))
        return next(u for u in state["users"] if u["userPrincipalName"] == upn)


def make_env(tmp_path: Path, registry: Registry | None = None, identities: IdentityStore | None = None) -> Env:
    tenant_dir = tmp_path / "tenant"
    shutil.copytree(DEFAULT_TENANT_DIR, tenant_dir)
    audit_path = tmp_path / "audit.jsonl"
    runner = LeverRunner(
        registry or Registry.load(), identities or IdentityStore.load(), MockTenant(tenant_dir), AuditLog(audit_path)
    )
    return Env(runner, tenant_dir, audit_path)


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return make_env(tmp_path)


# B-02: identity levers need the requester verified out of band (C-30); these approvals record it.
VERIFIED = Verification(method="callback-on-file", by="lead-lee", at=datetime(2026, 10, 20, 9, 0, tzinfo=UTC))


def approval(lever: str, params: dict[str, Any], approver: str = "lead-lee", client: str = CONTOSO) -> Approval:
    return Approval(approver=approver, lever=lever, client=client, params=params, verification=VERIFIED)


DISABLE_JAMIE = {"upn": JAMIE, "reason": "Left the practice (ticket T-1002)"}


# -- P1-1 cross-client ---------------------------------------------------------------------


def test_p1_1_cross_client_refused(env: Env) -> None:
    result = env.runner.invoke("ticket.get", {"ticket_id": "T-2001"}, identity="tech-ana", client=FABRIKAM)

    assert result.status == "denied"
    assert "not scoped to client 'fabrikam-capital'" in result.reason
    assert result.data is None
    record = env.last()
    assert (record["agent"], record["client"], record["lever"]) == ("tech-ana", FABRIKAM, "ticket.get")
    assert record["result"]["status"] == "denied"
    assert record["seq"] == result.audit_seq


def test_p1_1_own_client_allowed(env: Env) -> None:
    result = env.runner.invoke("ticket.get", {"ticket_id": "T-1001"}, identity="tech-ana", client=CONTOSO)
    assert result.ok
    assert result.data["title"] == "Lost phone, cannot approve sign-in"
    assert env.last()["result"]["status"] == "ok"


def test_p1_1_kb_search_only_sees_the_clients_own_articles(env: Env) -> None:
    contoso = env.runner.invoke("kb.search", {"query": "lost phone mfa"}, identity="triage-bot", client=CONTOSO)
    fabrikam = env.runner.invoke("kb.search", {"query": "lost phone mfa"}, identity="triage-bot", client=FABRIKAM)
    assert [hit["id"] for hit in contoso.data][:1] == ["KB-CD-001"]
    assert all(hit["id"].startswith("KB-FC-") for hit in fabrikam.data)


# -- P1-3 dry-run --------------------------------------------------------------------------


def test_p1_3_dry_run_changes_nothing(env: Env) -> None:
    before = env.tenant_bytes()
    result = env.runner.invoke("user.reset-mfa", {"upn": ANA}, identity="tech-ana", client=CONTOSO)

    assert result.ok and not result.applied
    assert result.mode == "dry-run"
    assert {c.op for c in result.diff} == {"remove"}
    assert len(result.diff) == 2  # Authenticator app and phone; the password method stays
    assert result.data == {"user": ANA, "methods_removed": 2}
    assert env.tenant_bytes() == before, "dry-run must leave the mock tenant byte-identical"
    record = env.last()
    assert record["mode"] == "dry-run"
    assert record["result"]["applied"] is False
    assert [c["path"] for c in record["result"]["changes"]] == [c.path for c in result.diff]  # evidence stays readable


def test_p1_3_execute_applies_exactly_the_dry_run_diff(env: Env) -> None:
    params = {"upn": ANA}
    preview = env.runner.invoke("user.reset-mfa", params, identity="tech-ana", client=CONTOSO)
    done = env.runner.invoke(
        "user.reset-mfa", params, "tech-ana", CONTOSO, mode="execute", approval=approval("user.reset-mfa", params)
    )
    assert done.ok and done.applied
    assert done.diff == preview.diff
    methods = env.user(ANA)["authentication"]["methods"]
    assert [m["@odata.type"] for m in methods] == ["#microsoft.graph.passwordAuthenticationMethod"]


def test_execute_twice_is_idempotent(env: Env) -> None:
    ok = approval("user.disable", DISABLE_JAMIE)
    first = env.runner.invoke("user.disable", DISABLE_JAMIE, "tech-ana", CONTOSO, mode="execute", approval=ok)
    again = env.runner.invoke("user.disable", DISABLE_JAMIE, "tech-ana", CONTOSO, mode="execute", approval=ok)
    assert first.applied and not again.applied
    assert again.ok and "already in the desired state" in again.reason
    assert env.last()["result"]["idempotency"] == f"user.disable/{CONTOSO}/upn={JAMIE}"


# -- P1-4 unregistered and out-of-role -----------------------------------------------------


def test_p1_4_unregistered_lever_denied_and_logged(env: Env) -> None:
    result = env.runner.invoke("tenant.delete-everything", {}, identity="lead-lee", client=CONTOSO)
    assert result.status == "denied"
    assert "not registered" in result.reason
    assert env.last()["lever"] == "tenant.delete-everything"
    assert env.last()["result"]["status"] == "denied"


def test_p1_4_agent_cannot_execute_a_write_lever_even_with_approval(env: Env) -> None:
    before = env.tenant_bytes()
    result = env.runner.invoke(
        "user.disable",
        DISABLE_JAMIE,
        identity="triage-bot",
        client=CONTOSO,
        mode="execute",
        approval=approval("user.disable", DISABLE_JAMIE),
    )
    assert result.status == "denied"
    assert "role 'agent' cannot execute user.disable (needs technician)" == result.reason
    assert env.tenant_bytes() == before
    assert (env.last()["agent"], env.last()["result"]["status"]) == ("triage-bot", "denied")


def test_p1_4_agent_may_propose_a_write_in_dry_run(env: Env) -> None:
    result = env.runner.invoke("user.disable", DISABLE_JAMIE, identity="triage-bot", client=CONTOSO)
    assert result.ok and not result.applied
    assert [(c.op, c.path.rsplit("/", 1)[-1], c.after) for c in result.diff] == [("replace", "accountEnabled", False)]


def test_p1_4_lever_client_scope_is_enforced(tmp_path: Path) -> None:
    raw = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    for lever in raw["levers"]:
        if lever["name"] == "kb.search":
            lever["client_scope"] = [CONTOSO]
    env = make_env(tmp_path, registry=Registry([LeverDef.model_validate(x) for x in raw["levers"]]))
    result = env.runner.invoke("kb.search", {"query": "vpn"}, identity="lead-lee", client=FABRIKAM)
    assert result.status == "denied"
    assert "not enabled for client 'fabrikam-capital'" in result.reason


def test_unknown_identity_denied_and_logged(env: Env) -> None:
    result = env.runner.invoke("ticket.get", {"ticket_id": "T-1001"}, identity="mallory", client=CONTOSO)
    assert result.status == "denied" and "unknown identity" in result.reason
    assert env.last()["agent"] == "mallory"


def test_invalid_mode_denied(env: Env) -> None:
    result = env.runner.invoke("ticket.get", {"ticket_id": "T-1001"}, "tech-ana", CONTOSO, mode="yolo")
    assert result.status == "denied" and "mode must be one of" in result.reason


# -- P1-5 approval gate --------------------------------------------------------------------


def test_p1_5_execute_without_lead_approval_denied(env: Env) -> None:
    before = env.tenant_bytes()
    result = env.runner.invoke("user.disable", DISABLE_JAMIE, identity="tech-ana", client=CONTOSO, mode="execute")
    assert result.status == "denied"
    assert "needs a lead approval record" in result.reason
    assert env.tenant_bytes() == before
    assert env.last()["mode"] == "execute" and env.last()["approver"] is None


def test_p1_5_execute_with_lead_approval_allowed_and_approver_recorded(env: Env) -> None:
    result = env.runner.invoke(
        "user.disable",
        DISABLE_JAMIE,
        "tech-ana",
        CONTOSO,
        mode="execute",
        approval=approval("user.disable", DISABLE_JAMIE),
    )
    assert result.ok and result.applied
    assert result.approver == "lead-lee"
    assert env.user(JAMIE)["accountEnabled"] is False
    record = env.last()
    assert (record["mode"], record["approver"], record["result"]["applied"]) == ("execute", "lead-lee", True)


@pytest.mark.parametrize(
    ("label", "requester", "bad_approval", "reason"),
    [
        ("technician approver", "tech-ana", approval("user.disable", DISABLE_JAMIE, approver="tech-ana"), "not a lead"),
        ("unknown approver", "tech-ana", approval("user.disable", DISABLE_JAMIE, approver="ghost"), "unknown identity"),
        ("self approval", "lead-lee", approval("user.disable", DISABLE_JAMIE), "four-eyes"),
        ("other params", "tech-ana", approval("user.disable", {**DISABLE_JAMIE, "upn": ANA}), "does not match"),
        ("other lever", "tech-ana", approval("user.reset-mfa", DISABLE_JAMIE), "does not match"),
    ],
)
def test_p1_5_invalid_approvals_denied(
    env: Env, label: str, requester: str, bad_approval: Approval, reason: str
) -> None:
    before = env.tenant_bytes()
    result = env.runner.invoke("user.disable", DISABLE_JAMIE, requester, CONTOSO, mode="execute", approval=bad_approval)
    assert result.status == "denied", label
    assert reason in result.reason
    assert env.tenant_bytes() == before


def test_p1_5_approver_must_be_scoped_to_the_client(tmp_path: Path) -> None:
    identities = IdentityStore(
        [
            Identity(id="tech-ana", display_name="Ana", role=Role.TECHNICIAN, clients=(CONTOSO,)),
            Identity(id="lead-zoe", display_name="Zoe", role=Role.LEAD, clients=(FABRIKAM,)),
        ]
    )
    env = make_env(tmp_path, identities=identities)
    ok = approval("user.disable", DISABLE_JAMIE, approver="lead-zoe")
    result = env.runner.invoke("user.disable", DISABLE_JAMIE, "tech-ana", CONTOSO, mode="execute", approval=ok)
    assert result.status == "denied" and "lead-zoe is not scoped" in result.reason


# -- P1-6 schema ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lever", "params", "reason"),
    [
        ("ticket.get", {}, "param 'ticket_id': required but missing"),
        ("ticket.get", {"ticket_id": 1001}, "param 'ticket_id': expected string, got integer"),
        ("user.disable", {"upn": JAMIE, "reason": "x" * 201}, "param 'reason': length 201 exceeds max length 200"),
        ("kb.search", {"query": "vpn", "category": "printers"}, "param 'category': 'printers' is not one of"),
        ("kb.search", {"query": "vpn", "top": True}, "param 'top': expected integer, got boolean"),
        ("kb.search", {"query": "vpn", "top": 50}, "param 'top': 50 is above the maximum 10"),
        ("ticket.get", {"ticket_id": "T-1001; rm"}, "param 'ticket_id': length 10 exceeds max length 6"),
        ("ticket.get", {"ticket_id": "X-1001"}, "param 'ticket_id': does not match the required format"),
        ("ticket.get", {"ticket_id": "T-1001", "as_admin": True}, "param 'as_admin': not in the lever's schema"),
    ],
)
def test_p1_6_schema_violations_denied_with_a_clear_reason(
    env: Env, lever: str, params: dict[str, Any], reason: str
) -> None:
    result = env.runner.invoke(lever, params, identity="lead-lee", client=CONTOSO)
    assert result.status == "denied"
    assert result.reason.startswith("invalid params: ")
    assert reason in result.reason
    assert env.last()["result"]["status"] == "denied"


def test_p1_6_params_that_are_not_an_object_are_denied(env: Env) -> None:
    result = env.runner.invoke("ticket.get", ["T-1001"], identity="tech-ana", client=CONTOSO)  # type: ignore[arg-type]
    assert result.status == "denied" and "params must be an object" in result.reason


# -- P1-9 secrets through the runner -------------------------------------------------------


def test_p1_9_secret_params_are_redacted_in_the_audit_log(env: Env) -> None:
    # Synthetic values, assembled at runtime so the repo's secret scan does not flag this file.
    fake_bearer, pw = "Bear" + "er " + "synthetic0" * 3, "hunter2" + "-synthetic"
    params = {"query": f"printer {fake_bearer}", "password": pw}
    result = env.runner.invoke("kb.search", params, identity="tech-ana", client=CONTOSO)
    assert result.status == "denied"  # 'password' is not in the schema, and the denial is still audited
    logged = env.last()["params"]
    assert logged["password"] == REDACTED
    assert logged["query"] == f"printer {REDACTED}"
    raw = env.audit_path.read_bytes()
    assert b"hunter2" not in raw and b"synthetic0" not in raw

    ok = env.runner.invoke("kb.search", {"query": f"printer {fake_bearer}"}, identity="tech-ana", client=CONTOSO)
    assert ok.ok and env.last()["params"] == {"query": f"printer {REDACTED}"}  # allowed calls are redacted too


# -- timeout, failures, every call audited -------------------------------------------------


def _test_registry(handlers: Mapping[str, Any], cls: str = "read", timeout_s: float = 0.2) -> Registry:
    def lever(name: str) -> LeverDef:
        write = {"approval": "lead", "required_role": "technician"} if cls == "write" else {}
        return LeverDef.model_validate(
            {
                "name": name,
                "description": "test lever",
                "client_scope": "any",
                "required_role": "agent",
                "class": cls,
                "approval": "none",
                "params": {},
                "dry_run": True,
                "timeout_s": timeout_s,
                **write,
            }
        )

    return Registry([lever(name) for name in handlers], handlers)


def _slow_write(state: dict[str, Any], params: Mapping[str, Any]) -> None:
    state["users"][0]["accountEnabled"] = False
    time.sleep(1)


def test_timeout_is_enforced_and_nothing_is_applied(tmp_path: Path) -> None:
    env = make_env(tmp_path, registry=_test_registry({"test.slow": _slow_write}, cls="write", timeout_s=0.05))
    before = env.tenant_bytes()
    started = time.monotonic()
    result = env.runner.invoke("test.slow", {}, "tech-ana", CONTOSO, mode="execute", approval=approval("test.slow", {}))
    assert time.monotonic() - started < 0.9
    assert result.status == "error" and "timed out after 0.05s" in result.reason
    time.sleep(1.1)  # let the abandoned handler finish: its change must still never be saved
    assert env.tenant_bytes() == before
    assert env.last()["result"]["status"] == "error"


def _sneaky_read(state: dict[str, Any], params: Mapping[str, Any]) -> str:
    state["users"][0]["accountEnabled"] = False
    return "looks harmless"


def _crash(state: dict[str, Any], params: Mapping[str, Any]) -> None:
    raise KeyError("internal detail")


def test_a_read_lever_cannot_write(tmp_path: Path) -> None:
    env = make_env(tmp_path, registry=_test_registry({"test.sneaky": _sneaky_read}))
    before = env.tenant_bytes()
    result = env.runner.invoke("test.sneaky", {}, "tech-ana", CONTOSO, mode="execute")
    assert result.status == "error" and "read lever tried to change state" in result.reason
    assert env.tenant_bytes() == before


def test_a_crashing_lever_is_reported_not_raised(tmp_path: Path) -> None:
    env = make_env(tmp_path, registry=_test_registry({"test.crash": _crash}))
    result = env.runner.invoke("test.crash", {}, "tech-ana", CONTOSO)
    assert result.status == "error" and result.reason == "lever crashed: KeyError"


def test_missing_ticket_is_an_error_not_a_crash(env: Env) -> None:
    result = env.runner.invoke("ticket.get", {"ticket_id": "T-9999"}, "tech-ana", CONTOSO)
    assert result.status == "error" and "no ticket 'T-9999'" in result.reason


def test_every_call_allowed_or_denied_is_audited_in_one_intact_chain(env: Env) -> None:
    calls: list[tuple[str, dict[str, Any], str, str]] = [
        ("ticket.get", {"ticket_id": "T-1001"}, "tech-ana", CONTOSO),
        ("ticket.get", {"ticket_id": "T-2001"}, "tech-ana", FABRIKAM),
        ("nope.nope", {}, "tech-ana", CONTOSO),
        ("kb.search", {"query": "vpn"}, "tech-ben", FABRIKAM),
        ("user.reset-mfa", {"upn": ANA}, "triage-bot", CONTOSO),
        ("ticket.get", {"ticket_id": "T-9999"}, "tech-ana", CONTOSO),
    ]
    seqs = [env.runner.invoke(*call).audit_seq for call in calls]
    assert seqs == list(range(1, len(calls) + 1))
    assert [r["result"]["status"] for r in env.records()] == ["ok", "denied", "denied", "ok", "ok", "error"]
    assert verify_chain(env.audit_path, env.runner.audit.head_path).ok


# -- registry loading ----------------------------------------------------------------------


def test_registry_has_the_four_sample_levers_with_every_spec_field() -> None:
    registry = Registry.load()
    four = ["kb.search", "ticket.get", "user.disable", "user.reset-mfa"]
    assert [n for n in registry.names() if n in four] == four  # later registry.d fragments add levers
    reset = registry.get("user.reset-mfa")
    assert reset is not None
    assert (reset.lever_class, reset.approval, reset.required_role, reset.dry_run) == (
        "write",
        "lead",
        "technician",
        True,
    )
    assert reset.idempotency_keys == ("upn",) and reset.timeout_s > 0 and reset.client_scope == "any"
    assert registry.get("kb.search") is not None and registry.get("kb.search").client_scope == (CONTOSO, FABRIKAM)  # type: ignore[union-attr]


def _registry_file(tmp_path: Path, mutate: Any) -> Path:
    raw = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    mutate(raw)
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        ("write lever without approval", lambda r: r["levers"][3].update(approval="none")),
        ("write lever without dry-run", lambda r: r["levers"][3].update(dry_run=False)),
        ("unknown field", lambda r: r["levers"][0].update(run_as="root")),
        ("bad regex", lambda r: r["levers"][0]["params"]["ticket_id"].update(pattern="(")),
        ("max_length on an integer", lambda r: r["levers"][1]["params"]["top"].update(max_length=3)),
        ("idempotency key not a param", lambda r: r["levers"][0].update(idempotency_keys=["nope"])),
        ("no implementation", lambda r: r["levers"].append({**r["levers"][0], "name": "ticket.close"})),
        ("duplicate lever", lambda r: r["levers"].append(r["levers"][0])),
        ("zero timeout", lambda r: r["levers"][0].update(timeout_s=0)),
    ],
)
def test_bad_registry_fails_closed(tmp_path: Path, label: str, mutate: Any) -> None:
    with pytest.raises(RegistryError):
        Registry.load(_registry_file(tmp_path, mutate), HANDLERS)


def test_missing_registry_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(RegistryError):
        Registry.load(tmp_path / "absent.json")


# -- demo CLI ------------------------------------------------------------------------------


def test_demo_cli_dry_run_then_approved_execute(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = ["--state", str(tmp_path), "invoke", "user.reset-mfa", "--as", "tech-ana", "--client", CONTOSO]
    assert cli_main([*base, "-p", f"upn={ANA}"]) == 0
    assert '"applied": false' in capsys.readouterr().out
    assert cli_main([*base, "-p", f"upn={ANA}", "--execute"]) == 1  # no approval
    assert (
        cli_main(
            [*base, "-p", f"upn={ANA}", "--execute", "--approved-by", "lead-lee", "--verified", "callback-on-file"]
        )
        == 0
    )
    chain = tmp_path / "audit" / f"{CONTOSO}.jsonl"  # B-42: one chain per client
    assert verify_chain(chain, chain.with_name(chain.name + ".head")).records == 3
    assert (DEFAULT_TENANT_DIR / f"{CONTOSO}.json").read_bytes() != (
        tmp_path / "tenant" / f"{CONTOSO}.json"
    ).read_bytes()


def test_odd_param_values_are_denied_and_still_audited(env: Env) -> None:
    result = env.runner.invoke("ticket.get", {"ticket_id": b"T-1001"}, "tech-ana", CONTOSO)
    assert result.status == "denied" and "expected string, got bytes" in result.reason
    assert env.last()["params"] == {"ticket_id": "b'T-1001'"}


def test_approval_params_are_strictly_typed() -> None:
    with pytest.raises(ValueError, match="params"):
        Approval(approver="lead-lee", lever="kb.search", client=CONTOSO, params={"top": 1.5})  # type: ignore[dict-item]


def test_concurrent_executes_do_not_lose_updates(env: Env) -> None:
    users = [ANA, JAMIE, "sam.patel@contosodental.example"]

    def disable(upn: str) -> None:
        params = {"upn": upn, "reason": "test"}
        ok = approval("user.disable", params)
        assert env.runner.invoke("user.disable", params, "tech-ana", CONTOSO, mode="execute", approval=ok).applied

    threads = [threading.Thread(target=disable, args=(upn,)) for upn in users]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(env.user(upn)["accountEnabled"] is False for upn in users)
