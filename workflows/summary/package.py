"""Escalation context package (W-SD-07, W-VND-04): what is already known, each line citing its source field (B-22).

Built for one client from that client's PSA adapter (read-only) and, for device facts, that client's tenant. The code
only copies: every ``Fact.value`` is a substring of the field named by ``Fact.source``, and ``build_package`` checks it
before it returns (fail closed). Where nothing is known the section says so; the code never writes a fact of its own,
so the next technician is not misled by an invented step (AIR-4 pattern). Nothing is written anywhere.

Source references: ``psa:ticket/<number>#<field>``, ``psa:ticket-note/<id>#<field>``, ``psa:contact/<id>#<field>``,
``tenant:user/<upn>#<field path>``. Text from the ticket, its notes and related tickets is untrusted: it is scanned
(a flagged ticket contributes no free text at all) and anything that later goes to a model must be wrapped (C-12).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from adapters import PsaAdapter
from core.guard import detect_injection
from core.levers import MockTenant, TenantError
from workflows.summary.common import keywords, sentences

RELATED_MAX = 5
SAME_CONTACT_DAYS = 30
SIMILAR_HOURS = 4
SIMILAR_SHARED_WORDS = 2
# Placeholder picklist (fixtures/psa/SOURCES.md: real values are per-tenant picklists, UNVERIFIED).
STATUS_NAMES = {1: "new", 2: "in progress", 3: "waiting on client", 4: "waiting on vendor", 5: "resolved"}
_TRIED = re.compile(
    r"\b(?:tried|already|restarted|rebooted|reinstalled|re-installed|unplugged|cleared|power[- ]cycled|swapped|"
    r"turned (?:it )?off|checked)\b",
    re.IGNORECASE,
)
NONE_RECORDED = "none recorded"


@dataclass(frozen=True, slots=True)
class Fact:
    """One line of the package. ``value`` is copied from the field ``source`` names; ``label`` is fixed wording."""

    label: str
    value: str
    source: str


@dataclass(frozen=True, slots=True)
class EscalationPackage:
    ticket_id: str
    client: str
    company: str
    flagged: bool
    rules: tuple[str, ...]
    ticket_facts: tuple[Fact, ...]
    steps_tried: tuple[Fact, ...]
    related_tickets: tuple[Fact, ...]
    device_facts: tuple[Fact, ...]
    withheld: tuple[str, ...]

    def facts(self) -> tuple[Fact, ...]:
        return (*self.ticket_facts, *self.steps_tried, *self.related_tickets, *self.device_facts)

    def render(self) -> str:
        """Markdown for the receiving technician. Every fact line ends with its source in brackets."""
        lines = [
            f"# Escalation context: {self.ticket_id} ({self.company})",
            "",
            "Draft fact pack for the receiving technician (read-only). Every line is copied from the source named in "
            "brackets; nothing was written by a model. Read the source when it matters.",
        ]
        if self.flagged:
            lines += [
                "",
                f"FLAGGED: the ticket text looks like an instruction (rules: {', '.join(self.rules)}).",
            ]
        for title, facts in (
            ("Ticket facts", self.ticket_facts),
            ("Steps tried", self.steps_tried),
            ("Related tickets", self.related_tickets),
            ("Device facts", self.device_facts),
        ):
            lines += ["", f"## {title}"]
            if not facts:
                lines.append(f"- {NONE_RECORDED}")
            for fact in facts:
                shown = (
                    f"{fact.value} ({STATUS_NAMES.get(int(fact.value), 'unknown')})"
                    if fact.label == "Status"
                    else fact.value
                )
                lines.append(f"- {fact.label}: {shown} [{fact.source}]")
        if self.withheld:
            lines += ["", "## Withheld"]
            lines += [f"- {item}" for item in self.withheld]
        return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class PackageResult:
    package: EscalationPackage | None
    reason: str

    @property
    def ok(self) -> bool:
        return self.package is not None


def trace_facts(facts: tuple[Fact, ...], resolve: Callable[[str], str | None]) -> list[str]:
    """Facts whose value is not found in the field their source names (B22-2). An empty list means all are traced."""
    problems: list[str] = []
    for fact in facts:
        field = resolve(fact.source)
        if field is None:
            problems.append(f"{fact.label}: no such source field {fact.source}")
        elif not fact.value or fact.value not in field:
            problems.append(f"{fact.label}: value is not in {fact.source}")
    return problems


class DeviceFacts:
    """Device facts from the client's tenant: registered authenticator device names and whether the account is enabled.

    This stands in for a read lever: there is no RMM adapter yet (B-18 builds the PSA seam only), so nothing about
    managed laptops, patch level or backup is known here and the package says so.
    """

    def __init__(self, tenant: MockTenant) -> None:
        self._tenant = tenant

    def user(self, client: str, upn: str) -> dict[str, Any] | None:
        try:
            state = self._tenant.load(client)
        except TenantError:
            return None
        for user in state.get("users", []):
            if isinstance(user, dict) and str(user.get("userPrincipalName", "")).lower() == upn.lower():
                return user
        return None


def _when(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _flagged(*texts: object) -> bool:
    return detect_injection("\n\n".join(str(t) for t in texts if t)).flagged


def build_package(ticket_id: str, psa: PsaAdapter, devices: DeviceFacts | None = None) -> PackageResult:
    """The escalation package for ``ticket_id`` in the client ``psa`` is bound to (B22-2).

    A ticket of another client gets the same answer as an absent one. Returns no package, with the reason, when the
    ticket is not found. Raises ``ValueError`` if a fact fails its own trace (a bug, never a data problem).
    """
    client = psa.client
    found = psa.get_ticket(ticket_id)
    if not found.ok or found.data is None:
        return PackageResult(None, "no package: no such ticket for this client")
    ticket = found.data
    number = str(ticket["ticketNumber"])
    sources: dict[str, str] = {}

    def fact(label: str, ref: str, field_value: object) -> Fact | None:
        if field_value is None or str(field_value).strip() == "":
            return None
        sources[ref] = str(field_value)
        return Fact(label, str(field_value), ref)

    def sentence_fact(label: str, ref: str, text: str, sentence: str) -> Fact:
        sources[ref] = text
        return Fact(label, sentence, ref)

    company = psa.get_company()
    company_name = str(company.data.get("companyName", client)) if company.ok and company.data else client
    contact: dict[str, Any] | None = None
    if ticket.get("contactID") is not None:
        got = psa.get_contact(int(ticket["contactID"]))
        contact = got.data if got.ok else None
    detection = detect_injection(f"{ticket.get('title', '')}\n\n{ticket.get('description', '')}")
    flagged = detection.flagged
    withheld: list[str] = []

    ticket_facts: list[Fact | None] = [
        fact("Created", f"psa:ticket/{number}#createDate", ticket.get("createDate")),
        fact("Status", f"psa:ticket/{number}#status", ticket.get("status")),
        fact("Channel", f"psa:ticket/{number}#source", ticket.get("source")),
    ]
    if contact is not None:
        cref = f"psa:contact/{contact['id']}"
        ticket_facts += [
            fact("Contact first name", f"{cref}#firstName", contact.get("firstName")),
            fact("Contact last name", f"{cref}#lastName", contact.get("lastName")),
            fact("Contact role", f"{cref}#title", contact.get("title")),
        ]
    steps: list[Fact | None] = []
    description = str(ticket.get("description", ""))
    if flagged:
        withheld.append(
            "The ticket title and description are withheld: they look like an instruction to the assistant "
            f"(rules: {', '.join(sorted(detection.rules))}). A person should read the ticket itself."
        )
    else:
        ticket_facts.append(fact("Title", f"psa:ticket/{number}#title", ticket.get("title")))
        dref = f"psa:ticket/{number}#description"
        for sentence in sentences(description):
            target = steps if _TRIED.search(sentence) else ticket_facts
            label = "Requester says they tried" if target is steps else "Description"
            target.append(sentence_fact(label, dref, description, sentence))

    notes = psa.list_ticket_notes(number)
    held_notes = 0
    for note in (notes.data or []) if notes.ok else []:
        text = str(note.get("description", ""))
        if _flagged(note.get("title"), text):
            held_notes += 1
            continue
        nref = f"psa:ticket-note/{note['id']}#description"
        steps += [
            sentence_fact(f"Technician note {note.get('createDateTime', '')}".strip(), nref, text, s)
            for s in sentences(text)
        ]
    if held_notes:
        withheld.append(f"{held_notes} ticket note(s) withheld: they look like an instruction to the assistant.")

    related, held_related = _related(psa, ticket, flagged, sources)
    if held_related:
        withheld.append(
            f"{held_related} related ticket(s) withheld: their text looks like an instruction to the assistant."
        )

    device: list[Fact | None] = []
    upn = str(ticket.get("affectedUserEmail") or (contact or {}).get("emailAddress") or "").strip()
    if devices is None:
        withheld.append("Device facts: no device source is configured. No RMM adapter exists yet.")
    elif not upn:
        withheld.append("Device facts: the ticket names no affected user.")
    elif upn.lower() not in {str(c.get("emailAddress", "")).lower() for c in (psa.list_contacts().data or [])}:
        withheld.append(
            "Device facts: the affected user is not one of this client's contacts, so nothing was looked up."
        )
    else:
        user = devices.user(client, upn)
        if user is None:
            withheld.append("Device facts: this client's tenant has no such user.")
        else:
            uref = f"tenant:user/{user['userPrincipalName']}"
            device.append(fact("Account enabled", f"{uref}#accountEnabled", user.get("accountEnabled")))
            for index, method in enumerate(user.get("authentication", {}).get("methods", [])):
                device.append(
                    fact(
                        "Registered sign-in device",
                        f"{uref}#authentication.methods[{index}].displayName",
                        method.get("displayName"),
                    )
                )
        withheld.append("Device facts cover registered sign-in devices only; managed-device health is not available.")

    package = EscalationPackage(
        ticket_id=number,
        client=client,
        company=company_name,
        flagged=flagged,
        rules=tuple(sorted(detection.rules)),
        ticket_facts=tuple(f for f in ticket_facts if f is not None),
        steps_tried=tuple(f for f in steps if f is not None),
        related_tickets=tuple(related),
        device_facts=tuple(f for f in device if f is not None),
        withheld=tuple(withheld),
    )
    problems = trace_facts(package.facts(), sources.get)
    if problems:  # fail closed: a package with an untraceable line is never returned
        raise ValueError(f"package for {number} failed its own trace: {problems[0]}")
    return PackageResult(package, "ok")


def _related(psa: PsaAdapter, ticket: dict[str, Any], flagged: bool, sources: dict[str, str]) -> tuple[list[Fact], int]:
    """Same contact in the previous 30 days, then similar wording within four hours. The same client only."""
    listed = psa.list_tickets()
    others = [t for t in (listed.data or []) if t.get("ticketNumber") != ticket["ticketNumber"]] if listed.ok else []
    created = _when(ticket.get("createDate"))
    if created is None:
        return [], 0
    own_words = keywords(f"{ticket.get('title', '')} {ticket.get('description', '')}")
    chosen: list[tuple[dict[str, Any], str]] = []
    if ticket.get("contactID") is not None:
        same = [
            t
            for t in others
            if t.get("contactID") == ticket["contactID"]
            and (w := _when(t.get("createDate"))) is not None
            and created - timedelta(days=SAME_CONTACT_DAYS) <= w < created
        ]
        same.sort(key=lambda t: str(t["createDate"]), reverse=True)
        chosen += [(t, "same contact") for t in same]
    if not flagged:  # the ticket's own words are not used to search when they may be an attack
        taken = {str(t["ticketNumber"]) for t, _ in chosen}
        similar = [
            t
            for t in others
            if str(t["ticketNumber"]) not in taken
            and (w := _when(t.get("createDate"))) is not None
            and abs(w - created) <= timedelta(hours=SIMILAR_HOURS)
            and len(own_words & keywords(f"{t.get('title', '')} {t.get('description', '')}")) >= SIMILAR_SHARED_WORDS
        ]
        similar.sort(key=lambda t: str(t["createDate"]))
        chosen += [(t, "similar wording within 4 hours") for t in similar]
    facts: list[Fact] = []
    held = 0
    for other, reason in chosen:
        if len(facts) >= RELATED_MAX:
            break
        if _flagged(other.get("title"), other.get("description")):
            held += 1
            continue
        ref = f"psa:ticket/{other['ticketNumber']}#title"
        sources[ref] = str(other["title"])
        facts.append(Fact(f"{other['ticketNumber']} ({reason})", str(other["title"]), ref))
    return facts, held
