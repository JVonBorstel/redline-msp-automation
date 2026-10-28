"""Vendor-neutral PSA interface (D6-01, B18-4).

Return shapes follow the public Autotask REST entities (Companies, Contacts, Tickets, TicketNotes, Resources,
ServiceLevelAgreements), but callers depend only on this interface, so a ConnectWise or Halo binding is the
same seam. Every method returns an ``AdapterResult`` and never raises (STD-ER-1). All methods are read-only:
a PSA write lever would be a separate, approved item.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from adapters.base import Adapter, AdapterResult

Record = dict[str, Any]


class PsaAdapter(Adapter, ABC):
    system = "psa"

    @abstractmethod
    def get_company(self) -> AdapterResult[Record]:
        """The one PSA company this adapter is bound to."""

    @abstractmethod
    def list_contacts(self) -> AdapterResult[list[Record]]: ...

    @abstractmethod
    def get_contact(self, contact_id: int) -> AdapterResult[Record]: ...

    @abstractmethod
    def list_tickets(self, status: int | None = None) -> AdapterResult[list[Record]]: ...

    @abstractmethod
    def get_ticket(self, ticket: str) -> AdapterResult[Record]:
        """By ticket number (``T-3101``) or numeric id, within the bound company only."""

    @abstractmethod
    def list_ticket_notes(self, ticket: str) -> AdapterResult[list[Record]]: ...

    @abstractmethod
    def list_resources(self) -> AdapterResult[list[Record]]: ...

    @abstractmethod
    def get_sla_settings(self) -> AdapterResult[list[Record]]: ...
