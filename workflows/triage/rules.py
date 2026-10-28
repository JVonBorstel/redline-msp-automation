"""The rules that run after the model: priority, queue and the one lever a category may propose.

The model only names a category. Everything here is plain, reviewable code: the lever comes from a fixed table
keyed by that category (never from model output or ticket text), and its parameters come from the ticket's form
fields. A fooled classification can at worst pick another row of this table, and every row is a registered,
approval-gated lever that the runner checks again.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, get_args

from workflows.triage.tickets import Category, Priority, Queue, Ticket

CATEGORIES: tuple[Category, ...] = get_args(Category)
PRIORITIES: tuple[Priority, ...] = get_args(Priority)
QUEUES: tuple[Queue, ...] = get_args(Queue)

BASE_PRIORITY: Mapping[Category, Priority] = {
    "security": "high",
    "offboarding": "high",
    "mfa": "high",
    "account-access": "medium",
    "email": "medium",
    "network": "medium",
    "software": "medium",
    "hardware": "low",
    "other": "low",
}

# Each group found in the ticket wording raises the priority one step. This only orders the queue; ticket text
# never changes what may be done, by whom, or for which client.
WIDE_IMPACT = ("everyone", "whole office", "entire office", "whole practice", "whole firm", "all staff", "nobody can")
BLOCKING = ("outage", "is down", "down for", "can't work", "cannot work", "immediately", "urgent", "asap")

QUEUE_BY_CATEGORY: Mapping[Category, Queue] = {
    "security": "security",
    "offboarding": "identity",
    "mfa": "identity",
    "account-access": "identity",
    "email": "service-desk",
    "software": "service-desk",
    "other": "service-desk",
    "network": "network",
    "hardware": "onsite",
}
FLAGGED_QUEUE: Queue = "security"
FLAGGED_PRIORITY: Priority = "high"


@dataclass(frozen=True, slots=True)
class LeverRule:
    """One row of the lever table: a registered lever and how to fill its params from the ticket's form fields."""

    lever: str
    params: Callable[[Ticket], dict[str, Any] | None]
    source: str  # which ticket fields the params come from, for the explanation


def _affected_user(ticket: Ticket) -> dict[str, Any] | None:
    return {"upn": ticket.affected_user} if ticket.affected_user else None


def _offboard(ticket: Ticket) -> dict[str, Any] | None:
    if not ticket.affected_user:
        return None
    return {"upn": ticket.affected_user, "reason": f"Offboarding request {ticket.id} (triage proposal)"}


LEVER_RULES: Mapping[Category, LeverRule] = {
    "mfa": LeverRule("user.reset-mfa", _affected_user, "upn from the ticket's affected_user field"),
    "offboarding": LeverRule("user.disable", _offboard, "upn from the ticket's affected_user field"),
}


def priority_for(category: Category, text: str) -> tuple[Priority, list[str]]:
    """Base priority for the category, raised one step per matching wording group. Returns it with the reasons."""
    level = PRIORITIES.index(BASE_PRIORITY[category])
    why = [f"base {BASE_PRIORITY[category]} for {category}"]
    folded = text.casefold()
    for name, words in (("wide impact", WIDE_IMPACT), ("blocking", BLOCKING)):
        hit = next((w for w in words if w in folded), None)
        if hit is not None and level < len(PRIORITIES) - 1:
            level += 1
            why.append(f"raised one step for {name} wording ({hit!r})")
    return PRIORITIES[level], why
