"""B-03 approval page: scoped listing (DR-12), verification capture (C-30), diff, undo and impact shown, seed dry-run.

Acceptance ids B03-1 to B03-4 are defined in specs/B-03.md. Every test is offline and uses its own state folder under
tmp_path (a private copy of the synthetic mock tenant, audit log and queue); committed files are never modified.
Phone-shaped strings are built at runtime, never typed here.
Run: uv run --frozen pytest tests/py/queue
"""

from __future__ import annotations

import json
import re
import shutil
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from core.audit import AuditLog
from core.audit.router import AuditRouter
from core.identity import Identity, IdentityStore, Role
from core.levers import DEFAULT_TENANT_DIR, LeverRunner, MockTenant, Registry
from core.queue.__main__ import SEED_AGENT, demo_proposals
from core.queue.__main__ import main as queue_cli
from core.queue.store import (
    NUMBER_ON_FILE_PREFIX,
    NUMBER_ON_FILE_SOURCES,
    VERIFICATION_METHODS,
    Proposal,
    ProposalQueue,
    QueueError,
    open_queue,
)
from ui.app import NO_UNDO, App, Response, make_server

CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
HOST = {"host": "127.0.0.1:8765"}
LEE = "/?as=lead-lee"
FORM = {**HOST, "content-type": "application/x-www-form-urlencoded"}
CSP = "default-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
HOSTILE = '<script>alert(1)</script>"><img src=x onerror=alert(2)>'
PHONE_SHAPE = re.compile(r"\+\d[\d\s().-]{5,}\d")
MFA, STALE, FAB = demo_proposals()  # reset-mfa Contoso, disable Contoso, reset-mfa Fabrikam


def ident(id_: str, role: Role, *clients: str) -> Identity:
    return Identity(id=id_, display_name=f"{id_} (synthetic)", role=role, clients=clients)


# The shipped identities plus lead-fay, a lead for Fabrikam only (DR-12 needs a lead without every client).
IDENTITIES = IdentityStore(
    [
        ident("tech-ana", Role.TECHNICIAN, CONTOSO),
        ident("tech-ben", Role.TECHNICIAN, FABRIKAM),
        ident("lead-lee", Role.LEAD, CONTOSO, FABRIKAM),
        ident("lead-fay", Role.LEAD, FABRIKAM),
        ident("triage-bot", Role.AGENT, CONTOSO, FABRIKAM),
    ]
)


def make_queue(tmp_path: Path, registry: Registry | None = None) -> ProposalQueue:
    shutil.copytree(DEFAULT_TENANT_DIR, tmp_path / "tenant")
    runner = LeverRunner(
        registry or Registry.load(), IDENTITIES, MockTenant(tmp_path / "tenant"), AuditLog(tmp_path / "audit.jsonl")
    )
    return ProposalQueue(tmp_path / "queue.jsonl", runner)


def seeded(queue: ProposalQueue) -> App:
    for proposal in demo_proposals():
        queue.propose(proposal, SEED_AGENT)
    return App(queue)


@pytest.fixture
def app(tmp_path: Path) -> App:
    return seeded(make_queue(tmp_path))


def get(app: App, target: str) -> Response:
    return app.handle("GET", target, HOST)


def post(app: App, act: str, actor: str = "lead-lee", **extra: str) -> Response:
    fields = {"csrf": app.csrf_token, "actor": actor, "act": act, **extra}
    return app.handle("POST", "/decide", FORM, urlencode(fields).encode())


def text(response: Response) -> str:
    return response.body.decode("utf-8")


def records(queue: ProposalQueue) -> list[dict[str, Any]]:
    audit = queue.runner.audit
    # B-42: a router keeps one chain per client (clients in name order, then _msp); a plain log is one file.
    paths = list(audit.paths().values()) if isinstance(audit, AuditRouter) else [audit.path]
    return [json.loads(line) for p in paths if p.exists() for line in p.read_text(encoding="utf-8").splitlines()]


def tenant_bytes(queue: ProposalQueue) -> dict[str, bytes]:
    return {c: queue.runner.tenant.path_for(c).read_bytes() for c in (CONTOSO, FABRIKAM)}


def status(queue: ProposalQueue, proposal: Proposal) -> str:
    stored = queue.get(proposal.id)
    assert stored is not None
    return stored.status


def fake_phone() -> str:
    # Built at runtime so no phone-shaped literal sits in the repo (STD-SC secret-looking strings rule).
    return "+" + "".join(str(d) for d in (1, 5, 5, 5, 0, 1, 0, 0, 4, 2))


# -- B03-1 a lead sees and decides only their own clients (DR-12) -----------------------------------------------


def test_b03_1_list_filters_to_the_viewers_clients_and_an_unknown_viewer_sees_nothing(app: App) -> None:
    queue = app.queue
    assert [p.id for p in queue.list(viewer="lead-fay")] == [FAB.id]
    assert [p.id for p in queue.list(viewer="lead-lee")] == [p.id for p in demo_proposals()]
    assert [p.id for p in queue.list("pending", viewer="tech-ana")] == [MFA.id, STALE.id]
    assert queue.list(viewer="mallory") == ()
    assert len(queue.list()) == 3, "without a viewer the CLI and tests still see everything"


def test_b03_1_the_page_shows_a_lead_only_proposals_for_their_clients(app: App) -> None:
    fay = text(get(app, "/?as=lead-fay"))
    assert f'value="approve:{FAB.id}"' in fay
    for other in (MFA, STALE):
        assert other.id not in fay, "a Contoso proposal must not appear for a Fabrikam-only lead"
    assert "Showing proposals for your clients only: fabrikam-capital." in fay
    assert 'name="actor" value="lead-fay"' in fay

    assert "approve:" in text(get(app, "/"))  # the default demo sign-in is the first lead in id order (lead-fay)
    lee = text(get(app, LEE))
    assert all(f'value="approve:{p.id}"' in lee for p in demo_proposals())

    # Decided proposals for another client stay hidden too, and so do their outcome banners.
    assert post(app, f"reject:{STALE.id}").status == 303
    fay = text(get(app, f"/?as=lead-fay&outcome={STALE.id}"))
    assert STALE.id not in fay and "Rejected" not in fay


@pytest.mark.parametrize("viewer", ["tech-ana", "triage-bot", "mallory", HOSTILE])
def test_b03_1_only_a_lead_can_be_the_viewer(app: App, viewer: str) -> None:
    response = get(app, "/?" + urlencode({"as": viewer}))
    assert response.status == 400
    assert "<script>" not in text(response) and "approve:" not in text(response)


@pytest.mark.parametrize("verb", ["approve", "reject"])
def test_b03_1_a_decide_post_for_another_client_is_refused_and_audited(app: App, verb: str) -> None:
    queue = app.queue
    before = tenant_bytes(queue)
    response = post(app, f"{verb}:{STALE.id}", actor="lead-fay", verified="in-person")
    assert response.status == 403
    assert "lead-fay is not scoped to client &#x27;contoso-dental&#x27;" in text(response)
    last = records(queue)[-1]
    assert (last["agent"], last["mode"], last["client"], last["result"]["status"]) == (
        "lead-fay",
        verb,
        CONTOSO,
        "denied",
    )
    assert last["result"]["proposal"] == STALE.id and last["result"]["applied"] is False
    assert status(queue, STALE) == "pending" and tenant_bytes(queue) == before


# -- B03-2 verification capture, enforced on the server (C-30) ---------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({}, "needs the requester verified out of band first"),
        ({"verified": "callback-on-file"}, "a callback needs where the number on file came from"),
        ({"verified": "callback-on-file", "number_source": "the-caller-told-me"}, "a callback needs where"),
        ({"verified": "a-friendly-voice"}, "unknown verification method"),
        ({"verified": "in-person", "number_source": "psa-contact"}, "applies only to a callback"),
        ({"number_source": "psa-contact"}, "sent without a verification method"),
    ],
)
@pytest.mark.parametrize("target", [MFA, STALE], ids=["reset-mfa", "disable"])
def test_b03_2_approve_without_an_allowed_verification_is_refused_audited_and_stays_pending(
    app: App, target: Proposal, fields: dict[str, str], reason: str
) -> None:
    queue = app.queue
    before, count = tenant_bytes(queue), len(records(queue))
    response = post(app, f"approve:{target.id}", **fields)
    assert response.status == 400 and reason in text(response)
    assert status(queue, target) == "pending" and tenant_bytes(queue) == before
    new = records(queue)[count:]
    assert len(new) == 1, "one audit record for the refused approval, and no execute"
    assert (new[0]["agent"], new[0]["mode"], new[0]["result"]["status"]) == ("lead-lee", "approve", "denied")
    assert reason in new[0]["result"]["reason"] and new[0]["result"]["proposal"] == target.id


def test_b03_2_the_number_itself_is_never_accepted_or_recorded(app: App) -> None:
    queue = app.queue
    phone = fake_phone()
    tries = [
        {"verified": "callback-on-file", "number_source": phone},
        {"verified": "callback-on-file", "number_source": "psa-contact", "number": phone},
        {"verified": phone},
    ]
    for fields in tries:
        assert post(app, f"approve:{MFA.id}", **fields).status == 400
    assert status(queue, MFA) == "pending"
    for path in (queue.runner.audit.path, queue.path):
        assert phone not in path.read_text(encoding="utf-8")
        assert not PHONE_SHAPE.search(path.read_text(encoding="utf-8"))


def test_b03_2_callback_on_file_with_its_source_executes_and_the_decision_records_it(app: App) -> None:
    queue = app.queue
    response = post(app, f"approve:{MFA.id}", verified="callback-on-file", number_source="psa-contact")
    assert response.status == 303
    stored = queue.get(MFA.id)
    assert stored is not None and stored.status == "executed" and stored.verification is not None
    v = stored.verification
    assert (v.method, v.by, v.ref) == ("callback-on-file", "lead-lee", NUMBER_ON_FILE_PREFIX + "psa-contact")

    # The queue file is its own history: the approved and executed lines both hold the verification.
    lines = [json.loads(x) for x in queue.path.read_text(encoding="utf-8").splitlines()]
    mine = [x for x in lines if x["id"] == MFA.id]
    assert [x["status"] for x in mine] == ["pending", "approved", "executed"]
    assert mine[0]["verification"] is None
    assert all(x["verification"]["ref"] == "number-on-file:psa-contact" for x in mine[1:])

    execute = records(queue)[-1]
    assert (execute["mode"], execute["approver"], execute["result"]["applied"]) == ("execute", "lead-lee", True)
    assert execute["result"]["verification"]["method"] == "callback-on-file"
    assert execute["result"]["verification"]["ref"] == "number-on-file:psa-contact"
    page = text(get(app, f"{LEE}&outcome={MFA.id}"))
    assert "Requester verification: callback-on-file (number-on-file:psa-contact) by lead-lee" in page


@pytest.mark.parametrize(
    ("method", "target", "ref"),
    [("in-person", STALE, ""), ("manager-confirmed", FAB, ""), ("finding-reference", STALE, STALE.ref)],
)
def test_b03_2_other_allowed_methods_execute_and_are_recorded(
    app: App, method: str, target: Proposal, ref: str
) -> None:
    assert post(app, f"approve:{target.id}", verified=method, number_source="").status == 303
    stored = app.queue.get(target.id)
    assert stored is not None and stored.status == "executed" and stored.verification is not None
    assert (stored.verification.method, stored.verification.ref) == (method, ref)


def test_b03_2_reject_needs_no_verification(app: App) -> None:
    assert post(app, f"reject:{MFA.id}").status == 303
    stored = app.queue.get(MFA.id)
    assert stored is not None and stored.status == "rejected" and stored.verification is None


def test_b03_2_the_page_offers_exactly_the_allowed_methods_and_sources_and_no_free_text(app: App) -> None:
    page = text(get(app, LEE))
    assert page.count('<select name="verified">') == 3 and page.count('<select name="number_source">') == 3
    for method in VERIFICATION_METHODS:
        assert f'<option value="{method}">' in page
    for source in NUMBER_ON_FILE_SOURCES:
        assert f'<option value="{source}">' in page
    assert 'type="text"' not in page and 'type="tel"' not in page and "<textarea" not in page
    assert "Never type the phone number here" in page


# -- B03-3 diff, undo, person and impact on every pending proposal; CSP and escaping ---------------------------


def test_b03_3_each_pending_proposal_shows_diff_undo_upn_and_l1_impact(app: App) -> None:
    page = text(get(app, LEE))
    registry = app.queue.runner.registry
    sections = page.split('<section class="proposal">')[1:]
    assert len(sections) == 3
    for proposal, section in zip(demo_proposals(), sections, strict=True):
        spec = registry.get(proposal.lever)
        assert spec is not None and spec.impact is not None
        assert proposal.id in section
        assert f"<dt>Person affected</dt><dd>{escape(str(proposal.params['upn']))}</dd>" in section
        assert escape(spec.impact.L1) in section
        # MFA reset has no undo lever; user.disable names user.enable (B-29)
        assert (NO_UNDO in section) == (proposal.lever == "user.reset-mfa")
        assert '<ul class="diff">' in section and "Dry-run by triage-bot, audit seq" in section
        assert "No dry-run on record" not in section
    disable = sections[1]
    assert "accountEnabled</code>: true &rarr; false" in disable
    assert "/authentication/methods/" in sections[0] and "&rarr; removed" in sections[0]
    assert not PHONE_SHAPE.search(page), "the diff on the page is the masked audit copy (DR-02)"


def test_b03_3_an_undo_lever_is_named_when_the_registry_has_one(tmp_path: Path) -> None:
    shipped = Registry.load()
    levers = [shipped.get(name) for name in shipped.names()]
    patched = [
        lever.model_copy(update={"undo": "user.reset-mfa"})
        if lever.name == "user.disable"
        else lever.model_copy(update={"undo_of": None})
        if lever.name == "user.enable"
        else lever
        for lever in levers
        if lever is not None
    ]
    app = seeded(make_queue(tmp_path, Registry(patched, {n: shipped.handler(n) for n in shipped.names()})))
    disable = text(get(app, LEE)).split('<section class="proposal">')[2]
    assert "undo lever: user.reset-mfa" in disable and NO_UNDO not in disable


def test_b03_3_a_proposal_without_a_dry_run_record_says_so(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    queue.add(STALE)  # straight into the queue, no dry-run (what B03-4 stops the demo seed doing)
    page = text(get(App(queue), LEE))
    assert "No dry-run on record for this exact action. Do not approve it." in page


def test_b03_3_the_page_keeps_the_csp_with_no_script_and_escapes_every_value(app: App) -> None:
    hostile, _ = app.queue.propose(
        Proposal.new(
            source="triage",
            ref=HOSTILE[:64],
            lever="user.disable",
            client=CONTOSO,
            params={"upn": "jamie.chen@contosodental.example", "reason": HOSTILE},
            requested_by="tech-ana",
            reason=HOSTILE,
        ),
        SEED_AGENT,
    )
    for target in ("/", LEE, "/audit", "/?as=" + HOSTILE):
        response = get(app, target)
        assert ("Content-Security-Policy", CSP) in response.headers()
        body = text(response)
        assert "<script" not in body and "<img" not in body
    page = text(get(app, LEE))
    assert hostile.id in page and "&lt;script&gt;alert(1)&lt;/script&gt;&quot;&gt;&lt;img" in page


# -- B03-4 seed --demo dry-runs every proposal as triage-bot first (DR-15); SC-1 to SC-3 still pass --------------


def test_b03_4_seed_demo_dry_runs_each_proposal_as_triage_bot_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert queue_cli(["--state", str(tmp_path), "seed", "--demo"]) == 0
    out = capsys.readouterr().out
    queue = open_queue(tmp_path)
    stored = queue.list("pending")
    assert [p.id for p in stored] == [p.id for p in demo_proposals()]
    dry_runs = [r for r in records(queue) if r["mode"] == "dry-run"]
    assert len(dry_runs) == 3 and len(records(queue)) == 3
    for proposal, record in zip(stored, dry_runs, strict=True):
        assert (record["agent"], record["lever"], record["client"]) == (SEED_AGENT, proposal.lever, proposal.client)
        assert record["params"] == proposal.params and record["result"]["status"] == "ok"
        assert record["result"]["applied"] is False and f"dry-run seq {record['seq']}" in out
    audit = queue.runner.audit
    assert isinstance(audit, AuditRouter)
    verified = audit.verify_all()  # B-42: each chain verifies alone; Contoso has two dry-runs, Fabrikam one
    assert {name: (r.ok, r.records) for name, r in verified.items()} == {CONTOSO: (True, 2), FABRIKAM: (True, 1)}

    # Idempotent: seeding again adds no proposal and no dry-run.
    assert queue_cli(["--state", str(tmp_path), "seed", "--demo"]) == 0
    assert "already queued" in capsys.readouterr().out
    assert len(records(queue)) == 3 and len(queue.list()) == 3


def test_b03_4_a_refused_dry_run_is_audited_and_not_queued(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    queue = open_queue(tmp_path)
    assert queue.runner.pause("user.disable", "lead-lee", "incident drill, IR-2").ok
    assert queue_cli(["--state", str(tmp_path), "seed", "--demo"]) == 1
    assert "not queued: dry-run refused" in capsys.readouterr().err
    assert [p.id for p in queue.list()] == [MFA.id, FAB.id]
    denied = [r for r in records(queue) if r["mode"] == "dry-run" and r["result"]["status"] == "denied"]
    assert len(denied) == 1 and denied[0]["lever"] == "user.disable" and denied[0]["agent"] == SEED_AGENT
    with pytest.raises(QueueError, match="lever paused by lead-lee"):
        queue.propose(STALE, SEED_AGENT)


def test_b03_4_sc1_still_passes_on_a_seeded_queue(tmp_path: Path) -> None:
    assert queue_cli(["--state", str(tmp_path), "seed", "--demo"]) == 0
    app = App(open_queue(tmp_path))
    queue = app.queue
    response = post(app, f"approve:{STALE.id}", verified="callback-on-file", number_source="onboarding-form")
    assert response.status == 303 and status(queue, STALE) == "executed"
    state = json.loads(tenant_bytes(queue)[CONTOSO])
    assert next(u for u in state["users"] if u["userPrincipalName"] == STALE.params["upn"])["accountEnabled"] is False
    assert "<td>execute</td><td>ok</td><td>lead-lee</td>" in text(get(app, "/audit"))

    before = tenant_bytes(queue)
    assert post(app, f"reject:{MFA.id}").status == 303
    assert tenant_bytes(queue) == before and status(queue, MFA) == "rejected"


def test_b03_4_sc2_a_tampered_log_still_shows_as_broken(tmp_path: Path) -> None:
    assert queue_cli(["--state", str(tmp_path), "seed", "--demo"]) == 0
    app = App(open_queue(tmp_path))
    # B-42: the page opens on the first client chain (Contoso: 2 of the 3 seeded dry-runs)
    assert "OK: 2 records" in text(get(app, "/audit?verify=1"))
    log = app.queue.runner.audit.path_for(CONTOSO)
    log.write_bytes(log.read_bytes().replace(b'"agent":"triage-bot"', b'"agent":"triage-bat"', 1))
    assert "BROKEN at seq 1" in text(get(app, "/audit?verify=1"))


@pytest.mark.parametrize("host", ["0.0.0.0", "localhost", "::1"])  # noqa: S104
def test_b03_4_sc3_the_page_still_binds_ipv4_loopback_only(app: App, host: str) -> None:
    with pytest.raises(ValueError, match="binds 127.0.0.1 only"):
        make_server(app, host, 0)
