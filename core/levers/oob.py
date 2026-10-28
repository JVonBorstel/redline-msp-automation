"""Out-of-band delivery of a generated credential (B-30, specs/B-30.md; controls C-10, C-30; D6-06).

The mock channel is a file. The PowerShell credential levers (levers/powershell/CredentialOps) write one JSON file per
issued credential to ``<root>/<client>/<target id>-<type>.json``; this module is how a person reads it and how a test
finds out where it is. The value in that file is the only copy: it is not in the lever result, the queue, the audit
log, a notice or a prompt (B30-1), and nothing in ``core`` imports this module, so no workflow can reach it by accident.

- ``oob_root()``: ``$REDLINE_OOB_DIR`` if set, else ``.tmp/oob`` in the repository (git-ignored).
- ``read_delivery()``: returns the value to a signed-in human technician or lead scoped to the client, once. An agent,
  a person scoped to another client, an expired file or a malformed file is refused. A single-use file is deleted by
  the read (``consume=True``, the default).
- ``find_secret_shapes()`` / ``scan_for_value()``: helpers for the sweep test (B30-2); they never return the value
  they found, only where.

Synthetic data only. A real channel (a password manager hand-off, an SMS gateway) replaces the file later.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from core.identity import Identity, Role
from core.paths import REPO_ROOT

OOB_DIR_ENV = "REDLINE_OOB_DIR"
DEFAULT_OOB_DIR = REPO_ROOT / ".tmp" / "oob"
CredentialType = Literal["password", "tap"]
CREDENTIAL_TYPES: tuple[str, ...] = ("password", "tap")

_CLIENT = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_TARGET = re.compile(r"^[A-Za-z0-9-]{1,64}$")
# Value shapes that must never appear outside the out-of-band file: the lengths and alphabets the levers generate,
# plus the generic shapes of STD-AU-5 (bearer, sk-, JWT, long hex).
_SHAPES = {
    "password": re.compile(
        r"(?<![A-Za-z0-9!#%+=?@])(?=[^\s\"]*[A-Z])(?=[^\s\"]*[a-z])(?=[^\s\"]*[2-9])(?=[^\s\"]*[!#%+=?@])[A-Za-z2-9!#%+=?@]{20}(?![A-Za-z0-9!#%+=?@])"
    ),
    "bearer": re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    "sk": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"),
    "hex": re.compile(r"\b[0-9a-fA-F]{40,}\b"),
}


class OobError(ValueError):
    """The delivery cannot be read. The message never contains the value."""


def oob_root() -> Path:
    raw = os.environ.get(OOB_DIR_ENV, "").strip()
    return Path(raw) if raw else DEFAULT_OOB_DIR


def delivery_path(client: str, target_id: str, credential_type: str, root: Path | None = None) -> Path:
    """The one place a client, a target id and a type become a path (STD-ID-4): plain ids only."""
    if not _CLIENT.match(client):
        raise OobError("client id is not a plain slug")
    if not _TARGET.match(target_id):
        raise OobError("target id is not a plain id")
    if credential_type not in CREDENTIAL_TYPES:
        raise OobError("credential type is not one of password or tap")
    return (root if root is not None else oob_root()) / client / f"{target_id}-{credential_type}.json"


def read_delivery(
    reader: Identity,
    client: str,
    target_id: str,
    credential_type: str,
    *,
    requester: str | None = None,
    now: datetime | None = None,
    consume: bool = True,
    root: Path | None = None,
) -> str:
    """Hand the value to the technician who asked for it. Refuses anyone else, an expired file or a malformed file.

    ``requester`` (the identity that invoked the lever) narrows the read to that one person. A single-use delivery is
    deleted by a successful read; an expired one is deleted by the attempt.
    """
    if reader.role is Role.AGENT:
        raise OobError("an agent cannot read an out-of-band delivery")
    if not reader.can_act_for(client):
        raise OobError(f"{reader.id} is not scoped to client {client}")
    if requester is not None and reader.id != requester:
        raise OobError("only the technician who requested this credential can read it")
    path = delivery_path(client, target_id, credential_type, root)
    if not path.is_file():
        raise OobError("no delivery is waiting for this target")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        value = record["value"]
        expires = datetime.fromisoformat(str(record["expires_at"]))
        single_use = bool(record.get("single_use", True))
        if record["client"] != client or record["target_id"] != target_id or record["type"] != credential_type:
            raise KeyError("mismatch")
    except (OSError, ValueError, KeyError, TypeError):
        raise OobError("the delivery file is malformed; nothing was read") from None
    if not isinstance(value, str) or not value:
        raise OobError("the delivery file is malformed; nothing was read")
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if (now or datetime.now(UTC)) >= expires:
        path.unlink(missing_ok=True)
        raise OobError("the delivery has expired and was removed; ask for a new one")
    if consume and single_use:
        path.unlink(missing_ok=True)
    return value


def find_secret_shapes(text: str) -> list[str]:
    """Names of the secret-looking shapes found in ``text`` (never the matched text)."""
    return sorted(name for name, pattern in _SHAPES.items() if pattern.search(text))


def scan_for_value(texts: Iterable[str], value: str) -> int:
    """How many of ``texts`` contain ``value`` exactly. For the sweep test; the value is not returned or logged."""
    return sum(1 for text in texts if value and value in text)
