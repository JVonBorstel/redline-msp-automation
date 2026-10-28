"""Approval queue (Slice C, SC-1): approve executes through the runner, approver audited; reject changes nothing.

Every test uses its own state folder: a private copy of the synthetic mock tenant, audit log and queue file.
"""

import hashlib
import json
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from core.audit import AuditLog, canonical_json, verify_chain
from core.identity import Identity, IdentityStore, Role
from core.levers import DEFAULT_TENANT_DIR, LeverRunner, MockTenant, Registry
from core.levers.models import Verification
from core.queue import DecisionDenied, Proposal, ProposalQueue, QueueError, open_queue, proposal_id
from core.queue.__main__ import demo_proposals
from core.queue.__main__ import main as queue_cli

CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
JAMIE = "jamie.chen@contosodental.example"
DISABLE_JAMIE = {"upn": JAMIE, "reason": "Left the practice"}


def ident(id_: str, role: Role, *clients: str) -> Identity:
    return Identity(id=id_, display_name=f"{id_} (synthetic)", role=role, clients=clients)


IDENTITIES = IdentityStore(
    [
        ident("tech-ana", Role.TECHNICIAN, CONTOSO),
        ident("lead-lee", Role.LEAD, CONTOSO, FABRIKAM),
        ident("lead-fay", Role.LEAD, FABRIKAM),  # a lead, but not for Contoso
        ident("triage-bot", Role.AGENT, CONTOSO, FABRIKAM),
    ]
)


@pytest.fixture
def queue(tmp_path: Path) -> ProposalQueue:
    shutil.copytree(DEFAULT_TENANT_DIR, tmp_path / "tenant")
    runner = LeverRunner(
        Registry.load(), IDENTITIES, MockTenant(tmp_path / "tenant"), AuditLog(tmp_path / "audit.jsonl")
    )
    return ProposalQueue(tmp_path / "queue.jsonl", runner)


# B-02: identity levers need the requester verified out of band (C-30).
VERIFIED = Verification(method="callback-on-file", by="lead-lee", at=datetime(2026, 10, 20, 9, 0, tzinfo=UTC))


def propose(queue: ProposalQueue, requested_by: str = "tech-ana", **params: Any) -> Proposal:
    return queue.add(
        Proposal.new(
            source="baseline",
            ref="TB-DEMO-STALE-01",
            lever="user.disable",
            client=CONTOSO,
            params=params or DISABLE_JAMIE,
            requested_by=requested_by,
            reason="Leaver account still enabled",
        )
    )


def tenant_bytes(queue: ProposalQueue) -> dict[str, bytes]:
    return {c: queue.runner.tenant.path_for(c).read_bytes() for c in (CONTOSO, FABRIKAM)}


def audit(queue: ProposalQueue) -> list[dict[str, Any]]:
    return [json.loads(line) for line in queue.runner.audit.path.read_text(encoding="utf-8").splitlines()]


def test_proposal_id_follows_the_shared_contract() -> None:
    expected = hashlib.sha256(b"user.disable" + CONTOSO.encode() + canonical_json(DISABLE_JAMIE)).hexdigest()[:12]
    assert proposal_id("user.disable", CONTOSO, DISABLE_JAMIE) == f"P-{expected}"
    assert proposal_id("user.disable", CONTOSO, dict(reversed(DISABLE_JAMIE.items()))) == f"P-{expected}"


def test_add_is_idempotent_and_list_filters_by_status(queue: ProposalQueue) -> None:
    first = propose(queue)
    again = propose(queue)
    assert again == first and len(queue.list()) == 1
    assert queue.list("pending") == (first,) and queue.list("executed") == ()


def test_proposal_with_a_forged_id_is_invalid() -> None:
    good = Proposal.new(
        source="triage", ref="T-1", lever="user.disable", client=CONTOSO, params={}, requested_by="x", reason="r"
    ).model_dump()
    with pytest.raises(ValidationError, match="id does not match"):
        Proposal.model_validate({**good, "params": {"upn": "someone.else@contosodental.example"}})


@pytest.mark.parametrize(
    ("lever", "params", "message"),
    [
        ("ticket.get", {"ticket_id": "T-1001"}, "not a registered write lever"),
        ("tenant.wipe", {}, "not a registered write lever"),
        ("user.disable", {"upn": JAMIE}, "required but missing"),
    ],
)
def test_add_refuses_what_could_never_run(
    queue: ProposalQueue, lever: str, params: dict[str, Any], message: str
) -> None:
    proposal = Proposal.new(
        source="triage", ref="T-1", lever=lever, client=CONTOSO, params=params, requested_by="tech-ana", reason="r"
    )
    with pytest.raises(QueueError, match=message):
        queue.add(proposal)


def test_sc1_approve_executes_against_the_mock_and_audits_the_approver(queue: ProposalQueue) -> None:
    proposal = propose(queue)
    decision = queue.decide(proposal.id, "lead-lee", approve=True, verification=VERIFIED)

    assert decision.proposal.status == "executed" and decision.proposal.decided_by == "lead-lee"
    state = json.loads(tenant_bytes(queue)[CONTOSO])
    assert next(u for u in state["users"] if u["userPrincipalName"] == JAMIE)["accountEnabled"] is False
    record = audit(queue)[-1]
    assert record["seq"] == decision.audit_seq
    assert (record["agent"], record["approver"], record["mode"]) == ("tech-ana", "lead-lee", "execute")
    assert record["result"]["applied"] is True
    history = [json.loads(line)["status"] for line in queue.path.read_text(encoding="utf-8").splitlines()]
    assert history == ["pending", "approved", "executed"]
    assert verify_chain(queue.runner.audit.path, queue.runner.audit.head_path).ok


def test_sc1_reject_changes_nothing_and_is_audited(queue: ProposalQueue) -> None:
    proposal = propose(queue)
    before = tenant_bytes(queue)
    decision = queue.decide(proposal.id, "lead-lee", approve=False)

    assert tenant_bytes(queue) == before, "reject must leave the mock tenant byte-identical"
    assert decision.proposal.status == "rejected"
    record = audit(queue)[-1]
    assert (record["agent"], record["mode"], record["result"]["status"]) == ("lead-lee", "reject", "rejected")
    assert record["result"]["proposal"] == proposal.id and record["result"]["applied"] is False
    with pytest.raises(QueueError, match="already rejected"):
        queue.decide(proposal.id, "lead-lee", approve=True)


@pytest.mark.parametrize(
    ("actor", "requested_by", "message"),
    [
        ("tech-ana", "tech-ana", "tech-ana is not a lead"),
        ("triage-bot", "tech-ana", "triage-bot is not a lead"),
        ("lead-fay", "tech-ana", "not scoped to client 'contoso-dental'"),
        ("mallory", "tech-ana", "unknown identity 'mallory'"),
        ("lead-lee", "lead-lee", "four-eyes rule"),
    ],
)
@pytest.mark.parametrize("approve", [True, False])
def test_only_a_lead_for_the_client_other_than_the_requester_may_decide(
    queue: ProposalQueue, actor: str, requested_by: str, message: str, approve: bool
) -> None:
    proposal = propose(queue, requested_by=requested_by)
    before = tenant_bytes(queue)
    with pytest.raises(DecisionDenied, match=message):
        queue.decide(proposal.id, actor, approve=approve)
    assert tenant_bytes(queue) == before
    assert queue.get(proposal.id) == proposal, "a denied decision leaves the proposal pending"
    assert (audit(queue)[-1]["agent"], audit(queue)[-1]["result"]["status"]) == (actor, "denied")


def test_the_runner_still_decides_an_agent_requested_write_fails(queue: ProposalQueue) -> None:
    proposal = propose(queue, requested_by="triage-bot")
    before = tenant_bytes(queue)
    decision = queue.decide(proposal.id, "lead-lee", approve=True)
    assert decision.proposal.status == "failed"
    assert decision.result is not None and "role 'agent' cannot execute" in decision.result.reason
    assert tenant_bytes(queue) == before


def test_two_concurrent_approvals_execute_once(queue: ProposalQueue) -> None:
    proposal = propose(queue)
    outcomes: list[str] = []

    def approve() -> None:
        try:
            outcomes.append(queue.decide(proposal.id, "lead-lee", approve=True, verification=VERIFIED).proposal.status)
        except QueueError as exc:
            outcomes.append(str(exc))

    threads = [threading.Thread(target=approve) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes)[-1] == "executed" and outcomes.count("executed") == 1
    assert sum(1 for r in audit(queue) if r["mode"] == "execute") == 1


def test_seed_demo_writes_three_pending_proposals_idempotently(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert queue_cli(["--state", str(tmp_path), "seed", "--demo"]) == 0
    assert queue_cli(["--state", str(tmp_path), "seed", "--demo"]) == 0
    stored = open_queue(tmp_path).list("pending")
    assert [p.id for p in stored] == [p.id for p in demo_proposals()]
    assert {p.lever for p in stored} == {"user.reset-mfa", "user.disable"}
    assert (tmp_path / "tenant" / f"{CONTOSO}.json").exists()
    capsys.readouterr()
