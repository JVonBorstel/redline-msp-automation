"""Ticket levers on the mock PSA state (B-23). Mock only: the state is one client's mock tenant file.

``ticket.link`` relates two tickets of the same client. Both tickets must be in this client's own state; a ticket of
another client is simply "not found", in the same words as an absent one (no existence oracle, TEN-04). The link is
stored on both tickets as ``links: {<other ticket id>: <link type>}``, so the dry-run diff is one ``add`` per ticket
and running it twice changes nothing (STD-LV-6). The handler gets one client's state copy and validated params only
(STD-LV-8); a link is a relation, never a close, so no ticket changes status.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.levers.handlers import LeverFailed
from core.levers.tenant import JsonDict


def _find(state: JsonDict, ticket_id: str) -> JsonDict:
    for ticket in state.get("tickets", []):
        if isinstance(ticket, dict) and ticket.get("id") == ticket_id:
            found: JsonDict = ticket  # the same object, so writes land in the runner's state copy
            return found
    raise LeverFailed(f"no ticket {ticket_id!r} for this client")


def ticket_link(state: JsonDict, params: Mapping[str, Any]) -> Any:
    """Record ``link_type`` between two tickets on both of them."""
    first, second, kind = params["ticket_id"], params["related_id"], params["link_type"]
    if first == second:
        raise LeverFailed("a ticket cannot be linked to itself")
    one, two = _find(state, first), _find(state, second)
    for ticket, other in ((one, second), (two, first)):
        links = ticket.setdefault("links", {})
        if not isinstance(links, dict):
            raise LeverFailed(f"ticket {ticket['id']!r} has links in an unexpected shape")
        links[other] = kind
    return {"ticket_id": first, "related_id": second, "link_type": kind}
