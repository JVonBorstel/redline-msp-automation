"""Sign-in log read lever on the mock tenant's ``signins`` family file (B-39). Mock only.

``signins.list`` returns one user's newest sign-ins. The runner hands a read lever the client's state plus that client's
own family files under ``_families`` (``MockTenant.load_for_read``), so the handler sees one client's data only and
needs no path or identity (STD-LV-8). The user must exist in this client's tenant; another client's user is "not
found" in the same words as an absent one (no existence oracle). Read results go back to the caller only: the runner
audits who asked about whom, never the data (D-017). The lever returns IP addresses and places, so it needs a
technician (DC-3); the lockout workflow keeps them out of prompts.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.levers.handlers import LeverFailed
from core.levers.tenant import JsonDict

DEFAULT_LIMIT = 10
_NO_USER = "no such user for this client"


def signins_list(state: JsonDict, params: Mapping[str, Any]) -> Any:
    """The user's sign-ins, newest first, at most ``limit``."""
    upn = str(params["upn"]).lower()
    limit = params.get("limit", DEFAULT_LIMIT)
    users = state.get("users", [])
    if not any(isinstance(u, dict) and str(u.get("userPrincipalName", "")).lower() == upn for u in users):
        raise LeverFailed(_NO_USER)
    family = (state.get("_families") or {}).get("signins")
    events = family.get("value", []) if isinstance(family, dict) else []
    mine = [e for e in events if isinstance(e, dict) and str(e.get("userPrincipalName", "")).lower() == upn]
    mine.sort(key=lambda e: str(e.get("createdDateTime", "")), reverse=True)
    return mine[:limit]
