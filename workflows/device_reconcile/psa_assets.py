"""PSA asset reader for device reconciliation: one client's Autotask-shaped ConfigurationItems (B-61).

``adapters/psa`` (B-18) has no asset method yet and ``fixtures/psa/`` is not B-61's to change, so the PSA side of the
reconciliation is read here, through the same one-client adapter base: ``PsaAssetsMock`` is built for one client from
that client's ``psa`` binding (``external_id`` = the PSA company id), refuses a fixture of another client or company at
construction (TEN-04), and drops any item whose ``companyID`` is not the bound company. When the PSA adapter gains a
configuration-item read, this module is replaced by it. Read-only; synthetic data only; no network.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from adapters import BuildResult
from adapters.base import REAL_ADAPTER_NOT_CONFIGURED, Adapter, AdapterError, AdapterResult
from adapters.binding import CLIENT_ID, DEFAULT_CLIENT_DIR, BoundBinding, ClientConfigError, bound_binding, load_client

Record = dict[str, Any]
DEFAULT_PSA_ASSETS_DIR = Path(__file__).with_name("psa_assets")


def _read(client: str, root: Path) -> dict[str, Any]:
    if not CLIENT_ID.fullmatch(client):
        raise AdapterError("invalid client id; adapter not built")
    try:
        data = json.loads((Path(root) / f"{client}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AdapterError(f"no readable PSA asset fixture for this client ({type(exc).__name__})") from exc
    if not isinstance(data, dict):
        raise AdapterError("PSA asset fixture must be a JSON object; adapter not built")
    return data


class PsaAssetsMock(Adapter):
    system = "psa"

    def __init__(self, client: str, binding: BoundBinding, root: Path = DEFAULT_PSA_ASSETS_DIR) -> None:
        super().__init__(client, binding)
        if binding.implementation != "mock":
            raise AdapterError("PsaAssetsMock serves the 'mock' implementation only")
        data = _read(client, root)
        if data.get("client") != client or str(data.get("companyID")) != binding.external_id:
            raise AdapterError("PSA asset fixture does not belong to this client's company binding; adapter not built")
        self._data = data
        self._company: Any = data["companyID"]

    @classmethod
    def for_fixture(cls, client: str, root: Path = DEFAULT_PSA_ASSETS_DIR) -> PsaAssetsMock:
        """Build from the fixture's own company id (tests and the CLI; a real run uses the client's binding)."""
        data = _read(client, root)
        return cls(client, BoundBinding(client, "psa", "mock", str(data.get("companyID"))), root)

    @property
    def company_id(self) -> str:
        return str(self._company)

    def list_configuration_items(self) -> AdapterResult[list[Record]]:
        """Every configuration item of the bound company, by id (``GET /ConfigurationItems/query``)."""

        def run() -> AdapterResult[list[Record]]:
            rows = self._data.get("configurationItems", {}).get("items", [])
            mine = [copy.deepcopy(r) for r in rows if isinstance(r, dict) and r.get("companyID") == self._company]
            return AdapterResult.success(sorted(mine, key=lambda r: int(r.get("id", 0))))

        return self._guard(run)


def build_psa_assets(
    client: str, *, config_dir: Path = DEFAULT_CLIENT_DIR, fixtures_dir: Path = DEFAULT_PSA_ASSETS_DIR
) -> BuildResult:
    """Build the PSA asset reader for ``client`` from its ``psa`` binding. Never raises; fails closed (B61-3)."""
    try:
        cfg = load_client(client, config_dir)
    except ClientConfigError as exc:
        return BuildResult(False, str(exc))
    binding = bound_binding(cfg, "psa")
    if binding is None:
        return BuildResult(False, "client has no 'psa' binding")
    if binding.implementation != "mock":
        return BuildResult(False, REAL_ADAPTER_NOT_CONFIGURED)
    try:
        return BuildResult(True, "ok", PsaAssetsMock(client, binding, fixtures_dir))
    except AdapterError as exc:
        return BuildResult(False, str(exc))
