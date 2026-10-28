"""Intune adapters: the vendor-neutral interface, the mock and the builder (B-61)."""

from __future__ import annotations

from pathlib import Path

from adapters import BuildResult
from adapters.base import REAL_ADAPTER_NOT_CONFIGURED, AdapterError
from adapters.binding import DEFAULT_CLIENT_DIR, ClientConfigError, bound_binding, load_client
from adapters.intune.base import IntuneAdapter
from adapters.intune.mock import DEFAULT_INTUNE_DIR, IntuneMock


def build_intune_adapter(
    client: str,
    *,
    config_dir: Path = DEFAULT_CLIENT_DIR,
    fixtures_dir: Path = DEFAULT_INTUNE_DIR,
) -> BuildResult:
    """Build the Intune adapter for ``client`` from its ``m365`` binding. Never raises; fails closed (B61-3)."""
    try:
        cfg = load_client(client, config_dir)
    except ClientConfigError as exc:
        return BuildResult(False, str(exc))
    binding = bound_binding(cfg, "m365")
    if binding is None:
        return BuildResult(False, "client has no 'm365' binding")
    if binding.implementation != "mock":
        return BuildResult(False, REAL_ADAPTER_NOT_CONFIGURED)
    try:
        return BuildResult(True, "ok", IntuneMock(client, binding, fixtures_dir))
    except AdapterError as exc:
        return BuildResult(False, str(exc))


__all__ = ["DEFAULT_INTUNE_DIR", "IntuneAdapter", "IntuneMock", "build_intune_adapter"]
