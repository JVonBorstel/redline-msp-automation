"""B-28 dual approval on the loopback approval page: a partial approval, then a different signed-in lead completes it.

Change note: docs/changes/B-28-dual-approval.md. The page is driven as a plain function (App.handle), as in
tests/py/queue/test_b03_approval_page.py; no socket. Demo-picker tests run a RunnerPolicy(demo=True) runner (the
picker is not authentication); token tests use the B-89 mock issuer with an in-memory key from a fixed seed. Every test
has its own state folder under tmp_path; committed files are never modified.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/ui
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from core.audit.router import AuditRouter
from core.auth import AuthConfig, TokenValidator
from core.auth.mock_issuer import MockIssuer
from core.identity import Identity, IdentityStore, Role
from core.levers import DEFAULT_TENANT_DIR, LeverRunner, MockTenant, Registry
from core.levers.runner import RunnerPolicy
from core.queue import AWAITING, Proposal, ProposalQueue
from core.queue.__main__ import SEED_AGENT, demo_proposals
from ui.app import App, Response

CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
HOST = {"host": "127.0.0.1:8765"}
FORM = {**HOST, "content-type": "application/x-www-form-urlencoded"}
MFA, STALE, FAB = demo_proposals()  # reset-mfa Contoso, disable Contoso, reset-mfa Fabrikam
CALLBACK = {"verified": "callback-on-file", "number_source": "psa-contact"}
CONTACT = "contact-1"
EVERY_DAY = {"days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "start": "00:00", "end": "23:59"}
RECORDS: dict[str, dict[str, Any]] = {
    CONTOSO: {"time_zone": "UTC", "business_hours": EVERY_DAY, "authorized_contacts": [CONTACT, "contact-2"]},
}
WAITING = "waiting for a second lead"


def ident(id_: str, role: Role, *clients: str) -> Identity:
    return Identity(id=id_, display_name=f"{id_} (synthetic)", role=role, clients=clients)


IDENTITIES = IdentityStore(
    [
        ident("tech-ana", Role.TECHNICIAN, CONTOSO),
        ident("tech-ben", Role.TECHNICIAN, FABRIKAM),
        ident("lead-lee", Role.LEAD, CONTOSO, FABRIKAM),
        ident("lead-mia", Role.LEAD, CONTOSO, FABRIKAM),
        ident("triage-bot", Role.AGENT, CONTOSO, FABRIKAM),
    ]
)


def guid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://example.invalid/b28-page/{name}"))


TENANT, APP_ID, OID_LEE, OID_MIA = guid("tenant"), guid("approval-page"), guid("lee"), guid("mia")


def make_queue(tmp: Path, policy: RunnerPolicy) -> ProposalQueue:
    shutil.copytree(DEFAULT_TENANT_DIR, tmp / "tenant")
    runner = LeverRunner(
        Registry.load(), IDENTITIES, MockTenant(tmp / "tenant"), AuditRouter(tmp / "audit"), policy=policy
    )
    queue = ProposalQueue(tmp / "queue.jsonl", runner)
    for proposal in demo_proposals():
        queue.propose(proposal, SEED_AGENT)
    return queue


@pytest.fixture
def app(tmp_path: Path) -> App:
    return App(make_queue(tmp_path, RunnerPolicy(demo=True, client_records=RECORDS)))


@pytest.fixture(scope="module")
def issuer() -> MockIssuer:
    return MockIssuer(TENANT, seed=2828)


@pytest.fixture
def token_app(tmp_path: Path, issuer: MockIssuer) -> App:
    config = AuthConfig.model_validate(
        {
            "version": 1,
            "tenant_id": TENANT,
            "client_id": APP_ID,
            "keys": [issuer.jwk()],
            "approvers": {OID_LEE: "lead-lee", OID_MIA: "lead-mia"},
        }
    )
    validator = TokenValidator(config, IDENTITIES)
    return App(make_queue(tmp_path, RunnerPolicy(validator=validator, client_records=RECORDS)), auth=validator)


def bearer(issuer: MockIssuer, oid: str) -> dict[str, str]:
    tok = issuer.sign(issuer.claims(audience=APP_ID, oid=oid, now=datetime.now(UTC) - timedelta(seconds=5)))
    return {"authorization": f"Bearer {tok}"}


def get(app: App, target: str, headers: dict[str, str] | None = None) -> str:
    response = app.handle("GET", target, {**HOST, **(headers or {})})
    assert response.status == 200, response.body[:400]
    return response.body.decode("utf-8")


def post(app: App, act: str, actor: str = "lead-lee", headers: dict[str, str] | None = None, **extra: str) -> Response:
    fields = {"csrf": app.csrf_token, "actor": actor, "act": act, **extra}
    return app.handle("POST", "/decide", {**FORM, **(headers or {})}, urlencode(fields).encode())


def card(page: str, proposal_id: str) -> str:
    """The <section> of one proposal card."""
    for section in page.split('<section class="proposal">')[1:]:
        if proposal_id in section.split("</h2>")[0]:
            return section.split("</section>")[0]
    raise AssertionError(f"no card for {proposal_id}")


def digest_in(section: str) -> str:
    found = re.search(r'name="digest" value="([0-9a-f]{64})"', section)
    assert found, section
    return found.group(1)


def outcome(app: App, response: Response, headers: dict[str, str] | None = None) -> str:
    assert response.status == 303, response.body.decode("utf-8")[:600]
    location = dict(response.extra_headers)["Location"]
    return get(app, location, headers)


def records(app: App, client: str = CONTOSO) -> list[dict[str, Any]]:
    path = app.queue.runner.audit.path_for(client)  # type: ignore[union-attr]
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# -- the demo picker ------------------------------------------------------------------------------------------------


def test_b28d_page_the_first_approval_shows_waiting_and_a_different_lead_completes_it(app: App) -> None:
    page = outcome(app, post(app, f"approve:{MFA.id}", **CALLBACK))
    assert f"Approved {MFA.id} as lead-lee: {WAITING}" in page and "Nothing has run yet" in page
    mine = card(page, MFA.id)
    assert f"Approved by lead-lee, {WAITING}" in mine
    assert f'value="approve:{MFA.id}"' not in mine, "the first lead cannot press approve again"
    assert f'value="reject:{MFA.id}"' in mine
    assert "a different signed-in lead must complete it" in mine
    other = card(get(app, "/?as=lead-mia"), MFA.id)
    assert f"Approved by lead-lee, {WAITING}" in other and f'value="approve:{MFA.id}"' in other
    assert "called back on the number on file" in other, "the second lead sees how the requester was verified"
    assert 'name="verified"' not in other, "the verification is not asked for twice"
    done = outcome(app, post(app, f"approve:{MFA.id}", actor="lead-mia", digest=digest_in(other)))
    assert f"Executed {MFA.id}: user.reset-mfa for {CONTOSO} as tech-ana, approved by lead-lee and lead-mia." in done
    execute = next(r for r in records(app) if r["mode"] == "execute")
    assert execute["approver"] == "lead-lee,lead-mia"
    assert [a["approver"] for a in execute["result"]["approvals"]] == ["lead-lee", "lead-mia"]
    assert all(a["demo"] is True and a["auth"] == "demo-picker" for a in execute["result"]["approvals"])


def test_b28d_page_the_same_lead_twice_is_refused_and_audited(app: App) -> None:
    outcome(app, post(app, f"approve:{MFA.id}", **CALLBACK))
    digest = app.queue.get(MFA.id).digest  # type: ignore[union-attr]
    response = post(app, f"approve:{MFA.id}", digest=digest)
    assert response.status == 403 and "already approved" in response.body.decode("utf-8")
    assert records(app)[-1]["result"]["status"] == "denied"
    assert app.queue.get(MFA.id).status == AWAITING  # type: ignore[union-attr]


def test_b28d_page_a_stale_card_is_refused(app: App) -> None:
    outcome(app, post(app, f"approve:{MFA.id}", **CALLBACK))
    response = post(app, f"approve:{MFA.id}", actor="lead-mia", digest="0" * 64)
    assert response.status == 403 and "changed since" in response.body.decode("utf-8")
    assert app.queue.get(MFA.id).status == AWAITING  # type: ignore[union-attr]


def test_b28d_page_a_second_approval_with_verification_fields_is_refused(app: App) -> None:
    outcome(app, post(app, f"approve:{MFA.id}", **CALLBACK))
    digest = app.queue.get(MFA.id).digest  # type: ignore[union-attr]
    response = post(app, f"approve:{MFA.id}", actor="lead-mia", digest=digest, **CALLBACK)
    assert response.status == 400 and "already recorded" in response.body.decode("utf-8")
    assert records(app)[-1]["result"]["status"] == "denied"


def test_b28d_page_the_second_lead_can_reject(app: App) -> None:
    outcome(app, post(app, f"approve:{MFA.id}", **CALLBACK))
    page = outcome(app, post(app, f"reject:{MFA.id}", actor="lead-mia"))
    assert f"Rejected {MFA.id}" in page
    assert app.queue.get(MFA.id).status == "rejected"  # type: ignore[union-attr]
    assert not any(r["mode"] == "execute" for r in records(app))


def test_b28d_page_the_demo_picker_is_still_labelled_not_authentication(app: App) -> None:
    page = get(app, "/?as=lead-mia")
    assert "demo sign-in, synthetic" in page and "not authentication" in page


def test_b28d_page_a_non_r3_card_has_no_second_approval_step(tmp_path: Path) -> None:
    queue = make_queue(tmp_path, RunnerPolicy(demo=True, client_records=RECORDS))
    rule = queue.add(
        Proposal.new(
            source="triage",
            ref="T-2802",
            lever="inboxrule.disable",
            client=CONTOSO,
            params={"upn": "priya.nair@contosodental.example", "rule_id": "IR-CD-0002"},
            requested_by="tech-ana",
            reason="Suspicious rule hides invoices (B-28 R2 single path)",
        )
    )
    page_app = App(queue)
    page = get(page_app, "/?as=lead-lee")
    assert "needs 2 lead approvals" not in card(page, rule.id)
    assert "needs 2 lead approvals" in card(page, MFA.id)
    done = outcome(page_app, post(page_app, f"approve:{rule.id}"))
    assert f"Executed {rule.id}: inboxrule.disable for {CONTOSO} as tech-ana, approved by lead-lee." in done


# -- requester+contact (B-65) ---------------------------------------------------------------------------------------


def lock_proposal() -> Proposal:
    return Proposal.new(
        source="triage",
        ref="T-2803",
        lever="device.lock",
        client=CONTOSO,
        params={"device": "c0000000-0000-4000-8000-0000000d0006", "upn": "lena.fischer@contosodental.example"},
        requested_by="tech-ana",
        reason="Laptop reported stolen (B-28 dual approval, requester+contact)",
    )


def test_b28d_page_a_requester_contact_card_collects_the_authorized_contact(app: App) -> None:
    lock = app.queue.add(lock_proposal())
    section = card(get(app, "/?as=lead-lee"), lock.id)
    assert 'name="contact"' in section and f'value="{CONTACT}"' in section and 'value="contact-2"' in section
    assert "authorized contact" in section
    refused = post(app, f"approve:{lock.id}", **CALLBACK)
    assert refused.status == 400 and "authorized contact" in refused.body.decode("utf-8")
    assert records(app)[-1]["result"]["status"] == "denied"
    unknown = post(app, f"approve:{lock.id}", contact="contact-9", **CALLBACK)
    assert unknown.status == 400 and "choose one from the list" in unknown.body.decode("utf-8")
    in_person = post(app, f"approve:{lock.id}", verified="in-person", contact=CONTACT)
    assert in_person.status == 400 and "callback" in in_person.body.decode("utf-8")
    page = outcome(app, post(app, f"approve:{lock.id}", contact=CONTACT, **CALLBACK))
    assert f"Approved {lock.id} as lead-lee: {WAITING}" in page
    stored = app.queue.get(lock.id)
    assert stored is not None and stored.approvals[0].contact_verification is not None
    assert stored.approvals[0].contact_verification.contact == CONTACT


def test_b28d_page_a_contact_on_a_lever_that_does_not_need_one_is_refused(app: App) -> None:
    response = post(app, f"approve:{MFA.id}", contact=CONTACT, **CALLBACK)
    assert response.status == 400 and "contact" in response.body.decode("utf-8")
    assert app.queue.get(MFA.id).status == "pending"  # type: ignore[union-attr]


# -- signed in with Entra ID tokens (mock issuer) -------------------------------------------------------------------


def test_b28d_page_two_signed_in_leads_complete_an_mfa_reset(token_app: App, issuer: MockIssuer) -> None:
    lee, mia = bearer(issuer, OID_LEE), bearer(issuer, OID_MIA)
    page = outcome(token_app, post(token_app, f"approve:{MFA.id}", headers=lee, **CALLBACK), lee)
    assert f"Approved by lead-lee, {WAITING}" in card(page, MFA.id)
    partial = token_app.queue.get(MFA.id)
    assert partial is not None and partial.approvals[0].auth.method == "entra-id-token"
    assert partial.approvals[0].attestation is not None and partial.approvals[0].attestation.auth == "entra-id-token"
    assert "Bearer" not in (token_app.queue.path.read_text(encoding="utf-8")), "no token is stored"
    other = card(get(token_app, "/", mia), MFA.id)
    done = outcome(
        token_app, post(token_app, f"approve:{MFA.id}", actor="lead-mia", headers=mia, digest=digest_in(other)), mia
    )
    assert "approved by lead-lee and lead-mia" in done
    execute = next(r for r in records(token_app) if r["mode"] == "execute")
    signins = execute["result"]["approvals"]
    assert [s["approver"] for s in signins] == ["lead-lee", "lead-mia"]
    assert all(s["auth"] == "entra-id-token" and s["demo"] is False and s["sid"] for s in signins)


def test_b28d_page_a_token_lead_cannot_complete_their_own_partial(token_app: App, issuer: MockIssuer) -> None:
    lee = bearer(issuer, OID_LEE)
    outcome(token_app, post(token_app, f"approve:{MFA.id}", headers=lee, **CALLBACK), lee)
    digest = token_app.queue.get(MFA.id).digest  # type: ignore[union-attr]
    again = post(token_app, f"approve:{MFA.id}", headers=bearer(issuer, OID_LEE), digest=digest)
    assert again.status == 403 and "already approved" in again.body.decode("utf-8")
    forged = post(token_app, f"approve:{MFA.id}", actor="lead-mia", headers=lee, digest=digest)
    assert forged.status == 401, "the form cannot name a different lead than the token"
    assert token_app.queue.get(MFA.id).status == AWAITING  # type: ignore[union-attr]


# -- python -m ui always runs the runner under a policy -------------------------------------------------------------


def test_b28d_page_python_m_ui_wires_a_runner_policy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import ui.__main__ as ui_cli

    started: list[App] = []

    class Fake:
        server_port = 0

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            pass

    def fake_make_server(app: App, host: str, port: int) -> Fake:
        started.append(app)
        return Fake()

    monkeypatch.setattr(ui_cli, "make_server", fake_make_server)
    records = tmp_path / "records.json"
    records.write_text(json.dumps(RECORDS), encoding="utf-8")
    assert ui_cli.main(["--state", str(tmp_path / "s1"), "--demo", "--client-records", str(records)]) == 0
    policy = started[0].queue.runner.policy
    assert policy is not None and policy.demo and policy.authorized_contacts(CONTOSO) == {CONTACT, "contact-2"}
    assert started[0].queue.runner.approvers_needed("user.reset-mfa", CONTOSO) == 2
    assert ui_cli.main(["--state", str(tmp_path / "s2"), "--demo"]) == 0
    assert started[1].queue.runner.policy is not None
    bad = tmp_path / "bad.json"
    for content in ("[1, 2]", "{not json", json.dumps({CONTOSO: {"approver_minimum": {"R3": 1}}})):
        bad.write_text(content, encoding="utf-8")
        assert ui_cli.main(["--state", str(tmp_path / "s3"), "--demo", "--client-records", str(bad)]) == 2
        assert not (tmp_path / "s3").exists()
