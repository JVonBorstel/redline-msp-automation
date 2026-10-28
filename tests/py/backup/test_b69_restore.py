"""B-69 restore requests to an alternate location, scheduled restore tests, and the restore.to-alternate lever.

Acceptance ids B69-1 to B69-3 are defined in specs/B-69.md. Every test is offline and works in a private folder
(tmp_path); committed fixtures are never modified. Run: uv run --frozen pytest -p no:cacheprovider tests/py/backup
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from adapters.base import AdapterError
from core.audit import AuditLog, verify_chain
from core.audit.chain import head_path_for
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, Approval, LeverRunner, MockTenant, Registry
from core.levers.handlers import LeverFailed
from core.levers.models import Verification
from core.scheduler import Unit
from levers.python.restore import restore_to_alternate
from workflows.notify import TEMPLATES_DIR, missing_templates
from workflows.restore_tests import (
    IN_PLACE_REFUSED,
    RestoreCatalog,
    RestoreError,
    VerifyError,
    audit_digest,
    canonical_bytes,
    load_config,
    pick_item,
    propose_restore,
    restore_test_workflow,
    run_restore_test,
    sidecar_for,
    verify_evidence,
)
from workflows.restore_tests.__main__ import main
from workflows.restore_tests.catalog import DEFAULT_CATALOG_DIR

REPO = Path(__file__).resolve().parents[3]
CATALOGS = REPO / "workflows" / "restore_tests" / "catalog"
SPEC = REPO / "specs" / "B-69.md"
CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
LEVER = "restore.to-alternate"
REQUEST = {"item_id": "RI-1001", "alternate_location": "ALT-RESTORE-1001"}
DAY = "2026-10-21"
TECH = {CONTOSO: "tech-ana", FABRIKAM: "tech-ben"}


@pytest.fixture
def runner(tmp_path: Path) -> LeverRunner:
    shutil.copytree(DEFAULT_TENANT_DIR, tmp_path / "tenant")
    return LeverRunner(
        Registry.load(), IdentityStore.load(), MockTenant(tmp_path / "tenant"), AuditLog(tmp_path / "audit.jsonl")
    )


def _chain_ok(tmp_path: Path) -> bool:
    return verify_chain(tmp_path / "audit.jsonl", tmp_path / "audit.jsonl.head").ok


def _verification(by: str = "tech-ana", **kw: Any) -> Verification:
    fields: dict[str, Any] = {
        "method": "finding-reference",
        "by": by,
        "at": datetime.now(UTC) - timedelta(minutes=5),
        "ref": "T-1001",
    }
    return Verification(**{**fields, **kw})


def _approval(
    params: dict[str, Any], client: str = CONTOSO, verification: Verification | None = None, approver: str = "lead-lee"
) -> Approval:
    return Approval(approver=approver, lever=LEVER, client=client, params=params, verification=verification)


def _raw(client: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((CATALOGS / f"{client}.json").read_text(encoding="utf-8"))
    return data


def _catalog(client: str = CONTOSO, root: Path = DEFAULT_CATALOG_DIR) -> RestoreCatalog:
    return RestoreCatalog.for_fixture(client, root)


def _records(audit: Path, client: str) -> list[dict[str, Any]]:
    chain = audit / f"{client}.jsonl"
    return [json.loads(line) for line in chain.read_text(encoding="utf-8").splitlines()] if chain.is_file() else []


def _copy_catalog(tmp_path: Path, client: str, edit: Any) -> Path:
    root = tmp_path / "catalog"
    root.mkdir(parents=True, exist_ok=True)
    data = _raw(client)
    edit(data)
    (root / f"{client}.json").write_text(json.dumps(data), encoding="utf-8")
    return root


# -- B69-1 restore.to-alternate (R2): alternate location only ----------------------------------------------------


def test_b69_1_restore_to_alternate_is_a_registered_r2_write_lever_with_a_notice_template() -> None:
    registry = Registry.load()
    spec = registry.get(LEVER)
    assert spec is not None
    assert (spec.lever_class, spec.risk_class, spec.approval, spec.dry_run) == ("write", "R2", "lead", True)
    assert spec.dry_run_role is not None and spec.dry_run_role.value == "agent"
    assert spec.required_role.value == "technician"
    assert spec.impact is not None
    assert (TEMPLATES_DIR / f"{LEVER}.md").is_file()
    assert missing_templates(registry) == []


def test_b69_1_in_place_overwrite_is_not_a_lever(runner: LeverRunner) -> None:
    registry = Registry.load()
    restore_levers = [n for n in registry.names() if n.startswith("restore.") or "overwrite" in n or "in-place" in n]
    assert restore_levers == [LEVER]
    spec = registry.get(LEVER)
    assert spec is not None and set(spec.params) == {"item_id", "alternate_location"}
    pattern = spec.params["alternate_location"].pattern or ""
    assert pattern.startswith("^ALT-")
    for original in (
        "//DENTAL-SRV01/Shared/Forms/treatment-plan-template.txt",
        "image:FRONTDESK-PC1",
        "mailbox:frontdesk@contoso-dental.example/Drafts",
        "DENTAL-SRV01",
        "ALT-",
        "alt-lower-case",
        "ALT-X; drop",
    ):
        assert not re.fullmatch(pattern, original), original
        result = runner.invoke(
            LEVER, {**REQUEST, "alternate_location": original}, identity="triage-bot", client=CONTOSO
        )
        assert not result.ok, original


def test_b69_1_the_handler_refuses_a_non_alternate_location_even_if_the_registry_were_loosened() -> None:
    state: dict[str, Any] = {}
    with pytest.raises(LeverFailed):
        restore_to_alternate(state, {"item_id": "RI-1001", "alternate_location": "//DENTAL-SRV01/Shared"})
    assert state == {}


def test_b69_1_dry_run_shows_a_diff_as_an_agent_and_saves_nothing(runner: LeverRunner, tmp_path: Path) -> None:
    path = tmp_path / "tenant" / f"{CONTOSO}.json"
    before = path.read_bytes()
    result = runner.invoke(LEVER, REQUEST, identity="triage-bot", client=CONTOSO)
    assert result.ok and result.mode == "dry-run" and not result.applied
    assert [(c.op, c.path) for c in result.diff] == [("add", "/restoreRequests")]
    assert result.diff[0].after == {
        "RI-1001@ALT-RESTORE-1001": {"action": "restore", "target": "alternate", "status": "requested"}
    }
    assert path.read_bytes() == before
    assert _chain_ok(tmp_path)


def test_b69_1_executing_needs_a_technician_and_a_leads_approval_bound_to_item_and_location(
    runner: LeverRunner, tmp_path: Path
) -> None:
    path = tmp_path / "tenant" / f"{CONTOSO}.json"
    before = path.read_bytes()
    verified = _verification()
    agent = runner.invoke(LEVER, REQUEST, identity="triage-bot", client=CONTOSO, mode="execute")
    assert agent.status == "denied" and path.read_bytes() == before
    bare = runner.invoke(LEVER, REQUEST, identity="tech-ana", client=CONTOSO, mode="execute")
    assert bare.status == "denied" and path.read_bytes() == before
    for other in (
        {**REQUEST, "item_id": "RI-1003"},
        {**REQUEST, "alternate_location": "ALT-SOMEWHERE-ELSE"},
    ):
        wrong = runner.invoke(
            LEVER,
            REQUEST,
            identity="tech-ana",
            client=CONTOSO,
            mode="execute",
            approval=_approval(other, verification=verified),
        )
        assert wrong.status == "denied" and path.read_bytes() == before
    done = runner.invoke(
        LEVER,
        REQUEST,
        identity="tech-ana",
        client=CONTOSO,
        mode="execute",
        approval=_approval(REQUEST, verification=verified),
    )
    assert done.ok and done.applied and done.approver == "lead-lee"
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["restoreRequests"] == {
        "RI-1001@ALT-RESTORE-1001": {"action": "restore", "target": "alternate", "status": "requested"}
    }
    again = runner.invoke(
        LEVER,
        REQUEST,
        identity="tech-ana",
        client=CONTOSO,
        mode="execute",
        approval=_approval(REQUEST, verification=verified),
    )
    assert again.ok and not again.applied and again.diff == ()  # convergent: one request however often it is asked
    assert _chain_ok(tmp_path)


def test_b69_1_bad_input_is_refused_before_any_handler_runs(runner: LeverRunner) -> None:
    for bad in (
        {"item_id": "RI-1", "alternate_location": "ALT-RESTORE-1001"},
        {"item_id": "BJ-1001", "alternate_location": "ALT-RESTORE-1001"},
        {"item_id": "RI-1001"},
        {"alternate_location": "ALT-RESTORE-1001"},
        {**REQUEST, "x": 1},
        {**REQUEST, "overwrite": True},
        {},
    ):
        result = runner.invoke(LEVER, bad, identity="triage-bot", client=CONTOSO)
        assert not result.ok, bad


@pytest.mark.parametrize(
    ("client", "item_id", "kind"),
    [
        (CONTOSO, "RI-1001", "file"),
        (CONTOSO, "RI-1003", "mailbox-item"),
        (CONTOSO, "RI-1004", "vm"),
        (FABRIKAM, "RI-2001", "file"),
        (FABRIKAM, "RI-2002", "mailbox-item"),
        (FABRIKAM, "RI-2003", "vm"),
    ],
)
def test_b69_1_a_file_a_mailbox_item_and_a_vm_each_dry_run_to_an_alternate_location(
    client: str, item_id: str, kind: str, runner: LeverRunner, tmp_path: Path
) -> None:
    catalog = _catalog(client)
    assert catalog.get_item(item_id).data["kind"] == kind  # type: ignore[index]
    tenant = tmp_path / "tenant" / f"{client}.json"
    before = tenant.read_bytes()
    proposal = propose_restore(item_id, f"ALT-RESTORE-{item_id[3:]}", catalog, runner)
    assert proposal.ok and proposal.result is not None
    assert proposal.result.mode == "dry-run" and not proposal.result.applied
    assert tenant.read_bytes() == before and _chain_ok(tmp_path)


def test_b69_1_a_request_for_the_original_location_is_refused_and_the_lever_is_never_called(
    runner: LeverRunner, tmp_path: Path
) -> None:
    catalog = _catalog()
    item = catalog.get_item("RI-1001").data
    assert item is not None
    original = item["originalLocation"]
    for target in (
        original,
        original.upper(),
        original + "/",
        original.replace("/", "\\"),
        "  " + original,
        "//DENTAL-SRV01/Shared",  # not an ALT- name
        "ALT",
        "",
    ):
        proposal = propose_restore("RI-1001", target, catalog, runner)
        assert not proposal.ok and proposal.result is None, target
        assert proposal.reason == IN_PLACE_REFUSED
    assert "own approval" in IN_PLACE_REFUSED
    assert not (tmp_path / "audit.jsonl").exists()  # refused before the lever: nothing audited as a lever call


def test_b69_1_only_a_restorable_item_of_this_client_is_proposed(runner: LeverRunner, tmp_path: Path) -> None:
    catalog = _catalog(CONTOSO)
    failed_job = propose_restore("RI-1002", "ALT-RESTORE-1002", catalog, runner)  # its backup job BJ-1003 failed
    assert not failed_job.ok and failed_job.result is None and "did not finish successfully" in failed_job.reason
    foreign = propose_restore(
        "RI-9001", "ALT-RESTORE-9001", catalog, runner
    )  # Fabrikam's organization, in Contoso's file
    absent = propose_restore("RI-7777", "ALT-RESTORE-7777", catalog, runner)
    assert not foreign.ok and foreign.result is None
    assert foreign.reason == absent.reason == "no such restorable item for this client"
    assert propose_restore("RI-1001", "ALT-RESTORE-1001", catalog, runner).ok
    audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert audit.count(LEVER) >= 1 and "RI-9001" not in audit and "RI-1002" not in audit  # refused before the lever


def test_b69_1_the_workflow_can_only_dry_run_and_never_names_the_execute_mode() -> None:
    source = (REPO / "workflows" / "restore_tests" / "restore.py").read_text(encoding="utf-8")
    calls = [
        n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "invoke"
    ]
    assert len(calls) == 1
    modes = [k.value.value for k in calls[0].keywords if k.arg == "mode" and isinstance(k.value, ast.Constant)]
    assert modes == ["dry-run"]


# -- B69-1 catalog: per-client scope -----------------------------------------------------------------------------


def test_b69_1_the_catalog_is_built_for_one_client_and_drops_every_foreign_item() -> None:
    for client, foreign in ((CONTOSO, "RI-9001"), (FABRIKAM, "RI-9002")):
        raw_ids = {i["id"] for i in _raw(client)["items"]}
        assert foreign in raw_ids  # the decoy really is in the file
        catalog = _catalog(client)
        assert foreign not in {i["id"] for i in catalog.items().data or []}
        assert not catalog.get_item(foreign).ok and not catalog.restorable(foreign).ok
        assert foreign not in catalog.restorable_ids()
        # the item list never carries restored bytes
        assert all("content" not in i for i in catalog.items().data or [])


def test_b69_1_a_catalog_of_another_client_or_organization_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "catalog"
    root.mkdir()
    (root / f"{CONTOSO}.json").write_text((CATALOGS / f"{FABRIKAM}.json").read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(AdapterError):
        RestoreCatalog.for_fixture(CONTOSO, root)
    wrong_org = _copy_catalog(tmp_path / "x", CONTOSO, lambda d: d.update(organizationId=81002))
    with pytest.raises(AdapterError):
        RestoreCatalog.for_fixture(CONTOSO, wrong_org)
    with pytest.raises(AdapterError):
        RestoreCatalog.for_fixture("../tenant/contoso-dental")
    with pytest.raises(AdapterError):
        RestoreCatalog.for_fixture("no-such-client")


def test_b69_1_a_restore_through_the_catalog_goes_to_an_alternate_location_only() -> None:
    catalog = _catalog()
    sink: dict[str, bytes] = {}
    original = (catalog.get_item("RI-1001").data or {})["originalLocation"]
    refused = catalog.restore("RI-1001", original, sink)
    assert not refused.ok and sink == {}
    done = catalog.restore("RI-1001", "ALT-RESTORE-1001", sink)
    assert done.ok and list(sink) == ["ALT-RESTORE-1001"]
    assert not catalog.restore("RI-9001", "ALT-RESTORE-9001", sink).ok  # another client's item
    assert not catalog.restore("RI-1002", "ALT-RESTORE-1002", sink).ok  # its backup job failed
    assert list(sink) == ["ALT-RESTORE-1001"]


# -- B69-2 scheduled restore test ---------------------------------------------------------------------------------


def _run(tmp_path: Path, client: str = CONTOSO, day: str = DAY, **kw: Any) -> Any:
    return run_restore_test(_catalog(client), day, out_dir=tmp_path / "out", audit_dir=tmp_path / "audit", **kw)


@pytest.mark.parametrize("client", [CONTOSO, FABRIKAM])
def test_b69_2_a_test_restores_one_item_verifies_its_hash_and_records_evidence(client: str, tmp_path: Path) -> None:
    record = _run(tmp_path, client)
    assert record.result == "passed" and record.client == client
    assert record.path == tmp_path / "out" / client / f"{DAY}.json"
    body = json.loads(record.path.read_bytes())
    assert body["expected_sha256"] == body["restored_sha256"] and len(body["expected_sha256"]) == 64
    assert body["result"] == "passed" and body["client"] == client and body["as_of"] == DAY
    assert body["item"]["id"] in _catalog(client).restorable_ids()
    assert body["restore"]["location"].startswith("ALT-")
    assert body["restore"]["location"] != body["item"]["original_location"]
    assert body["catalog_sha256"] == _catalog(client).source_sha256
    # the evidence hash is in a sha256sum-format sidecar and in the client's audit chain
    side = sidecar_for(record.path).read_text(encoding="ascii")
    assert side == f"{record.sha256}  {record.path.name}\n"
    assert verify_evidence(record.path, tmp_path / "audit") == record.sha256
    chain = _records(tmp_path / "audit", client)
    assert len(chain) == 1 and chain[0]["lever"] == "restore-test.run"
    assert chain[0]["result"]["sha256"] == audit_digest(record.sha256) and chain[0]["client"] == client
    assert verify_chain(
        tmp_path / "audit" / f"{client}.jsonl", head_path_for(tmp_path / "audit" / f"{client}.jsonl")
    ).ok


def test_b69_2_the_hash_is_computed_from_what_came_back_not_copied_from_the_catalog(tmp_path: Path) -> None:
    root = _copy_catalog(
        tmp_path,
        CONTOSO,
        lambda d: [i.update(content=i["content"] + "bit rot\n") for i in d["items"] if i["id"] == "RI-1001"],
    )
    record = run_restore_test(
        _catalog(CONTOSO, root), DAY, out_dir=tmp_path / "out", audit_dir=tmp_path / "audit", item_id="RI-1001"
    )
    body = json.loads(record.path.read_bytes())
    assert record.result == "failed" and body["result"] == "failed"
    assert body["expected_sha256"] != body["restored_sha256"] and body["restored_sha256"] is not None
    assert "does not have the SHA-256" in body["reason"]
    assert verify_evidence(record.path, tmp_path / "audit") == record.sha256  # a failed test is still intact evidence
    assert (
        main(
            [
                "run",
                CONTOSO,
                "--as-of",
                "2026-10-22",
                "--item",
                "RI-1001",
                "--catalog",
                str(root),
                "--out",
                str(tmp_path / "o2"),
                "--audit-dir",
                str(tmp_path / "a2"),
            ]
        )
        == 1
    )


def test_b69_2_the_pick_is_deterministic_per_day_and_varies_with_the_day_and_seed(tmp_path: Path) -> None:
    ids = ["RI-1001", "RI-1003", "RI-1004"]
    assert pick_item(CONTOSO, DAY, "", ids) == pick_item(CONTOSO, DAY, "", list(reversed(ids)))
    picks = {pick_item(CONTOSO, f"2026-10-{d:02d}", "", ids) for d in range(1, 29)}
    assert picks == set(ids)  # over a month every restorable item is eventually tested
    assert len({pick_item(CONTOSO, DAY, str(s), ids) for s in range(30)}) > 1
    first, again = _run(tmp_path), _run(tmp_path)
    assert first.sha256 == again.sha256 and first.item_id == again.item_id  # re-running a day changes nothing
    assert len(_records(tmp_path / "audit", CONTOSO)) == 2 and _chain_ok_dir(tmp_path / "audit", CONTOSO)


def _chain_ok_dir(audit: Path, client: str) -> bool:
    path = audit / f"{client}.jsonl"
    return verify_chain(path, head_path_for(path)).ok


def test_b69_2_a_test_never_picks_an_item_that_is_not_restorable_or_not_this_clients(tmp_path: Path) -> None:
    allowed = set(_catalog(CONTOSO).restorable_ids())
    assert allowed == {"RI-1001", "RI-1003", "RI-1004"}  # not RI-1002 (failed job) and not RI-9001 (Fabrikam's)
    seen = set()
    for n in range(40):
        record = run_restore_test(
            _catalog(CONTOSO), DAY, out_dir=tmp_path / f"o{n}", audit_dir=tmp_path / "a", seed=f"s{n}"
        )
        seen.add(record.item_id)
    assert seen <= allowed and len(seen) >= 2


def test_b69_2_a_test_changes_no_tenant_state_and_no_fixture_and_never_writes_the_original(tmp_path: Path) -> None:
    watched = [
        *sorted((REPO / "fixtures" / "tenant").glob("*.json")),
        *sorted((REPO / "fixtures" / "backup").glob("*.json")),
        *sorted(CATALOGS.glob("*.json")),
    ]
    before = {p: p.read_bytes() for p in watched}
    for client in (CONTOSO, FABRIKAM):
        _run(tmp_path, client)
    assert {p: p.read_bytes() for p in watched} == before
    written = sorted(
        p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file() and p.suffix != ".lock"
    )
    assert written == [
        "audit/contoso-dental.jsonl",
        "audit/contoso-dental.jsonl.head",
        "audit/fabrikam-capital.jsonl",
        "audit/fabrikam-capital.jsonl.head",
        "out/contoso-dental/2026-10-21.json",
        "out/contoso-dental/2026-10-21.json.sha256",
        "out/fabrikam-capital/2026-10-21.json",
        "out/fabrikam-capital/2026-10-21.json.sha256",
    ]


def test_b69_2_evidence_is_per_client_and_never_names_another_clients_item(tmp_path: Path) -> None:
    contoso, fabrikam = _run(tmp_path, CONTOSO), _run(tmp_path, FABRIKAM)
    text_c, text_f = contoso.path.read_text(encoding="ascii"), fabrikam.path.read_text(encoding="ascii")
    assert "RI-9001" not in text_c and "RI-9002" not in text_f
    assert "fab-dc-notes" not in text_c and "dental-schedule" not in text_f
    assert "fabrikam" not in text_c.lower() and "contoso" not in text_f.lower()
    assert "contoso" not in (tmp_path / "audit" / f"{FABRIKAM}.jsonl").read_text(encoding="utf-8").lower()


def test_b69_2_a_client_with_nothing_restorable_records_not_run_rather_than_nothing(tmp_path: Path) -> None:
    root = _copy_catalog(tmp_path, CONTOSO, lambda d: d.update(items=[i for i in d["items"] if i["id"] == "RI-1002"]))
    record = run_restore_test(_catalog(CONTOSO, root), DAY, out_dir=tmp_path / "out", audit_dir=tmp_path / "audit")
    body = json.loads(record.path.read_bytes())
    assert record.result == "not-run" and body["item"] is None and body["restore"] is None
    assert body["expected_sha256"] is None and body["restored_sha256"] is None
    assert verify_evidence(record.path, tmp_path / "audit") == record.sha256


def test_b69_2_changed_evidence_is_caught_even_with_a_fresh_sidecar(tmp_path: Path) -> None:
    root = _copy_catalog(
        tmp_path,
        CONTOSO,
        lambda d: [i.update(content="rotten\n") for i in d["items"] if i["id"] == "RI-1001"],
    )
    record = run_restore_test(
        _catalog(CONTOSO, root), DAY, out_dir=tmp_path / "out", audit_dir=tmp_path / "audit", item_id="RI-1001"
    )
    body = json.loads(record.path.read_bytes())
    # 1: edit without touching the sidecar
    edited = {**body, "result": "passed"}
    record.path.write_text(json.dumps(edited, sort_keys=True, indent=2) + "\n", encoding="ascii")
    with pytest.raises(VerifyError, match="does not match the sidecar"):
        verify_evidence(record.path)
    # 2: edit and rewrite the sidecar: the file now disagrees with its own two hashes
    forged = canonical_bytes(edited)
    record.path.write_bytes(forged)
    digest = hashlib.sha256(forged).hexdigest()
    sidecar_for(record.path).write_text(f"{digest}  {record.path.name}\n", encoding="ascii")
    with pytest.raises(VerifyError, match="does not agree with the two hashes"):
        verify_evidence(record.path)
    # 3: make the hashes agree too: only the audit pin catches it
    forged2 = canonical_bytes({**edited, "restored_sha256": edited["expected_sha256"]})
    record.path.write_bytes(forged2)
    digest2 = hashlib.sha256(forged2).hexdigest()
    sidecar_for(record.path).write_text(f"{digest2}  {record.path.name}\n", encoding="ascii")
    assert verify_evidence(record.path) == digest2  # internally consistent
    with pytest.raises(VerifyError, match="is not pinned"):
        verify_evidence(record.path, tmp_path / "audit")


def test_b69_2_evidence_that_restored_over_the_original_does_not_verify(tmp_path: Path) -> None:
    record = _run(tmp_path)
    body = json.loads(record.path.read_bytes())
    body["restore"]["location"] = body["item"]["original_location"]
    forged = canonical_bytes(body)
    record.path.write_bytes(forged)
    sidecar_for(record.path).write_text(f"{hashlib.sha256(forged).hexdigest()}  {record.path.name}\n", encoding="ascii")
    with pytest.raises(VerifyError, match="original location"):
        verify_evidence(record.path)


def test_b69_2_a_different_result_for_a_day_that_has_evidence_is_refused_not_overwritten(tmp_path: Path) -> None:
    first = _run(tmp_path, item_id="RI-1001")
    kept = first.path.read_bytes()
    root = _copy_catalog(
        tmp_path, CONTOSO, lambda d: [i.update(content="x\n") for i in d["items"] if i["id"] == "RI-1001"]
    )
    with pytest.raises(RestoreError, match="not overwritten"):
        run_restore_test(
            _catalog(CONTOSO, root), DAY, out_dir=tmp_path / "out", audit_dir=tmp_path / "audit", item_id="RI-1001"
        )
    assert first.path.read_bytes() == kept
    assert _records(tmp_path / "audit", CONTOSO)[-1]["result"]["status"] == "refused"


def test_b69_2_the_runner_must_be_known_and_scoped_to_the_client(tmp_path: Path) -> None:
    for who in ("tech-ben", "ghost"):  # Ben serves Fabrikam only; ghost does not exist
        with pytest.raises(RestoreError):
            _run(tmp_path, by=who)
    assert not (tmp_path / "out").exists()  # nothing restored, no evidence
    refused = _records(tmp_path / "audit", CONTOSO)
    assert [r["result"]["status"] for r in refused] == ["refused", "refused"]
    assert _run(tmp_path, by="tech-ana").result == "passed"


def test_b69_2_bad_dates_and_seeds_are_refused_before_anything_is_written(tmp_path: Path) -> None:
    for day in ("yesterday", "2026-13-01", "2026-10-21T00:00:00Z", "../2026-10-21"):
        with pytest.raises(RestoreError):
            _run(tmp_path, day=day)
    with pytest.raises(RestoreError):
        _run(tmp_path, seed="../x")
    with pytest.raises(RestoreError):
        _run(tmp_path, item_id="RI-9001")  # Fabrikam's item, forced into Contoso's test
    with pytest.raises(RestoreError):
        _run(tmp_path, item_id="RI-1002")  # backup job failed
    assert not (tmp_path / "out").exists()


def test_b69_2_the_scheduler_workflow_runs_one_test_for_the_units_client_and_proposes_nothing(tmp_path: Path) -> None:
    workflow = restore_test_workflow(out_dir=tmp_path / "out", audit_dir=tmp_path / "audit")
    as_of = datetime(2026, 10, 21, 7, 0, tzinfo=UTC)
    unit = Unit(
        key=f"restore-tests/{CONTOSO}/2026-10", job="restore-tests", client=CONTOSO, period="2026-10", as_of=as_of
    )
    result = workflow(unit)
    assert result.proposals == () and result.report.startswith("restore test of RI-") and "PASSED" in result.report
    assert len(result.report) <= 200
    assert (tmp_path / "out" / CONTOSO / f"{DAY}.json").is_file() and not (tmp_path / "out" / FABRIKAM).exists()
    assert workflow(unit).report == result.report  # same unit again, same evidence
    assert load_config().every == "monthly"


def test_b69_2_the_cli_runs_a_test_and_verifies_it_and_refuses_bad_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["--as-of", DAY, "--out", str(tmp_path / "out"), "--audit-dir", str(tmp_path / "audit")]
    assert main(["run", CONTOSO, *args]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["result"] == "passed" and out["client"] == CONTOSO and len(out["sha256"]) == 64
    path = Path(out["path"])
    assert main(["verify", str(path), "--audit-dir", str(tmp_path / "audit")]) == 0
    assert out["sha256"] in capsys.readouterr().out
    path.write_text(path.read_text(encoding="ascii").replace("passed", "failed"), encoding="ascii")
    assert main(["verify", str(path)]) == 1
    assert main(["run", "no-such-client", *args]) == 2
    assert main(["run", "../etc", *args]) == 2
    assert main(["run", CONTOSO, "--as-of", "soon", "--out", str(tmp_path / "out")]) == 2
    capsys.readouterr()


def test_b69_2_the_catalog_fields_are_all_listed_as_unverified_in_the_spec() -> None:
    spec = SPEC.read_text(encoding="utf-8")
    rows = {
        tuple(c.strip(" `") for c in line.strip("|").split("|")[:3])
        for line in spec.splitlines()
        if line.startswith("| ")
    }
    for client in (CONTOSO, FABRIKAM):
        data = _raw(client)
        for key in data:
            if key != "_note":
                assert ("file", key, "UNVERIFIED") in {(a, b, c.split(" ")[0]) for a, b, c in rows}, key
        for item in data["items"]:
            for key in item:
                assert ("items", key, "UNVERIFIED") in {(a, b, c.split(" ")[0]) for a, b, c in rows}, key


# -- B69-3 the requester is verified for user-data restores -------------------------------------------------------


def test_b69_3_the_lever_requires_a_recorded_requester_verification() -> None:
    spec = Registry.load().get(LEVER)
    assert spec is not None and spec.verification == "requester"


def test_b69_3_execute_without_a_verification_is_denied_and_with_one_it_runs_and_is_audited(
    runner: LeverRunner, tmp_path: Path
) -> None:
    path = tmp_path / "tenant" / f"{CONTOSO}.json"
    before = path.read_bytes()
    plain = runner.invoke(
        LEVER, REQUEST, identity="tech-ana", client=CONTOSO, mode="execute", approval=_approval(REQUEST)
    )
    assert plain.status == "denied" and "verification" in plain.reason and path.read_bytes() == before
    ok = runner.invoke(
        LEVER,
        REQUEST,
        identity="tech-ana",
        client=CONTOSO,
        mode="execute",
        approval=_approval(REQUEST, verification=_verification()),
    )
    assert ok.ok and ok.applied
    records = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    executed = [r for r in records if r.get("mode") == "execute" and r["result"].get("applied")]
    assert executed and executed[-1]["result"]["verification"]["by"] == "tech-ana"
    assert executed[-1]["result"]["verification"]["ref"] == "T-1001"
    assert _chain_ok(tmp_path)


@pytest.mark.parametrize(
    "verification",
    [
        {"by": "triage-bot"},  # an agent cannot verify a person
        {"by": "tech-ben"},  # a technician of another client cannot
        {"by": "ghost"},  # unknown identity
        {"at": datetime.now(UTC) + timedelta(hours=2)},  # from the future
    ],
)
def test_b69_3_a_verification_by_an_agent_a_stranger_or_from_the_future_is_denied(
    verification: dict[str, Any], runner: LeverRunner, tmp_path: Path
) -> None:
    path = tmp_path / "tenant" / f"{CONTOSO}.json"
    before = path.read_bytes()
    result = runner.invoke(
        LEVER,
        REQUEST,
        identity="tech-ana",
        client=CONTOSO,
        mode="execute",
        approval=_approval(REQUEST, verification=_verification(**verification)),
    )
    assert result.status == "denied" and path.read_bytes() == before


def test_b69_3_a_verification_for_one_client_does_not_open_another_clients_restore(
    runner: LeverRunner, tmp_path: Path
) -> None:
    other = {"item_id": "RI-2001", "alternate_location": "ALT-RESTORE-2001"}
    fabrikam_state = tmp_path / "tenant" / f"{FABRIKAM}.json"
    before = fabrikam_state.read_bytes()
    # Ana is scoped to Contoso: she cannot execute for Fabrikam, whoever approves
    result = runner.invoke(
        LEVER,
        other,
        identity="tech-ana",
        client=FABRIKAM,
        mode="execute",
        approval=_approval(other, FABRIKAM, verification=_verification("tech-ben")),
    )
    assert result.status == "denied" and fabrikam_state.read_bytes() == before
    ok = runner.invoke(
        LEVER,
        other,
        identity="tech-ben",
        client=FABRIKAM,
        mode="execute",
        approval=_approval(other, FABRIKAM, verification=_verification("tech-ben")),
    )
    assert ok.ok and ok.applied
    contoso_state = json.loads((tmp_path / "tenant" / f"{CONTOSO}.json").read_text(encoding="utf-8"))
    assert "restoreRequests" not in contoso_state


def test_b69_3_a_restore_test_needs_no_requester_because_it_restores_only_synthetic_test_data(tmp_path: Path) -> None:
    # The test restores into a throw-away location and hands the data to nobody; the spec says so in plain words.
    spec = SPEC.read_text(encoding="utf-8")
    assert "no requester" in spec.lower() or "hands" in spec.lower()
    assert _run(tmp_path).result == "passed"
