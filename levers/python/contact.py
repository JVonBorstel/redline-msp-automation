"""Requester authorization check (B-34, C-30). Read lever, mock only.

``contact.check`` answers one question: may this named requester ask for this kind of change for this client? The
answer comes from that client's authorized-contacts list only (``fixtures/psa/contacts-authorized.json``). The client is
taken from the state the runner hands over (``_meta.client``), never from a parameter, and only that client's entry of
the file is used: another client's list is never looked at, so it cannot leak into the answer or be guessed from it.

An unknown requester, an inactive one, or one not listed for that change type gets the same words and a pointer to the
client's primary contact (never a guess, never a hint which of the three it was). The result is evidence for the
verification record shown on the approval page. It never sets verification: ``sets_verification`` is always false and
callback-on-file stays a human act (W-IDM-04, D6-06).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.levers.handlers import LeverFailed
from core.levers.tenant import JsonDict

CONTACTS_FILE = Path(__file__).resolve().parents[2] / "fixtures" / "psa" / "contacts-authorized.json"
SOURCE = "fixtures/psa/contacts-authorized.json"
NOT_AUTHORIZED = "not authorized: confirm with the client's primary contact"
EVIDENCE_NOTE = (
    "Evidence only. This does not verify the requester: call the number on file and record the callback (C-30)."
)


def _contacts_for(client: str) -> list[Any]:
    try:
        data = json.loads(CONTACTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LeverFailed("the authorized-contacts list is not readable") from exc
    clients = data.get("clients") if isinstance(data, dict) else None
    entry = clients.get(client) if isinstance(clients, dict) else None  # this client's entry, and no other
    contacts = entry.get("contacts") if isinstance(entry, dict) else None
    return contacts if isinstance(contacts, list) else []


def contact_check(state: JsonDict, params: Mapping[str, Any]) -> Any:
    """Whether ``requester`` may request ``change_type`` for the runner's client; evidence, not verification."""
    meta = state.get("_meta")
    client = meta.get("client") if isinstance(meta, dict) else None
    if not isinstance(client, str) or not client:
        raise LeverFailed("the client of this tenant is not known")
    requester = str(params["requester"]).strip().lower()
    change_type = str(params["change_type"])
    match: Mapping[str, Any] | None = None
    for contact in _contacts_for(client):
        if (
            isinstance(contact, dict)
            and str(contact.get("email", "")).lower() == requester
            and contact.get("active") is True
            and change_type in (contact.get("changeTypes") or [])
        ):
            match = contact
            break
    evidence: dict[str, Any] = {
        "kind": "requester-authorization",
        "client": client,
        "requester": requester,
        "change_type": change_type,
        "source": SOURCE,
        "sets_verification": False,
        "note": EVIDENCE_NOTE,
    }
    if match is None:
        return {"authorized": False, "message": NOT_AUTHORIZED, "evidence": evidence}
    evidence["contact_id"] = match.get("contactId")
    return {"authorized": True, "message": f"authorized contact: {match.get('name')}", "evidence": evidence}
