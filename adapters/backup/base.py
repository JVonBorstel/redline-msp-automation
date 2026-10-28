"""Vendor-neutral backup interface (D6-24, B68-4).

Two job types are modelled, because the MSP sells both: ``image-appliance`` (an image-based appliance/agent job with a
boot-check screenshot result) and ``m365-saas`` (a Microsoft 365 SaaS backup job). Field names are UNVERIFIED stand-ins
(``fixtures/backup/SOURCES.md``). Every method returns an ``AdapterResult`` and never raises (STD-ER-1). The interface
is read-only: the one backup write is the ``backup.retry-job`` lever (approved, audited), not an adapter call.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from adapters.base import Adapter, AdapterResult

Record = dict[str, Any]
JOB_TYPES: tuple[str, ...] = ("image-appliance", "m365-saas")


class BackupAdapter(Adapter, ABC):
    system = "backup"

    @abstractmethod
    def get_organization(self) -> AdapterResult[Record]:
        """The one backup organization this adapter is bound to."""

    @abstractmethod
    def list_jobs(self, job_type: str | None = None) -> AdapterResult[list[Record]]:
        """Every job record of the bound organization, oldest first; optionally one job type only."""

    @abstractmethod
    def get_job(self, job_id: str) -> AdapterResult[Record]:
        """One job of the bound organization. Another organization's job answers like an absent one."""
