"""Restorable-item catalog mock for one client (B-69; workflows/restore_tests/catalog/<client>.json).

This stands for "what the backup product holds that can be restored": files, mailbox items and VMs, each with the
SHA-256 recorded when it was backed up. It is built on that client's ``BackupAdapter`` (B-68): the organization id comes
from the adapter, every item of another organization is dropped and answered like an absent one (TEN-04), and an item
is restorable only when the backup job it came from is a job of this client that finished with status ``success``.

``restore`` copies an item's bytes into a caller-owned dictionary standing for the alternate location. Nothing is
written to disk and the fixtures are never modified. Field names are UNVERIFIED (``catalog/SOURCES.md``). Every
method returns an ``AdapterResult`` and never raises (STD-ER-1).
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from adapters.backup import BackupAdapter, BackupMock
from adapters.base import AdapterError, AdapterResult
from adapters.binding import CLIENT_ID
from core.paths import REPO_ROOT

Record = dict[str, Any]
ITEM_KINDS: tuple[str, ...] = ("file", "mailbox-item", "vm")
DEFAULT_CATALOG_DIR = REPO_ROOT / "workflows" / "restore_tests" / "catalog"
NO_SUCH_ITEM = "no such restorable item for this client"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RestoreCatalog:
    def __init__(self, adapter: BackupAdapter, root: Path = DEFAULT_CATALOG_DIR) -> None:
        client = adapter.client
        if not CLIENT_ID.fullmatch(client):
            raise AdapterError("invalid client id; catalog not built")
        org = adapter.get_organization()
        if not org.ok or org.data is None:
            raise AdapterError("the backup adapter has no organization; catalog not built")
        path = Path(root) / f"{client}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AdapterError(f"no readable restore catalog for this client ({type(exc).__name__})") from exc
        if not isinstance(data, dict) or data.get("client") != client or data.get("organizationId") != org.data["id"]:
            raise AdapterError("restore catalog does not belong to this client's backup organization; not built")
        self._adapter = adapter
        self._data: dict[str, Any] = data
        self._org_id: Any = org.data["id"]
        self._path = path

    @classmethod
    def for_fixture(
        cls, client: str, root: Path = DEFAULT_CATALOG_DIR, backup_root: Path | None = None
    ) -> RestoreCatalog:
        """Build on the client's backup mock (tests and the CLI; a real run uses the client's binding)."""

        adapter = BackupMock.for_fixture(client) if backup_root is None else BackupMock.for_fixture(client, backup_root)
        return cls(adapter, root)

    @property
    def client(self) -> str:
        return self._adapter.client

    @property
    def as_of(self) -> str:
        return str(self._data["asOf"])

    @property
    def source_sha256(self) -> str:
        """SHA-256 of the catalog file as read from disk, so evidence can say which catalog it was run against."""
        return sha256_hex(self._path.read_bytes())

    def _mine(self) -> list[Record]:
        rows = self._data.get("items", [])
        return [copy.deepcopy(r) for r in rows if isinstance(r, dict) and r.get("organizationId") == self._org_id]

    def items(self) -> AdapterResult[list[Record]]:
        """Every item of the bound organization, ordered by id. The bytes stay in the catalog: see ``restore``."""

        def run() -> AdapterResult[list[Record]]:
            rows = [{k: v for k, v in r.items() if k != "content"} for r in self._mine()]
            rows.sort(key=lambda r: str(r.get("id")))
            return AdapterResult.success(rows)

        return self._adapter._guard(run)

    def get_item(self, item_id: str) -> AdapterResult[Record]:
        def run() -> AdapterResult[Record]:
            for row in self._mine():
                if row.get("id") == item_id:
                    row.pop("content", None)
                    return AdapterResult.success(row)
            return AdapterResult.failure(NO_SUCH_ITEM)  # absent or another client's: same words

        return self._adapter._guard(run)

    def restorable(self, item_id: str) -> AdapterResult[Record]:
        """The item, if its backup job is one of this client's jobs and finished with status ``success``."""

        def run() -> AdapterResult[Record]:
            found = self.get_item(item_id)
            if not found.ok or found.data is None:
                return found
            if found.data.get("kind") not in ITEM_KINDS:
                return AdapterResult.failure("the item has a kind this catalog does not restore")
            job = self._adapter.get_job(str(found.data.get("sourceJobId")))
            if not job.ok or job.data is None:
                return AdapterResult.failure("the item's backup job is not a job of this client")
            if job.data.get("status") != "success":
                return AdapterResult.failure("not restorable: the backup job it came from did not finish successfully")
            return found

        return self._adapter._guard(run)

    def restorable_ids(self) -> list[str]:
        rows = self.items().data or []
        return [str(r["id"]) for r in rows if self.restorable(str(r["id"])).ok]

    def restore(self, item_id: str, location: str, sink: dict[str, bytes]) -> AdapterResult[Record]:
        """Mock restore: copy the item's bytes into ``sink[location]``. Never the item's original location."""

        def run() -> AdapterResult[Record]:
            found = self.restorable(item_id)
            if not found.ok or found.data is None:
                return AdapterResult.failure(found.reason)
            if not location.startswith("ALT-") or location == found.data.get("originalLocation"):
                return AdapterResult.failure(
                    "only an alternate location is restored to; the original is never overwritten"
                )
            content = next((r.get("content") for r in self._mine() if r.get("id") == item_id), None)
            if not isinstance(content, str):
                return AdapterResult.failure("the item has no content to restore")
            data = content.encode("utf-8")
            sink[location] = data
            return AdapterResult.success({"item_id": item_id, "location": location, "bytes": len(data)})

        return self._adapter._guard(run)
