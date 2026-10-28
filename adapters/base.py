"""Adapter base: typed results and the one-client rule (STD-ER-1, STD-ID-4, TEN-04).

An adapter is the seam between a lever or workflow and an external system (PSA, later RMM, documentation,
backup, Microsoft 365). Two guarantees live here so every adapter shares them:

* an adapter instance is built for exactly one client, from that client's binding, and carries that client for
  its whole life; a binding that belongs to another client is refused at construction (``AdapterError``);
* a call never raises to its caller: it returns ``AdapterResult`` with ``ok`` and a human-readable ``reason``
  (an unexpected exception becomes ``"<component> crashed: <ExceptionType>"``, STD-ER-5).

Nothing here talks to a network. Synthetic data only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from adapters.binding import BoundBinding

REAL_ADAPTER_NOT_CONFIGURED = "real adapter not configured"


class AdapterError(RuntimeError):
    """A startup or construction error (STD-ER-4): wrong client, bad binding. Never raised by a call."""


@dataclass(frozen=True, slots=True)
class AdapterResult[T]:
    """What every adapter call returns. ``data`` is set only when ``ok``; ``reason`` is always readable."""

    ok: bool
    reason: str
    data: T | None = None

    @staticmethod
    def success[U](data: U, reason: str = "ok") -> AdapterResult[U]:
        return AdapterResult(True, reason, data)

    @staticmethod
    def failure[U](reason: str) -> AdapterResult[U]:
        return AdapterResult(False, reason, None)


class Adapter:
    """Base for one adapter instance, bound to one client and one external system."""

    system: str = ""  # "psa", "rmm", ... set by each interface

    def __init__(self, client: str, binding: BoundBinding) -> None:
        if binding.client != client:
            # TEN-04: never hold, even briefly, another client's binding.
            raise AdapterError("binding belongs to a different client; adapter not built")
        if self.system and binding.system != self.system:
            raise AdapterError(f"binding is for system {binding.system!r}, not {self.system!r}; adapter not built")
        self._client = client
        self._binding = binding

    @property
    def client(self) -> str:
        return self._client

    @property
    def external_id(self) -> str:
        return self._binding.external_id

    @property
    def credential_ref(self) -> str | None:
        """The secret NAME (never a value, STD-CF-7). A real adapter would resolve it from a vault."""
        return self._binding.credential_ref

    def _guard[U](self, call: Callable[[], AdapterResult[U]]) -> AdapterResult[U]:
        """Run one call and turn anything unexpected into a failed result (STD-ER-5)."""
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - boundary: nothing may raise to the caller (STD-ER-1)
            return AdapterResult.failure(f"{type(self).__name__} crashed: {type(exc).__name__}")
