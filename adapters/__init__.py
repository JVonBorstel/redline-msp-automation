"""Adapters: one instance per client, built from that client's binding (TEN-04). Mock only; synthetic data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from adapters.base import REAL_ADAPTER_NOT_CONFIGURED, Adapter, AdapterError, AdapterResult
from adapters.binding import (
    DEFAULT_CLIENT_DIR,
    BoundBinding,
    ClientConfig,
    ClientConfigError,
    bound_binding,
    load_client,
)
from adapters.psa import PsaAdapter, PsaMock


@dataclass(frozen=True, slots=True)
class BuildResult:
    """Outcome of ``build_adapter`` (STD-ER-1): never raises; ``adapter`` is set only when ``ok``."""

    ok: bool
    reason: str
    adapter: Adapter | None = None


def build_adapter(
    client: str,
    system: str,
    *,
    config_dir: Path = DEFAULT_CLIENT_DIR,
    fixtures_dir: Path | None = None,
) -> BuildResult:
    """Build the adapter for ``client`` and ``system`` from config/clients/<client>.json.

    Fails closed: an invalid config, a missing binding, a system with no adapter yet, or any implementation
    other than ``mock`` returns ``ok=False`` (real ones say ``real adapter not configured``).
    """
    try:
        cfg = load_client(client, config_dir)
    except ClientConfigError as exc:
        return BuildResult(False, str(exc))
    binding = bound_binding(cfg, system)
    if binding is None:
        return BuildResult(False, f"client has no {system!r} binding")
    if binding.implementation != "mock":
        return BuildResult(False, REAL_ADAPTER_NOT_CONFIGURED)
    if system != "psa":
        return BuildResult(False, f"no {system!r} adapter yet")
    try:
        adapter = PsaMock(client, binding) if fixtures_dir is None else PsaMock(client, binding, fixtures_dir)
    except AdapterError as exc:
        return BuildResult(False, str(exc))
    return BuildResult(True, "ok", adapter)


__all__ = [
    "REAL_ADAPTER_NOT_CONFIGURED",
    "Adapter",
    "AdapterError",
    "AdapterResult",
    "BoundBinding",
    "BuildResult",
    "ClientConfig",
    "ClientConfigError",
    "PsaAdapter",
    "PsaMock",
    "bound_binding",
    "build_adapter",
    "load_client",
]
