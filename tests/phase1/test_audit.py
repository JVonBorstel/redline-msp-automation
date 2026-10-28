"""Hash-chained audit log, head pin, verifier CLI and redaction (acceptance P1-2 and P1-9)."""

import hashlib
import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from core.audit import GENESIS_HASH, REDACTED, AuditError, AuditLog, head_path_for, redact, verify_chain
from core.audit.verify import main as verify_main

REPO = Path(__file__).resolve().parents[2]


def _append(log: AuditLog, n: int, **overrides: Any) -> None:
    for i in range(n):
        fields: dict[str, Any] = {
            "agent": "tech-ana",
            "client": "contoso-dental",
            "lever": "ticket.get",
            "params": {"ticket_id": f"T-{1000 + i}"},
            "mode": "dry-run",
            "result": {"status": "ok"},
        }
        log.append(**{**fields, **overrides})


def _records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def log(tmp_path: Path) -> AuditLog:
    audit = AuditLog(tmp_path / "audit.jsonl")
    _append(audit, 5)
    return audit


def test_records_carry_every_field_and_chain(log: AuditLog) -> None:
    records = _records(log.path)
    assert [r["seq"] for r in records] == [1, 2, 3, 4, 5]
    assert records[0]["prev_hash"] == GENESIS_HASH
    for prev, cur in zip(records, records[1:], strict=False):
        assert cur["prev_hash"] == prev["hash"]
    first = records[0]
    assert set(first) == {
        *("seq", "ts", "agent", "client", "lever", "params", "mode", "result", "approver", "prev_hash", "hash"),
        *("v", "event", "actor_kind", "lever_version", "request_id"),  # audit v2 (B-17, STD-AU-2)
    }
    assert first["ts"].endswith("Z")


def test_hash_is_sha256_over_sorted_compact_json(log: AuditLog) -> None:
    record = _records(log.path)[0]
    body = {k: v for k, v in record.items() if k != "hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert record["hash"] == hashlib.sha256(canonical).hexdigest()


def test_head_pin_tracks_the_newest_record(log: AuditLog) -> None:
    head = json.loads(log.head_path.read_text(encoding="utf-8"))
    assert head == {"seq": 5, "hash": _records(log.path)[-1]["hash"]}
    assert log.head_path == head_path_for(log.path)


def test_p1_2_intact_log_exits_0(log: AuditLog, capsys: pytest.CaptureFixture[str]) -> None:
    assert verify_chain(log.path, log.head_path).ok
    assert verify_main([str(log.path), "--head", str(log.head_path)]) == 0
    assert "OK: 5 records" in capsys.readouterr().out


def test_p1_2_one_byte_changed_in_a_middle_record_names_its_seq(
    log: AuditLog, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = log.path.read_bytes().splitlines(keepends=True)
    lines[2] = lines[2].replace(b"T-1002", b"T-1009")  # seq 3: a one-byte edit
    log.path.write_bytes(b"".join(lines))

    result = verify_chain(log.path, log.head_path)
    assert (result.ok, result.broken_seq) == (False, 3)
    assert verify_main([str(log.path)]) == 1
    assert "BROKEN at seq 3" in capsys.readouterr().out


def test_p1_2_rehashed_edit_still_breaks_the_next_record(log: AuditLog) -> None:
    """An attacker who recomputes the edited record's own hash still breaks the chain at the next seq."""
    records = _records(log.path)
    records[2]["params"]["ticket_id"] = "T-6666"
    body = {k: v for k, v in records[2].items() if k != "hash"}
    records[2]["hash"] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    log.path.write_text("".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in records))
    assert verify_chain(log.path, log.head_path).broken_seq == 4


def test_p1_2_deleting_the_last_record_is_caught_by_the_head_pin(
    log: AuditLog, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = log.path.read_bytes().splitlines(keepends=True)
    log.path.write_bytes(b"".join(lines[:-1]))

    assert verify_chain(log.path).ok, "without the head pin a clean truncation looks intact"
    result = verify_chain(log.path, log.head_path)
    assert (result.ok, result.broken_seq) == (False, 5)
    assert "head pins seq 5" in result.reason
    assert verify_main([str(log.path)]) == 1  # the CLI finds <log>.head by default


@pytest.mark.parametrize(
    ("mutate", "seq"),
    [
        (lambda lines: lines[:1] + lines[2:], 2),  # middle record deleted
        (lambda lines: [lines[1], lines[0], *lines[2:]], 1),  # records swapped
        (lambda lines: [*lines[:2], b"not json\n", *lines[3:]], 3),  # record replaced by junk
    ],
)
def test_p1_2_structural_tampering_is_detected(log: AuditLog, mutate: Any, seq: int) -> None:
    log.path.write_bytes(b"".join(mutate(log.path.read_bytes().splitlines(keepends=True))))
    assert verify_chain(log.path, log.head_path).broken_seq == seq


def test_p1_2_missing_head_file_fails_when_a_head_is_required(log: AuditLog) -> None:
    log.head_path.unlink()
    assert not verify_chain(log.path, log.head_path).ok


def test_verifier_cli_runs_as_a_module(log: AuditLog) -> None:
    ok = subprocess.run(  # noqa: S603 - fixed argv, no shell, local interpreter
        [sys.executable, "-m", "core.audit.verify", str(log.path)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr
    missing = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "core.audit.verify", str(log.path) + ".nope"], cwd=REPO, capture_output=True, check=False
    )
    assert missing.returncode == 2


def test_append_refuses_to_extend_a_log_whose_head_pin_disagrees(log: AuditLog) -> None:
    lines = log.path.read_bytes().splitlines(keepends=True)
    log.path.write_bytes(b"".join(lines[:-1]))
    with pytest.raises(AuditError, match="head pin"):
        _append(log, 1)


def test_concurrent_appends_keep_one_unbroken_chain(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    threads = [threading.Thread(target=_append, args=(AuditLog(path), 20)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    result = verify_chain(path, head_path_for(path))
    assert (result.ok, result.records) == (True, 160)


# -- P1-9 secrets --------------------------------------------------------------------------

# Secret-shaped values are assembled at runtime so the repo's own secret scan (scripts/hooks/pre-commit)
# does not flag this file. All of them are synthetic.
FAKE_BEARER = "Bear" + "er " + "synthetic0" * 3
FAKE_SK = "sk" + "-" + "synthetic0" * 3
FAKE_JWT = ".".join(["eyJ" + "hbGciOiJIUzI1NiJ9", "eyJ" + "zdWIiOiJzeW50aGV0aWMifQ", "c2lnbmF0dXJlLW5vdC1yZWFs"])


@pytest.mark.parametrize("key", ["password", "newPassword", "client_secret", "access_token", "apiKey", "Credential"])
def test_p1_9_secret_named_params_are_redacted(tmp_path: Path, key: str) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.append(
        agent="tech-ana",
        client="contoso-dental",
        lever="user.disable",
        params={key: "hunter2-synthetic", "upn": "ana.lopez@contosodental.example"},
        mode="dry-run",
        result={"status": "ok"},
    )
    record = _records(audit.path)[0]
    assert record["params"][key] == REDACTED
    assert record["params"]["upn"] == "ana.lopez@contosodental.example"
    assert b"hunter2" not in audit.path.read_bytes()


@pytest.mark.parametrize(
    "value",
    [
        FAKE_BEARER,
        FAKE_SK,
        FAKE_JWT,
        "0123456789abcdef0123456789abcdef01234567",
        "c3ludGhldGljLW5vdC1hLXJlYWwtc2VjcmV0LTEyMzQ1Njc4",
    ],
)
def test_p1_9_secret_shaped_values_are_redacted(value: str) -> None:
    redacted = redact({"note": f"pasted by the user: {value} please fix"})
    assert value not in redacted["note"]
    assert REDACTED in redacted["note"]
    assert redacted["note"].startswith("pasted by the user:")


@pytest.mark.parametrize(
    "value",
    [
        "ana.lopez@contosodental.example",
        "3f1c9a52-7d4e-4b8a-9c21-0a5e6b7c8d91",  # directory object id (GUID)
        "/users/3f1c9a52-7d4e-4b8a-9c21-0a5e6b7c8d91/authentication/methods/b7d2e9f1-4a6c-4e8b-a1c3-5d7e9f0a2b4c",
        "T-1001",
        "The reception printer shows offline again after the power cut.",
        "internationalization-and-localization-guidelines",  # long word with no digits
    ],
)
def test_p1_9_ordinary_values_survive_redaction(value: str) -> None:
    assert redact({"note": value}) == {"note": value}


def test_redact_does_not_modify_its_input() -> None:
    original = {"token": "abc", "nested": [{"secret": "x"}]}
    redact(original)
    assert original == {"token": "abc", "nested": [{"secret": "x"}]}


def test_redact_turns_values_that_are_not_json_into_text() -> None:
    assert redact({"blob": b"raw", "n": 3, "ok": True, "none": None}) == {
        "blob": "b'raw'",
        "n": 3,
        "ok": True,
        "none": None,
    }
