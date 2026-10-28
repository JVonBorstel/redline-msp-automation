"""Content-free JSON operational logs (B-83, C-11 never-log list, STD-AU).

One line is one JSON object::

    {"client","component","dropped"?,"duration_ms"?,"event","fields"?,"level","outcome","request_id","ts","v"}

**Allow-list, not scrub-list.** A line is built only from values that pass a shape check for their field. Anything
else is dropped (and counted in ``dropped``), never trimmed or masked into the line:

- ``component`` and ``event`` are lowercase identifiers chosen by the code that logs; ``outcome`` is one of
  ``ok denied error skipped unknown``; ``level`` is a stdlib level name; ``client`` is a client id, ``_msp`` when the
  line is not about one client, or ``invalid-client``; ``request_id`` is a short safe identifier.
- ``fields`` accepts only the names in ``FIELD_RULES``: counts and lengths (non-negative integers), flags, codes from
  a closed vocabulary (provider, status, mode, data class, reason code) and three identifiers from config (lever,
  task, model). Free text has no field to live in: a string with a space, an upper-case letter, a newline or more
  than 64 characters cannot pass any of the checks.
- Every string that passes is also run through the audit redactor (``core.audit.redact``): a value it would change
  (bearer header, ``sk-`` key, JWT, long hex or base64 run) is dropped.
- Nothing calls ``repr`` or ``str`` on a value of unknown type, and exceptions raised while logging are swallowed, so
  logging cannot leak through an error message or break the caller.

``ContentFreeFilter`` applies the same rule to records that did not come from ``OpsLogger`` (a library logging to
``redline.ops.*``): their message, arguments, exception and stack text are discarded and one ``log.unstructured`` line
is written. ``check_line`` re-validates a finished line and is what the tests use as the oracle.

Residual (specs/B-83.md): ``lever``, ``task`` and ``model`` accept any lowercase identifier, so a caller that put a
one-word lowercase string there would get it logged. The gateway and the runner pass only registry, route and config
names there.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import IO, Any

from core.audit.redact import redact_text
from core.obs.context import current_client, current_request_id

LOGGER_NAME = "redline.ops"
SCHEMA_VERSION = 1
MSP_LABEL = "_msp"
INVALID_CLIENT = "invalid-client"
NO_REQUEST = "req-none"
INVALID_REQUEST = "req-invalid"

OUTCOMES = frozenset({"ok", "denied", "error", "skipped", "unknown"})
LEVELS: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

_COMPONENT = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_EVENT = re.compile(r"[a-z][a-z0-9._-]{0,63}")
_CLIENT = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
_REQUEST = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_TS = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
_IDENT = re.compile(r"[a-z0-9][a-z0-9._:-]{0,63}")
_DATA_CLASS = re.compile(r"DC-[0-6]")
_REASON = re.compile(
    r"ok|blocked|no-route|provider-disabled|hosted-refused|circuit-open|provider-error|crashed"
    r"|budget:(?:global|client|agent):(?:calls|tokens)"
)
_INT_MAX = 10**12


def _is_count(value: object) -> bool:
    return type(value) is int and 0 <= value <= _INT_MAX


def _is_flag(value: object) -> bool:
    return type(value) is bool


def _matches(pattern: re.Pattern[str]) -> Callable[[object], bool]:
    def check(value: object) -> bool:
        return isinstance(value, str) and pattern.fullmatch(value) is not None and redact_text(value) == value

    return check


def _one_of(*allowed: str) -> Callable[[object], bool]:
    return lambda value: isinstance(value, str) and value in allowed


FIELD_RULES: dict[str, Callable[[object], bool]] = {
    "input_chars": _is_count,
    "prompt_chars": _is_count,
    "completion_chars": _is_count,
    "latency_ms": _is_count,
    "prompt_est": _is_count,
    "completion_est": _is_count,
    "seq": _is_count,
    "count": _is_count,
    "attempts": _is_count,
    "records": _is_count,
    "changes": _is_count,
    "lever_version": _is_count,
    "ok": _is_flag,
    "applied": _is_flag,
    "status": _one_of("ok", "denied", "error"),
    "provider": _one_of("mock", "ollama", "azure_openai", "anthropic"),
    "mode": _one_of("dry-run", "execute", "approve", "reject", "pause", "resume", "invalid"),
    "actor_kind": _one_of("human", "agent", "unknown"),
    "data_class": _matches(_DATA_CLASS),
    "reason": _matches(_REASON),
    "lever": _matches(_IDENT),
    "task": _matches(_IDENT),
    "model": _matches(_IDENT),
}
REQUIRED_KEYS = frozenset({"v", "ts", "level", "request_id", "component", "event", "outcome", "client"})
ALLOWED_KEYS = REQUIRED_KEYS | {"duration_ms", "fields", "dropped"}


def _text(pattern: re.Pattern[str], value: object, fallback: str) -> str:
    if isinstance(value, str) and pattern.fullmatch(value) is not None and redact_text(value) == value:
        return value
    return fallback


def _stamp(value: object) -> str:
    when = value if isinstance(value, datetime) and value.tzinfo is not None else datetime.now(UTC)
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sanitize_record(raw: Mapping[str, Any]) -> dict[str, Any]:
    """The line for ``raw``: every value checked, every doubtful one replaced by a fixed label or dropped.

    ``raw`` may hold ``component event outcome level client request_id duration_ms ts fields``. A missing client
    falls back to the request scope's, then to ``_msp``; a missing request id to the scope's, then to ``req-none``.
    """
    dropped = 0
    client_in = raw.get("client")
    if client_in is None:
        client_in = current_client()
    client = MSP_LABEL if client_in is None or client_in == MSP_LABEL else _text(_CLIENT, client_in, INVALID_CLIENT)
    request_in = raw.get("request_id")
    if request_in is None:
        request_in = current_request_id()
    request_id = NO_REQUEST if request_in is None else _text(_REQUEST, request_in, INVALID_REQUEST)
    outcome_in = raw.get("outcome")
    level_in = raw.get("level")
    record: dict[str, Any] = {
        "v": SCHEMA_VERSION,
        "ts": _stamp(raw.get("ts")),
        "level": level_in if isinstance(level_in, str) and level_in in LEVELS else "info",
        "request_id": request_id,
        "component": _text(_COMPONENT, raw.get("component"), "invalid-component"),
        "event": _text(_EVENT, raw.get("event"), "invalid-event"),
        "outcome": outcome_in if isinstance(outcome_in, str) and outcome_in in OUTCOMES else "unknown",
        "client": client,
    }
    duration = raw.get("duration_ms")
    if duration is not None:
        if _is_count(duration):
            record["duration_ms"] = duration
        else:
            dropped += 1
    fields_in = raw.get("fields")
    kept: dict[str, Any] = {}
    if isinstance(fields_in, Mapping):
        for name, value in fields_in.items():
            if value is None:  # None means "not known", not a value
                continue
            rule = FIELD_RULES.get(name) if isinstance(name, str) else None
            if rule is not None and rule(value):
                kept[name] = value
            else:
                dropped += 1
    elif fields_in is not None:
        dropped += 1
    if kept:
        record["fields"] = dict(sorted(kept.items()))
    if dropped:
        record["dropped"] = dropped
    return record


def _dump(record: Mapping[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def check_line(line: str) -> list[str]:
    """Why ``line`` is not a content-free ops line (empty list when it is). Messages never repeat the line's values."""
    try:
        body = json.loads(line)
    except ValueError:
        return ["not JSON"]
    if not isinstance(body, dict):
        return ["not a JSON object"]
    problems = ["unexpected key"] * len(set(body) - ALLOWED_KEYS)
    problems += [f"missing key {key}" for key in sorted(REQUIRED_KEYS - set(body))]
    checks: dict[str, Callable[[object], bool]] = {
        "v": lambda v: v == SCHEMA_VERSION and type(v) is int,
        "ts": lambda v: isinstance(v, str) and _TS.fullmatch(v) is not None,
        "level": lambda v: isinstance(v, str) and v in LEVELS,
        "request_id": _matches(_REQUEST),
        "component": _matches(_COMPONENT),
        "event": _matches(_EVENT),
        "outcome": lambda v: isinstance(v, str) and v in OUTCOMES,
        "client": lambda v: v == MSP_LABEL or _matches(_CLIENT)(v),
        "duration_ms": _is_count,
        "dropped": _is_count,
    }
    for key, check in checks.items():
        if key in body and not check(body[key]):
            problems.append(f"bad value for {key}")
    fields = body.get("fields")
    if "fields" in body:
        if not isinstance(fields, dict) or not fields:
            problems.append("bad value for fields")
        else:
            for name, value in fields.items():
                rule = FIELD_RULES.get(name)
                if rule is None:
                    problems.append("unexpected field name")
                elif not rule(value):
                    problems.append(f"bad value for field {name}")
    return problems


def _ensure_line(record: logging.LogRecord) -> str:
    """The sanitized line for a record, built once; a pre-set line is trusted only if it passes ``check_line``."""
    existing = getattr(record, "ops_line", None)
    if isinstance(existing, str) and not check_line(existing):
        return existing
    line = _dump(
        sanitize_record(
            {
                "component": record.name,
                "event": "log.unstructured",
                "outcome": "unknown",
                "level": record.levelname.lower(),
                "ts": datetime.fromtimestamp(record.created, UTC),
            }
        )
    )
    record.ops_line = line
    return line


class ContentFreeFilter(logging.Filter):
    """Replace whatever a record carries with its sanitized line, so no handler downstream can see the original."""

    def filter(self, record: logging.LogRecord) -> bool:
        line = _ensure_line(record)
        record.msg = line
        record.args = None
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


class JsonLineFormatter(logging.Formatter):
    """Format a record as its sanitized line, whether or not the filter ran first."""

    def format(self, record: logging.LogRecord) -> str:
        return _ensure_line(record)


@dataclass
class Span:
    """What a ``timed`` block will log: set ``outcome`` (default ``ok``) and add ``fields`` before it ends."""

    outcome: str = "ok"
    fields: dict[str, Any] = field(default_factory=dict)


def _level_for(outcome: object) -> str:
    return "error" if outcome == "error" else "warning" if outcome == "denied" else "info"


class OpsLogger:
    """Writes one content-free line per ``log`` call to the ``redline.ops`` logger. Never raises."""

    def __init__(
        self,
        component: str,
        *,
        clock: Callable[[], datetime] | None = None,
        timer: Callable[[], float] | None = None,
    ) -> None:
        self.component = component
        self._clock = clock or (lambda: datetime.now(UTC))
        self._timer = timer or time.perf_counter
        self._logger = logging.getLogger(LOGGER_NAME)

    def log(
        self,
        event: str,
        outcome: str,
        *,
        client: str | None = None,
        request_id: str | None = None,
        duration_ms: int | None = None,
        level: str | None = None,
        **fields: Any,
    ) -> None:
        """Log ``event`` with ``outcome``. ``fields`` are checked against ``FIELD_RULES``; unknown ones are dropped."""
        with contextlib.suppress(Exception):  # logging must never break, or leak through, the code it observes
            chosen = level if isinstance(level, str) and level in LEVELS else _level_for(outcome)
            line = _dump(
                sanitize_record(
                    {
                        "component": self.component,
                        "event": event,
                        "outcome": outcome,
                        "level": chosen,
                        "client": client,
                        "request_id": request_id,
                        "duration_ms": duration_ms,
                        "ts": self._clock(),
                        "fields": fields,
                    }
                )
            )
            self._logger.log(LEVELS[json.loads(line)["level"]], line, extra={"ops_line": line})

    @contextmanager
    def timed(
        self, event: str, *, client: str | None = None, request_id: str | None = None, **fields: Any
    ) -> Iterator[Span]:
        """Time a block and log it once: ``ok`` unless the block set another outcome or raised (then ``error``)."""
        span = Span(fields=dict(fields))
        started = self._timer()
        try:
            yield span
        except BaseException:
            span.outcome = "error"
            raise
        finally:
            elapsed = round((self._timer() - started) * 1000)
            self.log(event, span.outcome, client=client, request_id=request_id, duration_ms=elapsed, **span.fields)


_base = logging.getLogger(LOGGER_NAME)
_base.setLevel(logging.INFO)
_base.propagate = False
_base.addHandler(logging.NullHandler())


def configure(stream: IO[str] | None = None, *, level: int = logging.INFO) -> logging.Handler:
    """Send ops lines to ``stream`` (default stderr). Returns the handler; pass it to ``unconfigure`` to remove it."""
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLineFormatter())
    handler.addFilter(ContentFreeFilter())
    handler.setLevel(level)
    _base.addHandler(handler)
    return handler


def unconfigure(handler: logging.Handler) -> None:
    _base.removeHandler(handler)
    handler.close()
