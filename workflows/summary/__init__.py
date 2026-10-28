"""Ticket summaries, intake matching and escalation context packages (B-22). Proposals and fact packs for a person.

proposal = propose(ticket, load_adapters())       # client + contact from PSA contacts, short summary
result = build_package("T-5301", adapters["litware-legal"], DeviceFacts(MockTenant()))   # every fact cites its source
"""

from workflows.summary.common import (
    DEFAULT_PSA_DIR,
    DEFAULT_TICKETS_DIR,
    IntakeTicket,
    SummaryError,
    get_ticket,
    load_adapters,
    load_tickets,
)
from workflows.summary.intake import (
    SUMMARY_MAX,
    AffectedMatch,
    IntakeMatch,
    IntakeProposal,
    Summary,
    match_intake,
    propose,
    rules_summary,
    summarise,
)
from workflows.summary.package import (
    DeviceFacts,
    EscalationPackage,
    Fact,
    PackageResult,
    build_package,
    trace_facts,
)

__all__ = [
    "DEFAULT_PSA_DIR",
    "DEFAULT_TICKETS_DIR",
    "SUMMARY_MAX",
    "AffectedMatch",
    "DeviceFacts",
    "EscalationPackage",
    "Fact",
    "IntakeMatch",
    "IntakeProposal",
    "IntakeTicket",
    "PackageResult",
    "Summary",
    "SummaryError",
    "build_package",
    "get_ticket",
    "load_adapters",
    "load_tickets",
    "match_intake",
    "propose",
    "rules_summary",
    "summarise",
    "trace_facts",
]
