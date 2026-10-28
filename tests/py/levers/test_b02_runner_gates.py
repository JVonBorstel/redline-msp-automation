"""B-02 runner gates: pause switch (C-31, IR-2), requester verification (C-30), contact-detail masking (DR-02).

Acceptance ids B02-1 to B02-4 are defined in specs/B-02.md. Every test is offline and works on a private copy of
the synthetic mock tenant and its own audit log under tmp_path; committed files are never modified. Phone numbers
are read from the fixture at runtime, never typed here.
Run: uv run --frozen pytest tests/py/levers
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from core.audit import AuditLog, verify_chain
from core.identity import Identity, IdentityStore, Role
from core.levers import DEFAULT_TENANT_DIR, Approval, Change, LeverDef, LeverRunner, MockTenant, Registry
from core.levers.__main__ import main as cli_main
from core.levers.handlers import HANDLERS
from core.levers.models import Verification
from core.levers.pause import PAUSES_FILE, PauseStore
from core.levers.runner import MASKED, VERIFICATION_NEEDED, mask_change
from core.queue import open_queue
from core.queue.__main__ import demo_proposals
from ui.app import App

CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
ANA = "ana.lopez@contosodental.example"
JAMIE = "jamie.chen@contosodental.example"
MORGAN = "morgan.reyes@fabrikamcapital.example"
DISABLE_JAMIE: dict[str, Any] = {"upn": JAMIE, "reason": "Left the practice (ticket T-1002)"}
IDENTITY_LEVERS = ("user.reset-mfa", "user.disable")
PARAMS = {"user.reset-mfa": {"upn": ANA}, "user.disable": DISABLE_JAMIE}
AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
VERIFIED = Verification(method="callback-on-file", by="lead-lee", at=AT, ref="CALL-3101")
PHONE_SHAPE = re.compile(r"\+\d[\d\s().-]{5,}\d")
REASON = "suspected help-desk social engineering, IR-2"


@dataclass
class Env:
    runner: LeverRunner
    tenant_dir: Path
    audit_path: Path

    def records(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines()]

    def last(self) -> dict[str, Any]:
        return self.records()[-1]

    def raw_log(self) -> str:
        return self.audit_path.read_text(encoding="utf-8")

    def tenant_bytes(self, client: str = CONTOSO) -> bytes:
        return (self.tenant_dir / f"{client}.json").read_bytes()

    def chain_ok(self) -> bool:
        return verify_chain(self.audit_path, self.audit_path.with_name("audit.jsonl.head")).ok


def make_env(tmp_path: Path, registry: Registry | None = None, identities: IdentityStore | None = None) -> Env:
    tenant_dir = tmp_path / "tenant"
    if not tenant_dir.exists():
        shutil.copytree(DEFAULT_TENANT_DIR, tenant_dir)
    audit_path = tmp_path / "audit.jsonl"
    runner = LeverRunner(
        registry or Registry.load(), identities or IdentityStore.load(), MockTenant(tenant_dir), AuditLog(audit_path)
    )
    return Env(runner, tenant_dir, audit_path)


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return make_env(tmp_path)


def approval(
    lever: str, params: Mapping[str, Any], verification: Verification | None = VERIFIED, client: str = CONTOSO
) -> Approval:
    return Approval(approver="lead-lee", lever=lever, client=client, params=dict(params), verification=verification)


def fixture_phone_numbers() -> list[str]:
    numbers: list[str] = []
    for path in DEFAULT_TENANT_DIR.glob("*.json"):
        for user in json.loads(path.read_text(encoding="utf-8")).get("users", []):
            for method in user.get("authentication", {}).get("methods", []):
                if "phoneNumber" in method:
                    numbers.append(method["phoneNumber"])
    return numbers


def two_lead_identities() -> IdentityStore:
    return IdentityStore(
        [
            Identity(id="tech-ana", display_name="Ana", role=Role.TECHNICIAN, clients=(CONTOSO,)),
            Identity(id="lead-lee", display_name="Lee", role=Role.LEAD, clients=(CONTOSO, FABRIKAM)),
            Identity(id="lead-zoe", display_name="Zoe", role=Role.LEAD, clients=(FABRIKAM,)),
            Identity(id="tech-ben", display_name="Ben", role=Role.TECHNICIAN, clients=(FABRIKAM,)),
        ]
    )


# -- B02-1 pause switch ------------------------------------------------------------------------


@pytest.mark.parametrize("lever", ["user.reset-mfa", "user.disable", "ticket.get"])
def test_b02_1_global_pause_denies_dry_run_and_execute_with_the_reason(env: Env, lever: str) -> None:
    params = PARAMS.get(lever, {"ticket_id": "T-1001"})
    before = env.tenant_bytes()
    assert env.runner.pause(lever, "lead-lee", REASON).ok

    for mode in ("dry-run", "execute"):
        result = env.runner.invoke(lever, params, "tech-ana", CONTOSO, mode=mode, approval=approval(lever, params))
        assert (result.status, result.reason) == ("denied", f"lever paused by lead-lee: {REASON}")
        record = env.last()
        assert (record["mode"], record["result"]["status"], record["result"]["reason"]) == (
            mode,
            "denied",
            f"lever paused by lead-lee: {REASON}",
        )
        assert result.audit_seq == record["seq"]
    assert env.tenant_bytes() == before
    assert env.chain_ok()


def test_b02_1_client_pause_stops_only_that_client(env: Env) -> None:
    assert env.runner.pause("user.reset-mfa", "lead-lee", REASON, client=CONTOSO).ok
    denied = env.runner.invoke("user.reset-mfa", {"upn": ANA}, "tech-ana", CONTOSO)
    other = env.runner.invoke("user.reset-mfa", {"upn": MORGAN}, "tech-ben", FABRIKAM)
    assert denied.reason == f"lever paused by lead-lee: {REASON}"
    assert other.ok and other.mode == "dry-run"


def test_b02_1_global_pause_wins_over_a_client_pause(env: Env) -> None:
    assert env.runner.pause("user.disable", "lead-lee", "client pause", client=CONTOSO).ok
    assert env.runner.pause("user.disable", "lead-lee", "global pause").ok
    result = env.runner.invoke("user.disable", DISABLE_JAMIE, "tech-ana", CONTOSO)
    assert result.reason == "lever paused by lead-lee: global pause"


def test_b02_1_pause_and_resume_each_write_one_audit_record(env: Env) -> None:
    paused = env.runner.pause("user.reset-mfa", "lead-lee", REASON)
    assert len(env.records()) == 1
    record = env.last()
    assert (record["agent"], record["client"], record["lever"], record["mode"]) == (
        "lead-lee",
        None,
        "user.reset-mfa",
        "pause",
    )
    assert record["params"] == {"scope": "all clients", "reason": REASON}
    assert (record["result"]["status"], record["result"]["applied"], record["approver"]) == ("ok", True, None)
    assert paused.audit_seq == 1

    resumed = env.runner.resume("user.reset-mfa", "lead-lee", "verified the caller list, IR-4")
    assert len(env.records()) == 2 and resumed.ok and resumed.audit_seq == 2
    assert (env.last()["mode"], env.last()["result"]["applied"]) == ("resume", True)
    assert env.chain_ok()


def test_b02_1_resume_lets_the_lever_run_again(env: Env) -> None:
    env.runner.pause("user.reset-mfa", "lead-lee", REASON, client=CONTOSO)
    env.runner.resume("user.reset-mfa", "lead-lee", "all clear", client=CONTOSO)
    assert env.runner.invoke("user.reset-mfa", {"upn": ANA}, "tech-ana", CONTOSO).ok
    assert env.runner.pauses.all() == ()


def test_b02_1_pausing_needs_no_approval_and_no_second_person(env: Env) -> None:
    # A lead acting alone, with no approval record, stops the lever immediately (IR-2).
    result = env.runner.pause("user.disable", "lead-lee", REASON)
    assert result.ok and result.applied and result.approver is None
    assert env.runner.pauses.exact("user.disable", None) is not None


@pytest.mark.parametrize(
    ("identity", "reason"),
    [
        ("tech-ana", "only a lead may pause or resume a lever (tech-ana is technician)"),
        ("triage-bot", "only a lead may pause or resume a lever (triage-bot is agent)"),
        ("mallory", "unknown identity 'mallory'"),
    ],
)
@pytest.mark.parametrize("action", ["pause", "resume"])
def test_b02_1_only_a_lead_may_pause_or_resume(env: Env, identity: str, reason: str, action: str) -> None:
    if action == "resume":
        env.runner.pause("user.disable", "lead-lee", REASON)
    before = env.runner.pauses.all()
    act = env.runner.pause if action == "pause" else env.runner.resume
    result = act("user.disable", identity, REASON)
    assert (result.status, result.reason) == ("denied", reason)
    assert (env.last()["agent"], env.last()["mode"], env.last()["result"]["status"]) == (identity, action, "denied")
    assert env.runner.pauses.all() == before


def test_b02_1_a_client_pause_needs_a_lead_scoped_to_that_client(tmp_path: Path) -> None:
    env = make_env(tmp_path, identities=two_lead_identities())
    result = env.runner.pause("user.reset-mfa", "lead-zoe", REASON, client=CONTOSO)
    assert (result.status, result.reason) == ("denied", "lead-zoe is not scoped to client 'contoso-dental'")
    assert env.last()["client"] == CONTOSO and env.runner.pauses.all() == ()
    # Any lead may pull the global kill switch (IR-2: the on-call lead, immediately).
    assert env.runner.pause("user.reset-mfa", "lead-zoe", REASON).ok


@pytest.mark.parametrize(
    ("lever", "reason", "message"),
    [
        ("tenant.wipe", REASON, "lever 'tenant.wipe' is not registered"),
        ("user.disable", "", "a pause needs a one-line reason of 1-200 characters and a valid client id"),
        (
            "user.disable",
            "line one\nline two",
            "a pause needs a one-line reason of 1-200 characters and a valid client id",
        ),
        ("user.disable", "x" * 201, "a pause needs a one-line reason of 1-200 characters and a valid client id"),
    ],
)
def test_b02_1_bad_pause_requests_are_denied_and_audited(env: Env, lever: str, reason: str, message: str) -> None:
    result = env.runner.pause(lever, "lead-lee", reason)
    assert (result.status, result.reason) == ("denied", message)
    assert env.last()["result"]["status"] == "denied" and env.runner.pauses.all() == ()


def test_b02_1_pausing_twice_keeps_the_first_pause_and_resuming_nothing_is_denied(env: Env) -> None:
    env.runner.pause("user.disable", "lead-lee", "first")
    again = env.runner.pause("user.disable", "lead-lee", "second")
    assert again.ok and not again.applied and again.reason == "already paused by lead-lee: first"
    assert [p.reason for p in env.runner.pauses.all()] == ["first"]
    missing = env.runner.resume("kb.search", "lead-lee", "nothing to lift")
    assert (missing.status, missing.reason) == ("denied", "kb.search is not paused for all clients")


def test_b02_1_runners_on_the_same_state_share_pauses(tmp_path: Path) -> None:
    # The CLI, the queue and the page each build their own runner on one state folder.
    first, second = make_env(tmp_path), make_env(tmp_path)
    first.runner.pause("user.reset-mfa", "lead-lee", REASON)
    assert (tmp_path / PAUSES_FILE).exists()
    assert second.runner.invoke("user.reset-mfa", {"upn": ANA}, "tech-ana", CONTOSO).status == "denied"


def test_b02_1_an_unreadable_pause_file_fails_closed(env: Env) -> None:
    (env.audit_path.parent / PAUSES_FILE).write_text("{not json", encoding="utf-8")
    result = env.runner.invoke("ticket.get", {"ticket_id": "T-1001"}, "tech-ana", CONTOSO)
    assert result.status == "denied" and result.reason.startswith("lever pause state cannot be read, failing closed")
    assert env.last()["result"]["status"] == "denied"


def test_b02_1_cli_pause_listing_and_resume(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    state = ["--state", str(tmp_path)]
    assert (
        cli_main([*state, "pause", "user.reset-mfa", "--client", CONTOSO, "--as", "lead-lee", "--reason", REASON]) == 0
    )
    assert cli_main([*state, "paused"]) == 0
    assert f"user.reset-mfa   client {CONTOSO}" in capsys.readouterr().out
    invoke = [*state, "invoke", "user.reset-mfa", "--as", "tech-ana", "--client", CONTOSO, "-p", f"upn={ANA}"]
    assert cli_main(invoke) == 1
    assert f"lever paused by lead-lee: {REASON}" in capsys.readouterr().out
    assert cli_main([*state, "pause", "user.reset-mfa", "--as", "tech-ana", "--reason", REASON]) == 1
    assert cli_main([*state, "resume", "user.reset-mfa", "--client", CONTOSO, "--as", "lead-lee"]) == 0
    assert cli_main(invoke) == 0
    assert cli_main([*state, "paused"]) == 0
    assert "no levers are paused" in capsys.readouterr().out
    # B-42: one chain per client; the refused all-clients pause (no client) goes to the MSP chain.
    audit_dir = tmp_path / "audit"
    contoso = [json.loads(x) for x in (audit_dir / f"{CONTOSO}.jsonl").read_text(encoding="utf-8").splitlines()]
    msp = [json.loads(x) for x in (audit_dir / "_msp.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["mode"] for r in contoso] == ["pause", "dry-run", "resume", "dry-run"]
    assert [r["mode"] for r in msp] == ["pause"]
    for name in (CONTOSO, "_msp"):
        assert verify_chain(audit_dir / f"{name}.jsonl", audit_dir / f"{name}.jsonl.head").ok


def test_b02_1_pause_store_rejects_an_unknown_file_version(tmp_path: Path) -> None:
    store = PauseStore(tmp_path / PAUSES_FILE)
    (tmp_path / PAUSES_FILE).write_text(json.dumps({"version": 2, "pauses": []}), encoding="utf-8")
    with pytest.raises(Exception, match="unreadable"):
        store.all()


# -- B02-2 requester verification ---------------------------------------------------------------


@pytest.mark.parametrize("lever", IDENTITY_LEVERS)
def test_b02_2_execute_without_verification_is_denied_and_audited(env: Env, lever: str) -> None:
    before = env.tenant_bytes()
    result = env.runner.invoke(
        lever, PARAMS[lever], "tech-ana", CONTOSO, mode="execute", approval=approval(lever, PARAMS[lever], None)
    )
    assert result.status == "denied" and result.reason == f"{lever} {VERIFICATION_NEEDED}"
    assert result.reason.endswith("needs a recorded requester verification (C-30)")
    record = env.last()
    assert (record["mode"], record["result"]["status"], record["result"]["applied"]) == ("execute", "denied", False)
    assert "verification" not in record["result"]
    assert env.tenant_bytes() == before


@pytest.mark.parametrize("lever", IDENTITY_LEVERS)
def test_b02_2_with_a_verification_the_record_carries_method_by_and_at(env: Env, lever: str) -> None:
    result = env.runner.invoke(
        lever, PARAMS[lever], "tech-ana", CONTOSO, mode="execute", approval=approval(lever, PARAMS[lever])
    )
    assert result.ok and result.applied and result.approver == "lead-lee"
    verification = env.last()["result"]["verification"]
    assert verification == {
        "method": "callback-on-file",
        "by": "lead-lee",
        "at": "2026-10-20T09:00:00Z",
        "ref": "CALL-3101",
    }
    assert env.last()["approver"] == "lead-lee"


def test_b02_2_dry_run_proposals_need_no_verification(env: Env) -> None:
    # Agents and technicians can still propose; verification is asked of the approval, before execute.
    assert env.runner.invoke("user.reset-mfa", {"upn": ANA}, "triage-bot", CONTOSO).ok


@pytest.mark.parametrize(
    ("verification", "reason"),
    [
        (Verification(method="in-person", by="mallory", at=AT), "verification is by unknown identity 'mallory'"),
        (
            Verification(method="in-person", by="tech-ben", at=AT),
            "verifier tech-ben is not scoped to client 'contoso-dental'",
        ),
        (
            Verification(method="in-person", by="lead-lee", at=datetime.now(UTC) + timedelta(hours=1)),
            "verification time is in the future",
        ),
    ],
)
def test_b02_2_a_verification_must_be_by_a_scoped_identity_and_not_in_the_future(
    env: Env, verification: Verification, reason: str
) -> None:
    params = {"upn": ANA}
    result = env.runner.invoke(
        "user.reset-mfa",
        params,
        "tech-ana",
        CONTOSO,
        mode="execute",
        approval=approval("user.reset-mfa", params, verification),
    )
    assert (result.status, result.reason) == ("denied", reason)
    assert env.last()["result"]["status"] == "denied"


def test_b02_2_the_approval_checks_still_come_first(env: Env) -> None:
    # Four-eyes is not weakened by a verification record: a self-approval is denied for its own reason.
    bad = Approval(
        approver="lead-lee", lever="user.disable", client=CONTOSO, params=DISABLE_JAMIE, verification=VERIFIED
    )
    result = env.runner.invoke("user.disable", DISABLE_JAMIE, "lead-lee", CONTOSO, mode="execute", approval=bad)
    assert result.reason == "requester cannot approve their own action (four-eyes rule)"


def _plain_write_registry() -> Registry:
    levers = [
        LeverDef.model_validate(
            {
                "name": "test.flag",
                "description": "A write lever without a verification rule (test only).",
                "client_scope": "any",
                "required_role": "technician",
                "class": "write",
                "approval": "lead",
                "params": {},
                "dry_run": True,
                "timeout_s": 2,
                "risk_class": "R1",
            }
        )
    ]

    def flag(state: dict[str, Any], params: Mapping[str, Any]) -> Any:
        state["flag"] = True
        return {"flag": True}

    return Registry(levers, {"test.flag": flag})


def test_b02_2_a_lever_without_the_rule_executes_without_verification(tmp_path: Path) -> None:
    env = make_env(tmp_path, registry=_plain_write_registry())
    result = env.runner.invoke(
        "test.flag", {}, "tech-ana", CONTOSO, mode="execute", approval=approval("test.flag", {}, None)
    )
    assert result.ok and result.applied
    assert "verification" not in env.last()["result"]


def test_b02_2_cli_verified_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = ["--state", str(tmp_path), "invoke", "user.disable", "--as", "tech-ana", "--client", CONTOSO]
    base += ["-p", f"upn={JAMIE}", "-p", "reason=Left the practice", "--execute"]
    assert cli_main([*base, "--approved-by", "lead-lee"]) == 1
    assert VERIFICATION_NEEDED in capsys.readouterr().out
    assert cli_main([*base, "--verified", "in-person"]) == 2  # a verification is part of an approval
    assert cli_main([*base, "--approved-by", "lead-lee", "--verified", "finding-reference"]) == 2  # needs a ref
    capsys.readouterr()
    assert cli_main([*base, "--approved-by", "lead-lee", "--verified", "in-person", "--verified-by", "tech-ana"]) == 0
    record = json.loads((tmp_path / "audit" / f"{CONTOSO}.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert (record["result"]["verification"]["method"], record["result"]["verification"]["by"]) == (
        "in-person",
        "tech-ana",
    )


def test_b02_2_queue_path_with_and_without_a_verification(tmp_path: Path) -> None:
    # The explicit path B-03's page uses: an approval that carries a verification record executes (demo step 6).
    queue = open_queue(tmp_path)
    for proposal in demo_proposals():
        queue.add(proposal)
    mfa, stale = demo_proposals()[0], demo_proposals()[1]
    unverified = queue.decide(stale.id, "lead-lee", approve=True)
    assert unverified.proposal.status == "failed"
    assert unverified.result is not None and VERIFICATION_NEEDED in unverified.result.reason
    verified = queue.decide(mfa.id, "lead-lee", approve=True, verification=VERIFIED)
    assert verified.proposal.status == "executed"
    contoso_log = (tmp_path / "audit" / f"{CONTOSO}.jsonl").read_text(encoding="utf-8")
    record = [json.loads(x) for x in contoso_log.splitlines()][-1]
    assert record["result"]["verification"]["method"] == "callback-on-file"


def test_b02_2_page_bridge_records_the_method_and_refuses_unknown_ones(tmp_path: Path) -> None:
    queue = open_queue(tmp_path)
    for proposal in demo_proposals():
        queue.add(proposal)
    app = App(queue)
    form = {"host": "127.0.0.1:8765", "content-type": "application/x-www-form-urlencoded"}

    def post(act: str, verified: str | None) -> int:
        fields = {"csrf": app.csrf_token, "actor": "lead-lee", "act": act}
        if verified is not None:
            fields["verified"] = verified
        return app.handle("POST", "/decide", form, urlencode(fields).encode()).status

    mfa, stale, fab = demo_proposals()
    assert post(f"approve:{mfa.id}", "a-friendly-voice") == 400
    assert queue.get(mfa.id) is not None and queue.get(mfa.id).status == "pending"  # type: ignore[union-attr]
    # B-03 (B03-2): the page now refuses an unverified approval itself; the proposal stays pending.
    assert post(f"approve:{stale.id}", None) == 400
    assert queue.get(stale.id).status == "pending"  # type: ignore[union-attr]
    assert post(f"approve:{fab.id}", "manager-confirmed") == 303
    assert queue.get(fab.id).status == "executed"  # type: ignore[union-attr]
    fabrikam_log = (tmp_path / "audit" / f"{FABRIKAM}.jsonl").read_text(encoding="utf-8")
    record = [json.loads(x) for x in fabrikam_log.splitlines()][-1]
    assert (record["result"]["verification"]["method"], record["result"]["verification"]["by"]) == (
        "manager-confirmed",
        "lead-lee",
    )


# -- B02-3 contact-detail masking -----------------------------------------------------------------


def _assert_no_contact_details(env: Env) -> None:
    raw = env.raw_log()
    assert not PHONE_SHAPE.search(raw)
    for number in fixture_phone_numbers():
        assert number not in raw
    for record in env.records():
        for change in record["result"]["changes"]:
            for side in (change["before"], change["after"]):
                for method in _methods_in(change["path"], side):
                    assert set(method) <= {"@odata.type", "id"}, method


def _methods_in(path: str, value: Any) -> list[dict[str, Any]]:
    if "/authentication/methods/" in path and isinstance(value, dict):
        return [value] if path.count("/") == 5 else []
    if isinstance(value, dict):
        found: list[dict[str, Any]] = []
        for key, item in value.items():
            if key == "methods" and isinstance(item, list):
                found += [m for m in item if isinstance(m, dict)]
            else:
                found += _methods_in("", item)
        return found
    return []


def test_b02_3_fixture_has_phone_numbers_to_mask() -> None:
    assert fixture_phone_numbers(), "the Contoso fixture should hold a phone method, or this suite proves nothing"


def test_b02_3_reset_mfa_execute_leaves_no_contact_detail_in_the_audit(env: Env) -> None:
    preview = env.runner.invoke("user.reset-mfa", {"upn": ANA}, "tech-ana", CONTOSO)
    done = env.runner.invoke(
        "user.reset-mfa",
        {"upn": ANA},
        "tech-ana",
        CONTOSO,
        mode="execute",
        approval=approval("user.reset-mfa", {"upn": ANA}),
    )
    assert preview.ok and done.ok and done.applied
    _assert_no_contact_details(env)
    removed = [c for c in env.last()["result"]["changes"] if c["op"] == "remove"]
    assert removed and all(set(c["before"]) == {"@odata.type", "id"} for c in removed)
    assert any(c["before"]["@odata.type"].endswith("phoneAuthenticationMethod") for c in removed)
    assert env.chain_ok()


def test_b02_3_the_caller_still_sees_the_full_dry_run_diff(env: Env) -> None:
    preview = env.runner.invoke("user.reset-mfa", {"upn": ANA}, "tech-ana", CONTOSO)
    phone_changes = [c for c in preview.diff if isinstance(c.before, dict) and "phoneNumber" in c.before]
    assert phone_changes and phone_changes[0].before["phoneNumber"] in fixture_phone_numbers()
    assert any(isinstance(c.before, dict) and "displayName" in c.before for c in preview.diff)
    audited = env.last()["result"]["changes"]
    assert len(audited) == len(preview.diff)
    assert [c["path"] for c in audited] == [c.path for c in preview.diff]


def test_b02_3_ticket_get_leaves_no_ticket_field_in_the_audit(env: Env) -> None:
    result = env.runner.invoke("ticket.get", {"ticket_id": "T-1001"}, "tech-ana", CONTOSO)
    assert result.ok and isinstance(result.data, dict) and result.data["id"] == "T-1001"
    raw = env.raw_log()
    record = env.last()
    assert record["params"] == {"ticket_id": "T-1001"} and record["result"]["changes"] == []
    for key, value in result.data.items():
        if key == "id":
            continue
        if isinstance(value, str) and len(value) > 3:
            assert value not in raw, key


@pytest.mark.parametrize(
    ("change", "expected_before", "expected_after"),
    [
        (
            Change(
                op="replace",
                path="/users/u1/authentication/methods/m1/phoneNumber",
                before="+1 555 0000",
                after="+1 555 9999",
            ),
            MASKED,
            MASKED,
        ),
        (
            Change(op="replace", path="/users/u1/authentication/methods/m1/id", before="m1", after="m2"),
            "m1",
            "m2",
        ),
        (Change(op="add", path="/users/u1/mobilePhone", after="+44 20 7946 0000"), None, MASKED),
        (Change(op="replace", path="/users/u1/note", before="call +1 (555) 010-0000", after="ok"), MASKED, "ok"),
        (
            Change(
                op="add",
                path="/users/u2",
                after={
                    "id": "u2",
                    "businessPhones": ["+1 555 0100"],
                    "authentication": {"methods": [{"@odata.type": "#t", "id": "m9", "displayName": "Phone of Sam"}]},
                },
            ),
            None,
            {"id": "u2", "businessPhones": MASKED, "authentication": {"methods": [{"@odata.type": "#t", "id": "m9"}]}},
        ),
        (
            Change(
                op="remove", path="/users/u1/authentication/methods", before=[{"@odata.type": "#t", "id": "a", "x": 1}]
            ),
            [{"@odata.type": "#t", "id": "a"}],
            None,
        ),
        (Change(op="replace", path="/users/u1/accountEnabled", before=True, after=False), True, False),
    ],
)
def test_b02_3_mask_change_keeps_ids_and_masks_contact_details(
    change: Change, expected_before: Any, expected_after: Any
) -> None:
    masked = mask_change(change)
    assert (masked["op"], masked["path"]) == (change.op, change.path)
    assert (masked["before"], masked["after"]) == (expected_before, expected_after)


# -- B02-4 crash path and compatibility -----------------------------------------------------------


def test_b02_4_the_crash_path_records_the_idempotency_key(tmp_path: Path) -> None:
    spec = LeverDef.model_validate(
        {
            "name": "test.crash",
            "description": "Crashes (test only).",
            "client_scope": "any",
            "required_role": "agent",
            "class": "read",
            "approval": "none",
            "idempotency_keys": ["n"],
            "params": {"n": {"type": "string", "required": True}},
            "dry_run": True,
            "timeout_s": 2,
        }
    )

    def crash(state: dict[str, Any], params: Mapping[str, Any]) -> Any:
        raise RuntimeError("boom with private detail")

    env = make_env(tmp_path, registry=Registry([spec], {"test.crash": crash}))
    result = env.runner.invoke("test.crash", {"n": "7"}, "tech-ana", CONTOSO)
    assert (result.status, result.reason) == ("error", "lever crashed: RuntimeError")
    assert env.last()["result"]["idempotency"] == f"test.crash/{CONTOSO}/n=7"
    assert "private detail" not in env.raw_log()


def test_b02_4_runner_keeps_its_four_argument_constructor(tmp_path: Path) -> None:
    # Phase 1 callers (queue, UI, tests) build the runner without a pause store; it defaults beside the audit log.
    env = make_env(tmp_path)
    assert env.runner.pauses.path == (tmp_path / PAUSES_FILE).resolve()
    assert set(HANDLERS) == {"ticket.get", "kb.search", "user.reset-mfa", "user.disable"}


def test_b02_4_demo_fallback_changes_only_by_adding_verified(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # docs/DEMO.md step 6 fallback: the approved execute now also names how Ana was verified.
    base = ["--state", str(tmp_path), "invoke", "user.reset-mfa", "--as", "tech-ana", "--client", CONTOSO]
    base += ["-p", f"upn={ANA}", "--execute"]
    assert cli_main(base) == 1
    assert "user.reset-mfa in execute mode needs a lead approval record" in capsys.readouterr().out
    assert cli_main([*base, "--approved-by", "lead-lee"]) == 1
    assert cli_main([*base, "--approved-by", "lead-lee", "--verified", "callback-on-file"]) == 0
    out = capsys.readouterr().out
    assert '"approver": "lead-lee"' in out and '"applied": true' in out
    assert (
        cli_main(
            [
                "--state",
                str(tmp_path),
                "invoke",
                "user.reset-mfa",
                "--as",
                "lead-lee",
                "--client",
                CONTOSO,
                "-p",
                f"upn={ANA}",
                "--execute",
                "--approved-by",
                "lead-lee",
                "--verified",
                "callback-on-file",
            ]
        )
        == 1
    )
    assert "requester cannot approve their own action (four-eyes rule)" in capsys.readouterr().out
