"""Triage one ticket: injection scan, model classification, then rules. The model never picks a lever.

Steps, in order:
1. ``detect_injection`` scans the raw ticket text (before anything else touches it);
2. the text is wrapped with ``wrap_untrusted`` and only that block goes to the gateway's ``classify`` task;
3. the reply is parsed as ``{"category": ...}`` and checked against the fixed category list (anything else is
   ``other``, for a technician to set);
4. rules set priority and queue; a flagged ticket goes to the security queue and gets no lever, it is reported;
5. otherwise at most one lever, from ``LEVER_RULES`` keyed by category, with params from the ticket's form fields,
   is run through the lever runner in dry-run as the triage agent (so it is checked and audited like any call);
6. if the dry-run is allowed and succeeds, a pending proposal (``proposal.py``) is returned for the approval queue,
   requested by the ticket's technician. Executing it is a lead's decision, never triage's;
7. with a proposal, the result also carries the lever's own trace from ``levers/registry.json`` (B-05): who it
   affects (``impact`` L1-L4) and, when the lever says ``verification: "requester"``, the check a lead needs before
   approving. Both come from the registry only, never from ticket text. A flagged ticket gets no lever and no trace.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.gateway import Completion, Gateway, GatewayConfig, ProviderName
from core.guard import Detection, detect_injection, wrap_untrusted
from core.identity import IdentityStore, Role, UnknownIdentity, role_satisfies
from core.levers import InvokeResult, LeverRunner
from workflows.triage.proposal import make_proposal, utc_now
from workflows.triage.rules import (
    CATEGORIES,
    FLAGGED_PRIORITY,
    FLAGGED_QUEUE,
    LEVER_RULES,
    QUEUE_BY_CATEGORY,
    priority_for,
)
from workflows.triage.tickets import Category, Priority, Queue, Ticket

TRIAGE_AGENT = "triage-bot"
REPO_ROOT = Path(__file__).resolve().parents[2]
_MAX_DIFF_LINES = 6
# B-05: what a lead must do before approving a lever marked verification "requester" (C-30, governance HO-4).
CALLBACK_ON_FILE = "call back on the number on file"
_IMPACT_LEVELS = (("L1", "one person"), ("L2", "the client"), ("L3", "the MSP"), ("L4", "the community"))


def classify_gateway(provider: ProviderName = "mock", root: Path = REPO_ROOT) -> Gateway:
    """The configured gateway with the ``classify`` task routed to ``provider``'s small model."""
    data = GatewayConfig.load(root).model_dump()
    data["routes"]["classify"] = {"provider": provider, "model": "small"}
    return Gateway(GatewayConfig.model_validate(data))


@dataclass(frozen=True, slots=True)
class TriageResult:
    """What triage decided and why. ``proposal`` follows the shared contract in ``proposal.py``."""

    ticket_id: str
    client: str
    category: Category
    priority: Priority
    queue: Queue
    why: tuple[str, ...]
    data_used: tuple[str, ...]
    injection: Detection
    proposal: dict[str, Any] | None
    dry_run: InvokeResult | None = None
    # B-05, set only with a proposal and only from the lever's registry entry: L1-L4 impact lines, risk class and
    # the check a lead needs before approving (None when the lever does not require one).
    who_this_affects: dict[str, str] | None = None
    risk_class: str | None = None
    before_approval: str | None = None

    @property
    def lever(self) -> str | None:
        return None if self.proposal is None else str(self.proposal["lever"])

    def to_json(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "client": self.client,
            "category": self.category,
            "priority": self.priority,
            "queue": self.queue,
            "why": list(self.why),
            "data_used": list(self.data_used),
            "injection": {
                "flagged": self.injection.flagged,
                "reasons": [{"rule": r.rule, "evidence": r.evidence} for r in self.injection.reasons],
            },
            "proposal": self.proposal,
            "dry_run": None if self.dry_run is None else self.dry_run.model_dump(mode="json"),
            "who_this_affects": None if self.who_this_affects is None else dict(self.who_this_affects),
            "risk_class": self.risk_class,
            "before_approval": self.before_approval,
        }

    def explain(self) -> str:
        lines = [
            f"{self.ticket_id} ({self.client}): {self.category} / {self.priority} / queue {self.queue}",
            "",
            "Why:",
        ]
        lines += [f"  - {w}" for w in self.why]
        lines += ["", "Data used:", *(f"  - {d}" for d in self.data_used), ""]
        if self.injection.flagged:
            lines.append("Injection check: FLAGGED (reported, not followed)")
            lines += [f"  - {r}" for r in self.injection.reasons]
        else:
            lines.append("Injection check: nothing flagged")
        lines.append("")
        if self.proposal is None:
            lines.append("Proposal: none")
        else:
            p = self.proposal
            lines += [
                f"Proposal {p['id']} ({p['status']}, needs a lead's approval to execute):",
                f"  lever {p['lever']} for {p['client']}, params {json.dumps(p['params'], sort_keys=True)}",
                f"  requested by {p['requested_by']}: {p['reason']}",
            ]
        if self.dry_run is not None and self.dry_run.ok:
            lines.append(f"  dry-run diff ({len(self.dry_run.diff)} change(s), nothing applied):")
            lines += [f"    {c.op:7} {c.path}" for c in self.dry_run.diff[:_MAX_DIFF_LINES]]
            if len(self.dry_run.diff) > _MAX_DIFF_LINES:
                lines.append(f"    ... and {len(self.dry_run.diff) - _MAX_DIFF_LINES} more")
        if self.proposal is not None and self.who_this_affects is not None:
            risk = f", risk class {self.risk_class}" if self.risk_class else ""
            lines += ["", f"Who this affects ({self.proposal['lever']}{risk}, from the lever's registry entry):"]
            lines += [f"  {level} {label}: {self.who_this_affects[level]}" for level, label in _IMPACT_LEVELS]
        if self.proposal is not None and self.before_approval is not None:
            lines += [
                "",
                f"Before approval: {self.before_approval}, never a number given in the ticket "
                "(the lever requires requester verification, C-30).",
            ]
        return "\n".join(lines)


def triage(
    ticket: Ticket,
    gateway: Gateway,
    runner: LeverRunner,
    *,
    agent: str = TRIAGE_AGENT,
    clock: Callable[[], datetime] = utc_now,
) -> TriageResult:
    injection = detect_injection(ticket.text)
    completion = gateway.complete("classify", wrap_untrusted("ticket", ticket.text))
    category, category_why = _category_from(completion)

    if injection.flagged:
        priority: Priority = FLAGGED_PRIORITY
        queue: Queue = FLAGGED_QUEUE
        priority_why = "flagged tickets are reviewed by a person first"
        queue_why = "flagged tickets go to the security queue"
    else:
        priority, reasons = priority_for(category, ticket.text)
        priority_why = "; ".join(reasons)
        queue = QUEUE_BY_CATEGORY[category]
        queue_why = f"rule for {category}"

    why = [
        f"Category {category}: {category_why}.",
        f"Priority {priority}: {priority_why}.",
        f"Queue {queue}: {queue_why}.",
    ]
    data_used = [
        "ticket subject and body (untrusted: scanned for injection, then wrapped before the model saw them)",
        f"ticket client field: {ticket.client}",
        f"model: {completion.provider}/{completion.model} (classify task)" if completion.provider else "model: none",
    ]

    proposal: dict[str, Any] | None = None
    dry_run: InvokeResult | None = None
    who_this_affects: dict[str, str] | None = None
    risk_class: str | None = None
    before_approval: str | None = None
    rule = LEVER_RULES.get(category)
    params = rule.params(ticket) if rule else None
    requester = _technician_for(runner.identities, ticket)

    if injection.flagged:
        names = ", ".join(sorted(injection.rules))
        why.append(f"Injection flagged ({names}): reported for review, its text was not followed, no lever proposed.")
    elif rule is None:
        why.append(f"No lever: no lever rule for category {category}.")
    elif params is None:
        why.append(f"No lever: the {rule.lever} rule needs the ticket's affected_user field, which is empty.")
    elif requester is None:
        why.append(f"No lever: technician {ticket.technician!r} cannot request changes for {ticket.client}.")
    elif not _is_gated_write(runner, rule.lever):
        why.append(f"No lever: {rule.lever} is not a registered write lever behind lead approval.")
    else:
        data_used += [
            f"ticket affected_user field: {params['upn']}",
            f"ticket technician field: {requester}",
            f"levers/registry.json: {rule.lever}",
            f"mock tenant for {ticket.client} (read by the dry-run, never written)",
        ]
        dry_run = runner.invoke(rule.lever, params, identity=agent, client=ticket.client, mode="dry-run")
        if dry_run.ok:
            proposal = make_proposal(
                source="triage",
                ref=ticket.id,
                lever=rule.lever,
                client=ticket.client,
                params=params,
                requested_by=requester,
                reason=f"{ticket.id} triaged as {category}: {rule.lever} for {params['upn']}",
                created=clock(),
            )
            why.append(
                f"Lever {rule.lever}: fixed rule for category {category}, {rule.source}. "
                f"Dry-run as {agent} ok, {len(dry_run.diff)} change(s), nothing applied "
                f"(audit seq {dry_run.audit_seq}); pending lead approval."
            )
            who_this_affects, risk_class, before_approval = _lever_trace(runner, rule.lever)
        else:
            why.append(
                f"No lever: dry-run of {rule.lever} as {agent} was {dry_run.status}: {dry_run.reason} "
                f"(audit seq {dry_run.audit_seq})."
            )

    return TriageResult(
        ticket_id=ticket.id,
        client=ticket.client,
        category=category,
        priority=priority,
        queue=queue,
        why=tuple(why),
        data_used=tuple(data_used),
        injection=injection,
        proposal=proposal,
        dry_run=dry_run,
        who_this_affects=who_this_affects,
        risk_class=risk_class,
        before_approval=before_approval,
    )


def _lever_trace(runner: LeverRunner, lever: str) -> tuple[dict[str, str] | None, str | None, str | None]:
    """The lever's impact lines, risk class and pre-approval check, from the registry only (never the ticket)."""
    spec = runner.registry.get(lever)
    if spec is None:
        return None, None, None
    impact = None if spec.impact is None else {level: str(getattr(spec.impact, level)) for level, _ in _IMPACT_LEVELS}
    before = CALLBACK_ON_FILE if spec.verification == "requester" else None
    return impact, spec.risk_class, before


def _category_from(completion: Completion) -> tuple[Category, str]:
    """The model's category if it is one of ours; otherwise ``other`` and the reason."""
    if not completion.ok:
        return "other", f"model unavailable ({completion.error}); left as other for a technician"
    try:
        value = json.loads(completion.text)["category"]
    except (ValueError, KeyError, TypeError):
        return "other", 'model reply was not {"category": ...} JSON; left as other for a technician'
    for category in CATEGORIES:
        if value == category:
            return category, f"{completion.provider}/{completion.model} classified the wrapped ticket text"
    return "other", f"model named an unknown category {str(value)[:40]!r}; left as other for a technician"


def _technician_for(identities: IdentityStore, ticket: Ticket) -> str | None:
    """The ticket's technician if they are a known human who may act for the ticket's client."""
    try:
        who = identities.get(ticket.technician)
    except UnknownIdentity:
        return None
    if not role_satisfies(who.role, Role.TECHNICIAN) or not who.can_act_for(ticket.client):
        return None
    return who.id


def _is_gated_write(runner: LeverRunner, lever: str) -> bool:
    spec = runner.registry.get(lever)
    return spec is not None and spec.lever_class == "write" and spec.approval == "lead"
