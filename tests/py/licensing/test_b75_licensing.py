"""B-75 licence reconciliation, seat and device true-up, renewals. Acceptance ids B75-1 to B75-3: specs/B-75.md.

Offline and deterministic: dates are pinned with as_of, output goes under tmp_path, committed fixtures are never
modified (tests that change an input work on a copy under tmp_path). Every figure here comes from the synthetic
fixtures and is fixture-based. The arithmetic is recomputed in this file straight from the raw fixture JSON, not from
the workflow's own helpers, so a wrong count in the report cannot pass by agreeing with itself.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/licensing
"""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from workflows.licensing import (
    DEFAULT_LICENSING_DIR,
    DEFAULT_PSA_DIR,
    DEFAULT_RMM_DIR,
    DEFAULT_TENANT_DIR,
    LicensingError,
    build_report,
    render_markdown,
    write_report,
)
from workflows.licensing.__main__ import main

REPO = Path(__file__).resolve().parents[3]
AS_OF = "2026-10-22"
CLIENTS = ("contoso-dental", "fabrikam-capital")
BUCKETS = ("active", "unused", "duplicate", "orphaned")


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class Inputs:
    """A private copy of one client's input files, so a test can edit them."""

    def __init__(self, root: Path, client: str) -> None:
        self.client = client
        self.tenant = root / "tenant"
        self.rmm = root / "rmm"
        self.psa = root / "psa"
        self.lic = root / "licensing"
        (self.tenant / client).mkdir(parents=True)
        for rel in (f"{client}.json", f"{client}/licenses.json", f"{client}/signins.json"):
            shutil.copy(DEFAULT_TENANT_DIR / rel, self.tenant / rel)
        for src, dst in ((DEFAULT_RMM_DIR, self.rmm), (DEFAULT_PSA_DIR, self.psa), (DEFAULT_LICENSING_DIR, self.lic)):
            dst.mkdir()
            shutil.copy(src / f"{client}.json", dst / f"{client}.json")

    def path(self, which: str) -> Path:
        return {
            "licenses": self.tenant / self.client / "licenses.json",
            "signins": self.tenant / self.client / "signins.json",
            "directory": self.tenant / f"{self.client}.json",
            "rmm": self.rmm / f"{self.client}.json",
            "psa": self.psa / f"{self.client}.json",
            "lic": self.lic / f"{self.client}.json",
        }[which]

    def edit(self, which: str, change: Callable[[Any], None]) -> None:
        data = _json(self.path(which))
        change(data)
        self.path(which).write_text(json.dumps(data), encoding="utf-8")

    def report(self, **kw: Any) -> dict[str, Any]:
        return build_report(
            self.client,
            as_of=kw.pop("as_of", AS_OF),
            tenant_dir=self.tenant,
            rmm_dir=self.rmm,
            psa_dir=self.psa,
            licensing_dir=self.lic,
            **kw,
        )


@pytest.fixture
def inputs(tmp_path: Path) -> Callable[..., Inputs]:
    def make(client: str = "contoso-dental") -> Inputs:
        return Inputs(tmp_path / client, client)

    return make


def _sku(report: dict[str, Any], part: str) -> dict[str, Any]:
    hits = [s for s in report["seats"] if s["sku"] == part]
    assert len(hits) == 1, part
    return hits[0]


def _row(report: dict[str, Any], upn: str, sku: str) -> dict[str, Any]:
    hits = [r for r in report["seat_rows"] if r["upn"] == upn and r["sku"] == sku]
    assert len(hits) == 1, (upn, sku)
    return hits[0]


# --- B75-1: bought vs assigned vs active, and every count reconciles ----------------------------------------------


def test_b75_1_purchased_and_assigned_match_the_raw_licence_file() -> None:
    for client in CLIENTS:
        raw = _json(DEFAULT_TENANT_DIR / client / "licenses.json")
        report = build_report(client, as_of=AS_OF)
        for sku in raw["skus"]:
            row = _sku(report, sku["skuPartNumber"])
            assert row["purchased"] == sku["prepaidUnits"]["enabled"]
            assert row["assigned"] == sum(1 for a in raw["assignments"] if a["skuId"] == sku["skuId"])
            assert row["free"] == row["purchased"] - row["assigned"]


def test_b75_1_every_assigned_seat_is_in_exactly_one_bucket() -> None:
    for client in CLIENTS:
        report = build_report(client, as_of=AS_OF)
        raw = _json(DEFAULT_TENANT_DIR / client / "licenses.json")
        assert len(report["seat_rows"]) == len(raw["assignments"])
        for sku in report["seats"]:
            assert sum(sku[b] for b in BUCKETS) == sku["assigned"]
            rows = [r for r in report["seat_rows"] if r["sku"] == sku["sku"]]
            assert len(rows) == sku["assigned"]
            for bucket in BUCKETS:
                assert sku[bucket] == sum(1 for r in rows if r["status"] == bucket)
        totals = report["seat_totals"]
        for key in ("purchased", "assigned", "free", *BUCKETS):
            assert totals[key] == sum(s[key] for s in report["seats"])


def test_b75_1_committed_fixture_figures_contoso_dental() -> None:
    report = build_report("contoso-dental", as_of=AS_OF)
    premium = _sku(report, "O365_BUSINESS_PREMIUM")
    assert (premium["purchased"], premium["assigned"], premium["active"], premium["unused"]) == (6, 6, 3, 2)
    assert (premium["duplicate"], premium["orphaned"], premium["free"]) == (0, 1, 0)
    ess = _sku(report, "O365_BUSINESS_ESSENTIALS")
    assert (ess["purchased"], ess["assigned"], ess["active"], ess["orphaned"], ess["free"]) == (4, 2, 0, 1, 2)
    assert ess["in_retention"] == 1


def test_b75_1_committed_fixture_figures_fabrikam_capital() -> None:
    report = build_report("fabrikam-capital", as_of=AS_OF)
    premium = _sku(report, "O365_BUSINESS_PREMIUM")
    assert (premium["purchased"], premium["assigned"], premium["active"], premium["unused"]) == (10, 6, 1, 4)
    assert (premium["duplicate"], premium["orphaned"], premium["free"]) == (0, 1, 4)
    e3 = _sku(report, "ENTERPRISEPACK")
    assert (e3["purchased"], e3["assigned"], e3["active"], e3["duplicate"], e3["free"]) == (3, 3, 0, 3, 0)


def test_b75_1_active_means_a_successful_sign_in_inside_the_window(inputs: Callable[..., Inputs]) -> None:
    raw = _json(DEFAULT_TENANT_DIR / "contoso-dental" / "signins.json")["value"]
    last: dict[str, str] = {}
    for s in raw:
        if s["status"]["errorCode"] == 0:
            upn = s["userPrincipalName"]
            last[upn] = max(last.get(upn, ""), s["createdDateTime"][:10])
    report = build_report("contoso-dental", as_of=AS_OF)
    for row in report["seat_rows"]:
        assert row["last_sign_in"] == last.get(row["upn"])
    jamie = _row(report, "jamie.chen@contosodental.example", "O365_BUSINESS_PREMIUM")
    assert (jamie["status"], jamie["last_sign_in"]) == ("unused", None)
    # the latest committed sign-in is 2026-10-21, so a zero-day window ending 2026-10-22 keeps nobody
    assert inputs().report(inactive_days=0)["seat_totals"]["active"] == 0


def test_b75_1_a_failed_or_future_sign_in_is_not_activity(inputs: Callable[..., Inputs]) -> None:
    box = inputs()

    def change(data: dict[str, Any]) -> None:
        for s in data["value"]:
            if s["userPrincipalName"].startswith("sam.patel"):
                s["status"]["errorCode"] = 50126
            if s["userPrincipalName"].startswith("tom.baker"):
                s["createdDateTime"] = "2026-11-30T09:00:00Z"

    box.edit("signins", change)
    report = box.report()
    assert _row(report, "sam.patel@contosodental.example", "O365_BUSINESS_PREMIUM")["status"] == "unused"
    assert _row(report, "tom.baker@contosodental.example", "O365_BUSINESS_PREMIUM")["status"] == "unused"


def test_b75_1_orphaned_seats_are_users_missing_from_the_directory_or_disabled(
    inputs: Callable[..., Inputs],
) -> None:
    report = build_report("contoso-dental", as_of=AS_OF)
    pat = _row(report, "pat.ellis@contosodental.example", "O365_BUSINESS_PREMIUM")
    assert pat["status"] == "orphaned" and pat["in_retention"] is False
    assert "not in the directory" in pat["reason"]
    mo = _row(report, "mo.reyes@contosodental.example", "O365_BUSINESS_ESSENTIALS")
    assert mo["status"] == "orphaned" and mo["in_retention"] is True
    box = inputs()

    def disable(data: dict[str, Any]) -> None:
        for u in data["users"]:
            if u["userPrincipalName"].startswith("ana.lopez"):
                u["accountEnabled"] = False

    box.edit("directory", disable)
    ana = _row(box.report(), "ana.lopez@contosodental.example", "O365_BUSINESS_PREMIUM")
    assert ana["status"] == "orphaned" and "disabled" in ana["reason"]


def test_b75_1_duplicates_are_a_repeated_seat_or_an_overlapping_sku() -> None:
    report = build_report("fabrikam-capital", as_of=AS_OF)
    for who in ("morgan.reyes", "riley.brooks", "dana.kim"):
        upn = f"{who}@fabrikamcapital.example"
        assert _row(report, upn, "ENTERPRISEPACK")["status"] == "duplicate"
        assert _row(report, upn, "O365_BUSINESS_PREMIUM")["status"] != "duplicate"


def test_b75_1_the_same_user_and_sku_twice_counts_the_second_as_duplicate(inputs: Callable[..., Inputs]) -> None:
    box = inputs()

    def change(data: dict[str, Any]) -> None:
        data["assignments"].append(dict(data["assignments"][0]))

    box.edit("licenses", change)
    report = box.report()
    premium = _sku(report, "O365_BUSINESS_PREMIUM")
    assert (premium["assigned"], premium["duplicate"], premium["free"]) == (7, 1, -1)
    assert premium["over_assigned"] == 1
    assert sum(1 for p in report["proposals"] if p["type"] == "check-over-assignment") == 1
    assert report["reconciliation"]["ok"] is True


def test_b75_1_a_sku_the_tenant_does_not_list_is_a_gap_not_a_seat(inputs: Callable[..., Inputs]) -> None:
    box = inputs()

    def change(data: dict[str, Any]) -> None:
        data["assignments"].append(
            {"userPrincipalName": "ana.lopez@contosodental.example", "skuId": "x", "skuPartNumber": "MYSTERY"}
        )

    box.edit("licenses", change)
    report = box.report()
    assert [g["kind"] for g in report["gaps"]] == ["unknown-sku"]
    assert len(report["seat_rows"]) == len(_json(box.path("licenses"))["assignments"]) - 1
    assert report["reconciliation"]["ok"] is True


def test_b75_1_a_missing_seat_count_is_reported_not_guessed(inputs: Callable[..., Inputs]) -> None:
    box = inputs()

    def change(data: dict[str, Any]) -> None:
        data["skus"][0]["prepaidUnits"] = {}

    box.edit("licenses", change)
    report = box.report()
    premium = _sku(report, "O365_BUSINESS_PREMIUM")
    assert premium["purchased"] is None and premium["free"] is None
    assert "seat-count-unknown" in [g["kind"] for g in report["gaps"]]
    assert not [p for p in report["proposals"] if p["type"] == "reduce-subscription" and "PREMIUM" in p["summary"]]
    assert report["reconciliation"]["ok"] is True


def test_b75_1_the_report_reconciles_itself() -> None:
    for client in CLIENTS:
        report = build_report(client, as_of=AS_OF)
        assert report["reconciliation"]["ok"] is True
        assert report["reconciliation"]["checks"]
        assert all(c["ok"] and c["left"] == c["right"] for c in report["reconciliation"]["checks"])


def test_b75_1_user_and_device_counts_match_the_raw_files() -> None:
    for client in CLIENTS:
        report = build_report(client, as_of=AS_OF)
        lic = _json(DEFAULT_LICENSING_DIR / f"{client}.json")
        directory = _json(DEFAULT_TENANT_DIR / f"{client}.json")
        rmm = _json(DEFAULT_RMM_DIR / f"{client}.json")
        psa = _json(DEFAULT_PSA_DIR / f"{client}.json")
        users = report["users"]
        assert users["billed"] == lic["agreement"]["billed_users"]
        assert users["directory_enabled"] == sum(1 for u in directory["users"] if u["accountEnabled"] is True)
        assert users["licensed"] == len({r["upn"] for r in report["seat_rows"]})
        assert users["active"] == len({r["upn"] for r in report["seat_rows"] if r["status"] == "active"})
        assert users["billing_delta"] == users["billed"] - users["directory_enabled"]
        site = rmm["site"]["uid"]
        own = [d for d in rmm["devices"]["devices"] if d["siteUid"] == site and not d["deleted"]]
        names = {d["hostname"].lower() for d in own}
        devices = report["devices"]
        assert devices["rmm_records"] == len(own)
        assert devices["rmm_unique"] == len(names)
        assert devices["rmm_duplicate_records"] == len(own) - len(names)
        assert devices["rmm_active"] + devices["rmm_stale"] == devices["rmm_unique"]
        assert devices["psa_active"] == sum(
            1 for i in psa["configurationItems"]["items"] if i["companyID"] == psa["companyID"] and i["isActive"]
        )
        assert devices["billed"] == lic["agreement"]["billed_devices"]
        assert devices["billing_delta"] == devices["billed"] - devices["rmm_active"]


def test_b75_1_committed_device_figures() -> None:
    contoso = build_report("contoso-dental", as_of=AS_OF)["devices"]
    assert (contoso["rmm_records"], contoso["rmm_unique"], contoso["rmm_duplicate_records"]) == (9, 8, 1)
    assert (contoso["rmm_active"], contoso["rmm_stale"], contoso["psa_active"]) == (7, 1, 8)
    assert (contoso["billed"], contoso["billing_delta"]) == (9, 2)
    fab = build_report("fabrikam-capital", as_of=AS_OF)["devices"]
    assert (fab["rmm_records"], fab["rmm_active"], fab["psa_active"], fab["billing_delta"]) == (4, 4, 4, 0)


def test_b75_1_another_clients_device_rows_are_never_counted() -> None:
    # The RMM and PSA fixtures hold a decoy row of the other client on purpose (C-27).
    rmm = _json(DEFAULT_RMM_DIR / "contoso-dental.json")
    assert len(rmm["devices"]["devices"]) == 10
    assert build_report("contoso-dental", as_of=AS_OF)["devices"]["rmm_records"] == 9
    assert build_report("fabrikam-capital", as_of=AS_OF)["devices"]["rmm_records"] == 4


def test_b75_1_a_fixture_file_of_another_client_is_refused(inputs: Callable[..., Inputs]) -> None:
    box = inputs()
    shutil.copy(DEFAULT_LICENSING_DIR / "fabrikam-capital.json", box.path("lic"))
    with pytest.raises(LicensingError, match="does not belong"):
        box.report()
    box = inputs("fabrikam-capital")
    shutil.copy(DEFAULT_RMM_DIR / "contoso-dental.json", box.path("rmm"))
    with pytest.raises(LicensingError, match="does not belong"):
        box.report()


@pytest.mark.parametrize("bad", ["", "../x", "Contoso", "a b", "a/b", "x" * 80])
def test_b75_1_a_bad_client_id_is_refused_before_any_file_is_opened(bad: str) -> None:
    with pytest.raises(LicensingError, match="client id"):
        build_report(bad, as_of=AS_OF)


def test_b75_1_a_client_with_no_licence_data_is_refused_not_reported_empty() -> None:
    with pytest.raises(LicensingError, match="no readable"):
        build_report("litware-legal", as_of=AS_OF)


def test_b75_1_a_bad_as_of_or_window_is_refused() -> None:
    with pytest.raises(LicensingError, match="as_of"):
        build_report("contoso-dental", as_of="22/10/2026")
    for kw in ({"inactive_days": -1}, {"device_days": -5}, {"within_days": -1}, {"within_days": 4000}):
        with pytest.raises(LicensingError, match="days"):
            build_report("contoso-dental", as_of=AS_OF, **kw)


# --- B75-2: renewals and hardware lifecycle ------------------------------------------------------------------------


def test_b75_2_renewals_inside_the_window_are_listed_soonest_first() -> None:
    report = build_report("contoso-dental", as_of=AS_OF, within_days=90)
    due = [(r["kind"], r["name"], r["ends_on"], r["days_left"]) for r in report["renewals"] if r["status"] == "due"]
    assert due == [
        ("subscription", "O365_BUSINESS_PREMIUM", "2026-11-15", 24),
        ("warranty", "DENTAL-SRV01", "2026-11-30", 39),
        ("domain", "contosodental.example", "2026-12-20", 59),
    ]
    dates = [r["ends_on"] for r in report["renewals"]]
    assert dates == sorted(dates)
    assert all(r["status"] in ("due", "lapsed") for r in report["renewals"])
    # Essentials renews on 2027-03-01, outside the window
    assert "O365_BUSINESS_ESSENTIALS" not in [r["name"] for r in report["renewals"]]


def test_b75_2_days_left_is_counted_from_as_of_and_the_edge_day_is_in() -> None:
    edge = date.fromisoformat(AS_OF) + timedelta(days=24)
    assert edge.isoformat() == "2026-11-15"
    inside = build_report("contoso-dental", as_of=AS_OF, within_days=24)
    assert "O365_BUSINESS_PREMIUM" in [r["name"] for r in inside["renewals"]]
    outside = build_report("contoso-dental", as_of=AS_OF, within_days=23)
    assert "O365_BUSINESS_PREMIUM" not in [r["name"] for r in outside["renewals"]]
    assert all(0 <= r["days_left"] <= 23 for r in outside["renewals"] if r["status"] == "due")


def test_b75_2_a_warranty_already_ended_is_listed_as_lapsed() -> None:
    report = build_report("contoso-dental", as_of=AS_OF, within_days=30)
    lapsed = {r["name"] for r in report["renewals"] if r["status"] == "lapsed"}
    assert {"RECEPTION-OLD", "HYGIENE-03"} <= lapsed
    row = next(r for r in report["renewals"] if r["name"] == "RECEPTION-OLD")
    assert row["kind"] == "warranty" and row["days_left"] < 0


def test_b75_2_renewals_cover_subscriptions_warranties_and_domains() -> None:
    kinds = {r["kind"] for r in build_report("fabrikam-capital", as_of=AS_OF, within_days=400)["renewals"]}
    assert kinds == {"subscription", "warranty", "domain"}


def test_b75_2_hardware_past_lifecycle_is_listed_with_the_date_it_passed() -> None:
    report = build_report("contoso-dental", as_of=AS_OF, within_days=90)
    past = {h["hostname"]: h for h in report["hardware"] if h["lifecycle"] == "past"}
    assert set(past) == {"RECEPTION-OLD", "HYGIENE-03"}
    assert past["RECEPTION-OLD"]["lifecycle_ends_on"] == "2025-06-01"
    assert past["HYGIENE-03"]["lifecycle_ends_on"] == "2026-01-15"
    assert [h["hostname"] for h in report["hardware"] if h["lifecycle"] == "ending-soon"] == ["DENTAL-SRV01"]
    ok = sorted(h["hostname"] for h in report["hardware"] if h["lifecycle"] == "ok")
    assert ok == ["FRONTDESK-01", "OPERATORY-02"]


def test_b75_2_hardware_not_seen_by_the_rmm_is_flagged(inputs: Callable[..., Inputs]) -> None:
    box = inputs()

    def change(data: dict[str, Any]) -> None:
        data["hardware"].append(
            {
                "hostname": "GHOST-01",
                "purchased_on": "2025-01-01",
                "warranty_ends_on": "2028-01-01",
                "lifecycle_years": 5,
            }
        )

    box.edit("lic", change)
    hardware = {h["hostname"]: h for h in box.report()["hardware"]}
    assert hardware["GHOST-01"]["in_rmm"] is False
    assert hardware["FRONTDESK-01"]["in_rmm"] is True


def test_b75_2_an_unreadable_date_is_a_gap_and_is_never_guessed(inputs: Callable[..., Inputs]) -> None:
    box = inputs()

    def change(data: dict[str, Any]) -> None:
        data["renewals"][0]["ends_on"] = "next spring"
        data["hardware"][0]["purchased_on"] = "2020-13-45"

    box.edit("lic", change)
    report = box.report()
    assert sorted(g["kind"] for g in report["gaps"]) == ["bad-date", "bad-date"]
    assert "O365_BUSINESS_PREMIUM" not in [r["name"] for r in report["renewals"]]
    assert "RECEPTION-OLD" not in [h["hostname"] for h in report["hardware"]]


# --- B75-3: recommendations only; nothing is bought, cancelled or changed -----------------------------------------


def test_b75_3_every_change_is_a_proposal_that_needs_approval_and_none_ran() -> None:
    for client in CLIENTS:
        report = build_report(client, as_of=AS_OF)
        assert report["proposals"]
        for p in report["proposals"]:
            assert p["status"] == "proposed" and p["executed"] is False
            assert p["approval_required"] is True and p["approver"]
            assert p["evidence"] and p["summary"]
            assert p["client"] == client
        assert report["executed_changes"] == 0
        ids = [p["id"] for p in report["proposals"]]
        assert ids == [f"P-{n:03d}" for n in range(1, len(ids) + 1)]


def test_b75_3_proposal_types_cover_seats_billing_renewals_and_hardware() -> None:
    types = {p["type"] for p in build_report("contoso-dental", as_of=AS_OF)["proposals"]}
    assert {
        "reduce-subscription",
        "reclaim-seat",
        "review-seat",
        "true-up-billing-users",
        "true-up-billing-devices",
        "renew",
        "replace-hardware",
    } <= types


def test_b75_3_a_reduction_is_floored_at_seats_in_use_or_in_retention() -> None:
    report = build_report("contoso-dental", as_of=AS_OF)
    by_sku = {s["sku"]: s for s in report["seats"]}
    # Essentials: 4 bought, 0 active, 1 kept inside its retention window: the floor is 1, so 3 can be reduced
    ess = by_sku["O365_BUSINESS_ESSENTIALS"]
    assert (ess["floor"], ess["reducible"]) == (1, 3)
    prem = by_sku["O365_BUSINESS_PREMIUM"]
    assert (prem["floor"], prem["reducible"]) == (3, 3)
    cut = [p for p in report["proposals"] if p["type"] == "reduce-subscription"]
    assert len(cut) == 2
    text = next(p for p in cut if "ESSENTIALS" in p["summary"])
    assert "from 4 to 1" in text["summary"]
    assert "Recommendation only" in text["summary"]


def test_b75_3_money_is_price_times_seats_and_labelled_fixture_based() -> None:
    report = build_report("contoso-dental", as_of=AS_OF)
    prices = _json(DEFAULT_LICENSING_DIR / "contoso-dental.json")["unit_prices_monthly"]
    for s in report["seats"]:
        assert s["monthly_saving"] == round(s["reducible"] * prices[s["sku"]], 2)
    assert report["seat_totals"]["monthly_saving"] == round(sum(s["monthly_saving"] for s in report["seats"]), 2)
    assert "fixture-based" in report["label"] and "synthetic" in report["label"].lower()


def test_b75_3_billing_true_up_names_the_direction() -> None:
    contoso = build_report("contoso-dental", as_of=AS_OF)
    users = next(p for p in contoso["proposals"] if p["type"] == "true-up-billing-users")
    assert "billed 7" in users["evidence"] and "6 enabled" in users["evidence"] and "over-billed" in users["summary"]
    fab = build_report("fabrikam-capital", as_of=AS_OF)
    under = next(p for p in fab["proposals"] if p["type"] == "true-up-billing-users")
    assert "under-billed" in under["summary"]
    assert not [p for p in fab["proposals"] if p["type"] == "true-up-billing-devices"]


def test_b75_3_seat_proposals_do_not_cover_a_retention_window_seat() -> None:
    report = build_report("contoso-dental", as_of=AS_OF)
    seat_props = [p for p in report["proposals"] if p["type"] in ("reclaim-seat", "review-seat")]
    assert not [p for p in seat_props if "mo.reyes" in p["summary"]]
    assert [p for p in seat_props if "pat.ellis" in p["summary"] and p["type"] == "reclaim-seat"]
    assert [p for p in seat_props if "jamie.chen" in p["summary"] and p["type"] == "review-seat"]


def test_b75_3_the_workflow_has_no_way_to_buy_cancel_call_out_or_run_a_lever() -> None:
    banned = {"subprocess", "socket", "urllib", "http", "requests", "httpx", "smtplib", "os"}
    files = list((REPO / "workflows" / "licensing").glob("*.py"))
    assert files
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in banned, (path.name, name)
                assert not name.startswith(("core.levers", "adapters", "levers")), (path.name, name)


def test_b75_3_a_run_changes_no_input_file(tmp_path: Path) -> None:
    def digest() -> str:
        h = hashlib.sha256()
        for root in (REPO / "fixtures", REPO / "workflows" / "device_reconcile" / "psa_assets", REPO / "config"):
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    h.update(p.as_posix().encode() + p.read_bytes())
        return h.hexdigest()

    before = digest()
    for client in CLIENTS:
        write_report(client, as_of=AS_OF, out_dir=tmp_path)
    assert digest() == before


# --- report files: markdown + JSON, hashed, deterministic --------------------------------------------------------


def test_b75_report_files_are_json_markdown_and_a_hash(tmp_path: Path) -> None:
    written = write_report("contoso-dental", as_of=AS_OF, out_dir=tmp_path)
    folder = tmp_path / AS_OF
    assert sorted(p.name for p in folder.iterdir()) == [
        "contoso-dental.json",
        "contoso-dental.json.sha256",
        "contoso-dental.md",
    ]
    data = (folder / "contoso-dental.json").read_bytes()
    assert written.sha256 == hashlib.sha256(data).hexdigest()
    sidecar = (folder / "contoso-dental.json.sha256").read_text(encoding="ascii")
    assert sidecar == f"{written.sha256}  contoso-dental.json\n"
    assert data.endswith(b"\n") and data.isascii()
    assert json.loads(data) == build_report("contoso-dental", as_of=AS_OF)


def test_b75_report_bytes_are_the_same_on_every_run(tmp_path: Path) -> None:
    a = write_report("fabrikam-capital", as_of=AS_OF, out_dir=tmp_path / "a")
    b = write_report("fabrikam-capital", as_of=AS_OF, out_dir=tmp_path / "b")
    assert a.sha256 == b.sha256
    name = "fabrikam-capital.md"
    assert (tmp_path / "a" / AS_OF / name).read_bytes() == (tmp_path / "b" / AS_OF / name).read_bytes()


def _table(markdown: str, heading: str) -> list[list[str]]:
    lines = markdown.splitlines()
    start = lines.index(heading) + 1
    rows: list[list[str]] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        if line.startswith("|") and not line.startswith("| ---") and not line.startswith("| SKU"):
            rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows


def test_b75_markdown_numbers_equal_the_json_numbers() -> None:
    keys = ("purchased", "assigned", "active", "unused", "duplicate", "orphaned", "free", "reducible")
    for client in CLIENTS:
        report = build_report(client, as_of=AS_OF)
        md = render_markdown(report)
        by_sku = {r[0]: r for r in _table(md, "## Seats: bought, assigned, active")}
        for s in report["seats"]:
            assert [int(c) for c in by_sku[s["sku"]][1:9]] == [s[k] for k in keys]
        total = by_sku["Total"]
        assert [int(c) for c in total[1:9]] == [report["seat_totals"][k] for k in keys]
        assert f"{report['seat_totals']['monthly_saving']:.2f}" in md
        assert f"billed {report['users']['billed']}" in md
        assert f"billed {report['devices']['billed']}" in md


def test_b75_markdown_is_labelled_and_states_nothing_was_executed() -> None:
    md = render_markdown(build_report("contoso-dental", as_of=AS_OF))
    assert md.startswith("# Licence true-up: contoso-dental (as of 2026-10-22)")
    assert "fixture-based" in md and "Synthetic" in md
    assert "Nothing was bought, cancelled, assigned or removed" in md
    assert "needs approval" in md


def test_b75_a_clients_report_never_names_another_client() -> None:
    for client, other in (("contoso-dental", "fabrikam"), ("fabrikam-capital", "contoso")):
        report = build_report(client, as_of=AS_OF)
        assert other not in json.dumps(report).lower()
        assert other not in render_markdown(report).lower()


# --- command line ---------------------------------------------------------------------------------------------------


def test_b75_cli_writes_the_report_and_prints_where(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["report", "contoso-dental", "--as-of", AS_OF, "--out", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["json"].endswith("contoso-dental.json") and out["markdown"].endswith("contoso-dental.md")
    assert len(out["sha256"]) == 64
    assert out["proposals"] == len(build_report("contoso-dental", as_of=AS_OF)["proposals"])


def test_b75_cli_refuses_bad_input_with_exit_2_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["report", "nobody-here", "--as-of", AS_OF, "--out", str(tmp_path)]) == 2
    assert main(["report", "contoso-dental", "--as-of", "yesterday", "--out", str(tmp_path)]) == 2
    assert main(["report", "contoso-dental", "--as-of", AS_OF, "--within-days", "-3", "--out", str(tmp_path)]) == 2
    assert "error:" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []
