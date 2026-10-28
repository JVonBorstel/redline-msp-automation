"""AI ticket triage for technicians (specs/slices-abc.md, Slice A).

    runner = LeverRunner(Registry.load(), IdentityStore.load(), MockTenant(), AuditLog(path))
    result = triage(ticket, classify_gateway("mock"), runner)
    print(result.explain())

The model (mock by default) only names a category for the wrapped, untrusted ticket text. Rules set priority and
queue and choose at most one registered lever, which runs in dry-run as the triage agent and comes back as a
pending proposal for a lead. A ticket flagged for prompt injection gets no lever; it is reported.
"""

from workflows.triage.corrections import (
    DEFAULT_CORRECTIONS_PATH,
    Correction,
    CorrectionError,
    apply_corrections,
    load_corrections,
    record_correction,
)
from workflows.triage.proposal import make_proposal, proposal_id
from workflows.triage.tickets import DEFAULT_TICKETS_DIR, LabelledTicket, Ticket, TicketError, get_ticket, load_tickets
from workflows.triage.triage import TRIAGE_AGENT, TriageResult, classify_gateway, triage

__all__ = [
    "DEFAULT_CORRECTIONS_PATH",
    "DEFAULT_TICKETS_DIR",
    "TRIAGE_AGENT",
    "Correction",
    "CorrectionError",
    "LabelledTicket",
    "Ticket",
    "TicketError",
    "TriageResult",
    "apply_corrections",
    "classify_gateway",
    "get_ticket",
    "load_corrections",
    "load_tickets",
    "make_proposal",
    "proposal_id",
    "record_correction",
    "triage",
]
