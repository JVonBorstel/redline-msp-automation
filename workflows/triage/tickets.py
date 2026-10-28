"""Synthetic service-desk tickets (fixtures/tickets/<client>.json) and their gold labels.

A ticket has two kinds of fields. ``subject`` and ``body`` are free text typed by the requester: untrusted, so
triage wraps them before a model sees them and never takes a lever or a parameter from them. ``requester``,
``affected_user`` and ``technician`` are PSA form fields, the only place a lever parameter may come from, and the
lever runner still checks them (schema, client scope, the user existing in that client's tenant).

``labels`` hold the answers a lead would give. They live beside the ticket for the eval and never reach triage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

DEFAULT_TICKETS_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "tickets"

Category = Literal[
    "security", "offboarding", "mfa", "account-access", "email", "network", "hardware", "software", "other"
]
Priority = Literal["low", "medium", "high", "critical"]
Queue = Literal["security", "identity", "service-desk", "network", "onsite"]

TicketId = Annotated[str, StringConstraints(pattern=r"^T-[0-9]{4}$")]
ClientId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")]
Upn = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", max_length=113)]

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class TicketError(ValueError):
    """The ticket fixtures are missing or malformed, or a ticket id is unknown."""


class Ticket(BaseModel):
    """What triage sees: the ticket without its labels."""

    model_config = _FROZEN

    id: TicketId
    client: ClientId
    subject: str = Field(max_length=200)
    body: str = Field(max_length=4000)
    requester: Upn
    affected_user: Upn | None = None
    technician: str = Field(min_length=1, max_length=64)

    @property
    def text(self) -> str:
        """The untrusted free text, as one block."""
        return f"Subject: {self.subject}\n\n{self.body}"


class Labels(BaseModel):
    """Gold answers for one ticket. ``expected_lever`` is the lever a correct triage proposes, or None."""

    model_config = _FROZEN

    category: Category
    priority: Priority
    queue: Queue
    expected_lever: str | None
    injection: bool
    note: str = ""


class LabelledTicket(Ticket):
    labels: Labels

    def unlabelled(self) -> Ticket:
        return Ticket.model_validate(self.model_dump(exclude={"labels"}))


class _TicketFile(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    note: str = Field(alias="_note", default="")
    client: ClientId
    tickets: list[LabelledTicket]


def load_tickets(root: Path = DEFAULT_TICKETS_DIR) -> list[LabelledTicket]:
    """Every ticket under ``root``, sorted by id. Fails closed on a bad file, a client mismatch or a duplicate id."""
    tickets: dict[str, LabelledTicket] = {}
    files = sorted(Path(root).glob("*.json"))
    if not files:
        raise TicketError(f"no ticket fixtures in {root}")
    for path in files:
        try:
            parsed = _TicketFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, ValidationError) as exc:
            raise TicketError(f"cannot load tickets from {path}: {exc}") from exc
        for ticket in parsed.tickets:
            if ticket.client != parsed.client:
                raise TicketError(f"{ticket.id} is in {path.name} but names client {ticket.client!r}")
            if ticket.id in tickets:
                raise TicketError(f"ticket id {ticket.id} appears twice")
            tickets[ticket.id] = ticket
    return [tickets[i] for i in sorted(tickets)]


def get_ticket(ticket_id: str, root: Path = DEFAULT_TICKETS_DIR) -> LabelledTicket:
    for ticket in load_tickets(root):
        if ticket.id == ticket_id:
            return ticket
    raise TicketError(f"no ticket {ticket_id!r} in {root}")
