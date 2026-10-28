"""Build snapshot parts from the real stores (B-83): audit events from a chain file, and a chain verification result.

Both are read-only. ``audit_events_from_log`` keeps only ``ts``, ``client``, ``event``, the result's fixed ``reason``
code and the provider name; the record's params, result text and request id are not copied.
Approval and dead-letter counts are not read here: they come from the queue stores (B-82) and are passed into the
snapshot by whoever builds it (see specs/B-83.md, unverified list).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from core.audit.chain import head_path_for, verify_chain
from workflows.monitoring.evaluator import AuditEvent, ChainCheck

_REASON = re.compile(r"[a-z0-9][a-z0-9:-]{0,63}")
_SLUG = re.compile(r"[a-z0-9_][a-z0-9._:-]{0,63}")


def _code(value: object, pattern: re.Pattern[str]) -> str | None:
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def audit_events_from_log(path: Path) -> list[AuditEvent]:
    """One ``AuditEvent`` per record in the chain file. An unreadable line is skipped (the chain check flags it)."""
    events: list[AuditEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
            event = _code(record.get("event"), _SLUG)
            if event is None:
                continue
            result, params = record.get("result"), record.get("params")
            events.append(
                AuditEvent(
                    ts=record["ts"],
                    client=_code(record.get("client"), _SLUG),
                    event=event,
                    reason=_code(result.get("reason") if isinstance(result, dict) else None, _REASON),
                    provider=_code(params.get("provider") if isinstance(params, dict) else None, _SLUG),
                )
            )
        except (ValueError, KeyError, AttributeError):
            continue
    return events


def chain_check(path: Path) -> ChainCheck:
    """Verify one chain (against its head pin when present). A missing or unreadable log is a failure, not a crash."""
    scope = path.stem if _SLUG.fullmatch(path.stem) else "unknown"
    head = head_path_for(path)
    try:
        result = verify_chain(path, head if head.exists() else None)
    except OSError:
        return ChainCheck(scope=scope, ok=False)
    return ChainCheck(scope=scope, ok=result.ok, broken_seq=None if result.ok else result.broken_seq)
