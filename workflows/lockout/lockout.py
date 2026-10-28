"""Sign-in failure and lockout investigation (B-39, specs/B-39.md; W-IDM-03; C-20, C-27, C-12).

One technician asks "why can't this person sign in?". ``investigate`` reads that user's recent sign-ins through the
``signins.list`` lever (R0, audited who-asked-about-whom, results never written to the audit), maps each failure code to
a plain cause from the cited table in ``codes.json``, and suggests the lever a lead could approve. It never executes
anything: the only lever it calls is the read lever, and a suggestion is a name and params in a result.

Two views (DC-3, minimum necessary). The **technician view** has the times, apps, IP addresses and places, for a person
to read. The **prompt view** (what may reach a model) has failure codes, plain causes, counts and one boolean about
the pattern; it never contains an IP address, a place, a time or any log text. ``prompt_text`` is built from the prompt
view only. The log's free text (failureReason, additionalDetails) is untrusted (C-12): it is scanned and a count is
raised, but it is never copied into either view.

No model is called; the table and the thresholds are plain configuration a reviewer can read (D-022).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.guard import detect_injection
from core.levers import LeverRunner

DEFAULT_CODES_PATH = Path(__file__).with_name("codes.json")
SIGNINS_LEVER = "signins.list"
UNKNOWN_CAUSE = "A code that is not in the table; read the sign-in in the technician view and the Microsoft Learn page."


class LockoutError(ValueError):
    """The table or the sign-in read is bad; nothing was concluded."""


@dataclass(frozen=True)
class CodeRow:
    code: int
    name: str
    status: str
    cause: str
    next: str
    lever: str | None


@dataclass(frozen=True)
class CodeTable:
    source: str
    rows: dict[int, CodeRow]
    guess_codes: frozenset[int]
    guess_min_failures: int
    guess_min_ips: int


def load_codes(path: Path = DEFAULT_CODES_PATH) -> CodeTable:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        rows = {int(r["code"]): CodeRow(**{k: r[k] for k in CodeRow.__dataclass_fields__}) for r in raw["codes"]}
        pattern = raw["guessing_pattern"]
        if raw["version"] != 1 or len(rows) != len(raw["codes"]):
            raise ValueError("bad version or duplicate code")
        if any(r.status not in ("verified", "UNVERIFIED") for r in rows.values()):
            raise ValueError("status must be verified or UNVERIFIED")
        return CodeTable(
            source=str(raw["source"]),
            rows=rows,
            guess_codes=frozenset(int(c) for c in pattern["password_failure_codes"]),
            guess_min_failures=int(pattern["min_failures"]),
            guess_min_ips=int(pattern["min_distinct_ips"]),
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise LockoutError(f"cannot load the sign-in code table from {path}: {exc}") from exc


@dataclass(frozen=True)
class Investigation:
    client: str
    upn: str
    technician_view: dict[str, Any]
    prompt_view: dict[str, Any]
    audit_seq: int
    executed: bool = False  # always False: this workflow never runs a write lever


def _failure_rows(events: list[dict[str, Any]]) -> list[tuple[dict[str, Any], int]]:
    out = []
    for e in events:
        status = e.get("status")
        code = status.get("errorCode") if isinstance(status, dict) else None
        if isinstance(code, int) and not isinstance(code, bool) and code != 0:
            out.append((e, code))
    return out


def _flagged_text(event: dict[str, Any]) -> bool:
    status = event.get("status")
    if not isinstance(status, dict):
        return False
    return any(detect_injection(str(status.get(k) or "")).flagged for k in ("failureReason", "additionalDetails"))


def investigate(
    runner: LeverRunner,
    client: str,
    upn: str,
    identity: str,
    table: CodeTable | None = None,
    limit: int = 10,
) -> Investigation:
    """Read the user's recent sign-ins and explain the failures. Raises ``LockoutError`` if the read is refused."""
    table = table or load_codes()
    result = runner.invoke(
        SIGNINS_LEVER, {"upn": upn, "limit": limit}, identity=identity, client=client, mode="execute"
    )
    if not result.ok or not isinstance(result.data, list):
        raise LockoutError(f"cannot read sign-ins: {result.reason}")
    events: list[dict[str, Any]] = [e for e in result.data if isinstance(e, dict)]
    failures = _failure_rows(events)

    counts = Counter(code for _, code in failures)
    causes: list[dict[str, Any]] = []
    suggestions: list[dict[str, Any]] = []
    for code, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        row = table.rows.get(code)
        causes.append(
            {
                "code": code,
                "count": count,
                "name": row.name if row else "unknown",
                "cause": row.cause if row else UNKNOWN_CAUSE,
                "next": row.next if row else "Look the code up before choosing a fix.",
                "status": row.status if row else "UNVERIFIED",
                "source": table.source,
            }
        )
        if row and row.lever and not any(s["lever"] == row.lever for s in suggestions):
            suggestions.append(
                {
                    "lever": row.lever,
                    "params": {"upn": upn},
                    "because": code,
                    "executed": False,
                    "note": "A technician proposes it; a lead approves it after callback verification.",
                }
            )

    password_failures = [e for e, code in failures if code in table.guess_codes]
    ips = {str(e.get("ipAddress")) for e in password_failures}
    guessing = len(password_failures) >= table.guess_min_failures and len(ips) >= table.guess_min_ips
    if guessing:
        suggestions.append(
            {
                "lever": None,
                "params": {},
                "because": "pattern",
                "executed": False,
                "note": "Possible password guessing: tell the security lead before unlocking or resetting anything.",
            }
        )

    prompt_view: dict[str, Any] = {
        "user": upn,
        "signins_read": len(events),
        "failures": len(failures),
        "causes": causes,
        "possible_password_guessing": guessing,
        "log_text_flagged_as_instructions": sum(1 for e in events if _flagged_text(e)),
        "suggestions": suggestions,
    }
    technician_view: dict[str, Any] = {
        **prompt_view,
        "distinct_ips_in_password_failures": len(ips),
        "events": [
            {
                "time": e.get("createdDateTime"),
                "app": e.get("appDisplayName"),
                "code": (e.get("status") or {}).get("errorCode"),
                "interactive": e.get("isInteractive"),
                "ip_address": e.get("ipAddress"),
                "location": e.get("location"),
            }
            for e in events
        ],
    }
    return Investigation(client, upn, technician_view, prompt_view, result.audit_seq)


def prompt_text(inv: Investigation) -> str:
    """Plain text for a model, from the prompt view only (no IP address, place, time or log text)."""
    v = inv.prompt_view
    lines = [f"User {v['user']}: {v['failures']} failed of {v['signins_read']} recent sign-ins."]
    for c in v["causes"]:
        lines.append(f"- code {c['code']} x{c['count']} ({c['status']}): {c['cause']}")
    if v["possible_password_guessing"]:
        lines.append("Pattern: possible password guessing.")
    for s in v["suggestions"]:
        lines.append(f"Suggested (not run): {s['lever'] or 'escalate'}")
    return "\n".join(lines)


def summary(inv: Investigation) -> dict[str, Any]:
    """The technician's view (the CLI prints this)."""
    return inv.technician_view
