"""Validate a Microsoft Entra ID v2.0 ID token for an approver, offline (B-89, C-44).

Guarantees:
- signature first, claims second: nothing in an unverified payload is trusted or returned;
- only `RS256` with a `kid` from the configured key set (no `none`, no `HS256` key confusion, no
  `crit` extensions, no keys embedded in the token);
- `iss`, `aud`, `tid` and `ver` must equal the configured single-tenant values exactly;
- `exp`, `nbf` and `iat` are checked against an explicit `now` with a bounded leeway, and a token
  that lives longer than `max_lifetime_s` is refused;
- `amr` must contain a required method (default `mfa`), and `sid` must be present, because the
  approval record carries both;
- the token's `oid` must map to a known repo identity; an unmapped person is refused, never
  defaulted. Role and client scope are still checked by the queue and the runner (STD-ID-3).

Every refusal is an `AuthError` with a fixed `code` (safe to audit) and never echoes the token.
The configuration is loaded from a file and fails closed on anything unexpected (STD-DD-7). The
claim names follow Microsoft's published ID token reference; they have not been checked against a
live tenant here (docs/BLUEPRINT.md hard rule 7).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, StringConstraints, ValidationError

from core.auth.jws import MIN_RSA_BITS, JwsError, RsaPublicKey, int_from_b64url, parse_compact, verify_rs256
from core.auth.models import AmrValue, ApproverAuth, Guid, IdentityId
from core.identity import IdentityStore

ENTRA_AUTHORITY = "https://login.microsoftonline.com"
MAX_LEEWAY_S = 300
MAX_LIFETIME_S = 86400

AuthErrorCode = Literal[
    "no-token",
    "malformed",
    "bad-algorithm",
    "unknown-key",
    "bad-signature",
    "wrong-issuer",
    "wrong-audience",
    "wrong-tenant",
    "wrong-version",
    "expired",
    "not-yet-valid",
    "issued-in-future",
    "lifetime-too-long",
    "missing-claim",
    "no-mfa",
    "unknown-approver",
]


class AuthError(Exception):
    """The token does not prove who the approver is. `code` is a fixed string, safe to audit."""

    def __init__(self, code: AuthErrorCode, detail: str = "") -> None:
        self.code: AuthErrorCode = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class AuthConfigError(ValueError):
    """The auth configuration is missing or malformed. Nothing loads (fail closed)."""


class Jwk(BaseModel):
    """One public RSA signing key in JWK form (RFC 7517), as Entra publishes them."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    kty: Literal["RSA"]
    kid: Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")]
    use: Literal["sig"] = "sig"
    n: StrictStr
    e: StrictStr

    def public_key(self) -> RsaPublicKey:
        try:
            key = RsaPublicKey(n=int_from_b64url(self.n), e=int_from_b64url(self.e))
        except JwsError as exc:
            raise AuthConfigError(f"key {self.kid!r}: {exc}") from exc
        if key.bits < MIN_RSA_BITS:
            raise AuthConfigError(f"key {self.kid!r} is {key.bits} bits; at least {MIN_RSA_BITS} are required")
        return key


class AuthConfig(BaseModel):
    """Single-tenant app registration settings and the approver map (synthetic values only in this repo)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: StrictInt = Field(ge=1, le=1)
    tenant_id: Guid
    client_id: Guid
    keys: tuple[Jwk, ...] = Field(min_length=1)
    approvers: dict[Guid, IdentityId] = Field(min_length=1)
    leeway_s: StrictInt = Field(default=60, ge=0, le=MAX_LEEWAY_S)
    max_lifetime_s: StrictInt = Field(default=3600, ge=60, le=MAX_LIFETIME_S)
    required_amr: tuple[AmrValue, ...] = Field(default=("mfa",), min_length=1)

    @property
    def issuer(self) -> str:
        return f"{ENTRA_AUTHORITY}/{self.tenant_id}/v2.0"


def load_auth_config(path: Path) -> AuthConfig:
    try:
        return AuthConfig.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:  # json.JSONDecodeError is a ValueError
        raise AuthConfigError(f"cannot load auth config from {path}: {exc}") from exc


def _stamp(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _int_claim(claims: Mapping[str, Any], name: str) -> int:
    value = claims.get(name)
    if type(value) is not int:  # bool is an int subclass; a string or float is malformed
        raise AuthError("missing-claim", f"{name} must be an integer")
    return value


def _str_claim(claims: Mapping[str, Any], name: str) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value:
        raise AuthError("missing-claim", f"{name} must be a non-empty string")
    return value


class TokenValidator:
    """Checks approver ID tokens against one `AuthConfig`. Holds no mutable state."""

    def __init__(self, config: AuthConfig, identities: IdentityStore | None = None) -> None:
        keys: dict[str, RsaPublicKey] = {}
        for jwk in config.keys:
            if jwk.kid in keys:
                raise AuthConfigError(f"duplicate key id {jwk.kid!r}")
            keys[jwk.kid] = jwk.public_key()
        if identities is not None:
            unknown = sorted(i for i in config.approvers.values() if i not in identities)
            if unknown:
                raise AuthConfigError(f"approver map names unknown identities: {', '.join(unknown)}")
        self.config = config
        self._keys = keys

    def validate(self, token: str | None, now: datetime) -> ApproverAuth:
        """The approver this token proves, or AuthError. `now` must be timezone-aware."""
        if not token:
            raise AuthError("no-token")
        try:
            jws = parse_compact(token)
        except JwsError as exc:
            raise AuthError("malformed", str(exc)) from None
        header = jws.header
        if header.get("alg") != "RS256":
            raise AuthError("bad-algorithm", "only RS256 is accepted")
        if "crit" in header or any(k in header for k in ("jwk", "jku", "x5u", "x5c")):
            raise AuthError("bad-algorithm", "embedded keys and critical extensions are refused")
        if header.get("typ", "JWT") != "JWT":
            raise AuthError("malformed", "typ must be JWT")
        kid = header.get("kid")
        key = self._keys.get(kid) if isinstance(kid, str) else None
        if key is None:
            raise AuthError("unknown-key")
        if not verify_rs256(key, jws.signing_input, jws.signature):
            raise AuthError("bad-signature")
        return self._claims(jws.payload, now)

    def _claims(self, claims: Mapping[str, Any], now: datetime) -> ApproverAuth:
        cfg = self.config
        if claims.get("iss") != cfg.issuer:
            raise AuthError("wrong-issuer")
        if claims.get("aud") != cfg.client_id:
            raise AuthError("wrong-audience")
        if claims.get("tid") != cfg.tenant_id:
            raise AuthError("wrong-tenant")
        if claims.get("ver") != "2.0":
            raise AuthError("wrong-version")
        t = int(now.timestamp())
        exp, iat = _int_claim(claims, "exp"), _int_claim(claims, "iat")
        nbf = _int_claim(claims, "nbf") if "nbf" in claims else iat
        if exp <= t - cfg.leeway_s:
            raise AuthError("expired")
        if iat > t + cfg.leeway_s:
            raise AuthError("issued-in-future")
        if nbf > t + cfg.leeway_s:
            raise AuthError("not-yet-valid")
        if exp - iat > cfg.max_lifetime_s:
            raise AuthError("lifetime-too-long")
        amr = claims.get("amr")
        if not isinstance(amr, list) or not amr or not all(isinstance(m, str) for m in amr):
            raise AuthError("missing-claim", "amr must be a non-empty list of strings")
        if not set(cfg.required_amr) & set(amr):
            raise AuthError("no-mfa", "the sign-in did not use a required method")
        sid, oid = _str_claim(claims, "sid"), _str_claim(claims, "oid")
        identity = cfg.approvers.get(oid)
        if identity is None:
            raise AuthError("unknown-approver")
        try:
            return ApproverAuth(
                method="entra-id-token",
                identity=identity,
                oid=oid,
                tid=cfg.tenant_id,
                amr=tuple(amr),
                sid=sid,
                issued_at=_stamp(iat),
                expires_at=_stamp(exp),
            )
        except ValidationError:
            raise AuthError("malformed", "a claim has an unexpected shape") from None
