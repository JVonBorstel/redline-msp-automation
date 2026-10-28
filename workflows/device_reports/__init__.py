"""Device compliance, encryption and LAPS coverage reports and provisioning readiness (B-64). Read-only; per client.

report = build_client_report("contoso-dental")   # fixtures; status only, never a key or a password
written = write_report(report, out_dir)          # <client>/<date>.json and .md, each with a .sha256 sidecar
"""

from __future__ import annotations

from workflows.device_reports.reports import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_OUT_DIR,
    DEFAULT_OVERLAY_DIR,
    ReportConfig,
    ReportError,
    Written,
    build_client_report,
    find_secrets,
    load_config,
    render_markdown,
    verify,
    write_report,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_OUT_DIR",
    "DEFAULT_OVERLAY_DIR",
    "ReportConfig",
    "ReportError",
    "Written",
    "build_client_report",
    "find_secrets",
    "load_config",
    "render_markdown",
    "verify",
    "write_report",
]
