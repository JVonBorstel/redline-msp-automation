"""Per-client bindings: config/clients/<id>.json -> one adapter per client (B18-1, B18-3, TEN-04).

``schemas/client.schema.json`` is the hand-written contract (B-13); ``ClientConfig`` is the loader's pydantic
model and agrees with it (a test compares the patterns). Files are validated at load and fail closed
(STD-CF-3): one clear ``ClientConfigError`` that names the file. A binding holds a credential *reference
name* (a Key Vault secret name, D6-10), never a value (STD-CF-7); a value-shaped string fails validation.

The config files themselves (config/**) are a protected owner step (W2-E1); tests use private copies.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictStr, ValidationError, field_validator, model_validator

from core.paths import REPO_ROOT

DEFAULT_CLIENT_DIR = REPO_ROOT / "config" / "clients"

CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
IMPLEMENTATION = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
EXTERNAL_ID = re.compile(r"^[A-Za-z0-9._:-]+$")
CREDENTIAL_REF = re.compile(r"^client-[a-z0-9][a-z0-9-]{0,62}-[a-z][a-z0-9-]{1,31}$")
GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
DOTTED = re.compile(r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9-]*)+$")

System = Literal["psa", "rmm", "documentation", "backup", "m365"]


class ClientConfigError(RuntimeError):
    """A client config is missing, unreadable or invalid (fail closed, STD-CF-3)."""


_FROZEN = ConfigDict(frozen=True, extra="forbid")


class Binding(BaseModel):
    model_config = _FROZEN

    implementation: StrictStr
    external_id: StrictStr
    credential_ref: StrictStr | None = None
    access: Literal["gdap", "app-registration"] | None = None  # m365 only

    @field_validator("implementation")
    @classmethod
    def _impl(cls, v: str) -> str:
        if not IMPLEMENTATION.fullmatch(v):
            raise ValueError("implementation must be a short lowercase name such as 'mock'")
        return v

    @field_validator("external_id")
    @classmethod
    def _ext(cls, v: str) -> str:
        if len(v) > 128 or not EXTERNAL_ID.fullmatch(v):
            raise ValueError("external_id has characters or length a vendor id never has")
        return v

    @field_validator("credential_ref")
    @classmethod
    def _cred(cls, v: str | None) -> str | None:
        if v is not None and not CREDENTIAL_REF.fullmatch(v):
            # Deliberately does not echo the value: it may be a secret pasted by mistake (STD-CF-7).
            raise ValueError("credential_ref must be a secret NAME like client-<id>-<purpose>, never a value")
        return v


class ClientConfig(BaseModel):
    model_config = _FROZEN

    version: Literal[1]
    note: StrictStr | None = None
    id: StrictStr
    display_name: StrictStr
    psa_company_id: StrictStr
    industry: Literal["financial", "ria", "legal", "accounting", "dental", "other"]
    regimes: tuple[Literal["glba-ftc-safeguards", "sec-reg-s-p", "bank-ffiec", "ncua", "hipaa"], ...]
    model_processing: Literal["none", "local", "hosted"]
    retention_class: Literal["standard", "regulated-financial", "legal-hold-capable"]
    vault: Literal["shared", "dedicated"] | None = None
    enabled_levers: tuple[StrictStr, ...]
    enabled_jobs: tuple[dict[str, StrictStr], ...] = ()
    bindings: dict[System, Binding]

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not CLIENT_ID.fullmatch(v):
            raise ValueError("id must be a slug")
        return v

    @field_validator("display_name")
    @classmethod
    def _display(cls, v: str) -> str:
        if not 1 <= len(v) <= 80:
            raise ValueError("display_name must be 1 to 80 characters")
        return v

    @field_validator("psa_company_id")
    @classmethod
    def _psa(cls, v: str) -> str:
        if not re.fullmatch(r"[0-9]{1,12}", v):
            raise ValueError("psa_company_id must be digits written as a string")
        return v

    @field_validator("enabled_levers")
    @classmethod
    def _levers(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(v)) != len(v) or not all(len(n) <= 64 and DOTTED.fullmatch(n) for n in v):
            raise ValueError("enabled_levers must be unique lever names")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> ClientConfig:
        if not self.bindings:
            raise ValueError("at least one binding is required")
        for system, b in self.bindings.items():
            if system == "m365":
                if b.access is None or not GUID.fullmatch(b.external_id):
                    raise ValueError("m365 binding needs a tenant GUID and access (gdap or app-registration)")
            elif b.access is not None:
                raise ValueError("access belongs to the m365 binding only")
            if b.credential_ref is not None and not b.credential_ref.startswith(f"client-{self.id}-"):
                raise ValueError("credential_ref must name this client's own secret (client-<id>-...)")
        psa = self.bindings.get("psa")
        if psa is not None and psa.external_id != self.psa_company_id:
            raise ValueError("psa binding external_id must equal psa_company_id (the PSA is the source of truth)")
        return self


@dataclass(frozen=True, slots=True)
class BoundBinding:
    """One client's binding for one system, the only thing an adapter is built from (TEN-04)."""

    client: str
    system: str
    implementation: str
    external_id: str
    credential_ref: str | None = None


def load_client(client: str, root: Path = DEFAULT_CLIENT_DIR) -> ClientConfig:
    """Load and validate config/clients/<client>.json; raise ClientConfigError naming the file on any problem."""
    if not CLIENT_ID.fullmatch(client):
        raise ClientConfigError(f"invalid client id {client!r}")
    path = Path(root) / f"{client}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ClientConfigError(f"{path.name}: unreadable ({type(exc).__name__})") from exc
    if not isinstance(raw, dict):
        raise ClientConfigError(f"{path.name}: must be a JSON object")
    if "_note" in raw:  # STD-CF-5: a human note, ignored by readers
        raw = {("note" if k == "_note" else k): v for k, v in raw.items()}
    try:
        cfg = ClientConfig.model_validate(raw)
    except ValidationError as exc:
        # Messages name the field and the rule, never the offending input (it may be a secret).
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors(include_input=False)
        )
        raise ClientConfigError(f"{path.name}: invalid ({problems})") from exc
    if cfg.id != client:
        raise ClientConfigError(f"{path.name}: id {cfg.id!r} does not match the file name")
    return cfg


def bound_binding(config: ClientConfig, system: str) -> BoundBinding | None:
    """The binding of ``config`` for ``system`` (None when the client has none)."""
    for name, b in config.bindings.items():
        if name == system:
            return BoundBinding(config.id, name, b.implementation, b.external_id, b.credential_ref)
    return None
