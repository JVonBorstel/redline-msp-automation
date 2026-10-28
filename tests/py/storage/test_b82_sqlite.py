"""B-82 SQLite job/approval queue and append-only audit store (specs/B-82.md).

Offline, synthetic data only; every database lives under tmp_path. Child processes (crash and writer tests) run the
repo's own code through the current interpreter. Run: uv run --frozen pytest tests/py/storage
"""

from __future__ import annotations

import dataclasses
import os
import sqlite3
import subprocess
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from core.audit import AuditLog, VerifyResult, canonical_json, record_hash, verify_chain
from core.audit import chain as chain_module
from core.audit.router import AuditRouter
from core.audit.sqlite_store import GUARD_STATEMENTS, SqliteAuditStore, SqliteAuditStoreError
from core.audit.sqlite_store import main as store_cli
from core.audit.verify import main as jsonl_verify_cli
from core.queue import Proposal, open_queue
from core.queue.sqlite_store import (
    AlreadyDecided,
    JobQueueError,
    LeaseLost,
    QueueConflict,
    SchemaTooNew,
    SelfApproval,
    SqliteApprovalStore,
    SqliteJobQueue,
)

REPO = Path(__file__).resolve().parents[3]
START = datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class OffsetClock:
    """The real clock plus an offset, so a test can jump forward past a lease a child process took."""

    def __init__(self) -> None:
        self.offset = timedelta(0)

    def __call__(self) -> datetime:
        return datetime.now(UTC) + self.offset

    def advance(self, seconds: float) -> None:
        self.offset += timedelta(seconds=seconds)


def child_env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(REPO)}


def run_child(code: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, repo code only
        [sys.executable, "-c", code, *args], cwd=REPO, env=child_env(), capture_output=True, text=True, timeout=120
    )


def spawn(code: str, *args: str, capture: bool = False) -> subprocess.Popen[str]:
    return subprocess.Popen(  # noqa: S603 - fixed argv, repo code only
        [sys.executable, "-c", code, *args],
        cwd=REPO,
        env=child_env(),
        stdout=subprocess.PIPE if capture else None,
        text=True,
    )


def run_threads(count: int, target: Callable[[int], None]) -> None:
    errors: list[BaseException] = []

    def wrapped(index: int) -> None:
        try:
            target(index)
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            errors.append(exc)

    threads = [threading.Thread(target=wrapped, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    if errors:
        raise errors[0]


# ---------------------------------------------------------------------------------------------------------------
# Job queue (B82-1)
# ---------------------------------------------------------------------------------------------------------------


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def jobs(tmp_path: Path, clock: FakeClock) -> SqliteJobQueue:
    return SqliteJobQueue(tmp_path / "b82.db", clock=clock)


def test_b82_1_enqueue_is_idempotent_on_client_and_key(jobs: SqliteJobQueue) -> None:
    first = jobs.enqueue("contoso-dental", "disk-check", {"host": "srv1"}, "key-1")
    again = jobs.enqueue("contoso-dental", "disk-check", {"host": "srv1"}, "key-1")
    assert first.created is True and again.created is False
    assert again.job.id == first.job.id
    assert len(jobs.list("contoso-dental")) == 1
    other = jobs.enqueue("fabrikam-capital", "disk-check", {"host": "srv1"}, "key-1")
    assert other.created is True and other.job.id != first.job.id


def test_b82_1_same_key_with_a_different_request_is_a_conflict(jobs: SqliteJobQueue) -> None:
    jobs.enqueue("contoso-dental", "disk-check", {"host": "srv1"}, "key-1")
    with pytest.raises(QueueConflict):
        jobs.enqueue("contoso-dental", "disk-check", {"host": "srv2"}, "key-1")
    with pytest.raises(QueueConflict):
        jobs.enqueue("contoso-dental", "other-kind", {"host": "srv1"}, "key-1")
    assert len(jobs.list("contoso-dental")) == 1


def test_b82_1_bad_input_is_refused(jobs: SqliteJobQueue) -> None:
    for client in ("", "Contoso", "../x", "_msp", "con", "a" * 80):
        with pytest.raises(JobQueueError):
            jobs.enqueue(client, "k", {}, "key")
    with pytest.raises(JobQueueError):
        jobs.enqueue("contoso-dental", "k", {}, "")
    with pytest.raises(JobQueueError):
        jobs.enqueue("contoso-dental", "k", {}, "key", max_attempts=0)
    with pytest.raises(JobQueueError):
        jobs.enqueue("contoso-dental", "k", {}, "key", delay_s=-1)
    with pytest.raises(JobQueueError):
        jobs.enqueue("contoso-dental", "k", {"bad": object()}, "key")
    with pytest.raises(JobQueueError):
        jobs.claim("contoso-dental", "", lease_s=30)
    with pytest.raises(JobQueueError):
        jobs.claim("contoso-dental", "w1", lease_s=0)


def test_b82_1_claim_is_oldest_first_and_honours_delay_and_kinds(jobs: SqliteJobQueue, clock: FakeClock) -> None:
    a = jobs.enqueue("contoso-dental", "scan", {"n": 1}, "a").job
    jobs.enqueue("contoso-dental", "report", {"n": 2}, "b")
    later = jobs.enqueue("contoso-dental", "scan", {"n": 3}, "c", delay_s=60).job
    got = jobs.claim("contoso-dental", "w1", lease_s=30, kinds=["report"])
    assert got is not None and got.kind == "report"
    jobs.complete(got, {})
    got_a = jobs.claim("contoso-dental", "w1", lease_s=30)
    assert got_a is not None and got_a.id == a.id and got_a.status == "leased"
    assert jobs.claim("contoso-dental", "w1", lease_s=30) is None  # the delayed one is not due
    jobs.complete(got_a, {})
    clock.advance(60)
    got_c = jobs.claim("contoso-dental", "w2", lease_s=30)
    assert got_c is not None and got_c.id == later.id


def test_b82_1_clients_are_isolated(jobs: SqliteJobQueue) -> None:
    a = jobs.enqueue("contoso-dental", "scan", {}, "k").job
    b = jobs.enqueue("fabrikam-capital", "scan", {}, "k").job
    claimed = jobs.claim("fabrikam-capital", "w1", lease_s=30)
    assert claimed is not None and claimed.id == b.id
    assert jobs.get("fabrikam-capital", a.id) is None
    assert [j.id for j in jobs.list("contoso-dental")] == [a.id]
    forged = dataclasses.replace(claimed, client="contoso-dental")
    with pytest.raises(LeaseLost):
        jobs.complete(forged, {"ok": True})
    still = jobs.get("contoso-dental", a.id)
    assert still is not None and still.status == "queued"
    assert jobs.claim("nobody-here", "w1", lease_s=30) is None


def test_b82_1_a_live_lease_blocks_others_and_expiry_hands_the_job_on(jobs: SqliteJobQueue, clock: FakeClock) -> None:
    jobs.enqueue("contoso-dental", "scan", {}, "k")
    first = jobs.claim("contoso-dental", "w1", lease_s=30)
    assert first is not None and first.attempts == 1
    clock.advance(29)
    assert jobs.claim("contoso-dental", "w2", lease_s=30) is None
    clock.advance(2)
    second = jobs.claim("contoso-dental", "w2", lease_s=30)
    assert second is not None and second.id == first.id and second.attempts == 2
    with pytest.raises(LeaseLost):
        jobs.complete(first, {"late": True})
    with pytest.raises(LeaseLost):
        jobs.heartbeat(first, lease_s=30)
    done = jobs.complete(second, {"ok": True})
    assert done.status == "done" and done.result == {"ok": True}


def test_b82_1_heartbeat_extends_the_lease_but_not_an_expired_one(jobs: SqliteJobQueue, clock: FakeClock) -> None:
    jobs.enqueue("contoso-dental", "scan", {}, "k")
    job = jobs.claim("contoso-dental", "w1", lease_s=30)
    assert job is not None
    clock.advance(20)
    job = jobs.heartbeat(job, lease_s=30)
    clock.advance(20)
    assert jobs.claim("contoso-dental", "w2", lease_s=30) is None
    clock.advance(11)
    with pytest.raises(LeaseLost):
        jobs.heartbeat(job, lease_s=30)
    with pytest.raises(LeaseLost):
        jobs.complete(job, {})


def test_b82_1_complete_twice_is_refused(jobs: SqliteJobQueue) -> None:
    jobs.enqueue("contoso-dental", "scan", {}, "k")
    job = jobs.claim("contoso-dental", "w1", lease_s=30)
    assert job is not None
    jobs.complete(job, {"n": 1})
    with pytest.raises(LeaseLost):
        jobs.complete(job, {"n": 2})
    with pytest.raises(LeaseLost):
        jobs.fail(job, "boom")
    again = jobs.enqueue("contoso-dental", "scan", {}, "k")
    assert again.created is False and again.job.status == "done"


def test_b82_1_failures_retry_with_backoff_then_dead_letter(jobs: SqliteJobQueue, clock: FakeClock) -> None:
    jobs.enqueue("contoso-dental", "scan", {}, "k", max_attempts=3)
    j1 = jobs.claim("contoso-dental", "w1", lease_s=30)
    assert j1 is not None
    after1 = jobs.fail(j1, "timeout")
    assert after1.status == "queued" and after1.last_error == "timeout"
    assert after1.available_at == START + timedelta(seconds=5)
    assert jobs.claim("contoso-dental", "w1", lease_s=30) is None
    clock.advance(5)
    j2 = jobs.claim("contoso-dental", "w1", lease_s=30)
    assert j2 is not None and j2.attempts == 2
    after2 = jobs.fail(j2, "timeout again")
    assert after2.available_at == clock.now + timedelta(seconds=10)
    clock.advance(10)
    j3 = jobs.claim("contoso-dental", "w1", lease_s=30)
    assert j3 is not None and j3.attempts == 3
    dead = jobs.fail(j3, "still failing")
    assert dead.status == "dead" and dead.last_error == "still failing"
    clock.advance(10_000)
    assert jobs.claim("contoso-dental", "w1", lease_s=30) is None
    assert [j.id for j in jobs.dead_letters("contoso-dental")] == [dead.id]
    assert jobs.dead_letters("fabrikam-capital") == ()


def test_b82_1_backoff_is_capped(tmp_path: Path, clock: FakeClock) -> None:
    q = SqliteJobQueue(tmp_path / "cap.db", clock=clock, backoff_base_s=100, backoff_cap_s=250)
    q.enqueue("contoso-dental", "scan", {}, "k", max_attempts=10)
    waits = []
    for _ in range(4):
        job = q.claim("contoso-dental", "w", lease_s=30)
        assert job is not None
        waits.append((q.fail(job, "x").available_at - clock.now).total_seconds())
        clock.advance(1000)
    assert waits == [100, 200, 250, 250]


def test_b82_1_a_permanent_failure_goes_straight_to_dead_letter(jobs: SqliteJobQueue) -> None:
    jobs.enqueue("contoso-dental", "scan", {}, "k")
    job = jobs.claim("contoso-dental", "w1", lease_s=30)
    assert job is not None
    assert jobs.fail(job, "bad payload", retry=False).status == "dead"


def test_b82_1_a_job_that_keeps_killing_its_worker_is_dead_lettered(jobs: SqliteJobQueue, clock: FakeClock) -> None:
    jobs.enqueue("contoso-dental", "scan", {}, "k", max_attempts=2)
    for expected in (1, 2):
        job = jobs.claim("contoso-dental", "w1", lease_s=30)
        assert job is not None and job.attempts == expected
        clock.advance(31)  # the worker "crashed": no complete, no fail
    assert jobs.claim("contoso-dental", "w1", lease_s=30) is None
    dead = jobs.dead_letters("contoso-dental")
    assert len(dead) == 1 and "lease expired" in (dead[0].last_error or "")


def test_b82_1_a_dead_letter_can_be_requeued_by_a_person(jobs: SqliteJobQueue) -> None:
    jobs.enqueue("contoso-dental", "scan", {}, "k", max_attempts=1)
    job = jobs.claim("contoso-dental", "w1", lease_s=30)
    assert job is not None
    dead = jobs.fail(job, "x")
    with pytest.raises(JobQueueError):
        jobs.requeue_dead("fabrikam-capital", dead.id)
    back = jobs.requeue_dead("contoso-dental", dead.id)
    assert back.status == "queued" and back.attempts == 0
    with pytest.raises(JobQueueError):
        jobs.requeue_dead("contoso-dental", dead.id)  # no longer dead


def test_b82_1_counts_by_status(jobs: SqliteJobQueue) -> None:
    jobs.enqueue("contoso-dental", "scan", {}, "a")
    jobs.enqueue("contoso-dental", "scan", {}, "b")
    jobs.claim("contoso-dental", "w1", lease_s=30)
    assert jobs.counts("contoso-dental") == {"queued": 1, "leased": 1, "done": 0, "dead": 0}


def test_b82_1_timestamps_come_from_the_injected_clock(jobs: SqliteJobQueue, clock: FakeClock) -> None:
    job = jobs.enqueue("contoso-dental", "scan", {}, "k").job
    assert job.created_at == START and job.updated_at == START
    clock.advance(7)
    claimed = jobs.claim("contoso-dental", "w1", lease_s=30)
    assert claimed is not None
    assert claimed.lease_until == START + timedelta(seconds=37) and claimed.updated_at == START + timedelta(seconds=7)


def test_b82_1_concurrent_threads_claim_each_job_exactly_once(tmp_path: Path) -> None:
    q = SqliteJobQueue(tmp_path / "t.db")
    for n in range(60):
        q.enqueue("contoso-dental", "scan", {"n": n}, f"k{n}")
    seen: list[list[int]] = [[] for _ in range(6)]

    def worker(index: int) -> None:
        mine = SqliteJobQueue(tmp_path / "t.db")
        while (job := mine.claim("contoso-dental", f"w{index}", lease_s=60)) is not None:
            seen[index].append(job.id)
            mine.complete(job, {})

    run_threads(6, worker)
    flat = [i for part in seen for i in part]
    assert len(flat) == 60 and len(set(flat)) == 60
    assert all(j.attempts == 1 and j.status == "done" for j in q.list("contoso-dental"))


_CLAIM_LOOP = """
import sys
from core.queue.sqlite_store import SqliteJobQueue
q = SqliteJobQueue(sys.argv[1])
while (job := q.claim("contoso-dental", "proc-" + sys.argv[2], lease_s=60)) is not None:
    q.complete(job, {})
    print(job.id)
"""


def test_b82_1_concurrent_processes_claim_each_job_exactly_once(tmp_path: Path) -> None:
    db = tmp_path / "p.db"
    q = SqliteJobQueue(db)
    for n in range(45):
        q.enqueue("contoso-dental", "scan", {"n": n}, f"k{n}")
    procs = [spawn(_CLAIM_LOOP, str(db), str(i), capture=True) for i in range(3)]
    ids: list[str] = []
    for p in procs:
        out, _ = p.communicate(timeout=120)
        assert p.returncode == 0
        ids += out.split()
    assert len(ids) == 45 and len(set(ids)) == 45
    assert q.counts("contoso-dental")["done"] == 45


def test_b82_1_concurrent_enqueues_of_one_key_make_one_job(tmp_path: Path) -> None:
    db = tmp_path / "e.db"
    SqliteJobQueue(db)
    created: list[bool] = []

    def worker(_: int) -> None:
        created.append(SqliteJobQueue(db).enqueue("contoso-dental", "scan", {}, "same").created)

    run_threads(8, worker)
    assert created.count(True) == 1 and len(created) == 8
    assert len(SqliteJobQueue(db).list("contoso-dental")) == 1


_CLAIM_AND_DIE = """
import os, sys
from core.queue.sqlite_store import SqliteJobQueue
q = SqliteJobQueue(sys.argv[1])
job = q.claim("contoso-dental", "doomed", lease_s=30)
assert job is not None
os._exit(7)  # no complete, no fail, no cleanup: the worker is gone
"""


def test_b82_1_crash_recovery_a_dead_workers_job_is_reclaimed_after_the_lease(tmp_path: Path) -> None:
    db = tmp_path / "c.db"
    clock = OffsetClock()
    q = SqliteJobQueue(db, clock=clock)
    q.enqueue("contoso-dental", "scan", {"n": 1}, "k")
    assert run_child(_CLAIM_AND_DIE, str(db)).returncode == 7
    assert q.claim("contoso-dental", "w2", lease_s=30) is None  # the lease is still live
    clock.advance(31)
    again = q.claim("contoso-dental", "w2", lease_s=30)
    assert again is not None and again.attempts == 2 and again.lease_owner == "w2"
    assert q.complete(again, {"ok": True}).status == "done"


_DIE_IN_TRANSACTION = """
import os, sqlite3, sys
con = sqlite3.connect(sys.argv[1], isolation_level=None)
con.execute("BEGIN IMMEDIATE")
con.execute(
    "INSERT INTO jobs(client, kind, payload, idem_key, request_hash, status, attempts, max_attempts, available_ms,"
    " created_ms, updated_ms) VALUES ('contoso-dental','scan','{}','half','x','queued',0,5,0,0,0)"
)
os._exit(7)  # killed before COMMIT
"""


def test_b82_1_crash_recovery_an_uncommitted_write_leaves_no_trace(tmp_path: Path) -> None:
    db = tmp_path / "half.db"
    q = SqliteJobQueue(db)
    q.enqueue("contoso-dental", "scan", {}, "before")
    assert run_child(_DIE_IN_TRANSACTION, str(db)).returncode == 7
    assert [j.idempotency_key for j in q.list("contoso-dental")] == ["before"]
    assert q.enqueue("contoso-dental", "scan", {}, "half").created is True  # the db is usable and the key is free
    assert q.integrity_check() == "ok"


# ---------------------------------------------------------------------------------------------------------------
# Approval store (B82-1: compare-and-set)
# ---------------------------------------------------------------------------------------------------------------


def make_proposal(user: str = "ana.diaz@contoso-dental.example", requested_by: str = "tech-ana") -> Proposal:
    return Proposal.new(
        source="baseline",
        ref="TB-STALE-01",
        lever="user.disable",
        client="contoso-dental",
        params={"user": user},
        requested_by=requested_by,
        reason="Stale account found by the baseline check",
    )


@pytest.fixture
def approvals(tmp_path: Path, clock: FakeClock) -> SqliteApprovalStore:
    return SqliteApprovalStore(tmp_path / "b82.db", clock=clock)


def test_b82_1_add_is_idempotent_and_get_is_per_client(approvals: SqliteApprovalStore) -> None:
    p = make_proposal()
    assert approvals.add(p) == p
    assert approvals.add(p) == p
    assert approvals.get("contoso-dental", p.id) == p
    assert approvals.get("fabrikam-capital", p.id) is None
    assert approvals.list("fabrikam-capital") == ()
    assert approvals.list("contoso-dental", status="pending") == (p,)


def test_b82_1_add_refuses_a_proposal_that_is_not_pending(approvals: SqliteApprovalStore) -> None:
    p = make_proposal()
    decided = p.model_copy(update={"status": "rejected", "decided_by": "lead-lee", "decided_at": p.created})
    with pytest.raises(JobQueueError):
        approvals.add(decided)


def test_b82_1_decide_sets_status_once(approvals: SqliteApprovalStore, clock: FakeClock) -> None:
    p = approvals.add(make_proposal())
    clock.advance(90)
    done = approvals.decide("contoso-dental", p.id, "lead-lee", approve=True)
    assert done.status == "approved" and done.decided_by == "lead-lee" and done.decided_at == "2026-10-27T12:01:30Z"
    with pytest.raises(AlreadyDecided) as info:
        approvals.decide("contoso-dental", p.id, "lead-kim", approve=False)
    assert info.value.status == "approved"
    stored = approvals.get("contoso-dental", p.id)
    assert stored is not None and stored.decided_by == "lead-lee"


def test_b82_1_decide_other_clients_proposal_is_not_found(approvals: SqliteApprovalStore) -> None:
    p = approvals.add(make_proposal())
    with pytest.raises(JobQueueError):
        approvals.decide("fabrikam-capital", p.id, "lead-lee", approve=True)
    stored = approvals.get("contoso-dental", p.id)
    assert stored is not None and stored.status == "pending"


def test_b82_1_a_requester_cannot_decide_their_own_proposal(approvals: SqliteApprovalStore) -> None:
    p = approvals.add(make_proposal(requested_by="tech-ana"))
    with pytest.raises(SelfApproval):
        approvals.decide("contoso-dental", p.id, "tech-ana", approve=True)
    stored = approvals.get("contoso-dental", p.id)
    assert stored is not None and stored.status == "pending"


def test_b82_1_two_leads_deciding_at_once_produce_one_decision(tmp_path: Path) -> None:
    db = tmp_path / "cas.db"
    p = SqliteApprovalStore(db).add(make_proposal())
    outcomes: list[str] = []
    guard = threading.Lock()

    def lead(index: int) -> None:
        store = SqliteApprovalStore(db)
        try:
            store.decide("contoso-dental", p.id, f"lead-{index}", approve=index % 2 == 0)
            result = "won"
        except AlreadyDecided:
            result = "lost"
        with guard:
            outcomes.append(result)

    run_threads(12, lead)
    assert sorted(outcomes) == ["lost"] * 11 + ["won"]
    stored = SqliteApprovalStore(db).get("contoso-dental", p.id)
    assert stored is not None and stored.status in ("approved", "rejected")


_DECIDE = """
import sys
from core.queue.sqlite_store import AlreadyDecided, SqliteApprovalStore
store = SqliteApprovalStore(sys.argv[1])
try:
    store.decide("contoso-dental", sys.argv[2], "lead-" + sys.argv[3], approve=True)
    print("won")
except AlreadyDecided:
    print("lost")
"""


def test_b82_1_two_processes_deciding_at_once_produce_one_decision(tmp_path: Path) -> None:
    db = tmp_path / "cas2.db"
    p = SqliteApprovalStore(db).add(make_proposal())
    procs = [spawn(_DECIDE, str(db), p.id, str(i), capture=True) for i in range(4)]
    results = [proc.communicate(timeout=120)[0].strip() for proc in procs]
    assert sorted(results) == ["lost", "lost", "lost", "won"]


def test_b82_1_execution_outcome_follows_approval_only(approvals: SqliteApprovalStore) -> None:
    p = approvals.add(make_proposal())
    with pytest.raises(AlreadyDecided):
        approvals.finish("contoso-dental", p.id, ok=True)  # still pending
    approvals.decide("contoso-dental", p.id, "lead-lee", approve=True)
    final = approvals.finish("contoso-dental", p.id, ok=True)
    assert final.status == "executed" and final.decided_by == "lead-lee"
    with pytest.raises(AlreadyDecided):
        approvals.finish("contoso-dental", p.id, ok=False)
    rejected = approvals.add(make_proposal(user="bo.chen@contoso-dental.example"))
    approvals.decide("contoso-dental", rejected.id, "lead-lee", approve=False)
    with pytest.raises(AlreadyDecided):
        approvals.finish("contoso-dental", rejected.id, ok=True)


def test_b82_1_triggers_refuse_an_illegal_status_move_even_by_raw_sql(tmp_path: Path) -> None:
    db = tmp_path / "raw.db"
    store = SqliteApprovalStore(db)
    p = store.add(make_proposal())
    store.decide("contoso-dental", p.id, "lead-lee", approve=False)
    con = sqlite3.connect(db)
    with pytest.raises(sqlite3.DatabaseError, match="status"):
        con.execute("UPDATE proposals SET status = 'pending' WHERE id = ?", (p.id,))
    with pytest.raises(sqlite3.DatabaseError, match="status"):
        con.execute("UPDATE proposals SET status = 'executed' WHERE id = ?", (p.id,))
    con.close()


def test_b82_1_crash_after_approval_leaves_it_approved_never_pending(tmp_path: Path) -> None:
    db = tmp_path / "crash-approve.db"
    store = SqliteApprovalStore(db)
    p = store.add(make_proposal())
    code = (
        "import os, sys\n"
        "from core.queue.sqlite_store import SqliteApprovalStore\n"
        "SqliteApprovalStore(sys.argv[1]).decide('contoso-dental', sys.argv[2], 'lead-lee', approve=True)\n"
        "os._exit(7)\n"
    )
    assert run_child(code, str(db), p.id).returncode == 7
    stored = store.get("contoso-dental", p.id)
    assert stored is not None and stored.status == "approved"  # a restart cannot run it twice from pending
    with pytest.raises(AlreadyDecided):
        store.decide("contoso-dental", p.id, "lead-kim", approve=True)


# ---------------------------------------------------------------------------------------------------------------
# Database basics: WAL, migrations, durability settings
# ---------------------------------------------------------------------------------------------------------------


def test_b82_wal_mode_is_on_and_stays_on(tmp_path: Path) -> None:
    db = tmp_path / "wal.db"
    SqliteJobQueue(db)
    SqliteAuditStore(db)
    con = sqlite3.connect(db)
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    con.close()
    assert SqliteJobQueue(db).journal_mode() == "wal"
    assert SqliteAuditStore(db).journal_mode() == "wal"


def test_b82_migrations_are_recorded_once_and_reopen_is_a_noop(tmp_path: Path) -> None:
    db = tmp_path / "mig.db"
    SqliteJobQueue(db).enqueue("contoso-dental", "scan", {}, "k")
    SqliteAuditStore(db)
    q = SqliteJobQueue(db)
    assert q.schema_version() == 1 and len(q.list("contoso-dental")) == 1
    con = sqlite3.connect(db)
    rows = con.execute("SELECT component, version FROM schema_migrations ORDER BY component, version").fetchall()
    con.close()
    assert rows == [("audit", 1), ("queue", 1)]


def test_b82_a_database_from_a_newer_version_is_refused(tmp_path: Path) -> None:
    db = tmp_path / "new.db"
    SqliteJobQueue(db)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO schema_migrations(component, version, applied_ms) VALUES ('queue', 99, 0)")
    con.commit()
    con.close()
    with pytest.raises(SchemaTooNew):
        SqliteJobQueue(db)


def test_b82_a_failed_migration_rolls_back_whole(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.queue import sqlite_store

    bad = [*sqlite_store.MIGRATIONS, (2, ("CREATE TABLE extra_ok(x)", "CREATE TABLE jobs(x)"))]  # second one fails
    db = tmp_path / "bad.db"
    SqliteJobQueue(db)
    monkeypatch.setattr(sqlite_store, "MIGRATIONS", bad)
    with pytest.raises(sqlite3.DatabaseError):
        SqliteJobQueue(db)
    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    versions = con.execute("SELECT version FROM schema_migrations WHERE component='queue'").fetchall()
    con.close()
    assert "extra_ok" not in tables and versions == [(1,)]


def test_b82_two_processes_opening_a_new_database_both_succeed(tmp_path: Path) -> None:
    db = tmp_path / "race.db"
    code = "import sys\nfrom core.queue.sqlite_store import SqliteJobQueue\nSqliteJobQueue(sys.argv[1])\n"
    procs = [spawn(code, str(db)) for _ in range(4)]
    assert [p.wait(timeout=120) for p in procs] == [0, 0, 0, 0]
    assert SqliteJobQueue(db).schema_version() == 1


def test_b82_3_the_jsonl_stores_remain_the_default(tmp_path: Path) -> None:
    queue = open_queue(tmp_path / "state")
    assert queue.path.name == "queue.jsonl"
    assert isinstance(queue.runner.audit, AuditRouter)
    import core.audit
    import core.queue

    for module in (core.audit, core.queue):
        assert not any("sqlite" in name.lower() for name in module.__all__)


# ---------------------------------------------------------------------------------------------------------------
# Audit store (B82-2)
# ---------------------------------------------------------------------------------------------------------------


@pytest.fixture
def audit_db(tmp_path: Path) -> Path:
    return tmp_path / "audit.db"


@pytest.fixture
def store(audit_db: Path, clock: FakeClock) -> SqliteAuditStore:
    return SqliteAuditStore(audit_db, clock=clock)


def put(s: SqliteAuditStore, client: str | None = "contoso-dental", n: int = 0, **kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "agent": "agent-triage",
        "client": client,
        "lever": "user.disable",
        "params": {"user": f"u{n}@contoso-dental.example"},
        "mode": "dry-run",
        "result": {"status": "ok", "n": n},
    }
    args.update(kw)
    return s.append(**args)


def fill(s: SqliteAuditStore, count: int, client: str | None = "contoso-dental") -> list[dict[str, Any]]:
    return [put(s, client, n) for n in range(count)]


def tamper(db: Path, statements: list[tuple[str, tuple[Any, ...]]], reinstall_guards: bool = False) -> None:
    """Edit the database the way an attacker with file access would: drop the guard triggers, then edit."""
    con = sqlite3.connect(db, isolation_level=None)
    for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
        if name.startswith("audit_"):
            con.execute(f'DROP TRIGGER "{name}"')
    for sql, params in statements:
        con.execute(sql, params)
    if reinstall_guards:
        for sql in GUARD_STATEMENTS:
            con.execute(sql)
    con.close()


def test_b82_2_records_are_byte_identical_to_the_jsonl_writer(
    store: SqliteAuditStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chain_module, "_utc_now", lambda: "2026-10-27T12:00:00.000Z")
    jsonl = AuditLog(tmp_path / "ref" / "contoso-dental.jsonl")
    cases: list[dict[str, Any]] = [
        {"mode": "dry-run", "result": {"status": "ok"}},
        {"mode": "execute", "result": {"status": "ok", "applied": True}, "approver": "lead-lee", "lever_version": 2},
        {"mode": "yolo", "result": {"status": "denied"}},  # becomes mode "invalid"
        {"mode": "approve", "result": {"status": "x"}, "actor_kind": "human", "request_id": "req-fixed-1"},
        {"mode": "reject", "params": {"password": "hunter2", "note": "Bearer abc.def.ghi"}},
        {"mode": "dry-run", "event": "model.complete", "actor_kind": "nonsense", "lever_version": 0},
    ]
    for n, extra in enumerate(cases):
        base: dict[str, Any] = {
            "agent": "agent-triage",
            "client": "contoso-dental",
            "lever": "user.disable",
            "params": {"n": n},
            "mode": "dry-run",
            "result": {},
            "request_id": f"req-n-{n}",
        }
        base.update(extra)
        expected = jsonl.append(**base)
        got = store.append(**base)
        assert canonical_json(got) == canonical_json(expected)
    assert [canonical_json(r) for r in store.records("contoso-dental")] == jsonl.path.read_bytes().splitlines()


def test_b82_2_an_exported_chain_verifies_with_the_jsonl_verifier(store: SqliteAuditStore, tmp_path: Path) -> None:
    fill(store, 12)
    log, head = store.export_chain("contoso-dental", tmp_path / "out")
    jsonl = verify_chain(log, head)
    assert jsonl.ok and jsonl.records == 12 and jsonl.v2_records == 12
    assert store.verify("contoso-dental") == jsonl
    assert jsonl_verify_cli([str(log)]) == 0  # the stock CLI, default head pin next to the log
    assert log.name == "contoso-dental.jsonl" and head.name == "contoso-dental.jsonl.head"


def test_b82_2_an_existing_jsonl_chain_imports_verifies_and_continues(store: SqliteAuditStore, tmp_path: Path) -> None:
    jsonl = AuditLog(tmp_path / "old" / "contoso-dental.jsonl")
    for n in range(5):
        jsonl.append(
            agent="a", client="contoso-dental", lever="l", params={"n": n}, mode="dry-run", result={"status": "ok"}
        )
    assert store.import_jsonl("contoso-dental", jsonl.path, jsonl.head_path) == 5
    imported = store.verify("contoso-dental")
    assert imported.ok and imported.records == 5
    assert [canonical_json(r) for r in store.records("contoso-dental")] == jsonl.path.read_bytes().splitlines()
    nxt = put(store, n=5)
    assert nxt["seq"] == 6 and nxt["prev_hash"] == store.records("contoso-dental")[4]["hash"]
    log, head = store.export_chain("contoso-dental", tmp_path / "back")
    assert verify_chain(log, head).ok
    with pytest.raises(SqliteAuditStoreError):
        store.import_jsonl("contoso-dental", jsonl.path, jsonl.head_path)  # the chain already has records


def test_b82_2_a_broken_jsonl_chain_is_refused_on_import(store: SqliteAuditStore, tmp_path: Path) -> None:
    jsonl = AuditLog(tmp_path / "old" / "contoso-dental.jsonl")
    for n in range(3):
        jsonl.append(agent="a", client="contoso-dental", lever="l", params={"n": n}, mode="dry-run", result={})
    lines = jsonl.path.read_bytes().splitlines()
    jsonl.path.write_bytes(b"\n".join([lines[0], lines[1].replace(b'"n":1', b'"n":9'), lines[2]]) + b"\n")
    with pytest.raises(SqliteAuditStoreError, match="seq 2"):
        store.import_jsonl("contoso-dental", jsonl.path, jsonl.head_path)
    assert store.records("contoso-dental") == ()
    short = tmp_path / "short.jsonl"
    short.write_bytes(b"\n".join(lines[:2]) + b"\n")  # truncated: the head pin still says 3
    with pytest.raises(SqliteAuditStoreError):
        store.import_jsonl("contoso-dental", short, jsonl.head_path)
    assert store.records("contoso-dental") == ()


def test_b82_2_update_and_delete_are_refused_by_triggers(audit_db: Path, store: SqliteAuditStore) -> None:
    fill(store, 3)
    con = sqlite3.connect(audit_db)
    for sql in (
        "UPDATE audit_records SET line = 'x' WHERE seq = 2",
        "UPDATE audit_records SET hash = 'x' WHERE seq = 2",
        "UPDATE audit_records SET chain = 'other' WHERE seq = 2",
        "DELETE FROM audit_records WHERE seq = 3",
        "DELETE FROM audit_records",
        "DELETE FROM audit_heads",
        "UPDATE audit_heads SET seq = 1",
        "UPDATE audit_heads SET hash = 'x'",
    ):
        with pytest.raises(sqlite3.DatabaseError, match="append-only|monotonic"):
            con.execute(sql)
    con.close()
    assert store.verify("contoso-dental").ok and len(store.records("contoso-dental")) == 3


def test_b82_2_a_forked_or_gapped_insert_is_refused_by_the_database(audit_db: Path, store: SqliteAuditStore) -> None:
    rec = put(store)
    con = sqlite3.connect(audit_db)
    ins = "INSERT INTO audit_records(chain, seq, hash, prev_hash, line) VALUES (?, ?, ?, ?, ?)"
    with pytest.raises(sqlite3.DatabaseError, match="chain"):
        con.execute(ins, ("contoso-dental", 3, "h" * 64, rec["hash"], "{}"))  # a gap
    with pytest.raises(sqlite3.DatabaseError):
        con.execute(ins, ("contoso-dental", 1, "h" * 64, "0" * 64, "{}"))  # a second seq 1
    with pytest.raises(sqlite3.DatabaseError, match="chain"):
        con.execute(ins, ("contoso-dental", 2, "h" * 64, "f" * 64, "{}"))  # wrong prev_hash
    con.close()
    assert store.verify("contoso-dental").ok


def test_b82_2_a_line_edited_with_triggers_dropped_is_found_at_its_seq(audit_db: Path, store: SqliteAuditStore) -> None:
    fill(store, 5)
    line = store.records("contoso-dental")[2]
    edited = canonical_json({**line, "result": {"status": "ok", "n": 999}}).decode()  # hash not recomputed
    tamper(audit_db, [("UPDATE audit_records SET line = ? WHERE chain = 'contoso-dental' AND seq = 3", (edited,))])
    result = store.verify("contoso-dental")
    assert not result.ok and result.broken_seq == 3 and "hash" in result.reason


def test_b82_2_a_rewritten_record_with_a_fresh_hash_breaks_the_next_link(
    audit_db: Path, store: SqliteAuditStore
) -> None:
    fill(store, 5)
    rec = dict(store.records("contoso-dental")[2])
    rec["result"] = {"status": "ok", "n": 999}
    rec["hash"] = record_hash(rec)
    sql = "UPDATE audit_records SET line = ?, hash = ? WHERE chain = 'contoso-dental' AND seq = 3"
    tamper(audit_db, [(sql, (canonical_json(rec).decode(), rec["hash"]))], reinstall_guards=True)
    result = store.verify("contoso-dental")
    assert not result.ok and result.broken_seq == 4 and "prev_hash" in result.reason


def test_b82_2_a_deleted_middle_record_is_found(audit_db: Path, store: SqliteAuditStore) -> None:
    fill(store, 5)
    tamper(audit_db, [("DELETE FROM audit_records WHERE chain = 'contoso-dental' AND seq = 3", ())])
    result = store.verify("contoso-dental")
    assert not result.ok and result.broken_seq == 3


def test_b82_2_truncation_is_found_by_the_stored_head(audit_db: Path, store: SqliteAuditStore) -> None:
    fill(store, 5)
    tamper(audit_db, [("DELETE FROM audit_records WHERE chain = 'contoso-dental' AND seq > 3", ())], True)
    assert store.schema_problems() == []
    result = store.verify("contoso-dental")
    assert not result.ok and "pins seq 5" in result.reason and result.broken_seq == 4


def test_b82_2_truncation_with_the_head_also_rewound_is_found_by_the_missing_triggers(
    audit_db: Path, store: SqliteAuditStore
) -> None:
    fill(store, 5)
    keep = store.records("contoso-dental")[2]
    tamper(
        audit_db,
        [
            ("DELETE FROM audit_records WHERE chain = 'contoso-dental' AND seq > 3", ()),
            ("UPDATE audit_heads SET seq = 3, hash = ? WHERE chain = 'contoso-dental'", (keep["hash"],)),
        ],
    )
    assert store.schema_problems()
    result = store.verify("contoso-dental")
    assert not result.ok and "trigger" in result.reason


def test_b82_2_a_pinned_head_held_elsewhere_catches_a_fully_rewound_database(
    audit_db: Path, store: SqliteAuditStore
) -> None:
    fill(store, 5)
    pin = store.head("contoso-dental")
    assert pin is not None and pin[0] == 5
    keep = store.records("contoso-dental")[2]
    tamper(
        audit_db,
        [
            ("DELETE FROM audit_records WHERE chain = 'contoso-dental' AND seq > 3", ()),
            ("UPDATE audit_heads SET seq = 3, hash = ? WHERE chain = 'contoso-dental'", (keep["hash"],)),
        ],
        reinstall_guards=True,  # the attacker puts the guard triggers back so nothing looks wrong inside the file
    )
    assert store.schema_problems() == []
    assert store.verify("contoso-dental").ok  # internally consistent: the file alone cannot tell
    pinned = store.verify("contoso-dental", expected_head=pin)
    assert not pinned.ok and "pins seq 5" in pinned.reason
    assert store.verify("contoso-dental", expected_head=(3, keep["hash"])).ok
    assert not store.verify("contoso-dental", expected_head=(3, "0" * 64)).ok


def test_b82_2_chains_are_isolated_per_client(store: SqliteAuditStore, tmp_path: Path) -> None:
    for n in range(3):
        put(store, "contoso-dental", n)
        put(store, "fabrikam-capital", n)
    put(store, None)
    put(store, "../../etc/passwd")  # hostile id: goes to the MSP chain, never a name of its own
    assert [r["seq"] for r in store.records("contoso-dental")] == [1, 2, 3]
    assert {r["client"] for r in store.records("fabrikam-capital")} == {"fabrikam-capital"}
    assert sorted(store.chains()) == ["_msp", "contoso-dental", "fabrikam-capital"]
    assert len(store.records(None)) == 2
    log, head = store.export_chain("contoso-dental", tmp_path / "x")
    text = log.read_text(encoding="utf-8") + head.read_text(encoding="utf-8")
    assert "fabrikam" not in text and "passwd" not in text
    assert sorted(p.name for p in (tmp_path / "x").iterdir()) == ["contoso-dental.jsonl", "contoso-dental.jsonl.head"]
    assert store.head("contoso-dental") != store.head("fabrikam-capital")
    with pytest.raises(SqliteAuditStoreError):
        store.export_chain("../x", tmp_path / "y")
    with pytest.raises(SqliteAuditStoreError):
        store.export_chain("no-such-client", tmp_path / "y")
    assert all(r.ok for r in store.verify_all().values())


def test_b82_2_a_record_moved_between_client_chains_is_found(audit_db: Path, store: SqliteAuditStore) -> None:
    put(store, "contoso-dental")
    put(store, "fabrikam-capital")
    other = canonical_json(store.records("fabrikam-capital")[0]).decode()
    tamper(audit_db, [("UPDATE audit_records SET line = ? WHERE chain = 'contoso-dental'", (other,))])
    assert not store.verify("contoso-dental").ok


def test_b82_2_secrets_are_redacted_before_they_are_stored(store: SqliteAuditStore) -> None:
    rec = put(store, params={"password": "hunter2", "note": "ok"})
    assert rec["params"]["password"] == "[REDACTED]"  # noqa: S105
    assert "hunter2" not in canonical_json(store.records("contoso-dental")).decode()


def test_b82_2_timestamps_come_from_the_injected_clock(store: SqliteAuditStore, clock: FakeClock) -> None:
    first = put(store)
    clock.advance(1.5)
    second = put(store)
    assert first["ts"] == "2026-10-27T12:00:00.000Z" and second["ts"] == "2026-10-27T12:00:01.500Z"


def test_b82_2_concurrent_threads_never_fork_the_chain(audit_db: Path) -> None:
    SqliteAuditStore(audit_db)

    def writer(index: int) -> None:
        s = SqliteAuditStore(audit_db)
        for n in range(15):
            put(s, "contoso-dental", n, agent=f"agent-{index}")

    run_threads(8, writer)
    s = SqliteAuditStore(audit_db)
    recs = s.records("contoso-dental")
    assert [r["seq"] for r in recs] == list(range(1, 121))
    assert s.verify("contoso-dental").ok


_APPEND_LOOP = """
import sys
from core.audit.sqlite_store import SqliteAuditStore
s = SqliteAuditStore(sys.argv[1])
for n in range(20):
    s.append(agent="proc-" + sys.argv[2], client=sys.argv[3], lever="user.disable", params={"n": n},
             mode="dry-run", result={"status": "ok"})
"""


def test_b82_2_concurrent_processes_never_fork_any_chain(audit_db: Path, tmp_path: Path) -> None:
    SqliteAuditStore(audit_db)
    clients = ["contoso-dental", "contoso-dental", "fabrikam-capital", "contoso-dental", "fabrikam-capital"]
    procs = [spawn(_APPEND_LOOP, str(audit_db), str(i), c) for i, c in enumerate(clients)]
    assert [p.wait(timeout=180) for p in procs] == [0] * 5
    s = SqliteAuditStore(audit_db)
    assert [r["seq"] for r in s.records("contoso-dental")] == list(range(1, 61))
    assert [r["seq"] for r in s.records("fabrikam-capital")] == list(range(1, 41))
    results = s.verify_all()
    assert all(r.ok for r in results.values()) and results["contoso-dental"].records == 60
    log, head = s.export_chain("contoso-dental", tmp_path / "e")
    assert verify_chain(log, head).ok


_APPEND_THEN_DIE = """
import os, sqlite3, sys
from core.audit.sqlite_store import SqliteAuditStore
s = SqliteAuditStore(sys.argv[1])
s.append(agent="a", client="contoso-dental", lever="l", params={}, mode="dry-run", result={})
if sys.argv[2] == "mid":
    con = sqlite3.connect(sys.argv[1], isolation_level=None)
    con.execute("BEGIN IMMEDIATE")
    rec = s.records("contoso-dental")[0]
    con.execute(
        "INSERT INTO audit_records(chain, seq, hash, prev_hash, line) VALUES ('contoso-dental', 2, ?, ?, ?)",
        ("a" * 64, rec["hash"], "{}"),
    )
os._exit(7)
"""


@pytest.mark.parametrize("when", ["after", "mid"])
def test_b82_2_crash_recovery_chain_is_intact_and_continues(audit_db: Path, when: str) -> None:
    assert run_child(_APPEND_THEN_DIE, str(audit_db), when).returncode == 7
    s = SqliteAuditStore(audit_db)
    assert s.verify("contoso-dental").ok and len(s.records("contoso-dental")) == 1
    nxt = put(s)
    assert nxt["seq"] == 2 and s.verify("contoso-dental").ok


def test_b82_2_failed_append_does_not_advance_the_chain(
    store: SqliteAuditStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    put(store)
    original = store._insert  # noqa: SLF001

    def boom(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        raise RuntimeError("disk went away after the insert, before the commit")

    monkeypatch.setattr(store, "_insert", boom)
    with pytest.raises(RuntimeError):
        put(store)
    monkeypatch.undo()
    assert len(store.records("contoso-dental")) == 1 and store.verify("contoso-dental").ok
    assert put(store)["seq"] == 2


def test_b82_2_the_queue_and_the_audit_store_can_share_one_database_file(tmp_path: Path) -> None:
    db = tmp_path / "shared.db"
    SqliteJobQueue(db).enqueue("contoso-dental", "scan", {}, "k")
    s = SqliteAuditStore(db)
    put(s)
    assert len(SqliteJobQueue(db).list("contoso-dental")) == 1 and s.verify("contoso-dental").ok


def test_b82_2_cli_verifies_and_reports_a_break(
    audit_db: Path, store: SqliteAuditStore, capsys: pytest.CaptureFixture[str]
) -> None:
    fill(store, 3)
    pin = store.head("contoso-dental")
    assert pin is not None
    assert store_cli(["verify", str(audit_db)]) == 0
    assert "OK" in capsys.readouterr().out
    assert store_cli(["verify", str(audit_db), "--client", "contoso-dental", "--pin", f"{pin[0]}:{pin[1]}"]) == 0
    assert store_cli(["verify", str(audit_db), "--client", "contoso-dental", "--pin", f"9:{pin[1]}"]) == 1
    tamper(audit_db, [("DELETE FROM audit_records WHERE seq = 3", ())])
    assert store_cli(["verify", str(audit_db)]) == 1
    assert "BROKEN" in capsys.readouterr().out
    assert store_cli(["verify", str(audit_db.parent / "missing.db")]) == 2


def test_b82_2_verify_returns_the_jsonl_verifiers_result_type(store: SqliteAuditStore) -> None:
    put(store)
    assert isinstance(store.verify("contoso-dental"), VerifyResult)
    empty = store.verify("fabrikam-capital")
    assert empty.ok and empty.records == 0
