"""Teams Adaptive Card for a pending approval, and the rule for card responses (B-88, B88-1). MOCK; nothing is posted.

UNVERIFIED: the message envelope (``type: message`` with an ``application/vnd.microsoft.card.adaptive`` attachment),
the Adaptive Card schema URL and version, ``Action.OpenUrl``, ``FactSet`` and ``TextBlock`` fields, and the size limit
were written from memory. No Microsoft page was opened, no card was posted, Teams has never rendered one of these.

What the card is for. A technician or lead sees, where they already work, that something waits and exactly what it
would change: the person affected, the lever's L1 impact line, the dry-run diff as the audit holds it, and the undo
lever. It carries ONE action, ``Action.OpenUrl`` to the loopback approval page. There is no ``Action.Submit``, no
``Action.Execute``, no input, no token and no CSRF value on the card, so a click cannot decide anything.

Deciding stays where it is: the approval page, with a signed-in lead scoped to the client, the four-eyes rule and the
requester verification (B-03, B-89). ``handle_card_response`` is the other half of that rule: if a card response ever
arrives (a forged one, or a future card version), it is audited as refused and points back to the page. It never
reads who the response claims to be from and it never calls ``ProposalQueue.decide``. Because it can never approve, it
cannot be fooled into approving; that is how "validated like a UI decision" is met here (the UI's checks all run on
the page, not on the card).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters.m365.text import one_line, screened_line
from core.audit import AuditMode
from core.audit.router import AuditRouter
from core.queue.store import Proposal, ProposalQueue, QueueError

CARD_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"  # UNVERIFIED
CARD_VERSION = "1.4"  # UNVERIFIED: the version Teams renders
CARD_CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"  # UNVERIFIED
CARD_AGENT = "teams-card"  # the audit identity of a refused card response (never a person)
MAX_CHANGES = 10
MAX_CARD_BYTES = 20_000  # kept well under the ~28 KB Teams message limit (UNVERIFIED figure)
NO_UNDO = "no undo lever: manual undo"
REFUSAL = "a card response cannot decide; open the approval page and sign in as a lead for this client"
_PROPOSAL_ID = re.compile(r"P-[0-9a-f]{12}")
_BASE = re.compile(r"http://(127\.0\.0\.1|localhost)(?::([0-9]{1,5}))?/?")  # exact: no userinfo, path or query


class CardError(ValueError):
    """No card can be built (bad link base, unknown or already decided proposal). Nothing is produced."""


def loopback_base(base_url: object) -> str:
    """The approval page's origin, or ``CardError``: plain http on loopback, no userinfo, path or query."""
    match = _BASE.fullmatch(base_url) if isinstance(base_url, str) else None
    if match is None:
        raise CardError("the approval page must be plain http on 127.0.0.1 or localhost (the page binds loopback only)")
    host, port = match.group(1), match.group(2)
    if port is not None and not 1 <= int(port) <= 65535:
        raise CardError("the approval page port is not usable")
    return f"http://{host}" + (f":{port}" if port is not None else "")


def _dry_run(queue: ProposalQueue, proposal: Proposal) -> Mapping[str, Any] | None:
    """The latest allowed dry-run record for this exact action, from the proposal's own client chain only (B42-2)."""
    audit = queue.runner.audit
    path: Path = audit.path_for(proposal.client) if isinstance(audit, AuditRouter) else audit.path
    if not path.exists():
        return None
    found: Mapping[str, Any] | None = None
    for line in path.read_bytes().splitlines():
        try:
            r = json.loads(line)
            if (
                r["mode"] == "dry-run"
                and r["result"]["status"] == "ok"
                and r["lever"] == proposal.lever
                and r["client"] == proposal.client
                and r["params"] == dict(proposal.params)
            ):
                found = r
        except (ValueError, KeyError, TypeError):
            continue
    return found


def _short(value: Any) -> str:
    return one_line(json.dumps(value, ensure_ascii=True, sort_keys=True), 80)


def _change_line(change: Mapping[str, Any]) -> str:
    op, path = one_line(change.get("op"), 12), one_line(change.get("path"), 60)
    if change.get("op") == "remove":
        what = f"{_short(change.get('before'))} -> removed"
    elif change.get("op") == "add":
        what = f"added -> {_short(change.get('after'))}"
    else:
        what = f"{_short(change.get('before'))} -> {_short(change.get('after'))}"
    return f"{op} {path}: {what}"


def _block(text: str, *, bold: bool = False, subtle: bool = False, size: str | None = None) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "TextBlock", "text": text, "wrap": True}
    if bold:
        block["weight"] = "Bolder"
    if subtle:
        block["isSubtle"] = True
    if size:
        block["size"] = size
    return block


def build_approval_card(queue: ProposalQueue, proposal_id: str, *, base_url: str) -> dict[str, Any]:
    """The Teams message payload for one PENDING proposal. Raises ``CardError``; reads, never writes."""
    base = loopback_base(base_url)
    if not isinstance(proposal_id, str) or not _PROPOSAL_ID.fullmatch(proposal_id):
        raise CardError("not a proposal id")
    try:
        proposal = queue.get(proposal_id)
    except QueueError as exc:
        raise CardError("the queue could not be read") from exc
    if proposal is None or proposal.status != "pending":
        raise CardError("no pending proposal with that id")

    spec = queue.runner.registry.get(proposal.lever)
    impact = spec.impact.L1 if spec is not None and spec.impact is not None else "no impact trace registered"
    undo = f"undo lever: {spec.undo}" if spec is not None and spec.undo else NO_UNDO
    reversibility = spec.reversibility if spec is not None else "unknown"
    upn = proposal.params.get("upn")

    record = _dry_run(queue, proposal)
    diff: list[dict[str, Any]]
    if record is None:
        diff = [_block("No dry-run on record for this exact action. Do not approve it.", bold=True)]
    else:
        changes = [c for c in (record["result"].get("changes") or []) if isinstance(c, Mapping)]
        head = (
            f"Dry-run by {one_line(record['agent'], 40)}, audit seq {one_line(record['seq'], 12)}. "
            "Contact details are masked."
        )
        diff = [_block(head, subtle=True)]
        if not changes:
            diff.append(_block("The dry-run found nothing to change."))
        diff += [_block(_change_line(c)) for c in changes[:MAX_CHANGES]]
        if len(changes) > MAX_CHANGES:
            diff.append(_block(f"...and {len(changes) - MAX_CHANGES} more change(s); see the approval page."))

    title = f"Approval needed: {one_line(proposal.lever, 60)} for {one_line(proposal.client, 63)}"
    person = screened_line(upn, 120) if upn is not None else "none in the parameters"
    body: list[dict[str, Any]] = [
        _block(title, bold=True, size="Medium"),
        {
            "type": "FactSet",
            "facts": [
                {"title": "Proposal", "value": one_line(proposal.id, 20)},
                {"title": "Client", "value": one_line(proposal.client, 63)},
                {"title": "Person affected", "value": person},
                {"title": "Requested by", "value": one_line(proposal.requested_by, 63)},
                {"title": "From", "value": f"{one_line(proposal.source, 20)} {one_line(proposal.ref, 64)}"},
            ],
        },
        _block("What it means for them", bold=True),
        _block(one_line(impact, 400)),
        _block("What will change", bold=True),
        *diff,
        _block("Undo", bold=True),
        _block(f"{one_line(undo, 120)} ({one_line(reversibility, 40)})"),
        _block("Why (the requester's words)", bold=True),
        _block(screened_line(proposal.reason, 200)),
        _block(
            "This card cannot approve or reject. Open the approval page and sign in as a lead for this client; "
            "the decision, the second pair of eyes and the requester check happen there.",
            subtle=True,
        ),
    ]
    payload: dict[str, Any] = {
        "type": "message",
        "attachments": [
            {
                "contentType": CARD_CONTENT_TYPE,
                "contentUrl": None,
                "content": {
                    "$schema": CARD_SCHEMA,
                    "type": "AdaptiveCard",
                    "version": CARD_VERSION,
                    "body": body,
                    "actions": [
                        {"type": "Action.OpenUrl", "title": "Open the approval page", "url": f"{base}/#{proposal.id}"}
                    ],
                },
            }
        ],
    }
    if len(json.dumps(payload).encode("utf-8")) > MAX_CARD_BYTES:
        raise CardError("the card would be too large")
    return payload


@dataclass(frozen=True, slots=True)
class CardResponseResult:
    """What became of a card response. ``decided`` is always False: only the approval page decides."""

    reason: str
    redirect_url: str
    audit_seq: int | None = None

    @property
    def decided(self) -> bool:
        return False


def handle_card_response(queue: ProposalQueue, response: object, *, base_url: str) -> CardResponseResult:
    """Refuse a card response. It never decides, whoever it claims to come from and whatever fields it carries.

    Only the proposal id (and, for the audit mode, the verb) is read from it. If the id names a pending proposal, the
    refusal is audited in that proposal's own client chain by ``teams-card``, never under the claimed person's name
    (nothing on a card response proves who sent it); otherwise nothing is written. The result points back to the page.
    """
    base = loopback_base(base_url)
    raw_id = response.get("proposal") if isinstance(response, Mapping) else None
    raw_verb = response.get("verb") if isinstance(response, Mapping) else None
    if not isinstance(raw_id, str) or not _PROPOSAL_ID.fullmatch(raw_id):
        return CardResponseResult("not a card response for a proposal; nothing was changed", f"{base}/")
    try:
        proposal = queue.get(raw_id)
    except QueueError as exc:
        raise CardError("the queue could not be read") from exc
    if proposal is None or proposal.status != "pending":
        return CardResponseResult("no pending proposal with that id; nothing was changed", f"{base}/")
    mode: AuditMode = "invalid"
    if raw_verb == "approve":
        mode = "approve"
    elif raw_verb == "reject":
        mode = "reject"
    record = queue.runner.audit.append(
        agent=CARD_AGENT,
        client=proposal.client,
        lever=proposal.lever,
        params=dict(proposal.params),
        mode=mode,
        result={"status": "denied", "reason": REFUSAL, "applied": False, "proposal": proposal.id},
    )
    return CardResponseResult(REFUSAL, f"{base}/#{proposal.id}", int(record["seq"]))
