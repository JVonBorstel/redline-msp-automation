"""B-28 dual approval end to end: two distinct leads approve user.reset-mfa and device.lock on the page; the audit
chain shows both approvals and verifies.

Change note: docs/changes/B-28-dual-approval.md. Proposals are dry-run by the triage agent through the queue (as
`python -m core.queue seed` does), approved on the page by two leads, executed once through the runner, and the
client's audit chain is checked with the verifier. user.reset-mfa runs with Entra ID tokens from the B-89 mock issuer;
device.lock (a PowerShell lever, requester+contact, business hours) runs behind the demo picker with the runner
clock pinned inside the client's business hours. Synthetic data only; everything is under tmp_path.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/ui/test_b28_dual_e2e.py
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

from core.audit import verify_chain
from core.audit.router import AuditRouter
from core.auth import AuthConfig, TokenValidator
from core.auth.mock_issuer import MockIssuer
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, LeverRunner, MockTenant, Registry
from core.levers.bridge import PowerShellBridge
from core.levers.runner import RunnerPolicy
from core.queue import Proposal, ProposalQueue
from ui.app import App, Response

CONTOSO = "contoso-dental"
HOST = {"host": "127.0.0.1:8765"}
FORM = {**HOST, "content-type": "application/x-www-form-urlencoded"}
PWSH = shutil.which("pwsh")
CONTACT = "contact-1"
WED_10 = datetime(2025, 3, 5, 18, 0, tzinfo=UTC)  # Wed 10:00 at a fixed UTC-08:00 client
RECORD: dict[str, Any] = {
    "time_zone": "UTC-08:00",
    "business_hours": {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "08:00", "end": "17:00"},
    "authorized_contacts": [CONTACT],
}
LAPTOP = "c0000000-0000-4000-8000-0000000d0006"  # OFFICE-MGR laptop (synthetic)


def guid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://example.invalid/b28-e2e/{name}"))


TENANT, APP_ID, OID_LEE, OID_MIA = guid("tenant"), guid("approval-page"), guid("lee"), guid("mia")


def shipped_identities() -> IdentityStore:
    """The committed config/identities.json: two synthetic leads for Contoso Dental (D-067)."""
    store = IdentityStore.load()
    assert {"lead-lee", "lead-mia"} <= {i.id for i in store}
    return store


def runner_for(tmp: Path, policy: RunnerPolicy, clock: datetime | None = None) -> LeverRunner:
    shutil.copytree(DEFAULT_TENANT_DIR, tmp / "tenant")
    return LeverRunner(
        Registry.load(),
        shipped_identities(),
        MockTenant(tmp / "tenant"),
        AuditRouter(tmp / "audit"),
        bridge=PowerShellBridge(tenant_dir=tmp / "tenant"),
        policy=policy,
        clock=(lambda: clock) if clock is not None else None,
    )


def post(app: App, act: str, actor: str, headers: dict[str, str] | None = None, **extra: str) -> Response:
    fields = {"csrf": app.csrf_token, "actor": actor, "act": act, **extra}
    return app.handle("POST", "/decide", {**FORM, **(headers or {})}, urlencode(fields).encode())


def digest_on_page(app: App, proposal_id: str, target: str, headers: dict[str, str] | None = None) -> str:
    page = app.handle("GET", target, {**HOST, **(headers or {})}).body.decode("utf-8")
    section = next(s for s in page.split('<section class="proposal">')[1:] if proposal_id in s.split("</h2>")[0])
    assert "Approved by lead-lee, waiting for a second lead" in section
    found = re.search(r'name="digest" value="([0-9a-f]{64})"', section)
    assert found
    return found.group(1)


def chain(tmp: Path) -> tuple[Path, list[dict[str, Any]]]:
    path = tmp / "audit" / f"{CONTOSO}.jsonl"
    return path, [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def assert_both_in_the_chain(tmp: Path, proposal: Proposal, auth: str) -> None:
    path, rows = chain(tmp)
    assert verify_chain(path).ok
    mine = [r for r in rows if r["lever"] == proposal.lever and r["params"] == proposal.params]
    kinds = [(r["mode"], r["agent"], r["result"]["status"]) for r in mine]
    assert kinds == [
        ("dry-run", "triage-bot", "ok"),
        ("approve", "lead-lee", "awaiting-second-approval"),
        ("execute", "tech-ana", "ok"),
    ], kinds
    partial, execute = mine[1], mine[2]
    assert partial["result"]["approver_auth"]["method"] == auth and partial["approver"] == "lead-lee"
    assert execute["approver"] == "lead-lee,lead-mia" and execute["result"]["applied"] is True
    assert execute["result"]["approvers_required"] == 2
    signins = execute["result"]["approvals"]
    assert [s["approver"] for s in signins] == ["lead-lee", "lead-mia"]
    assert {s["auth"] for s in signins} == {auth}
    assert "attested_at" in signins[0], "the first lead's sign-in was checked when they approved"


def test_b28d_e2e_two_signed_in_leads_reset_mfa_and_the_chain_shows_both(tmp_path: Path) -> None:
    issuer = MockIssuer(TENANT, seed=2829)
    config = {
        "version": 1,
        "tenant_id": TENANT,
        "client_id": APP_ID,
        "keys": [issuer.jwk()],
        "approvers": {OID_LEE: "lead-lee", OID_MIA: "lead-mia"},
    }
    validator = TokenValidator(AuthConfig.model_validate(config), shipped_identities())
    queue = ProposalQueue(tmp_path / "queue.jsonl", runner_for(tmp_path, RunnerPolicy(validator=validator)))
    proposal, _ = queue.propose(
        Proposal.new(
            source="triage",
            ref="T-2810",
            lever="user.reset-mfa",
            client=CONTOSO,
            params={"upn": "priya.nair@contosodental.example"},
            requested_by="tech-ana",
            reason="Lost phone: reset MFA (B-28 end to end)",
        ),
        "triage-bot",
    )
    app = App(queue, auth=validator)

    def bearer(oid: str) -> dict[str, str]:
        claims = issuer.claims(audience=APP_ID, oid=oid, now=datetime.now(UTC) - timedelta(seconds=5))
        return {"authorization": f"Bearer {issuer.sign(claims)}"}

    first = post(
        app,
        f"approve:{proposal.id}",
        "lead-lee",
        bearer(OID_LEE),
        verified="callback-on-file",
        number_source="psa-contact",
    )
    assert first.status == 303, first.body[:400]
    digest = digest_on_page(app, proposal.id, "/", bearer(OID_MIA))
    second = post(app, f"approve:{proposal.id}", "lead-mia", bearer(OID_MIA), digest=digest)
    assert second.status == 303, second.body[:400]
    done = queue.get(proposal.id)
    assert done is not None and done.status == "executed"
    assert_both_in_the_chain(tmp_path, proposal, "entra-id-token")


@pytest.mark.skipif(PWSH is None, reason="pwsh (PowerShell 7.4+) is not installed")
def test_b28d_e2e_two_leads_lock_a_device_with_the_contact_confirmed_and_the_chain_shows_both(tmp_path: Path) -> None:
    policy = RunnerPolicy(demo=True, client_records={CONTOSO: RECORD})
    queue = ProposalQueue(tmp_path / "queue.jsonl", runner_for(tmp_path, policy, WED_10))
    proposal, dry_run = queue.propose(
        Proposal.new(
            source="triage",
            ref="T-2811",
            lever="device.lock",
            client=CONTOSO,
            params={"device": LAPTOP, "upn": "lena.fischer@contosodental.example"},
            requested_by="tech-ana",
            reason="Office manager's laptop reported stolen (B-28 end to end)",
        ),
        "triage-bot",
    )
    assert dry_run is not None and dry_run.ok and dry_run.diff
    before = (tmp_path / "tenant" / CONTOSO / "devices.json").read_bytes()
    app = App(queue)
    first = post(
        app,
        f"approve:{proposal.id}",
        "lead-lee",
        verified="callback-on-file",
        number_source="psa-contact",
        contact=CONTACT,
    )
    assert first.status == 303, first.body[:400]
    assert (tmp_path / "tenant" / CONTOSO / "devices.json").read_bytes() == before, "one approval applies nothing"
    digest = digest_on_page(app, proposal.id, "/?as=lead-mia")
    second = post(app, f"approve:{proposal.id}", "lead-mia", digest=digest)
    assert second.status == 303, second.body[:400]
    done = queue.get(proposal.id)
    assert done is not None and done.status == "executed", done
    assert (tmp_path / "tenant" / CONTOSO / "devices.json").read_bytes() != before
    assert_both_in_the_chain(tmp_path, proposal, "demo-picker")
    _, rows = chain(tmp_path)
    execute = next(r for r in rows if r["mode"] == "execute")
    assert execute["result"]["contact_verification"]["contact"] == CONTACT
    assert execute["result"]["verification"]["ref"] == "number-on-file:psa-contact"
