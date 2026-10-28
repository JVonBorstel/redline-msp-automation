"""B-17 audit record v2 and verifier (STD-AU-2, DR-04, C-08).

Acceptance ids B17-1 to B17-3 are defined in specs/B-17.md. Offline: every log lives under tmp_path. v1 records
are built here the way the Phase 1 writer built them (eleven fields, no `v`), so mixed logs can be tested without
any committed fixture. Synthetic data only.
Run: uv run --frozen pytest tests/py/audit
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, get_args

import pytest

from core.audit import (
    ACTOR_KINDS,
    EVENTS,
    GENESIS_HASH,
    MODES,
    RECORD_FIELDS_V1,
    RECORD_FIELDS_V2,
    AuditLog,
    Mode,
    canonical_json,
    head_path_for,
    record_hash,
    verify_chain,
)
from core.audit.verify import main as verify_main
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, LeverRunner, MockTenant, Registry
from core.queue import open_queue
from core.queue.__main__ import demo_proposals

REPO = Path(__file__).resolve().parents[3]
CONTOSO = "contoso-dental"
V2_EXTRA = {"v", "event", "actor_kind", "lever_version", "request_id"}


# -- helpers --------------------------------------------------------------------------------


def _v1_record(seq: int, prev_hash: str, ticket: str) -> dict[str, Any]:
    record: dict[str, Any] = {
        "seq": seq,
        "ts": "2026-10-01T09:00:00.000Z",
        "agent": "tech-ana",
        "client": CONTOSO,
        "lever": "ticket.get",
        "params": {"ticket_id": ticket},
        "mode": "dry-run",
        "result": {"status": "ok", "reason": "read", "applied": False, "changes": []},
        "approver": None,
        "prev_hash": prev_hash,
    }
    record["hash"] = record_hash(record)
    return record


def _write_v1_log(path: Path, n: int) -> list[dict[str, Any]]:
    """A Phase 1 style log of n v1 records with its head pin."""
    records: list[dict[str, Any]] = []
    prev = GENESIS_HASH
    for i in range(n):
        rec = _v1_record(i + 1, prev, f"T-{1000 + i}")
        records.append(rec)
        prev = rec["hash"]
    path.write_bytes(b"".join(canonical_json(r) + b"\n" for r in records))
    head_path_for(path).write_text(json.dumps({"seq": n, "hash": prev}) + "\n", encoding="utf-8")
    return records


def _append_v2(log: AuditLog, n: int, start: int = 0) -> None:
    for i in range(n):
        log.append(
            agent="tech-ana",
            client=CONTOSO,
            lever="ticket.get",
            params={"ticket_id": f"T-{2000 + start + i}"},
            mode="dry-run",
            result={"status": "ok"},
        )


def _records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _rewrite(path: Path, records: list[dict[str, Any]], rehash: bool = True) -> None:
    """Write records back, recomputing every hash and the head pin: the strongest attacker without the pin store."""
    prev = GENESIS_HASH
    out = []
    for rec in records:
        rec = dict(rec)
        if rehash:
            rec["prev_hash"] = prev
            rec["hash"] = record_hash(rec)
        prev = rec["hash"]
        out.append(canonical_json(rec) + b"\n")
    path.write_bytes(b"".join(out))
    head_path_for(path).write_text(json.dumps({"seq": len(records), "hash": prev}) + "\n", encoding="utf-8")


@pytest.fixture
def v2_log(tmp_path: Path) -> AuditLog:
    log = AuditLog(tmp_path / "audit.jsonl")
    _append_v2(log, 5)
    return log


@pytest.fixture
def mixed_log(tmp_path: Path) -> AuditLog:
    """Seq 1-3 are v1 (written before B-17), seq 4-5 are v2 (appended after the upgrade)."""
    path = tmp_path / "audit.jsonl"
    _write_v1_log(path, 3)
    log = AuditLog(path)
    _append_v2(log, 2)
    return log


# -- B17-1 record v2 ------------------------------------------------------------------------


def test_b17_1_new_records_carry_the_v2_fields(v2_log: AuditLog) -> None:
    for rec in _records(v2_log.path):
        assert set(rec) == RECORD_FIELDS_V2 == RECORD_FIELDS_V1 | V2_EXTRA
        assert rec["v"] == 2 and type(rec["v"]) is int


def test_b17_1_defaults_when_the_caller_passes_nothing(v2_log: AuditLog) -> None:
    records = _records(v2_log.path)
    first = records[0]
    assert (first["event"], first["actor_kind"], first["lever_version"]) == ("lever.invoke", "unknown", None)
    ids = [r["request_id"] for r in records]
    assert all(i.startswith("req-") and len(i) == 40 and "[REDACTED]" not in i for i in ids)
    assert len(set(ids)) == len(ids), "each defaulted record gets its own correlation id"


def test_b17_1_caller_values_are_written(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    rec = log.append(
        agent="lead-lee",
        client=CONTOSO,
        lever="user.reset-mfa",
        params={"upn": "ana.lopez@contosodental.example"},
        mode="approve",
        result={"status": "ok"},
        approver="lead-lee",
        event="proposal.decide",
        actor_kind="human",
        lever_version=3,
        request_id="req-T3101-0001",
    )
    assert (rec["event"], rec["actor_kind"], rec["lever_version"], rec["request_id"]) == (
        "proposal.decide",
        "human",
        3,
        "req-T3101-0001",
    )
    assert _records(log.path)[0] == rec
    assert verify_chain(log.path, log.head_path).ok


@pytest.mark.parametrize(
    ("mode", "event"),
    [
        ("dry-run", "lever.invoke"),
        ("execute", "lever.invoke"),
        ("approve", "proposal.decide"),
        ("reject", "proposal.decide"),
        ("pause", "lever.pause"),
        ("resume", "lever.pause"),
    ],
)
def test_b17_1_default_event_follows_the_mode(tmp_path: Path, mode: Mode, event: str) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    rec = log.append(agent="lead-lee", client=CONTOSO, lever="user.disable", params={}, mode=mode, result={})
    assert rec["event"] == event


@pytest.mark.parametrize("bad_version", [0, -1, True, "2", 1.5])
def test_b17_1_odd_values_never_stop_a_record(tmp_path: Path, bad_version: Any) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    rec = log.append(
        agent="tech-ana",
        client=CONTOSO,
        lever="ticket.get",
        params={},
        mode="dry-run",
        result={"status": "denied"},
        event="made.up",  # type: ignore[arg-type]
        actor_kind="robot",  # type: ignore[arg-type]
        lever_version=bad_version,
        request_id="",
    )
    assert (rec["event"], rec["actor_kind"], rec["lever_version"]) == ("lever.invoke", "unknown", None)
    assert rec["request_id"].startswith("req-")
    assert verify_chain(log.path, log.head_path).ok


def test_b17_1_request_id_is_capped_and_redacted(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    secretish = "Bearer " + "ab12" * 10  # built at runtime: a secret-shaped value must not reach the record
    rec = log.append(
        agent="tech-ana", client=CONTOSO, lever="ticket.get", params={}, mode="dry-run", result={}, request_id=secretish
    )
    assert "ab12ab12" not in rec["request_id"] and "[REDACTED]" in rec["request_id"]
    long = log.append(
        agent="tech-ana", client=CONTOSO, lever="ticket.get", params={}, mode="dry-run", result={}, request_id="r" * 500
    )
    assert len(long["request_id"]) == 128


def test_b17_1_v1_records_are_never_rewritten(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    v1 = _write_v1_log(path, 3)
    before = path.read_bytes()
    log = AuditLog(path)
    _append_v2(log, 2)
    after = path.read_bytes()
    assert after.startswith(before), "the v1 prefix is byte-for-byte unchanged"
    records = _records(path)
    assert records[:3] == v1 and all("v" not in r for r in records[:3])
    assert records[3]["v"] == 2 and records[3]["seq"] == 4 and records[3]["prev_hash"] == v1[-1]["hash"]


# -- B17-2 verifier ---------------------------------------------------------------------------


def test_b17_2_accepts_a_v1_prefix_followed_by_v2_records(
    mixed_log: AuditLog, capsys: pytest.CaptureFixture[str]
) -> None:
    result = verify_chain(mixed_log.path, mixed_log.head_path)
    assert (result.ok, result.records, result.v1_records, result.v2_records) == (True, 5, 3, 2)
    assert verify_main([str(mixed_log.path)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("OK: 5 records, chain intact and matches the head pin") and "(3 v1, 2 v2)" in out


def test_b17_2_pure_v1_and_pure_v2_logs_still_verify(tmp_path: Path, v2_log: AuditLog) -> None:
    v1_path = tmp_path / "v1" / "audit.jsonl"
    v1_path.parent.mkdir()
    _write_v1_log(v1_path, 4)
    r1 = verify_chain(v1_path, head_path_for(v1_path))
    assert (r1.ok, r1.v1_records, r1.v2_records) == (True, 4, 0)
    r2 = verify_chain(v2_log.path, v2_log.head_path)
    assert (r2.ok, r2.v1_records, r2.v2_records) == (True, 0, 5)


def test_b17_2_rejects_a_v1_record_after_a_v2_one(tmp_path: Path) -> None:
    """A v1-shaped record placed after v2 records, with every hash and the head recomputed, is still broken."""
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    _append_v2(log, 3)
    records = _records(path)
    records.append(_v1_record(4, records[-1]["hash"], "T-6666"))
    _rewrite(path, records)
    result = verify_chain(path, head_path_for(path))
    assert (result.ok, result.broken_seq) == (False, 4)
    assert "v1 record after a v2 record" in result.reason


def test_b17_2_a_downgraded_v2_record_is_rejected(mixed_log: AuditLog) -> None:
    """Stripping the v2 fields from the newest v2 record (to hide its request id) breaks it, even rehashed."""
    records = _records(mixed_log.path)
    records[4] = {k: v for k, v in records[4].items() if k not in V2_EXTRA}
    _rewrite(mixed_log.path, records)
    result = verify_chain(mixed_log.path, mixed_log.head_path)
    assert (result.ok, result.broken_seq) == (False, 5)
    assert "v1 record after a v2 record" in result.reason


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda r: r.update(v=3), "unknown record version"),
        (lambda r: r.update(v=True), "unknown record version"),
        (lambda r: r.pop("request_id"), "record fields are missing or unexpected"),
        (lambda r: r.update(extra=1), "record fields are missing or unexpected"),
        (lambda r: r.update(mode="yolo"), "mode 'yolo' is not a known value"),
        (lambda r: r.update(event="made.up"), "event 'made.up' is not a known value"),
        (lambda r: r.update(actor_kind="robot"), "actor_kind 'robot' is not a known value"),
        (lambda r: r.update(lever_version=0), "lever_version must be a positive integer or null"),
        (lambda r: r.update(request_id=""), "request_id must be a non-empty string"),
    ],
)
def test_b17_2_malformed_v2_records_are_rejected_even_when_rehashed(
    v2_log: AuditLog, change: Callable[[dict[str, Any]], Any], reason: str
) -> None:
    records = _records(v2_log.path)
    change(records[2])
    _rewrite(v2_log.path, records)
    result = verify_chain(v2_log.path, v2_log.head_path)
    assert (result.ok, result.broken_seq) == (False, 3)
    assert reason in result.reason


# P1-2 tamper cases from tests/phase1/test_audit.py, run on both a pure v2 log and a mixed v1-then-v2 log.
# Seq 3 is v1 in the mixed log and v2 in the pure one; seq 4 and 5 are v2 in both.


@pytest.fixture(params=["v2", "mixed"])
def any_log(request: pytest.FixtureRequest, tmp_path: Path) -> AuditLog:
    log = AuditLog(tmp_path / "audit.jsonl")
    if request.param == "mixed":
        _write_v1_log(log.path, 3)
        _append_v2(log, 2)
    else:
        _append_v2(log, 5)
    return log


@pytest.mark.parametrize("seq", [3, 4])
def test_b17_2_p1_2_one_byte_changed_names_its_seq(any_log: AuditLog, seq: int) -> None:
    lines = any_log.path.read_bytes().splitlines(keepends=True)
    rec = json.loads(lines[seq - 1])
    old = rec["params"]["ticket_id"].encode()
    lines[seq - 1] = lines[seq - 1].replace(old, old[:-1] + (b"9" if old[-1:] != b"9" else b"8"))
    any_log.path.write_bytes(b"".join(lines))
    result = verify_chain(any_log.path, any_log.head_path)
    assert (result.ok, result.broken_seq) == (False, seq)
    assert verify_main([str(any_log.path)]) == 1


@pytest.mark.parametrize("seq", [3, 4])
def test_b17_2_p1_2_rehashed_edit_breaks_the_next_record(any_log: AuditLog, seq: int) -> None:
    records = _records(any_log.path)
    records[seq - 1]["params"]["ticket_id"] = "T-6666"
    body = {k: v for k, v in records[seq - 1].items() if k != "hash"}
    records[seq - 1]["hash"] = hashlib.sha256(canonical_json(body)).hexdigest()
    any_log.path.write_bytes(b"".join(canonical_json(r) + b"\n" for r in records))
    assert verify_chain(any_log.path).broken_seq == seq + 1


def test_b17_2_p1_2_deleting_the_last_record_is_caught_by_the_head_pin(any_log: AuditLog) -> None:
    lines = any_log.path.read_bytes().splitlines(keepends=True)
    any_log.path.write_bytes(b"".join(lines[:-1]))
    assert verify_chain(any_log.path).ok
    result = verify_chain(any_log.path, any_log.head_path)
    assert (result.ok, result.broken_seq) == (False, 5)
    assert verify_main([str(any_log.path)]) == 1


@pytest.mark.parametrize(
    ("mutate", "seq"),
    [
        (lambda lines: lines[:3] + lines[4:], 4),  # a middle record deleted (v2 in both logs)
        (lambda lines: lines[:2] + [lines[3], lines[2], lines[4]], 3),  # records swapped across the v1/v2 seam
        (lambda lines: [*lines[:3], b"not json\n", *lines[4:]], 4),  # record replaced by junk
    ],
)
def test_b17_2_p1_2_structural_tampering_is_detected(any_log: AuditLog, mutate: Any, seq: int) -> None:
    any_log.path.write_bytes(b"".join(mutate(any_log.path.read_bytes().splitlines(keepends=True))))
    assert verify_chain(any_log.path, any_log.head_path).broken_seq == seq


def test_b17_2_p1_2_missing_head_file_fails_when_a_head_is_required(any_log: AuditLog) -> None:
    any_log.head_path.unlink()
    assert not verify_chain(any_log.path, any_log.head_path).ok


def test_b17_2_verifier_cli_runs_as_a_module_on_a_mixed_log(mixed_log: AuditLog) -> None:
    ok = subprocess.run(  # noqa: S603 - fixed argv, no shell, local interpreter
        [sys.executable, "-m", "core.audit.verify", str(mixed_log.path)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ok.returncode == 0 and "(3 v1, 2 v2)" in ok.stdout


# -- B17-3 Mode literal (DR-04) ---------------------------------------------------------------


def test_b17_3_mode_literal_lists_the_values_actually_written() -> None:
    assert MODES == get_args(Mode) == ("dry-run", "execute", "approve", "reject", "pause", "resume", "invalid")
    assert set(EVENTS) >= {"lever.invoke", "proposal.add", "proposal.decide", "model.complete", "job.run"}
    assert set(ACTOR_KINDS) == {"agent", "human", "unknown"}


def test_b17_3_append_is_typed_with_mode() -> None:
    import inspect

    from core.audit import chain

    hints = inspect.get_annotations(chain.AuditLog.append, eval_str=True)
    assert hints["mode"] is Mode


def test_b17_3_every_mode_the_code_writes_is_in_the_literal(tmp_path: Path) -> None:
    """Drive the runner, the pause switch and the queue on a private state folder; every record's mode is in Mode."""
    queue = open_queue(tmp_path)
    runner = queue.runner
    runner.invoke("ticket.get", {"ticket_id": "T-1001"}, "tech-ana", CONTOSO)
    runner.invoke("ticket.get", {"ticket_id": "T-1001"}, "tech-ana", CONTOSO, mode="execute")
    runner.pause("user.disable", "lead-lee", "B17 test pause", CONTOSO)
    runner.resume("user.disable", "lead-lee", "B17 test resume", CONTOSO)
    proposals = list(demo_proposals())
    for p in proposals:
        queue.add(p)
    queue.decide(proposals[0].id, "lead-lee", approve=False)
    chain = tmp_path / "audit" / f"{CONTOSO}.jsonl"  # B-42: one chain per client
    records = _records(chain)
    written = {r["mode"] for r in records}
    assert written <= set(MODES)
    assert {"dry-run", "pause", "resume", "reject"} <= written
    assert all(r["v"] == 2 for r in records)
    assert verify_chain(chain, chain.with_name(chain.name + ".head")).ok


def test_b17_3_an_unknown_mode_is_recorded_as_invalid_with_the_raw_value(tmp_path: Path) -> None:
    tenant = tmp_path / "tenant"
    shutil.copytree(DEFAULT_TENANT_DIR, tenant)
    audit = AuditLog(tmp_path / "audit.jsonl")
    runner = LeverRunner(Registry.load(), IdentityStore.load(), MockTenant(tenant), audit)
    result = runner.invoke("ticket.get", {"ticket_id": "T-1001"}, "tech-ana", CONTOSO, mode="yolo")
    assert result.status == "denied" and "mode must be one of" in result.reason
    rec = _records(audit.path)[-1]
    assert (rec["mode"], rec["result"]["requested_mode"], rec["event"]) == ("invalid", "yolo", "lever.invoke")
    assert verify_chain(audit.path, audit.head_path).ok
