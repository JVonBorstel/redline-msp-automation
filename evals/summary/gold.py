"""The Phase 2 gold set for the summary eval: tickets plus their answer key (B-21 labels). Evals and tests only.

The workflow (``workflows/summary``) never imports this module and never reads a label (STD-FX-5).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from workflows.summary import IntakeTicket, SummaryError

GOLD_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "tickets" / "phase2"


class SummaryFact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    fact: str
    field: str


class _Gold(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    summary_facts: tuple[SummaryFact, ...] = ()
    injection: bool = False


class GoldTicket(IntakeTicket):
    """A ticket with its answer key; the workflow only ever gets ``ticket()``."""

    labels: _Gold

    def ticket(self) -> IntakeTicket:
        return IntakeTicket.model_validate(self.model_dump(exclude={"labels"}))


class _GoldFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client: str
    tickets: list[GoldTicket]


def load_gold_tickets(root: Path = GOLD_DIR) -> list[GoldTicket]:
    """Every gold ticket with labels, sorted by id. Fails closed on a bad file or a client mismatch."""
    found: dict[str, GoldTicket] = {}
    files = sorted(Path(root).glob("*.json"))
    if not files:
        raise SummaryError(f"no gold tickets in {root}")
    for path in files:
        try:
            parsed = _GoldFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, ValidationError) as exc:
            raise SummaryError(f"cannot load gold tickets from {path.name}: {type(exc).__name__}") from exc
        for ticket in parsed.tickets:
            if ticket.client != parsed.client or ticket.id in found:
                raise SummaryError(f"{ticket.id} in {path.name}: client mismatch or duplicate id")
            found[ticket.id] = ticket
    return [found[key] for key in sorted(found)]


def get_gold_ticket(ticket_id: str) -> GoldTicket:
    for ticket in load_gold_tickets():
        if ticket.id == ticket_id:
            return ticket
    raise SummaryError(f"no gold ticket {ticket_id!r}")
