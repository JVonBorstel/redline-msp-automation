"""Migration pre-flight checks for one client (B-77, B77-3; specs/B-77.md; W-PRJ-03; C-20, C-27).

Reads a migration plan (``data/migrations/<client>.json``: the mailboxes to move and a read-only snapshot of the
destination) and the client's own ``mailboxes.json``, then runs three checks:

- ``mailbox-sizes``: every planned mailbox is in this client's mailbox list and fits the destination quota;
- ``licence-availability``: the destination's target SKU has a free seat for every user mailbox (shared mailboxes
  are counted apart; whether they need a licence is UNVERIFIED and left to a person);
- ``conflicting-addresses``: each mailbox's address at the destination domain is not already in use there, and no
  two planned mailboxes map to the same address.

Read-only: nothing here moves, creates or changes a mailbox, and there is no execute step. Executing migrations is
``NN-04`` in the roadmap's not-now list. A plan written for another client is refused (C-27), and a planned mailbox
that is not this client's is reported by its position in the plan, never echoed (ISO-6).
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.levers.tenant import DEFAULT_TENANT_DIR
from workflows.client_lifecycle.discovery import DEFAULT_CONFIG_PATH, check_client, load_config

CHECKS = ("mailbox-sizes", "licence-availability", "conflicting-addresses")
NOT_NOW = "NN-04"
EXECUTION = "not available: executing migrations is NN-04 (not now); this tool only checks"
CheckStatus = Literal["pass", "fail"]
_DOMAIN = r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"


class PreflightError(ValueError):
    """The plan or the client's mailbox data is bad; nothing was checked."""


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class Meta(_Strict):
    client: str
    display_name: str = Field(default="", alias="displayName")
    family: Literal["migration-plan"]
    note: str = Field(min_length=1)


class TargetLicence(_Strict):
    sku_part_number: str = Field(alias="skuPartNumber", min_length=1, max_length=64)
    enabled: int = Field(ge=0)
    assigned: int = Field(ge=0)


class Destination(_Strict):
    label: str = Field(min_length=1, max_length=200)
    domain: str = Field(pattern=_DOMAIN, max_length=253)
    mailbox_quota_gb: float = Field(gt=0, le=10_000)
    licence: TargetLicence
    addresses_in_use: tuple[str, ...] = ()


class MigrationPlan(_Strict):
    meta: Meta = Field(alias="_meta")
    version: Literal[1]
    client: str
    kind: Literal["tenant-to-tenant", "mailbox-move"]
    mailboxes: tuple[str, ...] = Field(min_length=1, max_length=5000)
    destination: Destination


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: CheckStatus
    problems: tuple[str, ...]
    counts: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Preflight:
    client: str
    kind: str
    destination: str
    checks: tuple[Check, ...]

    @property
    def ready(self) -> bool:
        return all(c.status == "pass" for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "client": self.client,
            "kind": self.kind,
            "destination": self.destination,
            "read_only": True,
            "ready": self.ready,
            "execution": EXECUTION,
            "label": "fixture-based: synthetic data; independently built prototype",
            "checks": [asdict(c) for c in self.checks],
        }


def default_plan_path(client: str, config_path: Path = DEFAULT_CONFIG_PATH) -> Path:
    return Path(config_path).parent / load_config(config_path).migrations_dir / f"{check_client(client)}.json"


def load_plan(path: Path, client: str) -> MigrationPlan:
    """The plan at ``path``; refused when it is unreadable, malformed or written for another client (C-27)."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PreflightError("no migration plan for this client") from exc
    except (OSError, ValueError) as exc:
        raise PreflightError(f"the migration plan is unreadable ({type(exc).__name__})") from exc
    try:
        plan = MigrationPlan.model_validate(raw)
    except ValidationError as exc:
        raise PreflightError(f"the migration plan is not valid: {exc.error_count()} problem(s)") from exc
    if plan.client != client or plan.meta.client != client:
        raise PreflightError("the migration plan is not for this client; nothing was checked")
    return plan


def load_mailboxes(client: str, tenant_dir: Path = DEFAULT_TENANT_DIR) -> dict[str, dict[str, Any]]:
    """UPN (lower case) -> mailbox, from this client's own mailboxes.json."""
    path = Path(tenant_dir) / client / "mailboxes.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PreflightError("no mailbox data for this client") from exc
    except (OSError, ValueError) as exc:
        raise PreflightError(f"the mailbox data is unreadable ({type(exc).__name__})") from exc
    meta = data.get("_meta") if isinstance(data, dict) else None
    if not isinstance(meta, dict) or meta.get("client") != client or not isinstance(data.get("mailboxes"), list):
        raise PreflightError("the mailbox data does not belong to this client; nothing was checked")
    return {
        str(m["userPrincipalName"]).lower(): m
        for m in data["mailboxes"]
        if isinstance(m, dict) and "userPrincipalName" in m
    }


def _check(name: str, problems: list[str], counts: dict[str, Any]) -> Check:
    return Check(name, "fail" if problems else "pass", tuple(problems), counts)


def _size_gb(box: dict[str, Any]) -> float | None:
    """The mailbox size in GB; None when it is not recorded; PreflightError when it is recorded but not a size."""
    value = box.get("totalItemSizeGb")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise PreflightError("a mailbox size in the mailbox data is not a non-negative number; nothing was checked")
    return float(value)


def check_sizes(plan: MigrationPlan, mailboxes: dict[str, dict[str, Any]]) -> Check:
    quota = plan.destination.mailbox_quota_gb
    problems: list[str] = []
    total = 0.0
    largest = 0.0
    unknown = 0
    for n, upn in enumerate(plan.mailboxes, start=1):
        box = mailboxes.get(upn.lower())
        if box is None:
            problems.append(f"planned mailbox #{n} is not in this client's mailbox list")
            continue
        size = _size_gb(box)
        if size is None:
            problems.append(
                f"{box['userPrincipalName']} has no size recorded, so it cannot be checked against the quota"
            )
            unknown += 1
            continue
        total += size
        largest = max(largest, size)
        if size > quota:
            problems.append(f"{box['userPrincipalName']} is {size:g} GB, over the destination quota of {quota:g} GB")
    counts = {
        "planned": len(plan.mailboxes),
        "total_gb": round(total, 2),
        "largest_gb": largest,
        "quota_gb": quota,
        "unknown_size": unknown,
    }
    return _check("mailbox-sizes", problems, counts)


def _kind(box: dict[str, Any]) -> str | None:
    value = box.get("recipientTypeDetails")
    return value.strip() if isinstance(value, str) and value.strip() else None


def check_licences(plan: MigrationPlan, mailboxes: dict[str, dict[str, Any]]) -> Check:
    lic = plan.destination.licence
    planned = [mailboxes[upn.lower()] for upn in plan.mailboxes if upn.lower() in mailboxes]
    kinds = Counter(_kind(box) for box in planned)
    unknown = [str(box["userPrincipalName"]) for box in planned if _kind(box) is None]
    user_boxes = kinds.get("UserMailbox", 0)
    need = user_boxes + len(unknown)  # an unknown type is counted as needing a seat until a person says otherwise
    over = max(0, lic.assigned - lic.enabled)
    free = max(0, lic.enabled - lic.assigned)
    problems: list[str] = []
    if over:
        problems.append(
            f"the destination {lic.sku_part_number} is over-assigned: {lic.assigned} assigned of {lic.enabled} "
            f"bought, {over} more than bought; no seat is free"
        )
    problems.extend(f"{upn} has no recipient type, so it is counted as needing a seat" for upn in unknown)
    if need > free:
        problems.append(
            f"{need} user mailboxes need a {lic.sku_part_number} seat and {free} are free; {need - free} short"
        )
    counts = {
        "sku": lic.sku_part_number,
        "user_mailboxes": user_boxes,
        "shared_mailboxes": kinds.get("SharedMailbox", 0),
        "other_mailboxes": sum(v for k, v in kinds.items() if k not in (None, "UserMailbox", "SharedMailbox")),
        "unknown_type_mailboxes": len(unknown),
        "enabled": lic.enabled,
        "assigned": lic.assigned,
        "free": free,
        "over_assigned": over,
        "shared_note": "whether a shared mailbox needs a licence is UNVERIFIED; a person decides",
    }
    return _check("licence-availability", problems, counts)


def target_address(upn: str, domain: str) -> str:
    return f"{upn.split('@', 1)[0].lower()}@{domain.lower()}"


def check_addresses(plan: MigrationPlan, mailboxes: dict[str, dict[str, Any]]) -> Check:
    domain = plan.destination.domain
    in_use = {a.strip().lower() for a in plan.destination.addresses_in_use}
    targets: dict[str, list[str]] = {}
    for upn in plan.mailboxes:
        if upn.lower() in mailboxes:
            targets.setdefault(target_address(upn, domain), []).append(str(mailboxes[upn.lower()]["userPrincipalName"]))
    problems: list[str] = []
    for address, sources in sorted(targets.items()):
        if address in in_use:
            problems.append(f"{address} (for {sources[0]}) is already in use at the destination")
        if len(sources) > 1:
            problems.append(f"{address} is the destination address of {len(sources)} planned mailboxes")
    counts = {"addresses": len(targets), "in_use_at_destination": len(in_use), "domain": domain}
    return _check("conflicting-addresses", problems, counts)


def preflight(
    client: str,
    plan_path: Path | None = None,
    *,
    tenant_dir: Path = DEFAULT_TENANT_DIR,
) -> Preflight:
    """Run the three read-only checks for one client's migration plan (B77-3)."""
    check_client(client)
    plan = load_plan(plan_path or default_plan_path(client), client)
    mailboxes = load_mailboxes(client, tenant_dir)
    checks = (check_sizes(plan, mailboxes), check_licences(plan, mailboxes), check_addresses(plan, mailboxes))
    return Preflight(client, plan.kind, plan.destination.label, checks)
