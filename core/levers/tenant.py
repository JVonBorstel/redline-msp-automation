"""Mock tenant state: one synthetic JSON file per client (fixtures/tenant/<client>.json).

Users and their authentication methods are mock data shaped like Microsoft Graph v1.0;
tickets and KB articles are synthetic PSA and knowledge-base shapes. Nothing here talks to a
real tenant.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

DEFAULT_TENANT_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "tenant"
_CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_FAMILY = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")

JsonDict = dict[str, Any]


class TenantError(RuntimeError):
    """The client's mock tenant is missing, malformed or cannot be written."""


class MockTenant:
    def __init__(self, root: Path = DEFAULT_TENANT_DIR) -> None:
        self.root = Path(root)

    def path_for(self, client: str) -> Path:
        # The client id becomes a file name, so it must be a plain slug (no path traversal).
        if not _CLIENT_ID.fullmatch(client):
            raise TenantError(f"invalid client id {client!r}")
        return self.root / f"{client}.json"

    def load(self, client: str) -> JsonDict:
        path = self.path_for(client)
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise TenantError(f"no readable mock tenant for {client!r}: {exc}") from exc
        if not isinstance(state, dict):
            raise TenantError(f"mock tenant for {client!r} must be a JSON object")
        return state

    def load_for_read(self, client: str) -> JsonDict:
        """The client's state plus its family files under ``_families`` (B-39). For read levers only.

        Family files are ``<root>/<client>/<family>.json`` (B-19). Each must name this client in ``_meta.client``;
        one that does not fails the load. The runner never saves this view: a read lever that changes it is discarded.
        """
        state = self.load(client)
        folder = self.path_for(client).with_suffix("")
        families: JsonDict = {}
        if folder.is_dir():
            for path in sorted(folder.glob("*.json")):
                if not _FAMILY.fullmatch(path.stem):
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise TenantError(f"family state {path.stem!r} for {client!r} is not readable") from exc
                meta = data.get("_meta") if isinstance(data, dict) else None
                if not isinstance(meta, dict) or meta.get("client") != client:
                    raise TenantError(f"family state {path.stem!r} does not belong to {client!r}")
                families[path.stem] = data
        if families:
            state["_families"] = families
        return state

    def save(self, client: str, state: JsonDict) -> None:
        path = self.path_for(client)
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        try:
            tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            raise TenantError(f"cannot write mock tenant for {client!r}: {exc}") from exc
