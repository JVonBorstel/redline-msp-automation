"""Approval queue web page (Slice C): SC-1 through the page, SC-2 tampered log shows broken, SC-3 loopback only,
plus CSRF, POST-only state changes, Host checking and HTML escaping. Uses temp state folders; the one socket test
binds an ephemeral 127.0.0.1 port in-process.
"""

import http.client
import threading
from pathlib import Path
from urllib.parse import urlencode

import pytest

from core.queue import Proposal, open_queue
from core.queue.__main__ import demo_proposals
from ui.__main__ import main as ui_main
from ui.app import App, Response, make_server

HOST = {"host": "127.0.0.1:8765"}
FORM = {**HOST, "content-type": "application/x-www-form-urlencoded"}
HOSTILE = '<script>alert(1)</script>"><img src=x onerror=alert(2)>'


@pytest.fixture
def app(tmp_path: Path) -> App:
    queue = open_queue(tmp_path)
    for proposal in demo_proposals():
        queue.add(proposal)
    return App(queue)


def get(app: App, target: str) -> Response:
    return app.handle("GET", target, HOST)


def decide(app: App, act: str, actor: str = "lead-lee", csrf: str | None = None) -> Response:
    # B-02: approvals of identity levers carry the requester verification method (C-30).
    form = {
        "csrf": app.csrf_token if csrf is None else csrf,
        "actor": actor,
        "act": act,
        "verified": "callback-on-file",
        "number_source": "psa-contact",  # B-03: a callback records where the number on file came from
    }
    body = urlencode(form).encode()
    return app.handle("POST", "/decide", FORM, body)


def text(response: Response) -> str:
    return response.body.decode("utf-8")


def test_pending_page_lists_proposals_with_token_and_demo_sign_in(app: App) -> None:
    page = text(get(app, "/"))
    for proposal in demo_proposals():
        assert f'value="approve:{proposal.id}"' in page and f'value="reject:{proposal.id}"' in page
    assert f'name="csrf" value="{app.csrf_token}"' in page
    assert "demo sign-in, synthetic" in page and '<option value="lead-lee">' in page
    assert '<form method="post" action="/decide">' in page


def test_sc1_approve_through_the_page_executes_and_names_the_approver(app: App) -> None:
    target = demo_proposals()[1]  # user.disable for Contoso
    response = decide(app, f"approve:{target.id}")
    assert response.status == 303
    assert ("Location", f"/?outcome={target.id}") in response.headers()
    assert "approved by lead-lee" in text(get(app, f"/?outcome={target.id}"))
    audit_page = text(get(app, "/audit"))
    assert "<td>execute</td><td>ok</td><td>lead-lee</td>" in audit_page


def test_sc1_reject_through_the_page_changes_nothing(app: App) -> None:
    tenant = app.queue.runner.tenant.path_for("contoso-dental")
    before = tenant.read_bytes()
    target = demo_proposals()[0]
    assert decide(app, f"reject:{target.id}").status == 303
    assert tenant.read_bytes() == before
    assert app.queue.list("rejected")[0].id == target.id


def test_sc2_tampered_audit_log_shows_as_broken(app: App) -> None:
    for proposal in demo_proposals()[:2]:
        decide(app, f"reject:{proposal.id}")
    assert "OK: 2 records" in text(get(app, "/audit?verify=1"))

    log = app.queue.runner.audit.path_for("contoso-dental")  # B-42: one chain per client
    log.write_bytes(log.read_bytes().replace(b'"agent":"lead-lee"', b'"agent":"lead-lex"', 1))
    page = text(get(app, "/audit?verify=1"))
    assert "BROKEN at seq 1: hash does not match the record content" in page


@pytest.mark.parametrize("csrf", ["", "wrong", "é" * 43])
def test_csrf_token_is_required(app: App, csrf: str) -> None:
    target = demo_proposals()[0]
    assert decide(app, f"approve:{target.id}", csrf=csrf).status == 403
    stored = app.queue.get(target.id)
    assert stored is not None and stored.status == "pending"


def test_state_changes_are_post_only_and_host_is_checked(app: App) -> None:
    target = demo_proposals()[0]
    assert (
        app.handle("GET", f"/decide?csrf={app.csrf_token}&actor=lead-lee&act=approve:{target.id}", HOST).status == 405
    )
    assert app.handle("PUT", "/", HOST).status == 405
    assert app.handle("GET", "/", {"host": "attacker.example:8765"}).status == 400
    assert app.handle("POST", "/decide", HOST, b"csrf=x").status == 415
    assert get(app, "/nope").status == 404
    assert app.queue.list("pending")[0].id == target.id


def test_every_page_has_the_csp_and_no_script(app: App) -> None:
    for target in ("/", "/audit?verify=1", "/static/app.css", "/missing"):
        response = get(app, target)
        assert ("Content-Security-Policy", app_csp()) in response.headers()
        assert b"<script" not in response.body


def app_csp() -> str:
    return "default-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"


def test_hostile_values_are_escaped_everywhere(app: App) -> None:
    hostile = app.queue.add(
        Proposal.new(
            source="triage",
            ref=HOSTILE[:64],
            lever="user.disable",
            client="contoso-dental",
            params={"upn": "jamie.chen@contosodental.example", "reason": HOSTILE},
            requested_by="tech-ana",
            reason=HOSTILE,
        )
    )
    pending_page = text(get(app, "/"))
    decide(app, f"reject:{hostile.id}")
    decide(app, f"approve:{demo_proposals()[0].id}", actor=HOSTILE)  # denied, and the actor is audited
    for page in (pending_page, text(get(app, "/audit"))):
        assert "<script>" not in page and "<img" not in page
        assert "&lt;script&gt;alert(1)&lt;/script&gt;&quot;&gt;&lt;img" in page


@pytest.mark.parametrize("host", ["0.0.0.0", "", "localhost", "::", "::1", "192.168.1.10"])  # noqa: S104
def test_sc3_refuses_any_host_but_ipv4_loopback(app: App, host: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(ValueError, match="binds 127.0.0.1 only"):
        make_server(app, host, 0)
    assert ui_main(["--state", "unused-never-created", "--host", host]) == 2
    assert not Path("unused-never-created").exists()
    assert "refusing to bind" in capsys.readouterr().err


def test_real_server_on_loopback_serves_and_enforces_csrf(app: App) -> None:
    server = make_server(app, "127.0.0.1", 0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        assert server.server_address[0] == "127.0.0.1"
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        conn.request("GET", "/")
        page = conn.getresponse()
        assert page.status == 200 and "default-src 'self'" in page.getheader("Content-Security-Policy", "")
        page.read()
        body = urlencode({"actor": "lead-lee", "act": f"approve:{demo_proposals()[0].id}"})
        conn.request("POST", "/decide", body, {"Content-Type": "application/x-www-form-urlencoded"})
        refused = conn.getresponse()
        assert refused.status == 403 and b"CSRF" in refused.read()
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
    assert len(app.queue.list("pending")) == 3
