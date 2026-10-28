"""The hosted-provider vendor register and the approval gate decision (B-90, C-15, C-25, C-28, C-43).

``governance/ai-vendor-register.json`` is the only place a hosted provider is approved. An entry is a recorded
approval: it names the provider, the clients, the data classes, the purposes, the retention terms, who approved it
in writing and when, and a review date after which it stops approving. A ``pending`` or ``revoked`` entry allows
nothing. DC-6 (credentials) is never allowed, whatever the file says.

``VendorRegister.check`` is the whole decision. It reads only its arguments and the register, never the text, and
it returns a fixed code, never a value, so the code is safe to audit. Anything that is not an explicit yes is a no.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.gateway.base import ProviderName
from core.guard.classify import DataClass
from core.paths import REPO_ROOT

REGISTER_FILE = Path("governance/ai-vendor-register.json")

ID_PATTERN = r"^[a-z][a-z0-9-]{2,63}$"
PURPOSE_PATTERN = r"^[a-z][a-z0-9-]{1,39}$"
"""Approval ids and purposes are short codes, never free text, so neither can carry a name or a ticket's content."""

HostedName = Literal["azure_openai", "anthropic"]
Status = Literal["pending", "approved", "revoked"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VendorEntry(_Strict):
    id: str = Field(pattern=ID_PATTERN)
    provider: HostedName
    name: str = Field(min_length=1, max_length=80)
    status: Status
    allowed_data_classes: tuple[str, ...] = ()
    clients: tuple[str, ...] = ()
    purposes: tuple[str, ...] = ()
    retention_terms: str | None = Field(default=None, max_length=400)
    review_date: date | None = None
    approved_by: str | None = Field(default=None, max_length=80)
    approved_on: date | None = None
    approval_ref: str | None = Field(default=None, max_length=120)

    @field_validator("allowed_data_classes")
    @classmethod
    def _classes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for label in value:
            if DataClass.parse(label) is DataClass.DC6:
                raise ValueError("DC-6 (credentials and secrets) can never be allowed on a hosted route")
        return value

    @field_validator("purposes")
    @classmethod
    def _purposes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for purpose in value:
            if not re.fullmatch(PURPOSE_PATTERN, purpose):
                raise ValueError(f"purpose {purpose!r} is not a short code (lowercase letters, digits, hyphens)")
        return value

    @field_validator("clients")
    @classmethod
    def _clients(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for client in value:
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", client):
                raise ValueError(f"client {client!r} is not a client id")
        return value

    @model_validator(mode="after")
    def _complete_approval(self) -> Self:
        granted = (self.allowed_data_classes, self.clients, self.purposes)
        if self.status != "approved":
            if any(granted):
                raise ValueError(f"a {self.status} entry allows nothing: no data classes, clients or purposes")
            return self
        missing = [
            name
            for name, present in (
                ("allowed_data_classes", bool(self.allowed_data_classes)),
                ("clients", bool(self.clients)),
                ("purposes", bool(self.purposes)),
                ("retention_terms", bool(self.retention_terms)),
                ("review_date", self.review_date is not None),
                ("approved_by", bool(self.approved_by)),
                ("approved_on", self.approved_on is not None),
                ("approval_ref", bool(self.approval_ref)),
            )
            if not present
        ]
        if missing:
            raise ValueError(f"an approved entry needs {', '.join(missing)}")
        if self.approved_on is not None and self.review_date is not None and self.approved_on > self.review_date:
            raise ValueError("approved_on is after review_date")
        return self


@dataclass(frozen=True, slots=True)
class GateDecision:
    """``allowed`` plus a fixed ``code``: ``ok`` or why not. Never carries text from the call."""

    allowed: bool
    code: str


class VendorRegister(_Strict):
    version: Literal[1]
    vendors: tuple[VendorEntry, ...]

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        ids = [v.id for v in self.vendors]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate vendor ids")
        return self

    @classmethod
    def load(cls, path: Path | None = None) -> Self:
        """Read and validate the register. Raises OSError or ValueError (pydantic's ValidationError is one)."""
        file = path or REPO_ROOT / REGISTER_FILE
        document = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("vendor register must be a JSON object")
        return cls.model_validate({k: v for k, v in document.items() if k != "_note"})

    def get(self, approval_id: str) -> VendorEntry | None:
        return next((v for v in self.vendors if v.id == approval_id), None)

    def check_provider(self, *, approval_id: str | None, provider: ProviderName, today: date) -> GateDecision:
        """Is this approval id a live, approved entry for this provider? (B90-1: nothing hosted loads without it.)"""
        if not approval_id:
            return GateDecision(False, "no-approval-id")
        entry = self.get(approval_id)
        if entry is None:
            return GateDecision(False, "unknown-approval")
        if entry.provider != provider:
            return GateDecision(False, "wrong-provider")
        if entry.status != "approved":
            return GateDecision(False, "not-approved")
        if entry.review_date is None or today > entry.review_date:
            return GateDecision(False, "review-overdue")
        return GateDecision(True, "ok")

    def check(
        self,
        *,
        approval_id: str | None,
        provider: ProviderName,
        client_id: str | None,
        data_class: DataClass,
        purpose: str | None,
        today: date,
    ) -> GateDecision:
        """The approval must name this provider, this client, this data class and this purpose, and be in date."""
        base = self.check_provider(approval_id=approval_id, provider=provider, today=today)
        entry = self.get(approval_id or "")
        if not base.allowed or entry is None:
            return base if not base.allowed else GateDecision(False, "unknown-approval")
        if client_id is None or client_id not in entry.clients:
            return GateDecision(False, "client-not-approved")
        if data_class.label not in entry.allowed_data_classes or data_class is DataClass.DC6:
            return GateDecision(False, "class-not-approved")
        if not purpose or not re.fullmatch(PURPOSE_PATTERN, purpose):
            return GateDecision(False, "purpose-missing")
        if purpose not in entry.purposes:
            return GateDecision(False, "purpose-not-approved")
        return GateDecision(True, "ok")
