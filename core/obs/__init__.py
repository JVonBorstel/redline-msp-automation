"""Operational logging (B-83): content-free JSON log lines and the request scope that correlates them.

See ``core.obs.logs`` for what a line may hold and ``core.obs.context`` for the request id.
"""

from core.obs.context import current_client, current_request_id, is_safe_request_id, new_scope_id, request_scope
from core.obs.logs import (
    LOGGER_NAME,
    ContentFreeFilter,
    JsonLineFormatter,
    OpsLogger,
    Span,
    check_line,
    configure,
    sanitize_record,
    unconfigure,
)

__all__ = [
    "LOGGER_NAME",
    "ContentFreeFilter",
    "JsonLineFormatter",
    "OpsLogger",
    "Span",
    "check_line",
    "configure",
    "current_client",
    "current_request_id",
    "is_safe_request_id",
    "new_scope_id",
    "request_scope",
    "sanitize_record",
    "unconfigure",
]
