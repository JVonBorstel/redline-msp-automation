"""Field-level diff between two JSON values, used for dry-run output and the audit record.

Lists of objects that all carry an `id` are matched by id (so removing one item reads as one
`remove`, not a cascade of shifted indexes); other lists are compared by position.
"""

from __future__ import annotations

from typing import Any

from core.levers.models import Change


def _by_id(items: list[Any]) -> dict[str, Any] | None:
    if not all(isinstance(i, dict) and isinstance(i.get("id"), str) for i in items):
        return None
    keyed = {i["id"]: i for i in items}
    return keyed if len(keyed) == len(items) else None


def json_diff(before: Any, after: Any, path: str = "") -> list[Change]:
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[Change] = []
        for key in before.keys() | after.keys():
            sub = f"{path}/{key}"
            if key not in after:
                changes.append(Change(op="remove", path=sub, before=before[key]))
            elif key not in before:
                changes.append(Change(op="add", path=sub, after=after[key]))
            else:
                changes.extend(json_diff(before[key], after[key], sub))
        return sorted(changes, key=lambda c: c.path)
    if isinstance(before, list) and isinstance(after, list):
        keyed_before, keyed_after = _by_id(before), _by_id(after)
        if keyed_before is not None and keyed_after is not None:
            return json_diff(keyed_before, keyed_after, path)
        changes = []
        for i in range(max(len(before), len(after))):
            sub = f"{path}/{i}"
            if i >= len(after):
                changes.append(Change(op="remove", path=sub, before=before[i]))
            elif i >= len(before):
                changes.append(Change(op="add", path=sub, after=after[i]))
            else:
                changes.extend(json_diff(before[i], after[i], sub))
        return changes
    if before != after or type(before) is not type(after):
        return [Change(op="replace", path=path or "/", before=before, after=after)]
    return []
