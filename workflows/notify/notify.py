"""Affected-person notice drafts (B-04, specs/B-04.md; governance EU-1, EU-2, HO-9; controls C-35, C-36).

After a lead approved a write-lever proposal and the runner executed it, the person whose account changed should
hear, in plain words, what changed, why, who approved it, how to undo it and how to get back fast. This module
writes that message as a **draft** for a person to review and send; it never sends anything.

Guarantees:
- only an ``executed`` proposal gets a draft; any other status raises ``NotifyRefused`` and nothing is written;
- every write lever needs ``templates/<lever>.md``; a missing template or an unfilled placeholder fails closed;
- values come from trusted fields only (the proposal, the ticket's form fields, the tenant's ``displayName``, the
  identity store and ``fixtures/notify/contacts.json``), never from ticket free text and never from a model;
- filling is deterministic: the same inputs give byte-identical drafts;
- the first line is always ``DRAFT_HEADER`` (HO-9).

The queue file is read without its lock and never written (one reader; a torn last line fails closed).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from core.identity import IdentityStore, UnknownIdentity
from core.levers import DEFAULT_TENANT_DIR, MockTenant, Registry, TenantError
from core.queue import Proposal
from workflows.triage.tickets import DEFAULT_TICKETS_DIR, TicketError, get_ticket

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_CONTACTS_PATH = REPO_ROOT / "fixtures" / "notify" / "contacts.json"
DRAFT_HEADER = "Draft. A person reviews and sends this."

PROPOSAL_ID = re.compile(r"^P-[0-9a-f]{12}$")
_SAFE_VALUE = re.compile(r"^[^\r\n${}<>]{1,120}$")


class NotifyError(ValueError):
    """The draft cannot be made: bad input, missing template, contact or queue entry. Nothing is written."""


class NotifyRefused(NotifyError):
    """The proposal is not executed, so there is no change to tell anyone about. Nothing is written."""


class _Contact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    team: Annotated[str, StringConstraints(min_length=1, max_length=60, pattern=r"^[^\r\n${}<>]+$")]
    fast_phone: Annotated[str, StringConstraints(pattern=r"^555-01[0-9]{2}$")]
    hours: Annotated[str, StringConstraints(min_length=1, max_length=60, pattern=r"^[^\r\n${}<>]+$")]


class _ContactsFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    version: int
    note: str = Field(alias="_note", default="")
    clients: dict[Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")], _Contact]


def load_contacts(path: Path = DEFAULT_CONTACTS_PATH) -> dict[str, _Contact]:
    """The fast-path contact per client. Fails closed on a missing or invalid file or an unknown version."""
    try:
        parsed = _ContactsFile.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        raise NotifyError(f"cannot load contacts from {path}: {exc}") from exc
    if parsed.version != 1:
        raise NotifyError(f"{path}: unknown version {parsed.version}")
    return dict(parsed.clients)


def template_path(lever: str, templates_dir: Path = TEMPLATES_DIR) -> Path:
    return Path(templates_dir) / f"{lever}.md"


def missing_templates(registry: Registry, templates_dir: Path = TEMPLATES_DIR) -> list[str]:
    """Write levers in ``registry`` without a notice template (B04-2). Empty means every write lever has one."""
    missing = []
    for name in registry.names():
        spec = registry.get(name)
        if spec is not None and spec.lever_class == "write" and not template_path(name, templates_dir).is_file():
            missing.append(name)
    return missing


def load_proposal(state_dir: Path, proposal_id: str) -> Proposal:
    """The latest saved version of one proposal from ``<state_dir>/queue.jsonl`` (read only)."""
    if not PROPOSAL_ID.fullmatch(proposal_id):
        raise NotifyError(f"{proposal_id!r} is not a proposal id (P- and 12 hex characters)")
    path = Path(state_dir) / "queue.jsonl"
    try:
        lines = path.read_bytes().splitlines()
    except OSError as exc:
        raise NotifyError(f"no readable queue at {path}: {exc}") from exc
    found: Proposal | None = None
    for number, line in enumerate(lines, start=1):
        try:
            proposal = Proposal.model_validate_json(line)
        except ValidationError as exc:
            raise NotifyError(f"{path} line {number} is not a valid proposal") from exc
        if proposal.id == proposal_id:
            found = proposal  # a later line supersedes an earlier one
    if found is None:
        raise NotifyError(f"no proposal {proposal_id} in {path}")
    return found


@dataclass(frozen=True, slots=True)
class Notice:
    proposal_id: str
    lever: str
    client: str
    text: str


def _first_name(tenant: MockTenant, client: str, upn: str) -> str:
    try:
        state = tenant.load(client)
    except TenantError as exc:
        raise NotifyError(str(exc)) from exc
    for user in state.get("users", []):
        if isinstance(user, dict) and user.get("userPrincipalName") == upn:
            words = str(user.get("displayName", "")).split()
            if words:
                return words[0]
    return "there"


def _request(proposal: Proposal, tickets_dir: Path) -> str:
    if proposal.source == "triage":
        try:
            ticket = get_ticket(proposal.ref, tickets_dir)
        except TicketError as exc:
            raise NotifyError(f"ticket {proposal.ref} not found for {proposal.id}") from exc
        if ticket.client != proposal.client:
            raise NotifyError(f"ticket {ticket.id} belongs to another client")
        if ticket.affected_user is not None and ticket.requester == ticket.affected_user:
            return f"you asked for it in ticket {ticket.id}"
        return f"your workplace asked for it in ticket {ticket.id}"
    return f"a security check flagged it ({proposal.ref})"


def _approver(identities: IdentityStore, decided_by: str | None) -> str:
    if decided_by is None:
        raise NotifyError("the proposal has no approver")
    try:
        who = identities.get(decided_by)
    except UnknownIdentity as exc:
        raise NotifyError(f"unknown approver {decided_by!r}") from exc
    return who.display_name.split(" (")[0].strip() or decided_by


def draft_notice(
    proposal: Proposal,
    *,
    registry: Registry,
    identities: IdentityStore,
    tenant: MockTenant,
    contacts: dict[str, _Contact],
    templates_dir: Path = TEMPLATES_DIR,
    tickets_dir: Path = DEFAULT_TICKETS_DIR,
) -> Notice:
    """Fill the lever's template for one executed proposal. Raises NotifyRefused or NotifyError; never partial."""
    if proposal.status != "executed":
        raise NotifyRefused(
            f"{proposal.id} is {proposal.status}: a notice is drafted only after the change was executed; "
            "no draft was written"
        )
    spec = registry.get(proposal.lever)
    if spec is None or spec.lever_class != "write":
        raise NotifyError(f"{proposal.lever!r} is not a registered write lever")
    path = template_path(proposal.lever, templates_dir)
    if not path.is_file():
        raise NotifyError(f"no notice template for {proposal.lever} ({path.name}); no draft was written")
    contact = contacts.get(proposal.client)
    if contact is None:
        raise NotifyError(f"no fast-path contact for client {proposal.client!r} in contacts.json")
    upn = proposal.params.get("upn")
    if not isinstance(upn, str):
        raise NotifyError(f"{proposal.id} names no person (no upn param)")
    values = {
        "first_name": _first_name(tenant, proposal.client, upn),
        "request": _request(proposal, tickets_dir),
        "approver": _approver(identities, proposal.decided_by),
        "team": contact.team,
        "fast_phone": contact.fast_phone,
        "hours": contact.hours,
    }
    for key, value in values.items():
        if not _SAFE_VALUE.fullmatch(value):
            raise NotifyError(f"value for ${key} is not a safe single line")
    try:
        body = Template(path.read_text(encoding="utf-8")).substitute(values)
    except (KeyError, ValueError) as exc:
        raise NotifyError(f"template {path.name} has a placeholder with no trusted value: {exc}") from exc
    text = DRAFT_HEADER + "\n\n" + body.strip() + "\n"
    return Notice(proposal.id, proposal.lever, proposal.client, text)


def write_notice(notice: Notice, state_dir: Path) -> Path:
    """Write the draft to ``<state_dir>/notices/<proposal-id>.md`` atomically and return the path."""
    out_dir = Path(state_dir) / "notices"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{notice.proposal_id}.md"
    tmp = target.with_name(target.name + f".{os.getpid()}.tmp")
    tmp.write_bytes(notice.text.encode("utf-8"))
    os.replace(tmp, target)
    return target


def notice_for(state_dir: Path, proposal_id: str, *, contacts_path: Path = DEFAULT_CONTACTS_PATH) -> Path:
    """Load, draft and write the notice for one proposal in a state folder (the CLI path)."""
    proposal = load_proposal(state_dir, proposal_id)
    tenant_dir = Path(state_dir) / "tenant"
    notice = draft_notice(
        proposal,
        registry=Registry.load(),
        identities=IdentityStore.load(),
        tenant=MockTenant(tenant_dir if tenant_dir.is_dir() else DEFAULT_TENANT_DIR),
        contacts=load_contacts(contacts_path),
    )
    return write_notice(notice, state_dir)
