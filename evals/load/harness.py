"""B-84 load and failure harness: synthetic lever calls through the B-82 SQLite queue and audit store.

What it is: a model of "many clients each submit lever calls; workers claim them, call an adapter, write an audit
record and acknowledge". The queue (`SqliteJobQueue`), the audit store (`SqliteAuditStore`) and the B-80 circuit
breaker are the real classes. The "lever call" and the "adapter" are synthetic: the adapter is a SQLite file standing
in for an external system that applies an effect once per (client, idempotency key). The real `LeverRunner` is NOT in
this loop (it needs identities, approvals and a registry); its own timeout and idempotency behaviour is tested in
tests/py/levers. Numbers from here describe this harness on this machine only (see tools/bench_load.py).

Determinism, so a failure can be replayed:
- Every fault is a pure function of (seed, client, key, attempt): `FaultPlan.fault` hashes them. Which worker runs a
  job, and when, cannot change what happens to it, so `FaultPlan.expected` is an oracle for every job's ending, its
  attempt count, whether the effect was applied and how many audit records it leaves. The single-threaded run checks
  every job against that oracle.
- Time is a `SimClock` the driver advances by hand; nothing sleeps for time to pass. Randomness is seeded.
  `LoadReport.digest` covers every job outcome and every audit chain head, so two runs of one seed must match exactly.
- `run_threaded` uses real threads for real lock contention. Its schedule is not deterministic, so callers assert
  invariants (no lost job, no double apply, chains verify), never exact counts.

Fault kinds, per attempt:
- `timeout`: the adapter does not answer; nothing is applied; an `error` audit record; the job is retried after backoff.
- `adapter_crash`: the adapter raises an unexpected exception; same handling; only the exception class name is recorded.
- `worker_crash_before`: the worker dies after claiming and before calling; nothing applied, nothing recorded; the lease
  expires and the job is claimed again.
- `worker_crash_after`: the worker dies after the effect was applied and before acknowledging. The retry reaches the
  adapter again and must not apply twice: the adapter's idempotency key makes it a replay.
- A poisoned job fails with `adapter_crash` on every attempt and ends in the dead letters.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import sqlite3
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from core.audit.chain import canonical_json
from core.audit.sqlite_store import SqliteAuditStore
from core.gateway.budget import CircuitBreaker
from core.queue.sqlite_store import Job, LeaseLost, QueueConflict, SqliteJobQueue

START = datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC)
LEVERS: tuple[str, ...] = ("ticket.note-add", "device.tag-set", "user.label-set", "group.note-add")
KIND = "lever.call"

Fault = Literal["ok", "timeout", "adapter_crash", "worker_crash_before", "worker_crash_after"]
FAULT_KINDS: tuple[str, ...] = ("timeout", "adapter_crash", "worker_crash_before", "worker_crash_after")
Outcome = Literal["idle", "done", "retry", "dead", "crashed", "lease-lost", "breaker-open"]

_TOKEN = re.compile(r"tok-(client-\d+)")


class AdapterTimeout(Exception):
    """The synthetic adapter did not answer in time."""


class WorkerCrash(Exception):
    """Raised inside a worker to stand for its process dying: the caller must not acknowledge anything."""


def client_id(index: int) -> str:
    return f"client-{index:03d}"


def tenant_token(client: str) -> str:
    """A marker that belongs to one client and appears in its payloads; finding another client's marker is a leak."""
    return f"tok-{client}"


# ---------------------------------------------------------------------------------------------------------------
# clocks
# ---------------------------------------------------------------------------------------------------------------


class SimClock:
    """Injected time. `__call__` is the queue/audit clock, `seconds()` is the breaker clock; only `advance` moves it."""

    def __init__(self, start: datetime = START) -> None:
        self._start = start
        self._now = start
        self._lock = threading.Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self._now

    def seconds(self) -> float:
        return (self() - self._start).total_seconds()

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now += timedelta(seconds=seconds)


class RealClock(SimClock):
    """The wall clock plus an offset, for the test that kills a real child process. `advance` jumps the offset."""

    def __init__(self) -> None:
        super().__init__(datetime.now(UTC))

    def __call__(self) -> datetime:
        return datetime.now(UTC) + (super().__call__() - self._start)


# ---------------------------------------------------------------------------------------------------------------
# fault plan and oracle
# ---------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Expected:
    """What a job must come to under a plan, whatever the schedule."""

    status: Literal["done", "dead"]
    attempts: int
    applied: bool
    audit_records: int


@dataclass(frozen=True)
class FaultPlan:
    seed: int = 84
    timeout: float = 0.0
    adapter_crash: float = 0.0
    worker_crash_before: float = 0.0
    worker_crash_after: float = 0.0
    poison_rate: float = 0.0
    outage: tuple[float, float] | None = None  # sim seconds [start, end): every call times out
    script: Mapping[tuple[str, str], Sequence[str]] = field(default_factory=dict)  # (client, key) -> fault per attempt

    def __post_init__(self) -> None:
        rates = (self.timeout, self.adapter_crash, self.worker_crash_before, self.worker_crash_after)
        if any(not 0.0 <= r <= 1.0 for r in (*rates, self.poison_rate)):
            raise ValueError("fault rates must be between 0 and 1")
        if sum(rates) > 1.0:
            raise ValueError("fault rates per attempt must add up to at most 1")

    def _unit(self, *parts: object) -> float:
        digest = hashlib.sha256("|".join(str(p) for p in (self.seed, *parts)).encode()).digest()
        return int.from_bytes(digest[:8], "big") / 2**64

    def is_poison(self, client: str, key: str) -> bool:
        return self.poison_rate > 0 and self._unit("poison", client, key) < self.poison_rate

    def fault(self, client: str, key: str, attempt: int, now_s: float) -> Fault:
        if self.outage is not None and self.outage[0] <= now_s < self.outage[1]:
            return "timeout"
        scripted = self.script.get((client, key))
        if scripted is not None:
            return scripted[attempt - 1] if attempt <= len(scripted) else "ok"  # type: ignore[return-value]
        if self.is_poison(client, key):
            return "adapter_crash"
        draw = self._unit("fault", client, key, attempt)
        edge = 0.0
        for kind, rate in (
            ("timeout", self.timeout),
            ("adapter_crash", self.adapter_crash),
            ("worker_crash_before", self.worker_crash_before),
            ("worker_crash_after", self.worker_crash_after),
        ):
            edge += rate
            if draw < edge:
                return kind  # type: ignore[return-value]
        return "ok"

    def expected(self, client: str, key: str, max_attempts: int) -> Expected:
        """Walk the attempts the way the queue does. Ignores `outage` (a window in time, not a function of attempts)."""
        applied, audit = False, 0
        for attempt in range(1, max_attempts + 1):
            kind = self.fault(client, key, attempt, math.inf)
            if kind == "ok":
                return Expected("done", attempt, True, audit + 1)
            if kind in ("timeout", "adapter_crash"):
                audit += 1
            elif kind == "worker_crash_after":
                applied = True
        return Expected("dead", max_attempts, applied, audit + 1)  # the dead-letter record


# The fault mix the load test, the benchmark and the eval gate share (a few percent of each kind, 2% poison jobs).
STANDARD_PLAN = FaultPlan(
    seed=84, timeout=0.08, adapter_crash=0.05, worker_crash_before=0.03, worker_crash_after=0.04, poison_rate=0.02
)


# ---------------------------------------------------------------------------------------------------------------
# the synthetic adapter (the "external system")
# ---------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Effect:
    client: str
    key: str
    target: str
    value: int
    token: str
    applications: int  # times the effect really happened
    deliveries: int  # times a call reached the adapter's apply step


class SyntheticAdapter:
    """Applies an effect once per (client, idempotency key). `idempotent=False` is the control that double-applies."""

    def __init__(self, path: Path, *, idempotent: bool = True) -> None:
        self.path = Path(path)
        self.idempotent = idempotent
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as con:
            con.execute("PRAGMA journal_mode = WAL")
            con.execute(
                "CREATE TABLE IF NOT EXISTS effects (client TEXT NOT NULL, key TEXT NOT NULL, target TEXT NOT NULL,"
                " value INTEGER NOT NULL, token TEXT NOT NULL, applications INTEGER NOT NULL,"
                " deliveries INTEGER NOT NULL, PRIMARY KEY (client, key))"
            )

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        con.execute("PRAGMA synchronous = OFF")  # the external system's durability is not what is under test
        return con

    def call(self, job: Job, fault: str) -> dict[str, Any]:
        """One call for one attempt. Raises for every fault kind except `ok`."""
        if fault == "timeout":
            raise AdapterTimeout("the adapter did not answer")
        if fault == "adapter_crash":
            raise RuntimeError("synthetic adapter crash")
        if fault == "worker_crash_before":
            raise WorkerCrash("worker died before the call")
        replayed = self._apply(job)
        if fault == "worker_crash_after":
            raise WorkerCrash("worker died after the effect, before the acknowledgement")
        return self._result(job, replayed)

    @staticmethod
    def _digest(job: Job) -> str:
        raw = f"{job.client}|{job.payload['target']}|{job.payload['value']}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]  # 16 hex: the audit redactor blanks 32+ hex runs

    def _result(self, job: Job, replayed: bool) -> dict[str, Any]:
        return {
            "client": job.client,
            "target": job.payload["target"],
            "token": job.payload["tenant_token"],
            "applied": True,
            "replayed": replayed,
            "digest": self._digest(job),
        }

    def _apply(self, job: Job) -> bool:
        """Apply (or replay) the effect; True when it was a replay."""
        with closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT applications FROM effects WHERE client = ? AND key = ?", (job.client, job.idempotency_key)
            ).fetchone()
            if row is None:
                con.execute(
                    "INSERT INTO effects VALUES (?, ?, ?, ?, ?, 1, 1)",
                    (
                        job.client,
                        job.idempotency_key,
                        job.payload["target"],
                        job.payload["value"],
                        job.payload["tenant_token"],
                    ),
                )
                replayed = False
            else:
                step = 0 if self.idempotent else 1
                con.execute(
                    "UPDATE effects SET deliveries = deliveries + 1, applications = applications + ?"
                    " WHERE client = ? AND key = ?",
                    (step, job.client, job.idempotency_key),
                )
                replayed = self.idempotent
            con.execute("COMMIT")
        return replayed

    def effects(self) -> list[Effect]:
        with closing(self._connect()) as con:
            rows = con.execute("SELECT * FROM effects ORDER BY client, key").fetchall()
        return [Effect(*row) for row in rows]

    def effect(self, client: str, key: str) -> Effect | None:
        with closing(self._connect()) as con:
            row = con.execute("SELECT * FROM effects WHERE client = ? AND key = ?", (client, key)).fetchone()
        return Effect(*row) if row else None

    def double_applied(self) -> list[tuple[str, str, int]]:
        return [(e.client, e.key, e.applications) for e in self.effects() if e.applications > 1]


# ---------------------------------------------------------------------------------------------------------------
# configuration, context, timings
# ---------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LoadConfig:
    seed: int = 84
    clients: int = 300
    jobs: int = 10_000
    workers: int = 8
    max_attempts: int = 5
    lease_s: float = 10.0
    backoff_base_s: float = 1.0
    tick_s: float = 1.0  # simulated seconds that pass between sweeps
    duplicate_rate: float = 0.04  # share of submissions repeated with the same key and request
    conflict_rate: float = 0.01  # share repeated with the same key and a different request
    idempotent_adapter: bool = True
    plan: FaultPlan = field(default_factory=FaultPlan)
    breaker_threshold: int | None = None
    breaker_open_s: float = 10.0
    real_clock: bool = False
    max_sweeps: int = 20_000


class Timings:
    """Wall-time samples by operation name. Only the benchmark passes one; tests and the gate never time anything."""

    def __init__(self) -> None:
        self.samples: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def add(self, name: str, seconds: float) -> None:
        with self._lock:
            self.samples[name].append(seconds)


@dataclass
class Context:
    queue: SqliteJobQueue
    audit: SqliteAuditStore
    adapter: SyntheticAdapter
    clock: SimClock
    plan: FaultPlan
    lease_s: float
    max_attempts: int
    breaker: CircuitBreaker | None = None
    timings: Timings | None = None
    stats: Counter[str] = field(default_factory=Counter)
    audit_counts: Counter[str] = field(default_factory=Counter)
    audited_dead: set[tuple[str, int, datetime]] = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def bump(self, name: str, amount: int = 1) -> None:
        with self.lock:
            self.stats[name] += amount

    @contextmanager
    def timed(self, name: str) -> Iterator[None]:
        if self.timings is None:
            yield
            return
        began = time.perf_counter()
        try:
            yield
        finally:
            self.timings.add(name, time.perf_counter() - began)


def build_context(workdir: Path, cfg: LoadConfig) -> Context:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    clock: SimClock = RealClock() if cfg.real_clock else SimClock()
    breaker = (
        CircuitBreaker(failure_threshold=cfg.breaker_threshold, open_s=cfg.breaker_open_s, clock=clock.seconds)
        if cfg.breaker_threshold is not None
        else None
    )
    return Context(
        queue=SqliteJobQueue(workdir / "queue.db", clock=clock, backoff_base_s=cfg.backoff_base_s),
        audit=SqliteAuditStore(workdir / "audit.db", clock=clock),
        adapter=SyntheticAdapter(workdir / "effects.db", idempotent=cfg.idempotent_adapter),
        clock=clock,
        plan=cfg.plan,
        lease_s=cfg.lease_s,
        max_attempts=cfg.max_attempts,
        breaker=breaker,
    )


# ---------------------------------------------------------------------------------------------------------------
# one worker step
# ---------------------------------------------------------------------------------------------------------------


def _audit(ctx: Context, job: Job, status: str, **extra: Any) -> None:
    result = {"status": status, "idempotency": job.idempotency_key, "attempt": job.attempts, **extra}
    with ctx.timed("audit"):
        ctx.audit.append(
            agent="load-worker",
            client=job.client,
            lever=str(job.payload["lever"]),
            params={"target": job.payload["target"], "job": job.id},
            mode="execute",
            result=result,
            actor_kind="agent",
            request_id=f"{job.idempotency_key}#{job.attempts}-{status}",
        )
    with ctx.lock:
        ctx.audit_counts[job.client] += 1


def _audit_dead(ctx: Context, job: Job) -> None:
    mark = (job.client, job.id, job.updated_at)
    with ctx.lock:
        if mark in ctx.audited_dead:
            return
        ctx.audited_dead.add(mark)
    _audit(ctx, job, "dead-letter", applied=False, reason=str(job.last_error or "")[:200])


def _fail(ctx: Context, job: Job, exc: Exception) -> Outcome:
    name = type(exc).__name__  # the class only: exception text could carry anything
    _audit(ctx, job, "error", error=name, applied=False)
    try:
        with ctx.timed("fail"):
            failed = ctx.queue.fail(job, name)
    except LeaseLost:
        ctx.bump("lease_lost")
        return "lease-lost"
    if failed.status == "dead":
        _audit_dead(ctx, failed)
        return "dead"
    return "retry"


def process_one(ctx: Context, client: str, worker: str) -> Outcome:
    """Claim this client's next due job and carry it through the adapter. One call is one attempt."""
    breaker = ctx.breaker
    if breaker is not None and not breaker.allow():
        ctx.bump("breaker_open")
        return "breaker-open"
    try:
        with ctx.timed("claim"):
            job = ctx.queue.claim(client, worker, lease_s=ctx.lease_s)
    except BaseException:
        if breaker is not None:
            breaker.cancel_probe()
        raise
    if job is None:
        if breaker is not None:
            breaker.cancel_probe()  # allow() may have handed out the half-open probe; nothing used it
        for dead in ctx.queue.dead_letters(client):  # a lease-expiry death has no worker to write its record
            _audit_dead(ctx, dead)
        return "idle"
    fault = ctx.plan.fault(client, job.idempotency_key, job.attempts, ctx.clock.seconds())
    if fault != "worker_crash_before":
        ctx.bump("adapter_calls")
    if fault != "ok":
        ctx.bump(f"fault.{fault}")
    try:
        with ctx.timed("adapter"):
            result = ctx.adapter.call(job, fault)
    except WorkerCrash:
        ctx.bump("worker_crashes")
        if breaker is not None:
            breaker.cancel_probe()
        return "crashed"  # no acknowledgement, no audit record: only the lease tells
    except Exception as exc:  # noqa: BLE001 - a timeout or an adapter crash is an error result by design
        if breaker is not None:
            breaker.record_failure()
        return _fail(ctx, job, exc)
    if breaker is not None:
        breaker.record_success()
    _audit(ctx, job, "ok", applied=True, replayed=result["replayed"], client=client)
    try:
        with ctx.timed("complete"):
            ctx.queue.complete(job, result)
    except LeaseLost:
        ctx.bump("lease_lost")
        return "lease-lost"
    return "done"


# ---------------------------------------------------------------------------------------------------------------
# submission, drivers
# ---------------------------------------------------------------------------------------------------------------


@dataclass
class Submission:
    per_client: dict[str, int] = field(default_factory=dict)
    created: int = 0
    duplicates_collapsed: int = 0
    conflicts_refused: int = 0
    violations: int = 0


def submit_jobs(ctx: Context, cfg: LoadConfig) -> Submission:
    """Submit `cfg.jobs` calls over `cfg.clients` clients (each client gets at least one when jobs >= clients)."""
    rng = random.Random(cfg.seed)  # noqa: S311 - seeded simulation, not cryptography
    counters: Counter[int] = Counter()
    sub = Submission()
    for i in range(cfg.jobs):
        index = i if i < cfg.clients else rng.randrange(cfg.clients)
        client = client_id(index)
        key = f"call-{counters[index]:05d}"  # the same key text recurs in every client: keys are per client
        counters[index] += 1
        payload: dict[str, Any] = {
            "lever": rng.choice(LEVERS),
            "target": f"T-{rng.randrange(1_000_000)}",
            "value": rng.randrange(1000),
            "tenant_token": tenant_token(client),
        }
        repeat, clash = rng.random() < cfg.duplicate_rate, rng.random() < cfg.conflict_rate
        with ctx.timed("enqueue"):
            made = ctx.queue.enqueue(client, KIND, payload, key, max_attempts=cfg.max_attempts)
        sub.violations += not made.created
        sub.created += 1
        sub.per_client[client] = sub.per_client.get(client, 0) + 1
        if repeat:
            again = ctx.queue.enqueue(client, KIND, payload, key, max_attempts=cfg.max_attempts)
            if again.created or again.job.id != made.job.id:
                sub.violations += 1
            sub.duplicates_collapsed += 1
        if clash:
            try:
                ctx.queue.enqueue(client, KIND, {**payload, "value": payload["value"] + 1}, key)
                sub.violations += 1  # a different request under a used key must never be accepted
            except QueueConflict:
                sub.conflicts_refused += 1
    return sub


def _outstanding(ctx: Context, client: str) -> bool:
    counts = ctx.queue.counts(client)
    return counts["queued"] + counts["leased"] > 0


def run_simulation(workdir: Path, cfg: LoadConfig, timings: Timings | None = None) -> LoadReport:
    """Single-threaded, fully deterministic: sweeps over the clients with work left, one step each, clock ticking."""
    ctx = build_context(workdir, cfg)
    ctx.timings = timings
    sub = submit_jobs(ctx, cfg)
    rng = random.Random(cfg.seed + 1)  # noqa: S311 - seeded simulation, not cryptography
    remaining = sorted(sub.per_client)
    generation = [0] * cfg.workers
    sweeps = 0
    while remaining and sweeps < cfg.max_sweeps:
        sweeps += 1
        still: list[str] = []
        for position, client in enumerate(rng.sample(remaining, len(remaining))):
            slot = position % cfg.workers
            outcome = process_one(ctx, client, f"w{slot}.{generation[slot]}")
            if outcome == "crashed":
                generation[slot] += 1  # the worker is restarted under a new name
            if outcome == "breaker-open" or _outstanding(ctx, client):
                still.append(client)
        remaining = sorted(still)
        ctx.clock.advance(cfg.tick_s)
    return summarize(ctx, cfg, sub, sweeps=sweeps, finished=not remaining, oracle=cfg.plan.outage is None)


def run_threaded(workdir: Path, cfg: LoadConfig, threads: int, timings: Timings | None = None) -> LoadReport:
    """Real threads on shared stores. A ticker thread (this one) moves the clock; the report's oracle is not applied."""
    ctx = build_context(workdir, cfg)
    ctx.timings = timings
    sub = submit_jobs(ctx, cfg)
    pending = set(sub.per_client)
    stop = threading.Event()

    def loop(index: int) -> None:
        rng = random.Random(cfg.seed * 1000 + index)  # noqa: S311 - seeded simulation, not cryptography
        generation = 0
        while not stop.is_set():
            with ctx.lock:
                choices = sorted(pending)
            if not choices:
                return
            client = rng.choice(choices)
            outcome = process_one(ctx, client, f"t{index}.{generation}")
            if outcome == "crashed":
                generation += 1
            elif outcome in ("idle", "done", "dead") and not _outstanding(ctx, client):
                with ctx.lock:
                    pending.discard(client)
            if outcome in ("idle", "breaker-open"):
                time.sleep(0)

    workers = [threading.Thread(target=loop, args=(i,), daemon=True) for i in range(threads)]
    deadline = time.monotonic() + 120 + cfg.jobs * 0.2
    for t in workers:
        t.start()
    while any(t.is_alive() for t in workers) and time.monotonic() < deadline:
        ctx.clock.advance(cfg.tick_s)
        time.sleep(0.002)
    stop.set()
    for t in workers:
        t.join(timeout=30)
    with ctx.lock:
        finished = not pending
    return summarize(ctx, cfg, sub, sweeps=0, finished=finished, oracle=False)


# ---------------------------------------------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LoadReport:
    seed: int
    clients: int
    clients_with_jobs: int
    jobs_requested: int
    jobs_created: int
    duplicates_collapsed: int
    conflicts_refused: int
    submission_violations: int
    done: int
    dead: int
    lost_jobs: int
    dead_but_applied: int
    finished: bool
    sweeps: int
    sim_seconds: float
    faults: dict[str, int]
    outcomes: dict[str, int]
    adapter_deliveries: int
    audit_records: int
    audit_chains_verified: int
    chain_breaks: int
    audit_count_mismatches: int
    double_applies: int
    cross_client_results: int
    oracle_checked: bool
    oracle_mismatches: int
    digest: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _isolation_violations(ctx: Context, client: str, jobs: Sequence[Job]) -> int:
    bad = 0
    mine = tenant_token(client)
    for job in jobs:
        if job.payload.get("tenant_token") != mine:
            bad += 1
        if job.status == "done":
            result = job.result or {}
            if result.get("client") != client or result.get("token") != mine:
                bad += 1
            elif result.get("digest") != SyntheticAdapter._digest(job):  # noqa: SLF001 - the one definition of it
                bad += 1
    for record in ctx.audit.records(client):
        text = canonical_json(record).decode("utf-8")
        if record.get("client") != client or any(found != client for found in _TOKEN.findall(text)):
            bad += 1
    return bad


def summarize(
    ctx: Context, cfg: LoadConfig, sub: Submission, *, sweeps: int, finished: bool, oracle: bool
) -> LoadReport:
    clients = sorted(sub.per_client)
    done = dead = lost = dead_applied = cross = mismatches = 0
    effects = {(e.client, e.key): e for e in ctx.adapter.effects()}
    digest = hashlib.sha256()
    for client in clients:
        jobs = ctx.queue.list(client)
        cross += _isolation_violations(ctx, client, jobs)
        expected_audit = 0
        for job in jobs:
            done += job.status == "done"
            dead += job.status == "dead"
            lost += job.status in ("queued", "leased")
            effect = effects.get((client, job.idempotency_key))
            dead_applied += job.status == "dead" and effect is not None
            if effect is not None and effect.token != tenant_token(client):
                cross += 1
            if oracle:
                want = cfg.plan.expected(client, job.idempotency_key, cfg.max_attempts)
                got = (job.status, job.attempts, effect is not None)
                mismatches += got != (want.status, want.attempts, want.applied)
                expected_audit += want.audit_records
            digest.update(f"{client}|{job.idempotency_key}|{job.status}|{job.attempts}|{effect is not None}\n".encode())
        if oracle:
            mismatches += len(ctx.audit.records(client)) != expected_audit
    verified = broken = records = count_mismatch = 0
    for chain, res in ctx.audit.verify_all().items():
        verified += res.ok
        broken += not res.ok
        records += res.records
        head = ctx.audit.head(None if chain == "_msp" else chain)
        digest.update(f"{chain}|{head}\n".encode())
    for client in clients:
        count_mismatch += len(ctx.audit.records(client)) != ctx.audit_counts[client]
    stats = ctx.stats
    return LoadReport(
        seed=cfg.seed,
        clients=cfg.clients,
        clients_with_jobs=len(clients),
        jobs_requested=cfg.jobs,
        jobs_created=sub.created,
        duplicates_collapsed=sub.duplicates_collapsed,
        conflicts_refused=sub.conflicts_refused,
        submission_violations=sub.violations,
        done=done,
        dead=dead,
        lost_jobs=lost,
        dead_but_applied=dead_applied,
        finished=finished,
        sweeps=sweeps,
        sim_seconds=ctx.clock.seconds(),
        faults={kind: stats[f"fault.{kind}"] for kind in FAULT_KINDS},
        outcomes={
            "worker_crashes": stats["worker_crashes"],
            "lease_lost": stats["lease_lost"],
            "breaker_open": stats["breaker_open"],
        },
        adapter_deliveries=stats["adapter_calls"],
        audit_records=records,
        audit_chains_verified=verified,
        chain_breaks=broken,
        audit_count_mismatches=count_mismatch,
        double_applies=len(ctx.adapter.double_applied()),
        cross_client_results=cross,
        oracle_checked=oracle,
        oracle_mismatches=mismatches,
        digest=digest.hexdigest(),
    )


def report_json(report: LoadReport) -> str:
    return json.dumps(report.as_dict(), indent=2, sort_keys=True)
