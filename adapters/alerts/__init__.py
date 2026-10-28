"""Security-alert adapters: the vendor-neutral interface and the mock (B-43). Synthetic data only."""

from __future__ import annotations

from adapters.alerts.base import (
    SEVERITY_ORDER,
    SOURCE_TYPES,
    Alert,
    AlertsAdapter,
    EntityKind,
    Severity,
    SourceType,
)
from adapters.alerts.mock import DEFAULT_ALERTS_DIR, AlertsMock

__all__ = [
    "DEFAULT_ALERTS_DIR",
    "SEVERITY_ORDER",
    "SOURCE_TYPES",
    "Alert",
    "AlertsAdapter",
    "AlertsMock",
    "EntityKind",
    "Severity",
    "SourceType",
]
