"""Risky-user, user-fact and device-fact read levers on the mock tenant (B-44). Mock only.

``risk.list-users`` reads the client's ``risky-users`` family file (Graph ``riskyUser`` shape). A real read needs
Microsoft Entra ID P2; whether a client holds it is UNVERIFIED, so a client with no file gets an empty list and a note
that says so, never a guess. ``risk.user-facts`` and ``risk.device-facts`` read one user's directory facts and device
list for the enrichment pack. The runner hands a read lever the client's state plus that client's own family files
under ``_families`` (``MockTenant.load_for_read``), so a handler sees one client's data only (STD-LV-8). A user of
another client is "not found" in the same words as an absent one. Read results go to the caller only; the runner audits
who asked about whom, never the data (D-017).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.levers.handlers import LeverFailed
from core.levers.tenant import JsonDict

DEFAULT_LIMIT = 50
DEVICES_PATH = Path(__file__).resolve().parents[2] / "workflows" / "factpack" / "fixtures" / "devices.json"
_NO_USER = "no such user for this client"
_LEVEL_ORDER = {"high": 0, "medium": 1, "low": 2, "none": 3}
_NOT_AVAILABLE = (
    "No risky-user data for this client: Entra ID P2 (Identity Protection) is not confirmed for it. "
    "Licensing is UNVERIFIED; an empty list does not mean no user is at risk."
)


def _find_user(state: JsonDict, params: Mapping[str, Any]) -> dict[str, Any]:
    upn = str(params["upn"]).lower()
    for user in state.get("users", []):
        if isinstance(user, dict) and str(user.get("userPrincipalName", "")).lower() == upn:
            return user
    raise LeverFailed(_NO_USER)


def risk_list_users(state: JsonDict, params: Mapping[str, Any]) -> Any:
    """Risky users, highest risk first, optionally only one risk ``level``, at most ``limit``."""
    family = (state.get("_families") or {}).get("risky-users")
    if not isinstance(family, dict):
        return {"value": [], "note": _NOT_AVAILABLE}
    level = params.get("level")
    limit = params.get("limit", DEFAULT_LIMIT)
    listed = [r for r in family.get("value", []) if isinstance(r, dict)]
    rows = [r for r in listed if level is None or r.get("riskLevel") == level]
    rows.sort(key=lambda r: (_LEVEL_ORDER.get(str(r.get("riskLevel")), 9), str(r.get("userPrincipalName", "")).lower()))
    note = "Entra ID P2 (Identity Protection) is required; whether this client holds it is UNVERIFIED."
    return {"value": rows[:limit], "note": note}


def risk_user_facts(state: JsonDict, params: Mapping[str, Any]) -> Any:
    """One user's directory facts. Phone numbers and method ids stay out; only the method kinds are returned."""
    user = _find_user(state, params)
    methods = (user.get("authentication") or {}).get("methods", [])
    kinds = sorted(
        str(m.get("@odata.type", "")).removeprefix("#microsoft.graph.")
        for m in methods
        if isinstance(m, dict) and m.get("@odata.type")
    )
    return {
        "id": user.get("id"),
        "displayName": user.get("displayName"),
        "userPrincipalName": user.get("userPrincipalName"),
        "jobTitle": user.get("jobTitle"),
        "accountEnabled": user.get("accountEnabled"),
        "authenticationMethods": kinds,
    }


def risk_device_facts(state: JsonDict, params: Mapping[str, Any]) -> Any:
    """The devices on record for one user of this client (stand-in device list; field names UNVERIFIED)."""
    _find_user(state, params)
    upn = str(params["upn"]).lower()
    client = str((state.get("_meta") or {}).get("client", ""))
    try:
        data = json.loads(DEVICES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LeverFailed("no device list available") from exc
    mine = ((data.get("clients") or {}).get(client) or {}).get("devices", []) if isinstance(data, dict) else []
    return [d for d in mine if isinstance(d, dict) and str(d.get("owner", "")).lower() == upn]
