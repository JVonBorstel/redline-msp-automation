"""Backup levers on the mock tenant state (B-68). Mock only: no backup product is called.

``backup.retry-job`` records ONE retry request for a failed or missed backup job in the client's own state, under
``backupRetryRequests[<job id>]``. It does not look at job data: the workflow looks the job up in the client's own
backup adapter and checks it is failed or missed before it dry-runs this lever (STD-LV-9), and a real adapter would
re-check at the vendor. Asking twice for the same job changes nothing (STD-LV-6), so a repeated failure is one request.
The handler gets one client's state copy and validated params only (STD-LV-8); it never reads a file or another client.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.levers.handlers import LeverFailed
from core.levers.tenant import JsonDict


def backup_retry_job(state: JsonDict, params: Mapping[str, Any]) -> Any:
    """Record that a retry of ``job_id`` was asked for."""
    job_id = params["job_id"]
    requests = state.setdefault("backupRetryRequests", {})
    if not isinstance(requests, dict):
        raise LeverFailed("backup retry requests are in an unexpected shape")
    requests.setdefault(job_id, {"action": "retry", "status": "requested"})
    return {"job_id": job_id, "action": "retry"}
