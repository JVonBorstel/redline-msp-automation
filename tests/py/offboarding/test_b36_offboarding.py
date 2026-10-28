"""B-36 offboarding change plan with completion proof: workflows/offboarding.

Acceptance ids B36-1 to B36-3 are defined in specs/B-36.md. Every test is offline and works on private copies of the
synthetic mock tenant in tmp_path; committed fixtures are never modified. Tests that dry-run or execute a lever start
`pwsh` (most offboarding levers are PowerShell) and skip when PowerShell 7.4+ is not installed; the verify, reconcile
and CLI tests build their audit records by hand and run everywhere.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/offboarding
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from core.audit import canonical_json, verify_chain
from core.levers import LeverRunner
from core.levers.models import Verification
from core.queue import ProposalQueue, open_queue
from workflows.offboarding import OffboardPlan, lob_checklist, plan, reconcile, record_path, summary, verify
from workflows.offboarding.__main__ import main
from workflows.offboarding.offboarding import _drafts, _facts

CONTOSO = "contoso-dental"
ANA = "ana.lopez@contosodental.example"
SAM = "sam.patel@contosodental.example"
AS_OF = "2026-10-21"
ENDS = "2026-11-04"  # AS_OF plus the 14 days in config.json
AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
VERIFIED = Verification(method="callback-on-file", by="lead-lee", at=AT, ref="CALL-3601")
needs_pwsh = pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh (PowerShell 7.4+) is not installed")
ORDER = [
    "block-sign-in",
    "revoke-sessions",
    "convert-mailbox",
    "auto-reply",
    "onedrive-grant",
    "remove-group",
    "remove-group",
    "remove-license",
]


@dataclass
class Env:
    state: Path
    queue: ProposalQueue

    @property
    def runner(self) -> LeverRunner:
        return self.queue.runner

    @property
    def tenant_dir(self) -> Path:
        return self.state / "tenant"

    @property
    def audit_path(self) -> Path:
        return self.state / "audit" / f"{CONTOSO}.jsonl"  # B-42: the client's own chain

    def edit(self, rel: str, change: Callable[[dict[str, Any]], None]) -> None:
        path = self.tenant_dir / rel
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def tenant_digest(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(self.tenant_dir.rglob("*.json")):
            digest.update(path.name.encode() + path.read_bytes())
        return digest.hexdigest()

    def records(self) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        return [json.loads(x) for x in self.audit_path.read_text(encoding="utf-8").splitlines() if x.strip()]

    def set_retention(self, ends_on: str | None, upn: str = ANA) -> None:
        def change(data: dict[str, Any]) -> None:
            for row in data["assignments"]:
                if row["userPrincipalName"] == upn:
                    row["retentionEndsOn"] = ends_on

        self.edit(f"{CONTOSO}/licenses.json", change)

    def drop_mailbox(self, upn: str = ANA) -> None:
        def change(data: dict[str, Any]) -> None:
            data["mailboxes"] = [m for m in data["mailboxes"] if m["userPrincipalName"] != upn]

        self.edit(f"{CONTOSO}/mailboxes.json", change)

    def add_mailbox(self, upn: str = ANA) -> None:
        reply = {"state": "Disabled", "internalMessage": None, "externalMessage": None, "externalAudience": "None"}
        box = {"id": "c0000000-0000-4000-8000-0000000002ff", "userPrincipalName": upn, "autoReply": reply}
        box |= {"recipientTypeDetails": "UserMailbox", "totalItemSizeGb": 1.0, "archiveStatus": "None"}
        box |= {"forwardingSmtpAddress": None, "fullAccess": [], "sendAs": []}
        self.edit(f"{CONTOSO}/mailboxes.json", lambda data: data["mailboxes"].append(box))

    def put_in_group(self, group_name: str, upn: str = ANA) -> None:
        def change(data: dict[str, Any]) -> None:
            group = next(g for g in data["value"] if g["displayName"] == group_name)
            group["members"].append({"id": "11111111-2222-4333-8444-555555555555", "userPrincipalName": upn})

        self.edit(f"{CONTOSO}/groups.json", change)

    def apply_target_state(self, upn: str = ANA, skip: tuple[str, ...] = ()) -> None:
        """Edit the tenant copy into the state the plan aims for (what the executed levers would leave behind)."""

        def user(data: dict[str, Any]) -> None:
            for u in data["users"]:
                if u["userPrincipalName"] == upn:
                    u["accountEnabled"] = False

        def sessions(data: dict[str, Any]) -> None:
            for row in data["value"]:
                if row["userPrincipalName"] == upn:
                    row["activeSessionCount"] = 0

        def mailbox(data: dict[str, Any]) -> None:
            for box in data["mailboxes"]:
                if box["userPrincipalName"] == upn:
                    box["recipientTypeDetails"] = "SharedMailbox"
                    box["autoReply"]["state"] = "Enabled"
            for drive in data["oneDrive"]:
                if drive["owner"] == upn:
                    drive["access"].append(
                        {"grantee": SAM, "grantedOn": AS_OF, "expiresOn": ENDS, "accessLevel": "SiteCollectionAdmin"}
                    )

        def groups(data: dict[str, Any]) -> None:
            for group in data["value"]:
                group["members"] = [m for m in group["members"] if m["userPrincipalName"] != upn]

        def licenses(data: dict[str, Any]) -> None:
            data["assignments"] = [a for a in data["assignments"] if a["userPrincipalName"] != upn]

        edits: dict[str, tuple[str, Callable[[dict[str, Any]], None]]] = {
            "block-sign-in": (f"{CONTOSO}.json", user),
            "revoke-sessions": (f"{CONTOSO}/sessions.json", sessions),
            "mailbox": (f"{CONTOSO}/mailboxes.json", mailbox),
            "remove-group": (f"{CONTOSO}/groups.json", groups),
            "remove-license": (f"{CONTOSO}/licenses.json", licenses),
        }
        for name, (rel, change) in edits.items():
            if name not in skip:
                self.edit(rel, change)

    def fake_plan(self, manager: str | None = SAM) -> OffboardPlan:
        """The plan for Ana with hand-written dry-run audit records, so no lever (and no pwsh) is needed."""
        facts = _facts(self.runner.tenant, CONTOSO)
        steps = _drafts(ANA, facts, date.fromisoformat(AS_OF), manager)
        for step in steps:
            if step.status == "planned":
                record = self.runner.audit.append(
                    agent="tech-ana",
                    client=CONTOSO,
                    lever=step.lever,
                    params=step.params,
                    mode="dry-run",
                    result={"status": "ok", "applied": False, "changes": []},
                )
                step.dry_run_audit_seq = int(record["seq"])
                step.status = "proposed"
        return OffboardPlan(
            CONTOSO, ANA, AS_OF, "tech-ana", None, "planned", "test plan", steps=steps, manual=[{"step": "x"}]
        )

    def fake_execute(self, built: OffboardPlan) -> None:
        """Append the applied execute record a lead-approved run of each proposed step would leave."""
        for step in built.steps:
            if step.status == "proposed":
                self.runner.audit.append(
                    agent="tech-ana",
                    client=CONTOSO,
                    lever=step.lever,
                    params=step.params,
                    mode="execute",
                    result={"status": "ok", "applied": True, "changes": []},
                    approver="lead-lee",
                )


@pytest.fixture
def env(tmp_path: Path) -> Env:
    state = tmp_path / "state"
    return Env(state, open_queue(state))


def seal(body: dict[str, Any]) -> dict[str, Any]:
    return {**body, "sha256": hashlib.sha256(canonical_json(body)).hexdigest()}


def keys(built: OffboardPlan) -> list[str]:
    return [s.key for s in built.steps]


def by_status(built: OffboardPlan, status: str) -> list[str]:
    return [s.key for s in built.steps if s.status == status]


# -- B36-1: the plan ----------------------------------------------------------------------------------------------


@needs_pwsh
def test_b36_1_plan_orders_the_steps_block_revoke_mailbox_onedrive_groups_license(env: Env) -> None:
    env.set_retention("2026-10-01")  # window over
    built = plan(env.runner, CONTOSO, ANA, "tech-ana", manager=SAM, queue=env.queue)
    assert built.outcome == "planned"
    assert keys(built) == ORDER
    assert [s.lever for s in built.steps] == [
        "user.disable",
        "user.revoke-sessions",
        "mailbox.convert-shared",
        "mailbox.set-auto-reply",
        "mailbox.grant-onedrive-manager",
        "group.remove-member",
        "group.remove-member",
        "license.remove",
    ]
    assert by_status(built, "proposed") == ORDER  # each has a dry-run diff and waits for a lead
    grant = next(s for s in built.steps if s.key == "onedrive-grant")
    assert grant.params == {"upn": ANA, "manager": SAM, "expires_on": ENDS}


@needs_pwsh
def test_b36_1_license_removal_is_dated_at_the_retention_end_and_not_proposed_early(env: Env) -> None:
    env.set_retention("2026-11-30")  # window still open on 2026-10-21
    built = plan(env.runner, CONTOSO, ANA, "tech-ana", manager=SAM, queue=env.queue)
    lic = next(s for s in built.steps if s.key == "remove-license")
    assert lic.status == "deferred" and lic.due_on == "2026-11-30" and "2026-11-30" in lic.reason
    assert lic.proposal_id is None and lic.dry_run_audit_seq is None
    assert "license.remove" not in {p.lever for p in env.queue.list()}
    assert "license.remove" not in {r["lever"] for r in env.records()}  # not even a dry-run
    # a window with no recorded end is listed too, not guessed
    env.set_retention(None)
    again = plan(env.runner, CONTOSO, ANA, "tech-ana", manager=SAM, queue=env.queue)
    lic = next(s for s in again.steps if s.key == "remove-license")
    assert lic.status == "skipped" and "no retention window" in lic.reason


@needs_pwsh
def test_b36_1_device_steps_are_listed_manual_until_w6(env: Env) -> None:
    built = plan(env.runner, CONTOSO, ANA, "tech-ana", manager=SAM, queue=env.queue)
    assert built.manual and all(m["status"] == "manual until W6" for m in built.manual)
    assert not {s.key for s in built.steps} & {"device", "wipe", "retire"}  # no lever for a device step
    assert not any("device" in s.lever for s in built.steps)


def test_b36_1_lob_apps_are_a_checklist_from_the_client_data(tmp_path: Path) -> None:
    items = lob_checklist(CONTOSO)
    assert [i["app"] for i in items] == ["Practice scheduling app (synthetic)", "Imaging viewer (synthetic)"]
    assert all(i["done"] is False and "synthetic" in i["source"] for i in items)
    custom = tmp_path / "lob.json"
    custom.write_text(json.dumps({"clients": {CONTOSO: ["Only app"]}}), encoding="utf-8")
    assert [i["app"] for i in lob_checklist(CONTOSO, custom)] == ["Only app"]
    assert lob_checklist("litware-legal") == []  # empty list stays empty
    assert lob_checklist("no-such-client") == []


@needs_pwsh
def test_b36_1_every_write_step_is_a_pending_proposal_and_nothing_is_executed(env: Env) -> None:
    env.set_retention("2026-10-01")
    before = env.tenant_digest()
    built = plan(env.runner, CONTOSO, ANA, "tech-ana", manager=SAM, queue=env.queue)
    pending = env.queue.list("pending")
    assert len(pending) == len(ORDER) and built.executed is False and summary(built)["executed"] is False
    assert {p.id for p in pending} == {s.proposal_id for s in built.steps}
    assert all(p.requested_by == "tech-ana" and p.client == CONTOSO for p in pending)
    assert env.tenant_digest() == before  # a plan changes nothing
    assert not [r for r in env.records() if r["mode"] == "execute"]


@needs_pwsh
def test_b36_1_every_step_has_a_dry_run_audit_record(env: Env) -> None:
    env.set_retention("2026-10-01")
    built = plan(env.runner, CONTOSO, ANA, "tech-ana", manager=SAM, queue=env.queue)
    by_seq = {r["seq"]: r for r in env.records()}
    for step in built.steps:
        record = by_seq[step.dry_run_audit_seq]
        assert (record["lever"], record["mode"], record["client"]) == (step.lever, "dry-run", CONTOSO)
        assert record["result"]["applied"] is False
    assert verify_chain(env.audit_path).ok


@needs_pwsh
def test_b36_1_a_refused_dry_run_is_listed_not_dropped(env: Env) -> None:
    env.put_in_group("Billing Administrators")  # on the client's privileged list: group.remove-member refuses
    built = plan(env.runner, CONTOSO, ANA, "tech-ana", manager=SAM, queue=env.queue)
    refused = [s for s in built.steps if s.status == "refused"]
    assert len(refused) == 1 and refused[0].key == "remove-group" and "refused" in refused[0].reason
    assert refused[0].proposal_id is None and refused[0].dry_run_audit_seq is not None
    assert "Billing Administrators" in refused[0].label
    assert refused[0].proposal_id not in {p.id for p in env.queue.list()}


def test_b36_1_unknown_user_or_client_gives_a_plain_refusal(env: Env) -> None:
    gone = plan(env.runner, CONTOSO, "nobody@contosodental.example", "tech-ana", queue=env.queue)
    assert gone.outcome == "refused" and "is not a user of contoso-dental" in gone.reason and gone.steps == []
    nowhere = plan(env.runner, "no-such-client", ANA, "tech-ana", queue=env.queue)
    assert nowhere.outcome == "refused" and "no readable tenant state" in nowhere.reason
    assert env.queue.list() == () and env.records() == []  # nothing was dry-run or queued


@needs_pwsh
def test_b36_1_no_mailbox_no_groups_no_licenses_no_manager_give_plain_empty_states(env: Env) -> None:
    env.drop_mailbox()
    env.apply_target_state(skip=("block-sign-in", "revoke-sessions", "mailbox"))  # leaves no group and no license
    built = plan(env.runner, CONTOSO, ANA, "tech-ana", queue=env.queue)
    assert keys(built) == ["block-sign-in", "revoke-sessions", "convert-mailbox", "auto-reply", "onedrive-grant"]
    assert [s.status for s in built.steps[2:]] == ["skipped"] * 3
    assert all("no mailbox" in s.reason for s in built.steps[2:])
    assert any("no group" in n for n in built.notes) and any("no license" in n for n in built.notes)
    # a person with a mailbox but no manager named: only the OneDrive grant is skipped, with the reason
    env.add_mailbox()
    nobody = plan(env.runner, CONTOSO, ANA, "tech-ana", queue=env.queue)
    grant = next(s for s in nobody.steps if s.key == "onedrive-grant")
    assert grant.status == "skipped" and "no manager" in grant.reason


# -- B36-2: verify and the completion record -----------------------------------------------------------------------


def test_b36_2_verify_writes_a_completion_record_when_every_step_is_met(env: Env, tmp_path: Path) -> None:
    env.set_retention("2026-10-01")
    built = env.fake_plan()
    env.apply_target_state()
    record = verify(built.to_dict(), env.runner.tenant, env.audit_path, out_dir=tmp_path / "out")
    assert record["complete"] is True and record["not_met"] == [] and record["pending_retention"] == []
    assert [s["key"] for s in record["steps"]] == ORDER
    assert all(s["state"] == "met" for s in record["steps"])
    saved = json.loads(record_path(tmp_path / "out", CONTOSO, ANA, "completion").read_text(encoding="utf-8"))
    assert saved == record and record["sha256"] == seal({k: v for k, v in record.items() if k != "sha256"})["sha256"]
    assert record["manual_until_w6"] == built.manual and record["audit_head"]["seq"] == len(env.records())


def test_b36_2_a_step_not_in_target_state_is_listed_and_complete_is_false(env: Env) -> None:
    env.set_retention("2026-10-01")
    built = env.fake_plan()
    env.apply_target_state(skip=("revoke-sessions", "remove-group"))
    record = verify(built.to_dict(), env.runner.tenant, env.audit_path)
    assert record["complete"] is False
    listed = [n["step"] for n in record["not_met"]]
    assert listed[0] == "Revoke sign-in sessions" and len(listed) == 3  # sessions and both groups
    assert {n["reason"] for n in record["not_met"]} == {"3 active sessions", "still a member"}
    assert [s["state"] for s in record["steps"]].count("met") == len(ORDER) - 3
    # a step the plan skipped is listed too, not hidden
    nobody = env.fake_plan(manager=None)
    skipped = verify(nobody.to_dict(), env.runner.tenant, env.audit_path)
    assert any("no manager" in n["reason"] for n in skipped["not_met"]) and skipped["complete"] is False


def test_b36_2_verify_changes_no_tenant_byte(env: Env, tmp_path: Path) -> None:
    env.set_retention("2026-10-01")
    built = env.fake_plan()
    env.apply_target_state(skip=("remove-group",))
    tenant, audit = env.tenant_digest(), env.audit_path.read_bytes()
    verify(built.to_dict(), env.runner.tenant, env.audit_path, out_dir=tmp_path / "out")
    assert env.tenant_digest() == tenant and env.audit_path.read_bytes() == audit


def test_b36_2_license_inside_retention_is_pending_not_failed(env: Env) -> None:
    env.set_retention("2026-11-30")
    built = env.fake_plan()
    env.apply_target_state(skip=("remove-license",))
    record = verify(built.to_dict(), env.runner.tenant, env.audit_path)
    lic = next(s for s in record["steps"] if s["key"] == "remove-license")
    assert lic["state"] == "pending-retention" and "2026-11-30" in lic["observed"]
    assert record["not_met"] == [] and len(record["pending_retention"]) == 1
    assert record["complete"] is False  # not finished until the window ends
    later = verify(built.to_dict(), env.runner.tenant, env.audit_path, as_of="2026-12-01")
    assert [n["step"] for n in later["not_met"]] == [lic["label"]]  # window over and still assigned: now a failure


def test_b36_2_a_user_without_a_mailbox_is_not_applicable_not_a_failure(env: Env) -> None:
    env.drop_mailbox()
    built = env.fake_plan()
    env.apply_target_state(skip=("mailbox",))
    record = verify(built.to_dict(), env.runner.tenant, env.audit_path)
    states = {s["key"]: s["state"] for s in record["steps"]}
    assert states["convert-mailbox"] == states["auto-reply"] == states["onedrive-grant"] == "not-applicable"


# -- B36-3: the record reconciles with the audit -------------------------------------------------------------------


def done_record(env: Env, tmp_path: Path) -> tuple[OffboardPlan, dict[str, Any]]:
    env.set_retention("2026-10-01")
    built = env.fake_plan()
    env.apply_target_state()
    env.fake_execute(built)
    return built, verify(built.to_dict(), env.runner.tenant, env.audit_path, out_dir=tmp_path / "out")


def test_b36_3_completion_record_reconciles_with_the_plans_audit_records(env: Env, tmp_path: Path) -> None:
    built, record = done_record(env, tmp_path)
    result = reconcile(record, env.audit_path)
    assert result == {"ok": True, "problems": [], "checked": len(built.steps)}
    assert record["audit_seqs"] == [s.dry_run_audit_seq for s in built.steps]


@needs_pwsh
def test_b36_3_a_real_plan_approved_by_a_lead_verifies_complete_and_reconciles(env: Env, tmp_path: Path) -> None:
    env.set_retention("2026-10-01")
    built = plan(env.runner, CONTOSO, ANA, "tech-ana", manager=SAM, queue=env.queue)
    for step in built.steps:
        assert step.proposal_id is not None
        decision = env.queue.decide(step.proposal_id, "lead-lee", True, VERIFIED)
        assert decision.proposal.status == "executed", (step.key, decision.proposal.status)
    record = verify(built.to_dict(), env.runner.tenant, env.audit_path, out_dir=tmp_path / "out")
    assert record["complete"] is True and record["not_met"] == []
    assert reconcile(record, env.audit_path)["ok"] is True
    assert verify_chain(env.audit_path).ok


def test_b36_3_a_tampered_record_or_audit_chain_fails_reconcile(env: Env, tmp_path: Path) -> None:
    _, record = done_record(env, tmp_path)
    edited = {**record, "complete": False}  # same content but one flag changed, hash not updated
    result = reconcile(edited, env.audit_path)
    assert result["ok"] is False and "sha256" in result["problems"][0]
    lines = env.audit_path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace("tech-ana", "tech-bob")
    env.audit_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    broken = reconcile(record, env.audit_path)
    assert broken["ok"] is False and broken["checked"] == 0
    assert any("audit chain does not verify" in p for p in broken["problems"])


def test_b36_3_a_missing_audit_seq_is_reported(env: Env, tmp_path: Path) -> None:
    _, record = done_record(env, tmp_path)
    body = {k: v for k, v in record.items() if k != "sha256"}
    body["steps"][0]["dry_run_audit_seq"] = 9999
    result = reconcile(seal(body), env.audit_path)
    assert result["ok"] is False and any("audit seq 9999 is missing" in p for p in result["problems"])
    body["steps"][0]["dry_run_audit_seq"] = body["steps"][1]["dry_run_audit_seq"]  # another step's record
    other = reconcile(seal(body), env.audit_path)
    assert any("is not the dry-run of this step" in p for p in other["problems"])


def test_b36_3_an_applied_step_without_an_execute_record_is_reported(env: Env, tmp_path: Path) -> None:
    env.set_retention("2026-10-01")
    built = env.fake_plan()
    env.apply_target_state()  # the tenant is in the target state but no lever execute was audited
    record = verify(built.to_dict(), env.runner.tenant, env.audit_path)
    result = reconcile(record, env.audit_path)
    assert result["ok"] is False and len(result["problems"]) == len(ORDER)
    assert all("no applied audit record" in p for p in result["problems"])


def test_b36_3_cli_exit_codes(env: Env, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    common = ["--client", CONTOSO, "--state", str(env.state)]
    assert main(["plan", "nobody@contosodental.example", *common]) == 2  # refused
    assert "is not a user" in json.loads(capsys.readouterr().out)["reason"]
    assert main(["verify", ANA, *common]) == 2  # no plan file yet
    assert "cannot read" in capsys.readouterr().err
    assert main(["reconcile", ANA, *common]) == 2  # no completion record yet
    capsys.readouterr()

    env.set_retention("2026-10-01")
    built = env.fake_plan()
    out = env.state / "offboarding"
    out.mkdir(parents=True, exist_ok=True)
    record_path(out, CONTOSO, ANA, "plan").write_text(json.dumps(summary(built)), encoding="utf-8")
    assert main(["verify", ANA, *common]) == 2  # nothing done yet: steps listed, exit 2
    assert json.loads(capsys.readouterr().out)["complete"] is False
    env.apply_target_state()
    env.fake_execute(built)
    assert main(["verify", ANA, *common]) == 0
    assert json.loads(capsys.readouterr().out)["complete"] is True
    assert main(["reconcile", ANA, *common]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    lines = env.audit_path.read_text(encoding="utf-8").splitlines()
    env.audit_path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")  # a record cut from the end
    assert main(["reconcile", ANA, *common]) == 2
