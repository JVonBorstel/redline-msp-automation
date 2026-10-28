"""B-73 technology roadmap recommendations and the client AI-use policy draft. Acceptance ids B73-1 to B73-3 are in
specs/B-73.md (B73-1 roadmap items with findings and budget ranges, B73-2 the AI-use policy draft, B73-3 no
recommendation without a cited finding).

Offline and deterministic: ``generated_on`` is always passed in, drafts go to tmp_path, committed fixtures are only
read. Expected values are recomputed here from the raw fixture files with small code of their own.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/reporting/test_b73_vcio.py
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from core.paths import REPO_ROOT
from workflows.reporting.roadmap import (
    AIPolicyDraft,
    Evidence,
    FileRef,
    Recommendation,
    Roadmap,
    RoadmapError,
    VerifyError,
    build_ai_policy,
    build_roadmap,
    create_drafts,
    main,
    verify_draft,
    verify_roadmap,
)

PERIOD = "2026-10"
GENERATED = "2026-10-31"
CLIENTS = ("contoso-dental", "fabrikam-capital", "litware-legal")
NAMES = {"contoso-dental": "Contoso Dental", "fabrikam-capital": "Fabrikam Capital", "litware-legal": "Litware Legal"}
ROADMAP_DIR = REPO_ROOT / "workflows" / "reporting" / "roadmap"
PRICES = ROADMAP_DIR / "data" / "price_list.json"
LICENSING = REPO_ROOT / "fixtures" / "licensing"
TEMPLATE = REPO_ROOT / "governance" / "templates" / "client-ai-policy-starter.md"
AI_POLICY = REPO_ROOT / "governance" / "AI_POLICY.md"
REGISTER = REPO_ROOT / "governance" / "ai-vendor-register.json"
LEVELS = {"low", "medium", "high"}
CATEGORIES = {"hardware", "licence", "security", "backup", "devices"}


def _json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _roadmap(client: str = "contoso-dental", **kw: Any) -> Roadmap:
    return build_roadmap(client, PERIOD, generated_on=GENERATED, **kw)


def _by_id(road: Roadmap) -> dict[str, Recommendation]:
    return {r.id: r for r in road.recommendations}


def _years_on(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 February
        return day.replace(year=day.year + years, day=28)


# -- B73-1: recommendations with the finding each rests on and a budget range ------------------------
def test_b73_1_hardware_items_follow_the_lifecycle_dates_in_the_licensing_fixture() -> None:
    raw = _json(LICENSING / "contoso-dental.json")["hardware"]
    asof = date.fromisoformat(GENERATED)
    expected = set()
    for row in raw:
        end = _years_on(date.fromisoformat(row["purchased_on"]), row["lifecycle_years"])
        if (end - asof).days <= 90:
            expected.add(f"hw-{row['hostname'].lower()}")
    got = {r.id for r in _roadmap().recommendations if r.category == "hardware"}
    assert got == expected
    assert "hw-reception-old" in got and "hw-dental-srv01" in got
    assert "hw-frontdesk-01" not in got


def test_b73_1_hardware_budget_is_the_fixture_price_for_the_device_class() -> None:
    prices = _json(PRICES)["hardware"]
    items = _by_id(_roadmap())
    ws, srv = items["hw-reception-old"].budget, items["hw-dental-srv01"].budget
    assert (ws.low, ws.high) == (prices["workstation"]["low"], prices["workstation"]["high"])
    assert (srv.low, srv.high) == (prices["server"]["low"], prices["server"]["high"])
    assert ws.unit == "one-time" and "price list" in ws.basis


def test_b73_1_hardware_item_cites_the_licensing_fixture_with_its_hash() -> None:
    item = _by_id(_roadmap())["hw-reception-old"]
    cited = [(f.path, f.sha256) for e in item.evidence for f in e.files]
    assert ("fixtures/licensing/contoso-dental.json", _sha(LICENSING / "contoso-dental.json")) in cited
    assert any(e.field == "hardware[RECEPTION-OLD].lifecycle" and e.value == "past" for e in item.evidence)


def test_b73_1_licence_items_rest_on_the_seat_and_renewal_findings() -> None:
    items = _by_id(_roadmap())
    seat = items["lic-seats-o365_business_premium"]
    assert seat.category == "licence"
    assert any(e.field == "seats[O365_BUSINESS_PREMIUM].reducible" and e.value == 3 for e in seat.evidence)
    assert "66.00" in seat.budget.basis  # the fixture's own monthly saving for that SKU
    renew = items["lic-renew-r-cd-01"]
    assert any(e.field == "renewals[R-CD-01].ends_on" and e.value == "2026-11-15" for e in renew.evidence)
    prices = _json(LICENSING / "contoso-dental.json")["unit_prices_monthly"]["O365_BUSINESS_PREMIUM"]
    assert renew.budget.unit == "per year" and renew.budget.high == prices * 6 * 12


def test_b73_1_security_items_come_from_the_health_report_rules_that_fired() -> None:
    items = _by_id(_roadmap())
    for rule in ("baseline.high", "patching.critical", "awareness.clicks"):
        item = items["sec-" + rule.replace(".", "-")]
        assert item.category == "security"
        assert item.evidence[0].source == "health report (B-71)"
    high = items["sec-baseline-high"]
    assert any(e.field == "baseline.high" and e.value == 2 for e in high.evidence)
    assert all(
        f.path.startswith("workflows/reporting/health/data/contoso-dental.") for e in high.evidence for f in e.files
    )


def test_b73_1_backup_and_device_items_cite_their_reports() -> None:
    items = _by_id(_roadmap())
    cov = items["bak-coverage"]
    assert cov.category == "backup"
    assert any(e.field == "counts.objects_uncovered" and e.value == 4 for e in cov.evidence)
    assert "bak-policy-pol-c1" in items and "bak-policy-pol-c2" in items
    dev = items["dev-not-in-intune"]
    assert dev.category == "devices"
    assert any(e.field == "counts.compliance.not-in-intune" and e.value == 6 for e in dev.evidence)
    for item in (cov, dev):
        assert all(f.sha256 and f.path for e in item.evidence for f in e.files)


def test_b73_1_every_item_has_effort_and_risk_labels_and_a_valid_range() -> None:
    for client in CLIENTS:
        road = _roadmap(client)
        assert road.recommendations
        for r in road.recommendations:
            assert r.category in CATEGORIES
            assert r.effort in LEVELS and r.risk in LEVELS
            assert 0 <= r.budget.low <= r.budget.high
            assert r.title and r.action and r.rule


def test_b73_1_totals_add_up_the_one_time_ranges() -> None:
    road = _roadmap()
    ones = [r.budget for r in road.recommendations if r.budget.unit == "one-time"]
    assert road.totals["one_time_low"] == sum(b.low for b in ones)
    assert road.totals["one_time_high"] == sum(b.high for b in ones)
    assert road.totals["items"] == len(road.recommendations)


def test_b73_1_order_is_stable_and_two_builds_are_identical() -> None:
    a, b = _roadmap(), _roadmap()
    assert a == b
    order = ["hardware", "licence", "security", "backup", "devices"]
    cats = [order.index(r.category) for r in a.recommendations]
    assert cats == sorted(cats)


def test_b73_1_client_with_no_licensing_backup_or_device_data_gets_health_items_and_named_gaps() -> None:
    road = _roadmap("litware-legal")
    assert {r.category for r in road.recommendations} <= {"security"}
    assert {g.split(":")[0] for g in road.gaps} == {"licensing", "backup coverage", "device reports"}


def test_b73_1_a_missing_or_broken_price_list_refuses_the_run(tmp_path: Path) -> None:
    with pytest.raises(RoadmapError):
        _roadmap(price_list=tmp_path / "missing.json")
    bad = tmp_path / "p.json"
    prices = _json(PRICES)
    prices["hardware"]["server"]["high"] = 1  # below low
    bad.write_text(json.dumps(prices), "utf-8")
    with pytest.raises(RoadmapError):
        _roadmap(price_list=bad)


def test_b73_1_a_changed_price_changes_the_budget(tmp_path: Path) -> None:
    prices = _json(PRICES)
    prices["hardware"]["workstation"] = {"low": 111, "high": 222}
    alt = tmp_path / "p.json"
    alt.write_text(json.dumps(prices), "utf-8")
    item = _by_id(_roadmap(price_list=alt))["hw-reception-old"]
    assert (item.budget.low, item.budget.high) == (111, 222)


# -- B73-3: no recommendation without a cited finding ---------------------------------------------------
def _ev() -> Evidence:
    return Evidence("licensing report (B-75)", "hardware[X].lifecycle", "past", (FileRef("a.json", "0" * 64),))


def test_b73_3_a_recommendation_without_evidence_cannot_be_built() -> None:
    from workflows.reporting.roadmap import Budget

    args: dict[str, Any] = {
        "id": "x",
        "category": "hardware",
        "rule": "r",
        "title": "t",
        "action": "a",
        "effort": "low",
        "risk": "low",
        "budget": Budget(0, 0, "one-time", "b"),
    }
    with pytest.raises(RoadmapError):
        Recommendation(evidence=(), **args)
    with pytest.raises(RoadmapError):
        Recommendation(evidence=(Evidence("s", "f", 1, ()),), **args)  # a finding with no source file
    assert Recommendation(evidence=(_ev(),), **args).evidence


def test_b73_3_every_built_item_cites_findings_whose_files_exist_and_hash_correctly() -> None:
    for client in CLIENTS:
        for r in _roadmap(client).recommendations:
            assert r.evidence, r.id
            for e in r.evidence:
                assert e.files, (r.id, e.field)
                for f in e.files:
                    assert _sha(REPO_ROOT / f.path) == f.sha256


def test_b73_3_verify_roadmap_catches_a_dropped_or_altered_citation() -> None:
    road = _roadmap()
    verify_roadmap(road)
    first = road.recommendations[0]
    wrong = FileRef(first.evidence[0].files[0].path, "f" * 64)
    forged = _replace(
        first,
        evidence=(Evidence(first.evidence[0].source, first.evidence[0].field, first.evidence[0].value, (wrong,)),),
    )
    with pytest.raises(VerifyError):
        verify_roadmap(Roadmap(**{**road.__dict__, "recommendations": (forged,) + road.recommendations[1:]}))


def _replace(rec: Recommendation, **kw: Any) -> Recommendation:
    # bypass __post_init__ so the test can build the forbidden shape
    fields = {**{k: getattr(rec, k) for k in rec.__dataclass_fields__}, **kw}
    obj = object.__new__(Recommendation)
    for k, v in fields.items():
        object.__setattr__(obj, k, v)
    return obj


def test_b73_3_verify_roadmap_rejects_an_item_with_no_citation() -> None:
    road = _roadmap()
    bare = _replace(road.recommendations[0], evidence=())
    with pytest.raises(VerifyError):
        verify_roadmap(Roadmap(**{**road.__dict__, "recommendations": (bare,) + road.recommendations[1:]}))


# -- isolation -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("client", CLIENTS)
def test_b73_isolation_a_clients_roadmap_and_policy_name_no_other_client(client: str, tmp_path: Path) -> None:
    drafts = create_drafts(client, PERIOD, generated_on=GENERATED, out_dir=tmp_path)
    others = [c for c in CLIENTS if c != client]
    for path in (drafts.roadmap_md, drafts.roadmap_json, drafts.policy_md):
        text = path.read_text("utf-8").lower()
        for other in others:
            token = other.split("-")[0]  # fabrikam, litware, contoso
            assert token not in text, (path.name, token)
            assert NAMES[other].lower() not in text
    road = _roadmap(client)
    for r in road.recommendations:
        for e in r.evidence:
            for f in e.files:
                assert not any(o in f.path for o in others)


# -- drafts, labels, files ---------------------------------------------------------------------------------
def test_b73_drafts_are_labelled_draft_unreviewed_and_fixture_based(tmp_path: Path) -> None:
    drafts = create_drafts("contoso-dental", PERIOD, generated_on=GENERATED, out_dir=tmp_path)
    md = drafts.roadmap_md.read_text("utf-8")
    assert md.startswith("# DRAFT")
    assert "fixture-based" in md and "Not sent" in md and "A person reviews" in md
    data = json.loads(drafts.roadmap_json.read_text("utf-8"))
    assert data["status"] == "draft" and data["reviewed_by"] is None and data["reviewed_on"] is None
    assert data["client"] == "contoso-dental" and data["generated_on"] == GENERATED
    policy = drafts.policy_md.read_text("utf-8")
    assert policy.splitlines()[0].startswith("# DRAFT")
    assert drafts.sha256 == hashlib.sha256(drafts.roadmap_json.read_bytes()).hexdigest()


def test_b73_draft_files_are_reproducible_byte_for_byte(tmp_path: Path) -> None:
    a = create_drafts("contoso-dental", PERIOD, generated_on=GENERATED, out_dir=tmp_path / "a")
    b = create_drafts("contoso-dental", PERIOD, generated_on=GENERATED, out_dir=tmp_path / "b")
    for x, y in ((a.roadmap_md, b.roadmap_md), (a.roadmap_json, b.roadmap_json), (a.policy_md, b.policy_md)):
        assert x.read_bytes() == y.read_bytes()


def test_b73_verify_draft_matches_and_catches_an_edit(tmp_path: Path) -> None:
    drafts = create_drafts("contoso-dental", PERIOD, generated_on=GENERATED, out_dir=tmp_path)
    verify_draft(drafts.roadmap_json)
    data = json.loads(drafts.roadmap_json.read_text("utf-8"))
    data["recommendations"][0]["effort"] = "low" if data["recommendations"][0]["effort"] != "low" else "high"
    drafts.roadmap_json.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", "utf-8")
    with pytest.raises(VerifyError):
        verify_draft(drafts.roadmap_json)


def test_b73_nothing_is_written_when_the_run_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RoadmapError):
        create_drafts("no-such-client", PERIOD, generated_on=GENERATED, out_dir=tmp_path)
    with pytest.raises(RoadmapError):
        create_drafts("../contoso-dental", PERIOD, generated_on=GENERATED, out_dir=tmp_path)
    with pytest.raises(RoadmapError):
        create_drafts("contoso-dental", "2026-13", generated_on=GENERATED, out_dir=tmp_path)
    with pytest.raises(RoadmapError):
        create_drafts("contoso-dental", PERIOD, generated_on="31/10/2026", out_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_b73_cli_builds_verifies_and_refuses(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["build", "contoso-dental", "--period", PERIOD, "--generated-on", GENERATED, "--out-dir", str(tmp_path)])
    assert rc == 0
    produced = tmp_path / PERIOD / "contoso-dental.roadmap.draft.json"
    assert produced.exists()
    assert main(["verify", str(produced)]) == 0
    assert main(["build", "nope!", "--period", PERIOD, "--generated-on", GENERATED, "--out-dir", str(tmp_path)]) == 2
    out = capsys.readouterr().out + capsys.readouterr().err
    assert "Traceback" not in out


# -- B73-2: the AI-use policy draft -------------------------------------------------------------------------
def _policy(client: str = "contoso-dental", **kw: Any) -> AIPolicyDraft:
    return build_ai_policy(client, generated_on=GENERATED, **kw)


def test_b73_2_policy_is_a_labelled_draft_that_needs_human_review() -> None:
    p = _policy()
    first = p.text.splitlines()[0]
    assert first.startswith("# DRAFT")
    assert "starter, review with your counsel" in p.text
    assert "human review" in p.text.lower()
    assert "Reviewed by:" in p.text and "not in force" in p.text.lower()
    assert p.status == "draft" and p.reviewed_by is None


def test_b73_2_dental_and_financial_clients_get_their_industry_defaults() -> None:
    dental, fin = _policy("contoso-dental"), _policy("fabrikam-capital")
    assert (dental.industry, dental.floor) == ("dental", "DC-4")
    assert (fin.industry, fin.floor) == ("financial", "DC-5")
    assert "DC-4" in dental.text and "patient" in dental.text.lower()
    assert "DC-5" in fin.text
    assert dental.text != fin.text
    assert "Contoso Dental" in dental.text and "Fabrikam Capital" in fin.text


def test_b73_2_floor_matches_the_guard_module_for_every_industry() -> None:
    from core.guard.classify import INDUSTRY_FLOOR

    for client in CLIENTS:
        p = _policy(client)
        assert p.floor == f"DC-{INDUSTRY_FLOOR[p.industry].value}"


def test_b73_2_permitted_data_classes_follow_the_dlp_mapping() -> None:
    p = _policy("contoso-dental")
    rows = {r.data_class: r for r in p.data_classes}
    assert set(rows) == {f"DC-{i}" for i in range(7)}
    assert rows["DC-6"].local == "never" and rows["DC-6"].hosted == "never"
    assert rows["DC-0"].local.startswith("yes") and rows["DC-0"].hosted.startswith("yes")
    assert rows["DC-4"].hosted == "no"  # PHI never to a hosted tool from this starter
    assert rows["DC-4"].local.startswith("minimum necessary")
    assert rows["DC-2"].hosted == "no"  # nothing approved: only DC-0 outside
    fin = {r.data_class: r for r in _policy("fabrikam-capital").data_classes}
    assert fin["DC-5"].local.startswith("minimum necessary") and fin["DC-5"].hosted == "no"


def test_b73_2_default_register_means_no_hosted_model_is_approved() -> None:
    p = _policy()
    assert p.hosted.status == "not approved"
    assert p.hosted.provider is None and p.hosted.allowed_classes == ()
    assert "No hosted AI model is approved" in p.text
    assert any("local" in t.name.lower() for t in p.approved_tools)
    assert all(t.kind != "hosted" for t in p.approved_tools)


def _register(tmp_path: Path, **over: Any) -> Path:
    entry: dict[str, Any] = {
        "id": "azure-openai-contoso",
        "provider": "azure_openai",
        "name": "Azure OpenAI",
        "status": "approved",
        "allowed_data_classes": ["DC-0", "DC-1", "DC-2"],
        "clients": ["contoso-dental"],
        "purposes": ["drafting"],
        "retention_terms": "30 days, no training (synthetic test terms)",
        "review_date": "2027-03-31",
        "approved_by": "ai change approver",
        "approved_on": "2026-09-01",
        "approval_ref": "DEC-TEST-1",
    }
    entry.update(over)
    path = tmp_path / "register.json"
    path.write_text(json.dumps({"version": 1, "vendors": [entry]}), "utf-8")
    return path


def test_b73_2_an_approved_entry_for_this_client_is_shown_with_its_terms(tmp_path: Path) -> None:
    p = _policy(register=_register(tmp_path))
    assert p.hosted.status == "approved"
    assert p.hosted.provider == "Azure OpenAI"
    assert p.hosted.allowed_classes == ("DC-0", "DC-1", "DC-2")
    assert p.hosted.review_date == "2027-03-31"
    rows = {r.data_class: r for r in p.data_classes}
    assert rows["DC-2"].hosted.startswith("yes") and rows["DC-3"].hosted == "no"
    assert any(t.kind == "hosted" and t.name == "Azure OpenAI" for t in p.approved_tools)
    assert "30 days" in p.text and "2027-03-31" in p.text


def test_b73_2_hosted_never_gets_phi_or_npi_even_if_the_register_lists_them(tmp_path: Path) -> None:
    reg = _register(tmp_path, allowed_data_classes=["DC-0", "DC-4", "DC-5"])
    p = _policy(register=reg)
    rows = {r.data_class: r for r in p.data_classes}
    assert rows["DC-4"].hosted == "no" and rows["DC-5"].hosted == "no"
    assert p.hosted.allowed_classes == ("DC-0",)


def test_b73_2_an_entry_for_another_client_or_an_expired_one_approves_nothing(tmp_path: Path) -> None:
    other = _policy(register=_register(tmp_path, clients=["fabrikam-capital"]))
    assert other.hosted.status == "not approved"
    assert "fabrikam" not in other.text.lower()
    expired = _policy(register=_register(tmp_path, review_date="2026-10-01", approved_on="2026-01-01"))
    assert expired.hosted.status == "expired"
    assert all(t.kind != "hosted" for t in expired.approved_tools)
    assert expired.hosted.allowed_classes == ()


def test_b73_2_a_pending_entry_allows_nothing() -> None:
    reg = _json(REGISTER)
    assert all(v["status"] == "pending" for v in reg["vendors"])  # the committed register approves no one
    assert _policy("fabrikam-capital").hosted.status == "not approved"


def test_b73_2_rules_are_taken_from_the_msp_ai_policy(tmp_path: Path) -> None:
    src = AI_POLICY.read_text("utf-8")
    titles = re.findall(r"^\d+\. \*\*(.+?)\*\*", src.split("## 2. Five rules")[1].split("## 3.")[0], flags=re.M)
    assert len(titles) == 5
    p = _policy()
    for title in titles:
        assert title in p.text
    changed = tmp_path / "AI_POLICY.md"
    changed.write_text(src.replace("AI proposes, people decide.", "People decide, always."), "utf-8")
    p2 = _policy(ai_policy=changed)
    assert "People decide, always." in p2.text and "AI proposes, people decide." not in p2.text
    assert p2.policy_sha256 == hashlib.sha256(changed.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_b73_2_a_policy_without_the_five_rules_refuses(tmp_path: Path) -> None:
    broken = tmp_path / "AI_POLICY.md"
    broken.write_text("# AI policy\n\n## 2. Five rules\n\n1. **Only one.** x.\n\n## 3. Data classes\n", "utf-8")
    with pytest.raises(RoadmapError):
        _policy(ai_policy=broken)


def test_b73_2_template_placeholders_are_all_filled_and_a_stray_one_refuses(tmp_path: Path) -> None:
    for client in CLIENTS:
        assert "{{" not in _policy(client).text
    tpl = tmp_path / "t.md"
    tpl.write_text(TEMPLATE.read_text("utf-8") + "\n{{NOT_A_FIELD}}\n", "utf-8")
    with pytest.raises(RoadmapError):
        _policy(template=tpl)


def test_b73_2_policy_makes_no_legal_or_certification_claim() -> None:
    banned = re.compile(
        r"\b(certif\w*|guarantee\w*|legal advice|compliant|compliance with|ensures? compliance|hipaa[- ]compliant)\b",
        re.I,
    )
    for client in CLIENTS:
        text = _policy(client).text
        stripped = text.replace("not legal advice", "").replace("Not legal advice", "")
        assert not banned.search(stripped), banned.search(stripped)
        assert "not legal advice" in text.lower()
        assert "synthetic" in text.lower()


def test_b73_2_unknown_industry_or_client_refuses(tmp_path: Path) -> None:
    with pytest.raises(RoadmapError):
        _policy("no-such-client")
    bad = tmp_path / "clients.json"
    bad.write_text(json.dumps({"clients": {"contoso-dental": {"industry": "space-mining"}}}), "utf-8")
    with pytest.raises(RoadmapError):
        _policy(clients=bad)


def test_b73_2_two_builds_are_identical_and_carry_the_source_hashes() -> None:
    a, b = _policy(), _policy()
    assert a == b
    assert a.template_sha256 == _sha(TEMPLATE) and a.policy_sha256 == _sha(AI_POLICY)


def test_b73_2_the_template_is_the_committed_starter_and_labelled() -> None:
    text = TEMPLATE.read_text("utf-8")
    assert "starter, review with your counsel" in text
    assert "DRAFT" in text.splitlines()[0]
    for field in ("CLIENT_NAME", "INDUSTRY", "FLOOR", "RULES", "DATA_CLASS_TABLE", "APPROVED_TOOLS", "HOSTED_STATUS"):
        assert "{{" + field + "}}" in text
