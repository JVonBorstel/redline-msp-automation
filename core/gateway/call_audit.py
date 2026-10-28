"""The model-call audit record (B-80, DR-17): metadata only, one ``model.complete`` v2 record per gateway call.

What is written: provider, model, task, the SHA-256 of the text the model was sent (after the B-55 redaction gate),
character lengths, estimated size, latency, data class, the kinds of span redacted, and the outcome. What is never
written: the prompt, the completion, a provider's error message, or any value the redaction gate found.

Field names avoid the words the audit redactor blanks (``token``, ``key``, ``secret``, ``password``), and the hash is
written as eight groups of eight hex digits because the redactor replaces any run of 32 or more hex digits (STD-AU-5).
``"".join(value.split())`` gives the hash back.
"""

from __future__ import annotations

import hashlib
from typing import Any, Protocol

from core.audit.chain import ActorKind, Event, Mode


class AuditSink(Protocol):
    """Anything shaped like ``AuditLog.append`` (an ``AuditLog``, or an ``AuditRouter`` with one chain per client)."""

    def append(
        self,
        *,
        agent: str,
        client: str | None,
        lever: str,
        params: dict[str, Any],
        mode: Mode,
        result: dict[str, Any],
        approver: str | None = None,
        event: Event | None = None,
        actor_kind: ActorKind | None = None,
        lever_version: int | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]: ...


MODEL_LEVER = "model.complete"
"""The ``lever`` field of a model-call record; the gateway is not a lever, but the record shape is shared."""


def prompt_digest(sent_text: str) -> str:
    """SHA-256 of the exact text a model was sent, as eight space-separated groups of eight hex digits."""
    digest = hashlib.sha256(sent_text.encode("utf-8")).hexdigest()
    return " ".join(digest[i : i + 8] for i in range(0, len(digest), 8))
