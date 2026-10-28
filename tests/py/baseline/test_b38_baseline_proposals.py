"""B-38 baseline-sourced proposals for stale accounts and expired guests: workflows/baseline_proposals.

Acceptance ids B38-1 to B38-3 are defined in specs/B-38.md. Every test is offline and works on private copies of the
synthetic mock tenant in tmp_path; committed fixtures are never modified. The one test that runs the real baseline
starts `pwsh` and skips when PowerShell 7.4+ is not installed.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/baseline
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from core.audit import AuditLog
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, LeverRunner, MockTenant, Registry
from core.queue import DecisionDenied, ProposalQueue
from workflows.baseline_proposals import BaselineProposalsError, Plan, WorkflowConfig, load_config, plan, summary
from workflows.baseline_proposals.__main__ import main
from workflows.baseline_proposals.baseline_proposals import BASELINE_CONFIG_PATH, DEFAULT_CONFIG_PATH, GRAPH_FIXTURE_DIR

CONTOSO = "contoso-dental"
FABRIKAM = "fabrikam-capital"
AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)  # in the past: the runner refuses a verification time ahead of its clock
AS_OF = "2026-10-01"
STALE_MEMBERS = ["dana.lopez", "frank.ortiz", "kyle.moss", "erin.brooks", "omar.hassan", "carl.reyes"]
BG_PREFIX = "bg-beta@contosodental.onmicrosoft.com"
BG_NAME = "emergency.admin@contosodental.example"
BG_REASON = "break-glass account: never proposed"
needs_pwsh = pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh (PowerShell 7.4+) is not installed")


def upn(local: str) -> str:
    return local if "@" in local else f"{local}@contosodental.example"


def finding(n: int, subject: str, check: str = "STALE", lever: str = "user.disable") -> dict[str, str]:
    return {
        "Id": f"TB-{check}-{n:02d}",
        "CheckId": check,
        "Severity": "Medium",
        "Title": f"No successful sign-in for 90+ days ({n})",
        "Subject": subject,
        "Evidence": "lastSuccessfulSignInDateTime=2026-05-10 (144 days before as-of); userType=Member",
        "FixLever": lever,
        "FixMode": "dry-run" if lever else "manual",
        "FixTarget": subject,
    }


def stale(names: list[str]) -> list[dict[str, str]]:
    return [finding(i + 1, upn(name)) for i, name in enumerate(names)]


def write_findings(path: Path, findings: list[dict[str, str]], tenant: str = CONTOSO, as_of: str = AS_OF) -> Path:
    body = {"schemaVersion": 1, "tenant": tenant, "asOf": as_of, "findings": findings}
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def cfg(cap: int = 5) -> WorkflowConfig:
    return WorkflowConfig(version=1, max_proposals_per_client_per_run=cap, requested_by="triage-bot")


def guest(gid: str, address: str, expires: str, enabled: bool = True, name: str = "Test Guest") -> dict[str, Any]:
    return {
        "id": gid,
        "displayName": name,
        "userPrincipalName": address,
        "userType": "Guest",
        "accountEnabled": enabled,
        "expiresOn": expires,
    }


@dataclass
class Env:
    queue: ProposalQueue
    tenant_dir: Path
    audit_path: Path
    tmp: Path

    def users(self) -> dict[str, dict[str, Any]]:
        state = json.loads((self.tenant_dir / f"{CONTOSO}.json").read_text(encoding="utf-8"))
        return {u["userPrincipalName"]: u for u in state["users"]}

    def audit(self) -> list[dict[str, Any]]:
        return [json.loads(x) for x in self.audit_path.read_text(encoding="utf-8").splitlines() if x.strip()]

    def findings(self, findings: list[dict[str, str]]) -> Path:
        return write_findings(self.tmp / "findings.json", findings)

    def set_guests(self, guests: list[dict[str, Any]], client: str = CONTOSO) -> None:
        meta = {"client": client, "family": "guests", "note": "synthetic test guests"}
        (self.tenant_dir / CONTOSO / "guests.json").write_text(json.dumps({"_meta": meta, "value": guests}), "utf-8")

    def drop_user(self, address: str) -> None:
        path = self.tenant_dir / f"{CONTOSO}.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["users"] = [u for u in state["users"] if u["userPrincipalName"] != address]
        path.write_text(json.dumps(state), encoding="utf-8")

    def add_user(self, address: str, name: str) -> None:
        path = self.tenant_dir / f"{CONTOSO}.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["users"].append({"id": "t1", "displayName": name, "userPrincipalName": address, "accountEnabled": True})
        path.write_text(json.dumps(state), encoding="utf-8")

    def run(self, findings: list[dict[str, str]], cap: int = 5, queue: bool = True, **kw: Any) -> Plan:
        path = self.findings(findings)
        return plan(CONTOSO, path, self.queue if queue else None, config=cfg(cap), tenant_dir=self.tenant_dir, **kw)


@pytest.fixture
def env(tmp_path: Path) -> Env:
    """A tenant copy that, unlike the committed one, holds the baseline's graph-fixture members (B-38 needs them).

    It starts with no guests; tests that want guests write their own (or copy the committed file back).
    """
    tenant_dir = tmp_path / "tenant"
    shutil.copytree(DEFAULT_TENANT_DIR, tenant_dir)
    (tenant_dir / CONTOSO / "guests.json").unlink()
    path = tenant_dir / f"{CONTOSO}.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    graph = json.loads((GRAPH_FIXTURE_DIR / "contoso" / "users.json").read_text(encoding="utf-8"))["value"]
    for u in graph:
        if u["userType"] == "Member":
            state["users"].append({k: u[k] for k in ("id", "displayName", "userPrincipalName", "accountEnabled")})
    path.write_text(json.dumps(state), encoding="utf-8")
    audit_path = tmp_path / "audit.jsonl"
    runner = LeverRunner(Registry.load(), IdentityStore.load(), MockTenant(tenant_dir), AuditLog(audit_path))
    return Env(ProposalQueue(tmp_path / "queue.jsonl", runner), tenant_dir, audit_path, tmp_path)


# --- B38-1 --------------------------------------------------------------------------------------


def test_b38_1_stale_member_finding_becomes_user_disable_proposal(env: Env) -> None:
    result = env.run(stale(["dana.lopez"]))
    assert len(result.proposals) == 1
    item = result.proposals[0]
    p = env.queue.get(item.proposal.id)
    assert p is not None and p.status == "pending" and p.source == "baseline" and p.lever == "user.disable"
    assert p.ref == "TB-STALE-01" and p.params["upn"] == upn("dana.lopez") and p.client == CONTOSO
    dry = [r for r in env.audit() if r["mode"] == "dry-run" and r["lever"] == "user.disable"]
    assert len(dry) == 1 and dry[0]["params"]["upn"] == upn("dana.lopez")  # dry-run first, audited (STD-PR-1)
    v = item.verification("lead-lee", AT)
    assert v.method == "finding-reference" and v.ref == "TB-STALE-01"
    out = summary(result)
    assert out["proposals"][0]["verification"] == {"method": "finding-reference", "ref": "TB-STALE-01"}
    assert out["executed"] is False


def test_b38_1_expired_guest_is_proposed(env: Env) -> None:
    env.set_guests([guest("GST-1", "pat.guest@contosodental.example", "2026-08-31")])
    first = env.run([])
    # the guest is not in the mock tenant's users, so the dry-run is refused and reported, not hidden
    assert [(s.ref, "not queued" in s.reason) for s in first.skipped] == [("GST-1", True)]
    env.add_user("pat.guest@contosodental.example", "Test Guest")
    result = env.run([])
    assert [(p.kind, p.ref, p.proposal.source) for p in result.proposals] == [("expired-guest", "GST-1", "baseline")]
    assert result.proposals[0].verification("lead-lee", AT).ref == "GST-1"


def test_b38_1_committed_guest_fixture_proposes_the_expired_guest_only(tmp_path: Path) -> None:
    findings = write_findings(tmp_path / "findings.json", [])
    result = plan(CONTOSO, findings, None, config=cfg(), tenant_dir=DEFAULT_TENANT_DIR)
    assert [(p.kind, p.ref, p.queued) for p in result.proposals] == [("expired-guest", "GST-contoso-0001", False)]
    reasons = {s.ref: s.reason for s in result.skipped}
    assert "not expired" in reasons["GST-contoso-0002"] and reasons["GST-contoso-0003"] == "already disabled"


def test_b38_1_unexpired_or_disabled_guest_is_not_proposed(env: Env) -> None:
    env.set_guests(
        [
            guest("GST-1", "a.guest@contosodental.example", "2026-10-01"),  # expires on the as-of day: not yet expired
            guest("GST-2", "b.guest@contosodental.example", "2026-01-01", enabled=False),
            guest("GST-3", "c.guest@contosodental.example", "not-a-date"),
        ]
    )
    result = env.run([], queue=False)
    assert not result.proposals and result.nothing_to_propose
    assert {s.ref for s in result.skipped} == {"GST-1", "GST-2", "GST-3"}
    assert "not an ISO 8601 date" in next(s.reason for s in result.skipped if s.ref == "GST-3")


def test_b38_1_guest_without_finding_uses_guest_record_id_and_a_finding_wins(env: Env) -> None:
    both = upn("dana.lopez")
    env.set_guests([guest("GST-9", both, "2026-01-01"), guest("GST-8", "z.guest@contosodental.example", "2026-02-01")])
    result = env.run(stale(["dana.lopez"]), queue=False)
    assert [(p.ref, p.proposal.params["upn"]) for p in result.proposals] == [
        ("TB-STALE-01", both),
        ("GST-8", "z.guest@contosodental.example"),
    ]
    assert any("GST-9" in n and "TB-STALE-01" in n for n in result.notes)  # collapsed, and said so


def test_b38_1_lead_approves_with_finding_reference_and_account_is_disabled(env: Env) -> None:
    item = env.run(stale(["dana.lopez"])).proposals[0]
    assert env.users()[upn("dana.lopez")]["accountEnabled"] is True  # proposing changed nothing
    decision = env.queue.decide(item.proposal.id, "lead-lee", True, verification=item.verification("lead-lee", AT))
    done = decision.proposal
    assert done.status == "executed"
    assert done.verification is not None and done.verification.method == "finding-reference"
    assert done.verification.ref == "TB-STALE-01"
    assert env.users()[upn("dana.lopez")]["accountEnabled"] is False


def test_b38_1_requester_cannot_approve_its_own_proposal(env: Env) -> None:
    item = env.run(stale(["dana.lopez"])).proposals[0]
    assert item.proposal.requested_by == "tech-ana"  # a technician owns the request; the agent only dry-ran
    with pytest.raises(DecisionDenied):
        env.queue.decide(item.proposal.id, "tech-ana", True, verification=item.verification("tech-ana", AT))
    assert env.users()[upn("dana.lopez")]["accountEnabled"] is True


def test_b38_1_non_stale_or_manual_findings_are_not_proposed(env: Env) -> None:
    findings = [
        finding(1, upn("dana.lopez"), check="MFA", lever="user.require-mfa"),
        finding(1, "Global Administrator", check="GLOBALADMIN", lever=""),
        finding(2, upn("frank.ortiz"), lever=""),  # STALE with no lever: a human decision
    ]
    result = env.run(findings)
    assert result.nothing_to_propose and result.findings_read == 3 and env.queue.list() == ()


def test_b38_1_dry_run_refusal_is_reported_not_hidden(env: Env) -> None:
    unknown = env.run([finding(1, "ghost.user@contosodental.example")])
    assert unknown.skipped[0].reason == "not in this client's directory snapshot, so break-glass cannot be checked"
    env.drop_user(upn("dana.lopez"))  # in the directory snapshot, missing from the mock tenant
    result = env.run(stale(["dana.lopez"]))
    refused = next(s for s in result.skipped if s.ref == "TB-STALE-01")
    assert not result.proposals and refused.reason.startswith("not queued: dry-run refused")
    assert env.queue.list() == ()


def test_b38_1_real_guest_upn_with_hash_is_refused_by_the_lever_and_reported(env: Env) -> None:
    shutil.copy(DEFAULT_TENANT_DIR / CONTOSO / "guests.json", env.tenant_dir / CONTOSO / "guests.json")
    result = env.run([])  # the committed guests.json, #EXT# UPNs
    assert [s.ref for s in result.skipped if "not queued" in s.reason] == ["GST-contoso-0001"]
    assert env.queue.list() == ()


@needs_pwsh
def test_b38_1_real_baseline_output_feeds_the_workflow(env: Env) -> None:
    out = env.tmp / "baseline"
    module = BASELINE_CONFIG_PATH.with_name("TenantBaseline.psd1")
    cmd = f"Import-Module -Force '{module}'; Invoke-TenantBaseline -Tenant {CONTOSO} -OutDir '{out}' | Out-Null"
    argv = ["pwsh", "-NoProfile", "-NonInteractive", "-Command", cmd]
    done = subprocess.run(argv, capture_output=True, text=True, timeout=180)  # noqa: S603
    assert done.returncode == 0, done.stderr
    result = plan(CONTOSO, out / "findings.json", None, config=cfg(10), tenant_dir=env.tenant_dir)
    members = [p for p in result.proposals if p.kind == "stale"]
    assert members and all(p.ref.startswith("TB-STALE-") for p in members)
    assert not any(p.proposal.params["upn"] in (BG_PREFIX, BG_NAME) for p in result.proposals)


# --- B38-2 --------------------------------------------------------------------------------------


def test_b38_2_bg_prefix_account_never_proposed(env: Env) -> None:
    result = env.run([finding(1, BG_PREFIX), finding(2, upn("dana.lopez"))])
    assert [p.proposal.params["upn"] for p in result.proposals] == [upn("dana.lopez")]
    assert [(s.ref, s.reason) for s in result.skipped if s.upn == BG_PREFIX] == [("TB-STALE-01", BG_REASON)]
    assert all(r["params"].get("upn") != BG_PREFIX for r in env.audit())  # not even dry-run


def test_b38_2_display_name_pattern_account_never_proposed(env: Env) -> None:
    result = env.run([finding(1, BG_NAME)])
    assert not result.proposals and result.skipped[0].reason == BG_REASON


def test_b38_2_break_glass_guest_is_never_proposed(env: Env) -> None:
    env.set_guests([guest("GST-1", "ext.person@contosodental.example", "2026-01-01", name="Break Glass Vendor")])
    result = env.run([], queue=False)
    assert not result.proposals and result.skipped[0].reason == BG_REASON


def test_b38_2_unresolvable_user_is_skipped_not_proposed(env: Env) -> None:
    prefix_only = env.run([finding(1, "bg-gamma@contosodental.onmicrosoft.com")])
    assert not prefix_only.proposals and prefix_only.skipped[0].reason == BG_REASON  # the prefix is enough
    unknown = env.run([finding(1, "nobody@contosodental.example")])
    assert not unknown.proposals and "cannot be checked" in unknown.skipped[0].reason


def test_b38_2_pattern_comes_from_baseline_config(env: Env) -> None:
    custom = env.tmp / "baseline.config.json"
    data = json.loads(BASELINE_CONFIG_PATH.read_text(encoding="utf-8"))
    data["breakGlass"]["namePrefix"] = "dana."
    data["breakGlass"]["candidateDisplayNamePattern"] = "Frank"
    custom.write_text(json.dumps(data), encoding="utf-8")
    findings = stale(["dana.lopez", "frank.ortiz", "kyle.moss"])
    result = env.run(findings, queue=False, baseline_config=custom)
    assert [p.proposal.params["upn"] for p in result.proposals] == [upn("kyle.moss")]
    bad = env.tmp / "bad.config.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(BaselineProposalsError, match="no usable break-glass rule"):
        env.run(findings, queue=False, baseline_config=bad)


# --- B38-3 --------------------------------------------------------------------------------------


def test_b38_3_cap_limits_proposals_and_lists_the_rest_as_deferred(env: Env) -> None:
    result = env.run(stale(STALE_MEMBERS), cap=2)
    assert [p.ref for p in result.proposals] == ["TB-STALE-01", "TB-STALE-02"]
    expected = [(f"TB-STALE-0{n}", upn(STALE_MEMBERS[n - 1])) for n in (3, 4, 5, 6)]
    assert [(d.ref, d.upn) for d in result.deferred] == expected
    assert all("cap of 2" in d.reason for d in result.deferred)
    assert len(env.queue.list()) == 2  # deferred ones are neither queued nor dry-run
    assert sum(1 for r in env.audit() if r["mode"] == "dry-run") == 2
    out = summary(result)
    assert out["cap"] == 2 and len(out["deferred"]) == 4 and out["deferred"][0]["ref"] == "TB-STALE-03"


def test_b38_3_cap_is_per_client(env: Env) -> None:
    contoso = env.findings(stale(["dana.lopez", "frank.ortiz", "kyle.moss"]))
    names = ["rosa.diaz", "sam.okafor", "tara.singh"]
    fab = write_findings(
        env.tmp / "fab.json", [finding(i, f"{n}@fabrikamcapital.example") for i, n in enumerate(names, 1)], FABRIKAM
    )
    first = plan(CONTOSO, contoso, None, config=cfg(2), tenant_dir=env.tenant_dir)
    second = plan(FABRIKAM, fab, None, config=cfg(2), tenant_dir=env.tenant_dir)
    assert (len(first.proposals), len(first.deferred)) == (2, 1)
    assert (len(second.proposals), len(second.deferred)) == (2, 1)
    assert {p.proposal.client for p in second.proposals} == {FABRIKAM}


def test_b38_3_cap_comes_from_config_and_bad_values_are_refused(tmp_path: Path) -> None:
    assert load_config().max_proposals_per_client_per_run == 5
    base = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    path = tmp_path / "c.json"
    for bad in (0, -1, True, 2.5, "3", 1001):
        path.write_text(json.dumps({**base, "max_proposals_per_client_per_run": bad}), encoding="utf-8")
        with pytest.raises(BaselineProposalsError, match="bad baseline proposals config"):
            load_config(path)
    path.write_text(json.dumps({**base, "surprise": 1}), encoding="utf-8")
    with pytest.raises(BaselineProposalsError):
        load_config(path)
    with pytest.raises(BaselineProposalsError, match="cannot read"):
        load_config(tmp_path / "missing.json")


def test_b38_3_second_run_is_idempotent_and_already_queued_do_not_use_the_cap(env: Env) -> None:
    findings = stale(STALE_MEMBERS)
    env.run(findings, cap=2)
    again = env.run(findings, cap=2)
    assert [p.ref for p in again.already_queued] == ["TB-STALE-01", "TB-STALE-02"]
    assert [p.ref for p in again.proposals] == ["TB-STALE-03", "TB-STALE-04"]  # the next batch, not the same two
    assert len(again.deferred) == 2 and len(env.queue.list()) == 4


# --- supporting ---------------------------------------------------------------------------------


def test_b38_empty_findings_say_nothing_to_propose(env: Env) -> None:
    result = env.run([])
    assert result.nothing_to_propose and summary(result)["nothing_to_propose"] is True and env.queue.list() == ()


def test_b38_missing_or_malformed_findings_file_is_an_error(env: Env) -> None:
    with pytest.raises(BaselineProposalsError, match="cannot read findings"):
        plan(CONTOSO, env.tmp / "nope.json", None, config=cfg(), tenant_dir=env.tenant_dir)
    bad = env.tmp / "bad.json"
    for text in ("not json", "[]", '{"tenant": "contoso-dental"}'):
        bad.write_text(text, encoding="utf-8")
        with pytest.raises(BaselineProposalsError):
            plan(CONTOSO, bad, None, config=cfg(), tenant_dir=env.tenant_dir)
    no_date = write_findings(env.tmp / "nd.json", [], as_of="")
    with pytest.raises(BaselineProposalsError, match="no as-of date"):
        plan(CONTOSO, no_date, None, config=cfg(), tenant_dir=env.tenant_dir)
    assert plan(CONTOSO, no_date, None, config=cfg(), tenant_dir=env.tenant_dir, as_of=AS_OF).as_of == AS_OF


def test_b38_schema_invalid_finding_is_refused(env: Env) -> None:
    broken = {**finding(1, upn("dana.lopez")), "Severity": "Critical"}
    with pytest.raises(BaselineProposalsError, match="finding.schema.json"):
        env.run([broken], queue=False)
    extra = {**finding(1, upn("dana.lopez")), "Surprise": "x"}
    with pytest.raises(BaselineProposalsError, match="finding.schema.json"):
        env.run([extra], queue=False)


def test_b38_client_isolation(env: Env) -> None:
    fab = write_findings(env.tmp / "fab.json", [finding(1, "rosa.diaz@fabrikamcapital.example")], FABRIKAM)
    with pytest.raises(BaselineProposalsError, match="not 'contoso-dental'"):
        plan(CONTOSO, fab, env.queue, config=cfg(), tenant_dir=env.tenant_dir)
    # a contoso file naming a fabrikam account: that person is not in contoso's directory
    mixed = env.run([finding(1, "rosa.diaz@fabrikamcapital.example")])
    assert not mixed.proposals and "not in this client's directory" in mixed.skipped[0].reason
    env.set_guests([], client=FABRIKAM)  # a guest file that names another client is refused
    with pytest.raises(BaselineProposalsError, match="does not belong"):
        env.run([], queue=False)
    with pytest.raises(BaselineProposalsError, match="no usable break-glass rule or tenant"):
        plan("unknown-client", env.findings([]), None, config=cfg(), tenant_dir=env.tenant_dir)


def test_b38_cli_exit_codes(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    state = env.tmp / "state"
    shutil.copytree(env.tenant_dir, state / "tenant")
    findings = env.findings(stale(["dana.lopez"]))
    base = ["--client", CONTOSO, "--findings", str(findings), "--state", str(state)]
    assert main(base) == 0
    out = json.loads(capsys.readouterr().out)
    assert [p["ref"] for p in out["proposals"]] == ["TB-STALE-01"] and out["executed"] is False
    assert main(base) == 0  # second run: already queued
    assert [p["ref"] for p in json.loads(capsys.readouterr().out)["already_queued"]] == ["TB-STALE-01"]
    assert main(["--client", CONTOSO, "--findings", str(env.tmp / "nope.json"), "--state", str(state)]) == 2
    assert "error:" in capsys.readouterr().err
    assert main([*base, "--as-of", "junk"]) == 2
