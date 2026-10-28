"""Duplicate, related-ticket and outage grouping (B-23, specs/B-23.md; W-SD-03, W-SD-08; C-27, C-41, C-05).

For one ticket this finds the same client's open tickets that are probably the same problem. For one client it finds
groups: tickets about one topic inside a short window (duplicates), and a widespread issue, where N or more tickets of
one category fall inside the window (an outage group). It only *suggests*. A link is made only by the ``ticket.link``
lever, which here is only ever dry-run; a lead approves the real write (HO-1, C-05).

Isolation (C-27, B23-1). Every entry point takes the client explicitly and drops every ticket of another client
*before* anything is classified, scored or counted, so a ticket of another client is never compared and never shown.
Nothing in a result carries ticket text: only ticket ids, topic ids, categories, counts and times.

Untrusted text (C-12). Subject and body are only matched against the topic words in ``config.json`` and tokenised for a
similarity score. They are never copied into a result, a lever parameter or a proposal reason. A ticket the injection
detector flags is left out of grouping and listed separately for a person to read; text can never steer a link.

No model is called: the topic words and the thresholds are plain configuration a reviewer can read (D-022).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator

from core.guard import detect_injection
from core.levers import InvokeResult, LeverRunner
from workflows.triage.tickets import Category

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.json")
DEFAULT_TICKETS_DIR = REPO_ROOT / "fixtures" / "tickets"
DUPLICATE_AGENT = "triage-bot"

CLIENT_ID = r"^[a-z0-9][a-z0-9-]{0,62}$"
CATEGORIES: tuple[str, ...] = get_args(Category)
UNGROUPED_CATEGORY = "other"  # a ticket with no topic is never grouped: the code does not guess
LinkType = Literal["duplicate", "related", "outage-group"]

_NON_WORD = re.compile(r"[^a-z0-9]+")
_STOP = frozenset(
    "the and for with from that this have has had not but are was were you your our can could would should will "
    "get got just still please help need needs want now today again when what which who how why all any too very "
    "its into out off new one two about after before since over under been being than then them they their "
    "there here some more most also only my me we is it on in to of at as an or be do does did".split()
)


class DuplicatesError(ValueError):
    """The input is bad (config, ticket file); nothing was grouped."""


def normalise(text: str) -> str:
    """Lower case, apostrophes removed, everything else that is not a letter or digit becomes one space."""
    return _NON_WORD.sub(" ", text.lower().replace("'", "").replace("’", "")).strip()


class Topic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,40}$")]
    category: str
    terms: tuple[Annotated[str, StringConstraints(min_length=2, max_length=40)], ...] = Field(min_length=1)

    @field_validator("category")
    @classmethod
    def _known_category(cls, value: str) -> str:
        if value not in CATEGORIES or value == UNGROUPED_CATEGORY:
            raise ValueError(f"category {value!r} must be one of the triage categories except 'other'")
        return value

    @field_validator("terms")
    @classmethod
    def _normalised(cls, terms: tuple[str, ...]) -> tuple[str, ...]:
        for term in terms:
            if term != normalise(term):
                raise ValueError(f"term {term!r} must be lower case words with no punctuation")
        return terms


class DuplicateConfig(BaseModel):
    """The workflow's configuration; unknown keys fail the load (STD-CF-3)."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    version: Literal[1]
    note: str = Field(default="", alias="_note")
    window_hours: float = Field(gt=0, le=48)
    outage_min_tickets: int = Field(ge=2, le=50)  # N: this many tickets of one category in the window raise a group
    outage_min_requesters: int = Field(ge=1, le=50)
    related_min_similarity: float = Field(ge=0, le=1)
    topics: tuple[Topic, ...] = Field(min_length=1)

    @field_validator("topics")
    @classmethod
    def _unique_topics(cls, topics: tuple[Topic, ...]) -> tuple[Topic, ...]:
        ids = [t.id for t in topics]
        if len(set(ids)) != len(ids):
            raise ValueError("topic ids must be unique")
        return topics

    @property
    def window(self) -> timedelta:
        return timedelta(hours=self.window_hours)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> DuplicateConfig:
    try:
        return DuplicateConfig.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        raise DuplicatesError(f"cannot load duplicate config from {path}: {exc}") from exc


class DupTicket(BaseModel):
    """The ticket fields this workflow reads. ``subject`` and ``body`` are untrusted. Answer-key labels are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: Annotated[str, StringConstraints(pattern=r"^T-[0-9]{4}$")]
    client: Annotated[str, StringConstraints(pattern=CLIENT_ID)]
    subject: str = Field(max_length=200)
    body: str = Field(max_length=4000)
    requester: str
    status: Literal["new", "in-progress", "waiting-client", "waiting-vendor", "resolved"]
    created: datetime
    updated: datetime

    @property
    def is_open(self) -> bool:
        return self.status != "resolved"


class _TicketFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client: str
    tickets: list[dict[str, Any]]


def load_tickets(root: Path = DEFAULT_TICKETS_DIR) -> list[DupTicket]:
    """Every ticket under ``root`` (any depth) that has a status and timestamps, sorted by id. Fails closed.

    A ticket with no ``created`` time (the older Phase 1 files) cannot be placed in a window, so it is not loaded.
    Answer-key labels in the files are ignored. A bad file, a client mismatch or a duplicate id fails the load.
    """
    found: dict[str, DupTicket] = {}
    files = sorted(Path(root).rglob("*.json"))
    if not files:
        raise DuplicatesError(f"no ticket fixtures in {root}")
    for path in files:
        try:
            parsed = _TicketFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
            tickets = [DupTicket.model_validate(raw) for raw in parsed.tickets if "created" in raw]
        except (OSError, ValueError, ValidationError) as exc:
            raise DuplicatesError(f"cannot load tickets from {path}: {exc}") from exc
        for ticket in tickets:
            if ticket.client != parsed.client or ticket.id in found:
                raise DuplicatesError(f"{ticket.id} in {path.name}: client mismatch or duplicate id")
            found[ticket.id] = ticket
    return [found[key] for key in sorted(found)]


# -- topic and similarity -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TopicHit:
    topic: str
    category: str
    score: int


def classify(ticket: DupTicket, config: DuplicateConfig) -> TopicHit | None:
    """The topic whose words match the ticket best, or None. A word in the subject counts 2, in the body 1.

    A tie goes to the topic listed first in the config, so the result is deterministic.
    """
    subject, body = f" {normalise(ticket.subject)} ", f" {normalise(ticket.body)} "
    best: TopicHit | None = None
    for topic in config.topics:
        score = 0
        for term in topic.terms:
            needle = f" {term} "
            score += 2 if needle in subject else 1 if needle in body else 0
        if score and (best is None or score > best.score):
            best = TopicHit(topic.id, topic.category, score)
    return best


def _tokens(ticket: DupTicket) -> frozenset[str]:
    words = normalise(f"{ticket.subject} {ticket.body}").split()
    return frozenset(w for w in words if len(w) > 2 and w not in _STOP)


def similarity(a: DupTicket, b: DupTicket) -> float:
    """Word overlap (Jaccard) of two tickets' content words, 0 to 1, rounded to 3 places."""
    left, right = _tokens(a), _tokens(b)
    if not left or not right:
        return 0.0
    return round(len(left & right) / len(left | right), 3)


# -- isolation: the only way tickets enter ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Pool:
    """One client's groupable tickets. ``flagged`` are tickets the injection detector would not let steer anything."""

    client: str
    tickets: tuple[DupTicket, ...]
    flagged: tuple[str, ...]


def pool_for(
    client: str, tickets: Iterable[DupTicket], *, open_only: bool = True, as_of: datetime | None = None
) -> Pool:
    """Keep only ``client``'s tickets (the others are dropped here, before any comparison) and the open ones.

    ``as_of`` hides tickets created after it. With ``open_only`` False resolved tickets stay (history, for evals).
    """
    if not re.fullmatch(CLIENT_ID, client):
        raise DuplicatesError(f"invalid client id {client!r}")
    kept: list[DupTicket] = []
    flagged: list[str] = []
    for ticket in sorted((t for t in tickets if t.client == client), key=lambda t: (t.created, t.id)):
        if open_only and not ticket.is_open:
            continue
        if as_of is not None and ticket.created > as_of:
            continue
        if detect_injection(ticket.subject + "\n\n" + ticket.body).flagged:
            flagged.append(ticket.id)
            continue
        kept.append(ticket)
    return Pool(client, tuple(kept), tuple(flagged))


# -- candidates for one ticket ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Candidate:
    ticket_id: str
    link_type: LinkType
    topic: str
    category: str
    minutes_apart: int
    similarity: float
    reason: str


def candidates_for(
    ticket: DupTicket, tickets: Iterable[DupTicket], config: DuplicateConfig, *, open_only: bool = True
) -> list[Candidate]:
    """The same client's tickets that look like ``ticket``, strongest first. Never another client's (B23-1).

    ``duplicate``: same topic inside the window. ``related``: same category, different topic, inside the window and
    similar enough in wording. A ticket with no topic has no candidates.
    """
    pool = pool_for(ticket.client, tickets, open_only=open_only)
    mine = classify(ticket, config)
    if mine is None:
        return []
    found: list[Candidate] = []
    for other in pool.tickets:
        if other.id == ticket.id:
            continue
        apart = abs(other.created - ticket.created)
        if apart > config.window:
            continue
        theirs = classify(other, config)
        if theirs is None or theirs.category != mine.category:
            continue
        score = similarity(ticket, other)
        minutes = int(apart.total_seconds() // 60)
        if theirs.topic == mine.topic:
            found.append(
                Candidate(other.id, "duplicate", mine.topic, mine.category, minutes, score, "same topic in the window")
            )
        elif score >= config.related_min_similarity:
            found.append(
                Candidate(
                    other.id, "related", mine.topic, mine.category, minutes, score, "same category, similar words"
                )
            )
    found.sort(key=lambda c: (c.link_type != "duplicate", -c.similarity, c.minutes_apart, c.ticket_id))
    return found


# -- groups for one client ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Group:
    id: str
    kind: Literal["duplicate", "outage"]
    client: str
    category: str
    topic: str | None
    ticket_ids: tuple[str, ...]
    requesters: int
    first_created: datetime
    last_created: datetime


@dataclass(frozen=True, slots=True)
class Grouping:
    client: str
    duplicate_groups: tuple[Group, ...]
    outage_groups: tuple[Group, ...]
    flagged: tuple[str, ...] = field(default=())
    ungrouped_topic: tuple[str, ...] = field(default=())


def _components(items: Sequence[DupTicket], window: timedelta) -> list[list[DupTicket]]:
    """Runs of tickets whose neighbours in time are within the window (items are sorted by time)."""
    sets: list[list[DupTicket]] = []
    for item in items:
        if sets and item.created - sets[-1][-1].created <= window:
            sets[-1].append(item)
        else:
            sets.append([item])
    return sets


def _group(
    kind: Literal["duplicate", "outage"], client: str, topic: str | None, category: str, members: list[DupTicket]
) -> Group:
    first = members[0]
    stem = topic if kind == "duplicate" and topic else category
    return Group(
        id=f"{'DUP' if kind == 'duplicate' else 'OUT'}-{client}-{stem}-{first.id}",
        kind=kind,
        client=client,
        category=category,
        topic=topic if kind == "duplicate" else None,
        ticket_ids=tuple(m.id for m in members),
        requesters=len({m.requester.lower() for m in members}),
        first_created=first.created,
        last_created=members[-1].created,
    )


def group_client(
    client: str,
    tickets: Iterable[DupTicket],
    config: DuplicateConfig,
    *,
    open_only: bool = True,
    as_of: datetime | None = None,
) -> Grouping:
    """Duplicate groups (same topic, 2+ tickets) and outage groups (same category, N+ tickets) for one client.

    Outage rule (B23-3): N or more tickets of one category whose creation times chain within the window and that come
    from at least ``outage_min_requesters`` different people. N and the window come from ``config``.
    """
    pool = pool_for(client, tickets, open_only=open_only, as_of=as_of)
    by_topic: dict[str, list[DupTicket]] = defaultdict(list)
    by_category: dict[str, list[DupTicket]] = defaultdict(list)
    category_of: dict[str, str] = {}
    unclassified: list[str] = []
    for ticket in pool.tickets:
        hit = classify(ticket, config)
        if hit is None:
            unclassified.append(ticket.id)
            continue
        by_topic[hit.topic].append(ticket)
        by_category[hit.category].append(ticket)
        category_of[hit.topic] = hit.category
    duplicates = [
        _group("duplicate", pool.client, topic, category_of[topic], members)
        for topic, items in sorted(by_topic.items())
        for members in _components(items, config.window)
        if len(members) >= 2
    ]
    outages = [
        group
        for category, items in sorted(by_category.items())
        for members in _components(items, config.window)
        if len(members) >= config.outage_min_tickets
        for group in [_group("outage", pool.client, None, category, members)]
        if group.requesters >= config.outage_min_requesters
    ]
    duplicates.sort(key=lambda g: (g.first_created, g.id))
    outages.sort(key=lambda g: (g.first_created, g.id))
    return Grouping(pool.client, tuple(duplicates), tuple(outages), pool.flagged, tuple(unclassified))


# -- dry-run links through the lever runner -----------------------------------------------------------------


def propose_links(group: Group, runner: LeverRunner, *, agent: str = DUPLICATE_AGENT) -> list[InvokeResult]:
    """Dry-run ``ticket.link`` from the group's first ticket to each other member. Nothing is ever executed here.

    A duplicate group uses ``duplicate``, an outage group ``outage-group``. The runner checks role, client scope,
    schema and that both tickets belong to this client's own state; every call is audited. A person turns an ok
    dry-run into a proposal for a lead (STD-PR-1).
    """
    kind: LinkType = "duplicate" if group.kind == "duplicate" else "outage-group"
    anchor, *others = group.ticket_ids
    return [
        runner.invoke(
            "ticket.link",
            {"ticket_id": anchor, "related_id": other, "link_type": kind},
            identity=agent,
            client=group.client,
            mode="dry-run",
        )
        for other in others
    ]


def summary(grouping: Grouping) -> dict[str, Any]:
    """A plain, text-free summary (ids and counts) for the CLI and reports."""
    return {
        "client": grouping.client,
        "duplicate_groups": [{"id": g.id, "tickets": list(g.ticket_ids)} for g in grouping.duplicate_groups],
        "outage_groups": [{"id": g.id, "tickets": list(g.ticket_ids)} for g in grouping.outage_groups],
        "needs_a_person_to_read": list(grouping.flagged),
    }


def utc(value: str) -> datetime:
    """Parse an ISO 8601 timestamp (``Z`` allowed) as UTC."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise DuplicatesError(f"{value!r} is not an ISO 8601 timestamp") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
