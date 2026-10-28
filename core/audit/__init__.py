"""Append-only, hash-chained audit log with a head pin and a verifier (specs/phase-1.md deliverable 3).

Records are version 2 from B-17 (specs/B-17.md, STD-AU-2); v1 logs still verify.
"""

from core.audit.chain import (
    ACTOR_KINDS,
    EVENTS,
    GENESIS_HASH,
    MODES,
    RECORD_FIELDS_V1,
    RECORD_FIELDS_V2,
    RECORD_VERSION,
    ActorKind,
    AuditError,
    AuditLog,
    AuditMode,
    Event,
    Mode,
    VerifyResult,
    canonical_json,
    default_event,
    head_path_for,
    new_request_id,
    record_hash,
    verify_chain,
)
from core.audit.redact import REDACTED, redact

__all__ = [
    "ACTOR_KINDS",
    "EVENTS",
    "GENESIS_HASH",
    "MODES",
    "RECORD_FIELDS_V1",
    "RECORD_FIELDS_V2",
    "RECORD_VERSION",
    "REDACTED",
    "ActorKind",
    "AuditError",
    "AuditLog",
    "AuditMode",
    "Event",
    "Mode",
    "VerifyResult",
    "canonical_json",
    "default_event",
    "head_path_for",
    "new_request_id",
    "record_hash",
    "redact",
    "verify_chain",
]
