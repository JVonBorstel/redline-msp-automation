"""Pending write-lever proposals: the shared contract between triage (Slice A), the baseline (B) and the queue (C).

    {"id": "P-<12 hex>", "source": "triage"|"baseline", "ref": "<ticket or finding id>", "lever": "<name>",
     "client": "<client id>", "params": {...}, "requested_by": "<identity id>", "reason": "<one line>",
     "created": "<UTC ISO>", "status": "pending", "decided_by": null, "decided_at": null}

The id is the first 12 hex digits of SHA-256 over lever + client + canonical JSON of the params, so the same action
proposed twice (by two tickets, or by triage and the baseline) gets the same id and the queue can de-duplicate it.

B-26 (DR-01): the contract has one definition, in core.queue. ``proposal_id``, ``Source`` and the UTC clock are
imported from there, and ``make_proposal`` builds the queue's own ``Proposal`` model, so triage can no longer drift
from what the queue accepts. Triage keeps handing proposals around as plain dicts (the shape above).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from core.queue.store import Proposal, Source, proposal_id
from core.queue.store import utc_now as utc_stamp

__all__ = ["Source", "make_proposal", "proposal_id", "utc_now"]


def utc_now() -> datetime:
    """The queue's UTC clock as a datetime (the clock triage and corrections take as a parameter)."""
    return datetime.fromisoformat(utc_stamp())


def make_proposal(
    *,
    source: Source,
    ref: str,
    lever: str,
    client: str,
    params: Mapping[str, Any],
    requested_by: str,
    reason: str,
    created: datetime,
) -> dict[str, Any]:
    """A new pending proposal. ``reason`` is flattened to one line; ``created`` must be timezone-aware."""
    if created.tzinfo is None:
        raise ValueError("created must be timezone-aware")
    proposal = Proposal(
        id=proposal_id(lever, client, params),
        source=source,
        ref=ref,
        lever=lever,
        client=client,
        params=dict(params),
        requested_by=requested_by,
        reason=" ".join(reason.split()),
        created=created.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )
    return proposal.model_dump(exclude={"verification"})
