"""B-84 load, failure and retry tests on the B-82 SQLite stores (specs/B-84.md).

Offline and synthetic: clients are `client-001`...; the "external system" is a SQLite file under tmp_path; every fault
is chosen by a hash of (seed, client, key, attempt), every clock is injected, nothing sleeps for time to pass. The one
real-process test kills a child with `os._exit`. The 10,000-call run is opt-in (B84_FULL_SCALE=1) because it takes
minutes on a disk that fsyncs every commit; the default run uses the same code at a smaller size.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/load
"""

from __future__ import annotations

import dataclasses
import os
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.audit.sqlite_store import GUARD_STATEMENTS, SqliteAuditStore
from core.gateway.budget import CircuitBreaker
from core.queue.sqlite_store import JobQueueError, LeaseLost, QueueConflict
from evals.load.harness import (
    START,
    Context,
    FaultPlan,
    LoadConfig,
    SimClock,
    SyntheticAdapter,
    build_context,
    process_one,
    run_simulation,
    run_threaded,
    tenant_token,
)

REPO = Path(__file__).resolve().parents[3]
FULL_SCALE = os.environ.get("B84_FULL_SCALE") == "1"


def one_client_ctx(tmp_path: Path, script: dict[tuple[str, str], list[str]], **overrides: object) -> Context:
    cfg = LoadConfig(clients=1, jobs=0, plan=FaultPlan(script=script), **overrides)  # type: ignore[arg-type]
    return build_context(tmp_path, cfg)


def submit(ctx: Context, client: str, key: str, value: int = 1) -> int:
    payload = {"lever": "ticket.note-add", "target": f"T-{key}", "value": value, "tenant_token": tenant_token(client)}
    return ctx.queue.enqueue(client, "lever.call", payload, key, max_attempts=ctx.max_attempts).job.id


def audit_statuses(ctx: Context, client: str) -> list[str]:
    return [str(r["result"]["status"]) for r in ctx.audit.records(client)]


# ---------------------------------------------------------------------------------------------------------------
# B84-2 load: many clients, many jobs, injected failures, worker crashes, and the chain still verifies
# ---------------------------------------------------------------------------------------------------------------

LOAD_PLAN = FaultPlan(
    seed=84, timeout=0.08, adapter_crash=0.05, worker_crash_before=0.03, worker_crash_after=0.04, poison_rate=0.02
)


def load_config(jobs: int, clients: int) -> LoadConfig:
    return LoadConfig(seed=84, clients=clients, jobs=jobs, workers=8, plan=LOAD_PLAN)


def check_report(report: dict[str, object], cfg: LoadConfig) -> None:
    assert report["finished"] is True
    assert report["chain_breaks"] == 0
    assert report["cross_client_results"] == 0
    assert report["double_applies"] == 0
    assert report["lost_jobs"] == 0
    assert report["audit_count_mismatches"] == 0
    assert report["oracle_mismatches"] == 0
    assert report["clients_with_jobs"] == cfg.clients
    assert report["jobs_created"] == report["done"] + report["dead"]  # type: ignore[operator]
    assert report["audit_chains_verified"] == report["clients_with_jobs"]


def test_b84_2_load_run_has_zero_chain_breaks_and_zero_cross_client_results(tmp_path: Path) -> None:
    cfg = load_config(600, 300)
    report = run_simulation(tmp_path, cfg).as_dict()
    check_report(report, cfg)
    faults = report["faults"]
    assert isinstance(faults, dict)
    # the faults really happened: a clean run proves nothing
    for kind in ("timeout", "adapter_crash", "worker_crash_before", "worker_crash_after"):
        assert faults[kind] > 0, kind
    assert report["dead"] > 0  # type: ignore[operator]
    assert report["duplicates_collapsed"] > 0  # type: ignore[operator]
    assert report["conflicts_refused"] > 0  # type: ignore[operator]


@pytest.mark.skipif(not FULL_SCALE, reason="opt-in: set B84_FULL_SCALE=1 (10,000 calls, minutes of fsync)")
def test_b84_2_full_scale_10000_calls_across_300_clients(tmp_path: Path) -> None:
    cfg = load_config(10_000, 300)
    report = run_simulation(tmp_path, cfg).as_dict()
    check_report(report, cfg)
    assert report["jobs_created"] >= 10_000  # type: ignore[operator]


def test_b84_2_same_seed_same_run_different_seed_different_run(tmp_path: Path) -> None:
    cfg = load_config(120, 20)
    first = run_simulation(tmp_path / "a", cfg)
    second = run_simulation(tmp_path / "b", cfg)
    other = run_simulation(
        tmp_path / "c", dataclasses.replace(cfg, seed=85, plan=dataclasses.replace(LOAD_PLAN, seed=85))
    )
    assert first.digest == second.digest  # outcomes AND every audit chain head, so ts and hashes match too
    assert first.as_dict() == second.as_dict()
    assert first.digest != other.digest


def test_b84_2_every_job_ends_as_the_oracle_says(tmp_path: Path) -> None:
    # the outcome of a job is a pure function of (seed, client, key): the system under test must agree with it
    cfg = load_config(200, 20)
    report = run_simulation(tmp_path, cfg)
    assert report.oracle_checked and report.oracle_mismatches == 0
    # and the oracle itself is not trivially "done": it predicts both endings
    expected = [
        cfg.plan.expected(f"client-{c:03d}", f"call-{n:05d}", cfg.max_attempts) for c in range(20) for n in range(10)
    ]
    assert {e.status for e in expected} == {"done", "dead"}


def test_b84_2_threads_contending_for_the_same_clients_lose_nothing(tmp_path: Path) -> None:
    cfg = LoadConfig(seed=7, clients=12, jobs=240, workers=8, lease_s=300, plan=LOAD_PLAN)
    report = run_threaded(tmp_path, cfg, threads=8).as_dict()
    # schedule-dependent counts (attempt numbers, dead letters) are not asserted, only the invariants
    assert report["finished"] is True
    assert report["chain_breaks"] == 0
    assert report["cross_client_results"] == 0
    assert report["double_applies"] == 0
    assert report["lost_jobs"] == 0
    assert report["audit_count_mismatches"] == 0
    assert report["jobs_created"] == report["done"] + report["dead"]  # type: ignore[operator]


def test_b84_2_verifier_has_teeth_after_a_load_run(tmp_path: Path) -> None:
    cfg = load_config(60, 6)
    assert run_simulation(tmp_path, cfg).chain_breaks == 0
    store = SqliteAuditStore(tmp_path / "audit.db", create=False)
    chain = "client-003"
    assert store.verify(chain).ok
    with sqlite3.connect(tmp_path / "audit.db") as con:  # someone with file access defeats the triggers...
        con.execute("DROP TRIGGER audit_records_no_update")
        con.execute(
            "UPDATE audit_records SET line = replace(line, 'load-worker', 'intruder-xx') WHERE chain = ?", (chain,)
        )
    broken = store.verify(chain)  # ...and the verifier still says so
    assert not broken.ok
    with sqlite3.connect(tmp_path / "audit.db") as con:  # put the triggers back: only the rewritten chain stays broken
        con.execute(GUARD_STATEMENTS[0])
    assert store.verify("client-004").ok
    rewritten = store.verify(chain)
    assert not rewritten.ok and rewritten.broken_seq is not None
    assert store.verify_all()[chain].ok is False


# ---------------------------------------------------------------------------------------------------------------
# B84-3 failure and retry behaviour, exact timelines on an injected clock
# ---------------------------------------------------------------------------------------------------------------

C1 = "client-001"
C2 = "client-002"


def test_b84_3_timeout_is_an_error_result_with_nothing_applied_then_a_retry_after_the_backoff(tmp_path: Path) -> None:
    ctx = one_client_ctx(tmp_path, {(C1, "k1"): ["timeout", "adapter_crash", "ok"]}, backoff_base_s=2.0)
    job_id = submit(ctx, C1, "k1")
    assert process_one(ctx, C1, "w1") == "retry"
    assert ctx.adapter.effect(C1, "k1") is None  # nothing applied by a timeout
    first = ctx.queue.get(C1, job_id)
    assert first is not None and first.status == "queued" and first.attempts == 1
    assert first.available_at == START + timedelta(seconds=2)
    ctx.clock.advance(1)
    assert process_one(ctx, C1, "w1") == "idle"  # still backing off
    ctx.clock.advance(1)
    assert process_one(ctx, C1, "w1") == "retry"  # an adapter exception is an error result too
    assert ctx.adapter.effect(C1, "k1") is None
    second = ctx.queue.get(C1, job_id)
    assert second is not None and second.available_at == START + timedelta(seconds=2 + 4)  # doubled
    ctx.clock.advance(4)
    assert process_one(ctx, C1, "w1") == "done"
    effect = ctx.adapter.effect(C1, "k1")
    assert effect is not None and effect.applications == 1
    assert audit_statuses(ctx, C1) == ["error", "error", "ok"]
    errors = [r["result"] for r in ctx.audit.records(C1)][:2]
    assert [e["error"] for e in errors] == ["AdapterTimeout", "RuntimeError"]  # class names only, never message text
    assert all(e["applied"] is False for e in errors)
    assert ctx.audit.verify(C1).ok


def test_b84_3_retries_stop_at_max_attempts_and_the_job_is_dead_lettered_not_dropped(tmp_path: Path) -> None:
    script = {(C1, "k1"): ["timeout"] * 9}
    ctx = one_client_ctx(tmp_path, script, backoff_base_s=1.0, max_attempts=4)
    job_id = submit(ctx, C1, "k1")
    waits = []
    for _ in range(3):
        assert process_one(ctx, C1, "w1") == "retry"
        job = ctx.queue.get(C1, job_id)
        assert job is not None
        waits.append((job.available_at - ctx.clock()).total_seconds())
        ctx.clock.advance(waits[-1])
    assert waits == [1.0, 2.0, 4.0]  # exponential, no jitter, exact
    assert process_one(ctx, C1, "w1") == "dead"
    assert process_one(ctx, C1, "w1") == "idle"  # a dead letter is never claimed again
    dead = ctx.queue.dead_letters(C1)
    assert [j.id for j in dead] == [job_id] and dead[0].attempts == 4
    assert audit_statuses(ctx, C1) == ["error", "error", "error", "error", "dead-letter"]
    assert ctx.adapter.effect(C1, "k1") is None
    # the adapter recovers; a person requeues the dead letter; the retry budget starts again and the work completes once
    ctx.plan = FaultPlan()
    ctx.queue.requeue_dead(C1, job_id)
    assert process_one(ctx, C1, "w1") == "done"
    effect = ctx.adapter.effect(C1, "k1")
    assert effect is not None and effect.applications == 1


def test_b84_3_worker_crash_before_the_call_applies_nothing_and_the_lease_expiry_retries_it(tmp_path: Path) -> None:
    ctx = one_client_ctx(tmp_path, {(C1, "k1"): ["worker_crash_before", "ok"]}, lease_s=10.0)
    job_id = submit(ctx, C1, "k1")
    assert process_one(ctx, C1, "w1") == "crashed"
    assert ctx.adapter.effect(C1, "k1") is None
    job = ctx.queue.get(C1, job_id)
    assert job is not None and job.status == "leased" and job.lease_owner == "w1"
    ctx.clock.advance(9)
    assert process_one(ctx, C1, "w2") == "idle"  # lease still live: nobody steals it early
    ctx.clock.advance(2)
    assert process_one(ctx, C1, "w2") == "done"
    final = ctx.queue.get(C1, job_id)
    assert final is not None and final.attempts == 2 and final.status == "done"
    effect = ctx.adapter.effect(C1, "k1")
    assert effect is not None and effect.applications == 1


def test_b84_3_worker_crash_after_the_effect_never_double_applies_on_retry(tmp_path: Path) -> None:
    ctx = one_client_ctx(tmp_path, {(C1, "k1"): ["worker_crash_after", "worker_crash_after", "ok"]}, lease_s=5.0)
    job_id = submit(ctx, C1, "k1")
    for worker in ("w1", "w2", "w3"):
        outcome = process_one(ctx, C1, worker)
        ctx.clock.advance(6)
    assert outcome == "done"
    effect = ctx.adapter.effect(C1, "k1")
    assert effect is not None
    assert effect.applications == 1 and effect.deliveries == 3  # reached the adapter three times, applied once
    job = ctx.queue.get(C1, job_id)
    assert job is not None and job.result is not None and job.result["replayed"] is True
    assert ctx.adapter.double_applied() == []


def test_b84_3_control_a_non_idempotent_adapter_does_double_apply(tmp_path: Path) -> None:
    # proves the detector above can fail: the same crash script against an adapter without the key check
    ctx = one_client_ctx(tmp_path, {(C1, "k1"): ["worker_crash_after", "ok"]}, lease_s=5.0, idempotent_adapter=False)
    submit(ctx, C1, "k1")
    process_one(ctx, C1, "w1")
    ctx.clock.advance(6)
    assert process_one(ctx, C1, "w2") == "done"
    assert ctx.adapter.double_applied() == [(C1, "k1", 2)]


def test_b84_3_a_worker_that_lost_its_lease_cannot_finish_the_job_and_the_effect_stays_single(tmp_path: Path) -> None:
    ctx = one_client_ctx(tmp_path, {}, lease_s=5.0)
    job_id = submit(ctx, C1, "k1")
    stale = ctx.queue.claim(C1, "zombie", lease_s=5)
    assert stale is not None
    ctx.adapter.call(stale, "ok")  # the zombie applies the effect, then stalls past its lease
    ctx.clock.advance(6)
    assert process_one(ctx, C1, "healthy") == "done"  # the healthy worker replays and finishes
    with pytest.raises(LeaseLost):
        ctx.queue.complete(stale, {"late": True})
    with pytest.raises(LeaseLost):
        ctx.queue.fail(stale, "late failure")
    job = ctx.queue.get(C1, job_id)
    assert job is not None and job.status == "done" and job.result is not None and "late" not in job.result
    effect = ctx.adapter.effect(C1, "k1")
    assert effect is not None and effect.applications == 1


def test_b84_3_a_job_that_keeps_killing_its_worker_is_dead_lettered_by_lease_expiry(tmp_path: Path) -> None:
    ctx = one_client_ctx(tmp_path, {(C1, "poison"): ["worker_crash_before"] * 9}, lease_s=5.0, max_attempts=3)
    job_id = submit(ctx, C1, "poison")
    healthy = submit(ctx, C1, "healthy")
    for _ in range(8):
        process_one(ctx, C1, "w1")
        ctx.clock.advance(6)
    poison = ctx.queue.get(C1, job_id)
    assert poison is not None and poison.status == "dead" and poison.attempts == 3
    assert poison.last_error is not None and "lease expired" in poison.last_error
    assert ctx.queue.get(C1, healthy).status == "done"  # type: ignore[union-attr]
    assert "dead-letter" in audit_statuses(ctx, C1)  # a lease-expiry death is audited too, once
    assert audit_statuses(ctx, C1).count("dead-letter") == 1


def test_b84_3_a_poison_job_does_not_block_the_clients_other_jobs(tmp_path: Path) -> None:
    ctx = one_client_ctx(tmp_path, {(C1, "bad"): ["adapter_crash"] * 9}, max_attempts=2, backoff_base_s=1.0)
    bad = submit(ctx, C1, "bad")
    good = [submit(ctx, C1, f"good-{i}") for i in range(5)]
    for _ in range(12):
        process_one(ctx, C1, "w1")
        ctx.clock.advance(2)
    assert ctx.queue.get(C1, bad).status == "dead"  # type: ignore[union-attr]
    assert [ctx.queue.get(C1, g).status for g in good] == ["done"] * 5  # type: ignore[union-attr]


def test_b84_3_submission_storm_makes_one_job_per_key_and_keys_are_per_client(tmp_path: Path) -> None:
    ctx = one_client_ctx(tmp_path, {})
    ids = {submit(ctx, C1, "same") for _ in range(50)}
    assert len(ids) == 1
    other = submit(ctx, C2, "same")  # the same key text under another client is another job
    assert other not in ids
    with pytest.raises(QueueConflict):
        submit(ctx, C1, "same", value=2)  # same key, different request: refused, never merged
    process_one(ctx, C1, "w1")
    process_one(ctx, C2, "w1")
    mine, theirs = ctx.adapter.effect(C1, "same"), ctx.adapter.effect(C2, "same")
    assert mine is not None and theirs is not None
    assert mine.token == tenant_token(C1) and theirs.token == tenant_token(C2)
    assert mine.applications == theirs.applications == 1
    assert ctx.queue.counts(C1) == {"queued": 0, "leased": 0, "done": 1, "dead": 0}


def test_b84_3_a_worker_only_ever_sees_its_own_clients_jobs(tmp_path: Path) -> None:
    ctx = one_client_ctx(tmp_path, {})
    submit(ctx, C2, "only-theirs")
    assert process_one(ctx, C1, "w1") == "idle"
    with pytest.raises(JobQueueError):
        process_one(ctx, "../etc", "w1")
    assert ctx.adapter.effect(C2, "only-theirs") is None


# ---------------------------------------------------------------------------------------------------------------
# B-80 breaker + B-82 queue: an outage must not burn the retry budget
# ---------------------------------------------------------------------------------------------------------------


def outage_config(use_breaker: bool) -> LoadConfig:
    return LoadConfig(
        seed=9,
        clients=20,
        jobs=100,
        workers=4,
        max_attempts=4,
        plan=FaultPlan(seed=9, outage=(0.0, 30.0)),
        breaker_threshold=3 if use_breaker else None,
        breaker_open_s=10.0,
    )


def test_b84_3_breaker_stops_calls_during_an_outage_and_no_job_is_dead_lettered(tmp_path: Path) -> None:
    with_breaker = run_simulation(tmp_path / "with", outage_config(True))
    without = run_simulation(tmp_path / "without", outage_config(False))
    assert with_breaker.finished and without.finished
    assert with_breaker.dead == 0 and with_breaker.done == with_breaker.jobs_created  # the outage cost no job
    assert without.dead > 0  # control: with no breaker the same outage dead-letters work
    assert with_breaker.adapter_deliveries < without.adapter_deliveries
    assert with_breaker.chain_breaks == without.chain_breaks == 0
    assert with_breaker.double_applies == 0


def test_b84_3_breaker_probe_slot_is_given_back_when_there_is_nothing_to_claim(tmp_path: Path) -> None:
    clock = SimClock()
    ctx = one_client_ctx(tmp_path, {})
    ctx.breaker = CircuitBreaker(failure_threshold=1, open_s=5.0, clock=clock.seconds)
    ctx.breaker.record_failure()
    clock.advance(6)
    assert ctx.breaker.state == "half-open"
    assert process_one(ctx, C1, "w1") == "idle"  # allowed through as the probe, found no job
    assert ctx.breaker.allow() is True  # so the probe slot is free for the next caller, not stuck


# ---------------------------------------------------------------------------------------------------------------
# A real process dies between the effect and the acknowledgement
# ---------------------------------------------------------------------------------------------------------------

CHILD = """
import os, sys
from pathlib import Path
from evals.load.harness import FaultPlan, LoadConfig, build_context, process_one
cfg = LoadConfig(clients=1, jobs=0, lease_s=1.0, plan=FaultPlan(script={("client-001", "k1"): ["worker_crash_after"]}),
                 real_clock=True)
ctx = build_context(Path(sys.argv[1]), cfg)
outcome = process_one(ctx, "client-001", "child")
if outcome == "crashed":
    os._exit(3)  # no cleanup, no acknowledgement, no audit record: what a killed worker leaves behind
sys.exit(0)
"""


def test_b84_3_real_process_death_after_the_effect_is_recovered_without_a_second_application(tmp_path: Path) -> None:
    cfg = LoadConfig(clients=1, jobs=0, lease_s=1.0, real_clock=True)
    ctx = build_context(tmp_path, cfg)
    job_id = submit(ctx, C1, "k1")
    child = subprocess.run(  # noqa: S603 - fixed argv, repo code only
        [sys.executable, "-c", CHILD, str(tmp_path)],
        cwd=REPO,
        env={**os.environ, "PYTHONPATH": str(REPO)},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert child.returncode == 3, child.stderr
    effect = ctx.adapter.effect(C1, "k1")
    assert effect is not None and effect.applications == 1  # the child did apply it before dying
    job = ctx.queue.get(C1, job_id)
    assert job is not None and job.status == "leased" and job.lease_owner == "child"
    assert ctx.audit.records(C1) == ()  # and left no audit record: the crash is visible only as a stuck lease
    ctx.clock.advance(5)  # type: ignore[attr-defined]  # RealClock.advance jumps past the child's 1 s lease
    assert process_one(ctx, C1, "parent") == "done"
    after = ctx.adapter.effect(C1, "k1")
    assert after is not None and after.applications == 1 and after.deliveries == 2
    assert ctx.audit.verify(C1).ok


# ---------------------------------------------------------------------------------------------------------------
# harness self-checks (so the load numbers mean what they say)
# ---------------------------------------------------------------------------------------------------------------


def test_b84_harness_fault_choice_is_pure_and_matches_the_requested_rates() -> None:
    plan = FaultPlan(seed=1, timeout=0.2, adapter_crash=0.1, worker_crash_before=0.1, worker_crash_after=0.1)
    seen = Counter(plan.fault("client-001", f"k{i}", 1, 0.0) for i in range(4000))
    again = Counter(plan.fault("client-001", f"k{i}", 1, 0.0) for i in range(4000))
    assert seen == again
    for kind, rate in (
        ("timeout", 0.2),
        ("adapter_crash", 0.1),
        ("worker_crash_before", 0.1),
        ("worker_crash_after", 0.1),
    ):
        assert abs(seen[kind] / 4000 - rate) < 0.03, kind
    assert plan.fault("client-001", "k1", 1, 0.0) == plan.fault("client-001", "k1", 1, 99.0)  # clock-independent
    with pytest.raises(ValueError):
        FaultPlan(timeout=0.7, adapter_crash=0.7)


def test_b84_harness_clock_is_injected_and_never_reads_the_wall_clock() -> None:
    clock = SimClock()
    assert clock() == datetime(2026, 10, 27, 12, 0, tzinfo=UTC) == START
    clock.advance(90)
    assert clock() == START + timedelta(seconds=90) and clock.seconds() == 90.0


def test_b84_harness_adapter_ledger_is_keyed_by_client_and_key(tmp_path: Path) -> None:
    adapter = SyntheticAdapter(tmp_path / "effects.db")
    assert adapter.effect(C1, "k") is None
    assert adapter.effects() == []
