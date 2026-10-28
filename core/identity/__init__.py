"""Agent and human identities with per-client scoping (specs/phase-1.md deliverable 1)."""

from core.identity.store import (
    DEFAULT_IDENTITIES_PATH,
    Identity,
    IdentityConfigError,
    IdentityStore,
    Role,
    UnknownIdentity,
    role_satisfies,
)

__all__ = [
    "DEFAULT_IDENTITIES_PATH",
    "Identity",
    "IdentityConfigError",
    "IdentityStore",
    "Role",
    "UnknownIdentity",
    "role_satisfies",
]
