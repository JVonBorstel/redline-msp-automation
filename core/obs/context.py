"""The request scope (B-83): one request id (and an optional client) that every log line and audit record can pick up.

``request_scope`` sets two context variables for the duration of a ``with`` block. The lever runner, the model
gateway and the audit log read them when the caller names no id of its own, so one operator action, one triage run or
one scheduled job carries a single ``req-<uuid>`` through every component it touches. Nothing here writes anything.

Context variables are per thread and per asyncio task: a new thread does not inherit the id (pass it, or open a scope
in the worker). An id must be a short safe identifier and must not look like a secret; anything else is refused with
``ValueError`` before it can reach a log line or an audit record.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

REQUEST_ID_SHAPE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")

_REQUEST_ID: ContextVar[str | None] = ContextVar("ops_request_id", default=None)
_CLIENT: ContextVar[str | None] = ContextVar("ops_client", default=None)


def new_scope_id() -> str:
    """A fresh id in the audit log's format: ``req-`` and a hyphenated UUID (a bare 32-hex run would be redacted)."""
    return "req-" + str(uuid.uuid4())


def is_safe_request_id(value: object) -> bool:
    """True for a short identifier that the audit redactor would leave alone."""
    if not isinstance(value, str) or REQUEST_ID_SHAPE.fullmatch(value) is None:
        return False
    from core.audit.redact import redact_text  # late: core.audit imports this module

    return redact_text(value) == value


def current_request_id() -> str | None:
    """The id of the enclosing ``request_scope``, or None outside one."""
    return _REQUEST_ID.get()


def current_client() -> str | None:
    """The client label of the enclosing ``request_scope``, or None."""
    return _CLIENT.get()


@contextmanager
def request_scope(request_id: str | None = None, *, client: str | None = None) -> Iterator[str]:
    """Run a block under one request id (a fresh one when none is given) and, optionally, one client label.

    Scopes nest; the inner one wins and the outer one is restored on exit. A nested scope that names no client keeps
    the outer client. Raises ``ValueError`` for an id that is not a safe identifier.
    """
    rid = new_scope_id() if request_id is None else request_id
    if not is_safe_request_id(rid):
        raise ValueError("request id must be 1 to 64 letters, digits, '.', '_' or '-' and must not look like a secret")
    id_token = _REQUEST_ID.set(rid)
    client_token = _CLIENT.set(client if client is not None else _CLIENT.get())
    try:
        yield rid
    finally:
        _CLIENT.reset(client_token)
        _REQUEST_ID.reset(id_token)
