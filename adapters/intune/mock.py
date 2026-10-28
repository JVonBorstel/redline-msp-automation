"""Intune mock: serves one client's synthetic managedDevice list (fixtures/intune/<client>.json).

Built for exactly one client from that client's ``m365`` binding. The fixture's ``client`` must equal the client and its
``tenantId`` the binding's ``external_id`` (the tenant GUID), or construction is refused (TEN-04). The file path is
built from this adapter's own client id only (STD-ID-4), so another client's file is never opened.

Read-only: fixtures are never modified and every result is a deep copy. Nothing here talks to a network.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from adapters.base import AdapterError, AdapterResult
from adapters.binding import CLIENT_ID, BoundBinding
from adapters.intune.base import IntuneAdapter, Record
from core.paths import REPO_ROOT

DEFAULT_INTUNE_DIR = REPO_ROOT / "fixtures" / "intune"


def _read(client: str, root: Path) -> dict[str, Any]:
    if not CLIENT_ID.fullmatch(client):
        raise AdapterError("invalid client id; adapter not built")
    try:
        data = json.loads((Path(root) / f"{client}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AdapterError(f"no readable Intune fixture for this client ({type(exc).__name__})") from exc
    if not isinstance(data, dict):
        raise AdapterError("Intune fixture must be a JSON object; adapter not built")
    return data


class IntuneMock(IntuneAdapter):
    def __init__(self, client: str, binding: BoundBinding, root: Path = DEFAULT_INTUNE_DIR) -> None:
        super().__init__(client, binding)
        if binding.implementation != "mock":
            raise AdapterError("IntuneMock serves the 'mock' implementation only")
        data = _read(client, root)
        if data.get("client") != client or data.get("tenantId") != binding.external_id:
            raise AdapterError("Intune fixture does not belong to this client's tenant binding; adapter not built")
        self._data = data

    @classmethod
    def for_fixture(cls, client: str, root: Path = DEFAULT_INTUNE_DIR) -> IntuneMock:
        """Build from the fixture's own tenant id (tests and the CLI; a real run uses the client's binding)."""
        data = _read(client, root)
        return cls(client, BoundBinding(client, "m365", "mock", str(data.get("tenantId"))), root)

    @property
    def as_of(self) -> str:
        """The moment the fixture is pinned to (UTC ISO 8601). A mock-only convenience, not part of the interface."""
        return str(self._data["asOf"])

    def _devices(self) -> list[Record]:
        rows = self._data.get("managedDevices", {}).get("value", [])
        return [copy.deepcopy(r) for r in rows if isinstance(r, dict)]

    def list_managed_devices(self) -> AdapterResult[list[Record]]:
        return self._guard(lambda: AdapterResult.success(sorted(self._devices(), key=lambda d: str(d.get("id")))))

    def get_managed_device(self, device_id: str) -> AdapterResult[Record]:
        def run() -> AdapterResult[Record]:
            device = next((d for d in self._devices() if d.get("id") == device_id), None)
            if device is None:
                return AdapterResult.failure("no such Intune device for this client")
            return AdapterResult.success(device)

        return self._guard(run)
