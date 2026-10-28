"""One audit chain per client, behind the same `append` as a single log (SL-01, B-42).

`AuditRouter(dir)` writes a client's records to `<dir>/<client>.jsonl` and everything else (MSP-level events such as
pausing every client, a record with no client, a client id that is not a safe file name) to `<dir>/_msp.jsonl`. Each
file is its own hash chain with its own head pin, so each verifies alone, and a client's chain exported alone holds
no other client's records. `_msp` cannot match the client id pattern, so a client can never collide with it, and a
hostile client id never becomes a file name.

Every append takes a cross-process file lock (`<log>.lock`) around `AuditLog.append`, so the web page, the CLI and a
workflow can write the same chain at once. If the lock cannot be had in time the append raises `AuditError`: the
caller sees a failure, never a silent skip. `file_lock` is also used by the approval queue and the review store.

`AuditRouter.path` is the MSP chain, so code that only needs "the audit folder" (`PauseStore.beside(audit.path)`)
keeps working: pauses live in the audit folder.
"""

from __future__ import annotations

import re
import shutil
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any

from core.audit.chain import (
    ActorKind,
    AuditError,
    AuditLog,
    Event,
    Mode,
    VerifyResult,
    head_path_for,
    verify_chain,
)

if sys.platform == "win32":
    import msvcrt

    def try_lock(fh: IO[bytes]) -> bool:
        """Take the OS lock on the open lock file without waiting; False when another process holds it."""
        fh.seek(0)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def unlock(fh: IO[bytes]) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def try_lock(fh: IO[bytes]) -> bool:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def unlock(fh: IO[bytes]) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


MSP_LOG = "_msp"
LOCK_TIMEOUT_S = 10.0
# The same shape as core.levers.models.ClientId (not imported: core.levers imports this package).
CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# Names Windows will not use as a file name, with or without an extension.
_RESERVED = frozenset(
    {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))}
)

_THREAD_LOCKS: dict[Path, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock(path: Path) -> threading.Lock:
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(path, threading.Lock())


@contextmanager
def file_lock(path: Path, timeout_s: float = LOCK_TIMEOUT_S) -> Iterator[None]:
    """Hold a cross-process lock for `path` (kept in `<path>.lock`); raise AuditError after `timeout_s`.

    A thread lock sits in front because the OS lock is per file handle on Windows: two threads of one process
    would otherwise spin on each other.
    """
    path = Path(path).resolve()
    lock_path = path.with_name(path.name + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_s
    guard = _thread_lock(path)
    if not guard.acquire(timeout=timeout_s):
        raise AuditError(f"{path.name} is locked by another thread; not written (failing closed)")
    try:
        with lock_path.open("a+b") as fh:
            while not try_lock(fh):
                if time.monotonic() > deadline:
                    raise AuditError(f"{path.name} is locked by another process; not written (failing closed)")
                time.sleep(0.02)
            try:
                yield
            finally:
                unlock(fh)
    finally:
        guard.release()


def valid_client_id(client: object) -> bool:
    """True when `client` is a client id that is safe to use as a file name."""
    return isinstance(client, str) and bool(CLIENT_ID.fullmatch(client)) and client not in _RESERVED


class AuditRouter:
    """Drop-in for `AuditLog` that keeps one chain per client plus one for the MSP."""

    def __init__(self, directory: Path, lock_timeout_s: float = LOCK_TIMEOUT_S) -> None:
        self.directory = Path(directory).resolve()
        self.lock_timeout_s = lock_timeout_s
        self._logs: dict[str, AuditLog] = {}
        self._guard = threading.Lock()

    @property
    def path(self) -> Path:
        """The MSP chain. Its folder is the audit folder (pauses and reviews live beside it)."""
        return self.directory / f"{MSP_LOG}.jsonl"

    def name_for(self, client: str | None) -> str:
        return client if client is not None and valid_client_id(client) else MSP_LOG

    def log_for(self, client: str | None) -> AuditLog:
        name = self.name_for(client)
        with self._guard:
            if name not in self._logs:
                self._logs[name] = AuditLog(self.directory / f"{name}.jsonl")
            return self._logs[name]

    def path_for(self, client: str | None) -> Path:
        return self.log_for(client).path

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
        """Append one record to the right chain under the cross-process lock; same arguments as AuditLog.append."""
        log = self.log_for(client)
        with file_lock(log.path, self.lock_timeout_s):
            return log.append(
                agent=agent,
                client=client,
                lever=lever,
                params=params,
                mode=mode,
                result=result,
                approver=approver,
                event=event,
                actor_kind=actor_kind,
                lever_version=lever_version,
                request_id=request_id,
            )

    # -- reading, verifying, exporting ------------------------------------------------------

    def client_paths(self) -> dict[str, Path]:
        """Every client chain on disk, by client id (the MSP chain is not in here)."""
        if not self.directory.is_dir():
            return {}
        return {
            item.stem: item
            for item in sorted(self.directory.glob("*.jsonl"))
            if item.is_file() and valid_client_id(item.stem)
        }

    def paths(self) -> dict[str, Path]:
        """Every chain on disk by name: the clients, plus `_msp` when it exists."""
        found: dict[str, Path] = dict(self.client_paths())
        if self.path.is_file():
            found[MSP_LOG] = self.path
        return found

    def verify_all(self) -> dict[str, VerifyResult]:
        """Verify each chain on its own against its own head pin."""
        out: dict[str, VerifyResult] = {}
        for name, chain in self.paths().items():
            head = head_path_for(chain)
            out[name] = verify_chain(chain, head if head.exists() else None)
        return out

    def export_client(self, client: str, dest: Path) -> tuple[Path, Path]:
        """Copy one client's chain and head pin into `dest`; nothing else. Returns (log, head)."""
        if not valid_client_id(client):
            raise AuditError(f"{client!r} is not a client id; nothing exported")
        source = self.path_for(client)
        if not source.is_file():
            raise AuditError(f"no audit chain for client {client!r}; nothing exported")
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        with file_lock(source, self.lock_timeout_s):
            log_out, head_out = dest / source.name, dest / head_path_for(source).name
            shutil.copyfile(source, log_out)
            head = head_path_for(source)
            if head.exists():
                shutil.copyfile(head, head_out)
        return log_out, head_out
