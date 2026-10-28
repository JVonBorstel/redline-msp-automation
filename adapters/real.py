"""Real-adapter stubs: one per adapter interface, all closed (B-91, B91-3).

A stub is the place a vendor client will plug in later. Today none is wired: every call returns
``AdapterResult(False, "real adapter not configured", None)`` and nothing talks to a network. A stub is built for
exactly one client from that client's binding, like a mock (TEN-04), and it refuses a binding that names the mock
or that carries a credential *value* where a secret *name* belongs (STD-CF-7). It keeps the name only and never
resolves it, prints it in a repr or logs it.

``REAL_STUBS`` is the registry the shared contract suite (``tests/py/contract/test_b91_adapters.py``) iterates:
a real implementation replaces its stub here only after it passes that suite (B91-1). Synthetic data only.
"""

from __future__ import annotations

from datetime import datetime

from adapters.alerts.base import Alert, AlertsAdapter
from adapters.backup.base import BackupAdapter
from adapters.base import REAL_ADAPTER_NOT_CONFIGURED, Adapter, AdapterError, AdapterResult
from adapters.binding import CREDENTIAL_REF, BoundBinding
from adapters.graph.base import GraphAdapter
from adapters.intune.base import IntuneAdapter
from adapters.psa.base import PsaAdapter
from adapters.rmm.base import Record, RmmAdapter


def _closed[T]() -> AdapterResult[T]:
    return AdapterResult.failure(REAL_ADAPTER_NOT_CONFIGURED)


class RealStub(Adapter):
    """Shared construction rules for every real stub."""

    def __init__(self, client: str, binding: BoundBinding) -> None:
        super().__init__(client, binding)
        if binding.implementation == "mock":
            raise AdapterError(f"{type(self).__name__} serves a real implementation, not 'mock'; adapter not built")
        ref = binding.credential_ref
        # Never echo ``ref``: if it is a pasted secret, the error would print it.
        if ref is not None and (not CREDENTIAL_REF.fullmatch(ref) or not ref.startswith(f"client-{client}-")):
            raise AdapterError("credential_ref must be this client's secret NAME, never a value; adapter not built")

    def __repr__(self) -> str:
        return f"<{type(self).__name__} client={self._client!r} unconfigured>"


class RealPsa(RealStub, PsaAdapter):
    def get_company(self) -> AdapterResult[Record]:
        return _closed()

    def list_contacts(self) -> AdapterResult[list[Record]]:
        return _closed()

    def get_contact(self, contact_id: int) -> AdapterResult[Record]:
        return _closed()

    def list_tickets(self, status: int | None = None) -> AdapterResult[list[Record]]:
        return _closed()

    def get_ticket(self, ticket: str) -> AdapterResult[Record]:
        return _closed()

    def list_ticket_notes(self, ticket: str) -> AdapterResult[list[Record]]:
        return _closed()

    def list_resources(self) -> AdapterResult[list[Record]]:
        return _closed()

    def get_sla_settings(self) -> AdapterResult[list[Record]]:
        return _closed()


class RealRmm(RealStub, RmmAdapter):
    def get_site(self) -> AdapterResult[Record]:
        return _closed()

    def list_devices(self) -> AdapterResult[list[Record]]:
        return _closed()

    def get_device(self, device_uid: str) -> AdapterResult[Record]:
        return _closed()

    def get_device_audit(self, device_uid: str) -> AdapterResult[Record]:
        return _closed()

    def list_open_alerts(self) -> AdapterResult[list[Record]]:
        return _closed()

    def list_jobs(self) -> AdapterResult[list[Record]]:
        return _closed()

    def get_job(self, job_uid: str) -> AdapterResult[Record]:
        return _closed()

    def list_components(self) -> AdapterResult[list[Record]]:
        return _closed()


class RealIntune(RealStub, IntuneAdapter):
    def list_managed_devices(self) -> AdapterResult[list[Record]]:
        return _closed()

    def get_managed_device(self, device_id: str) -> AdapterResult[Record]:
        return _closed()


class RealGraph(RealStub, GraphAdapter):
    def state(self) -> AdapterResult[Record]:
        return _closed()

    def families(self) -> AdapterResult[list[str]]:
        return _closed()

    def family_state(self, family: str) -> AdapterResult[Record]:
        return _closed()

    def list_users(self) -> AdapterResult[list[Record]]:
        return _closed()

    def get_user(self, user: str) -> AdapterResult[Record]:
        return _closed()

    def list_authentication_methods(self, user: str) -> AdapterResult[list[Record]]:
        return _closed()


class RealBackup(RealStub, BackupAdapter):
    def get_organization(self) -> AdapterResult[Record]:
        return _closed()

    def list_jobs(self, job_type: str | None = None) -> AdapterResult[list[Record]]:
        return _closed()

    def get_job(self, job_id: str) -> AdapterResult[Record]:
        return _closed()


class RealAlerts(RealStub, AlertsAdapter):
    def list_alerts(self, since: datetime | None = None, until: datetime | None = None) -> AdapterResult[list[Alert]]:
        return _closed()

    def get_alert(self, alert_id: str) -> AdapterResult[Alert]:
        return _closed()


REAL_STUBS: dict[str, type[RealStub]] = {
    "psa": RealPsa,
    "rmm": RealRmm,
    "intune": RealIntune,
    "graph": RealGraph,
    "backup": RealBackup,
    "alerts": RealAlerts,
}

__all__ = [
    "REAL_STUBS",
    "RealAlerts",
    "RealBackup",
    "RealGraph",
    "RealIntune",
    "RealPsa",
    "RealRmm",
    "RealStub",
]
