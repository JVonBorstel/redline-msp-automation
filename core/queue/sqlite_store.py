"""Durable job queue and approval store in SQLite (B-82): idempotency keys, leases, retries, dead letters, CAS.

Two classes share one database file (and, if you want, the audit store's file):

`SqliteJobQueue`: a per-client work queue.
- `enqueue(client, kind, payload, idempotency_key)` is idempotent on (client, key): the same request again returns the
  existing job (`created=False`); the same key with a different kind or payload is a `QueueConflict`.
- `claim(client, worker, lease_s=...)` hands out the oldest due job and leases it. Every claim counts as an attempt.
  A lease that runs out (the worker crashed or hung) makes the job claimable again; a job whose lease runs out on its
  last attempt goes to the dead letters, so a job that keeps killing its worker cannot loop forever.
- `heartbeat`, `complete` and `fail` act only on a live lease held by the caller: the claim's attempt number is a
  fencing token, so a worker that lost its lease cannot finish, fail or extend a job someone else now holds
  (`LeaseLost`). `fail` retries with exponential backoff (`backoff_base_s * 2**(attempt-1)`, capped, no jitter so
  tests and timelines are exact) until `max_attempts`, then dead-letters. `retry=False` dead-letters at once.
- Dead letters stay until a person calls `requeue_dead`. Nothing here ever deletes a job.
- Every method takes the client and touches only that client's rows. Idempotency keys are per client.

`SqliteApprovalStore`: the pending/approved/rejected/executed/failed life of a `core.queue.store.Proposal`.
- `decide` changes status with `UPDATE ... WHERE client = ? AND id = ? AND status = 'pending'` (compare-and-set), so
  two leads deciding at once produce one decision and one `AlreadyDecided`; a requester cannot decide their own
  proposal (`SelfApproval`). `finish` records executed/failed, only from approved. Triggers refuse any other status
  move even from raw SQL.
- This store does the bookkeeping only. Who may approve what (roles, client scope, runner re-check, audit of the
  decision) stays in `core.queue.store.ProposalQueue`, which remains the default (B82-3).

Every write is one `BEGIN IMMEDIATE` transaction in WAL mode with `synchronous=FULL`; a crash leaves a whole change or
none. Time comes from an injectable clock (UTC, millisecond integers in the database). Payloads and results are stored
as written: do not put secrets in them (error text is redacted). Migrations are numbered and recorded per component in
`schema_migrations`; a database newer than this code is refused.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from core.audit.chain import canonical_json
from core.audit.redact import redact_text
from core.audit.router import valid_client_id
from core.auth.models import ApproverAuth
from core.levers.models import Verification
from core.queue.store import Proposal, QueueError, Status

COMPONENT = "queue"
BUSY_TIMEOUT_S = 10.0
JOB_STATUSES: tuple[str, ...] = ("queued", "leased", "done", "dead")
Clock = Callable[[], datetime]
JobStatus = Literal["queued", "leased", "done", "dead"]

_UNIX = datetime(1970, 1, 1, tzinfo=UTC)
_KIND_MAX = 128
_KEY_MAX = 200
_ERROR_MAX = 2000

MIGRATIONS: list[tuple[int, tuple[str, ...]]] = [
    (
        1,
        (
            "CREATE TABLE jobs ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, client TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,"
            " idem_key TEXT NOT NULL, request_hash TEXT NOT NULL,"
            " status TEXT NOT NULL CHECK (status IN ('queued', 'leased', 'done', 'dead')),"
            " attempts INTEGER NOT NULL CHECK (attempts >= 0), max_attempts INTEGER NOT NULL CHECK (max_attempts >= 1),"
            " available_ms INTEGER NOT NULL, lease_owner TEXT, lease_until_ms INTEGER, last_error TEXT, result TEXT,"
            " created_ms INTEGER NOT NULL, updated_ms INTEGER NOT NULL, UNIQUE (client, idem_key))",
            "CREATE INDEX jobs_due ON jobs (client, status, available_ms)",
            "CREATE INDEX jobs_leases ON jobs (client, status, lease_until_ms)",
            "CREATE TRIGGER jobs_done_is_final BEFORE UPDATE ON jobs WHEN OLD.status = 'done' BEGIN "
            "SELECT RAISE(ABORT, 'jobs: a done job is final'); END",
            "CREATE TRIGGER jobs_identity_is_fixed BEFORE UPDATE ON jobs WHEN NEW.client <> OLD.client "
            "OR NEW.kind <> OLD.kind OR NEW.payload <> OLD.payload OR NEW.idem_key <> OLD.idem_key BEGIN "
            "SELECT RAISE(ABORT, 'jobs: client, kind, payload and idempotency key are fixed'); END",
            "CREATE TABLE proposals ("
            " id TEXT NOT NULL, client TEXT NOT NULL, requested_by TEXT NOT NULL,"
            " status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'executed', 'failed')),"
            " decided_by TEXT, decided_at TEXT, body TEXT NOT NULL, created_ms INTEGER NOT NULL,"
            " updated_ms INTEGER NOT NULL, UNIQUE (client, id))",
            "CREATE TRIGGER proposals_status_moves BEFORE UPDATE OF status ON proposals WHEN NOT ("
            "NEW.status = OLD.status OR (OLD.status = 'pending' AND NEW.status IN ('approved', 'rejected')) "
            "OR (OLD.status = 'approved' AND NEW.status IN ('executed', 'failed'))) BEGIN "
            "SELECT RAISE(ABORT, 'proposals: status may only move pending to approved or rejected, "
            "approved to executed or failed'); END",
            "CREATE TRIGGER proposals_identity_is_fixed BEFORE UPDATE ON proposals WHEN NEW.id <> OLD.id "
            "OR NEW.client <> OLD.client OR NEW.requested_by <> OLD.requested_by BEGIN "
            "SELECT RAISE(ABORT, 'proposals: id, client and requester are fixed'); END",
        ),
    )
]


class JobQueueError(QueueError):
    """A bad request to the SQLite queue (invalid input, unknown job or proposal, store unusable)."""


class QueueConflict(JobQueueError):
    """The idempotency key is already used for a different kind or payload."""


class LeaseLost(JobQueueError):
    """The caller no longer holds a live lease on the job (expired, taken over, or the job already finished)."""


class SchemaTooNew(JobQueueError):
    """The database was migrated by newer code than this."""


class AlreadyDecided(JobQueueError):
    """The proposal is not in the state the change needs (someone else decided first). `status` is what it is now."""

    def __init__(self, message: str, status: str) -> None:
        super().__init__(message)
        self.status = status


class SelfApproval(JobQueueError):
    """A requester tried to decide their own proposal (four-eyes rule)."""


@dataclass(frozen=True)
class Job:
    id: int
    client: str
    kind: str
    payload: dict[str, Any]
    idempotency_key: str
    status: JobStatus
    attempts: int
    max_attempts: int
    available_at: datetime
    lease_owner: str | None
    lease_until: datetime | None
    last_error: str | None
    result: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class EnqueueResult:
    job: Job
    created: bool


def _default_clock() -> datetime:
    return datetime.now(UTC)


def _to_dt(ms: int) -> datetime:
    return _UNIX + timedelta(milliseconds=ms)


def _check_client(client: str) -> None:
    if not valid_client_id(client):
        raise JobQueueError(f"{client!r} is not a client id")


class _Database:
    """Connection, WAL, migrations and write transactions shared by both stores."""

    def __init__(self, path: Path | str, clock: Clock | None, busy_timeout_s: float) -> None:
        self.path = Path(path).resolve()
        self.clock: Clock = clock or _default_clock
        self.busy_timeout_s = busy_timeout_s
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + busy_timeout_s
        while True:
            try:
                with closing(self._connect()) as con:
                    self._enable_wal(con)
                    self._migrate(con)
                break
            except sqlite3.OperationalError as exc:
                # Another process is creating or migrating the same file right now: wait and look again.
                if ("locked" not in str(exc) and "busy" not in str(exc)) or time.monotonic() > deadline:
                    raise
                time.sleep(0.05)

    def _now_ms(self) -> int:
        moment = self.clock()
        if moment.tzinfo is None:
            raise JobQueueError("the clock returned a naive datetime; it must be timezone-aware")
        return (moment - _UNIX) // timedelta(milliseconds=1)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=self.busy_timeout_s, isolation_level=None)
        con.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_s * 1000)}")
        con.execute("PRAGMA synchronous = FULL")
        con.execute("PRAGMA foreign_keys = ON")
        return con

    @staticmethod
    def _enable_wal(con: sqlite3.Connection) -> None:
        mode = str(con.execute("PRAGMA journal_mode = WAL").fetchone()[0]).lower()
        if mode != "wal":
            raise JobQueueError(f"could not switch the database to WAL mode (got {mode!r})")

    def _migrate(self, con: sqlite3.Connection) -> None:
        con.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " component TEXT NOT NULL, version INTEGER NOT NULL, applied_ms INTEGER NOT NULL,"
            " PRIMARY KEY (component, version))"
        )

        def applied() -> int:
            row = con.execute("SELECT MAX(version) FROM schema_migrations WHERE component = ?", (COMPONENT,)).fetchone()
            return int(row[0] or 0)

        latest = MIGRATIONS[-1][0]
        if applied() == latest:
            return
        con.execute("BEGIN IMMEDIATE")
        try:
            current = applied()  # re-read under the write lock: another process may have just migrated
            if current > latest:
                raise SchemaTooNew(f"database is at queue schema {current}, this code knows {latest}")
            for version, statements in MIGRATIONS:
                if version > current:
                    for statement in statements:
                        con.execute(statement)
                    con.execute(
                        "INSERT INTO schema_migrations (component, version, applied_ms) VALUES (?, ?, ?)",
                        (COMPONENT, version, self._now_ms()),
                    )
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """One write transaction: whole or nothing. A lock that is not released in time fails closed."""
        con = self._connect()
        try:
            try:
                con.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                raise JobQueueError(f"queue database is locked; nothing changed (failing closed): {exc}") from exc
            try:
                yield con
                con.execute("COMMIT")
            except BaseException:
                if con.in_transaction:
                    con.execute("ROLLBACK")
                raise
        finally:
            con.close()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        con = self._connect()
        try:
            con.execute("BEGIN")
            yield con
        finally:
            con.close()

    def journal_mode(self) -> str:
        with closing(self._connect()) as con:
            return str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower()

    def schema_version(self) -> int:
        with closing(self._connect()) as con:
            row = con.execute("SELECT MAX(version) FROM schema_migrations WHERE component = ?", (COMPONENT,)).fetchone()
        return int(row[0] or 0)

    def integrity_check(self) -> str:
        with closing(self._connect()) as con:
            return str(con.execute("PRAGMA integrity_check").fetchone()[0])


_JOB_COLUMNS = (
    "id, client, kind, payload, idem_key, status, attempts, max_attempts, available_ms, lease_owner, lease_until_ms,"
    " last_error, result, created_ms, updated_ms, request_hash"
)


def _select(where: str) -> str:
    """A job SELECT. `where` is always a literal written in this module, never caller input."""
    return "SELECT " + _JOB_COLUMNS + " FROM jobs WHERE " + where  # noqa: S608


def _job(row: Sequence[Any]) -> Job:
    return Job(
        id=int(row[0]),
        client=str(row[1]),
        kind=str(row[2]),
        payload=json.loads(row[3]),
        idempotency_key=str(row[4]),
        status=row[5],
        attempts=int(row[6]),
        max_attempts=int(row[7]),
        available_at=_to_dt(int(row[8])),
        lease_owner=row[9],
        lease_until=_to_dt(int(row[10])) if row[10] is not None else None,
        last_error=row[11],
        result=json.loads(row[12]) if row[12] is not None else None,
        created_at=_to_dt(int(row[13])),
        updated_at=_to_dt(int(row[14])),
    )


class SqliteJobQueue(_Database):
    def __init__(
        self,
        path: Path | str,
        *,
        clock: Clock | None = None,
        busy_timeout_s: float = BUSY_TIMEOUT_S,
        backoff_base_s: float = 5.0,
        backoff_cap_s: float = 300.0,
    ) -> None:
        super().__init__(path, clock, busy_timeout_s)
        self.backoff_base_s = backoff_base_s
        self.backoff_cap_s = backoff_cap_s

    def enqueue(
        self,
        client: str,
        kind: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
        *,
        max_attempts: int = 5,
        delay_s: float = 0,
    ) -> EnqueueResult:
        """Add a job, or return the job this (client, key) already made. A different request under the key conflicts."""
        _check_client(client)
        if not kind or len(kind) > _KIND_MAX or not kind.isprintable():
            raise JobQueueError("kind must be 1 to 128 printable characters")
        if not idempotency_key or len(idempotency_key) > _KEY_MAX or not idempotency_key.isprintable():
            raise JobQueueError("idempotency_key must be 1 to 200 printable characters")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise JobQueueError("max_attempts must be an integer of at least 1")
        if delay_s < 0:
            raise JobQueueError("delay_s must not be negative")
        try:
            body = canonical_json(dict(payload)).decode("utf-8")
        except (TypeError, ValueError) as exc:
            raise JobQueueError(f"payload is not JSON-serialisable: {exc}") from exc
        digest = hashlib.sha256(kind.encode() + b"\0" + body.encode()).hexdigest()
        with self._write() as con:
            row = con.execute(
                _select("client = ? AND idem_key = ?"),
                (client, idempotency_key),
            ).fetchone()
            if row is not None:
                if row[15] != digest:
                    raise QueueConflict(f"idempotency key {idempotency_key!r} was used for a different request")
                return EnqueueResult(_job(row), False)
            now = self._now_ms()
            cursor = con.execute(
                "INSERT INTO jobs (client, kind, payload, idem_key, request_hash, status, attempts, max_attempts,"
                " available_ms, created_ms, updated_ms) VALUES (?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?, ?)",
                (client, kind, body, idempotency_key, digest, max_attempts, now + int(delay_s * 1000), now, now),
            )
            created = con.execute(_select("id = ?"), (cursor.lastrowid,)).fetchone()
        return EnqueueResult(_job(created), True)

    def claim(self, client: str, worker: str, *, lease_s: float = 30, kinds: Sequence[str] | None = None) -> Job | None:
        """Lease the oldest due job of this client to `worker` for `lease_s` seconds, or return None."""
        _check_client(client)
        if not worker or len(worker) > 128:
            raise JobQueueError("worker must be 1 to 128 characters")
        if lease_s <= 0:
            raise JobQueueError("lease_s must be positive")
        with self._write() as con:
            now = self._now_ms()
            con.execute(
                "UPDATE jobs SET status = 'dead', lease_owner = NULL, lease_until_ms = NULL, updated_ms = ?,"
                " last_error = 'lease expired on attempt ' || attempts || ' and retries are exhausted'"
                " WHERE client = ? AND status = 'leased' AND lease_until_ms <= ? AND attempts >= max_attempts",
                (now, client, now),
            )
            query = (
                "SELECT id FROM jobs WHERE client = ? AND ((status = 'queued' AND available_ms <= ?)"
                " OR (status = 'leased' AND lease_until_ms <= ?))"
            )
            args: list[Any] = [client, now, now]
            if kinds is not None:
                query += f" AND kind IN ({', '.join('?' for _ in kinds)})"
                args += list(kinds)
            row = con.execute(query + " ORDER BY available_ms, id LIMIT 1", args).fetchone()
            if row is None:
                return None
            con.execute(
                "UPDATE jobs SET last_error = CASE WHEN status = 'leased'"
                " THEN 'lease expired: worker ' || lease_owner || ' did not finish attempt ' || attempts"
                " ELSE last_error END, status = 'leased', attempts = attempts + 1, lease_owner = ?,"
                " lease_until_ms = ?, updated_ms = ? WHERE id = ? AND client = ?",
                (worker, now + int(lease_s * 1000), now, row[0], client),
            )
            claimed = con.execute(_select("id = ?"), (row[0],)).fetchone()
        return _job(claimed)

    def _held(self, con: sqlite3.Connection, job: Job, now: int) -> tuple[Any, ...]:
        """The job's row if `job` is a live lease held by its owner (the attempt number is the fencing token)."""
        row = con.execute(
            _select(
                "id = ? AND client = ? AND status = 'leased' AND attempts = ?"
                " AND lease_owner = ? AND lease_until_ms > ?"
            ),
            (job.id, job.client, job.attempts, job.lease_owner, now),
        ).fetchone()
        if row is None:
            raise LeaseLost(f"job {job.id} is not leased to {job.lease_owner!r} for attempt {job.attempts} (any more)")
        return tuple(row)

    def heartbeat(self, job: Job, *, lease_s: float = 30) -> Job:
        """Push a live lease out to `lease_s` seconds from now."""
        if lease_s <= 0:
            raise JobQueueError("lease_s must be positive")
        with self._write() as con:
            now = self._now_ms()
            self._held(con, job, now)
            con.execute(
                "UPDATE jobs SET lease_until_ms = ?, updated_ms = ? WHERE id = ?",
                (now + int(lease_s * 1000), now, job.id),
            )
            row = con.execute(_select("id = ?"), (job.id,)).fetchone()
        return _job(row)

    def complete(self, job: Job, result: Mapping[str, Any] | None = None) -> Job:
        with self._write() as con:
            now = self._now_ms()
            self._held(con, job, now)
            try:
                body = canonical_json(dict(result or {})).decode("utf-8")
            except (TypeError, ValueError) as exc:
                raise JobQueueError(f"result is not JSON-serialisable: {exc}") from exc
            con.execute(
                "UPDATE jobs SET status = 'done', result = ?, lease_owner = NULL, lease_until_ms = NULL, updated_ms = ?"
                " WHERE id = ?",
                (body, now, job.id),
            )
            row = con.execute(_select("id = ?"), (job.id,)).fetchone()
        return _job(row)

    def fail(self, job: Job, error: str, *, retry: bool = True) -> Job:
        """Record a failed attempt: back to the queue after the backoff, or to the dead letters when out of attempts."""
        message = redact_text(str(error))[:_ERROR_MAX]
        with self._write() as con:
            now = self._now_ms()
            held = self._held(con, job, now)
            attempts, max_attempts = int(held[6]), int(held[7])
            if retry and attempts < max_attempts:
                wait = min(self.backoff_base_s * 2 ** (attempts - 1), self.backoff_cap_s)
                con.execute(
                    "UPDATE jobs SET status = 'queued', available_ms = ?, last_error = ?, lease_owner = NULL,"
                    " lease_until_ms = NULL, updated_ms = ? WHERE id = ?",
                    (now + int(wait * 1000), message, now, job.id),
                )
            else:
                con.execute(
                    "UPDATE jobs SET status = 'dead', last_error = ?, lease_owner = NULL, lease_until_ms = NULL,"
                    " updated_ms = ? WHERE id = ?",
                    (message, now, job.id),
                )
            row = con.execute(_select("id = ?"), (job.id,)).fetchone()
        return _job(row)

    def requeue_dead(self, client: str, job_id: int) -> Job:
        """A person's decision to try a dead-lettered job again: attempts reset, due now."""
        _check_client(client)
        with self._write() as con:
            now = self._now_ms()
            changed = con.execute(
                "UPDATE jobs SET status = 'queued', attempts = 0, available_ms = ?, updated_ms = ?"
                " WHERE id = ? AND client = ? AND status = 'dead'",
                (now, now, job_id, client),
            ).rowcount
            if changed != 1:
                raise JobQueueError(f"job {job_id} is not a dead letter of client {client!r}")
            row = con.execute(_select("id = ?"), (job_id,)).fetchone()
        return _job(row)

    def get(self, client: str, job_id: int) -> Job | None:
        _check_client(client)
        with self._read() as con:
            row = con.execute(_select("id = ? AND client = ?"), (job_id, client)).fetchone()
        return _job(row) if row else None

    def list(self, client: str, status: JobStatus | None = None) -> tuple[Job, ...]:
        _check_client(client)
        query, args = _select("client = ?"), [client]
        if status is not None:
            query, args = query + " AND status = ?", [client, status]
        with self._read() as con:
            rows = con.execute(query + " ORDER BY id", args).fetchall()
        return tuple(_job(r) for r in rows)

    def dead_letters(self, client: str) -> tuple[Job, ...]:
        return self.list(client, "dead")

    def counts(self, client: str) -> dict[str, int]:
        _check_client(client)
        with self._read() as con:
            rows = dict(con.execute("SELECT status, COUNT(*) FROM jobs WHERE client = ? GROUP BY status", (client,)))
        return {status: int(rows.get(status, 0)) for status in JOB_STATUSES}


class SqliteApprovalStore(_Database):
    def __init__(self, path: Path | str, *, clock: Clock | None = None, busy_timeout_s: float = BUSY_TIMEOUT_S) -> None:
        super().__init__(path, clock, busy_timeout_s)

    def _stamp(self) -> str:
        return (_to_dt(self._now_ms())).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _body(proposal: Proposal) -> str:
        return canonical_json(proposal.model_dump(mode="json")).decode("utf-8")

    @staticmethod
    def _load(body: str) -> Proposal:
        return Proposal.model_validate_json(body)

    def add(self, proposal: Proposal) -> Proposal:
        """Store a new pending proposal. Idempotent: a proposal already stored for the client is returned unchanged."""
        _check_client(proposal.client)
        if proposal.status != "pending":
            raise JobQueueError("only a pending proposal can be added")
        with self._write() as con:
            now = self._now_ms()
            con.execute(
                "INSERT OR IGNORE INTO proposals (id, client, requested_by, status, body, created_ms, updated_ms)"
                " VALUES (?, ?, ?, 'pending', ?, ?, ?)",
                (proposal.id, proposal.client, proposal.requested_by, self._body(proposal), now, now),
            )
            row = con.execute(
                "SELECT body FROM proposals WHERE client = ? AND id = ?", (proposal.client, proposal.id)
            ).fetchone()
        return self._load(row[0])

    def get(self, client: str, proposal_id: str) -> Proposal | None:
        _check_client(client)
        with self._read() as con:
            row = con.execute(
                "SELECT body FROM proposals WHERE client = ? AND id = ?", (client, proposal_id)
            ).fetchone()
        return self._load(row[0]) if row else None

    def list(self, client: str, status: Status | None = None) -> tuple[Proposal, ...]:
        _check_client(client)
        query, args = "SELECT body FROM proposals WHERE client = ?", [client]
        if status is not None:
            query, args = query + " AND status = ?", [client, status]
        with self._read() as con:
            rows = con.execute(query + " ORDER BY rowid", args).fetchall()
        return tuple(self._load(r[0]) for r in rows)

    def decide(
        self,
        client: str,
        proposal_id: str,
        approver: str,
        approve: bool,
        verification: Verification | None = None,
        auth: ApproverAuth | None = None,
    ) -> Proposal:
        """Approve or reject one pending proposal (compare-and-set on `status = 'pending'`).

        Raises AlreadyDecided when it is no longer pending, SelfApproval when the approver is the requester.
        """
        return self._move(
            client, proposal_id, "pending", "approved" if approve else "rejected", approver, verification, auth
        )

    def finish(self, client: str, proposal_id: str, ok: bool) -> Proposal:
        """Record the outcome of running an approved proposal: executed, or failed. Only from approved."""
        return self._move(client, proposal_id, "approved", "executed" if ok else "failed", None, None, None)

    def _move(
        self,
        client: str,
        proposal_id: str,
        expect: Status,
        new: Status,
        approver: str | None,
        verification: Verification | None,
        auth: ApproverAuth | None,
    ) -> Proposal:
        _check_client(client)
        with self._write() as con:
            row = con.execute(
                "SELECT body FROM proposals WHERE client = ? AND id = ?", (client, proposal_id)
            ).fetchone()
            if row is None:
                raise JobQueueError(f"no proposal {proposal_id!r} for client {client!r}")
            current = self._load(row[0])
            if approver is not None and approver == current.requested_by:
                raise SelfApproval("a requester cannot decide their own proposal (four-eyes rule)")
            if current.status != expect:
                raise AlreadyDecided(f"{proposal_id} is {current.status}, not {expect}", current.status)
            changes: dict[str, Any] = {"status": new}
            if approver is not None:
                changes.update(
                    decided_by=approver, decided_at=self._stamp(), verification=verification, approver_auth=auth
                )
            try:
                updated = Proposal.model_validate({**current.model_dump(), **changes})
            except ValidationError as exc:
                raise JobQueueError(f"invalid decision: {exc}") from exc
            now = self._now_ms()
            changed = con.execute(
                "UPDATE proposals SET status = ?, decided_by = ?, decided_at = ?, body = ?, updated_ms = ?"
                " WHERE client = ? AND id = ? AND status = ?",
                (new, updated.decided_by, updated.decided_at, self._body(updated), now, client, proposal_id, expect),
            ).rowcount
            if changed != 1:  # the compare-and-set lost: somebody moved it between our read and write
                raise AlreadyDecided(f"{proposal_id} changed under us; nothing was decided", "unknown")
        return updated
