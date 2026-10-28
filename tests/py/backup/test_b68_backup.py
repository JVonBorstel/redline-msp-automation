"""B-68 backup adapter mock, daily job review and failed-backup triage, and the backup.retry-job lever.

Acceptance ids B68-1 to B68-4 are defined in specs/B-68.md. Every test is offline and works in a private folder
(tmp_path); committed fixtures are never modified. Run: uv run --frozen pytest -p no:cacheprovider tests/py/backup
"""

from __future__ import annotations

import ast
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from adapters.backup import JOB_TYPES, BackupAdapter, BackupMock
from adapters.base import AdapterError
from adapters.binding import BoundBinding
from core.audit import AuditLog, verify_chain
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, Approval, LeverRunner, MockTenant, Registry
from workflows.backup_review import (
    ReviewError,
    classify,
    draft_tickets,
    load_config,
    propose_retries,
    propose_retry,
    review_client,
    review_clients,
    summary,
)
from workflows.backup_review.__main__ import main
from workflows.notify import TEMPLATES_DIR, missing_templates

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "fixtures" / "backup"
CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
AS_OF = datetime(2026, 10, 21, 7, 0, tzinfo=UTC)
LEVER = "backup.retry-job"
RETRY = {"job_id": "BJ-1003"}


@pytest.fixture
def config() -> Any:
    return load_config()


@pytest.fixture
def runner(tmp_path: Path) -> LeverRunner:
    shutil.copytree(DEFAULT_TENANT_DIR, tmp_path / "tenant")
    return LeverRunner(
        Registry.load(), IdentityStore.load(), MockTenant(tmp_path / "tenant"), AuditLog(tmp_path / "audit.jsonl")
    )


def _chain_ok(tmp_path: Path) -> bool:
    return verify_chain(tmp_path / "audit.jsonl", tmp_path / "audit.jsonl.head").ok


def _approval(params: dict[str, Any], client: str = CONTOSO) -> Approval:
    return Approval(approver="lead-lee", lever=LEVER, client=client, params=params, verification=None)


def _raw(client: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{client}.json").read_text(encoding="utf-8"))
    return data


def _own_jobs(client: str) -> list[dict[str, Any]]:
    data = _raw(client)
    return [j for j in data["jobs"] if j["organizationId"] == data["organization"]["id"]]


# -- B68-1 daily review: failed, missed and long-running per client, with the reason -----------------------------


def test_b68_1_contoso_review_lists_failed_missed_and_long_running_with_the_job_records_reason(config: Any) -> None:
    review = review_client(BackupMock.for_fixture(CONTOSO), AS_OF, config)
    found = {f.job_id: (f.bucket, f.reason) for f in review.findings}
    assert found == {
        "BJ-1003": ("failed", "Snapshot failed: not enough free space on the appliance volume"),
        "BJ-1005": (
            "failed",
            "The backup finished but the boot check failed. "
            "Screenshot shows the Windows recovery screen, not the login screen",
        ),
        "BJ-1007": ("long-running", "Running for 240 minutes; the job record expects about 90."),
        "BJ-1008": ("missed", "Job did not start: the tenant authorization has expired"),
    }
    assert review.flagged == ()


def test_b68_1_fabrikam_review_is_its_own_list_and_a_late_scheduled_job_is_missed(config: Any) -> None:
    review = review_client(BackupMock.for_fixture(FABRIKAM), AS_OF, config)
    buckets = {f.job_id: f.bucket for f in review.findings}
    assert buckets == {
        "BJ-2004": "failed",
        "BJ-2005": "failed",
        "BJ-2006": "long-running",
        "BJ-2007": "missed",
        "BJ-2012": "failed",
    }
    late = next(f for f in review.findings if f.job_id == "BJ-2007")
    assert late.reason == "No start was recorded within 60 minutes of the schedule."
    assert not any(f.job_id.startswith("BJ-1") for f in review.findings)  # nothing of Contoso's


def test_b68_1_a_job_inside_its_time_or_still_scheduled_is_not_a_finding(config: Any) -> None:
    review = review_client(BackupMock.for_fixture(FABRIKAM), AS_OF, config)
    assert "BJ-2008" not in {f.job_id for f in review.findings}  # running one hour of two expected
    early = review_client(BackupMock.for_fixture(FABRIKAM), datetime(2026, 10, 21, 4, 30, tzinfo=UTC), config)
    assert "BJ-2007" not in {f.job_id for f in early.findings}  # 04:00 job, 30 minutes late, inside the 60 minute grace


def test_b68_1_error_text_that_looks_like_an_instruction_is_withheld_and_listed_for_a_person(config: Any) -> None:
    review = review_client(BackupMock.for_fixture(FABRIKAM), AS_OF, config)
    hostile = next(f for f in review.findings if f.job_id == "BJ-2005")
    assert hostile.bucket == "failed" and hostile.reason_withheld
    assert "Ignore previous" not in hostile.reason and "read the job record" in hostile.reason.lower()
    assert review.flagged == ("BJ-2005",)
    drafts = draft_tickets(BackupMock.for_fixture(FABRIKAM), review, config)
    assert all("Ignore previous" not in d.body and "Ignore previous" not in d.title for d in drafts)


def test_b68_1_a_failed_job_without_a_reason_says_so_and_an_unknown_status_is_not_called_healthy(config: Any) -> None:
    job = {"status": "failed", "errorMessage": None, "scheduledStart": "2026-10-21T02:00:00Z"}
    assert classify(job, AS_OF, config)[:2] == ("failed", "The job record gives no reason.")
    odd = {"status": "teleporting", "scheduledStart": "2026-10-21T02:00:00Z"}
    assert classify(odd, AS_OF, config)[0] == "failed"


def test_b68_1_the_cli_prints_the_review_and_refuses_bad_input(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([CONTOSO]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["client"] == CONTOSO and out["reconciles"] is True
    assert {f["job_id"] for f in out["findings"]} == {"BJ-1003", "BJ-1005", "BJ-1007", "BJ-1008"}
    assert main(["no-such-client"]) == 2
    assert main([CONTOSO, "--as-of", "yesterday-ish"]) == 2
    assert main(["../etc"]) == 2
    capsys.readouterr()


# -- B68-2 backup.retry-job (R2): dry-run, approval, one ticket draft for repeated failures ----------------------


def test_b68_2_backup_retry_job_is_a_registered_r2_write_lever_with_a_notice_template() -> None:
    registry = Registry.load()
    spec = registry.get(LEVER)
    assert spec is not None
    assert (spec.lever_class, spec.risk_class, spec.approval, spec.dry_run) == ("write", "R2", "lead", True)
    assert spec.dry_run_role is not None and spec.dry_run_role.value == "agent"
    assert spec.required_role.value == "technician"
    assert spec.impact is not None
    assert (TEMPLATES_DIR / "backup.retry-job.md").is_file()
    assert missing_templates(registry) == []


def test_b68_2_dry_run_shows_a_diff_as_an_agent_and_saves_nothing(runner: LeverRunner, tmp_path: Path) -> None:
    path = tmp_path / "tenant" / f"{CONTOSO}.json"
    before = path.read_bytes()
    result = runner.invoke(LEVER, RETRY, identity="triage-bot", client=CONTOSO)
    assert result.ok and result.mode == "dry-run" and not result.applied
    assert [(c.op, c.path) for c in result.diff] == [("add", "/backupRetryRequests")]
    assert result.diff[0].after == {"BJ-1003": {"action": "retry", "status": "requested"}}
    assert path.read_bytes() == before
    assert _chain_ok(tmp_path)


def test_b68_2_executing_needs_a_technician_and_a_leads_approval_bound_to_the_job(
    runner: LeverRunner, tmp_path: Path
) -> None:
    path = tmp_path / "tenant" / f"{CONTOSO}.json"
    before = path.read_bytes()
    agent = runner.invoke(LEVER, RETRY, identity="triage-bot", client=CONTOSO, mode="execute")
    assert agent.status == "denied" and path.read_bytes() == before
    bare = runner.invoke(LEVER, RETRY, identity="tech-ana", client=CONTOSO, mode="execute")
    assert bare.status == "denied" and path.read_bytes() == before
    other = _approval({"job_id": "BJ-1002"})
    wrong = runner.invoke(LEVER, RETRY, identity="tech-ana", client=CONTOSO, mode="execute", approval=other)
    assert wrong.status == "denied" and path.read_bytes() == before
    done = runner.invoke(LEVER, RETRY, identity="tech-ana", client=CONTOSO, mode="execute", approval=_approval(RETRY))
    assert done.ok and done.applied and done.approver == "lead-lee"
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["backupRetryRequests"] == {"BJ-1003": {"action": "retry", "status": "requested"}}
    again = runner.invoke(LEVER, RETRY, identity="tech-ana", client=CONTOSO, mode="execute", approval=_approval(RETRY))
    assert again.ok and not again.applied and again.diff == ()  # convergent: one request however often it is asked
    assert _chain_ok(tmp_path)


def test_b68_2_bad_input_is_refused_before_any_handler_runs(runner: LeverRunner) -> None:
    for bad in (
        {"job_id": "BJ-1"},
        {"job_id": "T-1001"},
        {"job_id": "BJ-1003; drop"},
        {},
        {"job_id": "BJ-1003", "x": 1},
    ):
        result = runner.invoke(LEVER, bad, identity="triage-bot", client=CONTOSO)
        assert not result.ok, bad


def test_b68_2_repeated_failures_are_one_ticket_draft_and_one_retry_proposal(
    config: Any, runner: LeverRunner, tmp_path: Path
) -> None:
    adapter = BackupMock.for_fixture(FABRIKAM)
    review = review_client(adapter, AS_OF, config)
    drafts = draft_tickets(adapter, review, config)
    fs = [d for d in drafts if d.asset == "FAB-FS01"]
    assert len(fs) == 1  # three nights of failures, one draft
    assert fs[0].job_ids == ("BJ-2002", "BJ-2003", "BJ-2004") and fs[0].failures == 3
    assert fs[0].repeated and fs[0].priority == "high" and fs[0].retry_job_id == "BJ-2004"
    assert fs[0].title == "Backup failed: FAB-FS01 (3 runs in 7 days)"
    assert fs[0].body.splitlines()[0] == "Draft. A person reviews and creates this ticket."
    single = next(d for d in drafts if d.asset == "FAB-SQL01")
    assert not single.repeated and single.priority == "normal" and single.failures == 1
    onedrive = next(d for d in drafts if d.asset.endswith("OneDrive"))
    assert onedrive.job_ids == ("BJ-2011", "BJ-2012") and onedrive.repeated
    # a draft for a missed job that cannot be retried has no retry job; a long-running job gets no failure draft
    assert next(d for d in drafts if d.asset == "FAB-WEB01").retry_job_id is None
    assert "FAB-APP01" not in {d.asset for d in drafts}
    # one dry-run per draft that has a retryable run, never one per night, and never an execute
    tenant = tmp_path / "tenant" / f"{FABRIKAM}.json"
    before = tenant.read_bytes()
    proposals = propose_retries(adapter, drafts, runner)
    assert sorted(p.job_id for p in proposals) == ["BJ-2004", "BJ-2005", "BJ-2012"]
    assert all(p.ok and p.result is not None and not p.result.applied and p.result.mode == "dry-run" for p in proposals)
    assert tenant.read_bytes() == before and _chain_ok(tmp_path)


def test_b68_2_only_a_failed_or_missed_job_of_this_client_is_proposed_for_retry(
    config: Any, runner: LeverRunner, tmp_path: Path
) -> None:
    adapter = BackupMock.for_fixture(CONTOSO)
    healthy = propose_retry("BJ-1006", adapter, runner)
    assert not healthy.ok and healthy.result is None and "success" in healthy.reason
    running = propose_retry("BJ-1007", adapter, runner)
    assert not running.ok and running.result is None
    foreign = propose_retry("BJ-9001", adapter, runner)  # Fabrikam's organization, filed in Contoso's file
    absent = propose_retry("BJ-7777", adapter, runner)
    assert not foreign.ok and foreign.result is None
    assert foreign.reason == absent.reason == "no such backup job for this client"
    assert propose_retry("BJ-1003", adapter, runner).ok
    audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert audit.count(LEVER) >= 1 and "BJ-9001" not in audit and "BJ-1006" not in audit  # refused before the lever


def test_b68_2_a_failure_that_is_fine_today_is_not_a_daily_item(config: Any) -> None:
    adapter = BackupMock.for_fixture(CONTOSO)
    drafts = draft_tickets(adapter, review_client(adapter, AS_OF, config), config)
    assert "DENTAL-SRV01" in {d.asset for d in drafts}
    assert not any("BJ-1004" in d.job_ids or "BJ-1001" in d.job_ids for d in drafts)  # successful runs never listed


# -- B68-3 counts reconcile; another client's job is never shown -------------------------------------------------


@pytest.mark.parametrize("client", [CONTOSO, FABRIKAM])
def test_b68_3_counts_reconcile_overall_per_type_and_with_the_adapters_job_list(client: str, config: Any) -> None:
    adapter = BackupMock.for_fixture(client)
    review = review_client(adapter, AS_OF, config)
    assert review.reconciles
    assert sum(review.counts.values()) == review.reviewed
    assert review.reviewed + review.history == len(_own_jobs(client))  # nothing dropped, nothing invented
    assert len(_own_jobs(client)) == len(adapter.list_jobs().data or [])
    assert sum(len(review.of(b)) for b in ("failed", "missed", "long-running")) == sum(
        review.counts[b] for b in ("failed", "missed", "long-running")
    )
    for job_type, buckets in review.counts_by_type.items():
        in_window = [
            j for j in _own_jobs(client) if j["jobType"] == job_type and j["scheduledStart"] >= "2026-10-20T07:00"
        ]
        assert sum(buckets.values()) == len(in_window), job_type


def test_b68_3_known_counts_for_the_two_fixture_clients(config: Any) -> None:
    contoso = review_client(BackupMock.for_fixture(CONTOSO), AS_OF, config)
    assert (contoso.reviewed, contoso.history) == (5, 3)
    assert dict(contoso.counts) == {"healthy": 1, "in-progress": 0, "failed": 2, "missed": 1, "long-running": 1}
    fabrikam = review_client(BackupMock.for_fixture(FABRIKAM), AS_OF, config)
    assert (fabrikam.reviewed, fabrikam.history) == (9, 3)
    assert dict(fabrikam.counts) == {"healthy": 3, "in-progress": 1, "failed": 3, "missed": 1, "long-running": 1}


def test_b68_3_a_job_of_another_client_is_never_listed_counted_drafted_or_printed(
    config: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    for client, foreign_id, foreign_asset in ((CONTOSO, "BJ-9001", "FAB-DC01"), (FABRIKAM, "BJ-9002", "DENTAL-SRV01")):
        adapter = BackupMock.for_fixture(client)
        assert foreign_id in {j["id"] for j in _raw(client)["jobs"]}  # the decoy really is in the file
        assert foreign_id not in {j["id"] for j in adapter.list_jobs().data or []}
        review = review_client(adapter, AS_OF, config)
        text = json.dumps(summary(review, draft_tickets(adapter, review, config)))
        assert foreign_id not in text and foreign_asset not in text
        assert main([client]) == 0
        printed = capsys.readouterr().out
        assert foreign_id not in printed and foreign_asset not in printed


def test_b68_3_an_adapter_is_built_for_one_client_and_a_foreign_binding_is_refused() -> None:
    with pytest.raises(AdapterError):
        BackupMock(CONTOSO, BoundBinding(FABRIKAM, "backup", "mock", "81002"))  # binding of another client
    with pytest.raises(AdapterError):
        BackupMock(CONTOSO, BoundBinding(CONTOSO, "backup", "mock", "81002"))  # right client, another organization
    with pytest.raises(AdapterError):
        BackupMock(CONTOSO, BoundBinding(CONTOSO, "psa", "mock", "81001"))  # wrong system
    with pytest.raises(AdapterError):
        BackupMock(CONTOSO, BoundBinding(CONTOSO, "backup", "real", "81001"))  # only the mock is built here
    with pytest.raises(AdapterError):
        BackupMock.for_fixture("../tenant/contoso-dental")


def test_b68_3_the_review_refuses_an_adapter_filed_under_another_client(config: Any) -> None:
    contoso, fabrikam = BackupMock.for_fixture(CONTOSO), BackupMock.for_fixture(FABRIKAM)
    with pytest.raises(ReviewError):
        review_clients({CONTOSO: fabrikam}, AS_OF, config)
    both = review_clients({FABRIKAM: fabrikam, CONTOSO: contoso}, AS_OF, config)
    assert list(both) == [CONTOSO, FABRIKAM] and both[CONTOSO].client == CONTOSO
    with pytest.raises(ReviewError):
        draft_tickets(contoso, both[FABRIKAM], config)


def test_b68_3_a_job_lookup_answers_the_same_for_a_foreign_and_an_absent_job() -> None:
    adapter = BackupMock.for_fixture(CONTOSO)
    foreign, absent = adapter.get_job("BJ-9001"), adapter.get_job("BJ-0000")
    assert not foreign.ok and (foreign.ok, foreign.reason, foreign.data) == (absent.ok, absent.reason, absent.data)
    assert adapter.get_job("BJ-1003").ok


# -- B68-4 two job types, UNVERIFIED field names, read-only review, retry is the only write ----------------------


def test_b68_4_the_mock_models_image_appliance_jobs_with_a_boot_check_and_m365_saas_jobs() -> None:
    assert JOB_TYPES == ("image-appliance", "m365-saas")
    for client in (CONTOSO, FABRIKAM):
        adapter = BackupMock.for_fixture(client)
        images = adapter.list_jobs("image-appliance").data or []
        saas = adapter.list_jobs("m365-saas").data or []
        assert images and saas and len(images) + len(saas) == len(adapter.list_jobs().data or [])
        assert all(j["bootCheck"]["status"] in {"passed", "failed", "not-run"} for j in images)
        assert all(j["bootCheck"] is None and j["protectedService"] for j in saas)
    contoso_boot = {
        j["id"]: j["bootCheck"] for j in BackupMock.for_fixture(CONTOSO).list_jobs("image-appliance").data or []
    }
    assert contoso_boot["BJ-1005"]["status"] == "failed" and contoso_boot["BJ-1004"]["status"] == "passed"
    assert BackupMock.for_fixture(CONTOSO).list_jobs("tape").ok is False


def test_b68_4_every_fixture_field_is_listed_as_unverified_in_the_spec() -> None:
    spec = (REPO / "specs" / "B-68.md").read_text(encoding="utf-8")
    rows = {
        (m.group(1), m.group(2)): m.group(3)
        for m in re.finditer(r"^\| (\w+) \| `(\w+)` \| (.+?) \|$", spec, flags=re.MULTILINE)
    }

    def walk(entity: str, value: Any) -> set[tuple[str, str]]:
        found: set[tuple[str, str]] = set()
        if isinstance(value, dict):
            for key, sub in value.items():
                if key != "_note":
                    found.add((entity, key))
                    found |= walk(key, sub)
        elif isinstance(value, list):
            for item in value:
                found |= walk(entity, item)
        return found

    for client in (CONTOSO, FABRIKAM):
        data = _raw(client)
        used = walk("file", {k: v for k, v in data.items() if k != "jobs"}) | walk("jobs", data["jobs"])
        entity_of = {"organization": "organization", "bootCheck": "bootCheck"}
        for entity, field in used:
            row_entity = entity_of.get(entity, entity)
            assert (row_entity, field) in rows, f"{client}: {row_entity}.{field} missing from specs/B-68.md"
            assert "UNVERIFIED" in rows[(row_entity, field)], f"{row_entity}.{field} must be marked UNVERIFIED"
    sources = (FIXTURES / "SOURCES.md").read_text(encoding="utf-8")
    assert "UNVERIFIED" in sources and "No vendor API documentation was read" in sources
    assert not re.search(r"\bVerified\b(?! )|\| Verified", spec), "no field may be claimed Verified"


def test_b68_4_the_review_changes_nothing_and_the_adapter_has_no_write_method(config: Any, tmp_path: Path) -> None:
    before = {p.name: p.read_bytes() for p in FIXTURES.glob("*.json")}
    tenant_before = {p.name: p.read_bytes() for p in DEFAULT_TENANT_DIR.glob("*.json")}
    for client in (CONTOSO, FABRIKAM):
        adapter = BackupMock.for_fixture(client)
        review = review_client(adapter, AS_OF, config)
        draft_tickets(adapter, review, config)
    assert {p.name: p.read_bytes() for p in FIXTURES.glob("*.json")} == before
    assert {p.name: p.read_bytes() for p in DEFAULT_TENANT_DIR.glob("*.json")} == tenant_before
    public = {n for n in dir(BackupAdapter) if not n.startswith("_")}
    assert public <= {"system", "client", "external_id", "credential_ref", "get_organization", "list_jobs", "get_job"}
    assert not any(re.match(r"(create|update|delete|retry|run|set|write|put|post)", n) for n in public)


def test_b68_4_the_review_and_adapter_source_cannot_write_or_call_a_network() -> None:
    forbidden_calls = {"write_text", "write_bytes", "unlink", "rmtree", "rename", "urlopen", "request", "post"}
    forbidden_imports = {"requests", "httpx", "urllib", "socket", "subprocess", "http"}
    files = [*(REPO / "adapters" / "backup").glob("*.py"), *(REPO / "workflows" / "backup_review").glob("*.py")]
    assert len(files) >= 6
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                assert name not in forbidden_calls, f"{path.name}: {name}"
                if name == "open":
                    modes = [a.value for a in node.args[1:2] if isinstance(a, ast.Constant)]
                    assert not any(set(str(m)) & set("wax+") for m in modes), f"{path.name}: open for write"
            if isinstance(node, ast.Import):
                assert not {a.name.split(".")[0] for a in node.names} & forbidden_imports, path.name
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_imports, path.name


def test_b68_4_backup_retry_job_is_the_only_backup_write_lever_and_the_workflow_only_dry_runs_it() -> None:
    registry = Registry.load()
    backup_levers = [n for n in registry.names() if n.startswith("backup.")]
    assert backup_levers == [LEVER]
    spec = registry.get(LEVER)
    assert spec is not None and spec.lever_class == "write"
    source = (REPO / "workflows" / "backup_review" / "review.py").read_text(encoding="utf-8")
    modes = re.findall(r'mode="([a-z-]+)"', source)
    assert modes == ["dry-run"], "the workflow may only dry-run the lever; a lead approves the real retry"
    assert '"execute"' not in source


def test_b68_4_the_workflow_config_is_strict(tmp_path: Path) -> None:
    good = json.loads((REPO / "workflows" / "backup_review" / "config.json").read_text(encoding="utf-8"))
    bad = tmp_path / "config.json"
    bad.write_text(json.dumps({**good, "surprise": 1}), encoding="utf-8")
    with pytest.raises(ReviewError):
        load_config(bad)
    bad.write_text(json.dumps({**good, "long_running_factor": 0.5}), encoding="utf-8")
    with pytest.raises(ReviewError):
        load_config(bad)
    with pytest.raises(ReviewError):
        load_config(tmp_path / "missing.json")
    tight = load_config().model_copy(update={"long_running_factor": 2.9})
    review = review_client(BackupMock.for_fixture(CONTOSO), AS_OF, tight)  # 240 of 90 minutes is 2.67 times
    assert review.counts["long-running"] == 0 and review.counts["in-progress"] == 1 and review.reconciles
