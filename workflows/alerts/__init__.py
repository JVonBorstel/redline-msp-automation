"""Security-alert grouping and the after-hours on-call summary (B-43). Groups and suggests; never acts on an alert.

pool = pool_from_adapter(adapter); summary = build_summary("contoso-dental", pool.alerts, load_config())
"""

from workflows.alerts.alerts import (
    DEFAULT_CONFIG_PATH,
    AlertGroup,
    AlertsConfig,
    AlertsError,
    BusinessHours,
    Pool,
    build_summary,
    group_alerts,
    group_type_of,
    is_after_hours,
    load_config,
    pool_for,
    pool_from_adapter,
    render_text,
    utc,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "AlertGroup",
    "AlertsConfig",
    "AlertsError",
    "BusinessHours",
    "Pool",
    "build_summary",
    "group_alerts",
    "group_type_of",
    "is_after_hours",
    "load_config",
    "pool_for",
    "pool_from_adapter",
    "render_text",
    "utc",
]
