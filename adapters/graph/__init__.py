"""Graph (Microsoft 365) adapters: the interface, the mock and the builder."""

from __future__ import annotations

from pathlib import Path

from adapters import BuildResult
from adapters.base import REAL_ADAPTER_NOT_CONFIGURED, AdapterError
from adapters.binding import DEFAULT_CLIENT_DIR, ClientConfigError, bound_binding, load_client
from adapters.graph.base import GraphAdapter
from adapters.graph.mock import GraphMock


def build_graph_adapter(
    client: str,
    *,
    config_dir: Path = DEFAULT_CLIENT_DIR,
    tenant_dir: Path | None = None,
) -> BuildResult:
    """Build the Graph adapter for ``client`` from its ``m365`` binding. Never raises; fails closed."""
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
        adapter = GraphMock(client, binding) if tenant_dir is None else GraphMock(client, binding, tenant_dir)
    except AdapterError as exc:
        return BuildResult(False, str(exc))
    return BuildResult(True, "ok", adapter)


__all__ = ["GraphAdapter", "GraphMock", "build_graph_adapter"]
