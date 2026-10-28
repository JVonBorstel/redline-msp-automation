"""B-41 rollback from recorded before-state: workflows/rollback.

Acceptance ids B41-1 to B41-3 are defined in specs/B-41.md. Every test is offline and works on private copies of the
synthetic mock tenant in tmp_path; committed fixtures are never modified. Tests that start `pwsh` (user.enable is a
PowerShell lever) skip when PowerShell 7.4+ is not installed.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/rollback
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from core.audit import AuditLog, verify_chain
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, Approval, LeverRunner, MockTenant, Registry
from core.levers.models import Verification
from core.queue import DecisionDenied, ProposalQueue
from workflows.rollback import plan, summary
from workflows.rollback.__main__ import main

CONTOSO = "contoso-dental"
JAMIE = "jamie.chen@contosodental.example"
SAM = "sam.patel@contosodental.example"
AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
VERIFIED = Verification(method="callback-on-file", by="lead-lee", at=AT, ref="CALL-4101")
needs_pwsh = pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh (PowerShell 7.4+) is not installed")


@dataclass
class Env:
    runner: LeverRunner
    queue: ProposalQueue
    tenant_dir: Path
    audit_path: Path

    def tenant_bytes(self) -> bytes:
        return (self.tenant_dir / f"{CONTOSO}.json").read_bytes()

    def records(self) -> list[dict[str, Any]]:
        return [json.loads(x) for x in self.audit_path.read_text(encoding="utf-8").splitlines() if x.strip()]

    def disable(self, upn: str = JAMIE) -> int:
        """Disable through the runner as a lead-approved execute; returns the audit seq of the applied record."""
        params = {"upn": upn, "reason": "IR-4101 leaver"}
        approval = Approval(
            approver="lead-lee", lever="user.disable", client=CONTOSO, params=params, verification=VERIFIED
        )
        result = self.runner.invoke("user.disable", params, "tech-ana", CONTOSO, mode="execute", approval=approval)
        assert result.status == "ok" and result.applied is True
        return result.audit_seq

    def applied(self, lever: str, params: dict[str, Any], changes: list[dict[str, Any]]) -> int:
        """Append an audit record as if `lever` had been applied (for levers this test does not need to run)."""
        record = self.runner.audit.append(
            agent="tech-ana",
            client=CONTOSO,
            lever=lever,
            params=params,
            mode="execute",
            result={"status": "ok", "reason": "", "applied": True, "changes": changes},
            approver="lead-lee",
        )
        return int(record["seq"])


@pytest.fixture
def env(tmp_path: Path) -> Env:
    tenant_dir = tmp_path / "tenant"
    shutil.copytree(DEFAULT_TENANT_DIR, tenant_dir)
    audit_path = tmp_path / "audit.jsonl"
    runner = LeverRunner(Registry.load(), IdentityStore.load(), MockTenant(tenant_dir), AuditLog(audit_path))
    return Env(runner, ProposalQueue(tmp_path / "queue.jsonl", runner), tenant_dir, audit_path)


# -- B41-1: the undo proposal is built from the recorded before-state ---------------------------------------------


@needs_pwsh
def test_b41_1_builds_a_pending_undo_proposal_from_the_recorded_before_state_in_dry_run(env: Env) -> None:
    seq = env.disable()
    recorded = env.records()[-1]["result"]["changes"]
    assert [(c["before"], c["after"]) for c in recorded] == [(True, False)]
    state_after_disable = env.tenant_bytes()

    rb = plan(env.runner, env.audit_path, seq, "tech-ana", env.queue)

    assert rb.outcome == "proposed" and rb.executed is False
    assert rb.undo_lever == "user.enable" and rb.params == {"upn": JAMIE}
    assert rb.before_state == tuple(recorded)
    proposal = env.queue.get(rb.proposal.id) if rb.proposal else None
    assert proposal is not None and proposal.status == "pending" and proposal.source == "rollback"
    assert proposal.lever == "user.enable" and proposal.requested_by == "tech-ana" and proposal.ref == f"audit-{seq}"
    assert env.tenant_bytes() == state_after_disable  # a proposal changes nothing
    dry = [r for r in env.records() if r["seq"] == rb.dry_run_audit_seq][0]
    assert dry["lever"] == "user.enable" and dry["mode"] == "dry-run" and dry["result"]["applied"] is False
    assert len([r for r in env.records() if r["result"].get("applied") is True]) == 1  # only the disable


@needs_pwsh
def test_b41_1_the_proposal_needs_normal_approval_a_requester_cannot_approve_it(env: Env) -> None:
    rb = plan(env.runner, env.audit_path, env.disable(), "tech-ana", env.queue)
    assert rb.proposal is not None
    before = len(env.records())
    with pytest.raises(DecisionDenied):
        env.queue.decide(rb.proposal.id, "tech-ana", True, VERIFIED)
    denial = env.records()[before:]
    assert len(denial) == 1 and denial[0]["result"]["status"] == "denied" and denial[0]["result"]["applied"] is False
    assert env.queue.get(rb.proposal.id).status == "pending"  # type: ignore[union-attr]


@needs_pwsh
def test_b41_1_without_the_callback_verification_the_runner_refuses_the_approved_undo(env: Env) -> None:
    rb = plan(env.runner, env.audit_path, env.disable(), "tech-ana", env.queue)
    assert rb.proposal is not None
    off = env.tenant_bytes()
    decision = env.queue.decide(rb.proposal.id, "lead-lee", True)  # no verification
    assert decision.proposal.status == "failed" and decision.result is not None
    assert decision.result.status == "denied" and env.tenant_bytes() == off
    assert env.records()[-1]["result"]["status"] == "denied"


@needs_pwsh
def test_b41_1_nothing_is_proposed_when_the_state_is_already_back(env: Env) -> None:
    seq = env.disable()
    first = plan(env.runner, env.audit_path, seq, "tech-ana")  # no queue: just the plan
    assert first.outcome == "proposed" and env.queue.list() == ()
    params = {"upn": JAMIE}
    approval = Approval(approver="lead-lee", lever="user.enable", client=CONTOSO, params=params, verification=VERIFIED)
    assert env.runner.invoke("user.enable", params, "tech-ana", CONTOSO, "execute", approval).applied is True
    again = plan(env.runner, env.audit_path, seq, "tech-ana", env.queue)
    assert again.outcome == "nothing-to-undo" and again.proposal is None and env.queue.list() == ()


@needs_pwsh
def test_b41_1_a_state_that_moved_on_since_is_reported_as_drift_and_nothing_is_proposed(env: Env) -> None:
    # The record says the account went enabled to disabled, but the account is in fact still enabled and something
    # else was recorded: the undo's diff is not the inverse of the record, so a person must look first.
    seq = env.applied(
        "user.disable",
        {"upn": JAMIE, "reason": "x"},
        [{"op": "replace", "path": "/users/3/accountEnabled", "before": "something-else", "after": False}],
    )
    # (the account is enabled in the fixture, so the undo is a real, different change)
    state = json.loads((env.tenant_dir / f"{CONTOSO}.json").read_bytes())
    state["users"] = [dict(u, accountEnabled=False) if u["userPrincipalName"] == JAMIE else u for u in state["users"]]
    MockTenant(env.tenant_dir).save(CONTOSO, state)
    rb = plan(env.runner, env.audit_path, seq, "tech-ana", env.queue)
    assert rb.outcome == "drifted" and rb.proposal is None and env.queue.list() == ()


def test_b41_1_only_an_applied_change_can_be_rolled_back_and_the_refusal_names_why(env: Env) -> None:
    dry = env.runner.invoke("user.disable", {"upn": JAMIE, "reason": "x"}, "triage-bot", CONTOSO)
    assert dry.ok and not dry.applied
    for seq, word in ((dry.audit_seq, "not an applied"), (9999, "no audit record")):
        rb = plan(env.runner, env.audit_path, seq, "tech-ana", env.queue)
        assert rb.outcome == "refused" and word in rb.reason and rb.proposal is None
    assert env.queue.list() == ()


def test_b41_1_a_broken_audit_chain_is_not_trusted(env: Env) -> None:
    seq = env.applied("user.set-properties", {"upn": SAM, "field": "jobTitle", "value": "Hygienist"}, [])
    lines = env.audit_path.read_text(encoding="utf-8").splitlines()
    env.audit_path.write_text(lines[0].replace("Hygienist", "Dentist") + "\n", encoding="utf-8")
    assert not verify_chain(env.audit_path).ok
    rb = plan(env.runner, env.audit_path, seq, "tech-ana", env.queue)
    assert rb.outcome == "refused" and "chain" in rb.reason and rb.proposal is None


# -- B41-2: no undo lever, so print the manual steps and propose nothing -----------------------------------------


def test_b41_2_a_lever_without_undo_prints_the_readme_steps_and_proposes_nothing(env: Env) -> None:
    assert Registry.load().get("user.set-properties").undo is None  # type: ignore[union-attr]
    change = {"op": "replace", "path": "/users/2/jobTitle", "before": "Dental Assistant", "after": "Hygienist"}
    seq = env.applied("user.set-properties", {"upn": SAM, "field": "jobTitle", "value": "Hygienist"}, [change])
    audit_before, tenant_before = env.audit_path.read_bytes(), env.tenant_bytes()

    rb = plan(env.runner, env.audit_path, seq, "tech-ana", env.queue)

    assert rb.outcome == "manual" and rb.proposal is None and rb.undo_lever is None and rb.executed is False
    assert rb.manual_steps is not None and rb.manual_steps.startswith("## user.set-properties")
    assert "Manual undo" in rb.manual_steps and "before-state" in rb.manual_steps
    assert rb.before_state == (change,)  # the old value is printed for the person doing it by hand
    assert env.queue.list() == () and env.tenant_bytes() == tenant_before
    assert env.audit_path.read_bytes() == audit_before  # not even a dry-run: nothing was called


def test_b41_2_a_lever_with_neither_undo_nor_readme_section_says_so(env: Env) -> None:
    seq = env.applied("user.reset-mfa", {"upn": SAM}, [])
    rb = plan(env.runner, env.audit_path, seq, "tech-ana", env.queue)
    assert rb.outcome == "manual" and rb.manual_steps is None and rb.proposal is None
    assert "No README section" in rb.reason and env.queue.list() == ()


def test_b41_2_the_cli_prints_the_manual_steps_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state = tmp_path / "state"
    shutil.copytree(DEFAULT_TENANT_DIR, state / "tenant")
    log = AuditLog(state / "audit" / f"{CONTOSO}.jsonl")  # B-42: one chain per client
    log.append(
        agent="tech-ana",
        client=CONTOSO,
        lever="user.revoke-sessions",
        params={"upn": SAM},
        mode="execute",
        result={"status": "ok", "applied": True, "changes": []},
    )
    assert main(["1", "--client", CONTOSO, "--state", str(state)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["outcome"] == "manual" and out["proposal_id"] is None and "Manual undo" in out["manual_steps"]
    assert main(["77", "--client", CONTOSO, "--state", str(state)]) == 2  # no such record


# -- B41-3: disable, rollback proposal, approval, execute --------------------------------------------------------


@needs_pwsh
def test_b41_3_disable_then_rollback_proposal_approval_execute_restores_the_fixture_byte_for_byte(env: Env) -> None:
    # The committed fixture is hand-formatted; the first write by MockTenant lays it out canonically (see B-29).
    tenant = MockTenant(env.tenant_dir)
    tenant.save(CONTOSO, tenant.load(CONTOSO))
    baseline = env.tenant_bytes()
    sessions = (env.tenant_dir / CONTOSO / "sessions.json").read_bytes()

    disable_seq = env.disable()
    assert env.tenant_bytes() != baseline

    rb = plan(env.runner, env.audit_path, disable_seq, "tech-ana", env.queue)
    assert rb.outcome == "proposed" and rb.proposal is not None
    decision = env.queue.decide(rb.proposal.id, "lead-lee", True, VERIFIED)
    assert decision.proposal.status == "executed" and decision.result is not None and decision.result.applied is True

    assert env.tenant_bytes() == baseline
    assert (env.tenant_dir / CONTOSO / "sessions.json").read_bytes() == sessions
    applied = [r for r in env.records() if r["result"].get("applied") is True]
    assert [(r["lever"], r["mode"]) for r in applied] == [("user.disable", "execute"), ("user.enable", "execute")]
    assert applied[0]["approver"] == applied[1]["approver"] == "lead-lee"
    assert verify_chain(env.audit_path).ok
    assert summary(rb)["executed"] is False  # the workflow itself never executed anything
