"""Approval queue: a lead approves or rejects pending write-lever proposals (Slice C).

Typical use (the proposal contract is in store.py):

    queue = open_queue(Path(".tmp/demo"))
    queue.add(Proposal.new(source="baseline", ref="TB-STALE-01", lever="user.disable", ...))
    decision = queue.decide(proposal_id, approver="lead-lee", approve=True)  # executes through the runner
"""

from core.queue.store import (
    DEFAULT_STATE_DIR,
    Decision,
    DecisionDenied,
    Proposal,
    ProposalQueue,
    QueueError,
    open_queue,
    proposal_id,
)

__all__ = [
    "DEFAULT_STATE_DIR",
    "Decision",
    "DecisionDenied",
    "Proposal",
    "ProposalQueue",
    "QueueError",
    "open_queue",
    "proposal_id",
]
