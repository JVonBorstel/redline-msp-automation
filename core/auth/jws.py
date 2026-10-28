"""Compact JWS parsing and RS256 signature checks on the standard library only (B-89).

Guarantees:
- a token is three strict base64url parts (no padding, no other characters) under `MAX_TOKEN_BYTES`;
- the header and payload are JSON objects, or the token is refused;
- RS256 is RSASSA-PKCS1-v1_5 with SHA-256 (RFC 8017 section 8.2.2): the verifier rebuilds the whole
  expected encoded message and compares it in constant time, so a signature that only matches a
  prefix (the short-exponent forgery) never passes;
- an RSA key under `MIN_RSA_BITS` bits is refused.

Verification uses only public values, so it needs no constant-time arithmetic. Nothing here signs
real tokens; `core.auth.mock_issuer` signs synthetic ones for tests.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Any

MAX_TOKEN_BYTES = 8192
MIN_RSA_BITS = 2048
# DER prefix of DigestInfo for SHA-256 (RFC 8017 section 9.2, note 1).
SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")
_B64URL = re.compile(r"^[A-Za-z0-9_-]*$")


class JwsError(ValueError):
    """The token is not a well-formed compact JWS, or its signature does not verify."""


@dataclass(frozen=True, slots=True)
class RsaPublicKey:
    n: int
    e: int

    @property
    def bits(self) -> int:
        return self.n.bit_length()

    @property
    def size_bytes(self) -> int:
        return (self.n.bit_length() + 7) // 8


@dataclass(frozen=True, slots=True)
class CompactJws:
    header: dict[str, Any]
    payload: dict[str, Any]
    signing_input: bytes
    signature: bytes


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    """Strict base64url without padding; anything else raises JwsError."""
    if not _B64URL.match(text) or len(text) % 4 == 1:
        raise JwsError("not base64url")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise JwsError("not base64url") from exc


def int_from_b64url(text: str) -> int:
    raw = b64url_decode(text)
    if not raw or raw[0] == 0:
        raise JwsError("key integer is empty or has a leading zero byte")
    return int.from_bytes(raw, "big")


def _json_object(raw: bytes, what: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise JwsError(f"{what} is not JSON") from exc
    if not isinstance(value, dict):
        raise JwsError(f"{what} is not a JSON object")
    return value


def parse_compact(token: str) -> CompactJws:
    if not isinstance(token, str) or not token:
        raise JwsError("no token")
    if len(token.encode("utf-8", "replace")) > MAX_TOKEN_BYTES:
        raise JwsError("token too large")
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        raise JwsError("not a compact JWS (three non-empty parts)")
    header = _json_object(b64url_decode(parts[0]), "header")
    payload = _json_object(b64url_decode(parts[1]), "payload")
    signature = b64url_decode(parts[2])
    return CompactJws(header, payload, f"{parts[0]}.{parts[1]}".encode("ascii"), signature)


def emsa_pkcs1_v1_5_sha256(message: bytes, size_bytes: int) -> bytes:
    """The encoded message EM = 0x00 0x01 PS 0x00 DigestInfo(SHA-256(message)), PS at least 8 bytes of 0xff."""
    t = SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
    if size_bytes < len(t) + 11:
        raise JwsError("key too small for SHA-256")
    return b"\x00\x01" + b"\xff" * (size_bytes - len(t) - 3) + b"\x00" + t


def verify_rs256(key: RsaPublicKey, signing_input: bytes, signature: bytes) -> bool:
    """True when `signature` is a valid RS256 signature of `signing_input` under `key`."""
    if key.bits < MIN_RSA_BITS or key.e < 3 or key.e % 2 == 0:
        return False
    k = key.size_bytes
    if len(signature) != k:
        return False
    s = int.from_bytes(signature, "big")
    if s >= key.n:
        return False
    em = pow(s, key.e, key.n).to_bytes(k, "big")
    return hmac.compare_digest(em, emsa_pkcs1_v1_5_sha256(signing_input, k))
