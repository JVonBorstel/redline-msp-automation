"""Backup mock: serves one client's synthetic backup fixture (fixtures/backup/<client>.json).

Built for exactly one client from that client's backup binding. The fixture's organization id must equal the binding's
``external_id`` or construction is refused (TEN-04). Every record is filtered by the bound organization id, so a job
that belongs to another organization is never returned and is reported in the same words as an absent one. Read-only;
fixtures are never modified. Field names are UNVERIFIED (``fixtures/backup/SOURCES.md``).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from adapters.backup.base import JOB_TYPES, BackupAdapter, Record
from adapters.base import AdapterError, AdapterResult
from adapters.binding import CLIENT_ID, BoundBinding
from core.paths import REPO_ROOT

DEFAULT_BACKUP_DIR = REPO_ROOT / "fixtures" / "backup"


class BackupMock(BackupAdapter):
    def __init__(self, client: str, binding: BoundBinding, root: Path = DEFAULT_BACKUP_DIR) -> None:
        super().__init__(client, binding)
        if binding.implementation != "mock":
            raise AdapterError("BackupMock serves the 'mock' implementation only")
        if not CLIENT_ID.fullmatch(client):
            raise AdapterError("invalid client id; adapter not built")
        path = Path(root) / f"{client}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AdapterError(f"no readable backup fixture for this client ({type(exc).__name__})") from exc
        org = data.get("organization") if isinstance(data, dict) else None
        if not isinstance(org, dict) or data.get("client") != client or str(org.get("id")) != binding.external_id:
            raise AdapterError(
                "backup fixture does not belong to this client's organization binding; adapter not built"
            )
        self._data: dict[str, Any] = data
        self._org_id: Any = org["id"]

    @classmethod
    def for_fixture(cls, client: str, root: Path = DEFAULT_BACKUP_DIR) -> BackupMock:
        """Build from the fixture's own organization id (tests and the CLI; a real run uses the client's binding)."""
        if not CLIENT_ID.fullmatch(client):
            raise AdapterError("invalid client id; adapter not built")
        try:
            data = json.loads((Path(root) / f"{client}.json").read_text(encoding="utf-8"))
            external = str(data["organization"]["id"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise AdapterError(f"no readable backup fixture for this client ({type(exc).__name__})") from exc
        return cls(client, BoundBinding(client, "backup", "mock", external), root)

    @property
    def as_of(self) -> str:
        """The moment the fixture is pinned to (UTC ISO 8601). A mock-only convenience, not part of the interface."""
        return str(self._data["asOf"])

    def get_organization(self) -> AdapterResult[Record]:
        return self._guard(lambda: AdapterResult.success(copy.deepcopy(self._data["organization"])))

    def _mine(self) -> list[Record]:
        rows = self._data.get("jobs", [])
        return [copy.deepcopy(r) for r in rows if r.get("organizationId") == self._org_id]

    def list_jobs(self, job_type: str | None = None) -> AdapterResult[list[Record]]:
        def run() -> AdapterResult[list[Record]]:
            if job_type is not None and job_type not in JOB_TYPES:
                return AdapterResult.failure("unknown job type")
            rows = [r for r in self._mine() if job_type is None or r.get("jobType") == job_type]
            rows.sort(key=lambda r: (str(r.get("scheduledStart")), str(r.get("id"))))
            return AdapterResult.success(rows)

        return self._guard(run)

    def get_job(self, job_id: str) -> AdapterResult[Record]:
        def run() -> AdapterResult[Record]:
            for job in self._mine():
                if job.get("id") == job_id:
                    return AdapterResult.success(job)
            return AdapterResult.failure("no such backup job for this client")  # absent or another client's: same words

        return self._guard(run)
