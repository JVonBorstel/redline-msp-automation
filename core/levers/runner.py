"""Invoke a lever with every permission check in code, and audit every call.

Order of checks (a registered lever is needed first, because its schema lives on it):
  0. the lever is registered and the mode is valid (spec check 7), and the lever is not paused
     for this client (kill switch, C-31; B02-1);
  1. params match the lever's schema;
  2. the identity exists, its role is enough for this mode, and it may act for the client;
  3. the lever's client scope includes the client;
  4. execute on an `approval: lead` lever needs a valid approval record, and on a lever marked
     `verification: "requester"` that approval must record how the requester was verified out
     of band (C-30; B02-2);
  5. dry-run is the default: it returns a diff and saves nothing;
  6. the handler runs under the lever's timeout; a late result is discarded and nothing is saved.
A lever with `runtime: "powershell"` passes steps 0-5 here, in Python, first; only then does step 6 call the
PowerShell bridge (core/levers/bridge.py), which kills its child process at the timeout (B-16, SL-06). A write
lever's execute is two calls: a dry-run for the diff, then, after the audit record, the real call, which must
report exactly that diff as applied (B16-3). `runtime: "bash"` (B-66) takes the same path through the bash bridge.
B-28 adds, when the runner is given a `RunnerPolicy` (without one it keeps the W1 behaviour: one lead approval,
no sign-in proof, one global-style serialisation per client only):
  - R2 and R3 approvals must be signed in: an Entra ID token the B-89 validator accepts, or a demo pick that the
    policy allows and the audit marks `demo` (B28-6);
  - an R3 lever needs two approvals from two distinct leads, neither the requester (B28-3); a lever or a client may
    raise the minimum, never lower it (B28-7);
  - an irreversible lever needs approvals younger than 24 hours (B28-5; `undo_notice` is what the page shows);
  - a write whose idempotency key already has an `applied: true` record that another approval authorised is denied
    (B28-1, STD-LV-6a);
  - `verification: "requester+contact"` needs a callback-on-file record (number source, never the number) and the
    client's authorized contact, and refuses a target that holds a directory role (B28-8, D6-06).
Always on: executes serialise per client, so two clients run side by side (B28-2); every record carries
request_id, actor_kind and lever_version (B28-4).
B-42 adds, on an execute of a write lever, inside the per-client lock and before anything is applied:
  - a window check: a lever flagged `window: business-hours` or `maintenance` runs only inside that window on the
    client record; a client with no window is refused, never defaulted; an approval's `window_override` (a name) lets
    it through and the audit record keeps the name (B42-4, D6-08);
  - cap checks: targets per run, executes per client per hour, clients per day, from the lever's registry `caps` or its
    risk class default; the N+1th is denied and audited (B42-1, HO-6);
  - pre-authorized containment: a lever flagged `preauthorized_containment` on a client with
    `containment_preauthorized: true` may execute on one approval marked `on_call`; the runner opens a second review
    due at the end of the next business day, and `check_reviews` audits each overdue one once (B42-5). Sign-in and
    verification rules still apply, and an irreversible lever never takes this path.
The audit may be an `AuditRouter` (one chain per client plus `_msp`, B42-2); a plain `AuditLog` still works.

Allowed or denied, each call writes exactly one audit record (two if saving fails after the
record was written: the second one says so). The audit copy of a diff never carries contact
details or authentication-method details beyond type and id (DR-02, STD-AU-4); the result
returned to the caller keeps the full diff. Pausing and resuming a lever (`pause`, `resume`) are
lead-only, need no approval (IR-2) and each write one audit record.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import json
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from core.audit import AuditError, AuditLog, canonical_json, new_request_id
from core.audit.chain import ActorKind, default_event
from core.audit.router import AuditRouter
from core.auth import AuthError, TokenValidator
from core.identity import IdentityStore, Role, UnknownIdentity, role_satisfies
from core.levers.bridge import BashBridge, BridgeResult, PowerShellBridge
from core.levers.caps import (
    CapDenial,
    CapError,
    CapLedger,
    ClientRules,
    Review,
    ReviewError,
    SecondReviewStore,
)
from core.levers.diff import json_diff
from core.levers.handlers import Handler, LeverFailed
from core.levers.models import (
    APPROVER_MINIMUM,
    NUMBER_ON_FILE_PREFIX,
    NUMBER_ON_FILE_SOURCES,
    Approval,
    Change,
    ContactConfirmation,
    InvokeResult,
    LeverDef,
    Mode,
    Status,
    Verification,
)
from core.levers.pause import Pause, PauseError, PauseStore
from core.levers.registry import Registry
from core.levers.schema import validate_params
from core.levers.tenant import JsonDict, MockTenant, TenantError
from core.obs import OpsLogger, current_request_id

_ops = OpsLogger("lever-runner")

MODES = ("dry-run", "execute")
VERIFICATION_NEEDED = "needs a recorded requester verification (C-30)"
# A verification time this far ahead of the runner's clock is refused (clock skew allowance).
VERIFICATION_CLOCK_SKEW = timedelta(minutes=5)

# DR-02 / STD-AU-4 item 6: what the audit copy of a diff may keep.
MASKED = "[MASKED]"
METHOD_FIELDS_KEPT = ("@odata.type", "id")
CONTACT_KEYS = frozenset(
    {
        "phoneNumber",
        "mobilePhone",
        "businessPhones",
        "faxNumber",
        "otherMails",
        "emailAddress",
        "streetAddress",
        "postalCode",
    }
)
# Backstop for a contact value under an unexpected key: an international phone number.
_PHONE_SHAPE = re.compile(r"\+\d[\d\s().-]{5,}\d")


# B28-5: an approval for an irreversible lever is good for 24 hours.
IRREVERSIBLE_APPROVAL_MAX_AGE = timedelta(hours=24)
RISK_KEYS = ("R1", "R2", "R3")
# Risk classes whose approvers must be signed in (B28-6).
SIGNED_IN_RISKS = frozenset({"R2", "R3"})


class PolicyError(ValueError):
    """The runner policy or a client record is invalid, for example an approver minimum below the class default."""


class RunnerPolicy:
    """Switches on the B-28 rules. Without one, the runner keeps the W1 behaviour.

    `validator` checks approver ID tokens (B-89). `demo` lets the demo identity picker approve (`--demo` only; the
    audit marks it). `client_records` maps a client id to its record; the parts read here are
    `approver_minimum` (risk class to count, raise only) and `authorized_contacts` (record ids of the people who
    may confirm an identity change). A value below the class default fails here, at load (B28-7). B-42 reads the time
    keys too (core/levers/caps.py): a bad `containment_preauthorized` fails here, a bad window is refused when used.
    """

    def __init__(
        self,
        validator: TokenValidator | None = None,
        demo: bool = False,
        client_records: Mapping[str, Mapping[str, Any]] | None = None,
        max_irreversible_age: timedelta = IRREVERSIBLE_APPROVAL_MAX_AGE,
    ) -> None:
        self.validator = validator
        self.demo = demo
        self.max_irreversible_age = min(max_irreversible_age, IRREVERSIBLE_APPROVAL_MAX_AGE)
        self._minimums: dict[str, dict[str, int]] = {}
        self._contacts: dict[str, frozenset[str]] = {}
        self._rules: dict[str, ClientRules] = {}
        for client, record in (client_records or {}).items():
            try:
                self._rules[client] = ClientRules.from_record(record)
            except ValueError as exc:
                raise PolicyError(f"client {client}: {exc}") from exc
            self._minimums[client] = self._parse_minimums(client, record.get("approver_minimum", {}))
            contacts = record.get("authorized_contacts", [])
            if not isinstance(contacts, list | tuple) or not all(isinstance(c, str) and c for c in contacts):
                raise PolicyError(f"client {client}: authorized_contacts must be a list of record ids")
            self._contacts[client] = frozenset(contacts)

    @staticmethod
    def _parse_minimums(client: str, raw: Any) -> dict[str, int]:
        if not isinstance(raw, Mapping):
            raise PolicyError(f"client {client}: approver_minimum must map a risk class to a count")
        out: dict[str, int] = {}
        for risk, count in raw.items():
            if risk not in RISK_KEYS:
                raise PolicyError(f"client {client}: approver_minimum names unknown risk class {risk!r}")
            if type(count) is not int or count < 1:
                raise PolicyError(f"client {client}: approver_minimum for {risk} must be a positive integer")
            if count < APPROVER_MINIMUM[risk]:
                raise PolicyError(
                    f"client {client}: approver_minimum for {risk} is {count}, below {APPROVER_MINIMUM[risk]} (D6-05)"
                )
            out[risk] = count
        return out

    def client_minimum(self, client: str, risk: str) -> int:
        return self._minimums.get(client, {}).get(risk, 0)

    def authorized_contacts(self, client: str) -> frozenset[str]:
        return self._contacts.get(client, frozenset())

    def rules(self, client: str) -> ClientRules:
        """What the client record says about time; a client with no record has no windows (and so is refused)."""
        return self._rules.get(client, ClientRules())


def undo_notice(spec: LeverDef) -> str:
    """What the approval page says about undoing this lever (STD-LV-4): `no undo` for an irreversible one."""
    if spec.reversibility == "irreversible":
        return "no undo"
    return f"undo: {spec.undo}" if spec.undo else ""


@dataclass(frozen=True)
class _Authorized:
    """What passed the checks: the lever, who approved it, and what to write beside the audit record."""

    spec: LeverDef
    approvers: tuple[str, ...] = ()
    verification: Verification | None = None
    contact_verification: ContactConfirmation | None = None
    approval_id: str | None = None
    signins: tuple[dict[str, Any], ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)
    # B-42: written into the audit record's result; the on-call approver when the containment path was taken.
    result_extra: dict[str, Any] = field(default_factory=dict)
    on_call_approver: str | None = None


class _Denied(Exception):
    pass


class _TimedOut(Exception):
    pass


def _method_view(method: Any) -> Any:
    """An authentication method as the audit may hold it: type and id only."""
    if isinstance(method, Mapping):
        return {k: method[k] for k in METHOD_FIELDS_KEPT if k in method}
    return MASKED


def _methods_view(value: Any) -> Any:
    return [_method_view(m) for m in value] if isinstance(value, list) else _scrub(value)


def _masked_field(value: Any) -> Any:
    return None if value is None else MASKED


def _scrub(value: Any) -> Any:
    """Copy of a diff value without contact details; authentication methods keep only type and id."""
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in CONTACT_KEYS:
                out[key] = MASKED
            elif key == "methods" and isinstance(item, list):
                out[key] = [_method_view(m) for m in item]
            else:
                out[key] = _scrub(item)
        return out
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, str) and _PHONE_SHAPE.search(value):
        return MASKED
    return value


def mask_change(change: Change) -> dict[str, Any]:
    """The audit copy of one Change (DR-02). The path stays: it holds only ids and field names."""
    segments = change.path.split("/")
    view: Callable[[Any], Any] = _scrub
    methods_at = next(
        (i for i in range(1, len(segments)) if segments[i] == "methods" and segments[i - 1] == "authentication"),
        None,
    )
    if methods_at is not None:
        depth = len(segments) - methods_at - 1
        if depth == 0:
            view = _methods_view
        elif depth == 1:
            view = _method_view
        elif segments[methods_at + 2] not in METHOD_FIELDS_KEPT:
            view = _masked_field
    elif segments[-1] in CONTACT_KEYS:
        view = _masked_field
    dumped = change.model_dump()
    dumped["before"], dumped["after"] = view(change.before), view(change.after)
    return dumped


def _run_with_timeout(handler: Handler, state: JsonDict, params: Mapping[str, Any], timeout_s: float) -> Any:
    """Run in a daemon thread so a hung handler can neither block the caller nor the interpreter exit.

    Python cannot kill a thread, so a timed-out handler may keep running, but only against its
    private state copy, which is never saved.
    """
    outcome: dict[str, Any] = {}

    def target() -> None:
        try:
            outcome["value"] = handler(state, params)
        except BaseException as exc:  # handed back and re-raised in the caller's thread
            outcome["error"] = exc

    worker = threading.Thread(target=target, name="lever", daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        raise _TimedOut(f"timed out after {timeout_s}s; nothing was applied")
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")


def _idempotency(lever: LeverDef, client: str, params: Mapping[str, Any]) -> str:
    parts = [f"{k}={params.get(k)}" for k in lever.idempotency_keys]
    return "/".join([lever.name, client, *parts])


def _approval_id(lever: str, client: str, params: Mapping[str, Any], approvers: Sequence[str]) -> str:
    """A short stable id for one approval set (lever, client, params, approvers), kept in the audit record."""
    payload = {"lever": lever, "client": client, "params": dict(params), "approvers": sorted(approvers)}
    return "appr-" + hashlib.sha256(canonical_json(payload)).hexdigest()[:24]


def _as_list(approval: Approval | Sequence[Approval] | None) -> list[Approval]:
    if approval is None:
        return []
    return [approval] if isinstance(approval, Approval) else list(approval)


class LeverRunner:
    def __init__(
        self,
        registry: Registry,
        identities: IdentityStore,
        tenant: MockTenant,
        audit: AuditLog | AuditRouter,
        pauses: PauseStore | None = None,
        bridge: PowerShellBridge | None = None,
        policy: RunnerPolicy | None = None,
        bash_bridge: BashBridge | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.registry = registry
        self.identities = identities
        self.tenant = tenant
        self.audit = audit
        # Default: pauses.json beside the audit log, so every runner on the same state sees the same pauses.
        self.pauses = pauses if pauses is not None else PauseStore.beside(audit.path)
        self.policy = policy
        self._clock = clock if clock is not None else (lambda: datetime.now(UTC))
        # B-42: caps are counted from the audit chains; second reviews sit beside them.
        self.ledger = CapLedger(audit)
        self.reviews = SecondReviewStore.beside(audit.path)
        # Executes are load-modify-save on one client's tenant file; one lock per client so two clients run side by
        # side and two executes for one client cannot interleave (SL-05, B28-2).
        self._client_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        # Runs `runtime: "powershell"` levers; the offline mock reads the same tenant folder the runner does.
        self.bridge = bridge if bridge is not None else PowerShellBridge(tenant_dir=tenant.root)
        # Runs `runtime: "bash"` levers (B-66) on the synthetic unix hosts under levers/bash/mock.
        self.bash_bridge = bash_bridge if bash_bridge is not None else BashBridge()

    def _client_lock(self, client: str) -> threading.Lock:
        with self._locks_guard:
            return self._client_locks.setdefault(client, threading.Lock())

    def invoke(
        self,
        lever: str,
        params: Mapping[str, Any],
        identity: str,
        client: str,
        mode: str = "dry-run",
        approval: Approval | Sequence[Approval] | None = None,
    ) -> InvokeResult:
        call = {
            "lever": lever,
            "params": params,
            "identity": identity,
            "client": client,
            "mode": mode,
            "request_id": current_request_id() or new_request_id(),
            "started": time.perf_counter(),
        }
        approvals = _as_list(approval)
        try:
            auth = self._authorize(lever, params, identity, client, mode, approvals)
        except _Denied as denial:
            return self._record(call, "denied", str(denial))
        if mode == "execute":
            with self._client_lock(client):
                if auth.spec.lever_class != "write":
                    return self._run(call, auth)
                if self.policy is not None:
                    denial_reason = self._replay_denial(auth.spec, client, params, auth.approval_id)
                    if denial_reason:
                        return self._record(call, "denied", denial_reason, **self._common(auth, params, client))
                return self._execute_write(call, auth, approvals)
        return self._run(call, auth)

    def _execute_write(self, call: dict[str, Any], auth: _Authorized, approvals: list[Approval]) -> InvokeResult:
        """B-42: window, caps and the second review, in that order, then the run. Called under the client lock."""
        spec, client, params = auth.spec, call["client"], call["params"]
        now = self._clock()
        override = next((a.window_override for a in approvals if a.window_override), None)
        refusal, extra = self._window_gate(spec, client, override, now)
        if refusal:
            return self._deny(call, auth, refusal, extra)
        auth = replace(auth, result_extra={**auth.result_extra, **extra})
        try:
            cap = self.ledger.check(spec, client, params, now)
        except CapError as exc:
            cap = CapDenial(f"cap counts cannot be read, failing closed: {exc}", {"kind": "cap-unreadable"})
        if cap is not None:
            return self._deny(call, auth, cap.reason, cap.detail)
        review: Review | None = None
        if auth.on_call_approver is not None:
            try:
                review = self._open_review(call, auth, now)
            except (ReviewError, AuditError, ValueError) as exc:
                reason = f"the second review could not be opened, failing closed: {exc}"
                return self._deny(call, auth, reason, {"kind": "review-failed"})
            auth = replace(
                auth,
                result_extra={
                    **auth.result_extra,
                    "second_review": {"id": review.id, "due": review.due.isoformat()},
                },
            )
        result = self._run(call, auth)
        if review is not None and result.ok and not result.applied:
            # Nothing changed, so nothing to second-review. An error keeps the review: it may have half applied.
            self.reviews.update(review.id, status="void")
            self._record(
                {**call, "mode": "approve"},
                "ok",
                f"second review {review.id} voided: the action changed nothing",
                result_extra={"kind": "second-review-void", "review_id": review.id},
            )
        return result

    def _deny(self, call: dict[str, Any], auth: _Authorized, reason: str, detail: Mapping[str, Any]) -> InvokeResult:
        common = self._common(auth, call["params"], call["client"])
        common["result_extra"] = {**common["result_extra"], **detail}
        return self._record(call, "denied", reason, **common)

    def _window_gate(
        self, spec: LeverDef, client: str, override: str | None, now: datetime
    ) -> tuple[str, dict[str, Any]]:
        """(refusal, audit detail). The refusal is empty when the lever may run; a named override lets it through."""
        if spec.window is None:
            return "", {}
        rules = self.policy.rules(client) if self.policy is not None else ClientRules()
        refusal = rules.window_refusal(spec.window, now)
        if not refusal:
            return "", {}
        if override is not None:
            return "", {"window_override": {"name": override, "window": spec.window, "bypassed": refusal}}
        return f"{spec.name}: {refusal}; an approval may carry a named window override", {
            "kind": "window-denied",
            "window": spec.window,
        }

    # -- second review (D6-08) --------------------------------------------------------------

    def _open_review(self, call: dict[str, Any], auth: _Authorized, now: datetime) -> Review:
        assert self.policy is not None and auth.on_call_approver is not None
        client = call["client"]
        review = Review(
            id="rev-" + str(call["request_id"]).removeprefix("req-"),
            client=client,
            lever=auth.spec.name,
            params=dict(call["params"]),
            requester=str(call["identity"]),
            on_call_approver=auth.on_call_approver,
            opened_at=now,
            due=self.policy.rules(client).next_business_day_due(now),
        )
        self.reviews.add(review)
        self._record(
            {**call, "mode": "approve"},
            "ok",
            f"second review {review.id} opened, due {review.due.isoformat()} (D6-08)",
            result_extra={
                "kind": "second-review-opened",
                "review_id": review.id,
                "due": review.due.isoformat(),
                "on_call_approver": review.on_call_approver,
            },
        )
        return review

    def check_reviews(self, now: datetime | None = None) -> list[Review]:
        """Audit each overdue second review once (to the MSP chain) and return every overdue one."""
        when = now if now is not None else self._clock()
        overdue = self.reviews.overdue(when)
        for review in overdue:
            if review.overdue_audited:
                continue
            call = {
                "lever": review.lever,
                "params": {"client": review.client, "review_id": review.id},
                "identity": "review-check",
                "client": None,
                "mode": "approve",
            }
            self._record(
                call,
                "error",
                f"second review {review.id} for client {review.client} was due {review.due.isoformat()}; not done",
                result_extra={"kind": "second-review-overdue", "review_id": review.id, "due": review.due.isoformat()},
            )
            self.reviews.update(review.id, overdue_audited=True)
        return overdue

    def complete_review(self, review_id: str, identity: str) -> InvokeResult:
        """A lead other than the on-call approver and the requester completes a review. Audited either way."""
        call: dict[str, Any] = {
            "lever": "second-review",
            "params": {"review_id": review_id},
            "identity": identity,
            "client": None,
            "mode": "approve",
        }
        try:
            review = self.reviews.get(review_id)
        except ReviewError as exc:
            return self._record(call, "error", f"reviews cannot be read, failing closed: {exc}")
        if review is None:
            return self._record(call, "denied", f"no second review {review_id!r}")
        call = {**call, "lever": review.lever, "client": review.client}
        if review.status != "open":
            return self._record(call, "denied", f"second review {review_id} is already {review.status}")
        try:
            who = self.identities.get(identity)
        except UnknownIdentity:
            return self._record(call, "denied", f"unknown identity {identity!r}")
        if who.role is not Role.LEAD or not who.can_act_for(review.client):
            return self._record(call, "denied", f"{identity} is not a lead for client {review.client!r}")
        if identity in (review.on_call_approver, review.requester):
            reason = "the review must come from a lead who neither requested nor approved it"
            return self._record(call, "denied", reason)
        self.reviews.update(review_id, status="completed", completed_by=identity, completed_at=self._clock())
        return self._record(
            call,
            "ok",
            f"second review {review_id} completed",
            approver=identity,
            result_extra={"kind": "second-review-completed", "review_id": review_id},
        )

    # -- pause switch (C-31, IR-2) --------------------------------------------------------

    def pause(self, lever: str, identity: str, reason: str, client: str | None = None) -> InvokeResult:
        """Pause `lever` for every client (client None) or for one client. Lead only; no approval needed."""
        return self._pause_or_resume("pause", lever, identity, reason, client)

    def resume(self, lever: str, identity: str, reason: str, client: str | None = None) -> InvokeResult:
        """Lift the pause on exactly this lever and scope. Lead only."""
        return self._pause_or_resume("resume", lever, identity, reason, client)

    def _pause_or_resume(self, action: str, lever: str, identity: str, reason: str, client: str | None) -> InvokeResult:
        call = {
            "lever": lever,
            "params": {"scope": "all clients" if client is None else "client", "reason": reason},
            "identity": identity,
            "client": client,
            "mode": action,
        }
        try:
            pause = self._authorize_pause(lever, identity, reason, client)
            current = self.pauses.exact(lever, client)
        except _Denied as denial:
            return self._record(call, "denied", str(denial))
        except PauseError as exc:
            return self._record(call, "error", f"{action} not possible: {exc}")
        if action == "pause" and current is not None:
            return self._record(call, "ok", f"already paused by {current.by}: {current.reason}")
        if action == "resume" and current is None:
            return self._record(call, "denied", f"{lever} is not paused for {pause.scope}")
        # Audit first, then flip the switch: the same order as an execute.
        done = "paused" if action == "pause" else "resumed"
        result = self._record(call, "ok", f"{lever} {done} for {pause.scope}", applied=True)
        try:
            if action == "pause":
                self.pauses.add(pause)
            else:
                self.pauses.remove(lever, client)
        except PauseError as exc:
            return self._record(call, "error", f"{action} not saved after audit seq {result.audit_seq}: {exc}")
        return result

    def _authorize_pause(self, lever: str, identity: str, reason: str, client: str | None) -> Pause:
        if self.registry.get(lever) is None:
            raise _Denied(f"lever {lever!r} is not registered")
        try:
            who = self.identities.get(identity)
        except UnknownIdentity:
            raise _Denied(f"unknown identity {identity!r}") from None
        if who.role is not Role.LEAD:
            raise _Denied(f"only a lead may pause or resume a lever ({identity} is {who.role.value})")
        if client is not None and not who.can_act_for(client):
            raise _Denied(f"{identity} is not scoped to client {client!r}")
        try:
            return Pause(lever=lever, client=client, by=identity, reason=reason, at=datetime.now(UTC))
        except ValueError:
            raise _Denied("a pause needs a one-line reason of 1-200 characters and a valid client id") from None

    # -- checks ---------------------------------------------------------------------------

    def _authorize(
        self,
        lever: str,
        params: Mapping[str, Any],
        identity: str,
        client: str,
        mode: str,
        approvals: list[Approval],
    ) -> _Authorized:
        spec = self.registry.get(lever)
        if spec is None:
            raise _Denied(f"lever {lever!r} is not registered")
        if mode not in MODES:
            raise _Denied(f"mode must be one of {', '.join(MODES)}")
        try:
            paused = self.pauses.lookup(lever, client)
        except PauseError as exc:
            raise _Denied(f"lever pause state cannot be read, failing closed: {exc}") from None
        if paused is not None:
            raise _Denied(f"lever paused by {paused.by}: {paused.reason}")

        errors = validate_params(spec.params, params)
        if errors:
            raise _Denied("invalid params: " + "; ".join(errors))

        try:
            who = self.identities.get(identity)
        except UnknownIdentity:
            raise _Denied(f"unknown identity {identity!r}") from None
        needed = spec.required_role if mode == "execute" else spec.proposal_role
        if not role_satisfies(who.role, needed):
            raise _Denied(f"role {who.role.value!r} cannot {mode} {lever} (needs {needed.value})")
        if not who.can_act_for(client):
            raise _Denied(f"{identity} is not scoped to client {client!r}")

        if not spec.allows_client(client):
            raise _Denied(f"lever {lever} is not enabled for client {client!r}")

        if mode == "dry-run":
            if not spec.dry_run:
                raise _Denied(f"lever {lever} does not support dry-run")
            return _Authorized(spec)
        if spec.approval != "lead":
            return _Authorized(spec)
        if not approvals:
            raise _Denied(f"{lever} in execute mode needs a lead approval record")
        if self.policy is None:
            # W1 behaviour: one lead approval is enough, and sign-in is not checked.
            approvers = (self._check_approval(approvals[0], spec, identity, client, params),)
            verification, contact = self._check_verification(approvals[:1], spec, client, params)
            return _Authorized(spec, approvers, verification, contact)
        return self._authorize_strict(approvals, spec, identity, client, params)

    def _authorize_strict(
        self, approvals: list[Approval], spec: LeverDef, requester: str, client: str, params: Mapping[str, Any]
    ) -> _Authorized:
        policy = self.policy
        assert policy is not None
        risk = spec.risk_class or "R1"
        approvers: list[str] = []
        on_call: list[str] = []
        signins: list[dict[str, Any]] = []
        for approval in approvals:
            approver = self._check_approval(approval, spec, requester, client, params)
            if approver in approvers:
                raise _Denied(f"approver {approver} appears twice; approvals must come from distinct leads")
            if risk in SIGNED_IN_RISKS:
                signins.append(self._check_signin(approval, approver))
            if spec.reversibility == "irreversible":
                self._check_fresh(approval, spec)
            approvers.append(approver)
            if approval.on_call:
                on_call.append(approver)
        needed = max(APPROVER_MINIMUM[risk], spec.min_approvers or 0, policy.client_minimum(client, risk))
        containment_by: str | None = None
        not_used = ""
        if len(approvers) < needed and on_call and spec.preauthorized_containment:
            # D6-08: the class default drops to one; a lever or client minimum above the default still stands.
            blocker = "irreversible levers never use this path" if spec.reversibility != "reversible" else ""
            blocker = blocker or policy.rules(client).containment_blocker()
            if blocker:
                not_used = f"; pre-authorized containment not used: {blocker}"
            else:
                needed = max(1, spec.min_approvers or 0, policy.client_minimum(client, risk))
                containment_by = on_call[0]
        if len(approvers) < needed:
            raise _Denied(
                f"{spec.name} is {risk} and needs approvals from {needed} distinct leads "
                f"({len(approvers)} given; HO-3, D6-05){not_used}"
            )
        verification, contact = self._check_verification(approvals, spec, client, params)
        approval_id = _approval_id(spec.name, client, params, approvers)
        result_extra: dict[str, Any] = {}
        if containment_by is not None:
            result_extra["containment"] = {"kind": "pre-authorized", "on_call_approver": containment_by}
        return _Authorized(
            spec,
            tuple(approvers),
            verification,
            contact,
            approval_id,
            tuple(signins),
            {"approvers_required": needed},
            result_extra,
            containment_by,
        )

    def _check_approval(
        self, approval: Approval, spec: LeverDef, requester: str, client: str, params: Mapping[str, Any]
    ) -> str:
        try:
            approver = self.identities.get(approval.approver)
        except UnknownIdentity:
            raise _Denied(f"approval is from unknown identity {approval.approver!r}") from None
        if approver.role is not Role.LEAD:
            raise _Denied(f"approver {approver.id} is not a lead")
        if not approver.can_act_for(client):
            raise _Denied(f"approver {approver.id} is not scoped to client {client!r}")
        if approver.id == requester:
            raise _Denied("requester cannot approve their own action (four-eyes rule)")
        same_target = (approval.lever, approval.client) == (spec.name, client)
        if not same_target or canonical_json(approval.params) != canonical_json(dict(params)):
            raise _Denied("approval does not match this lever, client and params")
        return approver.id

    def _check_signin(self, approval: Approval, approver: str) -> dict[str, Any]:
        """B28-6: an R2 or R3 approval comes from a signed-in approver, or from the demo picker when allowed."""
        policy = self.policy
        assert policy is not None
        if approval.token is not None:
            if policy.validator is None:
                raise _Denied("no token validator is configured; approval refused (failing closed)")
            try:
                auth = policy.validator.validate(approval.token, self._clock())
            except AuthError as exc:
                raise _Denied(f"approver sign-in refused: {exc.code}") from None
            if auth.identity != approver:
                raise _Denied(f"the token belongs to a different identity than approver {approver}")
            return {"approver": approver, "auth": auth.method, "demo": False, "sid": auth.sid}
        if approval.demo:
            if not policy.demo:
                raise _Denied("demo approvals are accepted only when the runner is started with --demo")
            return {"approver": approver, "auth": "demo-picker", "demo": True}
        raise _Denied(f"approver {approver} is not authenticated: R2 and R3 approvals need a validated token")

    def _check_fresh(self, approval: Approval, spec: LeverDef) -> None:
        """B28-5: an irreversible lever executes only on an approval younger than 24 hours."""
        policy = self.policy
        assert policy is not None
        if approval.approved_at is None:
            raise _Denied(f"{spec.name} is irreversible ({undo_notice(spec)}) and needs a timed approval")
        now = self._clock()
        if approval.approved_at > now + VERIFICATION_CLOCK_SKEW:
            raise _Denied("approval time is in the future")
        if now - approval.approved_at >= policy.max_irreversible_age:
            raise _Denied(f"{spec.name} is irreversible ({undo_notice(spec)}); the approval is 24 hours old or older")

    def _replay_denial(self, spec: LeverDef, client: str, params: Mapping[str, Any], approval_id: str | None) -> str:
        """STD-LV-6a, B28-1: an `applied: true` record under this key from another approval blocks a repeat."""
        key = _idempotency(spec, client, params)
        # With a router only this client's chain can hold its records, so only that one is read (B42-2).
        paths = [self.audit.path_for(client)] if isinstance(self.audit, AuditRouter) else [self.audit.path]
        try:
            lines = [line for path in paths if path.exists() for line in path.read_text(encoding="utf-8").splitlines()]
        except OSError as exc:
            return f"audit log cannot be read to check idempotency, failing closed: {exc.__class__.__name__}"
        for line in lines:
            try:
                result = json.loads(line).get("result", {})
            except ValueError:
                continue
            if not isinstance(result, dict) or result.get("idempotency") != key or result.get("applied") is not True:
                continue
            if result.get("approval_id") != approval_id:
                return f"idempotency key {key} was already applied under another approval (STD-LV-6a)"
        return ""

    def _check_verification(
        self, approvals: list[Approval], spec: LeverDef, client: str, params: Mapping[str, Any]
    ) -> tuple[Verification | None, ContactConfirmation | None]:
        """C-30 / D6-06: a lever that changes someone's sign-in needs the requester verified out of band first."""
        if spec.verification is None:
            return None, None
        if spec.verification == "requester":
            callback = next((a.verification for a in approvals if a.verification is not None), None)
        else:
            callback = next(
                (a.verification for a in approvals if a.verification and a.verification.method == "callback-on-file"),
                None,
            )
        if callback is None:
            raise _Denied(f"{spec.name} {VERIFICATION_NEEDED}")
        self._check_verifier(callback, client)
        if spec.verification == "requester":
            return callback, None
        source = (
            callback.ref.removeprefix(NUMBER_ON_FILE_PREFIX) if callback.ref.startswith(NUMBER_ON_FILE_PREFIX) else ""
        )
        if callback.method != "callback-on-file" or source not in NUMBER_ON_FILE_SOURCES:
            raise _Denied(f"{spec.name} needs a callback-on-file record that names where the number on file came from")
        contact = next((a.contact_verification for a in approvals if a.contact_verification is not None), None)
        if contact is None:
            raise _Denied(f"{spec.name} needs confirmation from the client's authorized contact (D6-06)")
        self._check_verifier(contact, client)
        allowed = self.policy.authorized_contacts(client) if self.policy is not None else frozenset()
        if contact.contact not in allowed:
            raise _Denied(f"contact {contact.contact} is not an authorized contact for client {client!r}")
        self._refuse_privileged_target(client, params)
        return callback, contact

    def _check_verifier(self, verification: Verification | ContactConfirmation, client: str) -> None:
        try:
            verifier = self.identities.get(verification.by)
        except UnknownIdentity:
            raise _Denied(f"verification is by unknown identity {verification.by!r}") from None
        if verifier.role is Role.AGENT:
            raise _Denied("a verification must be recorded by a human, not an agent")
        if not verifier.can_act_for(client):
            raise _Denied(f"verifier {verifier.id} is not scoped to client {client!r}")
        if verification.at > self._clock() + VERIFICATION_CLOCK_SKEW:
            raise _Denied("verification time is in the future")

    def _refuse_privileged_target(self, client: str, params: Mapping[str, Any]) -> None:
        """D6-06: an account holding a directory role is never reset on a phone request (human-only procedure)."""
        upn = params.get("upn")
        if not isinstance(upn, str):
            raise _Denied("cannot tell which account this changes, so the privileged-role check cannot run")
        try:
            state = self.tenant.load(client)
        except TenantError as exc:
            raise _Denied(f"tenant state cannot be read for the privileged-role check, failing closed: {exc}") from None
        for role in state.get("directoryRoles", []):
            for member in role.get("members", []) if isinstance(role, Mapping) else []:
                if str(member.get("userPrincipalName", "")).lower() == upn.lower():
                    raise _Denied(f"{upn} holds a privileged directory role; this is a human-only procedure (D6-06)")

    # -- execution ------------------------------------------------------------------------

    def _common(self, auth: _Authorized, params: Mapping[str, Any], client: str) -> dict[str, Any]:
        spec = auth.spec
        return {
            "approver": ",".join(auth.approvers) or None,
            "idempotency": _idempotency(spec, client, params),
            "verification": auth.verification,
            "contact_verification": auth.contact_verification,
            "approval_id": auth.approval_id,
            "signins": list(auth.signins),
            "lever_version": spec.lever_version,
            "result_extra": dict(auth.result_extra),
            **auth.extra,
        }

    def _run(self, call: dict[str, Any], auth: _Authorized) -> InvokeResult:
        spec = auth.spec
        client, params, mode = call["client"], call["params"], call["mode"]
        common = self._common(auth, params, client)
        entry = self.registry.powershell_entry(spec.name)
        if entry is not None:
            return self._run_bridge(call, spec, common, functools.partial(self.bridge.call, entry=entry))
        bash_entry = self.registry.bash_entry(spec.name)
        if bash_entry is not None:
            return self._run_bridge(call, spec, common, functools.partial(self.bash_bridge.call, entry=bash_entry))
        try:
            before = self.tenant.load_for_read(client) if spec.lever_class == "read" else self.tenant.load(client)
            working = copy.deepcopy(before)
            data = _run_with_timeout(self.registry.handler(spec.name), working, dict(params), spec.timeout_s)
        except (_TimedOut, LeverFailed, TenantError) as exc:
            return self._record(call, "error", str(exc), **common)
        except Exception as exc:  # a crashing lever is reported, never raised to the agent (DR-03: key recorded)
            return self._record(call, "error", f"lever crashed: {type(exc).__name__}", **common)

        diff = json_diff(before, working)
        if spec.lever_class == "read" and diff:
            return self._record(call, "error", "read lever tried to change state; discarded", **common)
        if mode == "dry-run" or not diff:
            reason = "dry-run: nothing applied" if mode == "dry-run" else "no change: already in the desired state"
            return self._record(call, "ok", reason, data=data, diff=diff, **common)

        # Audit first, then save: a change is never applied without its record.
        result = self._record(call, "ok", "", data=data, diff=diff, applied=True, **common)
        try:
            self.tenant.save(client, working)
        except TenantError as exc:
            return self._record(call, "error", f"save failed after audit seq {result.audit_seq}: {exc}", **common)
        return result

    def _run_bridge(
        self,
        call: dict[str, Any],
        spec: LeverDef,
        common: dict[str, Any],
        send: Callable[..., BridgeResult],
    ) -> InvokeResult:
        """Run a PowerShell or bash lever through its bridge. Every permission check has already passed (B16-1)."""
        client, params, mode = call["client"], call["params"], call["mode"]
        request_id = call["request_id"]

        def host(host_mode: Mode) -> BridgeResult:
            return send(
                lever=spec.name,
                lever_version=spec.lever_version,
                client=client,
                mode=host_mode,
                params=dict(params),
                timeout_s=spec.timeout_s,
                request_id=request_id,
            )

        # A read lever has no -WhatIf, so the host only runs it as "execute" (B-15); it must report no change.
        first = host("execute" if spec.lever_class == "read" else "dry-run")
        if not first.ok:
            return self._record(call, first.status, first.reason, **common)
        diff = sorted(first.diff, key=lambda change: change.path)
        if spec.lever_class == "read" and (diff or first.applied):
            return self._record(call, "error", "read lever tried to change state; discarded", **common)
        if mode == "dry-run" or not diff:
            reason = "dry-run: nothing applied" if mode == "dry-run" else "no change: already in the desired state"
            return self._record(call, "ok", reason, data=first.data, diff=diff, **common)

        # Audit first, then apply: a change is never applied without its record.
        result = self._record(call, "ok", "", data=first.data, diff=diff, applied=True, **common)
        done = host("execute")
        seq = result.audit_seq
        if not done.ok:
            return self._record(call, "error", f"apply failed after audit seq {seq}: {done.reason}", **common)
        if not done.applied or sorted(done.diff, key=lambda change: change.path) != diff:
            reason = f"apply did not match the dry-run diff after audit seq {seq}; check the target before retrying"
            return self._record(call, "error", reason, **common)
        return result

    def _record(
        self,
        call: dict[str, Any],
        status: Status,
        reason: str,
        *,
        approver: str | None = None,
        data: Any = None,
        diff: list[Change] | None = None,
        applied: bool = False,
        idempotency: str | None = None,
        verification: Verification | None = None,
        contact_verification: ContactConfirmation | None = None,
        approval_id: str | None = None,
        signins: list[dict[str, Any]] | None = None,
        approvers_required: int | None = None,
        lever_version: int | None = None,
        result_extra: Mapping[str, Any] | None = None,
    ) -> InvokeResult:
        changes = tuple(diff or ())
        audit_result: dict[str, Any] = {
            "status": status,
            "reason": reason,
            "applied": applied,
            # Masked copy for the record (DR-02); the caller's InvokeResult keeps the full diff.
            "changes": [mask_change(c) for c in changes],
        }
        if idempotency is not None:
            audit_result["idempotency"] = idempotency
        if verification is not None:
            audit_result["verification"] = verification.model_dump(mode="json")
        if contact_verification is not None:
            audit_result["contact_verification"] = contact_verification.model_dump(mode="json")
        if approval_id is not None:
            audit_result["approval_id"] = approval_id
        if signins:
            # How each approver signed in (B28-6); a demo pick is marked `demo`. The token itself is never kept.
            audit_result["approvals"] = signins
        if approvers_required is not None:
            audit_result["approvers_required"] = approvers_required
        if result_extra:
            # B-42: cap, window, containment and second-review facts (kind, cap, limit, override name, review id).
            audit_result.update(result_extra)
        params = call["params"]
        client = call["client"]
        spec = self.registry.get(str(call["lever"]))
        record = self.audit.append(
            agent=str(call["identity"])[:128],
            client=None if client is None else str(client)[:128],
            lever=str(call["lever"])[:128],
            params=dict(params) if isinstance(params, Mapping) else {"_invalid": repr(params)[:200]},
            mode=call["mode"],  # typed Mode in append; an unknown value is written as "invalid"
            result=audit_result,
            approver=approver,
            actor_kind=self._actor_kind(str(call["identity"])),
            request_id=call.get("request_id"),
            lever_version=lever_version if lever_version is not None else (spec.lever_version if spec else None),
        )
        started = call.get("started")
        _ops.log(
            default_event(str(call["mode"])),
            status,
            client=client if isinstance(client, str) else None,
            request_id=call.get("request_id"),
            duration_ms=round((time.perf_counter() - started) * 1000) if isinstance(started, float) else None,
            lever=call["lever"] if isinstance(call["lever"], str) else None,
            mode=call["mode"] if isinstance(call["mode"], str) else None,
            status=status,
            applied=applied,
            changes=len(changes),
            actor_kind=record["actor_kind"],
            lever_version=record["lever_version"],
            seq=record["seq"],
        )
        return InvokeResult(
            status=status,
            reason=reason,
            lever=str(call["lever"]),
            client="*" if client is None else str(client),
            identity=str(call["identity"]),
            mode=str(call["mode"]),
            approver=approver,
            data=data,
            diff=changes,
            applied=applied,
            audit_seq=record["seq"],
        )

    def _actor_kind(self, identity: str) -> ActorKind:
        """B28-4: an agent identity is an `agent`, any other known one a `human`, an unknown one `unknown`."""
        try:
            who = self.identities.get(identity)
        except UnknownIdentity:
            return "unknown"
        return "agent" if who.role is Role.AGENT else "human"
