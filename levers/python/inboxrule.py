"""Inbox-rule levers on the mock tenant (B-46). Mock only: no mailbox or Graph API is called.

``inboxrule.list`` (R0) reads the client's ``inbox-rules`` family file (Graph ``messageRule`` shape, field names
UNVERIFIED) and flags each rule that forwards outside the client's own domains, deletes mail, or moves or copies it to
an RSS folder or an obscure folder (a hiding place such as "Conversation History", a name with no letters, or a folder
that is not on record). It returns data only; the runner audits who asked, never the rules (D-017).

``inboxrule.disable`` (R2) turns one rule off; ``inboxrule.enable`` (R2) is its registered undo. A write handler gets
the client's base state only (``MockTenant.load``), not the family file (STD-LV-8), so the levers record the change
in the base state under ``inboxRuleChanges[<rule id>] = {"mailbox", "isEnabled"}`` and ``inboxrule.list`` shows a
rule's effective ``isEnabled`` with that change applied. An entry exists only while it differs from the family file:
disabling a rule that was enabled by ``inboxrule.enable`` removes the entry again, so disable and enable are exact
inverses (the rollback check of B-41 holds). The handler cannot see whether the rule exists; the containment plan
(``workflows/bec``) reads it through ``inboxrule.list`` before any dry-run (STD-LV-9), as ``backup.retry-job`` does.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.levers.handlers import LeverFailed
from core.levers.tenant import JsonDict

FAMILY = "inbox-rules"
CHANGES_KEY = "inboxRuleChanges"
FORWARD_ACTIONS = ("forwardTo", "redirectTo", "forwardAsAttachmentTo")
DELETE_ACTIONS = ("delete", "permanentDelete")
FOLDER_ACTIONS = ("moveToFolder", "copyToFolder")
# Folder names attackers use to hide mail from the user (lowercase). The list is a fixture-based choice, not tuned.
OBSCURE_FOLDERS = frozenset(
    {"conversation history", "sync issues", "conflicts", "local failures", "server failures", "junk email", "notes"}
)
FLAG_KINDS = ("external-forward", "delete", "rss-folder", "obscure-folder")
_NO_USER = "no such user for this client"
_NOT_AVAILABLE = "No inbox-rule data for this client; an empty list does not mean no rule is suspicious."


def _same(a: object, b: str) -> bool:
    return isinstance(a, str) and a.lower() == b.lower()


def _has_user(state: JsonDict, upn: str) -> bool:
    return any(isinstance(u, dict) and _same(u.get("userPrincipalName"), upn) for u in state.get("users", []))


def _addresses(value: Any) -> list[str]:
    out: list[str] = []
    for item in value if isinstance(value, list) else []:
        email = item.get("emailAddress") if isinstance(item, dict) else None
        address = email.get("address") if isinstance(email, dict) else None
        if isinstance(address, str):
            out.append(address)
    return out


def _domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower() if "@" in address else ""


def flags_for(rule: Mapping[str, Any], folders: Mapping[str, str], internal: frozenset[str]) -> list[dict[str, str]]:
    """Why ``rule`` is suspicious, one entry per reason, in FLAG_KINDS order. Empty when it is not."""
    raw = rule.get("actions")
    actions: Mapping[str, Any] = raw if isinstance(raw, dict) else {}
    flags: list[dict[str, str]] = []
    for action in FORWARD_ACTIONS:
        for address in _addresses(actions.get(action)):
            domain = _domain(address)
            if not internal:
                flags.append(
                    {"kind": "external-forward", "why": f"{action}: the client's own domains are not on record"}
                )
            elif domain not in internal:
                flags.append({"kind": "external-forward", "why": f"{action} to a domain outside the client ({domain})"})
    for action in DELETE_ACTIONS:
        if actions.get(action) is True:
            flags.append({"kind": "delete", "why": f"{action}: mail is removed before the user sees it"})
    for action in FOLDER_ACTIONS:
        folder_id = actions.get(action)
        if not isinstance(folder_id, str):
            continue
        name = folders.get(folder_id)
        if name is None:
            flags.append({"kind": "obscure-folder", "why": f"{action} to a folder that is not on record"})
        elif name.strip().lower().startswith("rss"):
            flags.append({"kind": "rss-folder", "why": f"{action} to an RSS folder"})
        elif name.strip().lower() in OBSCURE_FOLDERS or not any(ch.isalnum() for ch in name):
            flags.append({"kind": "obscure-folder", "why": f"{action} to a folder users rarely open"})
    order = {kind: i for i, kind in enumerate(FLAG_KINDS)}
    return sorted(flags, key=lambda f: order[f["kind"]])


def inboxrule_list(state: JsonDict, params: Mapping[str, Any]) -> Any:
    """The client's inbox rules (one mailbox when ``upn`` is given), each with its ``flags``; flagged only on ask."""
    upn = params.get("upn")
    if isinstance(upn, str) and not _has_user(state, upn):
        raise LeverFailed(_NO_USER)
    family = (state.get("_families") or {}).get(FAMILY)
    if not isinstance(family, dict):
        return {"value": [], "note": _NOT_AVAILABLE}
    raw_meta = family.get("_meta")
    meta: Mapping[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    internal = frozenset(str(d).lower() for d in meta.get("internal_domains", []) if isinstance(d, str))
    raw_changes = state.get(CHANGES_KEY)
    changes: Mapping[str, Any] = raw_changes if isinstance(raw_changes, dict) else {}
    rows: list[dict[str, Any]] = []
    for box in family.get("mailboxes", []):
        if not isinstance(box, dict):
            continue
        mailbox = str(box.get("userPrincipalName", ""))
        if isinstance(upn, str) and not _same(mailbox, upn):
            continue
        folders = {
            str(f["id"]): str(f.get("displayName", ""))
            for f in box.get("mailFolders", [])
            if isinstance(f, dict) and isinstance(f.get("id"), str)
        }
        for rule in box.get("rules", []):
            if not isinstance(rule, dict):
                continue
            row = dict(rule)
            change = changes.get(str(rule.get("id")))
            if isinstance(change, dict) and _same(change.get("mailbox"), mailbox):
                row["isEnabled"] = bool(change.get("isEnabled"))
            row["mailbox"] = mailbox
            row["flags"] = flags_for(rule, folders, internal)
            row["flagged"] = bool(row["flags"])
            rows.append(row)
    if params.get("flagged_only"):
        rows = [r for r in rows if r["flagged"]]
    rows.sort(key=lambda r: (str(r["mailbox"]).lower(), int(r.get("sequence") or 0), str(r.get("id", ""))))
    note = "Field names are UNVERIFIED; rule times are a mock stand-in for the mailbox audit log."
    return {"value": rows, "note": note}


def _set_enabled(state: JsonDict, params: Mapping[str, Any], enabled: bool) -> Any:
    upn, rule_id = str(params["upn"]), str(params["rule_id"])
    if not _has_user(state, upn):
        raise LeverFailed(_NO_USER)
    changes = state.get(CHANGES_KEY, {})
    if not isinstance(changes, dict):
        raise LeverFailed("inbox rule changes are in an unexpected shape")
    entry = changes.get(rule_id)
    if entry is not None and (not isinstance(entry, dict) or not _same(entry.get("mailbox"), upn)):
        raise LeverFailed("that rule is not on record for this mailbox")
    if entry is None:
        changes[rule_id] = {"mailbox": upn.lower(), "isEnabled": enabled}
    elif bool(entry.get("isEnabled")) != enabled:
        del changes[rule_id]  # back to the family file's value, which is the one asked for
    if changes:
        state[CHANGES_KEY] = changes
    else:
        state.pop(CHANGES_KEY, None)
    return {"mailbox": upn, "rule_id": rule_id, "isEnabled": enabled}


def inboxrule_disable(state: JsonDict, params: Mapping[str, Any]) -> Any:
    """Turn one inbox rule off. Running it twice changes nothing the second time (STD-LV-6)."""
    return _set_enabled(state, params, False)


def inboxrule_enable(state: JsonDict, params: Mapping[str, Any]) -> Any:
    """Turn one inbox rule back on; the registered undo of ``inboxrule.disable``."""
    return _set_enabled(state, params, True)
