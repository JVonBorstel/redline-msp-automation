"""Draft replies with KB citations and closure follow-up drafts (B-25, specs/B-25.md; HO-9, AIR-4; C-12, C-26).

Two kinds of draft, both for a person to review and send. Nothing here sends anything.

**Reply draft** (W-SD-05). The ticket is scanned for injection first (C-12). Then ``kb.search`` runs through the lever
runner as the agent identity, for the ticket's own client only (C-26). Every sentence of the draft is a sentence of one
of the returned articles of that client, followed by ``[<article id>]``. With no source the result is exactly
``no draft: no source article``; the code never fills the gap itself (AIR-4). No model is called: the text is quoted
from the client's own KB, so a hallucinated promise is not possible. ``check_citations`` is the validator any later
model-written draft must also pass.

**Closure follow-up draft** (W-SD-09). Only for a ``resolved`` ticket. It says in plain words that the ticket is
resolved, what the fix was (a sentence the technician typed, or the client's KB guide, cited), asks the person to check
it, and offers the way back: the client's fast-path number from ``fixtures/notify/contacts.json``.

Untrusted ticket text (subject, body) only ever becomes search keywords. It is never copied into a draft. Values that
reach a draft are the ticket id, the person's first name from the client's tenant, KB text and the contacts fixture.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from core.guard import detect_injection
from core.levers import DEFAULT_TENANT_DIR, LeverRunner, MockTenant, TenantError
from workflows.notify import DEFAULT_CONTACTS_PATH, DRAFT_HEADER, NotifyError, load_contacts

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TICKETS_DIR = REPO_ROOT / "fixtures" / "tickets"
REPLY_AGENT = "triage-bot"
NO_SOURCE = "no draft: no source article"
FLAGGED = "no draft: the ticket text looks like an instruction to the assistant; a person should read it"

MIN_SCORE = 2  # kb.search keyword hits needed before an article counts as a source (tuned on the fixtures)
MAX_SOURCES = 2
MAX_SENTENCES_PER_SOURCE = 3
QUERY_MAX = 100  # kb.search `query` max_length in the registry

KB_ID = re.compile(r"^KB-[A-Z]{2,4}-[0-9]{3}$")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_CITATION = re.compile(r"^(?P<sentence>.+[.!?]) \[(?P<ids>KB-[A-Z]{2,4}-[0-9]{3}(?:, KB-[A-Z]{2,4}-[0-9]{3})*)\]$")
_SAFE_LINE = re.compile(r"^[^\r\n${}<>\[\]]{1,200}$")
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "the and for with from that this have has had not but are was were you your our can could would should will "
    "get got just still please help need needs want now today again when what which who how why all any too very "
    "its into out off new one two about after before since over under been being than then them they their "
    "there here some more most also only".split()
)

Kind = Literal["reply", "closure"]


class ReplyError(ValueError):
    """The input is bad (unknown ticket, bad file); nothing was drafted."""


class ReplyTicket(BaseModel):
    """The ticket fields this workflow reads. ``subject`` and ``body`` are untrusted free text.

    The PSA ``status`` is absent in the Phase 1 files, so it may be None (a closure draft then says it is not resolved).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: Annotated[str, StringConstraints(pattern=r"^T-[0-9]{4}$")]
    client: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")]
    subject: str = Field(max_length=200)
    body: str = Field(max_length=4000)
    requester: str
    affected_user: str | None = None
    status: Literal["new", "in-progress", "waiting-client", "waiting-vendor", "resolved"] | None = None


class _TicketFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client: str
    tickets: list[ReplyTicket]


def load_tickets(root: Path = DEFAULT_TICKETS_DIR) -> list[ReplyTicket]:
    """Every ticket under ``root`` (any depth), sorted by id. Answer-key labels in the files are ignored.

    Fails closed on a bad file, a client mismatch or a duplicate id.
    """
    found: dict[str, ReplyTicket] = {}
    files = sorted(Path(root).rglob("*.json"))
    if not files:
        raise ReplyError(f"no ticket fixtures in {root}")
    for path in files:
        try:
            parsed = _TicketFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, ValidationError) as exc:
            raise ReplyError(f"cannot load tickets from {path}: {exc}") from exc
        for ticket in parsed.tickets:
            if ticket.client != parsed.client or ticket.id in found:
                raise ReplyError(f"{ticket.id} in {path.name}: client mismatch or duplicate id")
            found[ticket.id] = ticket
    return [found[key] for key in sorted(found)]


def get_ticket(ticket_id: str, root: Path = DEFAULT_TICKETS_DIR) -> ReplyTicket:
    for ticket in load_tickets(root):
        if ticket.id == ticket_id:
            return ticket
    raise ReplyError(f"no ticket {ticket_id!r} in {root}")


@dataclass(frozen=True, slots=True)
class Draft:
    """The outcome for one ticket. ``text`` is the draft, or the ``no draft: ...`` line when ``drafted`` is False."""

    kind: Kind
    ticket_id: str
    client: str
    drafted: bool
    text: str
    sources: tuple[str, ...] = ()
    audit_seqs: tuple[int, ...] = ()


def _no_draft(kind: Kind, ticket: ReplyTicket, reason: str, seqs: tuple[int, ...] = ()) -> Draft:
    return Draft(kind, ticket.id, ticket.client, False, reason, (), seqs)


# -- KB access: ids come from kb.search, text from the same client's own KB ----------------------------------


def search_query(ticket: ReplyTicket) -> str:
    """Keywords from the ticket's subject then body (stop words dropped, deduplicated, at most 100 characters)."""
    seen: list[str] = []
    for word in _WORD.findall(f"{ticket.subject} {ticket.body}".lower()):
        if len(word) > 2 and word not in _STOP and word not in seen:
            seen.append(word)
    query = ""
    for word in seen:
        if len(query) + len(word) + (1 if query else 0) > QUERY_MAX:
            break
        query = f"{query} {word}".strip()
    return query


def _client_kb(tenant: MockTenant, client: str) -> dict[str, dict[str, Any]]:
    try:
        state = tenant.load(client)
    except TenantError as exc:
        raise ReplyError(str(exc)) from exc
    return {str(a["id"]): a for a in state.get("kb", []) if isinstance(a, dict) and KB_ID.fullmatch(str(a.get("id")))}


def kb_ids(tenant: MockTenant, client: str) -> frozenset[str]:
    """The article ids of one client's own knowledge base."""
    return frozenset(_client_kb(tenant, client))


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(" ".join(text.split())) if s.strip()]


def check_citations(draft_text: str, allowed_ids: frozenset[str]) -> list[str]:
    """Problems with a reply draft's body; an empty list means every sentence cites an allowed article (B25-1).

    The body is everything after the draft label and the ``Hi <name>,`` line. Each non-empty body line must be one
    sentence followed by ``[KB-...]`` and every id must be in ``allowed_ids`` (the ticket's own client's articles).
    """
    lines = draft_text.split("\n")
    if not lines or lines[0] != DRAFT_HEADER:
        return ["the first line is not the draft label"]
    body = [line for line in lines[1:] if line.strip()]
    if not body or not (body[0].startswith("Hi ") and body[0].endswith(",")):
        return ["no salutation line"]
    problems: list[str] = []
    cited = body[1:]
    if not cited:
        problems.append("the draft has no sentences")
    for line in cited:
        match = _CITATION.fullmatch(line)
        if match is None:
            problems.append(f"sentence without a citation: {line!r}")
            continue
        if len(_sentences(match["sentence"])) != 1:
            problems.append(f"more than one sentence under one citation: {line!r}")
        for article in match["ids"].split(", "):
            if article not in allowed_ids:
                problems.append(f"{article} is not an article of this client")
    return problems


def _first_name(tenant: MockTenant, ticket: ReplyTicket) -> str:
    upn = ticket.affected_user or ticket.requester
    try:
        users = tenant.load(ticket.client).get("users", [])
    except TenantError as exc:
        raise ReplyError(str(exc)) from exc
    for user in users:
        if isinstance(user, dict) and user.get("userPrincipalName") == upn:
            words = str(user.get("displayName", "")).split()
            if words and re.fullmatch(r"[A-Za-z][A-Za-z'-]{0,30}", words[0]):
                return words[0]
    return "there"


def _sources(runner: LeverRunner, ticket: ReplyTicket, agent: str) -> tuple[list[dict[str, Any]], int, str | None]:
    """Run kb.search (audited, scoped to the ticket's client). Returns hits, the audit seq and a denial reason."""
    query = search_query(ticket)
    if not query:
        return [], 0, None
    result = runner.invoke("kb.search", {"query": query, "top": 5}, identity=agent, client=ticket.client)
    if not result.ok:
        return [], result.audit_seq, result.reason
    hits = [h for h in result.data if isinstance(h, dict) and int(h.get("score", 0)) >= MIN_SCORE]
    best = int(hits[0]["score"]) if hits else 0
    keep = [h for h in hits if int(h["score"]) * 2 >= best]
    return keep[:MAX_SOURCES], result.audit_seq, None


# -- the two drafts ---------------------------------------------------------------------------------------------


def draft_reply(
    ticket: ReplyTicket, *, runner: LeverRunner, tenant: MockTenant | None = None, agent: str = REPLY_AGENT
) -> Draft:
    """A reply made only of sentences from the ticket's own client's KB, each cited; else ``no draft: ...``."""
    tenant = tenant if tenant is not None else runner.tenant
    if detect_injection(ticket.subject + "\n\n" + ticket.body).flagged:
        return _no_draft("reply", ticket, FLAGGED)
    hits, seq, denied = _sources(runner, ticket, agent)
    seqs = (seq,) if seq else ()
    if denied is not None:
        return _no_draft("reply", ticket, f"no draft: the knowledge base search was not allowed ({denied})", seqs)
    kb = _client_kb(tenant, ticket.client)
    lines: list[str] = []
    used: list[str] = []
    for hit in hits:
        article = kb.get(str(hit.get("id")))
        if article is None:  # an id the client's own KB does not hold is never cited
            continue
        article_id = str(article["id"])
        title = " ".join(str(article.get("title", "")).split())
        lines.append(f'We have a guide that matches this: "{title}". [{article_id}]')
        lines.extend(f"{s} [{article_id}]" for s in _sentences(str(article.get("body", "")))[:MAX_SENTENCES_PER_SOURCE])
        used.append(article_id)
    if not lines:
        return _no_draft("reply", ticket, NO_SOURCE, seqs)
    text = f"{DRAFT_HEADER}\n\nHi {_first_name(tenant, ticket)},\n\n" + "\n".join(lines) + "\n"
    problems = check_citations(text, frozenset(kb))
    if problems:  # fail closed: a draft that does not validate is never returned
        raise ReplyError(f"draft for {ticket.id} failed its own citation check: {problems[0]}")
    return Draft("reply", ticket.id, ticket.client, True, text, tuple(used), seqs)


_CLOSURE = Template(
    "Your ticket $ticket is now marked resolved.\n"
    "$fix\n"
    "Please check that it works the way you expect.\n"
    "If it is not fixed, or it comes back, call $phone ($hours) and we will reopen your ticket.\n"
)


def draft_closure(
    ticket: ReplyTicket,
    *,
    runner: LeverRunner,
    tenant: MockTenant | None = None,
    fix_summary: str | None = None,
    contacts_path: Path = DEFAULT_CONTACTS_PATH,
    agent: str = REPLY_AGENT,
) -> Draft:
    """A closure follow-up for a resolved ticket: the fix in plain words, a check, and the way back."""
    tenant = tenant if tenant is not None else runner.tenant
    if ticket.status != "resolved":
        state = ticket.status or "of unknown status"
        return _no_draft("closure", ticket, f"no draft: ticket {ticket.id} is {state}, not resolved")
    try:
        contact = load_contacts(contacts_path).get(ticket.client)
    except NotifyError as exc:
        raise ReplyError(str(exc)) from exc
    if contact is None:
        return _no_draft("closure", ticket, "no draft: no fast-path contact on file for this client")
    seqs: tuple[int, ...] = ()
    used: tuple[str, ...] = ()
    if fix_summary is not None:
        line = " ".join(fix_summary.split())
        if "\n" in fix_summary.strip() or "\r" in fix_summary or not _SAFE_LINE.fullmatch(line):
            raise ReplyError("the fix summary must be one plain line (200 characters at most, no $ { } < > [ ])")
        fix = f"What we did: {line.rstrip('.')}."
    else:
        fix = "We have marked it fixed."
        if not detect_injection(ticket.subject + "\n\n" + ticket.body).flagged:
            hits, seq, _ = _sources(runner, ticket, agent)
            seqs = (seq,) if seq else ()
            kb = _client_kb(tenant, ticket.client)
            if hits and str(hits[0].get("id")) in kb:
                article_id = str(hits[0]["id"])
                title = " ".join(str(kb[article_id].get("title", "")).split())
                fix = f'The fix follows our guide "{title}". [{article_id}]'
                used = (article_id,)
    body = _CLOSURE.substitute(ticket=ticket.id, fix=fix, phone=contact.fast_phone, hours=contact.hours)
    text = f"{DRAFT_HEADER}\n\nHi {_first_name(tenant, ticket)},\n\n{body}"
    return Draft("closure", ticket.id, ticket.client, True, text, used, seqs)


def write_draft(draft: Draft, state_dir: Path) -> Path:
    """Write a draft (or the no-draft line) to ``<state>/replies/<ticket>.<kind>.md`` atomically."""
    out_dir = Path(state_dir) / "replies"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{draft.ticket_id}.{draft.kind}.md"
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes((draft.text.rstrip("\n") + "\n").encode("utf-8"))
    tmp.replace(target)
    return target


def default_tenant_dir(state_dir: Path) -> Path:
    candidate = Path(state_dir) / "tenant"
    return candidate if candidate.is_dir() else DEFAULT_TENANT_DIR
