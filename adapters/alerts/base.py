"""Vendor-neutral security-alert interface (B43-4, B43-5, D6-04).

Alert sources are modelled as TYPES, never as products: an EDR/MDR service, Microsoft 365 identity threat detection,
a SIEM, RMM monitors, backup, and SaaS monitoring. A real adapter for any vendor maps that vendor's fields onto
``Alert``; callers depend only on this interface. The field names below are this repo's own neutral names, not any
vendor's (every vendor field name is UNVERIFIED, see ``fixtures/alerts/SOURCES.md``). Every method returns an
``AdapterResult`` and never raises (STD-ER-1). Read-only: this adapter cannot close, contain or acknowledge an alert.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Annotated, Literal, get_args

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints

from adapters.base import Adapter, AdapterResult

SourceType = Literal["edr-mdr", "m365-itdr", "siem", "rmm-monitor", "backup", "saas-monitoring"]
SOURCE_TYPES: tuple[str, ...] = get_args(SourceType)
Severity = Literal["critical", "high", "medium", "low", "info"]
SEVERITY_ORDER: tuple[str, ...] = get_args(Severity)  # most severe first
EntityKind = Literal["user", "device", "mailbox", "job", "tenant"]

CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
ENTITY_ID = r"^[A-Za-z0-9][A-Za-z0-9._@:-]{0,127}$"  # what a user, device or job id looks like; no spaces, no text


class Alert(BaseModel):
    """One alert as the adapter returns it. ``title`` and ``description`` are untrusted text (STD-SC-3).

    Everything else is structured and pattern-checked, so the grouping logic never reads free text. Answer-key
    labels are not part of the alert and never reach the code under test (STD-FX-5).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: Annotated[str, StringConstraints(pattern=r"^A-[0-9]{4}$")]
    client: Annotated[str, StringConstraints(pattern=CLIENT_ID.pattern)]
    source_type: SourceType
    severity: Severity
    category: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{1,40}$")]
    title: Annotated[str, StringConstraints(max_length=200)]
    description: Annotated[str, StringConstraints(max_length=2000)] = ""
    created_at: AwareDatetime
    entity_kind: EntityKind
    entity_id: Annotated[str, StringConstraints(pattern=ENTITY_ID)]
    soc_case_id: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9-]{2,39}$")] | None = None


class AlertsAdapter(Adapter, ABC):
    system = "alerts"

    @abstractmethod
    def list_alerts(self, since: datetime | None = None, until: datetime | None = None) -> AdapterResult[list[Alert]]:
        """The bound client's alerts, oldest first, optionally inside [since, until]."""

    @abstractmethod
    def get_alert(self, alert_id: str) -> AdapterResult[Alert]:
        """One alert of the bound client; another client's alert answers like an absent one."""
