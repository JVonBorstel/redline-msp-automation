"""Intake proposal (W-SD-01): client, contact and a short summary for one ticket (B-22; C-12, C-13, C-27).

The client and the contact are looked up, never chosen by a model: the sender address is compared with the contacts of
each client's own PSA adapter (the vendor-neutral read-only interface from B-18). The affected user is matched only
against the proposed client's contacts. The summary is the only free text; a summariser hook (a model later) may write
it but its output is checked, length-limited and used as the summary and nothing else. Nothing is saved to the PSA:
the dispatcher confirms the proposal.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from adapters import PsaAdapter
from core.guard import detect_injection
from workflows.summary.common import IntakeTicket, sentences

SUMMARY_MAX = 400
MAX_BODY_SENTENCES = 3
PART_SEP = " | "
_EMAIL = re.compile(r"^[a-z0-9._%+-]{1,64}@[a-z0-9.-]{1,120}\.[a-z]{2,}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

Summariser = Callable[[str, str], str]  # (subject, body) -> one-line summary. Gets the ticket text and nothing else.
How = Literal["email", "domain", "ambiguous", "none"]
AffectedState = Literal["same-as-sender", "contact", "not-a-contact-of-this-client", "no-client", "none"]


@dataclass(frozen=True, slots=True)
class AffectedMatch:
    state: AffectedState
    contact_id: int | None = None
    contact_name: str | None = None


@dataclass(frozen=True, slots=True)
class IntakeMatch:
    """Where the sender belongs. ``client`` and ``contact_id`` are set only from PSA contact lists."""

    how: How
    client: str | None
    contact_id: int | None
    contact_name: str | None
    inactive: bool
    affected: AffectedMatch
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Summary:
    text: str
    flagged: bool
    rules: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IntakeProposal:
    ticket_id: str
    match: IntakeMatch
    summary: Summary


def _name(contact: Mapping[str, object]) -> str:
    return f"{contact.get('firstName', '')} {contact.get('lastName', '')}".strip()


def _contacts(adapter: PsaAdapter) -> list[dict[str, object]]:
    result = adapter.list_contacts()
    return list(result.data) if result.ok and result.data is not None else []


def _norm(address: str | None) -> str:
    return (address or "").strip().lower()


def _domain(address: str) -> str:
    return address.rpartition("@")[2]


def _match_affected(
    ticket: IntakeTicket, sender: str, client: str | None, contacts: list[dict[str, object]]
) -> AffectedMatch:
    affected = _norm(ticket.affected_user)
    if not affected:
        return AffectedMatch("none")
    if affected == sender:
        return AffectedMatch("same-as-sender")
    if client is None:
        return AffectedMatch("no-client")
    for contact in contacts:  # only the proposed client's own contacts are ever searched
        if _norm(str(contact.get("emailAddress", ""))) == affected:
            raw_id = contact.get("id")
            return AffectedMatch("contact", raw_id if isinstance(raw_id, int) else None, _name(contact))
    return AffectedMatch("not-a-contact-of-this-client")


def match_intake(ticket: IntakeTicket, adapters: Mapping[str, PsaAdapter]) -> IntakeMatch:
    """Propose client and contact from the sender address and the clients' PSA contacts (B22-1).

    Exact address at exactly one client: that client and contact. At two or more: ``ambiguous``, nothing proposed.
    No exact match but a domain that only one client's contacts use: that client, no contact. Otherwise ``none``.
    The ticket's own ``client`` field is not read.
    """
    sender = _norm(ticket.requester)
    if not _EMAIL.fullmatch(sender):
        return IntakeMatch(
            "none", None, None, None, False, AffectedMatch("none"), ("the sender is not an email address",)
        )
    book = {client: _contacts(adapter) for client, adapter in sorted(adapters.items())}
    exact = [
        (client, contact)
        for client, contacts in book.items()
        for contact in contacts
        if _norm(str(contact.get("emailAddress", ""))) == sender
    ]
    exact_clients = sorted({client for client, _ in exact})
    if len(exact_clients) > 1:
        note = "the sender address is a contact at more than one client; a person picks the client"
        return IntakeMatch("ambiguous", None, None, None, False, AffectedMatch("no-client"), (note,))
    if len(exact_clients) == 1:
        client, contact = exact[0]
        raw_id = contact.get("id")
        inactive = contact.get("isActive") in (0, False)
        notes = ("the matching contact is marked inactive in the PSA",) if inactive else ()
        affected = _match_affected(ticket, sender, client, book[client])
        return IntakeMatch(
            "email", client, raw_id if isinstance(raw_id, int) else None, _name(contact), inactive, affected, notes
        )
    domain = _domain(sender)
    by_domain = sorted(
        client
        for client, contacts in book.items()
        if any(_domain(_norm(str(c.get("emailAddress", "")))) == domain for c in contacts)
    )
    if len(by_domain) == 1:
        client = by_domain[0]
        note = "the sender is not one of this client's contacts; a person picks or creates the contact"
        return IntakeMatch(
            "domain", client, None, None, False, _match_affected(ticket, sender, client, book[client]), (note,)
        )
    return IntakeMatch(
        "none", None, None, None, False, AffectedMatch("no-client"), ("no client has this sender or domain",)
    )


def rules_summary(ticket: IntakeTicket) -> str:
    """The subject then the first sentences of the body, verbatim, joined by `` | `` and at most 400 characters."""
    parts = [ticket.subject.strip()]
    for sentence in sentences(ticket.body)[:MAX_BODY_SENTENCES]:
        if len(PART_SEP.join([*parts, sentence])) > SUMMARY_MAX:
            break
        parts.append(sentence)
    return PART_SEP.join(parts)[:SUMMARY_MAX]


def _check_output(text: object) -> str | None:
    """Why a summariser's output is unusable, or None."""
    if not isinstance(text, str) or not text.strip():
        return "empty or not text"
    if len(text) > SUMMARY_MAX:
        return f"longer than {SUMMARY_MAX} characters"
    if _CONTROL.search(text):
        return "control characters or line breaks"
    if detect_injection(text).flagged:
        return "it looks like an instruction"
    return None


def summarise(ticket: IntakeTicket, *, summariser: Summariser | None = None) -> Summary:
    """A short summary. A flagged ticket is reported, not summarised, and never reaches the summariser (C-13)."""
    detection = detect_injection(ticket.subject + "\n\n" + ticket.body)
    if detection.flagged:
        rules = tuple(sorted(detection.rules))
        text = (
            f"Flagged: the ticket text looks like an instruction to the assistant (rules: {', '.join(rules)}). "
            "It was not summarised and not acted on; a person should read the ticket."
        )
        return Summary(text, True, rules)
    if summariser is not None:
        try:
            produced: object = summariser(ticket.subject, ticket.body)
        except Exception as exc:  # a failing model must not stop intake
            return Summary(
                rules_summary(ticket),
                False,
                (),
                (f"summariser failed ({type(exc).__name__}); used the rule-based summary",),
            )
        problem = _check_output(produced)
        if problem is None:
            return Summary(str(produced).strip(), False)
        return Summary(
            rules_summary(ticket), False, (), (f"summariser output rejected ({problem}); used the rule-based summary",)
        )
    return Summary(rules_summary(ticket), False)


def propose(
    ticket: IntakeTicket, adapters: Mapping[str, PsaAdapter], *, summariser: Summariser | None = None
) -> IntakeProposal:
    """Client, contact and summary for one ticket. The summariser can change the summary text and nothing else."""
    return IntakeProposal(ticket.id, match_intake(ticket, adapters), summarise(ticket, summariser=summariser))
