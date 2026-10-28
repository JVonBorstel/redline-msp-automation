"""Device reconciliation across RMM, Intune and PSA assets (B-61). Read-only; one client per run.

rec = reconcile(RmmMock.for_fixture(c), IntuneMock.for_fixture(c), PsaAssetsMock.for_fixture(c), as_of, load_config())
"""

from __future__ import annotations

from workflows.device_reconcile.psa_assets import (
    DEFAULT_PSA_ASSETS_DIR,
    PsaAssetsMock,
    build_psa_assets,
)
from workflows.device_reconcile.reconcile import (
    DEFAULT_CONFIG_PATH,
    MISMATCH_TYPES,
    NOT_RUN,
    SYSTEMS,
    Device,
    DeviceRecord,
    Finding,
    ReconcileConfig,
    ReconcileError,
    Reconciliation,
    Sources,
    SourcesResult,
    build_sources,
    collect,
    component_inventory,
    findings,
    load_config,
    match,
    norm_name,
    norm_serial,
    reconcile,
    summary,
    utc,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_PSA_ASSETS_DIR",
    "MISMATCH_TYPES",
    "NOT_RUN",
    "SYSTEMS",
    "Device",
    "DeviceRecord",
    "Finding",
    "PsaAssetsMock",
    "ReconcileConfig",
    "ReconcileError",
    "Reconciliation",
    "Sources",
    "SourcesResult",
    "build_psa_assets",
    "build_sources",
    "collect",
    "component_inventory",
    "findings",
    "load_config",
    "match",
    "norm_name",
    "norm_serial",
    "reconcile",
    "summary",
    "utc",
]
