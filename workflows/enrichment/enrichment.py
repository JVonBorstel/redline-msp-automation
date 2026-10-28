"""Alert enrichment and risky sign-in review (B-44, specs/B-44.md; W-SEC-02, W-IDM-05, W-SD-07; C-20, C-27, C-12).

``enrich`` gives the analyst one pack for one alert: user, device and recent sign-in facts, each citing the read lever
and the field it came from. Only read levers are called (R0, audited as who-asked-about-whom, results never written to
the audit, D-017). A pack is built under one client: the alert's client must be the client asked for, and every call
passes that client. A fact the data does not hold is a ``gaps`` entry, never a guess.

``review_risky_users`` reads ``risk.list-users`` and lists the levers a lead could approve (names and params only,
``executed`` False). It imports no write path. Entra ID P2 is UNVERIFIED per client, so a client with no risk data gets
an empty review and the note, not "all clear".

Two views (DC-3). The technician view holds times and places; the prompt view marks those facts ``sensitive`` and
leaves them out. Free text (names, titles) is untrusted (C-12): text the injection detector flags is withheld.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.guard import detect_injection
from core.levers import LeverRunner

USER_LEVER = "risk.user-facts"
DEVICE_LEVER = "risk.device-facts"
SIGNINS_LEVER = "signins.list"
RISK_LEVER = "risk.list-users"
READ_LEVERS = (USER_LEVER, DEVICE_LEVER, SIGNINS_LEVER, RISK_LEVER)
WITHHELD = "[text withheld: it looks like instructions]"
_AT_RISK = frozenset({"atRisk", "confirmedCompromised"})


class EnrichmentError(ValueError):
    """The pack or review cannot be built; nothing was concluded."""


@dataclass(frozen=True)
class Pack:
    client: str
    alert_id: str
    entity_kind: str
    entity_id: str
    facts: tuple[dict[str, Any], ...]
    gaps: tuple[str, ...]
    audit_seqs: tuple[int, ...]
    executed: bool = False  # always False: this workflow never runs a write lever


@dataclass(frozen=True)
class Review:
    client: str
    users: tuple[dict[str, Any], ...]
    recommended: tuple[dict[str, Any], ...]
    note: str
    executed: bool = False  # always False: recommendations are names and params only


def _fact(text: str, lever: str, field: str, *, sensitive: bool = False) -> dict[str, Any]:
    return {"fact": text, "lever": lever, "field": field, "sensitive": sensitive}


def _text(value: Any) -> str:
    s = str(value or "")
    return WITHHELD if s and detect_injection(s).flagged else s


def _read(runner: LeverRunner, lever: str, params: dict[str, Any], client: str, identity: str) -> Any:
    result = runner.invoke(lever, params, identity=identity, client=client, mode="execute")
    if not result.ok:
        raise EnrichmentError(f"cannot read {lever}: {result.reason}")
    return result


def enrich(runner: LeverRunner, client: str, alert: Any, identity: str) -> Pack:
    """Build the pack for ``alert`` (an ``Alert`` or anything with id, client, entity_kind, entity_id)."""
    if alert.client != client:
        raise EnrichmentError("the alert belongs to another client; a pack is built under one client")
    facts: list[dict[str, Any]] = []
    gaps: list[str] = []
    seqs: list[int] = []
    if alert.entity_kind != "user":
        gaps.append(f"{alert.entity_kind} alerts: no read lever finds one by id yet; look at its owner")
        return Pack(client, alert.id, alert.entity_kind, alert.entity_id, (), tuple(gaps), ())
    upn = alert.entity_id

    res = _read(runner, USER_LEVER, {"upn": upn}, client, identity)
    seqs.append(res.audit_seq)
    u = res.data
    facts.append(_fact(f"name: {_text(u.get('displayName'))}", USER_LEVER, "displayName"))
    if u.get("jobTitle"):
        facts.append(_fact(f"job title: {_text(u.get('jobTitle'))}", USER_LEVER, "jobTitle"))
    facts.append(_fact(f"account enabled: {u.get('accountEnabled')}", USER_LEVER, "accountEnabled"))
    kinds = u.get("authenticationMethods") or []
    if kinds:
        facts.append(_fact(f"sign-in methods: {', '.join(kinds)}", USER_LEVER, "authenticationMethods"))
    else:
        gaps.append("authentication methods: none on record for this person")

    res = _read(runner, DEVICE_LEVER, {"upn": upn}, client, identity)
    seqs.append(res.audit_seq)
    devices = [d for d in res.data if isinstance(d, dict)]
    if not devices:
        gaps.append("devices: none on record for this person")
    for d in devices:
        state = f"{d.get('os')}, managed {d.get('managed')}, compliance {d.get('compliance')}"
        facts.append(_fact(f"device {_text(d.get('name'))}: {state}", DEVICE_LEVER, "devices[].compliance"))

    res = _read(runner, SIGNINS_LEVER, {"upn": upn, "limit": 10}, client, identity)
    seqs.append(res.audit_seq)
    events = [e for e in res.data if isinstance(e, dict)]
    if not events:
        gaps.append("sign-ins: none on record for this person")
    else:
        failed = sum(1 for e in events if (e.get("status") or {}).get("errorCode") not in (0, None))
        facts.append(_fact(f"{failed} of the last {len(events)} sign-ins failed", SIGNINS_LEVER, "status.errorCode"))
        latest = events[0]
        loc = latest.get("location") or {}
        when = f"latest sign-in at {latest.get('createdDateTime')}"
        facts.append(_fact(when, SIGNINS_LEVER, "createdDateTime", sensitive=True))
        facts.append(
            _fact(
                f"latest sign-in from {loc.get('city')}, {loc.get('countryOrRegion')}",
                SIGNINS_LEVER,
                "location",
                sensitive=True,
            )
        )
    return Pack(client, alert.id, alert.entity_kind, upn, tuple(facts), tuple(gaps), tuple(seqs))


def prompt_text(pack: Pack) -> str:
    """Plain text for a model: facts not marked sensitive (no time, place or address)."""
    lines = [f"Alert {pack.alert_id} ({pack.entity_kind} {pack.entity_id}):"]
    lines += [f"- {f['fact']}" for f in pack.facts if not f["sensitive"]]
    lines += [f"- gap: {g}" for g in pack.gaps]
    return "\n".join(lines)


def _plan(upn: str, row: dict[str, Any]) -> list[dict[str, Any]]:
    level = row.get("riskLevel")
    names = ["user.revoke-sessions", "user.reset-mfa"] if level == "high" else ["user.revoke-sessions"]
    if level in ("high", "medium"):
        return [{"lever": n, "params": {"upn": upn}, "because": f"riskLevel {level}", "executed": False} for n in names]
    return []


def review_risky_users(runner: LeverRunner, client: str, identity: str) -> Review:
    """List the client's risky users and the levers a lead could approve. Runs none of them."""
    result = _read(runner, RISK_LEVER, {}, client, identity)
    data = result.data if isinstance(result.data, dict) else {}
    users = tuple(r for r in data.get("value", []) if isinstance(r, dict))
    recommended: list[dict[str, Any]] = []
    for row in users:
        if row.get("riskState") in _AT_RISK and not row.get("isDeleted"):
            for step in _plan(str(row.get("userPrincipalName")), row):
                if runner.registry.get(step["lever"]) is None:
                    raise EnrichmentError(f"recommended lever {step['lever']} is not registered")
                recommended.append(
                    {**step, "note": "A technician proposes it; a lead approves it after callback verification."}
                )
    return Review(client, users, tuple(recommended), str(data.get("note", "")))
