"""Vendor-neutral Microsoft 365 identity-state interface (B19-1, B19-2).

Read-only by construction: there is no write method here or in the mock. A write lever changes state only
through the lever runner's diff-and-save path (SL-04, STD-LV-3); the adapter shows what is on disk right now.
Every method returns an ``AdapterResult`` and never raises (STD-ER-1).
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

from adapters.base import Adapter, AdapterResult

Record = dict[str, Any]

FAMILY = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


class GraphAdapter(Adapter, ABC):
    system = "m365"

    @abstractmethod
    def state(self) -> AdapterResult[Record]:
        """A copy of the client's base tenant state (fixtures/tenant/<client>.json)."""

    @abstractmethod
    def families(self) -> AdapterResult[list[str]]:
        """Names of the optional per-family state files this client has."""

    @abstractmethod
    def family_state(self, family: str) -> AdapterResult[Record]:
        """A copy of one family's state (fixtures/tenant/<client>/<family>.json)."""

    @abstractmethod
    def list_users(self) -> AdapterResult[list[Record]]: ...

    @abstractmethod
    def get_user(self, user: str) -> AdapterResult[Record]:
        """By id or userPrincipalName, within the bound client only."""

    @abstractmethod
    def list_authentication_methods(self, user: str) -> AdapterResult[list[Record]]: ...
