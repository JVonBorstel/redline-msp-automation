"""Where the scheduler keeps job state and sends proposals and audit records (B-81).

Three small Protocols so storage can change without touching the scheduler. The SQLite queue (B-82) is meant to sit
behind `JobStore`; until then these in-memory versions are the only implementations. None of them can run a lever.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from core.audit.router import AuditRouter
from core.queue.store import proposal_id
from core.scheduler.models import ProposedAction, Unit, UnitRecord

SCHEDULER_AGENT = "scheduler"


class JobStore(Protocol):
    """Keyed job state. `claim` must be atomic: of two callers with one key, exactly one gets True."""

    def get(self, key: str) -> UnitRecord | None: ...

    def claim(self, unit: Unit) -> bool: ...

    def finish(self, record: UnitRecord) -> None: ...

    def records(self) -> list[UnitRecord]: ...


class ProposalSink(Protocol):
    """Takes a proposed lever for a client and returns its proposal id. Queues it; never runs it."""

    def propose(self, client: str, action: ProposedAction, ref: str) -> str: ...


class UnitAudit(Protocol):
    """Records one finished unit. Raising marks the unit failed (the audit is not optional once wired)."""

    def record(self, unit: Unit, record: UnitRecord) -> None: ...


class InMemoryJobStore:
    def __init__(self) -> None:
        self._rows: dict[str, UnitRecord] = {}

    def get(self, key: str) -> UnitRecord | None:
        return self._rows.get(key)

    def claim(self, unit: Unit) -> bool:
        if unit.key in self._rows:
            return False
        self._rows[unit.key] = UnitRecord(
            key=unit.key,
            job=unit.job,
            client=unit.client,
            period=unit.period,
            status="running",
            at=unit.as_of.isoformat(timespec="seconds"),
        )
        return True

    def finish(self, record: UnitRecord) -> None:
        self._rows[record.key] = record

    def records(self) -> list[UnitRecord]:
        return list(self._rows.values())


@dataclass(frozen=True)
class QueuedProposal:
    id: str
    client: str
    lever: str
    params: dict[str, Any]
    reason: str
    ref: str


class InMemoryProposalSink:
    """Keeps proposals in a list. The id is the queue's shared contract (`core.queue.store.proposal_id`)."""

    def __init__(self) -> None:
        self.proposals: list[QueuedProposal] = []

    def propose(self, client: str, action: ProposedAction, ref: str) -> str:
        pid = proposal_id(action.lever, client, action.params)
        if not any(p.id == pid for p in self.proposals):
            self.proposals.append(QueuedProposal(pid, client, action.lever, dict(action.params), action.reason, ref))
        return pid


class RouterAudit:
    """One `job.run` record per finished unit, in that client's own chain (B-42). Mode is dry-run: nothing runs."""

    def __init__(self, router: AuditRouter) -> None:
        self._router = router

    def record(self, unit: Unit, record: UnitRecord) -> None:
        self._router.append(
            agent=SCHEDULER_AGENT,
            client=unit.client,
            lever=f"scheduler.{unit.job}",
            params={"job": unit.job, "period": unit.period},
            mode="dry-run",
            result={"status": record.status, "detail": record.detail, "proposals": len(record.proposal_ids)},
            event="job.run",
            actor_kind="agent",
            lever_version=1,
        )
