"""B-34 requester authorization check (specs/B-34.md): contact.check on the client's authorized-contacts list.

B34-1  contact.check (R0) answers from the client's own list only
B34-2  an unknown requester gets the fixed wording; another client's list is never read
B34-3  the result is evidence; it never sets verification

Offline, synthetic fixtures only; the runner works on a private tenant copy and audit log under tmp_path.
Run: uv run --frozen pytest tests/py/levers/test_b34_contacts.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

import levers.python.contact as contact_module
from core.audit import AuditLog
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, Approval, InvokeResult, LeverRunner, MockTenant, Registry
from core.levers.runner import VERIFICATION_NEEDED

CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
SAM = "sam.patel@contosodental.example"
PRIYA = "priya.nair@contosodental.example"
TOM = "tom.baker@contosodental.example"
MORGAN = "morgan.reyes@fabrikamcapital.example"
RILEY = "riley.brooks@fabrikamcapital.example"
NOT_AUTHORIZED = "not authorized: confirm with the client's primary contact"
FIXTURE = Path(contact_module.CONTACTS_FILE)


class Env:
    def __init__(self, tmp_path: Path) -> None:
        tenant_dir = tmp_path / "tenant"
        shutil.copytree(DEFAULT_TENANT_DIR, tenant_dir)
        self.audit_path = tmp_path / "audit.jsonl"
        self.runner = LeverRunner(
            Registry.load(), IdentityStore.load(), MockTenant(tenant_dir), AuditLog(self.audit_path)
        )

    def check(self, requester: str, change: str, client: str = CONTOSO, who: str = "tech-ana") -> InvokeResult:
        return self.runner.invoke(
            "contact.check", {"requester": requester, "change_type": change}, who, client, mode="execute"
        )

    def records(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def test_b34_1_the_lever_is_a_registered_r0_read_lever() -> None:
    lever = Registry.load().get("contact.check")
    assert (lever.lever_class, lever.risk_class, lever.approval) == ("read", "R0", "none")


def test_b34_1_a_listed_contact_is_authorized_for_a_listed_change_type(env: Env) -> None:
    result = env.check(SAM, "new-account")
    assert result.ok and not result.applied and result.diff == ()
    assert result.data["authorized"] is True
    assert result.data["evidence"]["contact_id"] == 40002
    assert result.data["evidence"]["client"] == CONTOSO


def test_b34_1_the_answer_depends_on_the_change_type(env: Env) -> None:
    assert env.check(PRIYA, "password-reset").data["authorized"] is True
    denied = env.check(PRIYA, "new-account").data
    assert denied["authorized"] is False and denied["message"] == NOT_AUTHORIZED


def test_b34_1_the_requester_match_ignores_case(env: Env) -> None:
    assert env.check("SAM.Patel@ContosoDental.example", "mfa-reset").data["authorized"] is True


def test_b34_1_the_list_is_read_for_the_runners_client_not_a_parameter(env: Env) -> None:
    assert env.check(MORGAN, "new-account", FABRIKAM, "tech-ben").data["authorized"] is True
    extra = env.runner.invoke(
        "contact.check", {"requester": MORGAN, "change_type": "new-account", "client": FABRIKAM}, "tech-ana", CONTOSO
    )
    assert extra.status == "denied"  # no client parameter exists, so the list cannot be chosen by the caller
    assert env.check(MORGAN, "new-account").data["message"] == NOT_AUTHORIZED


def test_b34_2_an_unknown_requester_gets_the_fixed_wording(env: Env) -> None:
    result = env.check("stranger@evil.example", "new-account")
    assert result.ok
    assert result.data["authorized"] is False
    assert result.data["message"] == NOT_AUTHORIZED
    assert "contact_id" not in result.data["evidence"]


def test_b34_2_an_inactive_contact_looks_the_same_as_an_unknown_one(env: Env) -> None:
    gone = env.check(TOM, "new-account").data
    unknown = env.check("nobody@contosodental.example", "new-account").data
    assert gone["authorized"] is False and gone["message"] == unknown["message"] == NOT_AUTHORIZED
    assert gone["evidence"].keys() == unknown["evidence"].keys()


def test_b34_2_another_clients_contact_is_not_authorized_here_and_the_reverse(env: Env) -> None:
    assert env.check(MORGAN, "password-reset", CONTOSO).data["message"] == NOT_AUTHORIZED
    assert env.check(SAM, "password-reset", FABRIKAM, "tech-ben").data["message"] == NOT_AUTHORIZED


def test_b34_2_another_clients_list_is_never_used(env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Fabrikam's entry is replaced by garbage: a check for Contoso must not care, and a Contoso list holding Morgan
    # (an address that only Fabrikam's real list names) must not authorize Morgan for Fabrikam.
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["clients"][FABRIKAM] = "garbage"
    copy = tmp_path / "contacts.json"
    copy.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(contact_module, "CONTACTS_FILE", copy)
    assert env.check(SAM, "new-account").data["authorized"] is True
    assert env.check(MORGAN, "new-account", FABRIKAM, "tech-ben").data["message"] == NOT_AUTHORIZED
    data["clients"][CONTOSO]["contacts"].append(
        {"contactId": 1, "name": "M", "email": MORGAN, "primary": False, "active": True, "changeTypes": ["new-account"]}
    )
    del data["clients"][FABRIKAM]
    copy.write_text(json.dumps(data), encoding="utf-8")
    assert env.check(MORGAN, "new-account", FABRIKAM, "tech-ben").data["authorized"] is False


def test_b34_2_a_technician_of_another_client_cannot_ask(env: Env) -> None:
    result = env.check(SAM, "new-account", CONTOSO, "tech-ben")  # tech-ben is scoped to Fabrikam only
    assert result.status == "denied"
    assert env.records()[-1]["result"]["status"] == "denied"


def test_b34_2_the_fixture_marks_the_unverified_shape() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert "UNVERIFIED" in data["_meta"]["note"] and set(data["clients"]) == {CONTOSO, FABRIKAM}


def test_b34_3_the_result_is_evidence_and_says_it_does_not_verify(env: Env) -> None:
    for requester in (SAM, "stranger@evil.example"):
        evidence = env.check(requester, "mfa-reset").data["evidence"]
        assert evidence["kind"] == "requester-authorization"
        assert evidence["sets_verification"] is False
        assert "does not verify" in evidence["note"]
        assert evidence["source"] == "fixtures/psa/contacts-authorized.json"


def test_b34_3_an_authorized_answer_does_not_let_an_identity_change_through(env: Env) -> None:
    assert env.check(SAM, "mfa-reset").data["authorized"] is True
    params = {"upn": "ana.lopez@contosodental.example"}
    approval = Approval(approver="lead-lee", lever="user.reset-mfa", client=CONTOSO, params=params, verification=None)
    result = env.runner.invoke("user.reset-mfa", params, "tech-ana", CONTOSO, mode="execute", approval=approval)
    assert result.status == "denied" and result.reason == f"user.reset-mfa {VERIFICATION_NEEDED}"


def test_b34_3_the_check_writes_one_audit_record_and_no_verification(env: Env) -> None:
    env.check(SAM, "new-account")
    record = env.records()[-1]
    assert record["lever"] == "contact.check" and record["result"]["applied"] is False
    assert "verification" not in record["result"]
