"""PSA mock: serves one client's synthetic PSA fixture (fixtures/psa/<client>.json).

Built for exactly one client from that client's PSA binding (B18-1). The fixture's company id must equal the
binding's ``external_id`` or construction is refused, so a binding for client A can never be pointed at
client B's file (TEN-04). Every result is typed and nothing raises (B18-2). Read-only; fixtures are never
modified. Entity and field names follow the public Autotask REST shape; each field's verification status is in
``specs/B-18.md`` and ``fixtures/psa/SOURCES.md``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from adapters.base import AdapterError, AdapterResult
from adapters.binding import CLIENT_ID, BoundBinding
from adapters.psa.base import PsaAdapter, Record
from core.paths import REPO_ROOT

DEFAULT_PSA_DIR = REPO_ROOT / "fixtures" / "psa"


class PsaMock(PsaAdapter):
    def __init__(self, client: str, binding: BoundBinding, root: Path = DEFAULT_PSA_DIR) -> None:
        super().__init__(client, binding)
        if binding.implementation != "mock":
            raise AdapterError("PsaMock serves the 'mock' implementation only")
        if not CLIENT_ID.fullmatch(client):
            raise AdapterError("invalid client id; adapter not built")
        path = Path(root) / f"{client}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AdapterError(f"no readable PSA fixture for this client ({type(exc).__name__})") from exc
        company = data.get("company") if isinstance(data, dict) else None
        if (
            not isinstance(company, dict)
            or data.get("client") != client
            or str(company.get("id")) != binding.external_id
        ):
            raise AdapterError("PSA fixture does not belong to this client's company binding; adapter not built")
        self._data: dict[str, Any] = data
        self._company_id: Any = company["id"]

    # -- helpers ---------------------------------------------------------------------------------------------
    def _mine(self, key: str) -> list[Record]:
        rows = self._data.get(key, [])
        return [copy.deepcopy(r) for r in rows if r.get("companyID") == self._company_id]

    def _find_ticket(self, ticket: str) -> Record | None:
        for t in self._data.get("tickets", []):
            if t.get("companyID") == self._company_id and ticket in (t.get("ticketNumber"), str(t.get("id"))):
                found: Record = t
                return found
        return None

    # -- interface -------------------------------------------------------------------------------------------
    def get_company(self) -> AdapterResult[Record]:
        return self._guard(lambda: AdapterResult.success(copy.deepcopy(self._data["company"])))

    def list_contacts(self) -> AdapterResult[list[Record]]:
        return self._guard(lambda: AdapterResult.success(self._mine("contacts")))

    def get_contact(self, contact_id: int) -> AdapterResult[Record]:
        def run() -> AdapterResult[Record]:
            for c in self._mine("contacts"):
                if c.get("id") == contact_id:
                    return AdapterResult.success(c)
            return AdapterResult.failure("no such contact for this client")

        return self._guard(run)

    def list_tickets(self, status: int | None = None) -> AdapterResult[list[Record]]:
        def run() -> AdapterResult[list[Record]]:
            rows = self._mine("tickets")
            if status is not None:
                rows = [r for r in rows if r.get("status") == status]
            return AdapterResult.success(rows)

        return self._guard(run)

    def get_ticket(self, ticket: str) -> AdapterResult[Record]:
        def run() -> AdapterResult[Record]:
            found = self._find_ticket(ticket)
            if found is None:  # same words for "absent" and "another client's": no existence oracle
                return AdapterResult.failure("no such ticket for this client")
            return AdapterResult.success(copy.deepcopy(found))

        return self._guard(run)

    def list_ticket_notes(self, ticket: str) -> AdapterResult[list[Record]]:
        def run() -> AdapterResult[list[Record]]:
            found = self._find_ticket(ticket)
            if found is None:
                return AdapterResult.failure("no such ticket for this client")
            notes = [copy.deepcopy(n) for n in self._data.get("ticketNotes", []) if n.get("ticketID") == found["id"]]
            return AdapterResult.success(notes)

        return self._guard(run)

    def list_resources(self) -> AdapterResult[list[Record]]:
        return self._guard(lambda: AdapterResult.success(copy.deepcopy(self._data.get("resources", []))))

    def get_sla_settings(self) -> AdapterResult[list[Record]]:
        return self._guard(lambda: AdapterResult.success(copy.deepcopy(self._data.get("slaSettings", []))))
