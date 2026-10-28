"""Vendor-neutral Intune device interface (B-61).

Return shapes follow the Microsoft Graph v1.0 ``managedDevice`` resource (``GET /deviceManagement/managedDevices``;
field status in ``fixtures/intune/SOURCES.md``). Intune lives in the client's Microsoft 365 tenant, so the adapter is
built from the client's ``m365`` binding (the tenant GUID). Every method returns an ``AdapterResult`` and never raises
(STD-ER-1).

Read-only by construction: there is no retire, wipe, lock, sync or update method here. Device R3 actions are B-65's
levers under dual approval, never an adapter call.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from adapters.base import Adapter, AdapterResult

Record = dict[str, Any]


class IntuneAdapter(Adapter, ABC):
    system = "m365"

    @abstractmethod
    def list_managed_devices(self) -> AdapterResult[list[Record]]:
        """Every managed device of the bound tenant, by id."""

    @abstractmethod
    def get_managed_device(self, device_id: str) -> AdapterResult[Record]:
        """One managed device of the bound tenant. Anything else answers like an absent device."""
