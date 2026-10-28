"""RMM mock: serves one client's synthetic Datto-RMM-shaped fixture (fixtures/rmm/<client>.json).

Built for exactly one client from that client's ``rmm`` binding, whose ``external_id`` is the RMM site uid. The
fixture's ``client`` must equal the client and its ``site.uid`` the binding's ``external_id``, or construction is
refused (TEN-04). Every device, audit, alert and job is filtered by the bound site uid, so a record of another site is
never returned and is reported in the same words as an absent one.

Read-only: fixtures are never modified, every result is a deep copy, and there is no method that runs anything
(D6-26). Nothing here talks to a network. Field status: ``fixtures/rmm/SOURCES.md``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from adapters.base import AdapterError, AdapterResult
from adapters.binding import CLIENT_ID, BoundBinding
from adapters.rmm.base import Record, RmmAdapter
from core.paths import REPO_ROOT

DEFAULT_RMM_DIR = REPO_ROOT / "fixtures" / "rmm"

_NO_DEVICE = "no such RMM device for this client"
_NO_JOB = "no such RMM job for this client"


def _read(client: str, root: Path) -> dict[str, Any]:
    if not CLIENT_ID.fullmatch(client):
        raise AdapterError("invalid client id; adapter not built")
    try:
        data = json.loads((Path(root) / f"{client}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AdapterError(f"no readable RMM fixture for this client ({type(exc).__name__})") from exc
    if not isinstance(data, dict):
        raise AdapterError("RMM fixture must be a JSON object; adapter not built")
    return data


class RmmMock(RmmAdapter):
    def __init__(self, client: str, binding: BoundBinding, root: Path = DEFAULT_RMM_DIR) -> None:
        super().__init__(client, binding)
        if binding.implementation != "mock":
            raise AdapterError("RmmMock serves the 'mock' implementation only")
        data = _read(client, root)
        site = data.get("site")
        if not isinstance(site, dict) or data.get("client") != client or site.get("uid") != binding.external_id:
            raise AdapterError("RMM fixture does not belong to this client's site binding; adapter not built")
        self._data = data
        self._site_uid: str = binding.external_id

    @classmethod
    def for_fixture(cls, client: str, root: Path = DEFAULT_RMM_DIR) -> RmmMock:
        """Build from the fixture's own site uid (tests and the CLI; a real run uses the client's binding)."""
        data = _read(client, root)
        try:
            external = str(data["site"]["uid"])
        except (KeyError, TypeError) as exc:
            raise AdapterError(f"no readable RMM fixture for this client ({type(exc).__name__})") from exc
        return cls(client, BoundBinding(client, "rmm", "mock", external), root)

    @property
    def as_of(self) -> str:
        """The moment the fixture is pinned to (UTC ISO 8601). A mock-only convenience, not part of the interface."""
        return str(self._data["asOf"])

    def _devices(self) -> list[Record]:
        rows = self._data.get("devices", {}).get("devices", [])
        return [copy.deepcopy(r) for r in rows if isinstance(r, dict) and r.get("siteUid") == self._site_uid]

    def _device(self, device_uid: str) -> Record | None:
        return next((d for d in self._devices() if d.get("uid") == device_uid), None)

    def _jobs(self) -> list[Record]:
        rows = self._data.get("jobsBySite", {}).get(self._site_uid, [])
        return [copy.deepcopy(r) for r in rows if isinstance(r, dict)]

    def get_site(self) -> AdapterResult[Record]:
        return self._guard(lambda: AdapterResult.success(copy.deepcopy(self._data["site"])))

    def list_devices(self) -> AdapterResult[list[Record]]:
        return self._guard(lambda: AdapterResult.success(sorted(self._devices(), key=lambda d: str(d.get("uid")))))

    def get_device(self, device_uid: str) -> AdapterResult[Record]:
        def run() -> AdapterResult[Record]:
            device = self._device(device_uid)
            return AdapterResult.failure(_NO_DEVICE) if device is None else AdapterResult.success(device)

        return self._guard(run)

    def get_device_audit(self, device_uid: str) -> AdapterResult[Record]:
        def run() -> AdapterResult[Record]:
            if self._device(device_uid) is None:  # another site's device: same words as an absent one
                return AdapterResult.failure(_NO_DEVICE)
            audit = self._data.get("deviceAudits", {}).get(device_uid)
            if not isinstance(audit, dict):
                return AdapterResult.failure("no audit for this RMM device")
            return AdapterResult.success(copy.deepcopy(audit))

        return self._guard(run)

    def list_open_alerts(self) -> AdapterResult[list[Record]]:
        def run() -> AdapterResult[list[Record]]:
            rows = self._data.get("alerts", {}).get("alerts", [])
            mine = [
                copy.deepcopy(a)
                for a in rows
                if isinstance(a, dict)
                and (a.get("alertSourceInfo") or {}).get("siteUid") == self._site_uid
                and not a.get("resolved")
            ]
            return AdapterResult.success(sorted(mine, key=lambda a: str(a.get("alertUid"))))

        return self._guard(run)

    def list_jobs(self) -> AdapterResult[list[Record]]:
        return self._guard(lambda: AdapterResult.success(sorted(self._jobs(), key=lambda j: str(j.get("uid")))))

    def get_job(self, job_uid: str) -> AdapterResult[Record]:
        def run() -> AdapterResult[Record]:
            job = next((j for j in self._jobs() if j.get("uid") == job_uid), None)
            return AdapterResult.failure(_NO_JOB) if job is None else AdapterResult.success(job)

        return self._guard(run)

    def list_components(self) -> AdapterResult[list[Record]]:
        def run() -> AdapterResult[list[Record]]:
            rows = self._data.get("components", {}).get("components", [])
            return AdapterResult.success(sorted((copy.deepcopy(c) for c in rows), key=lambda c: str(c.get("uid"))))

        return self._guard(run)
