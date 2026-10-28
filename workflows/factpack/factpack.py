"""Fact packs for human-only identity decisions (B-37, specs/B-37.md).

Inventory W-ONB-15, W-IDM-04, W-IDM-06, W-IDM-07; controls C-20, C-27, C-42.

A fact pack puts what is known about ONE person or ONE Conditional Access policy of ONE client on a single page for
the human who decides. It assembles facts and nothing else: it registers no lever, proposes nothing, calls no runner,
queue or approval code, and writes no file. The decision, and for a termination the timing, stay with named humans
(docs/runbooks/urgent-termination.md, docs/runbooks/caller-verification.md).

Isolation (C-27). Every entry point takes the client explicitly (STD-ID-4). The tenant store is opened through the Graph
mock adapter for that client only; the baseline folder and the device list are picked by that client's id, so no other
client's file is opened. A target that is not in the client's own data gets the same words as an absent one.

Untrusted text (C-12). Names and failure texts that the injection detector flags are replaced by a fixed sentence and
listed under ``withheld``; text never steers anything here because nothing here acts. Phone numbers and other contact
details are never copied: authentication methods are listed by type only.

Sources. ``fixtures/tenant`` (users, sessions, sign-ins, groups: through ``GraphMock``), ``fixtures/graph/<dir>`` (the
Graph-shaped baseline: users, registration, directory roles, Conditional Access) and ``fixtures/devices.json`` next to
this file (a stand-in with UNVERIFIED field names). A section whose source has nothing on the target says so under
``gaps``; the pack never fills a gap with a guess.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters import AdapterError, BoundBinding
from adapters.graph import GraphMock
from core.guard import detect_injection
from core.levers import DEFAULT_TENANT_DIR
from core.paths import REPO_ROOT

CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
TARGET = re.compile(r"^[A-Za-z0-9._#@+-]{1,160}$")  # a user id or a UPN
DEFAULT_GRAPH_DIR = REPO_ROOT / "fixtures" / "graph"
DEFAULT_DEVICES_PATH = Path(__file__).with_name("fixtures") / "devices.json"

# Baseline folder per client (fixtures/graph/SOURCES.md: contoso is seeded with problems, clean is Fabrikam Capital).
BASELINE_DIR: dict[str, str] = {"contoso-dental": "contoso", "fabrikam-capital": "clean"}

PERSON_KINDS: dict[str, tuple[str, str]] = {
    "termination": ("W-ONB-15", "docs/runbooks/urgent-termination.md"),
    "caller": ("W-IDM-04", "docs/runbooks/caller-verification.md"),
    "role": ("W-IDM-07", "docs/runbooks/caller-verification.md"),
}
POLICY_KINDS: dict[str, tuple[str, str]] = {"policy": ("W-IDM-06", "")}
KINDS: tuple[str, ...] = (*PERSON_KINDS, *POLICY_KINDS)
WITHHELD = "[withheld: text flagged by the injection detector]"
RECENT_SIGNINS = 5
NO_PERSON = "no such person for this client"
NO_POLICY = "no such Conditional Access policy for this client"


class FactpackError(ValueError):
    """The input is bad or the target is not in this client's data; no pack was made."""


@dataclass
class _Ctx:
    withheld: list[str]

    def text(self, path: str, value: Any) -> Any:
        if isinstance(value, str) and value and detect_injection(value).flagged:
            self.withheld.append(path)
            return WITHHELD
        return value


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FactpackError(f"a source file is not readable: {path.name}") from exc


def _values(path: Path) -> list[dict[str, Any]]:
    data = _read(path)
    items = data.get("value") if isinstance(data, dict) else None
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _adapter(client: str, tenant_dir: Path) -> GraphMock:
    # The binding exists only to satisfy the adapter's constructor; tenant files without a tenantId are not matched.
    binding = BoundBinding(client, "m365", "mock", "factpack-read-only", f"client-{client}-m365")
    try:
        return GraphMock(client, binding, tenant_dir)
    except AdapterError as exc:
        raise FactpackError(str(exc)) from exc


def _baseline(client: str, graph_dir: Path) -> Path | None:
    folder = BASELINE_DIR.get(client)
    path = graph_dir / folder if folder else None
    return path if path is not None and path.is_dir() else None


def _same(a: Any, b: str) -> bool:
    return isinstance(a, str) and a.lower() == b.lower()


def _find_user(users: list[dict[str, Any]], target: str) -> dict[str, Any] | None:
    for u in users:
        if _same(u.get("id"), target) or _same(u.get("userPrincipalName"), target):
            return u
    return None


def _check_args(kind: str, client: str, target: str) -> None:
    if kind not in KINDS:
        raise FactpackError(f"unknown kind {kind!r}; choose one of {', '.join(KINDS)}")
    if not CLIENT_ID.fullmatch(client):
        raise FactpackError("client must be a client id such as contoso-dental")
    if kind in PERSON_KINDS and not TARGET.fullmatch(target):
        raise FactpackError("target must be a user id or a user principal name")
    if kind == "policy" and not 1 <= len(target) <= 160:
        raise FactpackError("target must be a policy id or name")


def build(
    kind: str,
    client: str,
    target: str,
    *,
    tenant_dir: Path = DEFAULT_TENANT_DIR,
    graph_dir: Path = DEFAULT_GRAPH_DIR,
    devices_path: Path = DEFAULT_DEVICES_PATH,
) -> dict[str, Any]:
    """Assemble a fact pack. Read-only: opens files for reading, returns plain data, changes nothing."""
    _check_args(kind, client, target)
    graph = _adapter(client, tenant_dir)
    baseline = _baseline(client, graph_dir)
    ctx = _Ctx(withheld=[])
    if kind in PERSON_KINDS:
        body = _person(ctx, graph, baseline, client, target, devices_path)
    else:
        body = _policy(ctx, baseline, target)
    inventory_id, runbook = (PERSON_KINDS | POLICY_KINDS)[kind]
    return {
        "kind": kind,
        "client": client,
        "target": body.pop("target"),
        "inventoryId": inventory_id,
        "readOnly": True,
        "leversRegistered": [],
        "proposals": [],
        "decision": "A named human decides" + (f"; see {runbook}" if runbook else "; a change needs a change record"),
        **body,
        "withheld": sorted(ctx.withheld),
    }


# -- person --------------------------------------------------------------------------------------------------------
def _person(
    ctx: _Ctx, graph: GraphMock, baseline: Path | None, client: str, target: str, devices_path: Path
) -> dict[str, Any]:
    t_users = graph.list_users().data or []
    b_users = _values(baseline / "users.json") if baseline else []
    t_user, b_user = _find_user(t_users, target), _find_user(b_users, target)
    if t_user is None and b_user is None:
        raise FactpackError(NO_PERSON)
    upn = str((t_user or b_user or {}).get("userPrincipalName", target))
    gaps: list[str] = []
    sources = [s for s, hit in (("tenant", t_user), ("baseline", b_user)) if hit is not None]

    account: dict[str, Any] = {"sources": sources}
    keys = ("id", "displayName", "userPrincipalName", "jobTitle", "userType", "accountEnabled", "createdDateTime")
    for src in (b_user, t_user):  # the tenant record wins where both have a field
        for key in keys:
            if src is not None and key in src:
                account[key] = ctx.text(f"account.{key}", src[key]) if key == "displayName" else src[key]
    if b_user is not None:
        sia = b_user.get("signInActivity")
        last = sia.get("lastSuccessfulSignInDateTime") if isinstance(sia, dict) else None
        account["lastSuccessfulSignIn"] = last if isinstance(last, str) else None
        account["onPremisesSyncEnabled"] = b_user.get("onPremisesSyncEnabled")

    methods = list(graph.list_authentication_methods(upn).data or []) if t_user is not None else []
    reg = _find_user(_values(baseline / "userRegistrationDetails.json"), upn) if baseline else None
    authentication: dict[str, Any] = {
        "methodTypes": sorted(str(m.get("@odata.type", "")).removeprefix("#microsoft.graph.") for m in methods),
        "contactDetailsShown": False,
    }
    if reg is not None:
        authentication.update(
            isMfaRegistered=reg.get("isMfaRegistered"),
            methodsRegistered=list(reg.get("methodsRegistered", [])),
            isAdmin=reg.get("isAdmin"),
        )
    if t_user is None and reg is None:
        gaps.append("authentication: no method or registration record for this person")

    sessions: dict[str, Any] = {}
    fams = graph.families().data or []
    sess = None
    if "sessions" in fams:
        rows = (graph.family_state("sessions").data or {}).get("value", [])
        sess = next((r for r in rows if _same(r.get("userPrincipalName"), upn)), None)
    if sess is not None:
        sessions["activeSessionCount"] = sess.get("activeSessionCount")
        sessions["activeSessionCountNote"] = "INVENTED counter in the mock; Graph exposes none"
    else:
        gaps.append("sessions: no session record for this person")
    recent: list[dict[str, Any]] = []
    if "signins" in fams:
        rows = (graph.family_state("signins").data or {}).get("value", [])
        mine = sorted(
            (r for r in rows if _same(r.get("userPrincipalName"), upn)), key=lambda r: str(r.get("createdDateTime"))
        )
        for r in mine[-RECENT_SIGNINS:]:
            status = r.get("status") if isinstance(r.get("status"), dict) else {}
            loc = r.get("location") if isinstance(r.get("location"), dict) else {}
            recent.append(
                {
                    "at": r.get("createdDateTime"),
                    "app": ctx.text("sessions.recentSignIns.app", r.get("appDisplayName")),
                    "ip": r.get("ipAddress"),
                    "country": loc.get("countryOrRegion"),
                    "errorCode": status.get("errorCode"),
                    "failureReason": ctx.text("sessions.recentSignIns.failureReason", status.get("failureReason", "")),
                }
            )
        sessions["signInsOnRecord"] = len(mine)
    else:
        gaps.append("sessions: no sign-in log for this client")
    sessions["recentSignIns"] = recent

    devices = _devices(devices_path, client, upn, ctx)
    if not devices:
        gaps.append("devices: none on record for this person")

    roles, groups = _roles(ctx, graph, baseline, upn, fams)
    if baseline is None:
        gaps.append("roles and Conditional Access: this client has no baseline folder")
    cas: list[dict[str, Any]] = []
    uid = str(account.get("id", ""))
    for pol in _values(baseline / "conditionalAccessPolicies.json") if baseline else []:
        users = (pol.get("conditions") or {}).get("users") or {}
        include = users.get("includeUsers") or []
        cas.append(
            {
                "id": pol.get("id"),
                "name": ctx.text("caPolicies.name", pol.get("displayName")),
                "state": pol.get("state"),
                "includesAllUsers": "All" in include,
                "includesThisUser": uid in include,
                "excludesThisUser": uid in (users.get("excludeUsers") or []),
                "hasGroupOrRoleScope": bool(users.get("includeGroups") or users.get("includeRoles")),
            }
        )
    return {
        "target": upn,
        "account": account,
        "authentication": authentication,
        "sessions": sessions,
        "devices": devices,
        "roles": roles,
        "groups": groups,
        "caPolicies": cas,
        "holdsPrivilegedAccess": bool(roles) or any(g["privileged"] for g in groups),
        "gaps": gaps,
    }


def _devices(path: Path, client: str, upn: str, ctx: _Ctx) -> list[dict[str, Any]]:
    data = _read(path)
    mine = (((data.get("clients") or {}).get(client) or {}).get("devices", [])) if isinstance(data, dict) else []
    out = []
    for d in mine:  # this client's slice only
        if isinstance(d, dict) and _same(d.get("owner"), upn):
            out.append({**d, "name": ctx.text("devices.name", d.get("name"))})
    return sorted(out, key=lambda d: str(d.get("id")))


def _roles(
    ctx: _Ctx, graph: GraphMock, baseline: Path | None, upn: str, fams: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    roles = []
    for role in _values(baseline / "directoryRoles.json") if baseline else []:
        if any(_same(m.get("userPrincipalName"), upn) for m in role.get("members", []) if isinstance(m, dict)):
            roles.append({"id": role.get("id"), "name": ctx.text("roles.name", role.get("displayName"))})
    groups: list[dict[str, Any]] = []
    if "groups" in fams:
        data = graph.family_state("groups").data or {}
        named = set(data.get("redlinePrivilegedGroups", []))
        for g in data.get("value", []):
            if any(_same(m.get("userPrincipalName"), upn) for m in g.get("members", []) if isinstance(m, dict)):
                groups.append(
                    {
                        "id": g.get("id"),
                        "name": ctx.text("groups.name", g.get("displayName")),
                        "privileged": bool(g.get("isAssignableToRole")) or g.get("displayName") in named,
                    }
                )
    return roles, groups


# -- policy --------------------------------------------------------------------------------------------------------
def _policy(ctx: _Ctx, baseline: Path | None, target: str) -> dict[str, Any]:
    if baseline is None:
        raise FactpackError(NO_POLICY)
    policies = _values(baseline / "conditionalAccessPolicies.json")
    pol = next((p for p in policies if _same(p.get("id"), target)), None) or next(
        (p for p in policies if _same(p.get("displayName"), target)), None
    )
    if pol is None:
        raise FactpackError(NO_POLICY)
    users_by_id = {str(u.get("id")): u for u in _values(baseline / "users.json")}
    roles = _values(baseline / "directoryRoles.json")
    admin_ids = {str(m.get("id")) for r in roles for m in r.get("members", []) if isinstance(m, dict)}
    cond = pol.get("conditions") or {}
    users = cond.get("users") or {}
    grant = pol.get("grantControls") or {}

    def person(uid: str) -> dict[str, Any]:
        u = users_by_id.get(uid)
        return {
            "id": uid,
            "userPrincipalName": ctx.text("policy.exclusions", u.get("userPrincipalName")) if u else None,
            "holdsDirectoryRole": uid in admin_ids,
            "inBaseline": u is not None,
        }

    excluded = [person(str(i)) for i in users.get("excludeUsers", [])]
    others = [
        {"id": p.get("id"), "name": ctx.text("otherPolicies.name", p.get("displayName")), "state": p.get("state")}
        for p in policies
        if p is not pol
    ]
    return {
        "target": str(pol.get("id")),
        "policy": {
            "name": ctx.text("policy.name", pol.get("displayName")),
            "state": pol.get("state"),
            "reportOnly": pol.get("state") == "enabledForReportingButNotEnforced",
            "createdDateTime": pol.get("createdDateTime"),
            "modifiedDateTime": pol.get("modifiedDateTime"),
            "clientAppTypes": list(cond.get("clientAppTypes", [])),
            "includeApplications": list((cond.get("applications") or {}).get("includeApplications", [])),
            "includeUsers": list(users.get("includeUsers", [])),
            "includeGroups": list(users.get("includeGroups", [])),
            "includeRoles": list(users.get("includeRoles", [])),
            "excludeGroups": list(users.get("excludeGroups", [])),
            "excludeRoles": list(users.get("excludeRoles", [])),
            "grantOperator": grant.get("operator"),
            "grantBuiltInControls": list(grant.get("builtInControls", [])),
        },
        "excludedUsers": excluded,
        "scope": {
            "usersInBaseline": len(users_by_id),
            "enabledUsersInBaseline": sum(1 for u in users_by_id.values() if u.get("accountEnabled")),
            "excludedCount": len(excluded),
            "excludedHoldingDirectoryRole": sum(1 for e in excluded if e["holdsDirectoryRole"]),
        },
        "otherPolicies": sorted(others, key=lambda p: str(p["id"])),
        "gaps": ["group and role membership of the include lists is not resolved here; a person reads it in Entra"],
    }
