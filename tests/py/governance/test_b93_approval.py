"""B-93 model and tool approval process: the record schema, the checker, the process page and the template.

Acceptance ids B93-1 to B93-3 are defined in specs/B-93.md. The checker reads governance/model_tool_approvals.json,
config/models.json, the lever registry, adapters/, mcp/server.py and governance/ai-vendor-register.json as committed.
Cases that need a bad world are built by editing a copy of the parsed data (nothing on disk is changed).
Run: uv run --frozen pytest -p no:cacheprovider tests/py/governance -o addopts=
"""

from __future__ import annotations

import copy
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from core.gateway.vendor_register import VendorRegister
from workflows.assurance import approvals
from workflows.assurance.approvals import ApprovalFile, ApprovalRecord, Problem, World

ROOT = Path(__file__).resolve().parents[3]
PROCESS = ROOT / "governance" / "MODEL_TOOL_APPROVAL.md"
TEMPLATE = ROOT / "governance" / "templates" / "ai-change-request.md"
RECORDS = ROOT / "governance" / "model_tool_approvals.json"
SCHEMA = ROOT / "governance" / "model_tool_approval.schema.json"
LABELLED = (PROCESS, TEMPLATE, ROOT / "specs" / "B-93.md", ROOT / "docs" / "changes" / "B-93.md")
TODAY = date(2026, 11, 1)
KINDS = ("model", "provider", "mcp-server", "lever-namespace", "adapter")
LLAMA = "ollama/llama3.2:3b"
APPROVERS = ("ai-change-approver", "security-lead", "compliance-owner")


def raw_records() -> dict[str, Any]:
    return json.loads(RECORDS.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def check(raw: dict[str, Any] | None = None, world: World | None = None, today: date = TODAY) -> list[Problem]:
    """Run the checker on (a possibly edited copy of) the committed records against the (possibly edited) world."""
    parsed = ApprovalFile.model_validate(copy.deepcopy(raw if raw is not None else raw_records()))
    return approvals.check(parsed, world or approvals.load_world(ROOT), ROOT, today)


def codes(problems: list[Problem]) -> set[str]:
    return {p.code for p in problems}


def record(raw: dict[str, Any], kind: str, subject: str | None = None) -> dict[str, Any]:
    for item in raw["records"]:
        if item["kind"] == kind and (subject is None or item["subject"] == subject):
            return item  # type: ignore[no-any-return]
    raise AssertionError(f"no {kind} record {subject}")


def world_with(**changes: Any) -> World:
    return approvals.load_world(ROOT).replace(**changes)


def register(*entries: Any) -> VendorRegister:
    return VendorRegister(version=1, vendors=tuple(entries))


# ---------- B93-1: the committed records cover everything and the checker is clean ----------


def test_b93_1_the_committed_records_pass_the_checker() -> None:
    assert check() == []


def test_b93_1_the_committed_records_cover_every_kind() -> None:
    assert {r["kind"] for r in raw_records()["records"]} == set(KINDS)


def test_b93_1_every_model_in_config_has_a_record() -> None:
    config = json.loads((ROOT / "config" / "models.json").read_text(encoding="utf-8"))
    wanted = {f"{p}/{m}" for p, cfg in config["providers"].items() for m in cfg["models"].values()}
    assert wanted, "the config names models"
    have = {r["subject"] for r in raw_records()["records"] if r["kind"] == "model"}
    assert wanted <= have


@pytest.mark.parametrize("kind", KINDS)
def test_b93_1_removing_a_record_fails_the_check_naming_the_subject(kind: str) -> None:
    raw = raw_records()
    victim = record(raw, kind)
    raw["records"] = [r for r in raw["records"] if r is not victim]
    hits = [p for p in check(raw) if p.code == "missing-record"]
    assert hits and any(victim["subject"] in p.detail for p in hits)


def test_b93_1_a_new_model_in_config_without_a_record_fails() -> None:
    config = copy.deepcopy(approvals.load_world(ROOT).config)
    config["providers"]["ollama"]["models"]["tiny"] = "newmodel:1b"
    problems = check(world=world_with(config=config))
    assert [p.detail for p in problems if p.code == "missing-record"] == [
        "model ollama/newmodel:1b is in config/models.json but has no approved, in-date record"
    ]


def test_b93_1_a_hosted_provider_enabled_in_config_without_a_record_fails() -> None:
    config = copy.deepcopy(approvals.load_world(ROOT).config)
    config["providers"]["azure_openai"] = {"enabled": True, "models": {"strong": "gpt-example"}}
    found = {(p.code, p.detail.split(" ")[1]) for p in check(world=world_with(config=config))}
    assert ("missing-record", "azure_openai/gpt-example") in found
    assert ("missing-record", "azure_openai") in found


def test_b93_1_a_disabled_provider_needs_no_provider_record() -> None:
    raw = raw_records()
    subjects = {r["subject"] for r in raw["records"] if r["kind"] == "provider"}
    assert "ollama" in subjects and "azure_openai" not in subjects
    assert check(raw) == []


def test_b93_1_a_new_lever_in_a_new_namespace_without_a_record_fails() -> None:
    world = approvals.load_world(ROOT)
    problems = check(world=world.replace(lever_names=(*world.lever_names, "vpn.disconnect-session")))
    assert any(p.code == "missing-record" and "vpn" in p.detail for p in problems)


def test_b93_1_a_new_lever_in_an_approved_namespace_is_covered_by_the_namespace_record() -> None:
    world = approvals.load_world(ROOT)
    assert check(world=world.replace(lever_names=(*world.lever_names, "ticket.close-note"))) == []


def test_b93_1_a_new_adapter_folder_without_a_record_fails() -> None:
    world = approvals.load_world(ROOT)
    problems = check(world=world.replace(adapters=(*world.adapters, "dns")))
    assert any(p.code == "missing-record" and "adapter dns" in p.detail for p in problems)


def test_b93_1_a_new_mcp_server_without_a_record_fails() -> None:
    world = approvals.load_world(ROOT)
    problems = check(world=world.replace(mcp_servers=(*world.mcp_servers, "other-server")))
    assert any(p.code == "missing-record" and "other-server" in p.detail for p in problems)


def test_b93_1_the_world_loader_reads_the_repo() -> None:
    world = approvals.load_world(ROOT)
    assert "ticket.get" in world.lever_names and "psa" in world.adapters
    assert world.mcp_servers == ("redline-levers",)
    assert ("model", "mock/mock-small") in approvals.required(world)
    assert ("lever-namespace", "ticket") in approvals.required(world)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"status": "draft", "approved_on": None, "review_date": None, "reviewers": []}, "not-approved"),
        ({"status": "revoked"}, "not-approved"),
        ({"status": "rejected"}, "not-approved"),
        ({"review_date": "2026-10-31", "approved_on": "2026-10-27"}, "expired"),
        ({"approved_on": "2026-11-02", "review_date": "2027-05-01"}, "not-yet-in-effect"),
    ],
)
def test_b93_1_a_record_that_is_not_approved_and_in_date_does_not_cover(change: dict[str, Any], code: str) -> None:
    raw = raw_records()
    record(raw, "model", LLAMA).update(change)
    problems = check(raw)
    assert code in codes(problems)
    assert any(p.code == "missing-record" and LLAMA in p.detail for p in problems)


def test_b93_1_the_review_date_day_itself_is_still_in_date() -> None:
    raw = raw_records()
    record(raw, "model", LLAMA)["review_date"] = "2026-11-01"
    assert check(raw) == []
    assert "expired" in codes(check(raw, today=date(2026, 11, 2)))


def test_b93_1_two_records_for_one_subject_are_refused() -> None:
    raw = raw_records()
    twin = copy.deepcopy(record(raw, "model", LLAMA))
    twin["id"] = "AC-099"
    raw["records"].append(twin)
    assert "duplicate-subject" in codes(check(raw))


def test_b93_1_duplicate_ids_are_refused() -> None:
    raw = raw_records()
    raw["records"][1]["id"] = raw["records"][0]["id"]
    with pytest.raises(ValidationError):
        ApprovalFile.model_validate(raw)


# ---------- B93-1: evidence ----------


def test_b93_1_evidence_file_that_does_not_exist_fails() -> None:
    raw = raw_records()
    for ev in record(raw, "model", LLAMA)["evidence"]:
        if ev["type"] == "eval_report":
            ev["ref"] = "evals/routing/no-such-report.md"
    assert "evidence-missing" in codes(check(raw))


def test_b93_1_evidence_test_name_that_the_file_does_not_define_fails() -> None:
    raw = raw_records()
    for ev in record(raw, "adapter", "psa")["evidence"]:
        if ev["type"] == "contract_test":
            ev["ref"] = "tests/py/contract/test_b91_adapters.py::test_b91_9_does_not_exist"
    problems = check(raw)
    assert any(p.code == "evidence-missing" and "test_b91_9_does_not_exist" in p.detail for p in problems)


@pytest.mark.parametrize(
    "ref", ["../outside.md", "C:/Windows/win.ini", "/etc/passwd", "tests/../../x.py", "tests\\x.py"]
)
def test_b93_1_evidence_path_that_leaves_the_repo_is_refused(ref: str) -> None:
    raw = raw_records()
    for ev in record(raw, "adapter", "psa")["evidence"]:
        if ev["type"] == "contract_test":
            ev["ref"] = ref
    assert "evidence-bad-ref" in codes(check(raw))


@pytest.mark.parametrize(
    ("kind", "subject", "dropped"),
    [
        ("model", LLAMA, "eval_report"),
        ("model", LLAMA, "redaction_test"),
        ("adapter", "psa", "contract_test"),
        ("adapter", "psa", "redaction_test"),
        ("lever-namespace", "ticket", "contract_test"),
        ("mcp-server", "redline-levers", "redaction_test"),
    ],
)
def test_b93_1_each_kind_needs_its_evidence_types(kind: str, subject: str, dropped: str) -> None:
    raw = raw_records()
    item = record(raw, kind, subject)
    item["evidence"] = [e for e in item["evidence"] if e["type"] != dropped]
    assert any(p.code == "evidence-required" and dropped in p.detail for p in check(raw))


def test_b93_1_a_test_reference_must_point_into_tests_and_a_report_into_evals() -> None:
    raw = raw_records()
    for ev in record(raw, "model", LLAMA)["evidence"]:
        ev["ref"] = "governance/AI_POLICY.md"
    problems = [p for p in check(raw) if p.code == "evidence-bad-ref"]
    assert len(problems) == len(record(raw, "model", LLAMA)["evidence"])


def test_b93_1_a_draft_record_is_not_checked_for_evidence_but_does_not_cover() -> None:
    raw = raw_records()
    record(raw, "model", LLAMA).update(
        {"status": "draft", "approved_on": None, "review_date": None, "reviewers": [], "evidence": []}
    )
    assert codes(check(raw)) == {"missing-record", "not-approved"}


# ---------- B93-1: who proposes, who approves ----------


def test_b93_1_an_approved_record_needs_the_ai_change_approver() -> None:
    raw = raw_records()
    record(raw, "model", LLAMA)["reviewers"] = [
        {"role": "technical-reviewer", "decision": "approve", "on": "2026-10-27"}
    ]
    assert "approver-missing" in codes(check(raw))


def test_b93_1_the_proposer_role_cannot_approve_its_own_request() -> None:
    raw = raw_records()
    item = record(raw, "model", LLAMA)
    item["proposed_by_role"] = "lead"
    item["reviewers"] = [{"role": "ai-change-approver", "decision": "approve", "on": "2026-10-27"}]
    assert check(raw) == []
    item["proposed_by_role"] = "ai-change-approver"
    assert "self-approval" in codes(check(raw))


def test_b93_1_a_rejecting_reviewer_blocks_approval() -> None:
    raw = raw_records()
    record(raw, "model", LLAMA)["reviewers"].append({"role": "security-lead", "decision": "reject", "on": "2026-10-27"})
    assert "reviewer-rejected" in codes(check(raw))


def test_b93_1_a_review_dated_after_the_approval_is_refused() -> None:
    raw = raw_records()
    record(raw, "model", LLAMA)["reviewers"][0]["on"] = "2026-10-28"
    assert "review-after-approval" in codes(check(raw))


def test_b93_1_risk_r2_and_r3_need_security_lead_and_compliance_owner() -> None:
    raw = raw_records()
    risky = [r for r in raw["records"] if r["risk_class"] in ("R2", "R3")]
    assert risky, "the committed records include R2 or R3 subjects"
    for item in risky:
        roles = {r["role"] for r in item["reviewers"] if r["decision"] == "approve"}
        assert set(APPROVERS) <= roles, item["id"]
    risky[0]["reviewers"] = [r for r in risky[0]["reviewers"] if r["role"] != "security-lead"]
    assert "approver-missing" in codes(check(raw))


def test_b93_1_dc4_or_dc5_needs_the_extra_approvers_too() -> None:
    raw = raw_records()
    item = record(raw, "model", LLAMA)
    assert [r["role"] for r in item["reviewers"]] == ["ai-change-approver"]
    item["data_classes"] = ["DC-0", "DC-4"]
    assert "approver-missing" in codes(check(raw))


# ---------- B93-1: retention terms, BAA or ZDR for anything hosted ----------


def hosted_world() -> tuple[dict[str, Any], World]:
    """A world with Azure OpenAI enabled, an approved vendor entry and complete approved provider and model records."""
    world = approvals.load_world(ROOT)
    config = copy.deepcopy(world.config)
    config["providers"]["azure_openai"] = {"enabled": True, "models": {"strong": "gpt-example"}}
    vendors = VendorRegister.model_validate(
        {
            "version": 1,
            "vendors": [
                {
                    "id": "azure-openai-contoso",
                    "provider": "azure_openai",
                    "name": "Azure OpenAI",
                    "status": "approved",
                    "allowed_data_classes": ["DC-0", "DC-1"],
                    "clients": ["contoso-dental"],
                    "purposes": ["summarise"],
                    "retention_terms": "synthetic: no retention beyond the request",
                    "review_date": "2027-04-27",
                    "approved_by": "ai-change-approver",
                    "approved_on": "2026-10-27",
                    "approval_ref": "AC-901",
                }
            ],
        }
    )
    raw = raw_records()
    for base, kind, subject, rid in (
        (record(raw, "provider", "ollama"), "provider", "azure_openai", "AC-901"),
        (record(raw, "model", LLAMA), "model", "azure_openai/gpt-example", "AC-902"),
    ):
        item = copy.deepcopy(base)
        item.update(
            id=rid,
            kind=kind,
            subject=subject,
            hosting="hosted",
            data_classes=["DC-0", "DC-1"],
            retention_terms="synthetic: no retention beyond the request",
            baa_status="not-applicable",
            zdr_status="confirmed",
            vendor_approval_id="azure-openai-contoso",
            risk_class="R1",
            reviewers=[{"role": r, "decision": "approve", "on": "2026-10-27"} for r in APPROVERS],
        )
        raw["records"].append(item)
    return raw, world.replace(config=config, vendors=vendors)


def test_b93_1_a_complete_hosted_request_passes() -> None:
    raw, world = hosted_world()
    assert check(raw, world) == []


@pytest.mark.parametrize("missing", ["retention_terms", "vendor_approval_id"])
def test_b93_1_a_hosted_record_without_retention_terms_or_vendor_id_cannot_be_loaded(missing: str) -> None:
    raw, _ = hosted_world()
    record(raw, "provider", "azure_openai")[missing] = None
    with pytest.raises(ValidationError):
        ApprovalFile.model_validate(raw)


def test_b93_1_hosting_must_match_the_provider() -> None:
    raw, world = hosted_world()
    record(raw, "provider", "azure_openai").update(hosting="local", vendor_approval_id=None)
    assert "hosting-mismatch" in codes(check(raw, world))
    raw2 = raw_records()
    record(raw2, "provider", "ollama").update(
        hosting="hosted", retention_terms="x", vendor_approval_id="azure-openai-contoso"
    )
    assert "hosting-mismatch" in codes(check(raw2))


def set_classes(raw: dict[str, Any], classes: list[str], **fields: Any) -> None:
    for kind, subject in (("provider", "azure_openai"), ("model", "azure_openai/gpt-example")):
        record(raw, kind, subject).update(data_classes=classes, **fields)


def test_b93_1_dc4_on_a_hosted_route_needs_a_signed_baa() -> None:
    raw, world = hosted_world()
    set_classes(raw, ["DC-0", "DC-4"])
    vendor = world.vendors.vendors[0].model_copy(update={"allowed_data_classes": ("DC-0", "DC-4")})
    world = world.replace(vendors=register(vendor))
    assert "baa-required" in codes(check(raw, world))
    set_classes(raw, ["DC-0", "DC-4"], baa_status="signed")
    assert "baa-required" not in codes(check(raw, world))


def test_b93_1_dc5_on_a_hosted_route_needs_a_signed_baa_or_confirmed_zdr() -> None:
    raw, world = hosted_world()
    set_classes(raw, ["DC-0", "DC-5"], zdr_status="none", baa_status="none")
    vendor = world.vendors.vendors[0].model_copy(update={"allowed_data_classes": ("DC-0", "DC-5")})
    world = world.replace(vendors=register(vendor))
    assert "baa-required" in codes(check(raw, world))
    set_classes(raw, ["DC-0", "DC-5"], zdr_status="confirmed", baa_status="none")
    assert "baa-required" not in codes(check(raw, world))


def test_b93_1_dc6_is_never_allowed_in_a_record() -> None:
    raw = raw_records()
    record(raw, "model", LLAMA)["data_classes"] = ["DC-1", "DC-6"]
    with pytest.raises(ValidationError):
        ApprovalFile.model_validate(raw)


def test_b93_1_a_hosted_record_needs_an_eval_report_and_a_redaction_test() -> None:
    raw, world = hosted_world()
    item = record(raw, "model", "azure_openai/gpt-example")
    item["evidence"] = [e for e in item["evidence"] if e["type"] != "eval_report"]
    assert "evidence-required" in codes(check(raw, world))


# ---------- B93-1: record shape ----------


@pytest.mark.parametrize(
    "change",
    [
        {"owner_role": "Jane Doe"},
        {"purpose": ""},
        {"rollback": ""},
        {"inventory_ids": []},
        {"inventory_ids": ["not-an-id"]},
        {"risk_class": "R9"},
        {"data_classes": []},
        {"kind": "plugin"},
        {"surprise": 1},
        {"proposed_by_role": "someone"},
        {"id": "AC-1"},
    ],
)
def test_b93_1_a_record_with_a_bad_field_cannot_be_loaded(change: dict[str, Any]) -> None:
    raw = raw_records()
    record(raw, "model", LLAMA).update(change)
    with pytest.raises(ValidationError):
        ApprovalFile.model_validate(raw)


@pytest.mark.parametrize("change", [{"data_basis": "real"}, {"extra": 1}, {"version": 2}])
def test_b93_1_data_basis_must_be_synthetic_and_unknown_top_level_keys_are_refused(change: dict[str, Any]) -> None:
    raw = raw_records()
    raw.update(change)
    with pytest.raises(ValidationError):
        ApprovalFile.model_validate(raw)


def test_b93_1_the_committed_records_hold_no_secret_endpoint_or_address() -> None:
    text = RECORDS.read_text(encoding="utf-8").lower()
    for forbidden in ("http://", "https://", "api_key", "apikey", "bearer", "sk-", "@"):
        assert forbidden not in text


def test_b93_1_the_json_schema_file_matches_the_model() -> None:
    assert json.loads(SCHEMA.read_text(encoding="utf-8")) == ApprovalFile.model_json_schema()


# ---------- B93-3: the vendor register is reached only through an approved record ----------


def approved_vendor(ref: str | None) -> World:
    entry = {
        "id": "azure-openai-contoso",
        "provider": "azure_openai",
        "name": "Azure OpenAI",
        "status": "approved",
        "allowed_data_classes": ["DC-0"],
        "clients": ["contoso-dental"],
        "purposes": ["summarise"],
        "retention_terms": "synthetic terms",
        "review_date": "2027-04-27",
        "approved_by": "ai-change-approver",
        "approved_on": "2026-10-27",
        "approval_ref": ref,
    }
    return world_with(vendors=VendorRegister.model_validate({"version": 1, "vendors": [entry]}))


def test_b93_3_the_committed_register_has_only_pending_entries_so_nothing_needs_a_record() -> None:
    assert all(v.status == "pending" for v in VendorRegister.load().vendors)
    assert check() == []


def test_b93_3_an_approved_vendor_entry_with_no_approval_record_fails() -> None:
    assert "vendor-unrecorded" in codes(check(world=approved_vendor("AC-777")))


def test_b93_3_an_approved_vendor_entry_citing_the_wrong_kind_of_record_fails() -> None:
    raw = raw_records()
    assert "vendor-unrecorded" in codes(check(raw, approved_vendor(record(raw, "model", LLAMA)["id"])))


def test_b93_3_an_approved_vendor_entry_backed_by_a_provider_record_passes() -> None:
    raw, world = hosted_world()
    assert check(raw, world) == []


def test_b93_3_the_record_must_name_the_vendor_entry_it_authorises() -> None:
    raw, world = hosted_world()
    record(raw, "provider", "azure_openai")["vendor_approval_id"] = "someone-else"
    assert {"vendor-unrecorded", "vendor-unknown"} <= codes(check(raw, world))


def test_b93_3_the_vendor_entry_may_not_allow_more_classes_than_the_record() -> None:
    raw, world = hosted_world()
    vendor = world.vendors.vendors[0].model_copy(update={"allowed_data_classes": ("DC-0", "DC-1", "DC-2")})
    assert "vendor-classes-exceed" in codes(check(raw, world.replace(vendors=register(vendor))))


def test_b93_3_a_hosted_record_over_a_pending_or_overdue_vendor_entry_fails() -> None:
    raw, world = hosted_world()
    pending = world.vendors.vendors[0].model_copy(
        update={"status": "pending", "allowed_data_classes": (), "clients": (), "purposes": ()}
    )
    assert "vendor-not-approved" in codes(check(raw, world.replace(vendors=register(pending))))
    assert "vendor-overdue" in codes(check(raw, world, today=date(2027, 4, 28)))


def test_b93_3_the_vendor_provider_must_match_the_record_provider() -> None:
    raw, world = hosted_world()
    vendor = world.vendors.vendors[0].model_copy(update={"provider": "anthropic"})
    assert "vendor-wrong-provider" in codes(check(raw, world.replace(vendors=register(vendor))))


# ---------- command line ----------


def test_b93_cli_check_exits_0_on_the_repo_and_1_when_records_have_expired(capsys: pytest.CaptureFixture[str]) -> None:
    assert approvals.main(["check", "--as-of", "2026-11-01"]) == 0
    assert "approval checks: ok" in capsys.readouterr().out
    assert approvals.main(["check", "--as-of", "2030-01-01"]) == 1
    assert "expired" in capsys.readouterr().out


def test_b93_cli_rejects_a_bad_date() -> None:
    assert approvals.main(["check", "--as-of", "yesterday"]) == 2


def test_b93_cli_schema_is_a_dry_run_unless_write(capsys: pytest.CaptureFixture[str]) -> None:
    assert approvals.main(["schema"]) == 0
    assert "in sync" in capsys.readouterr().out


# ---------- the pages ----------


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def blocks(text: str) -> list[str]:
    return re.findall(r"```json\n(.*?)```", text, flags=re.S)


@pytest.mark.parametrize("page", LABELLED, ids=lambda p: p.name)
def test_b93_pages_carry_the_honest_labels_and_no_certification_claim(page: Path) -> None:
    text = read(page)
    assert "Independently built prototype. Not affiliated with any vendor's or real company's systems." in text
    assert "Synthetic data only." in text
    assert not re.search(r"(?i)\bcertified\b|\bis compliant\b|\bguarantees?\b|\battests?\b", text), page


def test_b93_1_the_process_names_who_proposes_who_approves_and_what_evidence() -> None:
    text = read(PROCESS)
    for role in ("technician", "automation-engineer", "lead", *APPROVERS, "technical-reviewer"):
        assert f"`{role}`" in text, role
    for needed in ("retention", "BAA", "ZDR", "eval report", "contract test", "redaction test", "rollback"):
        assert needed.lower() in text.lower(), needed
    for kind in KINDS:
        assert f"`{kind}`" in text, kind
    assert "Not a certification" in text and "Not legal advice" in text


def test_b93_1_the_process_lists_every_check_code_the_checker_can_emit() -> None:
    text = read(PROCESS)
    for code in approvals.CODES:
        assert f"`{code}`" in text, code


def test_b93_1_every_code_in_the_list_is_used_by_the_checker() -> None:
    source = read(ROOT / "workflows" / "assurance" / "approvals.py")
    for code in approvals.CODES:
        assert source.count(f'"{code}"') >= 2, code


def test_b93_1_the_process_states_the_commands_and_files() -> None:
    text = read(PROCESS)
    assert "python -m workflows.assurance.approvals check" in text
    assert "governance/model_tool_approvals.json" in text and "governance/templates/ai-change-request.md" in text


def test_b93_3_the_process_says_it_is_the_only_way_into_the_vendor_register() -> None:
    text = read(PROCESS)
    assert "governance/ai-vendor-register.json" in text
    assert "only way" in text
    assert "approval_ref" in text


def test_b93_3_the_vendor_register_note_points_at_this_process() -> None:
    note = json.loads(read(ROOT / "governance" / "ai-vendor-register.json"))["_note"]
    assert "governance/MODEL_TOOL_APPROVAL.md" in note


def test_b93_2_the_template_carries_inventory_id_risk_class_data_classes_and_rollback() -> None:
    text = read(TEMPLATE)
    for label in ("Inventory id", "Risk class", "Data classes", "Rollback"):
        assert label in text, label


def test_b93_2_the_template_skeleton_has_exactly_the_record_fields() -> None:
    skeleton = json.loads(blocks(read(TEMPLATE))[0])
    assert set(skeleton) == set(ApprovalRecord.model_fields)


def test_b93_2_the_skeleton_is_a_valid_draft_record() -> None:
    skeleton = json.loads(blocks(read(TEMPLATE))[0])
    assert skeleton["status"] == "draft"
    ApprovalRecord.model_validate(skeleton)


def worked_example() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    found = [json.loads(b) for b in blocks(read(PROCESS))]
    by_kind = {b.get("kind", "vendor"): b for b in found}
    return by_kind["provider"], by_kind["model"], by_kind["vendor"]


def test_b93_worked_example_is_valid_and_passes_the_checker_in_its_own_world() -> None:
    provider, model, vendor = worked_example()
    raw, world = hosted_world()
    raw["records"] = [r for r in raw["records"] if r["id"] not in ("AC-901", "AC-902")]
    raw["records"] += [provider, model]
    world = world.replace(vendors=VendorRegister.model_validate({"version": 1, "vendors": [vendor]}))
    assert check(raw, world) == []


def test_b93_worked_example_is_synthetic_and_not_in_the_committed_register_or_records() -> None:
    provider, model, vendor = worked_example()
    assert vendor["id"] not in read(ROOT / "governance" / "ai-vendor-register.json")
    ids = {r["id"] for r in raw_records()["records"]}
    assert provider["id"] not in ids and model["id"] not in ids
    text = read(PROCESS).lower()
    assert "worked example" in text and "synthetic" in text
