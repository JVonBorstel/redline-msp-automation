"""Teams approval prompts for one client's pending proposals (B-88). Dry-run only: nothing is posted, nothing decided.

For each PENDING proposal of one client, ``plan_posts`` builds the Teams card with ``adapters.m365.build_approval_card``
(one ``Action.OpenUrl`` link back to the loopback approval page, no button that can decide) and ``record_dry_run``
writes what would be posted to ``<state>/teams-approvals/<client>.json``. There is no posting code: ``plan_posts``
refuses ``dry_run=False``, and a test reads this package so no network, Teams or Graph library can be added unnoticed.

This workflow reads no free text of its own. The proposal's reason and parameters reach the card only through the
adapter, which makes them one plain line and withholds text the injection tripwire flags (C-12). It never calls
``ProposalQueue.decide``, ``refuse`` or the runner; the queue and the audit chains are read, never written.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters.m365 import CardError, build_approval_card
from adapters.m365.teams_card import loopback_base
from core.queue.store import ProposalQueue, QueueError

OUTBOX = "teams-approvals"
NOTE = (
    "DRY RUN. Nothing was posted to Teams. Each card links to the loopback approval page only and cannot decide; "
    "a signed-in lead decides there. Card shapes are UNVERIFIED (specs/B-88.md)."
)
_CLIENT = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class TeamsApprovalsError(ValueError):
    """The run cannot be planned (bad client id, posting asked for, unreadable queue). Nothing is written."""


@dataclass(frozen=True, slots=True)
class PlannedPost:
    """One card that would be posted for one pending proposal."""

    proposal: str
    lever: str
    card: dict[str, Any]

    @property
    def card_sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.card, sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TeamsRun:
    """What a run would post for one client, and the pending proposals that got no card (with why)."""

    client: str
    posts: tuple[PlannedPost, ...]
    skipped: tuple[tuple[str, str], ...]

    @property
    def posted(self) -> bool:
        return False  # there is no posting code; a dry run is the only run


def plan_posts(queue: ProposalQueue, client: str, *, base_url: str, dry_run: bool = True) -> TeamsRun:
    """Cards for every pending proposal of ``client``, in queue order. Reads the queue and audit; writes nothing."""
    if not dry_run:
        raise TeamsApprovalsError("posting to Teams is not built; only a dry run is possible")
    if not isinstance(client, str) or not _CLIENT.fullmatch(client):
        raise TeamsApprovalsError("not a client id")
    try:
        loopback_base(base_url)
    except CardError as exc:
        raise TeamsApprovalsError(str(exc)) from exc
    try:
        pending = [p for p in queue.list(status="pending") if p.client == client]
    except QueueError as exc:
        raise TeamsApprovalsError("the queue could not be read") from exc
    posts: list[PlannedPost] = []
    skipped: list[tuple[str, str]] = []
    for proposal in pending:
        try:
            card = build_approval_card(queue, proposal.id, base_url=base_url)
        except CardError as exc:
            skipped.append((proposal.id, str(exc)))
            continue
        posts.append(PlannedPost(proposal.id, proposal.lever, card))
    return TeamsRun(client, tuple(posts), tuple(skipped))


def summary(run: TeamsRun) -> dict[str, Any]:
    """The outbox record of one run (deterministic: the same queue and audit give the same bytes)."""
    return {
        "client": run.client,
        "dry_run": True,
        "posted": run.posted,
        "note": NOTE,
        "posts": [
            {"proposal": p.proposal, "lever": p.lever, "card_sha256": p.card_sha256, "card": p.card} for p in run.posts
        ],
        "skipped": [{"proposal": pid, "reason": reason} for pid, reason in run.skipped],
    }


def record_dry_run(run: TeamsRun, state_dir: Path) -> Path:
    """Write what the run would post to ``<state>/teams-approvals/<client>.json`` (replaced on each run)."""
    folder = Path(state_dir) / OUTBOX
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{run.client}.json"
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(summary(run), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path
