"""Redact secrets before anything reaches the audit log.

Two rules, applied recursively to dicts and lists:
- a key whose name contains password, secret, token, key or credential (any case) has its value replaced;
- a string value that looks like a secret (bearer header, `sk-` API key, JWT, long hex or base64 run)
  has that part replaced, so the rest of the text stays readable.

This is a heuristic, not a guarantee (docs/THREAT_MODEL.md). It errs towards over-redaction.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

SENSITIVE_KEY = re.compile(r"password|passwd|secret|token|key|credential", re.IGNORECASE)

_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"),
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),
)
# A long base64-ish run only counts when it mixes letters and digits, so long plain words survive.
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/_-]{32,}={0,2}")
# Directory object ids (GUIDs) are identifiers, not secrets, and must stay readable in the evidence,
# including inside paths like /users/<guid>/authentication/methods/<guid>. The capture group makes
# re.split keep them, at the odd indexes.
_GUID_SPLIT = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")


def _redact_base64(match: re.Match[str]) -> str:
    run = match.group(0)
    has_letter = any(c.isalpha() for c in run)
    has_digit = any(c.isdigit() for c in run)
    return REDACTED if has_letter and has_digit else run


def _redact_piece(text: str) -> str:
    for pattern in _VALUE_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return _BASE64_RUN.sub(_redact_base64, text)


def redact_text(text: str) -> str:
    parts = _GUID_SPLIT.split(text)
    return "".join(part if i % 2 else _redact_piece(part) for i, part in enumerate(parts))


def redact(value: Any) -> Any:
    """Return a redacted deep copy of a JSON-like value. The input is not modified."""
    if isinstance(value, dict):
        return {str(k): (REDACTED if SENSITIVE_KEY.search(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    if value is None or isinstance(value, bool | int | float):
        return value
    # Anything else (bytes, objects from a buggy caller) is logged as its redacted repr, so a
    # denial can always be written: the audit record must never fail on odd input.
    return redact_text(repr(value))
