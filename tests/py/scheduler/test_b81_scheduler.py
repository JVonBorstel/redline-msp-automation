"""B-81 scheduler with per-client fan-out and job keys. Acceptance ids B81-1 to B81-3 are defined in specs/B-81.md.

Offline and deterministic: the clock is injected, nothing sleeps, no thread runs, the job store and the proposal sink
are in-memory, and audit chains go under tmp_path. Committed fixtures and config are never modified.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/scheduler
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from core.audit.chain import verify_chain
from core.audit.router import AuditRouter
from core.levers.registry import Registry
from core.scheduler import (
    InMemoryJobStore,
    InMemoryProposalSink,
    JobConfig,
    JobStore,
    ProposedAction,
    RouterAudit,
    Scheduler,
    SchedulerConfig,
    SchedulerError,
    Unit,
    UnitRecord,
    UnitResult,
    job_key,
    load_config,
    period_for,
)

REPO = Path(__file__).resolve().parents[3]
NOON = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
CLIENTS = ("contoso-dental", "fabrikam-capital", "litware-legal")
KEY_CONTOSO = "baseline/contoso-dental/2026-10-27"
DISABLE = {"upn": "a@contoso.example", "reason": "stale"}


def _job(**over: Any) -> JobConfig:
    base: dict[str, Any] = {"name": "baseline", "workflow": "wf", "every": "daily"}
    base.update(over)
    return JobConfig.model_validate(base)


def _config(*jobs: JobConfig, global_cap: int = 1000, per_client_cap: int = 10) -> SchedulerConfig:
    return SchedulerConfig(jobs=jobs or (_job(),), global_cap=global_cap, per_client_cap=per_client_cap)


class Clock:
    def __init__(self, now: datetime = NOON) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _ok(unit: Unit) -> UnitResult:
    return UnitResult(report=f"checked {unit.client}")


def _make(
    config: SchedulerConfig,
    workflows: dict[str, Any] | None = None,
    clients: tuple[str, ...] = CLIENTS,
    **kw: Any,
) -> tuple[Scheduler, Clock, InMemoryJobStore, InMemoryProposalSink]:
    clock = Clock()
    store = kw.pop("store", None) or InMemoryJobStore()
    sink = kw.pop("sink", None) or InMemoryProposalSink()
    sched = Scheduler(
        config,
        workflows if workflows is not None else {"wf": _ok},
        clients,
        clock=clock,
        store=store,
        sink=sink,
        registry=kw.pop("registry", Registry.load()),
        **kw,
    )
    return sched, clock, store, sink


def _rec(store: InMemoryJobStore, key: str) -> UnitRecord:
    rec = store.get(key)
    assert rec is not None
    return rec


# ---- B81-1: config, fan-out, key shape ------------------------------------------------------------------------


def test_b81_1_key_is_job_client_period() -> None:
    assert job_key("baseline", "contoso-dental", "2026-10-27") == KEY_CONTOSO


@pytest.mark.parametrize(
    ("every", "expected"),
    [("daily", "2026-10-27"), ("weekly", "2026-W44"), ("monthly", "2026-10"), ("quarterly", "2026-Q4")],
)
def test_b81_1_period_comes_from_the_injected_time(every: Any, expected: str) -> None:
    assert period_for(every, NOON) == expected


def test_b81_1_period_refuses_a_naive_or_non_utc_time() -> None:
    with pytest.raises(SchedulerError):
        period_for("daily", datetime(2026, 10, 27, 12, 0))
    with pytest.raises(SchedulerError):
        period_for("daily", datetime(2026, 10, 27, 12, 0, tzinfo=timezone(timedelta(hours=2))))


def test_b81_1_weekly_period_uses_the_iso_year_at_the_year_boundary() -> None:
    assert period_for("weekly", datetime(2027, 1, 1, 9, 0, tzinfo=UTC)) == "2026-W53"


def test_b81_1_a_run_fans_out_one_unit_per_client() -> None:
    sched, _, store, _ = _make(_config())
    report = sched.tick()
    assert report.ran == [
        "baseline/contoso-dental/2026-10-27",
        "baseline/fabrikam-capital/2026-10-27",
        "baseline/litware-legal/2026-10-27",
    ]
    assert {r.status for r in store.records()} == {"ok"}


def test_b81_1_workflow_receives_its_own_client_and_key() -> None:
    seen: list[Unit] = []

    def wf(unit: Unit) -> UnitResult:
        seen.append(unit)
        return UnitResult()

    sched, _, _, _ = _make(_config(), {"wf": wf})
    sched.tick()
    assert [(u.client, u.period, u.job, u.key) for u in seen] == [
        (c, "2026-10-27", "baseline", f"baseline/{c}/2026-10-27") for c in CLIENTS
    ]


def test_b81_1_per_client_enable_list_and_disable_list() -> None:
    only = _job(clients=["contoso-dental", "litware-legal"], disabled_clients=["litware-legal"])
    sched, _, _, _ = _make(_config(only))
    assert sched.tick().ran == [KEY_CONTOSO]


def test_b81_1_an_enabled_client_that_is_not_known_is_reported_not_run() -> None:
    sched, _, _, _ = _make(_config(_job(clients=["contoso-dental", "ghost-co"])))
    report = sched.tick()
    assert report.ran == [KEY_CONTOSO]
    assert report.unknown_clients == ["ghost-co"]


def test_b81_1_an_invalid_client_id_never_becomes_a_key() -> None:
    sched, _, _, _ = _make(_config(), clients=("contoso-dental", "bad/id", "../x", "UPPER"))
    report = sched.tick()
    assert report.ran == [KEY_CONTOSO]
    assert report.invalid_clients == ["../x", "UPPER", "bad/id"]


def test_b81_1_job_before_its_hour_is_not_due() -> None:
    sched, clock, _, _ = _make(_config(_job(not_before_hour=14)))
    first = sched.tick()
    assert first.ran == [] and first.not_due == ["baseline"]
    clock.now = datetime(2026, 10, 27, 14, 0, tzinfo=UTC)
    assert len(sched.tick().ran) == 3


def test_b81_1_next_period_runs_again_and_the_same_period_does_not() -> None:
    sched, clock, _, _ = _make(_config())
    assert len(sched.tick().ran) == 3
    clock.now = datetime(2026, 10, 27, 23, 59, tzinfo=UTC)
    assert sched.tick().ran == []
    clock.now = datetime(2026, 10, 28, 0, 1, tzinfo=UTC)
    assert len(sched.tick().ran) == 3


def test_b81_1_config_loads_from_json_and_the_committed_example_is_valid(tmp_path: Path) -> None:
    path = tmp_path / "jobs.json"
    body = {
        "version": 1,
        "global_cap": 5,
        "per_client_cap": 2,
        "jobs": [{"name": "a", "workflow": "wf", "every": "weekly"}],
    }
    path.write_text(json.dumps(body), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.global_cap == 5 and cfg.jobs[0].every == "weekly"
    committed = load_config(REPO / "core" / "scheduler" / "jobs.example.json")
    assert committed.jobs


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "has/slash", "workflow": "wf", "every": "daily"},
        {"name": "1starts-with-digit", "workflow": "wf", "every": "daily"},
        {"name": "a", "workflow": "wf", "every": "hourly"},
        {"name": "a", "workflow": "wf", "every": "daily", "not_before_hour": 24},
        {"name": "a", "workflow": "wf", "every": "daily", "job_cap": 0},
        {"name": "a", "workflow": "wf", "every": "daily", "surprise": 1},
        {"name": "a", "workflow": "wf", "every": "daily", "clients": ["Bad Client"]},
    ],
)
def test_b81_1_bad_job_config_is_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        JobConfig.model_validate(bad)


def test_b81_1_duplicate_job_names_bad_caps_and_unreadable_files_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _config(_job(), _job())
    with pytest.raises(ValueError):
        _config(global_cap=0)
    path = tmp_path / "jobs.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SchedulerError):
        load_config(path)
    with pytest.raises(SchedulerError):
        load_config(tmp_path / "missing.json")


def test_b81_1_a_job_naming_an_unregistered_workflow_is_refused_at_construction() -> None:
    with pytest.raises(SchedulerError):
        _make(_config(_job(workflow="nope")))


# ---- B81-2: idempotency, caps, isolation ----------------------------------------------------------------------


def test_b81_2_a_repeated_key_is_skipped_and_the_workflow_does_not_run_twice() -> None:
    calls: list[str] = []

    def wf(unit: Unit) -> UnitResult:
        calls.append(unit.key)
        return UnitResult()

    sched, _, _, _ = _make(_config(), {"wf": wf})
    sched.tick()
    again = sched.tick()
    assert len(calls) == 3
    assert again.ran == [] and len(again.skipped) == 3


def test_b81_2_idempotency_survives_a_new_scheduler_over_the_same_store() -> None:
    calls: list[str] = []

    def wf(unit: Unit) -> UnitResult:
        calls.append(unit.key)
        return UnitResult()

    store = InMemoryJobStore()
    first, _, _, _ = _make(_config(), {"wf": wf}, store=store)
    first.tick()
    second, _, _, _ = _make(_config(), {"wf": wf}, store=store)
    assert second.tick().ran == []
    assert len(calls) == 3


def test_b81_2_a_failed_unit_is_not_retried_in_the_same_period() -> None:
    calls: list[str] = []

    def wf(unit: Unit) -> UnitResult:
        calls.append(unit.client)
        raise RuntimeError("boom")

    sched, _, store, _ = _make(_config(), {"wf": wf})
    sched.tick()
    sched.tick()
    assert len(calls) == 3
    assert {r.status for r in store.records()} == {"failed"}


def test_b81_2_a_failing_client_does_not_stop_the_others() -> None:
    def wf(unit: Unit) -> UnitResult:
        if unit.client == "fabrikam-capital":
            raise ValueError("tenant exploded")
        return UnitResult(report="fine")

    sched, _, store, _ = _make(_config(), {"wf": wf})
    report = sched.tick()
    assert report.ran == ["baseline/contoso-dental/2026-10-27", "baseline/litware-legal/2026-10-27"]
    assert report.failed == ["baseline/fabrikam-capital/2026-10-27"]
    bad = _rec(store, "baseline/fabrikam-capital/2026-10-27")
    assert bad.status == "failed" and bad.detail == "ValueError"


def test_b81_2_a_failure_detail_carries_the_error_type_not_its_text() -> None:
    def wf(unit: Unit) -> UnitResult:
        raise RuntimeError("password=hunter2 for alice@contoso.example")

    sched, _, store, _ = _make(_config(), {"wf": wf}, clients=("contoso-dental",))
    sched.tick()
    assert "hunter2" not in _rec(store, KEY_CONTOSO).model_dump_json()


def test_b81_2_a_failing_client_leaves_other_jobs_for_the_same_client_running() -> None:
    def bad(unit: Unit) -> UnitResult:
        raise RuntimeError("x")

    sched, _, store, _ = _make(
        _config(_job(name="one", workflow="bad"), _job(name="two", workflow="wf")), {"bad": bad, "wf": _ok}
    )
    sched.tick()
    assert _rec(store, "two/contoso-dental/2026-10-27").status == "ok"


def test_b81_2_interrupts_are_not_swallowed() -> None:
    def wf(unit: Unit) -> UnitResult:
        raise KeyboardInterrupt

    sched, _, _, _ = _make(_config(), {"wf": wf})
    with pytest.raises(KeyboardInterrupt):
        sched.tick()


def test_b81_2_300_clients_honour_the_global_cap_and_finish_over_ticks() -> None:
    clients = tuple(f"client-{n:03d}" for n in range(300))
    sched, _, store, _ = _make(_config(global_cap=70), clients=clients)
    sizes = []
    while True:
        report = sched.tick()
        if not report.ran:
            break
        sizes.append(len(report.ran))
        assert len(report.deferred) == 300 - len(store.records())
    assert sizes == [70, 70, 70, 70, 20]
    assert len(store.records()) == 300
    assert len({r.key for r in store.records()}) == 300


def test_b81_2_300_clients_per_client_cap_limits_jobs_per_tick() -> None:
    clients = tuple(f"client-{n:03d}" for n in range(300))
    jobs = tuple(_job(name=f"job-{k}") for k in range(3))
    sched, _, store, _ = _make(_config(*jobs, per_client_cap=1), clients=clients)
    first = sched.tick()
    assert len(first.ran) == 300  # one job per client, never two for the same client
    per_client: dict[str, int] = {}
    for rec in store.records():
        per_client[rec.client] = per_client.get(rec.client, 0) + 1
    assert set(per_client.values()) == {1}
    assert len(first.deferred) == 600
    sched.tick()
    sched.tick()
    assert len(store.records()) == 900
    assert sched.tick().ran == []


def test_b81_2_global_and_client_caps_hold_together_with_300_clients() -> None:
    clients = tuple(f"client-{n:03d}" for n in range(300))
    jobs = tuple(_job(name=f"job-{k}") for k in range(2))
    sched, _, store, _ = _make(_config(*jobs, global_cap=100, per_client_cap=1), clients=clients)
    sizes: list[int] = []
    for _ in range(20):
        report = sched.tick()
        if not report.ran:
            break
        sizes.append(len(report.ran))
        who = [k.split("/")[1] for k in report.ran]
        assert len(who) == len(set(who))
    assert max(sizes) <= 100
    assert len(store.records()) == 600


def test_b81_2_a_job_cap_limits_that_job_only() -> None:
    sched, _, _, _ = _make(_config(_job(job_cap=1), _job(name="other")))
    report = sched.tick()
    assert [k for k in report.ran if k.startswith("baseline/")] == [KEY_CONTOSO]
    assert len([k for k in report.ran if k.startswith("other/")]) == 3


def test_b81_2_deferred_units_are_not_claimed_so_the_next_tick_picks_them_up() -> None:
    sched, _, store, _ = _make(_config(global_cap=2))
    first = sched.tick()
    assert len(first.ran) == 2 and first.deferred == ["baseline/litware-legal/2026-10-27"]
    assert store.get("baseline/litware-legal/2026-10-27") is None
    assert sched.tick().ran == ["baseline/litware-legal/2026-10-27"]


def test_b81_2_a_duplicate_does_not_use_up_a_cap() -> None:
    sched, clock, _, _ = _make(_config(global_cap=3))
    sched.tick()
    clock.now = datetime(2026, 10, 28, 1, 0, tzinfo=UTC)
    assert len(sched.tick().ran) == 3


def test_b81_2_claim_is_atomic_in_the_store() -> None:
    store = InMemoryJobStore()
    unit = Unit(key="a/b/c", job="a", client="b", period="c", as_of=NOON)
    assert store.claim(unit) is True
    assert store.claim(unit) is False
    assert _rec(store, "a/b/c").status == "running"


def test_b81_2_a_store_that_loses_the_claim_race_makes_the_unit_a_skip() -> None:
    class Racing(InMemoryJobStore):
        def get(self, key: str) -> UnitRecord | None:
            return None  # looks free to the pre-check ...

    store = Racing()
    sched, _, _, _ = _make(_config(), store=store)
    sched.tick()
    again = sched.tick()  # ... but claim() refuses the repeat
    assert again.ran == [] and len(again.skipped) == 3


# ---- B81-3: reports and proposals, never direct writes ---------------------------------------------------------


def _proposing(lever: str, params: dict[str, Any] | None = None) -> Any:
    def wf(unit: Unit) -> UnitResult:
        action = ProposedAction(lever=lever, params=DISABLE if params is None else params, reason="stale")
        return UnitResult(report="found one", proposals=(action,))

    return wf


def test_b81_3_a_registered_lever_becomes_a_proposal_for_that_client() -> None:
    sched, _, store, sink = _make(_config(), {"wf": _proposing("user.disable")})
    sched.tick()
    assert sorted(p.client for p in sink.proposals) == sorted(CLIENTS)
    assert {p.lever for p in sink.proposals} == {"user.disable"}
    assert all(p.id.startswith("P-") for p in sink.proposals)
    assert len(_rec(store, KEY_CONTOSO).proposal_ids) == 1


def test_b81_3_an_unregistered_lever_is_refused_and_the_unit_fails_with_nothing_queued() -> None:
    sched, _, store, sink = _make(_config(), {"wf": _proposing("shell.run", {"cmd": "format c:"})})
    report = sched.tick()
    assert sink.proposals == []
    assert len(report.failed) == 3
    assert _rec(store, KEY_CONTOSO).detail == "lever-not-registered"


def test_b81_3_bad_params_are_refused() -> None:
    sched, _, store, sink = _make(_config(), {"wf": _proposing("user.disable", {"upn": "a@x.example", "extra": "1"})})
    sched.tick()
    assert sink.proposals == []
    assert _rec(store, KEY_CONTOSO).detail == "params-invalid"


def test_b81_3_a_lever_scoped_to_other_clients_is_refused() -> None:
    spec = Registry.load().get("kb.search")
    assert spec is not None and spec.client_scope != "any"
    outside = next(c for c in CLIENTS if c not in spec.client_scope)
    sched, _, store, sink = _make(_config(), {"wf": _proposing("kb.search", {"query": "vpn"})}, clients=(outside,))
    sched.tick()
    assert sink.proposals == []
    assert _rec(store, f"baseline/{outside}/2026-10-27").detail == "lever-out-of-scope"


def test_b81_3_one_bad_proposal_means_none_of_that_units_proposals_are_queued() -> None:
    def wf(unit: Unit) -> UnitResult:
        good = ProposedAction(lever="user.disable", params=DISABLE, reason="r")
        bad = ProposedAction(lever="nope.nope", params={}, reason="r")
        return UnitResult(proposals=(good, bad))

    sched, _, _, sink = _make(_config(), {"wf": wf}, clients=("contoso-dental",))
    sched.tick()
    assert sink.proposals == []


def test_b81_3_the_same_proposal_twice_is_one_proposal() -> None:
    sink = InMemoryProposalSink()
    action = ProposedAction(lever="user.disable", params=DISABLE, reason="r")
    assert sink.propose("contoso-dental", action, "k") == sink.propose("contoso-dental", action, "k")
    assert len(sink.proposals) == 1


def test_b81_3_a_workflow_that_returns_the_wrong_type_fails_its_unit() -> None:
    def wf(unit: Unit) -> Any:
        return "not a result"

    sched, _, store, _ = _make(_config(), {"wf": wf}, clients=("contoso-dental",))
    sched.tick()
    assert _rec(store, KEY_CONTOSO).status == "failed"


def test_b81_3_a_report_only_unit_queues_nothing() -> None:
    sched, _, store, sink = _make(_config())
    sched.tick()
    assert sink.proposals == []
    assert _rec(store, KEY_CONTOSO).report == "checked contoso-dental"


def test_b81_3_the_report_is_one_bounded_line() -> None:
    def wf(unit: Unit) -> UnitResult:
        return UnitResult(report="line one\nline two " + "x" * 1000)

    sched, _, store, _ = _make(_config(), {"wf": wf}, clients=("contoso-dental",))
    sched.tick()
    report = _rec(store, KEY_CONTOSO).report
    assert "\n" not in report and len(report) <= 200


def test_b81_3_the_scheduler_has_no_way_to_run_a_lever() -> None:
    sched, _, _, _ = _make(_config())
    assert not [n for n in dir(sched) if not n.startswith("_") and ("execute" in n or "invoke" in n)]
    for name in ("scheduler.py", "stores.py", "models.py", "__init__.py"):
        source = (REPO / "core" / "scheduler" / name).read_text(encoding="utf-8")
        assert "LeverRunner" not in source and ".invoke(" not in source and "core.levers.runner" not in source


def test_b81_3_an_unregistered_lever_does_not_stop_other_clients() -> None:
    def wf(unit: Unit) -> UnitResult:
        lever = "shell.run" if unit.client == "contoso-dental" else "user.disable"
        return UnitResult(proposals=(ProposedAction(lever=lever, params=DISABLE, reason="r"),))

    sched, _, _, sink = _make(_config(), {"wf": wf})
    report = sched.tick()
    assert report.failed == [KEY_CONTOSO]
    assert sorted(p.client for p in sink.proposals) == ["fabrikam-capital", "litware-legal"]


def test_b81_3_a_sink_failure_fails_only_that_unit() -> None:
    class Flaky(InMemoryProposalSink):
        def propose(self, client: str, action: ProposedAction, ref: str) -> str:
            if client == "fabrikam-capital":
                raise OSError("queue down")
            return super().propose(client, action, ref)

    sched, _, _, sink = _make(_config(), {"wf": _proposing("user.disable")}, sink=Flaky())
    report = sched.tick()
    assert report.failed == ["baseline/fabrikam-capital/2026-10-27"]
    assert len(sink.proposals) == 2


# ---- audit: one job.run record per unit in that client's own chain ---------------------------------------------


def test_b81_audit_each_unit_writes_one_job_run_record_in_its_own_chain(tmp_path: Path) -> None:
    sched, _, _, _ = _make(_config(), audit=RouterAudit(AuditRouter(tmp_path)))
    sched.tick()
    for client in CLIENTS:
        lines = (tmp_path / f"{client}.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["event"] == "job.run" and rec["client"] == client and rec["mode"] == "dry-run"
        assert rec["agent"] == "scheduler" and rec["params"] == {"job": "baseline", "period": "2026-10-27"}
        assert rec["result"]["status"] == "ok"
        assert all(other not in lines[0] for other in CLIENTS if other != client)
        assert verify_chain(tmp_path / f"{client}.jsonl").ok


def test_b81_audit_a_skipped_duplicate_writes_nothing(tmp_path: Path) -> None:
    sched, _, _, _ = _make(_config(), audit=RouterAudit(AuditRouter(tmp_path)))
    sched.tick()
    sched.tick()
    assert len((tmp_path / "contoso-dental.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_b81_audit_failure_and_refusal_are_recorded(tmp_path: Path) -> None:
    sched, _, _, _ = _make(
        _config(),
        {"wf": _proposing("shell.run", {})},
        clients=("contoso-dental",),
        audit=RouterAudit(AuditRouter(tmp_path)),
    )
    sched.tick()
    rec = json.loads((tmp_path / "contoso-dental.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["result"]["status"] == "failed" and rec["result"]["detail"] == "lever-not-registered"


def test_b81_audit_a_broken_audit_write_fails_that_unit_and_not_the_others() -> None:
    class Flaky:
        def record(self, unit: Unit, record: UnitRecord) -> None:
            if unit.client == "litware-legal":
                raise OSError("disk full")

    sched, _, store, _ = _make(_config(), audit=Flaky())
    report = sched.tick()
    assert report.failed == ["baseline/litware-legal/2026-10-27"]
    assert len(report.ran) == 2
    rec = _rec(store, "baseline/litware-legal/2026-10-27")
    assert rec.status == "failed" and rec.detail == "audit-failed"


def test_b81_clock_is_injected_and_nothing_sleeps(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    def boom(*_: Any) -> None:
        raise AssertionError("scheduler slept")

    monkeypatch.setattr(time, "sleep", boom)
    sched, _, _, _ = _make(_config())
    sched.tick()
    sched.tick(datetime(2026, 11, 1, 3, 0, tzinfo=UTC))


def test_b81_tick_accepts_an_explicit_time_instead_of_the_clock() -> None:
    sched, _, _, _ = _make(_config(), clients=("contoso-dental",))
    assert sched.tick(datetime(2030, 1, 2, 3, 0, tzinfo=UTC)).ran == ["baseline/contoso-dental/2030-01-02"]


def test_b81_same_inputs_give_the_same_report_every_time() -> None:
    one = _make(_config(global_cap=2))[0].tick()
    two = _make(_config(global_cap=2))[0].tick()
    assert one == two


def test_b81_in_memory_store_satisfies_the_protocol() -> None:
    store: JobStore = InMemoryJobStore()
    assert store.records() == []
