"""Restore lever on the mock tenant state (B-69). Mock only: no backup product is called.

``restore.to-alternate`` records ONE request to restore a backed-up item to an ALTERNATE location in the client's own
state, under ``restoreRequests[<item id>@<alternate location>]``. There is no lever that restores over the original
location (B69-1): the registry pattern only accepts names that start with ``ALT-``, and this handler re-checks it, so
even a registry edit cannot turn the lever into an in-place overwrite. The handler does not look at the item: the
workflow looks it up in the client's own catalog and refuses another client's item or an original location before it
dry-runs (STD-LV-9), and a real adapter would re-check at the vendor. Asking twice changes nothing (STD-LV-6). The
handler gets one client's state copy and validated params only (STD-LV-8); it never reads a file or another client.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.levers.handlers import LeverFailed
from core.levers.tenant import JsonDict

ALTERNATE_PREFIX = "ALT-"


def restore_to_alternate(state: JsonDict, params: Mapping[str, Any]) -> Any:
    """Record that a restore of ``item_id`` to ``alternate_location`` was asked for."""
    item_id, location = params["item_id"], params["alternate_location"]
    if not str(location).startswith(ALTERNATE_PREFIX):
        raise LeverFailed("only an alternate location is accepted; the original location is never restored over")
    requests = state.setdefault("restoreRequests", {})
    if not isinstance(requests, dict):
        raise LeverFailed("restore requests are in an unexpected shape")
    requests.setdefault(
        f"{item_id}@{location}",
        {"action": "restore", "target": "alternate", "status": "requested"},
    )
    return {"item_id": item_id, "alternate_location": location, "action": "restore"}
