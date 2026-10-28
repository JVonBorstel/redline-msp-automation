"""Shared pieces of the summary workflow (B-22): ticket input, PSA adapters, text helpers.

Ticket text (subject, body) is untrusted. Answer-key labels in the ticket files are ignored here (STD-FX-5).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from adapters import BoundBinding, PsaAdapter, PsaMock

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TICKETS_DIR = REPO_ROOT / "fixtures" / "tickets"
DEFAULT_PSA_DIR = Path(__file__).resolve().parent / "data" / "psa"

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_ABBREVIATIONS = frozenset("dr. mr. mrs. ms. prof. st. vs. inc. ltd. llc. e.g. i.e. no. approx.".split())
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "the and for with from that this have has had not but are was were you your our can could would should will "
    "get got just still please help need needs want now today again when what which who how why all any too very "
    "its into out off new one two about after before since over under been being than then them they their "
    "there here some more most also only says since every each".split()
)


class SummaryError(ValueError):
    """The input is bad (unknown ticket, unreadable data); nothing was produced."""


class IntakeTicket(BaseModel):
    """What the workflow reads of a ticket. ``subject`` and ``body`` are untrusted free text.

    ``client`` is carried only to be ignored: the proposal comes from the sender address and the PSA contacts.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: Annotated[str, StringConstraints(pattern=r"^T-[0-9]{4}$")]
    client: str = ""
    subject: str = Field(max_length=200)
    body: str = Field(max_length=4000)
    requester: str = Field(max_length=200)
    affected_user: str | None = Field(default=None, max_length=200)


class _TicketFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client: str
    tickets: list[IntakeTicket]


def load_tickets(root: Path = DEFAULT_TICKETS_DIR) -> list[IntakeTicket]:
    """Every ticket under ``root`` (any depth), sorted by id. Fails closed on a bad file or a duplicate id."""
    found: dict[str, IntakeTicket] = {}
    files = sorted(Path(root).rglob("*.json"))
    if not files:
        raise SummaryError(f"no ticket fixtures in {root}")
    for path in files:
        try:
            parsed = _TicketFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, ValidationError) as exc:
            raise SummaryError(f"cannot load tickets from {path.name}: {type(exc).__name__}") from exc
        for ticket in parsed.tickets:
            if ticket.client != parsed.client or ticket.id in found:
                raise SummaryError(f"{ticket.id} in {path.name}: client mismatch or duplicate id")
            found[ticket.id] = ticket
    return [found[key] for key in sorted(found)]


def get_ticket(ticket_id: str, root: Path = DEFAULT_TICKETS_DIR) -> IntakeTicket:
    for ticket in load_tickets(root):
        if ticket.id == ticket_id:
            return ticket
    raise SummaryError(f"no ticket {ticket_id!r} in the ticket files")


def load_adapters(psa_dir: Path = DEFAULT_PSA_DIR) -> dict[str, PsaAdapter]:
    """One PSA adapter per client file in ``psa_dir``, each built from that client's own company id (TEN-04)."""
    adapters: dict[str, PsaAdapter] = {}
    files = sorted(Path(psa_dir).glob("*.json"))
    if not files:
        raise SummaryError(f"no PSA data in {psa_dir}")
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            client = str(data["client"])
            external_id = str(data["company"]["id"])
            adapters[client] = PsaMock(client, BoundBinding(client, "psa", "mock", external_id), root=Path(psa_dir))
        except Exception as exc:  # fail closed on anything: a half-loaded set would hide a client
            raise SummaryError(f"cannot build a PSA adapter from {path.name}: {type(exc).__name__}") from exc
    return adapters


def sentences(text: str) -> list[str]:
    """Sentences of ``text``, each an exact substring of it (stripped, not reworded).

    A full stop after a common title or abbreviation (``Dr.``, ``Mr.``, ``e.g.``) does not end a sentence.
    """
    out: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        before = text[start : match.start()].split()
        if before and before[-1].lower() in _ABBREVIATIONS:
            continue
        piece = text[start : match.start()].strip()
        if piece:
            out.append(piece)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def keywords(text: str) -> frozenset[str]:
    """Significant lowercase words (4+ letters, no stop words), used only to find related tickets."""
    return frozenset(w for w in _WORD.findall(text.lower()) if len(w) >= 4 and w not in _STOP)
