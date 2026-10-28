"""The Phase 2 gold set for the reply eval: tickets plus their answer key (B-21 labels). Evals and tests only.

The workflow (``workflows/replies``) never imports this module and never reads a label (STD-FX-5).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from workflows.replies import ReplyError, ReplyTicket

GOLD_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "tickets" / "phase2"


class _Gold(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    reply_sources: tuple[str, ...] = ()
    injection: bool = False


class GoldTicket(ReplyTicket):
    """A ticket with the answer key the eval compares against; the workflow itself only gets the ``ReplyTicket``."""

    labels: _Gold

    def ticket(self) -> ReplyTicket:
        return ReplyTicket.model_validate(self.model_dump(exclude={"labels"}))


class _GoldFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client: str
    tickets: list[GoldTicket]


def load_gold_tickets(root: Path = GOLD_DIR) -> list[GoldTicket]:
    """Every Phase 2 ticket with its labels, sorted by id. Fails closed on a bad file or a client mismatch."""
    found: dict[str, GoldTicket] = {}
    files = sorted(Path(root).glob("*.json"))
    if not files:
        raise ReplyError(f"no ticket fixtures in {root}")
    for path in files:
        try:
            parsed = _GoldFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, ValidationError) as exc:
            raise ReplyError(f"cannot load tickets from {path}: {exc}") from exc
        for ticket in parsed.tickets:
            if ticket.client != parsed.client or ticket.id in found:
                raise ReplyError(f"{ticket.id} in {path.name}: client mismatch or duplicate id")
            found[ticket.id] = ticket
    return [found[key] for key in sorted(found)]


def get_gold_ticket(ticket_id: str, root: Path = GOLD_DIR) -> GoldTicket:
    for ticket in load_gold_tickets(root):
        if ticket.id == ticket_id:
            return ticket
    raise ReplyError(f"no ticket {ticket_id!r} in {root}")
