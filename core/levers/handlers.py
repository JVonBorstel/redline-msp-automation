"""The four sample levers, backed by the mock tenant.

A handler gets a private copy of one client's tenant state and the validated params. A read
lever returns data and must not change the state; a write lever changes the copy, and the
runner turns that into a diff. Only the runner decides whether the change is saved (execute,
approved) or thrown away (dry-run). Handlers never see other clients' data.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

from core.levers.tenant import JsonDict

Handler = Callable[[JsonDict, Mapping[str, Any]], Any]

# The password method stays: resetting MFA must not lock the user out of first-factor sign-in.
KEPT_METHOD_TYPE = "#microsoft.graph.passwordAuthenticationMethod"


class LeverFailed(RuntimeError):
    """The lever ran but could not do its job (for example the user does not exist)."""


def _find_user(state: JsonDict, upn: str) -> JsonDict:
    for user in state.get("users", []):
        if str(user.get("userPrincipalName", "")).lower() == upn.lower():
            found: JsonDict = user  # the same object, so writes land in the runner's state copy
            return found
    raise LeverFailed(f"no user {upn!r} in this client's tenant")


def ticket_get(state: JsonDict, params: Mapping[str, Any]) -> Any:
    for ticket in state.get("tickets", []):
        if ticket.get("id") == params["ticket_id"]:
            return ticket
    raise LeverFailed(f"no ticket {params['ticket_id']!r} for this client")


def user_reset_mfa(state: JsonDict, params: Mapping[str, Any]) -> Any:
    """Remove every MFA method except the password, so the user must re-register at next sign-in."""
    user = _find_user(state, params["upn"])
    methods = user.setdefault("authentication", {}).setdefault("methods", [])
    kept = [m for m in methods if m.get("@odata.type") == KEPT_METHOD_TYPE]
    user["authentication"]["methods"] = kept
    return {"user": user["userPrincipalName"], "methods_removed": len(methods) - len(kept)}


def user_disable(state: JsonDict, params: Mapping[str, Any]) -> Any:
    user = _find_user(state, params["upn"])
    user["accountEnabled"] = False
    return {"user": user["userPrincipalName"], "accountEnabled": False}


def kb_search(state: JsonDict, params: Mapping[str, Any]) -> Any:
    """Keyword search over this client's KB only (per-client isolation at the retrieval layer)."""
    terms = {t for t in re.findall(r"[a-z0-9]+", params["query"].lower()) if len(t) > 1}
    category = params.get("category")
    hits: list[tuple[int, str, str]] = []
    for article in state.get("kb", []):
        if category is not None and article.get("category") != category:
            continue
        text = " ".join([article.get("title", ""), article.get("body", ""), *article.get("tags", [])]).lower()
        words = set(re.findall(r"[a-z0-9]+", text))
        score = len(terms & words)
        if score:
            hits.append((score, article["id"], article["title"]))
    hits.sort(key=lambda h: (-h[0], h[1]))
    return [{"id": i, "title": title, "score": s} for s, i, title in hits[: params.get("top", 3)]]


HANDLERS: Mapping[str, Handler] = {
    "ticket.get": ticket_get,
    "user.reset-mfa": user_reset_mfa,
    "user.disable": user_disable,
    "kb.search": kb_search,
}


# --- Python lever modules (B-14) -------------------------------------------------------------------
# A registry `entry` of the form "levers.python.<module>:<function>" names a handler. It resolves only
# to a callable defined inside the `levers.python` package, so a registry file can never point a lever
# at os, subprocess or any other module.

PYTHON_PACKAGE = "levers.python"
_ENTRY_RE = re.compile(r"^(levers\.python(?:\.[a-z_][a-z0-9_]*)*):([a-z_][a-z0-9_]*)$")


class EntryError(ValueError):
    """A registry `entry` does not resolve to a callable inside the levers.python package."""


def _inside_package(module: ModuleType, package: ModuleType) -> bool:
    file = getattr(module, "__file__", None)
    roots = list(getattr(package, "__path__", []))
    if not file or not roots:
        return False
    target = Path(file).resolve()
    return any(target.is_relative_to(Path(root).resolve()) for root in roots)


def resolve_python_entry(entry: str) -> Handler:
    """Import and return the handler named by `levers.python.<module>:<function>`, or raise EntryError."""
    match = _ENTRY_RE.match(entry)
    if match is None:
        raise EntryError(
            f"entry {entry!r} must look like '{PYTHON_PACKAGE}.<module>:<function>' (lowercase names only)"
        )
    module_name, function_name = match.groups()
    try:
        package = importlib.import_module(PYTHON_PACKAGE)
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise EntryError(f"entry {entry!r}: cannot import {module_name!r} ({type(exc).__name__})") from exc
    if module is not package and not _inside_package(module, package):
        raise EntryError(f"entry {entry!r}: module {module_name!r} is not inside the {PYTHON_PACKAGE} package")
    function = getattr(module, function_name, None)
    if not callable(function):
        raise EntryError(f"entry {entry!r}: {module_name!r} has no callable {function_name!r}")
    defined_in = getattr(function, "__module__", "")
    if defined_in != PYTHON_PACKAGE and not str(defined_in).startswith(PYTHON_PACKAGE + "."):
        raise EntryError(f"entry {entry!r}: {function_name!r} is defined in {defined_in!r}, not in {PYTHON_PACKAGE}")
    handler: Handler = function
    return handler
