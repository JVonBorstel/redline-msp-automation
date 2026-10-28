"""The deterministic rule evaluator (B-83): a rule set and a snapshot in, alerts out.

The evaluator reads no clock, no file and no network. ``Snapshot.now`` is the only time it knows, and the same rules and
snapshot always give the same alerts in the same order (severity, rule id, client, subject), whatever order the lists in
the snapshot came in. Alerts carry ids, counts and ages, never content: the snapshot itself holds none (audit
events keep the fixed ``reason`` code, not the record's params or result).

Windows are closed at both ends: an event exactly ``window_s`` old counts, one dated after ``now`` does not.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from workflows.monitoring.rules import (
    SEVERITY_ORDER,
    ApprovalBacklogAge,
    AuditChainFailure,
    BreakerOpen,
    BudgetExhaustion,
    DeadLetterGrowth,
    Rule,
    RuleSet,
    Severity,
)

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_][a-z0-9._:-]{0,63}$")]
Reason = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9:-]{0,63}$")]
Name = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuditEvent(_Strict):
    """The part of an audit record a rule may look at. ``reason`` is a fixed code such as ``circuit-open``."""

    ts: AwareDatetime
    client: Slug | None = None
    event: Slug
    reason: Reason | None = None
    provider: Slug | None = None


class ChainCheck(_Strict):
    """The outcome of verifying one audit chain (``scope`` is the client id or ``_msp``)."""

    scope: Slug
    ok: bool
    broken_seq: int | None = Field(default=None, ge=1)


class PendingApproval(_Strict):
    client: Slug
    id: Name
    created: AwareDatetime


class DeadLetterSample(_Strict):
    """The dead-letter count for one client at one time (from ``SqliteJobQueue.dead_letters``)."""

    client: Slug
    ts: AwareDatetime
    count: int = Field(ge=0)


class Snapshot(_Strict):
    now: AwareDatetime
    audit_events: list[AuditEvent] = Field(default_factory=list)
    chain_checks: list[ChainCheck] = Field(default_factory=list)
    pending_approvals: list[PendingApproval] = Field(default_factory=list)
    dead_letter_samples: list[DeadLetterSample] = Field(default_factory=list)


class Alert(_Strict):
    rule_id: str
    kind: str
    severity: Severity
    client: str | None
    subject: str
    summary: str
    detail: dict[str, int]
    rules_version: int
    as_of: AwareDatetime


def load_snapshot(path: Path) -> Snapshot:
    return Snapshot.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _in_window(ts: datetime, now: datetime, window_s: int) -> bool:
    return now - timedelta(seconds=window_s) <= ts <= now


def _alert(
    rule: Rule, snap: Snapshot, rules: RuleSet, client: str | None, subject: str, detail: dict[str, int]
) -> Alert:
    return Alert(
        rule_id=rule.id,
        kind=rule.kind,
        severity=rule.severity,
        client=client,
        subject=subject,
        summary=rule.summary,
        detail=detail,
        rules_version=rules.version,
        as_of=snap.now,
    )


def _chain(rule: AuditChainFailure, snap: Snapshot, rules: RuleSet) -> list[Alert]:
    return [
        _alert(rule, snap, rules, None, check.scope, {"broken_seq": check.broken_seq or 0})
        for check in snap.chain_checks
        if not check.ok
    ]


def _breaker(rule: BreakerOpen, snap: Snapshot, rules: RuleSet) -> list[Alert]:
    hits: dict[str, list[AuditEvent]] = defaultdict(list)
    for e in snap.audit_events:
        if e.event == "model.complete" and e.reason == "circuit-open" and _in_window(e.ts, snap.now, rule.window_s):
            hits[e.provider or "unknown"].append(e)
    return [
        _alert(rule, snap, rules, None, provider, {"events": len(found), "clients": len({e.client for e in found})})
        for provider, found in hits.items()
        if len(found) >= rule.min_events
    ]


def _budget(rule: BudgetExhaustion, snap: Snapshot, rules: RuleSet) -> list[Alert]:
    hits: dict[tuple[str, str | None], int] = defaultdict(int)
    for e in snap.audit_events:
        if e.event != "model.complete" or not e.reason or not e.reason.startswith("budget:"):
            continue
        if _in_window(e.ts, snap.now, rule.window_s):
            scope = e.reason.split(":")[1]
            hits[(scope, e.client if scope == "client" else None)] += 1
    return [
        _alert(rule, snap, rules, client, scope, {"events": count})
        for (scope, client), count in hits.items()
        if count >= rule.min_events
    ]


def _backlog(rule: ApprovalBacklogAge, snap: Snapshot, rules: RuleSet) -> list[Alert]:
    ages: dict[str, list[int]] = defaultdict(list)
    for p in snap.pending_approvals:
        ages[p.client].append(int((snap.now - p.created).total_seconds()))
    return [
        _alert(rule, snap, rules, client, "approvals", {"oldest_age_s": max(found), "pending": len(found)})
        for client, found in ages.items()
        if max(found) > rule.max_age_s
    ]


def _dead_letters(rule: DeadLetterGrowth, snap: Snapshot, rules: RuleSet) -> list[Alert]:
    by_client: dict[str, list[DeadLetterSample]] = defaultdict(list)
    for s in snap.dead_letter_samples:
        if s.ts <= snap.now:
            by_client[s.client].append(s)
    start = snap.now - timedelta(seconds=rule.window_s)
    alerts: list[Alert] = []
    for client, samples in by_client.items():
        samples.sort(key=lambda s: (s.ts, s.count))
        inside = [s for s in samples if s.ts >= start]
        before = [s for s in samples if s.ts < start]
        if not inside or not (before or len(inside) > 1):
            continue  # no sample in the window, or a single sample with nothing to compare it to
        baseline = before[-1] if before else inside[0]
        growth = inside[-1].count - baseline.count
        if growth >= rule.min_growth:
            alerts.append(
                _alert(rule, snap, rules, client, "dead-letters", {"growth": growth, "count": inside[-1].count})
            )
    return alerts


def evaluate(rules: RuleSet, snapshot: Snapshot) -> list[Alert]:
    """Every alert the snapshot raises under the rules, sorted by severity, rule id, client, subject."""
    alerts: list[Alert] = []
    for rule in rules.rules:
        if isinstance(rule, AuditChainFailure):
            alerts += _chain(rule, snapshot, rules)
        elif isinstance(rule, BreakerOpen):
            alerts += _breaker(rule, snapshot, rules)
        elif isinstance(rule, BudgetExhaustion):
            alerts += _budget(rule, snapshot, rules)
        elif isinstance(rule, ApprovalBacklogAge):
            alerts += _backlog(rule, snapshot, rules)
        else:
            alerts += _dead_letters(rule, snapshot, rules)
    alerts.sort(key=lambda a: (SEVERITY_ORDER.index(a.severity), a.rule_id, a.client or "", a.subject))
    return alerts
