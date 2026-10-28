"""Markdown for a B-75 true-up report. Every number is read from the report dict, never recomputed (C-21)."""

from __future__ import annotations

from typing import Any

SEAT_KEYS = ("purchased", "assigned", "active", "unused", "duplicate", "orphaned", "free", "reducible")


def _n(value: Any) -> str:
    return "unknown" if value is None else str(value)


def _cell(text: Any) -> str:
    return str(text).replace("|", "/").replace("\n", " ")


def _table(header: list[str], rows: list[list[Any]], empty: str) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    if not rows:
        lines.append("| " + empty + " |" + " |" * (len(header) - 1))
    return lines


def render_markdown(report: dict[str, Any]) -> str:
    """A plain report a person reads. Fixture-based; proposals only."""
    p, t = report["parameters"], report["seat_totals"]
    u, d = report["users"], report["devices"]
    lines = [
        f"# Licence true-up: {report['client']} (as of {report['as_of']})",
        "",
        f"> {report['label']}",
        "> Nothing was bought, cancelled, assigned or removed. Every change below is a proposal that needs approval.",
        "",
        f"{report['display_name']}. Windows: {p['inactive_days']} days without a sign-in counts as unused, "
        f"{p['device_days']} days without a check-in counts as a stale device, "
        f"renewals shown {p['within_days']} days ahead.",
        "",
        "## Seats: bought, assigned, active",
        "",
    ]
    seat_rows = [[s["sku"], *(_n(s[k]) for k in SEAT_KEYS), f"{s['monthly_saving']:.2f}"] for s in report["seats"]]
    seat_rows.append(["Total", *(_n(t[k]) for k in SEAT_KEYS), f"{t['monthly_saving']:.2f}"])
    lines += _table(
        [
            "SKU",
            "Purchased",
            "Assigned",
            "Active",
            "Unused",
            "Duplicate",
            "Orphaned",
            "Free",
            "Reducible",
            "Monthly saving",
        ],
        seat_rows,
        "no SKUs",
    )
    lines += [
        "",
        "Free is purchased minus assigned (negative means over-assigned). Reducible is purchased minus active seats "
        "minus orphaned seats still inside a retention window. Monthly saving is reducible seats times a synthetic "
        "unit price: an illustration, not a quote. Unused means no successful sign-in in the sign-in records the "
        "fixture holds, which are a sample and not a full log.",
        "",
        "## Seats needing a decision",
        "",
    ]
    lines += _table(
        ["User", "SKU", "Status", "Why", "Last sign-in", "Retention ends"],
        [
            [
                r["upn"] or "(no user name)",
                r["sku"],
                r["status"],
                r["reason"],
                _n(r["last_sign_in"]),
                _n(r["retention_ends_on"]),
            ]
            for r in report["seat_rows"]
            if r["status"] != "active"
        ],
        "none",
    )
    lines += [
        "",
        "## Billing true-up",
        "",
        f"- Users: billed {u['billed']}, enabled in the directory {u['directory_enabled']}, holding any seat "
        f"{u['licensed']}, with an active seat {u['active']}. Difference (billed minus enabled): {u['billing_delta']}.",
        f"- Devices: billed {d['billed']}, active in the RMM {d['rmm_active']} "
        f"({d['rmm_unique']} unique, {d['rmm_stale']} stale, {d['rmm_duplicate_records']} duplicate records of "
        f"{d['rmm_records']}), active in the PSA {d['psa_active']}. Difference (billed minus RMM active): "
        f"{d['billing_delta']}. RMM minus PSA: {d['rmm_vs_psa_delta']}.",
        "",
        "## Renewals and lapsed dates",
        "",
    ]
    lines += _table(
        ["Ends", "Days left", "Status", "Kind", "Name", "Owner"],
        [[r["ends_on"], r["days_left"], r["status"], r["kind"], r["name"], r["owner"]] for r in report["renewals"]],
        "nothing due",
    )
    lines += ["", "## Hardware lifecycle", ""]
    lines += _table(
        ["Hostname", "Purchased", "Lifecycle ends", "Lifecycle", "Warranty ends", "Seen in RMM"],
        [
            [
                h["hostname"],
                h["purchased_on"],
                h["lifecycle_ends_on"],
                h["lifecycle"],
                _n(h["warranty_ends_on"]),
                "yes" if h["in_rmm"] else "no",
            ]
            for h in report["hardware"]
        ],
        "no hardware listed",
    )
    lines += ["", "## Proposals (each needs approval)", ""]
    lines += _table(
        ["Id", "Type", "Approver", "Proposal", "Evidence"],
        [[x["id"], x["type"], x["approver"], x["summary"], x["evidence"]] for x in report["proposals"]],
        "none",
    )
    lines += ["", "## Gaps", ""]
    lines += _table(
        ["Kind", "Subject", "Detail"], [[g["kind"], g["subject"], g["detail"]] for g in report["gaps"]], "none"
    )
    rec = report["reconciliation"]
    agree = sum(1 for c in rec["checks"] if c["ok"])
    lines += [
        "",
        "## Reconciliation",
        "",
        f"{agree} of {len(rec['checks'])} checks agree." + ("" if rec["ok"] else " The report does not reconcile."),
        "",
    ]
    lines += _table(
        ["Check", "Left", "Right", "Agrees"],
        [[c["name"], c["left"], c["right"], "yes" if c["ok"] else "NO"] for c in rec["checks"]],
        "none",
    )
    lines.append("")
    return "\n".join(lines)
