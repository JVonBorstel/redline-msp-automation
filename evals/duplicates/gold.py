"""The Phase 2 gold set for the duplicate eval: tickets plus their duplicate-group answer key (B-21 labels).

Evals and tests only. The workflow (``workflows/duplicates``) never imports this module and never reads a label
(STD-FX-5).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from workflows.duplicates import DuplicatesError, DupTicket

GOLD_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "tickets" / "phase2"


class _Gold(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    duplicate_group: str | None = None


class GoldTicket(DupTicket):
    """A ticket with its answer key; the workflow itself only ever gets the plain ``DupTicket``."""

    labels: _Gold

    def ticket(self) -> DupTicket:
        return DupTicket.model_validate(self.model_dump(exclude={"labels"}))


class _GoldFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client: str
    tickets: list[GoldTicket]


def load_gold_tickets(root: Path = GOLD_DIR) -> list[GoldTicket]:
    """Every Phase 2 ticket with its labels, sorted by id. Fails closed on a bad file or a client mismatch."""
    found: dict[str, GoldTicket] = {}
    files = sorted(Path(root).glob("*.json"))
    if not files:
        raise DuplicatesError(f"no ticket fixtures in {root}")
    for path in files:
        try:
            parsed = _GoldFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, ValidationError) as exc:
            raise DuplicatesError(f"cannot load tickets from {path}: {exc}") from exc
        for ticket in parsed.tickets:
            if ticket.client != parsed.client or ticket.id in found:
                raise DuplicatesError(f"{ticket.id} in {path.name}: client mismatch or duplicate id")
            found[ticket.id] = ticket
    return [found[key] for key in sorted(found)]


def gold_groups(tickets: list[GoldTicket]) -> dict[str, tuple[str, ...]]:
    """Gold duplicate group id to its ticket ids (sorted)."""
    groups: dict[str, list[str]] = {}
    for ticket in tickets:
        if ticket.labels.duplicate_group:
            groups.setdefault(ticket.labels.duplicate_group, []).append(ticket.id)
    return {key: tuple(sorted(ids)) for key, ids in sorted(groups.items())}
