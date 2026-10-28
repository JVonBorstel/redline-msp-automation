"""Graph mock: serves one client's synthetic tenant state, base file plus optional per-family files.

Reads ``fixtures/tenant/<client>.json`` (the file the lever runner loads and saves) and, for a lever family
that brings its own data, ``fixtures/tenant/<client>/<family>.json`` (B19-1). Both files must name this client
in ``_meta.client`` (STD-FX-3); a family file that names another client is refused, and the other client's
directory is never opened, because the path is built from this adapter's own client id only (STD-ID-4).

State is re-read from disk on every call, so a change the runner saved is visible at once. Every result is a
deep copy; this module never writes a file (B19-2): writes belong to the runner's diff-and-save path (SL-04).
Synthetic data only; nothing here talks to a network.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from adapters.base import AdapterError, AdapterResult
from adapters.binding import BoundBinding
from adapters.graph.base import FAMILY, GraphAdapter, Record
from core.levers.tenant import DEFAULT_TENANT_DIR, MockTenant, TenantError

_NO_USER = "no such user for this client"


class GraphMock(GraphAdapter):
    def __init__(self, client: str, binding: BoundBinding, root: Path = DEFAULT_TENANT_DIR) -> None:
        super().__init__(client, binding)
        if binding.implementation != "mock":
            raise AdapterError("GraphMock serves the 'mock' implementation only")
        self._store = MockTenant(root)
        try:
            self._base_path = self._store.path_for(client)  # the one resolver; rejects non-slugs
        except TenantError as exc:
            raise AdapterError("invalid client id; adapter not built") from exc
        try:
            base = self._store.load(client)
        except TenantError as exc:
            raise AdapterError("no readable tenant state for this client; adapter not built") from exc
        self._check_owner(base)
        meta = base.get("_meta")
        tenant_id = meta.get("tenantId") if isinstance(meta, dict) else None
        if tenant_id is not None and tenant_id != binding.external_id:
            raise AdapterError("tenant state does not belong to this client's tenant binding; adapter not built")
        self._family_dir = self._base_path.with_suffix("")

    def _check_owner(self, data: Any) -> None:
        meta = data.get("_meta") if isinstance(data, dict) else None
        if not isinstance(meta, dict) or meta.get("client") != self._client:
            raise AdapterError("tenant state does not belong to this client; adapter not built")

    def _base(self) -> Record:
        data = self._store.load(self._client)
        self._check_owner(data)
        return data

    # -- interface -------------------------------------------------------------------------------------------
    def state(self) -> AdapterResult[Record]:
        return self._guard(lambda: AdapterResult.success(copy.deepcopy(self._base())))

    def families(self) -> AdapterResult[list[str]]:
        def run() -> AdapterResult[list[str]]:
            if not self._family_dir.is_dir():
                return AdapterResult.success([])
            names = sorted(p.stem for p in self._family_dir.glob("*.json") if FAMILY.fullmatch(p.stem))
            return AdapterResult.success(names)

        return self._guard(run)

    def family_state(self, family: str) -> AdapterResult[Record]:
        def run() -> AdapterResult[Record]:
            if not FAMILY.fullmatch(family):
                return AdapterResult.failure("invalid family name")
            path = self._family_dir / f"{family}.json"
            if not path.is_file():
                return AdapterResult.failure("no such family state for this client")
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return AdapterResult.failure("family state is not readable")
            meta = data.get("_meta") if isinstance(data, dict) else None
            if not isinstance(meta, dict) or meta.get("client") != self._client:
                return AdapterResult.failure("family state does not belong to this client")
            return AdapterResult.success(data)  # freshly parsed here, so already a private copy

        return self._guard(run)

    def _users(self) -> list[Record]:
        users = self._base().get("users", [])
        return users if isinstance(users, list) else []

    def _find(self, user: str) -> Record | None:
        needle = user.lower()
        for u in self._users():
            if needle in (str(u.get("id", "")).lower(), str(u.get("userPrincipalName", "")).lower()):
                return u
        return None

    def list_users(self) -> AdapterResult[list[Record]]:
        return self._guard(lambda: AdapterResult.success(copy.deepcopy(self._users())))

    def get_user(self, user: str) -> AdapterResult[Record]:
        def run() -> AdapterResult[Record]:
            found = self._find(user)
            if found is None:  # same words for "absent" and "another client's": no existence oracle
                return AdapterResult.failure(_NO_USER)
            return AdapterResult.success(copy.deepcopy(found))

        return self._guard(run)

    def list_authentication_methods(self, user: str) -> AdapterResult[list[Record]]:
        def run() -> AdapterResult[list[Record]]:
            found = self._find(user)
            if found is None:
                return AdapterResult.failure(_NO_USER)
            methods = (found.get("authentication") or {}).get("methods", [])
            return AdapterResult.success(copy.deepcopy(methods))

        return self._guard(run)
