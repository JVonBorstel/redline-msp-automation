"""Vendor-neutral RMM interface (D6-01, D6-26, B61-4).

Return shapes follow the public Datto RMM API v2 (sites, devices, device audit, alerts, jobs, components; field
status in ``fixtures/rmm/SOURCES.md``), but callers depend only on this interface, so another RMM is the same seam.
Every method returns an ``AdapterResult`` and never raises (STD-ER-1).

Read-only by construction. There is no method that runs a job, a quick job or a component, and none that changes a
device: existing RMM components are listed so a person can see them, and the program never runs one until it has been
vetted into the lever registry as a named script (D6-26, B-62).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from adapters.base import Adapter, AdapterResult

Record = dict[str, Any]


class RmmAdapter(Adapter, ABC):
    system = "rmm"

    @abstractmethod
    def get_site(self) -> AdapterResult[Record]:
        """The one RMM site this adapter is bound to (``GET /v2/site/{siteUid}``)."""

    @abstractmethod
    def list_devices(self) -> AdapterResult[list[Record]]:
        """Every device of the bound site (``GET /v2/site/{siteUid}/devices``), by uid."""

    @abstractmethod
    def get_device(self, device_uid: str) -> AdapterResult[Record]:
        """One device of the bound site. Another site's device answers like an absent one."""

    @abstractmethod
    def get_device_audit(self, device_uid: str) -> AdapterResult[Record]:
        """The hardware audit of one device of the bound site (``GET /v2/audit/device/{deviceUid}``)."""

    @abstractmethod
    def list_open_alerts(self) -> AdapterResult[list[Record]]:
        """Open alerts of the bound site (``GET /v2/site/{siteUid}/alerts/open``)."""

    @abstractmethod
    def list_jobs(self) -> AdapterResult[list[Record]]:
        """Jobs people already ran on the bound site's devices (each as ``GET /v2/job/{uid}``). Read-only."""

    @abstractmethod
    def get_job(self, job_uid: str) -> AdapterResult[Record]:
        """One job of the bound site. Another site's job answers like an absent one."""

    @abstractmethod
    def list_components(self) -> AdapterResult[list[Record]]:
        """The account's existing components (``GET /v2/account/components``), listed read-only, never run (D6-26)."""
