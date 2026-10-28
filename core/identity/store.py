"""Load identities from config/identities.json and fail closed on anything unexpected.

An identity is an id, a role and the clients it may act for. Roles are ranked
(agent < technician < lead): a lever that requires `technician` accepts a lead too,
but never an agent. Agents are button pushers and get the least privilege.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator

DEFAULT_IDENTITIES_PATH = Path(__file__).resolve().parents[2] / "config" / "identities.json"

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")]


class Role(StrEnum):
    AGENT = "agent"
    TECHNICIAN = "technician"
    LEAD = "lead"


_RANK = {Role.AGENT: 0, Role.TECHNICIAN: 1, Role.LEAD: 2}


def role_satisfies(actual: Role, required: Role) -> bool:
    """True when `actual` is at least as privileged as `required`."""
    return _RANK[actual] >= _RANK[required]


class UnknownIdentity(LookupError):
    """The id is not in the identity file. Callers must treat this as a denial."""


class IdentityConfigError(ValueError):
    """The identity file is missing or malformed. Nothing loads (fail closed)."""


class Identity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Slug
    display_name: str = Field(min_length=1, max_length=80)
    role: Role
    clients: tuple[Slug, ...] = Field(min_length=1)

    @field_validator("clients")
    @classmethod
    def _no_duplicate_clients(cls, clients: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(clients)) != len(clients):
            raise ValueError("duplicate client in allow list")
        return clients

    def can_act_for(self, client: str) -> bool:
        return client in self.clients


class _IdentityFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1, le=1)
    identities: list[Identity] = Field(min_length=1)


class IdentityStore:
    """Read-only lookup of identities by id."""

    def __init__(self, identities: list[Identity]) -> None:
        by_id: dict[str, Identity] = {}
        for identity in identities:
            if identity.id in by_id:
                raise IdentityConfigError(f"duplicate identity id {identity.id!r}")
            by_id[identity.id] = identity
        self._by_id = by_id

    @classmethod
    def load(cls, path: Path = DEFAULT_IDENTITIES_PATH) -> IdentityStore:
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            parsed = _IdentityFile.model_validate(raw)
        except (OSError, ValueError, ValidationError) as exc:  # json.JSONDecodeError is a ValueError
            raise IdentityConfigError(f"cannot load identities from {path}: {exc}") from exc
        return cls(parsed.identities)

    def get(self, identity_id: str) -> Identity:
        try:
            return self._by_id[identity_id]
        except KeyError:
            raise UnknownIdentity(f"unknown identity {identity_id!r}") from None

    def __contains__(self, identity_id: object) -> bool:
        return identity_id in self._by_id

    def __len__(self) -> int:
        return len(self._by_id)

    def __iter__(self) -> Iterator[Identity]:
        return iter(self._by_id.values())
