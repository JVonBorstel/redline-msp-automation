"""A mock Entra ID token issuer for tests and local trials (B-89). MOCK: not Microsoft Entra ID.

It makes a 2048-bit RSA key in memory at run time (never written to the repo), publishes the public
half as a JWK and signs synthetic RS256 ID tokens with Entra's v2.0 claim names. A seeded issuer is
deterministic so tests are repeatable; an unseeded one draws from the operating system's random
source. Pure-Python key generation takes about a second. It exists so the validator can be tested
end to end offline; it is not a signing service and must never hold a real key.
"""

from __future__ import annotations

import random
import secrets
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from core.audit import canonical_json
from core.auth.jws import RsaPublicKey, b64url_encode, emsa_pkcs1_v1_5_sha256
from core.auth.validator import ENTRA_AUTHORITY

_SMALL_PRIMES = (3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97)
_E = 65537


def _probable_prime(n: int, rng: random.Random, rounds: int = 40) -> bool:
    for p in _SMALL_PRIMES:
        if n % p == 0:
            return n == p
    d, s = n - 1, 0
    while d % 2 == 0:
        d, s = d // 2, s + 1
    for _ in range(rounds):
        x = pow(rng.randrange(2, n - 2), d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _prime(bits: int, rng: random.Random) -> int:
    while True:
        candidate = rng.getrandbits(bits) | (1 << (bits - 1)) | (1 << (bits - 2)) | 1
        if candidate % _E != 1 and _probable_prime(candidate, rng):
            return candidate


class MockIssuer:
    """MOCK Entra tenant: one signing key, one tenant id. Synthetic values only."""

    def __init__(self, tenant_id: str, *, kid: str = "mock-key-1", bits: int = 2048, seed: int | None = None) -> None:
        rng: random.Random = random.Random(seed) if seed is not None else secrets.SystemRandom()  # noqa: S311 - seeded only for repeatable tests
        while True:
            p, q = _prime(bits // 2, rng), _prime(bits // 2, rng)
            if p != q and (p * q).bit_length() == bits:
                break
        self.tenant_id = tenant_id
        self.kid = kid
        self.public = RsaPublicKey(n=p * q, e=_E)
        self._d = pow(_E, -1, (p - 1) * (q - 1))

    @property
    def issuer(self) -> str:
        return f"{ENTRA_AUTHORITY}/{self.tenant_id}/v2.0"

    def jwk(self) -> dict[str, str]:
        size = self.public.size_bytes
        return {
            "kty": "RSA",
            "use": "sig",
            "kid": self.kid,
            "n": b64url_encode(self.public.n.to_bytes(size, "big")),
            "e": b64url_encode(_E.to_bytes(3, "big")),
        }

    def claims(self, *, audience: str, oid: str, now: datetime, lifetime_s: int = 3600) -> dict[str, Any]:
        """Entra v2.0 ID token claims for one synthetic sign-in with MFA and a fresh session id."""
        iat = int(now.timestamp())
        return {
            "ver": "2.0",
            "iss": self.issuer,
            "aud": audience,
            "tid": self.tenant_id,
            "oid": oid,
            "sub": "mock-subject-" + oid[:8],
            "iat": iat,
            "nbf": iat,
            "exp": iat + lifetime_s,
            "amr": ["pwd", "mfa"],
            "sid": str(uuid.uuid4()),
            "name": "Synthetic approver",
        }

    def sign(self, claims: Mapping[str, Any], header: Mapping[str, Any] | None = None) -> str:
        """A compact RS256 JWS over `claims` (header defaults to this issuer's alg, kid and typ)."""
        head = dict(header) if header is not None else {"alg": "RS256", "kid": self.kid, "typ": "JWT"}
        signing_input = f"{b64url_encode(canonical_json(head))}.{b64url_encode(canonical_json(dict(claims)))}"
        size = self.public.size_bytes
        em = emsa_pkcs1_v1_5_sha256(signing_input.encode("ascii"), size)
        signature = pow(int.from_bytes(em, "big"), self._d, self.public.n).to_bytes(size, "big")
        return f"{signing_input}.{b64url_encode(signature)}"
