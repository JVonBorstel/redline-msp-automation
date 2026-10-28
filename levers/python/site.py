"""SharePoint / Teams site levers on the mock tenant (B-88, B88-3). Mock only: no Graph or SharePoint call is made.

``site.new`` (R2, lead approval) adds one private site to the client's base state under ``sites``: the exact display
name, URL slug, owners, template and sharing setting of a structured request. Sharing defaults to ``Disabled`` (no
external sharing) and visibility is always ``Private``. The dry-run diff and the returned ``site`` are the exact record
that an execute would write. Owners must be enabled member users of THIS client's mock tenant (the handler sees only
that client's state, so an owner of another client is "no such user"). The same request twice changes nothing; the
same slug with any other value is refused.

``site.remove-empty`` (R2, lead approval) is the registered undo. It takes the same parameters and removes the site
only when the record on file is exactly the one ``site.new`` would write from them, was created by ``site.new`` and
holds no content, so it is the exact inverse and the rollback check of B-41 holds. Why not ``site.archive``: an archive
leaves the site in place, so it cannot restore the before-state, and Microsoft 365 Archive is a separate paid feature
(UNVERIFIED). In a real tenant a removed site goes to the deleted-sites recycle bin for a retention period (from memory,
UNVERIFIED); the mock just drops the record.

``site.get`` (R0) reads one site back. ``verify_applied`` compares that read-back with the request; it is the check to
run after an execute (the runner itself has no post-apply hook, see specs/B-88.md).

``parse_site_request`` turns a structured request (form fields, never ticket text) into lever params. Unknown fields
are refused, and the only free-text field, ``notes``, is never read for a parameter: notes that name an address, a URL
or a slug are refused, so an owner or slug can only arrive in its own validated field.

UNVERIFIED: every field name and value here (``webTemplate`` ids, ``sharingCapability`` values, the site URL shape).
The URL host uses ``.sharepoint.example`` on purpose; a real tenant's host is ``<tenant>.sharepoint.com``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from core.guard import detect_injection
from core.levers.handlers import LeverFailed
from core.levers.tenant import JsonDict

SITES_KEY = "sites"
CREATED_BY = "site.new"
SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$"
DISPLAY_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9 &'-]{0,59}$"
UPN_PATTERN = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
# template param -> (webTemplate, group-connected, has a Team). The webTemplate ids are from memory, UNVERIFIED.
TEMPLATES: Mapping[str, tuple[str, bool, bool]] = {
    "teams-team": ("GROUP#0", True, True),
    "team-site": ("GROUP#0", True, False),
    "communication-site": ("SITEPAGEPUBLISHING#0", False, False),
}
# external_sharing param -> sharingCapability (UNVERIFIED names). Anyone links and new guests are not offered at all.
SHARING: Mapping[str, str] = {"disabled": "Disabled", "existing-guests": "ExistingExternalUserSharingOnly"}
DEFAULT_SHARING = "disabled"
# Paths a site slug must not take (fixture-based choice, not a list read from Microsoft).
RESERVED_SLUGS = frozenset({"admin", "root", "search", "sites", "teams", "portal", "personal", "contentstorage"})
REQUEST_FIELDS = frozenset({"display_name", "slug", "owners", "template", "external_sharing", "notes"})
MAX_NOTES = 500
_SLUG = re.compile(SLUG_PATTERN)
_DISPLAY = re.compile(DISPLAY_NAME_PATTERN)
_UPN = re.compile(UPN_PATTERN)
# Shapes that must never be in free text: an address, a URL or site path, or a slug/owner/url key with a value.
_SMUGGLED = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+|https?:|/sites/|/teams/|\b(?:slug|owners?|url|template|sharing)\s*[:=]",
    re.IGNORECASE,
)
_NO_USER = "no such user for this client"


class SiteRequestError(ValueError):
    """A site request is not a clean structured request; nothing is proposed."""


def parse_site_request(request: object) -> dict[str, str]:
    """Lever params for ``site.new`` from a structured request, or ``SiteRequestError``. Notes never become params."""
    if not isinstance(request, Mapping):
        raise SiteRequestError("a site request must be an object of form fields")
    unknown = sorted(str(k) for k in request if k not in REQUEST_FIELDS)
    if unknown:
        raise SiteRequestError(f"unknown request fields: {', '.join(unknown)}")
    notes = request.get("notes", "")
    if not isinstance(notes, str) or len(notes) > MAX_NOTES:
        raise SiteRequestError(f"notes must be text of at most {MAX_NOTES} characters")
    if _SMUGGLED.search(notes):
        raise SiteRequestError(
            "the notes name an address, a URL or a site setting; owners, slug and settings come only from their own "
            "fields, so the request is refused"
        )
    if notes and detect_injection(notes).flagged:
        raise SiteRequestError("the notes read like instructions to a tool; the request is refused")
    display_name, slug, template = request.get("display_name"), request.get("slug"), request.get("template")
    if not isinstance(display_name, str) or not _DISPLAY.fullmatch(display_name):
        raise SiteRequestError("display_name must be 1-60 letters, digits, spaces, & ' or -")
    if not isinstance(slug, str) or not _SLUG.fullmatch(slug) or "--" in slug or slug in RESERVED_SLUGS:
        raise SiteRequestError("slug must be 3-40 lowercase letters, digits or single hyphens, and not reserved")
    if not isinstance(template, str) or template not in TEMPLATES:
        raise SiteRequestError(f"template must be one of {', '.join(TEMPLATES)}")
    sharing = request.get("external_sharing", DEFAULT_SHARING)
    if not isinstance(sharing, str) or sharing not in SHARING:
        raise SiteRequestError(f"external_sharing must be one of {', '.join(SHARING)}")
    owners = request.get("owners")
    if (
        not isinstance(owners, list)
        or not 1 <= len(owners) <= 2
        or not all(isinstance(o, str) and len(o) <= 113 and _UPN.fullmatch(o) for o in owners)
    ):
        raise SiteRequestError("owners must be a list of one or two userPrincipalNames")
    if len({o.lower() for o in owners}) != len(owners):
        raise SiteRequestError("the two owners must be different people")
    params = {"display_name": display_name, "slug": slug, "upn": owners[0], "template": template}
    if len(owners) == 2:
        params["co_owner_upn"] = owners[1]
    if sharing != DEFAULT_SHARING:
        params["external_sharing"] = sharing
    return params


def _owner(state: JsonDict, upn: str) -> str:
    """The owner's UPN as the tenant spells it; an enabled member user of this client, or ``LeverFailed``."""
    for user in state.get("users", []):
        if isinstance(user, dict) and str(user.get("userPrincipalName", "")).lower() == upn.lower():
            if user.get("accountEnabled") is not True:
                raise LeverFailed("an owner's account is disabled")
            if str(user.get("userType", "Member")) != "Member":
                raise LeverFailed("an owner must be a member user, not a guest")
            return str(user["userPrincipalName"])
    raise LeverFailed(_NO_USER)


def _tenant_label(upn: str) -> str:
    label = re.sub(r"[^a-z0-9]", "", upn.rsplit("@", 1)[-1].split(".", 1)[0].lower())
    if not label:
        raise LeverFailed("cannot derive the tenant name from the owner's address")
    return label


def site_record(state: JsonDict, params: Mapping[str, Any]) -> JsonDict:
    """The exact record ``site.new`` writes for ``params`` (owners checked against this client's users)."""
    slug, template = str(params["slug"]), str(params["template"])
    if not _SLUG.fullmatch(slug) or "--" in slug or slug in RESERVED_SLUGS:
        raise LeverFailed("that slug is not allowed")
    if template not in TEMPLATES:
        raise LeverFailed("unknown template")
    sharing = str(params.get("external_sharing", DEFAULT_SHARING))
    if sharing not in SHARING:
        raise LeverFailed("unknown sharing setting")
    owners = [_owner(state, str(params["upn"]))]
    co_owner = params.get("co_owner_upn")
    if co_owner is not None:
        if str(co_owner).lower() == owners[0].lower():
            raise LeverFailed("the two owners must be different people")
        owners.append(_owner(state, str(co_owner)))
    web_template, group_connected, team = TEMPLATES[template]
    return {
        "id": slug,
        "displayName": str(params["display_name"]),
        "webUrl": f"https://{_tenant_label(owners[0])}.sharepoint.example/sites/{slug}",
        "template": template,
        "webTemplate": web_template,
        "groupConnected": group_connected,
        "teamsEnabled": team,
        "visibility": "Private",
        "sharingCapability": SHARING[sharing],
        "owners": owners,
        "contentItems": 0,
        "createdBy": CREATED_BY,
    }


def _sites(state: JsonDict) -> list[Any]:
    sites = state.get(SITES_KEY, [])
    if not isinstance(sites, list):
        raise LeverFailed("the client's sites are in an unexpected shape")
    return sites


def _find(sites: list[Any], slug: str) -> Any:
    return next((s for s in sites if isinstance(s, dict) and str(s.get("id", "")).lower() == slug.lower()), None)


def site_new(state: JsonDict, params: Mapping[str, Any]) -> Any:
    """Create one private site with its owners. Running it twice changes nothing the second time (STD-LV-6)."""
    record = site_record(state, params)
    sites = _sites(state)
    found = _find(sites, record["id"])
    if found is not None:
        if found != record:
            raise LeverFailed("a site with that URL already exists for this client with other values")
        return {"site": record, "created": False}
    for site in sites:
        if isinstance(site, dict) and str(site.get("displayName", "")).lower() == record["displayName"].lower():
            raise LeverFailed("a site with that display name already exists for this client")
    state[SITES_KEY] = sorted([*sites, record], key=lambda s: str(s.get("id", "")) if isinstance(s, dict) else "")
    return {"site": record, "created": True}


def site_remove_empty(state: JsonDict, params: Mapping[str, Any]) -> Any:
    """Undo of ``site.new``: remove the site only if it is exactly the one these params create, and still empty."""
    record = site_record(state, params)
    sites = _sites(state)
    found = _find(sites, record["id"])
    if found is None:
        return {"site": record["id"], "removed": False}
    if not isinstance(found, dict) or found.get("createdBy") != CREATED_BY:
        raise LeverFailed("that site was not created by site.new; remove it by hand after review")
    if found.get("contentItems") != 0:
        raise LeverFailed("that site holds content; it is not removed (manual review)")
    if found != record:
        raise LeverFailed("the site on record differs from these values; read it with site.get first")
    rest = [s for s in sites if s is not found]
    if rest:
        state[SITES_KEY] = rest
    else:
        state.pop(SITES_KEY, None)
    return {"site": record["id"], "removed": True}


def site_get(state: JsonDict, params: Mapping[str, Any]) -> Any:
    """One site of this client, read back, or ``site: None`` when there is none with that slug."""
    found = _find(_sites(state), str(params["slug"]))
    note = "Mock site record; field names UNVERIFIED."
    return {"site": dict(found) if isinstance(found, dict) else None, "note": note}


def verify_applied(read_back: Mapping[str, Any], params: Mapping[str, Any]) -> list[str]:
    """What is wrong with the read-back of ``site.get`` against the request; empty means the site is as asked."""
    site = read_back.get("site")
    if not isinstance(site, Mapping):
        return ["the site is not there"]
    problems: list[str] = []
    want_sharing = SHARING.get(str(params.get("external_sharing", DEFAULT_SHARING)))
    owners = [str(params["upn"]).lower()] + ([str(params["co_owner_upn"]).lower()] if "co_owner_upn" in params else [])
    expected = {
        "id": params["slug"],
        "displayName": params["display_name"],
        "template": params["template"],
        "visibility": "Private",
        "sharingCapability": want_sharing,
    }
    for key, value in expected.items():
        if site.get(key) != value:
            problems.append(f"{key} is {site.get(key)!r}, expected {value!r}")
    got = site.get("owners")
    if not isinstance(got, list) or [str(o).lower() for o in got] != owners:
        problems.append("the owners are not the requested owners")
    if not str(site.get("webUrl", "")).endswith(f"/sites/{params['slug']}"):
        problems.append("the URL does not end in the requested slug")
    return problems
