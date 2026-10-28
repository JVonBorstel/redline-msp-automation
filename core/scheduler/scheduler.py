"""The scheduler (B-81): `tick()` fans each due job out to one unit per client, keyed `job/client/period`.

- Deterministic: time comes from the injected clock (or the `now` argument), nothing sleeps, nothing runs in parallel.
  "Concurrency caps" are admission caps per tick: a unit over a cap is deferred (not claimed) and a later tick takes it.
- Idempotent: a key already in the store (ok, failed or still running) is skipped. A failed unit is not retried in the
  same period; a person looks at it. A crash between claim and finish leaves the key `running`; recovering from that
  belongs to the durable store (B-82) and is not built here.
- Isolated: an exception in one unit is recorded as that unit's failure (error class name only) and the tick goes on.
- Proposals only: a workflow returns a report and proposed levers. Each proposal must name a registered lever whose
  scope covers the client, with valid params, and a write lever must support dry-run. They go to a ProposalSink
  for a person to approve. This module holds no runner and has no call that runs a lever.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime

from core.audit.router import valid_client_id
from core.levers.registry import Registry
from core.levers.schema import validate_params
from core.scheduler.models import (
    REPORT_MAX,
    JobConfig,
    SchedulerConfig,
    SchedulerError,
    Status,
    TickReport,
    Unit,
    UnitRecord,
    UnitResult,
    job_key,
    period_for,
)
from core.scheduler.stores import JobStore, ProposalSink, UnitAudit

Workflow = Callable[[Unit], UnitResult]


class _Refused(Exception):
    """A unit's result was refused; `code` is the short detail kept in the record."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Scheduler:
    def __init__(
        self,
        config: SchedulerConfig,
        workflows: Mapping[str, Workflow],
        clients: Sequence[str],
        *,
        clock: Callable[[], datetime],
        store: JobStore,
        sink: ProposalSink,
        registry: Registry,
        audit: UnitAudit | None = None,
    ) -> None:
        missing = sorted({j.workflow for j in config.jobs if j.workflow not in workflows})
        if missing:
            raise SchedulerError(f"jobs name workflows that are not registered: {', '.join(missing)}")
        self._config = config
        self._workflows = dict(workflows)
        self._clients = sorted(set(clients))
        self._clock = clock
        self._store = store
        self._sink = sink
        self._registry = registry
        self._audit = audit

    def tick(self, now: datetime | None = None) -> TickReport:
        at = self._clock() if now is None else now
        report = TickReport()
        valid = [c for c in self._clients if valid_client_id(c)]
        report.invalid_clients.extend(c for c in self._clients if not valid_client_id(c))
        started = 0
        per_client: dict[str, int] = {}
        for job in self._config.jobs:
            period = period_for(job.every, at)  # also refuses a naive or non-UTC time
            if at.hour < job.not_before_hour:
                report.not_due.append(job.name)
                continue
            job_started = 0
            for client in self._eligible(job, valid, report):
                key = job_key(job.name, client, period)
                if self._store.get(key) is not None:
                    report.skipped.append(key)
                    continue
                if (
                    started >= self._config.global_cap
                    or per_client.get(client, 0) >= self._config.per_client_cap
                    or (job.job_cap is not None and job_started >= job.job_cap)
                ):
                    report.deferred.append(key)
                    continue
                unit = Unit(key=key, job=job.name, client=client, period=period, as_of=at)
                if not self._store.claim(unit):
                    report.skipped.append(key)
                    continue
                started += 1
                job_started += 1
                per_client[client] = per_client.get(client, 0) + 1
                final = self._run_unit(job, unit)
                (report.ran if final.status == "ok" else report.failed).append(key)
        return report

    @staticmethod
    def _eligible(job: JobConfig, valid: list[str], report: TickReport) -> list[str]:
        if job.clients == "all":
            chosen = list(valid)
        else:
            chosen = sorted(c for c in set(job.clients) if c in valid)
            for name in sorted(set(job.clients) - set(valid)):
                if name not in report.unknown_clients:
                    report.unknown_clients.append(name)
        off = set(job.disabled_clients)
        return [c for c in chosen if c not in off]

    def _run_unit(self, job: JobConfig, unit: Unit) -> UnitRecord:

        def make(status: Status, detail: str = "", report: str = "", ids: tuple[str, ...] = ()) -> UnitRecord:
            return UnitRecord(
                key=unit.key,
                job=unit.job,
                client=unit.client,
                period=unit.period,
                status=status,
                at=unit.as_of.isoformat(timespec="seconds"),
                detail=detail,
                report=report,
                proposal_ids=ids,
            )

        try:
            result = self._workflows[job.workflow](unit)
            if not isinstance(result, UnitResult):
                raise _Refused("bad-result-type")
            ids = self._propose(unit, result)
            record = make("ok", report=_one_line(result.report), ids=ids)
        except _Refused as refused:
            record = make("failed", refused.code)
        except Exception as exc:
            record = make("failed", type(exc).__name__)
        if self._audit is not None:
            try:
                self._audit.record(unit, record)
            except Exception:
                record = make("failed", "audit-failed", record.report)
        self._store.finish(record)
        return record

    def _propose(self, unit: Unit, result: UnitResult) -> tuple[str, ...]:
        # Check every proposal first so one bad one queues none of this unit's proposals.
        for action in result.proposals:
            spec = self._registry.get(action.lever)
            if spec is None:
                raise _Refused("lever-not-registered")
            if spec.client_scope != "any" and unit.client not in spec.client_scope:
                raise _Refused("lever-out-of-scope")
            if validate_params(spec.params, action.params):
                raise _Refused("params-invalid")
            if spec.lever_class == "write" and not spec.dry_run:
                raise _Refused("lever-has-no-dry-run")
        return tuple(self._sink.propose(unit.client, action, unit.key) for action in result.proposals)


def _one_line(text: str) -> str:
    return " ".join(text.split())[:REPORT_MAX]
