"""Licence reconciliation, seat and device true-up, renewals (B-75, specs/B-75.md; W-VND-01, W-VND-02, W-VND-03,
W-BIL-02, W-EP-10; C-21, C-27).

For one client this reads synthetic fixtures (never the network) and builds a review report:

- **Seats** per SKU: bought (``prepaidUnits.enabled``), assigned, and each assigned seat in exactly one bucket:
  ``orphaned`` (user not in the directory, disabled, or no user name), ``duplicate`` (the same SKU twice for one user,
  or a SKU that overlaps one the user also holds), ``unused`` (no successful sign-in inside the window) or ``active``.
  ``free`` is bought minus assigned and may be negative (over-assigned).
- **True-up**: billed users and devices from the (synthetic) agreement against the directory and the RMM / PSA counts.
- **Renewals** (subscriptions, warranties, domains) due inside the window or already lapsed, and hardware past or near
  the end of its lifecycle.
- **Proposals**: every change is a proposal that needs approval. ``executed`` is always false: nothing is bought,
  cancelled, assigned or removed (W-VND-02 is never automated). The module has no write path to any system; its only
  output is the report file.
- **Reconciliation**: the report re-adds its own numbers and lists each check; a mismatch is visible, not hidden (C-21).

Isolation (C-27): every entry point takes one client and opens only that client's files; a file whose client field
differs is refused, and RMM / PSA rows of another site or company are dropped. Dates come from ``as_of`` (the
licensing fixture's pinned date by default), never the wall clock. Every figure is fixture-based.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from workflows.licensing.render import render_markdown

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TENANT_DIR = REPO_ROOT / "fixtures" / "tenant"
DEFAULT_RMM_DIR = REPO_ROOT / "fixtures" / "rmm"
DEFAULT_PSA_DIR = REPO_ROOT / "workflows" / "device_reconcile" / "psa_assets"
DEFAULT_LICENSING_DIR = REPO_ROOT / "fixtures" / "licensing"
DEFAULT_OUT_DIR = REPO_ROOT / "build" / "licensing"

DEFAULT_INACTIVE_DAYS = 30
DEFAULT_DEVICE_DAYS = 30
DEFAULT_WITHIN_DAYS = 90
MAX_DAYS = 3650
VERSION = 1
KIND = "licence-true-up"
LABEL = (
    "Synthetic data. Every figure is fixture-based: computed from this repo's invented fixtures, not from a real "
    "tenant, RMM, PSA, billing system or vendor portal."
)
APPROVER_BILLING = "billing"
APPROVER_ACCOUNT = "account manager"
CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATUSES = ("active", "unused", "duplicate", "orphaned")

Report = dict[str, Any]


class LicensingError(ValueError):
    """The input is bad (client id, date, window, file); nothing was reported."""


@dataclass(frozen=True)
class Written:
    json_path: Path
    markdown_path: Path
    sha256: str
    proposals: int


# -- small helpers -------------------------------------------------------------------------------------------------
def _date(text: object) -> date | None:
    """A strict YYYY-MM-DD date, or None. Never guesses."""
    if not isinstance(text, str) or not ISO_DATE.fullmatch(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _stamp_day(text: object) -> date | None:
    """The date part of an ISO timestamp such as 2026-10-21T07:58:10Z, or None."""
    return _date(text[:10]) if isinstance(text, str) else None


def _add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 February
        return day.replace(year=day.year + years, day=28)


def _name(value: object) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def _whole(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _window(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_DAYS:
        raise LicensingError(f"{name} must be a whole number of days from 0 to {MAX_DAYS}")
    return value


def _load(path: Path, client: str, what: str, *, in_meta: bool = False) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LicensingError(f"no readable {what} file for this client ({type(exc).__name__})") from exc
    if not isinstance(data, dict):
        raise LicensingError(f"the {what} file must be a JSON object")
    meta = data.get("_meta")
    owner = meta.get("client") if in_meta and isinstance(meta, dict) else data.get("client")
    if owner != client:
        raise LicensingError(f"the {what} file does not belong to this client; nothing was read")
    checked: dict[str, Any] = data
    return checked


def _dicts(value: object) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


class _Gaps:
    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []

    def add(self, kind: str, subject: str, detail: str) -> None:
        self.rows.append({"kind": kind, "subject": subject, "detail": detail})


# -- seats ---------------------------------------------------------------------------------------------------------
def _last_sign_ins(signins: dict[str, Any], as_of: date) -> dict[str, date]:
    """Latest successful sign-in date per user, ignoring failures and anything dated after as_of."""
    last: dict[str, date] = {}
    for item in _dicts(signins.get("value")):
        status = item.get("status")
        if not isinstance(status, dict) or status.get("errorCode") != 0:
            continue
        who, day = _name(item.get("userPrincipalName")), _stamp_day(item.get("createdDateTime"))
        if who and day is not None and day <= as_of and (who not in last or day > last[who]):
            last[who] = day
    return last


def _classify_seats(
    skus: dict[str, dict[str, Any]],
    assignments: list[dict[str, Any]],
    users: dict[str, dict[str, Any]],
    last_in: dict[str, date],
    overlap_groups: list[list[str]],
    as_of: date,
    inactive_days: int,
    gaps: _Gaps,
) -> tuple[list[dict[str, Any]], int]:
    """One row per assignment of a listed SKU, each in exactly one bucket. Also returns the unlisted-SKU count."""
    cutoff = as_of - timedelta(days=inactive_days)
    parts = {sid: str(s.get("skuPartNumber", sid)) for sid, s in skus.items()}
    known: list[tuple[dict[str, Any], str, str]] = []  # (assignment, sku part number, lower-case user)
    unlisted = 0
    for a in assignments:
        sid = str(a.get("skuId"))
        if sid not in skus:
            unlisted += 1
            gaps.add("unknown-sku", str(a.get("userPrincipalName") or "no user name"), f"sku={a.get('skuPartNumber')}")
            continue
        known.append((a, parts[sid], _name(a.get("userPrincipalName"))))
    held: dict[str, set[str]] = {}
    for _, part, who in known:
        held.setdefault(who, set()).add(part)
    seen: set[tuple[str, str]] = set()
    rows: list[dict[str, Any]] = []
    for a, part, who in known:
        key = (who, part)
        repeated = bool(who) and key in seen
        seen.add(key)
        loser_of = ""
        for group in overlap_groups:
            mine = [p for p in group if p in held.get(who, set())]
            if who and part in group and len(mine) > 1 and part != mine[0]:
                loser_of = mine[0]
        row: dict[str, Any] = {
            "upn": str(a.get("userPrincipalName") or ""),
            "sku": part,
            "assigned_on": a.get("assignedOn"),
            "retention_ends_on": a.get("retentionEndsOn"),
            "last_sign_in": None,
            "in_retention": False,
        }
        user = users.get(who) if who else None
        seen_day = last_in.get(who) if who else None
        row["last_sign_in"] = seen_day.isoformat() if seen_day else None
        if not who:
            row.update(status="orphaned", reason="assignment has no user name")
        elif user is None:
            row.update(status="orphaned", reason="user is not in the directory")
        elif user.get("accountEnabled") is False:
            row.update(status="orphaned", reason="account is disabled")
        elif repeated:
            row.update(status="duplicate", reason="the same SKU is assigned to this user more than once")
        elif loser_of:
            row.update(status="duplicate", reason=f"also holds {loser_of}, which overlaps this SKU")
        elif seen_day is None or seen_day < cutoff:
            when = "no successful sign-in on record" if seen_day is None else f"last sign-in {seen_day.isoformat()}"
            row.update(status="unused", reason=f"{when}; window is {inactive_days} days")
        else:
            row.update(status="active", reason=f"signed in {seen_day.isoformat()}")
        if row["status"] == "orphaned":
            ends = a.get("retentionEndsOn")
            if ends:
                end_day = _date(ends)
                if end_day is None:
                    gaps.add("bad-date", row["upn"], f"retentionEndsOn {str(ends)[:40]!r} is not YYYY-MM-DD")
                # an unreadable window is treated as still open: no reclaim is proposed on a guess
                row["in_retention"] = end_day is None or end_day >= as_of
        rows.append(row)
    return rows, unlisted


def _seat_summary(
    skus: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
    prices: dict[str, Any],
    gaps: _Gaps,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sku in skus.values():
        part = str(sku.get("skuPartNumber"))
        mine = [r for r in rows if r["sku"] == part]
        units = sku.get("prepaidUnits")
        purchased = _whole(units.get("enabled")) if isinstance(units, dict) else None
        item: dict[str, Any] = {
            "sku": part,
            "display_name": str(sku.get("displayName", part)),
            "purchased": purchased,
            "assigned": len(mine),
        }
        for status in STATUSES:
            item[status] = sum(1 for r in mine if r["status"] == status)
        item["in_retention"] = sum(1 for r in mine if r["in_retention"])
        price = prices.get(part)
        unit = float(price) if isinstance(price, (int, float)) and not isinstance(price, bool) and price >= 0 else None
        if purchased is None:
            gaps.add("seat-count-unknown", part, "prepaidUnits.enabled is missing or not a whole number; not guessed")
            item.update(free=None, over_assigned=0, floor=None, reducible=None, monthly_saving=0.0)
        else:
            floor = item["active"] + item["in_retention"]
            item["free"] = purchased - len(mine)
            item["over_assigned"] = max(0, len(mine) - purchased)
            item["floor"] = floor
            item["reducible"] = max(0, purchased - floor)
            if item["reducible"] and unit is None:
                gaps.add("no-price", part, "no unit price in the licensing fixture; saving shown as 0.00")
            item["monthly_saving"] = 0.0 if unit is None else round(item["reducible"] * unit, 2)
        out.append(item)
    return out


def _totals(seats: list[dict[str, Any]]) -> dict[str, Any]:
    keys = ("purchased", "assigned", "free", "in_retention", "reducible", *STATUSES)
    totals: dict[str, Any] = {k: sum(s[k] or 0 for s in seats) for k in keys}
    totals["monthly_saving"] = round(sum(s["monthly_saving"] for s in seats), 2)
    return totals


# -- devices -------------------------------------------------------------------------------------------------------
def _devices(
    rmm: dict[str, Any],
    psa: dict[str, Any],
    billed: int,
    as_of: date,
    device_days: int,
    gaps: _Gaps,
) -> tuple[dict[str, Any], set[str]]:
    site = rmm.get("site")
    site_uid = site.get("uid") if isinstance(site, dict) else None
    block = rmm.get("devices")
    listed = _dicts(block.get("devices")) if isinstance(block, dict) else []
    own = [d for d in listed if d.get("siteUid") == site_uid and d.get("deleted") is not True]
    newest: dict[str, date | None] = {}
    for d in own:
        who = _name(d.get("hostname"))
        day = _stamp_day(d.get("lastSeen"))
        if day is None:
            gaps.add("bad-date", str(d.get("hostname")), "lastSeen is missing or not an ISO timestamp")
        best = newest.get(who)
        if who not in newest or (day is not None and (best is None or day > best)):
            newest[who] = day
    cutoff = as_of - timedelta(days=device_days)
    active = sum(1 for day in newest.values() if day is not None and day >= cutoff)
    items = psa.get("configurationItems")
    psa_items = _dicts(items.get("items")) if isinstance(items, dict) else []
    psa_active = sum(1 for i in psa_items if i.get("companyID") == psa.get("companyID") and i.get("isActive") is True)
    devices = {
        "billed": billed,
        "rmm_records": len(own),
        "rmm_unique": len(newest),
        "rmm_duplicate_records": len(own) - len(newest),
        "rmm_active": active,
        "rmm_stale": len(newest) - active,
        "psa_active": psa_active,
        "billing_delta": billed - active,
        "rmm_vs_psa_delta": active - psa_active,
    }
    return devices, set(newest)


# -- renewals and hardware -----------------------------------------------------------------------------------------
def _renewals_and_hardware(
    lic: dict[str, Any],
    rmm_names: set[str],
    as_of: date,
    within_days: int,
    gaps: _Gaps,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    horizon = as_of + timedelta(days=within_days)
    candidates: list[dict[str, Any]] = []
    for r in _dicts(lic.get("renewals")):
        end = _date(r.get("ends_on"))
        label = str(r.get("name"))
        kind = str(r.get("kind"))
        if end is None or kind not in ("subscription", "domain"):
            gaps.add(
                "bad-date" if end is None else "bad-kind", label, f"ends_on={str(r.get('ends_on'))[:40]!r} kind={kind}"
            )
            continue
        candidates.append(
            {
                "id": str(r.get("id")),
                "kind": kind,
                "name": label,
                "end": end,
                "owner": str(r.get("owner") or APPROVER_ACCOUNT),
            }
        )
    hardware: list[dict[str, Any]] = []
    for h in _dicts(lic.get("hardware")):
        host = str(h.get("hostname"))
        bought, years, warranty = (
            _date(h.get("purchased_on")),
            h.get("lifecycle_years"),
            _date(h.get("warranty_ends_on")),
        )
        if warranty is None:
            gaps.add("bad-date", host, f"warranty_ends_on={str(h.get('warranty_ends_on'))[:40]!r}")
        else:
            candidates.append(
                {"id": f"W-{host}", "kind": "warranty", "name": host, "end": warranty, "owner": APPROVER_ACCOUNT}
            )
        life = years if isinstance(years, int) and not isinstance(years, bool) and 1 <= years <= 30 else None
        if bought is None or life is None:
            gaps.add("bad-date", host, f"purchased_on={str(h.get('purchased_on'))[:40]!r} lifecycle_years={years!r}")
            continue
        ends = _add_years(bought, life)
        state = "past" if ends < as_of else "ending-soon" if ends <= horizon else "ok"
        hardware.append(
            {
                "hostname": host,
                "purchased_on": bought.isoformat(),
                "lifecycle_years": life,
                "lifecycle_ends_on": ends.isoformat(),
                "warranty_ends_on": warranty.isoformat() if warranty else None,
                "lifecycle": state,
                "in_rmm": host.lower() in rmm_names,
            }
        )
    hardware.sort(key=lambda h: (h["lifecycle_ends_on"], h["hostname"]))
    renewals: list[dict[str, Any]] = []
    for c in sorted(candidates, key=lambda c: (c["end"], c["id"])):
        left = (c["end"] - as_of).days
        if left > within_days:
            continue
        renewals.append(
            {
                "id": c["id"],
                "kind": c["kind"],
                "name": c["name"],
                "ends_on": c["end"].isoformat(),
                "days_left": left,
                "status": "lapsed" if left < 0 else "due",
                "owner": c["owner"],
            }
        )
    return renewals, hardware


# -- proposals -----------------------------------------------------------------------------------------------------
def _proposals(client: str, rep: Report) -> list[dict[str, Any]]:
    found: list[tuple[str, str, str, str]] = []  # type, summary, evidence, approver
    for s in rep["seats"]:
        if s["reducible"]:
            found.append(
                (
                    "reduce-subscription",
                    f"Recommendation only: reduce {s['sku']} from {s['purchased']} to {s['floor']} seats "
                    f"({s['reducible']} fewer). Nothing is cancelled until approved.",
                    f"bought {s['purchased']}, assigned {s['assigned']}, active {s['active']}, "
                    f"kept inside a retention window {s['in_retention']}, free {s['free']}; "
                    "the floor assumes every unused and duplicate seat is confirmed unneeded; fixture-based",
                    APPROVER_ACCOUNT,
                )
            )
        if s["over_assigned"]:
            found.append(
                (
                    "check-over-assignment",
                    f"{s['sku']} has {s['over_assigned']} more seats assigned than bought. Check the subscription "
                    "before the next invoice; a purchase needs the client's consent.",
                    f"bought {s['purchased']}, assigned {s['assigned']}",
                    APPROVER_ACCOUNT,
                )
            )
    order = {s["sku"]: n for n, s in enumerate(rep["seats"])}
    for r in sorted(rep["seat_rows"], key=lambda r: (order[r["sku"]], r["upn"])):
        if r["status"] == "orphaned" and not r["in_retention"]:
            found.append(
                (
                    "reclaim-seat",
                    f"Reclaim the {r['sku']} seat held by {r['upn'] or 'an assignment with no user name'} "
                    "(license.remove after approval).",
                    f"{r['reason']}; retention window ends {r['retention_ends_on'] or 'not recorded'}",
                    "lead",
                )
            )
        elif r["status"] in ("unused", "duplicate"):
            found.append(
                (
                    "review-seat",
                    f"Review the {r['sku']} seat held by {r['upn']}: {r['status']}.",
                    r["reason"],
                    "lead",
                )
            )
    u, d = rep["users"], rep["devices"]
    if u["billing_delta"]:
        side = "over-billed" if u["billing_delta"] > 0 else "under-billed"
        found.append(
            (
                "true-up-billing-users",
                f"Billing true-up for users ({side} by {abs(u['billing_delta'])}): "
                "adjust the agreement count after approval.",
                f"billed {u['billed']}; {u['directory_enabled']} enabled directory users; {u['active']} users with an "
                f"active seat; {u['licensed']} users holding any seat",
                APPROVER_BILLING,
            )
        )
    if d["billing_delta"]:
        side = "over-billed" if d["billing_delta"] > 0 else "under-billed"
        found.append(
            (
                "true-up-billing-devices",
                f"Billing true-up for devices ({side} by {abs(d['billing_delta'])}): "
                "adjust the agreement count after approval.",
                f"billed {d['billed']}; {d['rmm_active']} active in the RMM; {d['rmm_unique']} unique RMM devices "
                f"({d['rmm_duplicate_records']} duplicate records); {d['psa_active']} active in the PSA",
                APPROVER_BILLING,
            )
        )
    for r in rep["renewals"]:
        when = f"lapsed {-r['days_left']} days ago" if r["status"] == "lapsed" else f"due in {r['days_left']} days"
        found.append(
            (
                "renew",
                f"Renewal: {r['kind']} {r['name']} ends {r['ends_on']} ({when}). Ask the client; a person renews.",
                f"{r['kind']} end date {r['ends_on']} from the licensing fixture",
                r["owner"],
            )
        )
    for h in rep["hardware"]:
        if h["lifecycle"] == "past":
            found.append(
                (
                    "replace-hardware",
                    f"Plan replacement of {h['hostname']}: past its {h['lifecycle_years']}-year lifecycle.",
                    f"purchased {h['purchased_on']}; lifecycle ended {h['lifecycle_ends_on']}; "
                    f"warranty ended {h['warranty_ends_on']}",
                    APPROVER_ACCOUNT,
                )
            )
    return [
        {
            "id": f"P-{n:03d}",
            "type": kind,
            "client": client,
            "summary": summary,
            "evidence": evidence,
            "approval_required": True,
            "approver": approver,
            "status": "proposed",
            "executed": False,
        }
        for n, (kind, summary, evidence, approver) in enumerate(found, start=1)
    ]


# -- reconciliation ------------------------------------------------------------------------------------------------
def _reconcile(rep: Report, assignment_rows: int, unlisted: int) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, left: int, right: int) -> None:
        checks.append({"name": name, "left": left, "right": right, "ok": left == right})

    for s in rep["seats"]:
        mine = sum(1 for r in rep["seat_rows"] if r["sku"] == s["sku"])
        check(f"{s['sku']}: seat rows = assigned", mine, s["assigned"])
        check(
            f"{s['sku']}: active + unused + duplicate + orphaned = assigned", sum(s[k] for k in STATUSES), s["assigned"]
        )
        if s["purchased"] is not None:
            check(f"{s['sku']}: purchased - assigned = free", s["purchased"] - s["assigned"], s["free"])
    check(
        "seat rows + seats on unlisted SKUs = assignments in the licence file",
        len(rep["seat_rows"]) + unlisted,
        assignment_rows,
    )
    for key in ("assigned", *STATUSES):
        check(f"total {key} = sum over SKUs", rep["seat_totals"][key], sum(s[key] for s in rep["seats"]))
    d = rep["devices"]
    check(
        "devices: unique + duplicate records = RMM records",
        d["rmm_unique"] + d["rmm_duplicate_records"],
        d["rmm_records"],
    )
    check("devices: active + stale = unique", d["rmm_active"] + d["rmm_stale"], d["rmm_unique"])
    check("devices: billed - RMM active = billing delta", d["billed"] - d["rmm_active"], d["billing_delta"])
    u = rep["users"]
    check(
        "users: billed - enabled directory users = billing delta",
        u["billed"] - u["directory_enabled"],
        u["billing_delta"],
    )
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


# -- build ---------------------------------------------------------------------------------------------------------
def build_report(
    client: str,
    as_of: str | None = None,
    *,
    inactive_days: int = DEFAULT_INACTIVE_DAYS,
    device_days: int = DEFAULT_DEVICE_DAYS,
    within_days: int = DEFAULT_WITHIN_DAYS,
    tenant_dir: Path = DEFAULT_TENANT_DIR,
    rmm_dir: Path = DEFAULT_RMM_DIR,
    psa_dir: Path = DEFAULT_PSA_DIR,
    licensing_dir: Path = DEFAULT_LICENSING_DIR,
) -> Report:
    """The true-up report for one client: a plain dict, deterministic for the same inputs."""
    if not isinstance(client, str) or not CLIENT_ID.fullmatch(client):
        raise LicensingError("invalid client id")
    inactive_days = _window("inactive_days", inactive_days)
    device_days = _window("device_days", device_days)
    within_days = _window("within_days", within_days)
    lic = _load(Path(licensing_dir) / f"{client}.json", client, "licensing", in_meta=True)
    day = _date(as_of if as_of is not None else lic.get("as_of"))
    if day is None:
        raise LicensingError("as_of must be a date written YYYY-MM-DD")
    tenant = Path(tenant_dir)
    licences = _load(tenant / client / "licenses.json", client, "licence", in_meta=True)
    directory = _load(tenant / f"{client}.json", client, "directory", in_meta=True)
    signins = _load(tenant / client / "signins.json", client, "sign-in", in_meta=True)
    rmm = _load(Path(rmm_dir) / f"{client}.json", client, "RMM")
    psa = _load(Path(psa_dir) / f"{client}.json", client, "PSA")
    agreement: dict[str, Any] = lic["agreement"] if isinstance(lic.get("agreement"), dict) else {}
    billed_users, billed_devices = _whole(agreement.get("billed_users")), _whole(agreement.get("billed_devices"))
    if billed_users is None or billed_devices is None:
        raise LicensingError(
            "the licensing file needs agreement.billed_users and agreement.billed_devices (whole numbers)"
        )
    prices: dict[str, Any] = lic["unit_prices_monthly"] if isinstance(lic.get("unit_prices_monthly"), dict) else {}
    groups_raw = lic.get("overlap_groups")
    groups = [[str(p) for p in g] for g in groups_raw if isinstance(g, list)] if isinstance(groups_raw, list) else []

    gaps = _Gaps()
    skus = {str(s.get("skuId")): s for s in _dicts(licences.get("skus"))}
    assignments = _dicts(licences.get("assignments"))
    entries = _dicts(directory.get("users"))
    users = {_name(u.get("userPrincipalName")): u for u in entries if _name(u.get("userPrincipalName"))}
    rows, unlisted = _classify_seats(
        skus, assignments, users, _last_sign_ins(signins, day), groups, day, inactive_days, gaps
    )
    seats = _seat_summary(skus, rows, prices, gaps)
    devices, rmm_names = _devices(rmm, psa, billed_devices, day, device_days, gaps)
    renewals, hardware = _renewals_and_hardware(lic, rmm_names, day, within_days, gaps)
    enabled = sum(1 for u in users.values() if u.get("accountEnabled") is True)
    rep: Report = {
        "kind": KIND,
        "version": VERSION,
        "client": client,
        "display_name": str(licences.get("_meta", {}).get("displayName", client)),
        "as_of": day.isoformat(),
        "label": LABEL,
        "parameters": {"inactive_days": inactive_days, "device_days": device_days, "within_days": within_days},
        "seats": seats,
        "seat_totals": _totals(seats),
        "seat_rows": sorted(rows, key=lambda r: (r["sku"], r["upn"])),
        "users": {
            "billed": billed_users,
            "directory_enabled": enabled,
            "licensed": len({_name(r["upn"]) for r in rows}),
            "active": len({_name(r["upn"]) for r in rows if r["status"] == "active"}),
            "billing_delta": billed_users - enabled,
        },
        "devices": devices,
        "renewals": renewals,
        "hardware": hardware,
        "gaps": gaps.rows,
        "executed_changes": 0,
    }
    rep["proposals"] = _proposals(client, rep)
    rep["reconciliation"] = _reconcile(rep, len(assignments), unlisted)
    return rep


# -- files ---------------------------------------------------------------------------------------------------------
def canonical_bytes(report: Report) -> bytes:
    """Sorted keys, two-space indent, ASCII, one trailing newline: the same inputs give the same bytes."""
    return (json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def write_report(
    client: str,
    as_of: str | None = None,
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    **kw: Any,
) -> Written:
    """Write ``<out>/<as_of>/<client>.json``, ``.md`` and ``.json.sha256`` (sha256sum format). Nothing else."""
    report = build_report(client, as_of, **kw)
    data = canonical_bytes(report)
    digest = hashlib.sha256(data).hexdigest()
    folder = Path(out_dir) / report["as_of"]
    folder.mkdir(parents=True, exist_ok=True)
    json_path = folder / f"{client}.json"
    md_path = folder / f"{client}.md"
    json_path.write_bytes(data)
    md_path.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    json_path.with_name(json_path.name + ".sha256").write_text(
        f"{digest}  {json_path.name}\n", encoding="ascii", newline="\n"
    )
    return Written(json_path, md_path, digest, len(report["proposals"]))
