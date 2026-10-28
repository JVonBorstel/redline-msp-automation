"""Approval queue and audit viewer: one small local page on the standard library only (Slice C).

Safety lives in code here, not in the browser:
- binds 127.0.0.1 only (SC-3), and answers only requests whose Host is 127.0.0.1 or localhost
  (so a DNS-rebinding page on another name cannot drive it);
- state changes are POST /decide only, and need this process's random CSRF token;
- every value is HTML-escaped, and the Content-Security-Policy allows this server's stylesheet
  and nothing else: the page has no script at all;
- the identity picker is a demo sign-in over synthetic identities, not authentication, and is
  honoured only when the page runs without a token validator (`python -m ui --demo`). The queue
  and the lever runner still refuse anyone who is not a lead for that client.

B-89 (C-44): with a `TokenValidator` (`python -m ui --auth-config FILE`), the pending page, the
audit page and every POST /decide need `Authorization: Bearer <Entra ID token>`. The approver is
the token's identity, never a form value; a request with no valid token cannot decide, is audited
as `unauthenticated` with the reason code (never the token), and gets a 401. The decided record
keeps the sign-in method, `amr` and `sid`.

B-03: the page lists only proposals for clients in the signed-in lead's own list (DR-12); each
proposal shows the person affected, the lever's L1 impact line, the dry-run diff from the audit
log and the undo lever; approving a lever marked `verification: "requester"` needs a verification
method from the allowed list and, for a callback, where the number on file came from (never the
number). A refused approval is audited and leaves the proposal pending (C-30, STD-PR-4).

B-42: the audit is one chain per client plus `_msp` (core/audit/router.py). The audit page has a chain picker and
verifies the chain on screen; the dry-run diff on a card is read from that client's chain only. Both pages show a
banner when a second review of a pre-authorized containment is overdue (D6-08).
"""

from __future__ import annotations

import hmac
import json
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from core.audit import AuditError, AuditMode, canonical_json, head_path_for, verify_chain
from core.audit.router import MSP_LOG, AuditRouter
from core.auth import ApproverAuth, AuthError, TokenValidator
from core.identity import Role
from core.levers.caps import ReviewError
from core.levers.models import LeverDef, Verification
from core.queue.store import (
    NUMBER_ON_FILE_PREFIX,
    NUMBER_ON_FILE_SOURCES,
    VERIFICATION_METHODS,
    Decision,
    DecisionDenied,
    Proposal,
    ProposalQueue,
    QueueError,
)

LOOPBACK = "127.0.0.1"
ALLOWED_HOST_NAMES = frozenset({"127.0.0.1", "localhost"})
CSS_PATH = Path(__file__).with_name("static") / "app.css"
MAX_BODY = 4096
AUDIT_ROWS = 200
DIFF_VALUE_CHARS = 160
NO_UNDO = "no undo lever: manual undo"
UNAUTHENTICATED = "unauthenticated"  # the audit `agent` of a decision refused for want of a valid token
# The only fields a decision form may carry. Anything else (a phone number, a free-text note) is refused.
FORM_FIELDS = frozenset({"csrf", "actor", "act", "verified", "number_source"})
METHOD_LABELS = {
    "callback-on-file": "called back on the number on file",
    "in-person": "verified in person",
    "manager-confirmed": "confirmed by the client's manager",
    "finding-reference": "from a baseline finding (no caller)",
}
SECURITY_HEADERS = (
    ("Content-Security-Policy", "default-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
)


def esc(value: object) -> str:
    return escape(str(value), quote=True)


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    content_type: str = "text/html; charset=utf-8"
    extra_headers: tuple[tuple[str, str], ...] = ()

    def headers(self) -> list[tuple[str, str]]:
        return [*SECURITY_HEADERS, ("Content-Type", self.content_type), *self.extra_headers]


def _page(title: str, body: str, status: int = 200) -> Response:
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} - approval queue</title><link rel="stylesheet" href="/static/app.css"></head>
<body><header><strong>Approval queue</strong>
<span class="tag">independently built prototype, synthetic data, mock tenant</span>
<nav><a href="/">Pending actions</a> <a href="/audit">Audit log</a></nav></header>
<main><h1>{esc(title)}</h1>
{body}</main></body></html>
"""
    return Response(status, html.encode("utf-8"))


def _error(status: int, message: str, *extra: tuple[str, str]) -> Response:
    page = _page("Not done", f'<p class="banner bad">{esc(message)}</p><p><a href="/">Back to pending actions</a></p>')
    return Response(status, page.body, extra_headers=extra)


def _params(params: Mapping[str, Any]) -> str:
    return "<br>".join(f"{esc(k)} = {esc(v)}" for k, v in params.items())


def _short(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= DIFF_VALUE_CHARS else text[: DIFF_VALUE_CHARS - 3] + "..."


def _action_key(lever: str, client: str, params: Mapping[str, Any]) -> tuple[str, str, bytes]:
    return lever, client, canonical_json(dict(params))


def _diff_html(record: Mapping[str, Any] | None) -> str:
    """The dry-run diff as the audit holds it (masked, DR-02), or a warning when there is none."""
    if record is None:
        return '<p class="bad">No dry-run on record for this exact action. Do not approve it.</p>'
    head = (
        f'<p class="muted">Dry-run by {esc(record["agent"])}, audit seq {esc(record["seq"])}, '
        f"{esc(record['ts'])}. Contact details are masked.</p>"
    )
    changes = record["result"].get("changes") or []
    if not changes:
        return head + "<p>The dry-run found nothing to change.</p>"
    items = "".join(_change_html(c) for c in changes if isinstance(c, Mapping))
    return f'{head}<ul class="diff">{items}</ul>'


def _change_html(change: Mapping[str, Any]) -> str:
    op = change.get("op")
    if op == "remove":
        what = f"{esc(_short(change.get('before')))} &rarr; removed"
    elif op == "add":
        what = f"added &rarr; {esc(_short(change.get('after')))}"
    else:
        what = f"{esc(_short(change.get('before')))} &rarr; {esc(_short(change.get('after')))}"
    return f"<li><code>{esc(op)}</code> <code>{esc(change.get('path'))}</code>: {what}</li>"


def _verified(v: Verification | None) -> str:
    if v is None:
        return "none recorded"
    ref = f" ({v.ref})" if v.ref else ""
    return f"{v.method}{ref} by {v.by}"


def _describe(decision: Decision) -> str:
    p, seq = decision.proposal, decision.audit_seq
    if p.status == "rejected":
        return f"Rejected {p.id} ({p.lever} for {p.client}) as {p.decided_by}; nothing was changed. Audit seq {seq}."
    if p.status == "executed":
        who = f"as {p.requested_by}, approved by {p.decided_by}"
        verified = f" Requester verification: {_verified(p.verification)}." if p.verification else ""
        return f"Executed {p.id}: {p.lever} for {p.client} {who}.{verified} Audit seq {seq}."
    reason = decision.result.reason if decision.result else "unknown"
    return f"Approved {p.id}, but the lever did not apply: {reason}. Audit seq {seq}."


class App:
    """Request handling as a plain function of (method, target, headers, body), so it is testable without sockets."""

    def __init__(self, queue: ProposalQueue, auth: TokenValidator | None = None) -> None:
        """`auth=None` is the demo picker (STD-ID-7); `python -m ui` asks for it explicitly with `--demo`."""
        self.queue = queue
        self.auth = auth
        self.csrf_token = secrets.token_urlsafe(32)
        self.leads = sorted(i.id for i in queue.runner.identities if i.role is Role.LEAD)
        self._outcomes: dict[str, str] = {}

    def handle(self, method: str, target: str, headers: Mapping[str, str], body: bytes = b"") -> Response:
        """`headers` keys are lower-case."""
        host = headers.get("host", "").rsplit(":", 1)[0]
        if host not in ALLOWED_HOST_NAMES:
            return _error(400, "This page only answers on 127.0.0.1.")
        url = urlsplit(target)
        if url.path == "/decide":
            if method != "POST":
                return _error(405, "Decisions are POST only.", ("Allow", "POST"))
            return self._decide(headers, body)
        if method != "GET":
            return _error(405, "Read-only here; decisions go to POST /decide.", ("Allow", "GET"))
        query = parse_qs(url.query)
        if url.path == "/":
            if self.auth is None:
                return self._pending(query.get("outcome", [""])[0], query.get("as", [""])[0])
            signed_in = self._authenticate(headers)
            if isinstance(signed_in, AuthError):
                return self._unauthorized(signed_in)
            return self._pending(query.get("outcome", [""])[0], signed_in.identity, signed_in)
        if url.path == "/audit":
            if self.auth is not None:
                signed_in = self._authenticate(headers)
                if isinstance(signed_in, AuthError):
                    return self._unauthorized(signed_in)
            return self._audit("verify" in query, query.get("client", [""])[0])
        if url.path == "/static/app.css":
            return Response(200, CSS_PATH.read_bytes(), "text/css; charset=utf-8")
        return _error(404, "Not found.")

    # -- pages ----------------------------------------------------------------------------

    def _pending(self, outcome_id: str, viewer: str, signed_in: ApproverAuth | None = None) -> Response:
        if not self.leads:
            return _error(500, "No lead identities are configured.")
        viewer = viewer or self.leads[0]
        if viewer not in self.leads:
            if signed_in is not None:
                return _error(403, "Signed in, but not as a lead; nothing to decide here.")
            return _error(400, "Pick a lead from the list (demo sign-in).")
        # DR-12: a lead sees only proposals for clients in their own list.
        proposals = self.queue.list(viewer=viewer)
        visible = {p.id for p in proposals}
        pending = [p for p in proposals if p.status == "pending"]
        decided = [p for p in proposals if p.status != "pending"]
        clients = self.queue.runner.identities.get(viewer).clients
        parts = [self._review_banner()]
        if outcome_id in self._outcomes and outcome_id in visible:
            parts.append(f'<p class="banner">{esc(self._outcomes[outcome_id])}</p>')
        if signed_in is None:
            ordered = [viewer, *(lead for lead in self.leads if lead != viewer)]
            options = "".join(f'<option value="{esc(lead)}">{esc(lead)}</option>' for lead in ordered)
            parts.append(
                '<form method="get" action="/" class="signin">'
                f'<label>Acting as (demo sign-in, synthetic) <select name="as">{options}</select></label> '
                '<button class="secondary">Switch</button></form>'
            )
        else:
            parts.append(
                f'<p class="signin">Signed in as {esc(viewer)} (Entra ID token, methods '
                f"{esc(', '.join(signed_in.amr))}, session {esc(signed_in.sid)}).</p>"
            )
        parts.append(f'<p class="muted">Showing proposals for your clients only: {esc(", ".join(clients))}.</p>')
        dry_runs = self._dry_runs({p.client for p in pending})
        cards = "".join(
            self._pending_card(p, viewer, dry_runs.get(_action_key(p.lever, p.client, p.params))) for p in pending
        )
        parts.append(cards or "<p>Nothing pending.</p>")
        if decided:
            done = "".join(
                f"<tr><td>{esc(p.id)}</td><td>{esc(p.client)}</td><td><code>{esc(p.lever)}</code></td>"
                f'<td class="{esc(p.status)}">{esc(p.status)}</td><td>{esc(p.decided_by)}</td>'
                f"<td>{esc(p.decided_at)}</td><td>{esc(_verified(p.verification))}</td></tr>"
                for p in reversed(decided)
            )
            parts.append(
                "<h2>Decided</h2><table><thead><tr><th>Proposal</th><th>Client</th><th>Lever</th><th>Status</th>"
                "<th>Decided by</th><th>At (UTC)</th><th>Requester verification</th></tr></thead>"
                f"<tbody>{done}</tbody></table>"
            )
        return _page("Pending actions", "\n".join(parts))

    def _pending_card(self, p: Proposal, viewer: str, dry_run: Mapping[str, Any] | None) -> str:
        spec = self.queue.runner.registry.get(p.lever)
        upn = p.params.get("upn")
        impact = spec.impact.L1 if spec is not None and spec.impact is not None else "no impact trace registered"
        undo = f"undo lever: {spec.undo}" if spec is not None and spec.undo else NO_UNDO
        reversibility = spec.reversibility if spec is not None else "unknown"
        return (
            f'<section class="proposal"><h2><code>{esc(p.lever)}</code> for {esc(p.client)} '
            f'<span class="tag">{esc(p.id)}</span></h2><dl>'
            f"<dt>Person affected</dt><dd>{esc(upn) if upn is not None else 'no single person in the parameters'}</dd>"
            f"<dt>What it means for them (L1)</dt><dd>{esc(impact)}</dd>"
            f"<dt>What will change (dry-run)</dt><dd>{_diff_html(dry_run)}</dd>"
            f'<dt>Undo</dt><dd>{esc(undo)} <span class="muted">({esc(reversibility)})</span></dd>'
            f"<dt>Parameters</dt><dd>{_params(p.params)}</dd>"
            f"<dt>From</dt><dd>{esc(p.source)} {esc(p.ref)}</dd>"
            f"<dt>Requested by</dt><dd>{esc(p.requested_by)}</dd>"
            f"<dt>Why</dt><dd>{esc(p.reason)}</dd></dl>"
            '<form method="post" action="/decide">'
            f'<input type="hidden" name="csrf" value="{esc(self.csrf_token)}">'
            f'<input type="hidden" name="actor" value="{esc(viewer)}">'
            f"{self._verification_fields(spec)}"
            f'<p class="actions"><button name="act" value="approve:{esc(p.id)}">Approve</button> '
            f'<button name="act" value="reject:{esc(p.id)}" class="secondary">Reject</button></p></form></section>'
        )

    @staticmethod
    def _verification_fields(spec: LeverDef | None) -> str:
        if spec is None or spec.verification != "requester":
            return ""
        methods = "".join(
            f'<option value="{esc(m)}">{esc(METHOD_LABELS.get(m, m))}</option>' for m in VERIFICATION_METHODS
        )
        sources = "".join(f'<option value="{esc(k)}">{esc(v)}</option>' for k, v in NUMBER_ON_FILE_SOURCES.items())
        return (
            '<fieldset class="verify"><legend>Requester verified out of band (required to approve, C-30)</legend>'
            f'<label>How <select name="verified"><option value="">choose a method</option>{methods}</select></label>'
            "<label>For a callback: source of the number on file "
            f'<select name="number_source"><option value="">not a callback</option>{sources}</select></label>'
            '<p class="muted">Never type the phone number here; only its source is recorded.</p></fieldset>'
        )

    def _chains(self) -> dict[str, Path]:
        """Every audit chain on disk by name; a plain single log is one chain called `audit`."""
        audit = self.queue.runner.audit
        if isinstance(audit, AuditRouter):
            return audit.paths()
        return {"audit": audit.path} if audit.path.exists() else {}

    def _review_banner(self) -> str:
        """D6-08: audit each overdue second review once and say so on the page; a failed check says so too."""
        try:
            overdue = self.queue.runner.check_reviews()
        except (ReviewError, AuditError) as exc:
            return f'<p class="banner bad">Second reviews could not be checked: {esc(exc)}</p>'
        if not overdue:
            return ""
        items = ", ".join(f"{r.id} ({r.client}, {r.lever}, due {r.due.isoformat()})" for r in overdue)
        return (
            f'<p class="banner bad">Second review overdue: {esc(items)}. '
            "Complete it with: python -m core.levers complete-review.</p>"
        )

    def _dry_runs(self, clients: set[str]) -> dict[tuple[str, str, bytes], dict[str, Any]]:
        """The latest allowed dry-run audit record for each exact action (lever, client, params).

        With a router only the proposals' own client chains are read, never another client's (B42-2).
        """
        audit = self.queue.runner.audit
        paths = [audit.path_for(c) for c in sorted(clients)] if isinstance(audit, AuditRouter) else [audit.path]
        found: dict[tuple[str, str, bytes], dict[str, Any]] = {}
        for path in paths:
            if not path.exists():
                continue
            for line in path.read_bytes().splitlines():
                try:
                    r = json.loads(line)
                    if r["mode"] == "dry-run" and r["result"]["status"] == "ok" and isinstance(r["params"], dict):
                        found[_action_key(r["lever"], r["client"], r["params"])] = r
                except (ValueError, KeyError, TypeError):
                    continue
        return found

    def _audit(self, verify: bool, chain: str = "") -> Response:
        chains = self._chains()
        if chain and chain not in chains:
            return _error(404, "No such audit chain.")
        # No pick: the first client chain, then the MSP chain (the demo's one-client story opens on the client).
        name = chain or (min(chains, key=lambda n: (n == MSP_LOG, n)) if chains else MSP_LOG)
        path = chains.get(name, self.queue.runner.audit.path)
        lines = path.read_bytes().splitlines() if path.exists() else []
        options = "".join(
            f'<option value="{esc(n)}"{" selected" if n == name else ""}>{esc(n)}</option>' for n in sorted(chains)
        )
        parts = [
            self._review_banner(),
            '<form method="get" action="/audit">'
            f'<label>Chain <select name="client">{options}</select></label> '
            '<button class="secondary">Show</button> <button name="verify" value="1">Verify chain</button></form>',
        ]
        if verify:
            head = head_path_for(path)
            if not lines:
                parts.append('<p class="banner">No audit log yet.</p>')
            else:
                result = verify_chain(path, head if head.exists() else None)
                verdict = (
                    f"OK: {result.records} records, {result.reason}"
                    if result.ok
                    else f"BROKEN at seq {result.broken_seq}: {result.reason}"
                )
                parts.append(f'<p class="banner {"ok" if result.ok else "bad"}">{esc(verdict)}</p>')
        rows = []
        for number, line in reversed(list(enumerate(lines, start=1))[-AUDIT_ROWS:]):
            try:
                r = json.loads(line)
                result_ = r["result"]
                cells = [r["seq"], r["ts"], r["agent"], r["client"], r["lever"], r["mode"], result_["status"]]
                cells += [r["approver"] or ""]
                rows.append(
                    "<tr>" + "".join(f"<td>{esc(c)}</td>" for c in cells) + f"<td>{_params(r['params'])}</td>"
                    f"<td>{esc(result_.get('reason') or ('applied' if result_.get('applied') else ''))}</td></tr>"
                )
            except (ValueError, KeyError, TypeError, AttributeError):
                rows.append(f'<tr><td colspan="10" class="bad">line {number}: unreadable record</td></tr>')
        parts.append(
            f"<p>Newest first; up to {AUDIT_ROWS} records. File: <code>{esc(path.name)}</code> in the state folder.</p>"
            "<table><thead><tr><th>Seq</th><th>Time (UTC)</th><th>Identity</th><th>Client</th><th>Lever</th>"
            "<th>Mode</th><th>Status</th><th>Approver</th><th>Parameters</th><th>Reason</th></tr></thead>"
            f"<tbody>{''.join(rows) or '<tr><td colspan=10>No records yet.</td></tr>'}</tbody></table>"
        )
        return _page("Audit log", "\n".join(parts))

    # -- the one state change ---------------------------------------------------------------

    def _decide(self, headers: Mapping[str, str], body: bytes) -> Response:
        if headers.get("content-type", "").split(";")[0].strip() != "application/x-www-form-urlencoded":
            return _error(415, "Expected a form post.")
        try:
            form = parse_qs(body.decode("ascii"), strict_parsing=True, max_num_fields=8)
        except (UnicodeDecodeError, ValueError):
            return _error(400, "Malformed form.")
        fields = {k: v[0] for k, v in form.items() if len(v) == 1}
        if not hmac.compare_digest(fields.get("csrf", "").encode(), self.csrf_token.encode()):
            return _error(403, "Missing or wrong CSRF token; reload the page and try again.")
        if set(form) - FORM_FIELDS:
            return _error(400, "Unexpected form field. Only the listed choices are accepted; never type a number.")
        verb, _, proposal_id = fields.get("act", "").partition(":")
        if verb not in ("approve", "reject"):
            return _error(400, "Unknown decision.")
        actor = fields.get("actor", "")
        signed_in: ApproverAuth | None = None
        if self.auth is not None:
            authenticated = self._authenticate(headers)
            if isinstance(authenticated, AuthError):
                return self._refuse_unauthenticated(proposal_id, verb, authenticated)
            if actor and actor != authenticated.identity:
                mismatch = AuthError("unknown-approver", "the form names someone other than the signer")
                return self._refuse_unauthenticated(proposal_id, verb, mismatch)
            signed_in, actor = authenticated, authenticated.identity
        elif actor in self.leads:
            signed_in = ApproverAuth.demo(actor)
        verification = None
        if verb == "approve":
            proposal = self.queue.get(proposal_id)
            if proposal is None:
                return _error(409, f"no proposal {proposal_id!r}")
            problem, verification = self._verification(proposal, fields, actor)
            if problem:
                try:
                    seq = self.queue.refuse(proposal_id, actor, problem)
                except DecisionDenied as exc:
                    return _error(403, f"Refused: {exc}")
                except QueueError as exc:
                    return _error(409, str(exc))
                return _error(400, f"Refused: {problem}. Nothing was changed (audit seq {seq}).")
        try:
            decision = self.queue.decide(
                proposal_id, actor, approve=verb == "approve", verification=verification, auth=signed_in
            )
        except DecisionDenied as exc:
            return _error(403, f"Refused: {exc}")
        except QueueError as exc:
            return _error(409, str(exc))
        self._outcomes[decision.proposal.id] = _describe(decision)
        location = f"/?outcome={decision.proposal.id}"
        if self.auth is None and actor != self.leads[0]:
            location += f"&as={actor}"  # actor is a lead id (slug): the queue accepted the decision
        return Response(303, b"", extra_headers=(("Location", location),))

    def _authenticate(self, headers: Mapping[str, str]) -> ApproverAuth | AuthError:
        """The approver the request's bearer token proves (B-89), or why it proves no one."""
        if self.auth is None:
            return AuthError("no-token", "token mode is off")
        scheme, _, token = headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return AuthError("no-token")
        try:
            return self.auth.validate(token.strip(), datetime.now(UTC))
        except AuthError as exc:
            return exc

    @staticmethod
    def _unauthorized(error: AuthError, audit_seq: int | None = None) -> Response:
        challenge = "Bearer" if error.code == "no-token" else 'Bearer error="invalid_token"'
        seq = f" (audit seq {audit_seq})" if audit_seq is not None else ""
        return _error(
            401,
            f"Sign-in required: no accepted Entra ID token ({error.code}). Nothing was changed{seq}.",
            ("WWW-Authenticate", challenge),
        )

    def _refuse_unauthenticated(self, proposal_id: str, verb: str, error: AuthError) -> Response:
        """B89-3: no valid token, no decision. The refusal is audited (the reason code, never the token)."""
        proposal = self.queue.get(proposal_id)
        if proposal is None or proposal.status != "pending":
            return self._unauthorized(error)
        mode: AuditMode = "approve" if verb == "approve" else "reject"  # callers pass only these two
        record = self.queue.runner.audit.append(
            agent=UNAUTHENTICATED,
            client=proposal.client,
            lever=proposal.lever,
            params=dict(proposal.params),
            mode=mode,
            result={
                "status": "denied",
                "reason": f"approver not authenticated: {error.code}",
                "applied": False,
                "proposal": proposal.id,
            },
        )
        return self._unauthorized(error, int(record["seq"]))

    def _verification(
        self, proposal: Proposal, fields: Mapping[str, str], actor: str
    ) -> tuple[str | None, Verification | None]:
        """B03-2: the requester verification the form carries, or why the approval is refused."""
        spec = self.queue.runner.registry.get(proposal.lever)
        needed = spec is not None and spec.verification == "requester"
        method, source = fields.get("verified", ""), fields.get("number_source", "")
        if not method:
            if source:
                return "a number-on-file source was sent without a verification method", None
            if needed:
                return f"{proposal.lever} needs the requester verified out of band first; choose how (C-30)", None
            return None, None
        if method not in VERIFICATION_METHODS:
            return "unknown verification method; choose one from the list", None
        ref = ""
        if method == "callback-on-file":
            if source not in NUMBER_ON_FILE_SOURCES:
                return "a callback needs where the number on file came from; choose a source from the list", None
            ref = NUMBER_ON_FILE_PREFIX + source
        elif source:
            return "a number-on-file source applies only to a callback on the number on file", None
        elif method == "finding-reference":
            ref = proposal.ref
        try:
            verification = Verification.model_validate(
                {"method": method, "by": actor, "at": datetime.now(UTC), "ref": ref}
            )
        except ValueError:
            return "the verification cannot be recorded for this proposal (check the method and its reference)", None
        return None, verification


def check_host(host: str) -> None:
    """SC-3: refuse anything but the IPv4 loopback address."""
    if host != LOOPBACK:
        raise ValueError(f"refusing to bind {host!r}: this page binds {LOOPBACK} only")


def make_server(app: App, host: str = LOOPBACK, port: int = 8765) -> HTTPServer:
    check_host(host)

    class Handler(BaseHTTPRequestHandler):
        server_version = "approval-queue"
        sys_version = ""

        def _dispatch(self) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_BODY:
                response = _error(413, "Request body too large or malformed.")
            else:
                headers = {k.lower(): v for k, v in self.headers.items()}
                response = app.handle(self.command, self.path, headers, self.rfile.read(length))
            self.send_response(response.status)
            for name, value in [*response.headers(), ("Content-Length", str(len(response.body)))]:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(response.body)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _dispatch

    server = HTTPServer((host, port), Handler)
    check_host(str(server.server_address[0]))  # belt and braces: what the socket actually bound
    return server
