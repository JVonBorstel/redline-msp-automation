"""Append-only, hash-chained audit store in SQLite (B-82). Same records, same hashes, same verifier as the JSONL log.

Every record is the exact canonical JSON line `core.audit.chain.AuditLog` would write, stored whole in
`audit_records.line` beside indexed `chain`, `seq`, `hash` and `prev_hash` columns. The hash covers the record, so a
row exported to JSONL (`export_chain`) is the same bytes and `core.audit.verify` / `verify_chain` accept it. `verify`
runs that very verifier over the stored lines, so SQLite and JSONL cannot drift on what "intact" means.

One chain per client (plus `_msp` for records with no usable client id), as in `core.audit.router`: sequence numbers,
hashes and exports are per chain, and a client's export holds no other client's records.

What the database itself enforces (triggers, so even raw SQL from another tool is refused):
- UPDATE and DELETE on `audit_records` and `audit_heads`;
- an INSERT whose `seq` is not the next one, or whose `prev_hash` is not the chain's head hash (no fork, no gap);
- a head move of anything but "one record further, to a hash that exists".

What it cannot enforce: someone who can write the file can drop the triggers. `verify` therefore (1) re-verifies every
chain, (2) compares each chain with its stored head, so deleting the newest records is found, (3) checks that the guard
triggers exist unchanged, and (4) accepts an `expected_head` pin held somewhere else (a ticket, another host, the last
export) which is the only defence against an attacker who rewinds records and head together and re-creates the
triggers. See specs/B-82.md for the full list.

Concurrency: each append is one `BEGIN IMMEDIATE` transaction in WAL mode with `synchronous=FULL`, so writers in any
number of threads or processes queue on SQLite's write lock (waiting up to `busy_timeout_s`, then failing closed with
`SqliteAuditStoreError`) and a crash leaves either the whole record or nothing. This store is not wired into the
runner: the JSONL stores stay the default until a DECISIONS entry switches them (B82-3).

    uv run python -m core.audit.sqlite_store verify <db> [--client <id> --pin <seq>:<hash>]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.audit.chain import (
    ACTOR_KINDS,
    EVENTS,
    GENESIS_HASH,
    MODES,
    RECORD_VERSION,
    ActorKind,
    AuditError,
    Event,
    Mode,
    VerifyResult,
    canonical_json,
    default_event,
    head_path_for,
    new_request_id,
    record_hash,
    verify_chain,
)
from core.audit.redact import redact
from core.audit.router import MSP_LOG, valid_client_id
from core.obs.context import current_request_id

COMPONENT = "audit"
BUSY_TIMEOUT_S = 10.0
_ID_MAX = 128
Clock = Callable[[], datetime]

_TABLES: tuple[str, ...] = (
    "CREATE TABLE audit_records ("
    " chain TEXT NOT NULL, seq INTEGER NOT NULL, hash TEXT NOT NULL, prev_hash TEXT NOT NULL, line TEXT NOT NULL,"
    " PRIMARY KEY (chain, seq)) WITHOUT ROWID",
    "CREATE TABLE audit_heads (chain TEXT PRIMARY KEY, seq INTEGER NOT NULL, hash TEXT NOT NULL) WITHOUT ROWID",
)

# The guard triggers. `verify` compares the database's copy of each with this text, so editing one is also found.
GUARD_STATEMENTS: tuple[str, ...] = (
    "CREATE TRIGGER audit_records_no_update BEFORE UPDATE ON audit_records BEGIN "
    "SELECT RAISE(ABORT, 'audit_records is append-only: UPDATE refused'); END",
    "CREATE TRIGGER audit_records_no_delete BEFORE DELETE ON audit_records BEGIN "
    "SELECT RAISE(ABORT, 'audit_records is append-only: DELETE refused'); END",
    "CREATE TRIGGER audit_records_extends_chain BEFORE INSERT ON audit_records "
    "WHEN NEW.seq <> COALESCE((SELECT seq FROM audit_heads WHERE chain = NEW.chain), 0) + 1 "
    "OR NEW.prev_hash <> COALESCE((SELECT hash FROM audit_heads WHERE chain = NEW.chain), "
    "'00000000000000000000000000000000"
    "00000000000000000000000000000000') BEGIN "
    "SELECT RAISE(ABORT, 'audit_records chain check failed: seq and prev_hash must extend the chain head'); END",
    "CREATE TRIGGER audit_records_advance_head AFTER INSERT ON audit_records BEGIN "
    "INSERT INTO audit_heads (chain, seq, hash) VALUES (NEW.chain, NEW.seq, NEW.hash) "
    "ON CONFLICT (chain) DO UPDATE SET seq = excluded.seq, hash = excluded.hash; END",
    "CREATE TRIGGER audit_heads_advance_only BEFORE UPDATE ON audit_heads "
    "WHEN NEW.chain <> OLD.chain OR NEW.seq <> OLD.seq + 1 OR NOT EXISTS "
    "(SELECT 1 FROM audit_records WHERE chain = NEW.chain AND seq = NEW.seq AND hash = NEW.hash) BEGIN "
    "SELECT RAISE(ABORT, 'audit_heads is append-only: a head only advances by one record to an existing hash'); END",
    "CREATE TRIGGER audit_heads_no_delete BEFORE DELETE ON audit_heads BEGIN "
    "SELECT RAISE(ABORT, 'audit_heads is append-only: DELETE refused'); END",
)

# (version, statements). Never edit a released migration: add a new one.
assert GENESIS_HASH == "0" * 64  # the genesis literal in the chain trigger above

MIGRATIONS: list[tuple[int, tuple[str, ...]]] = [(1, _TABLES + GUARD_STATEMENTS)]


class SqliteAuditStoreError(AuditError):
    """The store cannot be used or appended to safely (locked too long, broken chain, bad input)."""


def _norm(sql: str) -> str:
    return " ".join(sql.split())


def _trigger_name(statement: str) -> str:
    found = re.match(r"CREATE TRIGGER (\w+) ", statement)
    assert found is not None
    return found.group(1)


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def chain_for(client: str | None) -> str:
    """The chain a client's records go to: its own id when that is a safe client id, otherwise `_msp`."""
    return client if client is not None and valid_client_id(client) else MSP_LOG


def _utc_stamp(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise SqliteAuditStoreError("the clock returned a naive datetime; it must be timezone-aware")
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _default_clock() -> datetime:
    return datetime.now(UTC)


class SqliteAuditStore:
    """Drop-in for `AuditLog` / `AuditRouter` on `append`, plus read, verify, export and import."""

    def __init__(
        self,
        path: Path | str,
        *,
        clock: Clock | None = None,
        busy_timeout_s: float = BUSY_TIMEOUT_S,
        create: bool = True,
    ) -> None:
        self.path = Path(path).resolve()
        self.clock: Clock = clock or _default_clock
        self.busy_timeout_s = busy_timeout_s
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialise()
        else:
            if not self.path.is_file():
                raise SqliteAuditStoreError(f"no database at {self.path}")
            if self.schema_version() != MIGRATIONS[-1][0]:
                raise SqliteAuditStoreError(f"{self.path} is not at audit schema version {MIGRATIONS[-1][0]}")

    # -- connection, migrations ----------------------------------------------------------------

    def _initialise(self) -> None:
        deadline = time.monotonic() + self.busy_timeout_s
        while True:
            try:
                with closing(self._connect()) as con:
                    self._enable_wal(con)
                    self._migrate(con)
                return
            except sqlite3.OperationalError as exc:
                # Another process is creating or migrating the same file right now: wait and look again.
                if ("locked" not in str(exc) and "busy" not in str(exc)) or time.monotonic() > deadline:
                    raise
                time.sleep(0.05)

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
            raise SqliteAuditStoreError(f"could not switch the database to WAL mode (got {mode!r})")

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
                raise SqliteAuditStoreError(f"database is at audit schema {current}, this code knows {latest}")
            for version, statements in MIGRATIONS:
                if version > current:
                    for statement in statements:
                        con.execute(statement)
                    con.execute(
                        "INSERT INTO schema_migrations (component, version, applied_ms) VALUES (?, ?, ?)",
                        (COMPONENT, version, int(self.clock().timestamp() * 1000)),
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
                raise SqliteAuditStoreError(
                    f"audit database is locked; nothing written (failing closed): {exc}"
                ) from exc
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
        """One consistent snapshot (WAL read transaction)."""
        con = self._connect()
        try:
            con.execute("BEGIN")
            yield con
        finally:
            con.close()

    # -- writing --------------------------------------------------------------------------------

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
        """Append one v2 record to the client's chain and return it as written; same arguments as AuditLog.append.

        Odd values never stop a record (STD-AU-6), exactly as in the JSONL writer: an unknown mode is written as
        `invalid` with the raw value in `result.requested_mode`, an unknown event falls back to the mode's default,
        an unknown actor kind to `unknown`, a lever version that is not a positive integer to null.
        """
        written_mode: Mode = mode if mode in MODES else "invalid"
        if written_mode != mode:
            result = {**result, "requested_mode": str(mode)[:64]}
        written_event: Event = event if event in EVENTS else default_event(written_mode)
        written_kind: ActorKind = actor_kind if actor_kind in ACTOR_KINDS else "unknown"
        written_request = str(request_id)[:_ID_MAX] if request_id else (current_request_id() or new_request_id())
        chain = chain_for(client)
        stamp = _utc_stamp(self.clock())
        with self._write() as con:
            row = con.execute("SELECT seq, hash FROM audit_heads WHERE chain = ?", (chain,)).fetchone()
            last_seq, last_hash = (int(row[0]), str(row[1])) if row else (0, GENESIS_HASH)
            record: dict[str, Any] = {
                "v": RECORD_VERSION,
                "seq": last_seq + 1,
                "ts": stamp,
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
            self._insert(con, chain, record)
        return record

    def _insert(self, con: sqlite3.Connection, chain: str, record: dict[str, Any]) -> None:
        con.execute(
            "INSERT INTO audit_records (chain, seq, hash, prev_hash, line) VALUES (?, ?, ?, ?, ?)",
            (chain, record["seq"], record["hash"], record["prev_hash"], canonical_json(record).decode("utf-8")),
        )

    def import_jsonl(self, client: str | None, log: Path, head: Path | None = None) -> int:
        """Load an existing JSONL chain into an empty chain of this store, after verifying it. Returns the count.

        The JSONL verifier runs first (with the head pin, `head` or `<log>.head` when present); a log it rejects
        is refused whole. Every record must name this chain's client. Afterwards `append` continues the chain.
        """
        log = Path(log)
        if head is None and head_path_for(log).exists():
            head = head_path_for(log)
        chain = chain_for(client)
        try:
            checked = verify_chain(log, head)
            lines = log.read_bytes().splitlines()
        except OSError as exc:
            raise SqliteAuditStoreError(f"cannot read {log}: {exc}") from exc
        if not checked.ok:
            raise SqliteAuditStoreError(
                f"{log} is not an intact chain: broken at seq {checked.broken_seq}: {checked.reason}"
            )
        records = [json.loads(line) for line in lines]
        for record in records:
            if chain_for(record["client"]) != chain:
                raise SqliteAuditStoreError(f"record {record['seq']} of {log} does not belong to chain {chain!r}")
        with self._write() as con:
            if con.execute("SELECT 1 FROM audit_heads WHERE chain = ?", (chain,)).fetchone():
                raise SqliteAuditStoreError(f"chain {chain!r} already has records; import only fills an empty chain")
            for record in records:
                self._insert(con, chain, record)
        return len(records)

    # -- reading, verifying, exporting ------------------------------------------------------------

    def _snapshot(self, chain: str) -> tuple[list[str], tuple[int, str] | None]:
        with self._read() as con:
            lines = [r[0] for r in con.execute("SELECT line FROM audit_records WHERE chain = ? ORDER BY seq", (chain,))]
            row = con.execute("SELECT seq, hash FROM audit_heads WHERE chain = ?", (chain,)).fetchone()
        return lines, ((int(row[0]), str(row[1])) if row else None)

    def records(self, client: str | None) -> tuple[dict[str, Any], ...]:
        lines, _ = self._snapshot(chain_for(client))
        return tuple(json.loads(line) for line in lines)

    def head(self, client: str | None) -> tuple[int, str] | None:
        """The chain's (seq, hash) as the database holds it, or None for an empty chain. Pin this elsewhere."""
        return self._snapshot(chain_for(client))[1]

    def chains(self) -> list[str]:
        with self._read() as con:
            return sorted(str(r[0]) for r in con.execute("SELECT chain FROM audit_heads"))

    def schema_problems(self) -> list[str]:
        """Guard triggers that are missing or edited (empty list when all six are present and unchanged)."""
        with self._read() as con:
            found = {
                str(n): _norm(str(s))
                for n, s in con.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'")
            }
        problems = []
        for statement in GUARD_STATEMENTS:
            name = _trigger_name(statement)
            if name not in found:
                problems.append(f"guard trigger {name} is missing")
            elif found[name] != _norm(statement):
                problems.append(f"guard trigger {name} has been changed")
        return problems

    def verify(self, client: str | None, expected_head: tuple[int, str] | None = None) -> VerifyResult:
        """Verify one chain with the JSONL verifier, against the stored head and then `expected_head` if given.

        `expected_head` is a (seq, hash) pin kept outside this file. It may be older than the chain (the chain grew
        since): the chain must then contain that exact record. A chain that is intact but has lost its guard
        triggers is reported as broken: the file alone can no longer prove nothing was rewritten.
        """
        chain = chain_for(client)
        lines, head = self._snapshot(chain)
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / f"{chain}.jsonl"
            log.write_bytes(b"".join(line.encode("utf-8") + b"\n" for line in lines))
            head_file: Path | None = None
            if head is not None:
                head_file = head_path_for(log)
                head_file.write_text(json.dumps({"seq": head[0], "hash": head[1]}) + "\n", encoding="utf-8")
            elif lines:
                return VerifyResult(
                    False, len(lines), len(lines) + 1, f"chain {chain!r} has records but no stored head"
                )
            result = verify_chain(log, head_file) if head_file is not None else verify_chain(log, None)
        if not result.ok:
            return result
        count = result.records
        if expected_head is not None:
            pin_seq, pin_hash = expected_head
            if pin_seq > count:
                return _failed(result, count + 1, f"log ends at seq {count} but the head pins seq {pin_seq}")
            if pin_seq >= 1 and json.loads(lines[pin_seq - 1])["hash"] != pin_hash:
                return _failed(result, pin_seq, "the record at the pinned seq does not match the pinned hash")
            if pin_seq == 0 and count > 0 and pin_hash != GENESIS_HASH:
                return _failed(result, 1, "the pinned hash is not the genesis hash")
        problems = self.schema_problems()
        if problems:
            return _failed(result, None, "the append-only guard triggers are not intact: " + "; ".join(problems))
        return result

    def verify_all(self) -> dict[str, VerifyResult]:
        return {chain: self.verify(None if chain == MSP_LOG else chain) for chain in self.chains()}

    def export_chain(self, client: str, dest: Path) -> tuple[Path, Path]:
        """Write one client's chain and head pin into `dest` as `<client>.jsonl` and `.jsonl.head`; nothing else.

        The two files are what the JSONL store holds, so `python -m core.audit.verify` accepts them as they are.
        """
        if not valid_client_id(client):
            raise SqliteAuditStoreError(f"{client!r} is not a client id; nothing exported")
        lines, head = self._snapshot(client)
        if head is None:
            raise SqliteAuditStoreError(f"no audit chain for client {client!r}; nothing exported")
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        log_out = dest / f"{client}.jsonl"
        head_out = head_path_for(log_out)
        log_out.write_bytes(b"".join(line.encode("utf-8") + b"\n" for line in lines))
        head_out.write_text(json.dumps({"seq": head[0], "hash": head[1]}) + "\n", encoding="utf-8")
        return log_out, head_out

    # -- facts about the database ------------------------------------------------------------------

    def journal_mode(self) -> str:
        with closing(self._connect()) as con:
            return str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower()

    def schema_version(self) -> int:
        with closing(self._connect()) as con:
            try:
                row = con.execute(
                    "SELECT MAX(version) FROM schema_migrations WHERE component = ?", (COMPONENT,)
                ).fetchone()
            except sqlite3.OperationalError:
                return 0
        return int(row[0] or 0)

    def integrity_check(self) -> str:
        with closing(self._connect()) as con:
            return str(con.execute("PRAGMA integrity_check").fetchone()[0])


def _failed(base: VerifyResult, broken_seq: int | None, reason: str) -> VerifyResult:
    return VerifyResult(False, base.records, broken_seq, reason, base.v1_records, base.v2_records)


def _parse_pin(text: str) -> tuple[int, str]:
    seq, _, digest = text.partition(":")
    return int(seq), digest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.audit.sqlite_store", description="SQLite audit store tools.")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("verify", help="verify every chain (or one client's) in a database")
    check.add_argument("db", type=Path)
    check.add_argument("--client", default=None, help="verify only this client's chain")
    check.add_argument("--pin", default=None, help="<seq>:<hash> head pin kept outside the database (needs --client)")
    args = parser.parse_args(argv)

    if args.pin is not None and args.client is None:
        print("ERROR: --pin needs --client", file=sys.stderr)
        return 2
    try:
        store = SqliteAuditStore(args.db, create=False)
        pin = _parse_pin(args.pin) if args.pin is not None else None
        results = {args.client: store.verify(args.client, pin)} if args.client is not None else store.verify_all()
    except (OSError, ValueError, sqlite3.Error, AuditError) as exc:
        print(f"ERROR: cannot verify {args.db}: {exc}", file=sys.stderr)
        return 2
    code = 0
    for name, res in results.items():
        if res.ok:
            print(f"OK: {name}: {res.records} records, {res.reason}")
        else:
            code = 1
            print(f"BROKEN: {name} at seq {res.broken_seq}: {res.reason} ({res.records} records verified before it)")
    if not results:
        print("OK: no chains in this database")
    return code


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "GUARD_STATEMENTS",
    "MIGRATIONS",
    "SqliteAuditStore",
    "SqliteAuditStoreError",
    "chain_for",
    "main",
]
