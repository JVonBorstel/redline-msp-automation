"""Lever pause switch (kill switch): pause a lever for every client or for one client (C-31, IR-2).

A pause is a small JSON file (`pauses.json`) next to the audit log by default, so every runner that
writes to the same audit log (the CLI, the approval queue, the UI) sees the same pauses without
any extra wiring. The runner checks it on every call, dry-run or execute, before anything else
about the lever.

Fail closed: if the file exists but cannot be read or does not validate, `PauseStore.lookup`
raises `PauseError` and the runner denies the call. Writes replace the file atomically.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from core.levers.models import ClientId, LeverName

PAUSES_FILE = "pauses.json"
PAUSE_FILE_VERSION = 1
# A pause reason is one short line: it is shown in every denial and written to the audit log.
PauseReason = Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=r"^[^\r\n]+$")]


class PauseError(RuntimeError):
    """The pause file cannot be read or written; the runner treats that as paused (fail closed)."""


class Pause(BaseModel):
    """One active pause. `client` None means the lever is paused for every client."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lever: LeverName
    client: ClientId | None = None
    by: str = Field(min_length=1, max_length=64)
    reason: PauseReason
    at: AwareDatetime

    @property
    def scope(self) -> str:
        return "all clients" if self.client is None else f"client {self.client}"


class _PauseFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=PAUSE_FILE_VERSION, le=PAUSE_FILE_VERSION)
    pauses: list[Pause]


class PauseStore:
    """Active pauses, persisted as one JSON file. Thread-safe inside one process."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()
        self._lock = threading.Lock()

    @classmethod
    def beside(cls, audit_path: Path) -> PauseStore:
        """The default store: `pauses.json` in the same folder as the audit log."""
        return cls(Path(audit_path).resolve().with_name(PAUSES_FILE))

    def all(self) -> tuple[Pause, ...]:
        with self._lock:
            return tuple(self._read())

    def lookup(self, lever: str, client: str) -> Pause | None:
        """The pause that stops `lever` for `client`: a global pause wins over a client pause."""
        pauses = self.all()
        for pause in pauses:
            if pause.lever == lever and pause.client is None:
                return pause
        for pause in pauses:
            if pause.lever == lever and pause.client == client:
                return pause
        return None

    def exact(self, lever: str, client: str | None) -> Pause | None:
        """The pause recorded for exactly this lever and scope (global when `client` is None)."""
        return next((p for p in self.all() if p.lever == lever and p.client == client), None)

    def add(self, pause: Pause) -> None:
        with self._lock:
            kept = [p for p in self._read() if (p.lever, p.client) != (pause.lever, pause.client)]
            self._write([*kept, pause])

    def remove(self, lever: str, client: str | None) -> None:
        with self._lock:
            self._write([p for p in self._read() if (p.lever, p.client) != (lever, client)])

    # -- file -----------------------------------------------------------------------------

    def _read(self) -> list[Pause]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return _PauseFile.model_validate(raw).pauses
        except (OSError, ValueError, ValidationError) as exc:
            raise PauseError(f"pause file {self.path.name} is unreadable: {type(exc).__name__}") from exc

    def _write(self, pauses: list[Pause]) -> None:
        body = {"version": PAUSE_FILE_VERSION, "pauses": [p.model_dump(mode="json") for p in pauses]}
        tmp = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
            for attempt in range(5):  # a reader holding the file open on Windows makes replace fail briefly
                try:
                    os.replace(tmp, self.path)
                    return
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.02 * (attempt + 1))
        except OSError as exc:
            raise PauseError(f"cannot write pause file {self.path.name}: {type(exc).__name__}") from exc
