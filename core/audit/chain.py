"""Append-only, hash-chained JSONL audit log with a head pin, and its verifier.

Each line is one record. `hash` is SHA-256 over the canonical JSON of the record without
`hash` (sorted keys, no spaces, UTF-8), and that record includes `prev_hash`, so changing any
byte of any earlier record breaks every hash after it. The head file pins the newest seq and
hash, so deleting records from the end is detected too.

Record versions (STD-AU-2, B-17). Version 1 records have exactly the eleven fields in
RECORD_FIELDS_V1 and no `v`. New records are version 2: the same fields plus `v: 2`, `event`,
`actor_kind`, `lever_version` and `request_id`. A log may start with v1 records and continue
with v2 records (old logs are never rewritten); the verifier rejects a v1 record after a v2 one,
so a v2 record cannot be quietly downgraded to the older, thinner shape.

One writer process per log: appends are serialised by a lock shared by every AuditLog object
on the same path inside this process. Cross-process writers are out of scope (Phase 1).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, get_args

from core.audit.redact import redact
from core.obs.context import current_request_id

GENESIS_HASH = "0" * 64
RECORD_VERSION = 2
RECORD_FIELDS_V1 = frozenset(
    {"seq", "ts", "agent", "client", "lever", "params", "mode", "result", "approver", "prev_hash", "hash"}
)
V2_FIELDS = frozenset({"v", "event", "actor_kind", "lever_version", "request_id"})
RECORD_FIELDS_V2 = RECORD_FIELDS_V1 | V2_FIELDS
RECORD_FIELDS = RECORD_FIELDS_V1  # historic name: the v1 field set

# Every `mode` value a caller writes (DR-04): the runner writes dry-run / execute, the queue
# approve / reject, the pause switch pause / resume (B-02). `invalid` is what append writes when a
# caller passes anything else (a denied `--mode yolo`); the raw value goes to result.requested_mode.
Mode = Literal["dry-run", "execute", "approve", "reject", "pause", "resume", "invalid"]
MODES: tuple[Mode, ...] = get_args(Mode)
AuditMode = Mode

# STD-AU-2 events, plus `lever.pause` for the pause switch (proposed in docs/changes/B-17.md).
Event = Literal["lever.invoke", "lever.pause", "proposal.add", "proposal.decide", "model.complete", "job.run"]
EVENTS: tuple[Event, ...] = get_args(Event)
# `unknown` is the honest default while a caller does not say (B-28 wires the runner's value).
ActorKind = Literal["agent", "human", "unknown"]
ACTOR_KINDS: tuple[ActorKind, ...] = get_args(ActorKind)

_EVENT_FOR_MODE: dict[str, Event] = {
    "dry-run": "lever.invoke",
    "execute": "lever.invoke",
    "invalid": "lever.invoke",
    "approve": "proposal.decide",
    "reject": "proposal.decide",
    "pause": "lever.pause",
    "resume": "lever.pause",
}
_ID_MAX = 128


def new_request_id() -> str:
    """A fresh correlation id (`req-` + a UUID with hyphens), used when the caller passes none.

    The hyphenated form matters: redaction keeps GUIDs but replaces a bare 32-hex run, so `uuid4().hex`
    would be written as `req-[REDACTED]` and correlate nothing.
    """
    return "req-" + str(uuid.uuid4())


def default_event(mode: str) -> Event:
    """The event a record of this mode belongs to when the caller does not name one."""
    return _EVENT_FOR_MODE.get(mode, "lever.invoke")


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


class AuditError(RuntimeError):
    """The log cannot be appended to safely (for example the head pin and the log disagree)."""


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def record_hash(record: dict[str, Any]) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(canonical_json(body)).hexdigest()


def head_path_for(log_path: Path) -> Path:
    """Default head file next to the log: audit.jsonl -> audit.jsonl.head."""
    return log_path.with_name(log_path.name + ".head")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _read_head(head_path: Path) -> tuple[int, str] | None:
    if not head_path.exists():
        return None
    data = json.loads(head_path.read_text(encoding="utf-8"))
    seq, hash_ = data["seq"], data["hash"]
    if not isinstance(seq, int) or not isinstance(hash_, str):
        raise ValueError("head file must hold an integer seq and a string hash")
    return seq, hash_


def _write_head_atomic(head_path: Path, seq: int, hash_: str) -> None:
    tmp = head_path.with_name(head_path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"seq": seq, "hash": hash_}) + "\n", encoding="utf-8")
    # On Windows a reader (the verifier, an antivirus scan) holding the file open makes os.replace
    # fail briefly, so retry a few times before giving up.
    for attempt in range(5):
        try:
            os.replace(tmp, head_path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.02 * (attempt + 1))


_PATH_LOCKS: dict[Path, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(path, threading.Lock())


class AuditLog:
    """Writes audit records. Refuses to extend a log whose head pin does not match its last record."""

    def __init__(self, path: Path, head_path: Path | None = None) -> None:
        self.path = Path(path).resolve()
        self.head_path = Path(head_path).resolve() if head_path else head_path_for(self.path)
        self._lock = _lock_for(self.path)

    def append(
        self,
        *,
        agent: str,
        client: str | None,
        lever: str,
        params: dict[str, Any],
        mode: Mode,
        result: dict[str, Any],
        approver: str | None = None,
        event: Event | None = None,
        actor_kind: ActorKind | None = None,
        lever_version: int | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Append one v2 record (params and result redacted) and return it as written.

        The v2 fields default when the caller does not pass them: `event` from the mode,
        `actor_kind` to `unknown`, `lever_version` to null, `request_id` to a fresh id. Odd
        values never stop a record (STD-AU-6): an unknown mode is written as `invalid` with the
        raw value in `result.requested_mode`, an unknown event falls back to the mode's default,
        an unknown actor kind to `unknown`, and a lever version that is not a positive integer
        to null.
        """
        written_mode: Mode = mode if mode in MODES else "invalid"
        if written_mode != mode:
            result = {**result, "requested_mode": str(mode)[:64]}
        written_event: Event = event if event in EVENTS else default_event(written_mode)
        written_kind: ActorKind = actor_kind if actor_kind in ACTOR_KINDS else "unknown"
        written_request = str(request_id)[:_ID_MAX] if request_id else (current_request_id() or new_request_id())
        with self._lock:
            last_seq, last_hash = self._tail()
            record: dict[str, Any] = {
                "v": RECORD_VERSION,
                "seq": last_seq + 1,
                "ts": _utc_now(),
                "event": written_event,
                "agent": agent,
                "actor_kind": written_kind,
                "client": client,
                "lever": lever,
                "lever_version": lever_version if _positive_int(lever_version) else None,
                "request_id": redact(written_request),
                "params": redact(params),
                "mode": written_mode,
                "result": redact(result),
                "approver": approver,
                "prev_hash": last_hash,
            }
            record["hash"] = record_hash(record)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("ab") as fh:
                fh.write(canonical_json(record) + b"\n")
                fh.flush()
                os.fsync(fh.fileno())
            _write_head_atomic(self.head_path, record["seq"], record["hash"])
            return record

    def _tail(self) -> tuple[int, str]:
        """Last (seq, hash), cross-checked between the log's last line and the head pin."""
        last_line = _last_line(self.path)
        try:
            head = _read_head(self.head_path)
        except (OSError, ValueError, KeyError) as exc:
            raise AuditError(f"unreadable head file {self.head_path}: {exc}") from exc
        if last_line is None:
            if head is not None:
                raise AuditError(f"log {self.path} is empty but the head pins seq {head[0]}")
            return 0, GENESIS_HASH
        try:
            last = json.loads(last_line)
            tail = (int(last["seq"]), str(last["hash"]))
        except (ValueError, KeyError, TypeError) as exc:
            raise AuditError(f"last record of {self.path} is unreadable: {exc}") from exc
        if head != tail:
            raise AuditError(f"head pin {head} does not match the last record {tail}; run the verifier")
        return tail


def _last_line(path: Path) -> bytes | None:
    """The last non-blank line, read backwards from the end so appends stay O(record size)."""
    if not path.exists():
        return None
    with path.open("rb") as fh:
        pos = fh.seek(0, os.SEEK_END)
        buf = b""
        while pos > 0:
            step = min(8192, pos)
            pos -= step
            fh.seek(pos)
            buf = fh.read(step) + buf
            stripped = buf.rstrip()
            if b"\n" in stripped:
                return stripped.rsplit(b"\n", 1)[1]
    return buf.rstrip() or None


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    records: int
    broken_seq: int | None = None
    reason: str = ""
    v1_records: int = 0
    v2_records: int = 0


def _shape_problem(record: dict[str, Any], seen_v2: bool) -> str | None:
    """Why this record's version and fields are not acceptable at this point of the log, or None."""
    if "v" not in record:
        if seen_v2:
            return "v1 record after a v2 record (versions only move forward)"
        if set(record) != RECORD_FIELDS_V1:
            return "record fields are missing or unexpected"
        return None
    version = record["v"]
    if isinstance(version, bool) or version != RECORD_VERSION:
        return f"unknown record version {version!r}"
    if set(record) != RECORD_FIELDS_V2:
        return "record fields are missing or unexpected"
    for field, allowed in (("mode", MODES), ("event", EVENTS), ("actor_kind", ACTOR_KINDS)):
        if record[field] not in allowed:
            return f"{field} {record[field]!r} is not a known value"
    if record["lever_version"] is not None and not _positive_int(record["lever_version"]):
        return "lever_version must be a positive integer or null"
    if not isinstance(record["request_id"], str) or not record["request_id"]:
        return "request_id must be a non-empty string"
    return None


def verify_chain(path: Path, head_path: Path | None = None) -> VerifyResult:
    """Check every record's version, seq, prev_hash and hash, then the head pin if one is given.

    Returns the first broken seq. A record that cannot be parsed is reported at the seq it
    should have had. Accepts v1 records followed by v2 records, never a v1 record after a v2 one.
    """
    lines = Path(path).read_bytes().splitlines()
    prev_hash = GENESIS_HASH
    counts = {1: 0, 2: 0}

    def done(ok: bool, broken_seq: int | None, reason: str) -> VerifyResult:
        return VerifyResult(ok, counts[1] + counts[2], broken_seq, reason, counts[1], counts[2])

    for index, line in enumerate(lines):
        expected_seq = index + 1
        if not line.strip():
            return done(False, expected_seq, f"blank line where seq {expected_seq} should be")
        try:
            record = json.loads(line)
        except ValueError:
            return done(False, expected_seq, "record is not valid JSON")
        if not isinstance(record, dict):
            return done(False, expected_seq, "record fields are missing or unexpected")
        problem = _shape_problem(record, seen_v2=counts[2] > 0)
        if problem:
            return done(False, expected_seq, problem)
        if record["seq"] != expected_seq:
            return done(False, expected_seq, f"seq is {record['seq']!r}, expected {expected_seq}")
        if record["prev_hash"] != prev_hash:
            return done(False, expected_seq, "prev_hash does not match the previous record")
        if record_hash(record) != record["hash"]:
            return done(False, expected_seq, "hash does not match the record content")
        if line != canonical_json(record):
            return done(False, expected_seq, "record bytes are not in canonical form (edited)")
        prev_hash = record["hash"]
        counts[2 if "v" in record else 1] += 1

    count = counts[1] + counts[2]
    if head_path is None:
        return done(True, None, "chain intact (no head pin checked)")
    try:
        head = _read_head(Path(head_path))
    except (OSError, ValueError, KeyError) as exc:
        return done(False, count + 1, f"head file unreadable: {exc}")
    if head is None:
        return done(False, count + 1, f"head file {head_path} is missing")
    head_seq, head_hash = head
    if head_seq > count:
        return done(False, count + 1, f"log ends at seq {count} but the head pins seq {head_seq}")
    if head_seq < count:
        return done(False, head_seq + 1, f"records after the pinned head seq {head_seq}")
    if head_hash != prev_hash:
        return done(False, count or None, "last record hash does not match the head pin")
    return done(True, None, "chain intact and matches the head pin")
