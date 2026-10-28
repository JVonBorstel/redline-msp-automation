"""B-28 dual approval in the queue: a partial approval, a second distinct lead, then one execute with both.

Change note: docs/changes/B-28-dual-approval.md. Ids B28D-1 to B28D-6 (specs/B-28.md, "Dual approval in the queue").
Every test is offline, on a private copy of the synthetic mock tenant under tmp_path, with the runner clock pinned and
moved by hand; committed files are never modified. Approvals here come from the demo picker (RunnerPolicy(demo=True)),
which is not authentication; the signed-in (token) path is in tests/py/ui/test_b28_page_dual.py.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/queue/test_b28_queue_dual.py
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from core.audit import canonical_json, verify_chain
from core.audit.router import AuditRouter
from core.auth import ApproverAuth
from core.identity import Identity, IdentityStore, Role
from core.levers import DEFAULT_TENANT_DIR, Approval, LeverRunner, MockTenant, Registry
from core.levers.models import ContactConfirmation, Verification
from core.levers.runner import RunnerPolicy
from core.queue import AWAITING, DecisionDenied, Proposal, ProposalQueue, QueueError, open_queue

CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
NOW = datetime(2026, 10, 21, 17, 0, tzinfo=UTC)
CONTACT = "contact-1"
EVERY_DAY = {"days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "start": "00:00", "end": "23:59"}
RECORDS: dict[str, dict[str, Any]] = {
    CONTOSO: {"time_zone": "UTC", "business_hours": EVERY_DAY, "authorized_contacts": [CONTACT]},
}
MFA_UPN = "ana.lopez@contosodental.example"


def ident(id_: str, role: Role, *clients: str) -> Identity:
    return Identity(id=id_, display_name=f"{id_} (synthetic)", role=role, clients=clients)


IDENTITIES = IdentityStore(
    [
        ident("tech-ana", Role.TECHNICIAN, CONTOSO),
        ident("lead-lee", Role.LEAD, CONTOSO, FABRIKAM),
        ident("lead-mia", Role.LEAD, CONTOSO, FABRIKAM),
        ident("lead-gus", Role.LEAD, CONTOSO),
        ident("lead-fab", Role.LEAD, FABRIKAM),
        ident("triage-bot", Role.AGENT, CONTOSO, FABRIKAM),
    ]
)


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def make_runner(tmp: Path, clock: Clock, *, policy: bool = True) -> LeverRunner:
    tenant = tmp / "tenant"
    if not tenant.exists():
        shutil.copytree(DEFAULT_TENANT_DIR, tenant)
    return LeverRunner(
        Registry.load(),
        IDENTITIES,
        MockTenant(tenant),
        AuditRouter(tmp / "audit"),
        policy=RunnerPolicy(demo=True, client_records=RECORDS) if policy else None,
        clock=clock,
    )


def make_queue(tmp: Path, clock: Clock | None = None, *, policy: bool = True) -> ProposalQueue:
    return ProposalQueue(tmp / "queue.jsonl", make_runner(tmp, clock or Clock(), policy=policy))


def mfa(requested_by: str = "tech-ana", upn: str = MFA_UPN) -> Proposal:
    return Proposal.new(
        source="triage",
        ref="T-2801",
        lever="user.reset-mfa",
        client=CONTOSO,
        params={"upn": upn},
        requested_by=requested_by,
        reason="Lost phone: reset MFA (B-28 dual approval test)",
    )


def callback(by: str = "lead-lee") -> Verification:
    return Verification(
        method="callback-on-file", by=by, at=NOW - timedelta(minutes=5), ref="number-on-file:psa-contact"
    )


def demo(who: str) -> ApproverAuth:
    return ApproverAuth.demo(who)


def approve(queue: ProposalQueue, pid: str, who: str, **kw: Any) -> Any:
    kw.setdefault("auth", demo(who))
    return queue.decide(pid, who, approve=True, **kw)


def audit(tmp: Path, client: str = CONTOSO) -> list[dict[str, Any]]:
    path = tmp / "audit" / f"{client}.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def methods(tmp: Path, upn: str = MFA_UPN) -> Any:
    state = json.loads((tmp / "tenant" / f"{CONTOSO}.json").read_text(encoding="utf-8"))
    return next(u for u in state["users"] if u["userPrincipalName"] == upn)["authentication"]["methods"]


@pytest.fixture
def queued(tmp_path: Path) -> tuple[ProposalQueue, Proposal, Clock]:
    clock = Clock()
    queue = make_queue(tmp_path, clock)
    proposal, dry_run = queue.propose(mfa(), "triage-bot")
    assert dry_run is not None and dry_run.ok, dry_run
    return queue, proposal, clock


# -- B28D-1 the first lead records a partial approval ------------------------------------------------------------


def test_b28d_1_the_first_lead_records_a_partial_approval_and_nothing_executes(
    tmp_path: Path, queued: tuple[ProposalQueue, Proposal, Clock]
) -> None:
    queue, proposal, _ = queued
    before = methods(tmp_path)
    decision = approve(queue, proposal.id, "lead-lee", verification=callback())
    partial = decision.proposal
    assert partial.status == AWAITING == "awaiting-second-approval"
    assert decision.result is None and partial.decided_by is None
    assert [a.approver for a in partial.approvals] == ["lead-lee"]
    first = partial.approvals[0]
    assert first.auth.method == "demo-picker" and first.auth.identity == "lead-lee"
    assert first.verification == callback() and first.approved_at == NOW
    assert first.attestation is not None and first.attestation.approver == "lead-lee"
    assert first.digest == partial.digest
    assert partial.verification == callback()
    assert methods(tmp_path) == before, "a partial approval applies nothing"
    record = audit(tmp_path)[-1]
    assert record["agent"] == "lead-lee" and record["approver"] == "lead-lee" and record["mode"] == "approve"
    assert record["result"]["status"] == "awaiting-second-approval" and record["result"]["applied"] is False
    assert record["result"]["approvers_required"] == 2 and record["result"]["approvals_given"] == 1
    assert record["result"]["approver_auth"]["method"] == "demo-picker"
    assert queue.get(proposal.id) == partial
    assert queue.list(status=AWAITING) == (partial,)


def test_b28d_1_a_partial_approval_needs_the_requester_verification_and_a_sign_in(
    tmp_path: Path, queued: tuple[ProposalQueue, Proposal, Clock]
) -> None:
    queue, proposal, _ = queued
    with pytest.raises(DecisionDenied, match="requester verification"):
        approve(queue, proposal.id, "lead-lee")
    with pytest.raises(DecisionDenied, match="not authenticated"):
        queue.decide(proposal.id, "lead-lee", approve=True, verification=callback(), auth=None)
    assert queue.get(proposal.id) == proposal
    reasons = [r["result"]["reason"] for r in audit(tmp_path)[-2:]]
    assert all(r["result"]["status"] == "denied" for r in audit(tmp_path)[-2:]), reasons


# -- B28D-2 a second, different lead completes it -----------------------------------------------------------------


def test_b28d_2_a_second_different_lead_completes_it_and_the_runner_gets_both(
    tmp_path: Path, queued: tuple[ProposalQueue, Proposal, Clock]
) -> None:
    queue, proposal, clock = queued
    approve(queue, proposal.id, "lead-lee", verification=callback())
    clock.now = NOW + timedelta(hours=2)
    decision = approve(queue, proposal.id, "lead-mia")
    done = decision.proposal
    assert done.status == "executed", decision.result
    assert decision.result is not None and decision.result.applied
    assert decision.result.approver == "lead-lee,lead-mia"
    assert done.decided_by == "lead-mia" and done.approver_auth == demo("lead-mia")
    assert [a.approver for a in done.approvals] == ["lead-lee", "lead-mia"]
    assert done.verification == callback()
    assert [m["@odata.type"] for m in methods(tmp_path)] == ["#microsoft.graph.passwordAuthenticationMethod"]
    execute = next(r for r in audit(tmp_path) if r["mode"] == "execute")
    assert execute["agent"] == "tech-ana" and execute["approver"] == "lead-lee,lead-mia"
    signins = execute["result"]["approvals"]
    assert [s["approver"] for s in signins] == ["lead-lee", "lead-mia"]
    assert all(s["auth"] == "demo-picker" and s["demo"] is True for s in signins)
    assert signins[0]["attested_at"] == NOW.isoformat()
    assert execute["result"]["approvers_required"] == 2
    assert verify_chain(tmp_path / "audit" / f"{CONTOSO}.jsonl").ok


def test_b28d_2_a_lever_that_needs_three_stays_awaiting_after_two(tmp_path: Path) -> None:
    records = {CONTOSO: {**RECORDS[CONTOSO], "approver_minimum": {"R3": 3}}}
    runner = make_runner(tmp_path, Clock())
    runner.policy = RunnerPolicy(demo=True, client_records=records)
    queue = ProposalQueue(tmp_path / "queue.jsonl", runner)
    proposal, _ = queue.propose(mfa(), "triage-bot")
    approve(queue, proposal.id, "lead-lee", verification=callback())
    second = approve(queue, proposal.id, "lead-mia").proposal
    assert second.status == AWAITING and [a.approver for a in second.approvals] == ["lead-lee", "lead-mia"]
    third = approve(queue, proposal.id, "lead-gus")
    assert third.proposal.status == "executed", third.result
    assert third.result is not None and third.result.approver == "lead-lee,lead-mia,lead-gus"


# -- B28D-3 refused and audited: the same lead twice, the requester, stale, a changed proposal ------------------


def test_b28d_3_the_same_lead_twice_is_refused_audited_and_still_awaiting(
    tmp_path: Path, queued: tuple[ProposalQueue, Proposal, Clock]
) -> None:
    queue, proposal, _ = queued
    partial = approve(queue, proposal.id, "lead-lee", verification=callback()).proposal
    count = len(audit(tmp_path))
    with pytest.raises(DecisionDenied, match="already approved") as caught:
        approve(queue, proposal.id, "lead-lee")
    assert "different lead" in str(caught.value)
    assert queue.get(proposal.id) == partial
    assert len(audit(tmp_path)) == count + 1
    record = audit(tmp_path)[-1]
    assert record["result"]["status"] == "denied" and record["agent"] == "lead-lee"
    assert not any(r["mode"] == "execute" for r in audit(tmp_path))


def test_b28d_3_the_requester_cannot_be_either_approver(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    proposal, _ = queue.propose(mfa(requested_by="lead-mia"), "triage-bot")
    with pytest.raises(DecisionDenied, match="four-eyes"):
        approve(queue, proposal.id, "lead-mia", verification=callback("lead-mia"))
    approve(queue, proposal.id, "lead-lee", verification=callback())
    with pytest.raises(DecisionDenied, match="four-eyes"):
        approve(queue, proposal.id, "lead-mia")
    assert queue.get(proposal.id).status == AWAITING  # type: ignore[union-attr]
    assert [r["result"]["status"] for r in audit(tmp_path) if r["agent"] == "lead-mia"] == ["denied", "denied"]


def test_b28d_3_a_lead_not_scoped_to_the_client_cannot_complete(
    tmp_path: Path, queued: tuple[ProposalQueue, Proposal, Clock]
) -> None:
    queue, proposal, _ = queued
    approve(queue, proposal.id, "lead-lee", verification=callback())
    with pytest.raises(DecisionDenied, match="not scoped"):
        approve(queue, proposal.id, "lead-fab")
    assert queue.get(proposal.id).status == AWAITING  # type: ignore[union-attr]


def test_b28d_3_a_first_approval_older_than_the_age_limit_is_refused_and_voided(
    tmp_path: Path, queued: tuple[ProposalQueue, Proposal, Clock]
) -> None:
    queue, proposal, clock = queued
    before = methods(tmp_path)
    approve(queue, proposal.id, "lead-lee", verification=callback())
    clock.now = NOW + timedelta(hours=24)
    with pytest.raises(DecisionDenied, match="older than"):
        approve(queue, proposal.id, "lead-mia")
    again = queue.get(proposal.id)
    assert again is not None and again.status == "pending" and again.approvals == ()
    assert methods(tmp_path) == before
    record = audit(tmp_path)[-1]
    assert record["result"]["status"] == "denied" and record["agent"] == "lead-mia"
    assert "older than" in record["result"]["reason"]
    # just under the limit still works, from a fresh start
    approve(queue, proposal.id, "lead-lee", verification=callback())
    clock.now = clock.now + timedelta(hours=23, minutes=59)
    assert approve(queue, proposal.id, "lead-mia").proposal.status == "executed"


def test_b28d_3_a_second_approval_for_a_changed_proposal_is_refused_and_voided(
    tmp_path: Path, queued: tuple[ProposalQueue, Proposal, Clock]
) -> None:
    queue, proposal, _ = queued
    partial = approve(queue, proposal.id, "lead-lee", verification=callback()).proposal
    # The stored proposal changes under the partial approval (same id, a different reason and requester).
    changed = partial.model_copy(update={"reason": "Changed after the first approval", "requested_by": "tech-ana"})
    with (tmp_path / "queue.jsonl").open("ab") as fh:
        fh.write(canonical_json(changed.model_dump(mode="json")) + b"\n")
    with pytest.raises(DecisionDenied, match="changed since"):
        approve(queue, proposal.id, "lead-mia")
    again = queue.get(proposal.id)
    assert again is not None and again.status == "pending" and again.approvals == ()
    assert audit(tmp_path)[-1]["result"]["status"] == "denied"
    assert not any(r["mode"] == "execute" for r in audit(tmp_path))


def test_b28d_3_a_second_approval_of_what_the_page_showed_must_match(
    tmp_path: Path, queued: tuple[ProposalQueue, Proposal, Clock]
) -> None:
    queue, proposal, _ = queued
    partial = approve(queue, proposal.id, "lead-lee", verification=callback()).proposal
    with pytest.raises(DecisionDenied, match="changed since"):
        approve(queue, proposal.id, "lead-mia", seen_digest="0" * 64)
    assert queue.get(proposal.id) == partial, "a stale page is refused; the stored partial stays"
    assert approve(queue, proposal.id, "lead-mia", seen_digest=partial.digest).proposal.status == "executed"


def test_b28d_3_a_partial_approval_from_another_runner_process_is_refused(
    tmp_path: Path, queued: tuple[ProposalQueue, Proposal, Clock]
) -> None:
    queue, proposal, _ = queued
    approve(queue, proposal.id, "lead-lee", verification=callback())
    restarted = ProposalQueue(tmp_path / "queue.jsonl", make_runner(tmp_path, Clock()))
    with pytest.raises(DecisionDenied, match="sign-in proof"):
        approve(restarted, proposal.id, "lead-mia")
    assert restarted.get(proposal.id).status == "pending"  # type: ignore[union-attr]


def test_b28d_3_a_forged_attestation_is_refused_by_the_runner(
    tmp_path: Path, queued: tuple[ProposalQueue, Proposal, Clock]
) -> None:
    queue, proposal, _ = queued
    partial = approve(queue, proposal.id, "lead-lee", verification=callback()).proposal
    att = partial.approvals[0].attestation
    assert att is not None
    params = dict(proposal.params)
    base = {"lever": proposal.lever, "client": CONTOSO, "params": params, "verification": callback()}
    forged = att.model_copy(update={"approver": "lead-gus"})
    tampered = [
        Approval(approver="lead-gus", attestation=forged, approved_at=NOW, **base),
        Approval(approver="lead-mia", demo=True, approved_at=NOW, **base),
    ]
    result = queue.runner.invoke(proposal.lever, params, "tech-ana", CONTOSO, "execute", tampered)
    assert result.status == "denied" and "attestation" in result.reason
    other = Approval(
        approver="lead-lee", attestation=att, approved_at=NOW, **{**base, "params": {"upn": "x@y.example"}}
    )
    result = queue.runner.invoke(proposal.lever, {"upn": "x@y.example"}, "tech-ana", CONTOSO, "execute", other)
    assert result.status == "denied"


# -- B28D-4 rejection by either lead closes it -------------------------------------------------------------------


@pytest.mark.parametrize("rejecter", ["lead-lee", "lead-mia"])
def test_b28d_4_rejection_by_either_lead_closes_it(
    tmp_path: Path, queued: tuple[ProposalQueue, Proposal, Clock], rejecter: str
) -> None:
    queue, proposal, _ = queued
    before = methods(tmp_path)
    approve(queue, proposal.id, "lead-lee", verification=callback())
    decision = queue.decide(proposal.id, rejecter, approve=False, auth=demo(rejecter))
    assert decision.proposal.status == "rejected" and decision.proposal.decided_by == rejecter
    assert decision.proposal.verification is None
    assert [a.approver for a in decision.proposal.approvals] == ["lead-lee"], "the partial stays as history"
    assert methods(tmp_path) == before
    assert audit(tmp_path)[-1]["result"]["status"] == "rejected"
    with pytest.raises(QueueError, match="already rejected"):
        approve(queue, proposal.id, "lead-gus")


# -- B28D-5 non-R3 levers keep the single-approval path ---------------------------------------------------------


def test_b28d_5_an_r2_lever_executes_on_one_signed_in_approval(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    proposal, _ = queue.propose(
        Proposal.new(
            source="triage",
            ref="T-2802",
            lever="inboxrule.disable",
            client=CONTOSO,
            params={"upn": "priya.nair@contosodental.example", "rule_id": "IR-CD-0002"},
            requested_by="tech-ana",
            reason="Suspicious rule hides invoices (B-28 R2 single path)",
        ),
        "triage-bot",
    )
    decision = approve(queue, proposal.id, "lead-lee")
    assert decision.proposal.status == "executed", decision.result
    assert decision.result is not None and decision.result.approver == "lead-lee"
    assert decision.proposal.approvals == ()
    execute = audit(tmp_path)[-1]
    assert execute["result"]["approvals"] == [{"approver": "lead-lee", "auth": "demo-picker", "demo": True}]


def test_b28d_5_without_a_runner_policy_the_w1_single_approval_path_is_unchanged(tmp_path: Path) -> None:
    queue = make_queue(tmp_path, policy=False)
    proposal, _ = queue.propose(mfa(), "triage-bot")
    decision = queue.decide(proposal.id, "lead-lee", approve=True, verification=callback())
    assert decision.proposal.status == "executed" and decision.proposal.approvals == ()


def test_b28d_5_open_queue_takes_a_policy(tmp_path: Path) -> None:
    queue = open_queue(tmp_path, policy=RunnerPolicy(demo=True))
    assert queue.runner.policy is not None and queue.runner.policy.demo
    assert open_queue(tmp_path / "w1").runner.policy is None


# -- B28D-6 requester+contact (B-65 levers) ---------------------------------------------------------------------


def test_b28d_6_a_requester_contact_lever_needs_the_callback_and_the_authorized_contact(tmp_path: Path) -> None:
    queue = make_queue(tmp_path, Clock(datetime(2026, 10, 21, 17, 0, tzinfo=UTC)))
    device = "c0000000-0000-4000-8000-0000000d0006"
    proposal = queue.add(
        Proposal.new(
            source="triage",
            ref="T-2803",
            lever="device.lock",
            client=CONTOSO,
            params={"device": device, "upn": "lena.fischer@contosodental.example"},
            requested_by="tech-ana",
            reason="Laptop reported stolen (B-28 dual approval, requester+contact)",
        )
    )
    with pytest.raises(DecisionDenied, match="authorized contact"):
        approve(queue, proposal.id, "lead-lee", verification=callback())
    in_person = Verification(method="in-person", by="lead-lee", at=NOW - timedelta(minutes=5))
    contact = ContactConfirmation(by="lead-lee", at=NOW - timedelta(minutes=4), contact=CONTACT)
    with pytest.raises(DecisionDenied, match="requester verification"):
        approve(queue, proposal.id, "lead-lee", verification=in_person, contact=contact)
    stranger = ContactConfirmation(by="lead-lee", at=NOW - timedelta(minutes=4), contact="contact-9")
    with pytest.raises(DecisionDenied, match="not an authorized contact"):
        approve(queue, proposal.id, "lead-lee", verification=callback(), contact=stranger)
    partial = approve(queue, proposal.id, "lead-lee", verification=callback(), contact=contact).proposal
    assert partial.status == AWAITING and partial.approvals[0].contact_verification == contact
    assert all(r["result"]["status"] == "denied" for r in audit(tmp_path)[:3])
