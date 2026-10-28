"""B-89 approver sign-in: Entra ID token validation (mocked issuer), the page gate and the approval record.

Acceptance ids B89-1 to B89-3 are defined in specs/B-89.md. Offline and deterministic: the "Entra tenant" is
core.auth.mock_issuer.MockIssuer with an RSA key made in memory from a fixed seed (never written anywhere), every
tenant, app, object and session id is a synthetic GUID built at run time, time is pinned or relative to now, and
each test has its own state folder under tmp_path. Committed fixtures are never modified.
Run: uv run --frozen pytest tests/py/auth
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import shutil
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

import ui.__main__ as ui_cli
from core.audit import AuditLog
from core.auth import ApproverAuth, AuthConfig, AuthConfigError, AuthError, TokenValidator, load_auth_config
from core.auth.jws import RsaPublicKey, b64url_encode, verify_rs256
from core.auth.mock_issuer import MockIssuer
from core.identity import Identity, IdentityStore, Role
from core.levers import DEFAULT_TENANT_DIR, LeverRunner, MockTenant, Registry
from core.queue.__main__ import SEED_AGENT, demo_proposals
from core.queue.store import Proposal, ProposalQueue, QueueError
from ui.app import UNAUTHENTICATED, App, Response, make_server

CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
HOST = {"host": "127.0.0.1:8765"}
FORM = {**HOST, "content-type": "application/x-www-form-urlencoded"}
MFA, STALE, FAB = demo_proposals()  # reset-mfa Contoso, disable Contoso, reset-mfa Fabrikam
CALLBACK = {"verified": "callback-on-file", "number_source": "psa-contact"}
NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)


def guid(name: str) -> str:
    """A synthetic, stable GUID for a name (never a real tenant or app id)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://example.invalid/b89/{name}"))


TENANT, APP_ID, OTHER_APP = guid("tenant"), guid("approval-page"), guid("some-other-app")
OID_LEE, OID_FAY, OID_STRANGER, OID_ANA = guid("lee"), guid("fay"), guid("stranger"), guid("ana")


def ident(id_: str, role: Role, *clients: str) -> Identity:
    return Identity(id=id_, display_name=f"{id_} (synthetic)", role=role, clients=clients)


IDENTITIES = IdentityStore(
    [
        ident("tech-ana", Role.TECHNICIAN, CONTOSO),
        ident("tech-ben", Role.TECHNICIAN, FABRIKAM),
        ident("lead-lee", Role.LEAD, CONTOSO, FABRIKAM),
        ident("lead-fay", Role.LEAD, FABRIKAM),
        ident("triage-bot", Role.AGENT, CONTOSO, FABRIKAM),
    ]
)


@pytest.fixture(scope="module")
def issuer() -> MockIssuer:
    return MockIssuer(TENANT, seed=89)


@pytest.fixture(scope="module")
def rogue() -> MockIssuer:
    """Same tenant id and key id as the real mock issuer, different key: an attacker's signer."""
    return MockIssuer(TENANT, seed=90)


def config_dict(issuer: MockIssuer, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "version": 1,
        "tenant_id": TENANT,
        "client_id": APP_ID,
        "keys": [issuer.jwk()],
        "approvers": {OID_LEE: "lead-lee", OID_FAY: "lead-fay", OID_ANA: "tech-ana"},
    }
    base.update(overrides)
    return base


@pytest.fixture(scope="module")
def validator(issuer: MockIssuer) -> TokenValidator:
    return TokenValidator(AuthConfig.model_validate(config_dict(issuer)), IDENTITIES)


def token(issuer: MockIssuer, now: datetime = NOW, oid: str = OID_LEE, /, **changes: Any) -> str:
    claims = issuer.claims(audience=APP_ID, oid=oid, now=now)
    for name, value in changes.items():
        if value is None:
            claims.pop(name, None)
        else:
            claims[name] = value
    return issuer.sign(claims)


def code_of(validator: TokenValidator, tok: str | None, now: datetime = NOW) -> str:
    with pytest.raises(AuthError) as caught:
        validator.validate(tok, now)
    return caught.value.code


# ---------- the page, in token mode ----------


def make_queue(tmp_path: Path) -> ProposalQueue:
    shutil.copytree(DEFAULT_TENANT_DIR, tmp_path / "tenant")
    runner = LeverRunner(
        Registry.load(), IDENTITIES, MockTenant(tmp_path / "tenant"), AuditLog(tmp_path / "audit.jsonl")
    )
    queue = ProposalQueue(tmp_path / "queue.jsonl", runner)
    for proposal in demo_proposals():
        queue.propose(proposal, SEED_AGENT)
    return queue


@pytest.fixture
def token_app(tmp_path: Path, validator: TokenValidator) -> App:
    return App(make_queue(tmp_path), auth=validator)


@pytest.fixture
def demo_app(tmp_path: Path) -> App:
    return App(make_queue(tmp_path))


def bearer(tok: str) -> dict[str, str]:
    return {"authorization": f"Bearer {tok}"}


def post(app: App, act: str, headers: dict[str, str] | None = None, **fields: str) -> Response:
    body = urlencode({"csrf": app.csrf_token, "act": act, **fields}).encode()
    return app.handle("POST", "/decide", {**FORM, **(headers or {})}, body)


def text(response: Response) -> str:
    return response.body.decode("utf-8")


def audit_records(app: App) -> list[dict[str, Any]]:
    return [json.loads(line) for line in app.queue.runner.audit.path.read_bytes().splitlines()]


def queue_lines(app: App) -> list[dict[str, Any]]:
    return [json.loads(line) for line in app.queue.path.read_bytes().splitlines()]


def tenant_digest(app: App) -> str:
    folder = app.queue.path.parent / "tenant"
    h = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            h.update(path.relative_to(folder).as_posix().encode() + b"\0" + path.read_bytes())
    return h.hexdigest()


def fresh_token(issuer: MockIssuer, oid: str = OID_LEE, /, **changes: Any) -> str:
    """A token valid now (the page checks against the wall clock)."""
    return token(issuer, datetime.now(UTC), oid, **changes)


# ===================== B89-1: a validated token, and the picker only behind --demo =====================


def test_b89_1_a_valid_token_proves_the_mapped_lead(validator: TokenValidator, issuer: MockIssuer) -> None:
    auth = validator.validate(token(issuer), NOW)
    assert auth.method == "entra-id-token" and auth.identity == "lead-lee"
    assert auth.oid == OID_LEE and auth.tid == TENANT and "mfa" in auth.amr and auth.sid
    assert auth.issued_at == "2026-10-21T09:00:00Z" and auth.expires_at == "2026-10-21T10:00:00Z"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"iss": "https://login.microsoftonline.com/common/v2.0"}, "wrong-issuer"),
        ({"iss": f"https://sts.windows.net/{TENANT}/"}, "wrong-issuer"),  # v1.0 issuer
        ({"aud": OTHER_APP}, "wrong-audience"),
        ({"aud": [APP_ID]}, "wrong-audience"),  # a list is not the single audience
        ({"tid": guid("another-tenant")}, "wrong-tenant"),
        ({"ver": "1.0"}, "wrong-version"),
        ({"amr": ["pwd"]}, "no-mfa"),
        ({"amr": []}, "missing-claim"),
        ({"amr": None}, "missing-claim"),
        ({"sid": None}, "missing-claim"),
        ({"oid": None}, "missing-claim"),
        ({"exp": "9999999999"}, "missing-claim"),
        ({"iat": True}, "missing-claim"),
    ],
)
def test_b89_1_claims_are_checked_exactly(
    validator: TokenValidator, issuer: MockIssuer, changes: dict[str, Any], code: str
) -> None:
    assert code_of(validator, token(issuer, **changes)) == code


def test_b89_1_an_unmapped_person_is_refused_never_defaulted(validator: TokenValidator, issuer: MockIssuer) -> None:
    assert code_of(validator, token(issuer, oid=OID_STRANGER)) == "unknown-approver"


def test_b89_1_expiry_not_before_issued_at_and_lifetime(validator: TokenValidator, issuer: MockIssuer) -> None:
    hour = timedelta(hours=1)
    assert code_of(validator, token(issuer), NOW + hour + timedelta(seconds=61)) == "expired"
    assert validator.validate(token(issuer), NOW + hour + timedelta(seconds=59)).identity == "lead-lee"  # leeway 60
    nbf = int((NOW + timedelta(minutes=5)).timestamp())
    assert code_of(validator, token(issuer, nbf=nbf)) == "not-yet-valid"
    assert code_of(validator, token(issuer, NOW + timedelta(minutes=5)), NOW) == "issued-in-future"
    long_lived = token(issuer, exp=int((NOW + timedelta(hours=2)).timestamp()))
    assert code_of(validator, long_lived) == "lifetime-too-long"


def _forge(header: dict[str, Any], claims: dict[str, Any], signature: bytes) -> str:
    def part(obj: dict[str, Any]) -> str:
        return b64url_encode(json.dumps(obj, separators=(",", ":")).encode())

    return f"{part(header)}.{part(claims)}.{b64url_encode(signature)}"


def test_b89_1_signature_is_checked_against_the_configured_key(
    validator: TokenValidator, issuer: MockIssuer, rogue: MockIssuer
) -> None:
    claims = issuer.claims(audience=APP_ID, oid=OID_LEE, now=NOW)
    # Signed by another key under the same kid.
    assert code_of(validator, rogue.sign(claims)) == "bad-signature"
    # Payload changed after signing (approver swapped).
    head, _, sig = issuer.sign(claims).split(".")
    swapped = {**claims, "oid": OID_FAY}
    tampered = f"{head}.{b64url_encode(json.dumps(swapped).encode())}.{sig}"
    assert code_of(validator, tampered) == "bad-signature"
    # Unknown kid.
    assert code_of(validator, issuer.sign(claims, {"alg": "RS256", "kid": "kid-nobody-published"})) == "unknown-key"
    assert code_of(validator, issuer.sign(claims, {"alg": "RS256"})) == "unknown-key"


def test_b89_1_only_rs256_no_none_no_hmac_key_confusion(validator: TokenValidator, issuer: MockIssuer) -> None:
    claims = issuer.claims(audience=APP_ID, oid=OID_LEE, now=NOW)
    assert code_of(validator, _forge({"alg": "none", "kid": issuer.kid}, claims, b"x")) == "bad-algorithm"
    # HS256 "signed" with the public key bytes as the HMAC secret: the classic key-confusion attack.
    head = b64url_encode(json.dumps({"alg": "HS256", "kid": issuer.kid}).encode())
    body = b64url_encode(json.dumps(claims).encode())
    mac = hmac.new(json.dumps(issuer.jwk()).encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    assert code_of(validator, f"{head}.{body}.{b64url_encode(mac)}") == "bad-algorithm"
    embedded = {"alg": "RS256", "kid": issuer.kid, "jwk": issuer.jwk()}
    assert code_of(validator, issuer.sign(claims, embedded)) == "bad-algorithm"
    assert (
        code_of(validator, issuer.sign(claims, {"alg": "RS256", "kid": issuer.kid, "crit": ["b64"]})) == "bad-algorithm"
    )


@pytest.mark.parametrize(
    "bad",
    ["", "abc", "a.b", "a.b.c.d", "..", "!!!.e30.e30", "e30.e30.e30=", "W10.e30.e30", "e30.W10.e30", "x" * 9000],
)
def test_b89_1_malformed_tokens_are_refused(validator: TokenValidator, bad: str) -> None:
    assert code_of(validator, bad) in ("no-token", "malformed", "unknown-key")


def test_b89_1_rs256_verifier_rejects_wrong_length_and_out_of_range(issuer: MockIssuer) -> None:
    tok = issuer.sign(issuer.claims(audience=APP_ID, oid=OID_LEE, now=NOW))
    head, body, _ = tok.split(".")
    signing_input = f"{head}.{body}".encode()
    key = issuer.public
    assert not verify_rs256(key, signing_input, b"\x00" * (key.size_bytes - 1))
    assert not verify_rs256(key, signing_input, (key.n).to_bytes(key.size_bytes, "big"))
    small = RsaPublicKey(n=key.n >> 1100, e=65537)
    assert not verify_rs256(small, signing_input, b"\x01" * small.size_bytes)  # under 2048 bits


def test_b89_1_config_fails_closed(issuer: MockIssuer, tmp_path: Path) -> None:
    weak = MockIssuer(TENANT, bits=1024, seed=7)
    with pytest.raises(AuthConfigError, match="at least 2048"):
        TokenValidator(AuthConfig.model_validate(config_dict(issuer, keys=[weak.jwk()])))
    with pytest.raises(AuthConfigError, match="duplicate key id"):
        TokenValidator(AuthConfig.model_validate(config_dict(issuer, keys=[issuer.jwk(), issuer.jwk()])))
    with pytest.raises(AuthConfigError, match="unknown identities: lead-ghost"):
        TokenValidator(AuthConfig.model_validate(config_dict(issuer, approvers={OID_LEE: "lead-ghost"})), IDENTITIES)
    for broken in (
        config_dict(issuer, leeway_s=301),
        config_dict(issuer, max_lifetime_s=86401),
        config_dict(issuer, tenant_id="contoso"),
        config_dict(issuer, approvers={}),
        config_dict(issuer, extra_field=True),
        config_dict(issuer, keys=[{**issuer.jwk(), "kty": "oct"}]),
    ):
        path = tmp_path / "auth.json"
        path.write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(AuthConfigError):
            load_auth_config(path)
    with pytest.raises(AuthConfigError):
        load_auth_config(tmp_path / "missing.json")


class _FakeServer:
    server_port = 0

    def __init__(self, app: App) -> None:
        self.app = app

    def serve_forever(self) -> None:
        raise KeyboardInterrupt

    def server_close(self) -> None:
        pass


def _run_cli(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> tuple[int, list[App]]:
    started: list[App] = []

    def fake_make_server(app: App, host: str, port: int) -> _FakeServer:
        started.append(app)
        return _FakeServer(app)

    monkeypatch.setattr(ui_cli, "make_server", fake_make_server)
    return ui_cli.main(argv), started


def test_b89_1_the_page_needs_an_explicit_mode_and_the_picker_only_with_demo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str], issuer: MockIssuer
) -> None:
    state = tmp_path / "state"
    code, started = _run_cli(monkeypatch, ["--state", str(state)])
    assert code == 2 and not started and not state.exists()
    assert "choose --demo" in capsys.readouterr().err

    with pytest.raises(SystemExit) as both:
        _run_cli(monkeypatch, ["--state", str(state), "--demo", "--auth-config", str(tmp_path / "a.json")])
    assert both.value.code == 2 and not state.exists()

    code, started = _run_cli(monkeypatch, ["--state", str(state), "--auth-config", str(tmp_path / "missing.json")])
    assert code == 2 and not started and not state.exists()

    code, started = _run_cli(monkeypatch, ["--state", str(state), "--demo"])
    assert code == 0 and started[0].auth is None
    assert "demo identity picker (--demo); synthetic, not authentication" in capsys.readouterr().out

    # The shipped identities have no lead-fay, so this config maps only the shipped lead.
    cfg = tmp_path / "auth.json"
    cfg.write_text(json.dumps(config_dict(issuer, approvers={OID_LEE: "lead-lee"})), encoding="utf-8")
    code, started = _run_cli(monkeypatch, ["--state", str(tmp_path / "state2"), "--auth-config", str(cfg)])
    assert code == 0 and isinstance(started[0].auth, TokenValidator)
    assert "Entra ID token required" in capsys.readouterr().out


def test_b89_1_in_token_mode_the_picker_is_gone_and_as_grants_nothing(token_app: App, issuer: MockIssuer) -> None:
    refused = token_app.handle("GET", "/?as=lead-lee", HOST)
    assert refused.status == 401 and MFA.id not in text(refused)
    assert dict(refused.headers())["WWW-Authenticate"] == "Bearer"

    page = token_app.handle("GET", "/?as=lead-lee", {**HOST, **bearer(fresh_token(issuer, OID_FAY))})
    body = text(page)
    assert page.status == 200 and 'name="as"' not in body and "demo sign-in" not in body
    assert "Signed in as lead-fay (Entra ID token" in body
    assert FAB.id in body and MFA.id not in body  # lead-fay serves Fabrikam only, whatever ?as= says

    technician = token_app.handle("GET", "/", {**HOST, **bearer(fresh_token(issuer, OID_ANA))})
    assert technician.status == 403
    assert token_app.handle("GET", "/audit", HOST).status == 401
    assert token_app.handle("GET", "/audit", {**HOST, **bearer(fresh_token(issuer))}).status == 200


def test_b89_1_a_valid_token_decides_and_the_actor_is_the_signer(token_app: App, issuer: MockIssuer) -> None:
    response = post(token_app, f"approve:{MFA.id}", bearer(fresh_token(issuer)), **CALLBACK)
    assert response.status == 303 and dict(response.headers())["Location"] == f"/?outcome={MFA.id}"
    final = token_app.queue.get(MFA.id)
    assert final is not None and final.status == "executed" and final.decided_by == "lead-lee"


def test_b89_1_demo_mode_still_works_and_is_recorded_as_demo(demo_app: App) -> None:
    response = post(demo_app, f"approve:{MFA.id}", actor="lead-lee", **CALLBACK)
    assert response.status == 303
    final = demo_app.queue.get(MFA.id)
    assert final is not None and final.status == "executed" and final.approver_auth is not None
    assert final.approver_auth.method == "demo-picker" and final.approver_auth.amr == ()
    assert final.approver_auth.sid is None and "not authentication" in final.approver_auth.note


# ===================== B89-2: the approval record carries amr and sid =====================


def test_b89_2_approved_and_final_lines_carry_amr_and_sid(token_app: App, issuer: MockIssuer) -> None:
    tok = fresh_token(issuer)
    expected = token_app.auth.validate(tok, datetime.now(UTC)) if token_app.auth else None
    assert expected is not None
    assert post(token_app, f"approve:{MFA.id}", bearer(tok), **CALLBACK).status == 303
    decided = [line for line in queue_lines(token_app) if line["id"] == MFA.id and line["status"] != "pending"]
    assert [line["status"] for line in decided] == ["approved", "executed"]
    for line in decided:
        auth = line["approver_auth"]
        assert auth["method"] == "entra-id-token" and auth["identity"] == "lead-lee"
        assert auth["amr"] == ["pwd", "mfa"] and auth["sid"] == expected.sid
        assert auth["oid"] == OID_LEE and auth["tid"] == TENANT
    signature = tok.rsplit(".", 1)[1]
    for path in (token_app.queue.path, token_app.queue.runner.audit.path):
        raw = path.read_text(encoding="utf-8")
        assert tok not in raw and signature not in raw  # STD-AU-4: the token is never stored


def test_b89_2_a_reject_audit_record_carries_amr_and_sid(token_app: App, issuer: MockIssuer) -> None:
    tok = fresh_token(issuer)
    assert post(token_app, f"reject:{STALE.id}", bearer(tok)).status == 303
    record = audit_records(token_app)[-1]
    assert record["mode"] == "reject" and record["result"]["status"] == "rejected" and record["agent"] == "lead-lee"
    auth = record["result"]["approver_auth"]
    assert auth["method"] == "entra-id-token" and auth["amr"] == ["pwd", "mfa"] and auth["sid"]
    rejected = token_app.queue.get(STALE.id)
    assert rejected is not None and rejected.approver_auth is not None and rejected.approver_auth.sid == auth["sid"]


def test_b89_2_the_record_cannot_name_another_approver_or_sit_on_a_pending_line(
    validator: TokenValidator, issuer: MockIssuer, tmp_path: Path
) -> None:
    fay = validator.validate(token(issuer, oid=OID_FAY), NOW)
    queue = make_queue(tmp_path)
    with pytest.raises(QueueError, match="different approver"):
        queue.decide(FAB.id, "lead-lee", approve=False, auth=fay)
    assert queue.get(FAB.id) is not None and queue.get(FAB.id).status == "pending"  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="approver_auth"):
        Proposal.model_validate({**FAB.model_dump(), "approver_auth": fay.model_dump()})
    with pytest.raises(ValueError, match="needs oid"):
        ApproverAuth(method="entra-id-token", identity="lead-lee")
    with pytest.raises(ValueError, match="carries no token claims"):
        ApproverAuth(method="demo-picker", identity="lead-lee", sid=guid("s"))


# ===================== B89-3: an unauthenticated or wrong-audience POST cannot decide =====================


def _assert_refused_and_audited(app: App, response: Response, before: str, code: str, proposal: Proposal) -> None:
    assert response.status == 401, text(response)
    assert f"({code})" in text(response) and "Nothing was changed" in text(response)
    current = app.queue.get(proposal.id)
    assert current is not None and current.status == "pending" and current.approver_auth is None
    assert tenant_digest(app) == before
    record = audit_records(app)[-1]
    assert record["agent"] == UNAUTHENTICATED and record["result"]["status"] == "denied"
    assert record["result"]["reason"] == f"approver not authenticated: {code}"
    assert record["result"]["applied"] is False and record["result"]["proposal"] == proposal.id
    assert record["approver"] is None


def test_b89_3_a_post_with_no_token_cannot_decide(token_app: App) -> None:
    before = tenant_digest(token_app)
    response = post(token_app, f"approve:{MFA.id}", actor="lead-lee", **CALLBACK)  # the demo form, no token
    _assert_refused_and_audited(token_app, response, before, "no-token", MFA)
    assert dict(response.headers())["WWW-Authenticate"] == "Bearer"
    response = post(
        token_app, f"reject:{STALE.id}", {"authorization": "Basic " + b64url_encode(b"lead-lee:x")}, actor="lead-lee"
    )
    _assert_refused_and_audited(token_app, response, before, "no-token", STALE)


def test_b89_3_a_wrong_audience_token_cannot_decide(token_app: App, issuer: MockIssuer) -> None:
    before = tenant_digest(token_app)
    tok = fresh_token(issuer, aud=OTHER_APP)
    response = post(token_app, f"approve:{MFA.id}", bearer(tok), **CALLBACK)
    _assert_refused_and_audited(token_app, response, before, "wrong-audience", MFA)
    assert dict(response.headers())["WWW-Authenticate"] == 'Bearer error="invalid_token"'
    assert tok not in token_app.queue.runner.audit.path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("make", "code"),
    [
        (lambda i: "not-a-token", "malformed"),
        (lambda i: token(i, datetime.now(UTC) - timedelta(hours=3)), "expired"),
        (lambda i: fresh_token(i, amr=["pwd"]), "no-mfa"),
        (lambda i: fresh_token(i, OID_STRANGER), "unknown-approver"),
        (lambda i: fresh_token(i, iss="https://login.microsoftonline.com/common/v2.0"), "wrong-issuer"),
    ],
)
def test_b89_3_other_unproven_tokens_cannot_decide(token_app: App, issuer: MockIssuer, make: Any, code: str) -> None:
    before = tenant_digest(token_app)
    response = post(token_app, f"approve:{MFA.id}", bearer(make(issuer)), **CALLBACK)
    _assert_refused_and_audited(token_app, response, before, code, MFA)


def test_b89_3_a_valid_token_cannot_decide_as_someone_else(token_app: App, issuer: MockIssuer) -> None:
    before = tenant_digest(token_app)
    response = post(token_app, f"reject:{FAB.id}", bearer(fresh_token(issuer, OID_FAY)), actor="lead-lee")
    _assert_refused_and_audited(token_app, response, before, "unknown-approver", FAB)


def test_b89_3_a_signed_in_lead_outside_the_client_is_still_denied_and_audited(
    token_app: App, issuer: MockIssuer
) -> None:
    before = tenant_digest(token_app)
    response = post(token_app, f"approve:{MFA.id}", bearer(fresh_token(issuer, OID_FAY)), **CALLBACK)
    assert response.status == 403 and "not scoped to client &#x27;contoso-dental&#x27;" in text(response)
    current = token_app.queue.get(MFA.id)
    assert current is not None and current.status == "pending" and tenant_digest(token_app) == before
    record = audit_records(token_app)[-1]
    assert record["agent"] == "lead-fay" and record["result"]["status"] == "denied"


def test_b89_3_over_a_real_loopback_socket(token_app: App, issuer: MockIssuer) -> None:
    server = make_server(token_app, "127.0.0.1", 0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        body = urlencode({"csrf": token_app.csrf_token, "act": f"reject:{STALE.id}"})
        for headers, status in (
            ({}, 401),
            (bearer(fresh_token(issuer, aud=OTHER_APP)), 401),
            (bearer(fresh_token(issuer)), 303),
        ):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
            conn.request("POST", "/decide", body, {"Content-Type": "application/x-www-form-urlencoded", **headers})
            assert conn.getresponse().status == status
            conn.close()
    finally:
        server.shutdown()
        server.server_close()
    rejected = token_app.queue.get(STALE.id)
    assert rejected is not None and rejected.status == "rejected" and rejected.decided_by == "lead-lee"
