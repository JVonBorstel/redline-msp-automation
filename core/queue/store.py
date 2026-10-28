"""Approval queue for pending write-lever proposals (Slice C, specs/slices-abc.md).

Slices A and B propose; a lead decides here. The store is one append-only JSONL file: every
change appends the whole proposal again and the last line for an id wins, so the file is its own
history. Every read and write holds an OS file lock (core.audit.router: msvcrt on Windows, fcntl elsewhere), so the
web page and the CLI can never decide the same proposal twice.

Approve: the proposal is first saved as `approved` (a crash can never leave it pending and let it
run twice), then executed through the lever runner as the requesting technician with an approval
record from the lead, then saved as `executed` or `failed`. The runner re-checks every permission
and writes the audit record that names the approver. Reject: the rejection is audited, the queue
records it, and nothing else changes. A denied decision is audited and changes nothing.

B-03: `propose` dry-runs a proposal through the runner as an agent before it is queued (STD-PR-1,
DR-15); `list(viewer=...)` shows a lead only the proposals for clients in their own list (DR-12);
`refuse` audits an approval the page turned down (STD-PR-4); an approved proposal keeps the
requester verification it was approved with (C-30).

B-89: a decided proposal keeps how the approver signed in (`approver_auth`: method, `amr`, `sid`),
and a reject's audit record carries it too (C-44). The token itself is never stored.
"""

from __future__ import annotations

import hashlib
import shutil
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr, StringConstraints, model_validator

from core.audit import Mode, canonical_json
from core.audit.router import AuditRouter, try_lock, unlock
from core.auth.models import ApproverAuth
from core.identity import IdentityStore, Role, UnknownIdentity
from core.levers import DEFAULT_TENANT_DIR, Approval, InvokeResult, LeverRunner, MockTenant, Registry
from core.levers.models import ClientId, LeverName, Verification, VerificationMethod
from core.levers.schema import validate_params

DEFAULT_STATE_DIR = Path(__file__).resolve().parents[2] / ".tmp" / "demo"
LOCK_TIMEOUT_S = 10.0

Source = Literal["triage", "baseline", "rollback"]
Status = Literal["pending", "approved", "rejected", "executed", "failed"]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")]
OneLine = Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=r"^[^\r\n]*$")]

# C-30 capture (B03-2): the methods a lead may record, and for a callback, where the number on file
# came from. Only the source is ever recorded, never the number itself.
VERIFICATION_METHODS: tuple[str, ...] = get_args(VerificationMethod)
NUMBER_ON_FILE_SOURCES: dict[str, str] = {
    "psa-contact": "PSA contact record for this client",
    "onboarding-form": "client onboarding form (signed by the client)",
    "client-contact-list": "contact list supplied by the client's owner or office manager",
}
NUMBER_ON_FILE_PREFIX = "number-on-file:"


def proposal_id(lever: str, client: str, params: Mapping[str, Any]) -> str:
    """The shared contract: "P-" + first 12 hex of SHA-256 over lever + client + canonical JSON params."""
    digest = hashlib.sha256(lever.encode() + client.encode() + canonical_json(dict(params))).hexdigest()
    return f"P-{digest[:12]}"


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _check_utc(stamp: str) -> None:
    # fromisoformat raises ValueError on junk, which pydantic reports; a naive time has no offset.
    if datetime.fromisoformat(stamp).utcoffset() != timedelta(0):
        raise ValueError(f"timestamp {stamp!r} must be UTC")


class Proposal(BaseModel):
    """A pending write-lever proposal (the shared Slice A/B/C contract)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    source: Source
    ref: Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r"^[^\r\n]*$")]
    lever: LeverName
    client: ClientId
    params: dict[str, StrictStr | StrictInt | StrictBool]
    requested_by: Slug
    reason: OneLine
    created: str
    status: Status = "pending"
    decided_by: Slug | None = None
    decided_at: str | None = None
    # How the requester was verified out of band, kept on the approved record (C-30, B03-2).
    verification: Verification | None = None
    # How the deciding lead signed in (B-89, C-44); set on every decided line, never on a pending one.
    approver_auth: ApproverAuth | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Proposal:
        if self.id != proposal_id(self.lever, self.client, self.params):
            raise ValueError("id does not match the lever, client and params")
        for stamp in (self.created, self.decided_at):
            if stamp is not None:
                _check_utc(stamp)
        pending = self.status == "pending"
        if pending != (self.decided_by is None) or pending != (self.decided_at is None):
            raise ValueError("decided_by and decided_at are set exactly when the status is not pending")
        if self.verification is not None and self.status in ("pending", "rejected"):
            raise ValueError("a verification is recorded only on an approved proposal")
        if self.approver_auth is not None and (pending or self.approver_auth.identity != self.decided_by):
            raise ValueError("approver_auth is recorded only on a decided proposal, for the lead who decided it")
        return self

    @classmethod
    def new(
        cls,
        *,
        source: Source,
        ref: str,
        lever: str,
        client: str,
        params: dict[str, Any],
        requested_by: str,
        reason: str,
    ) -> Proposal:
        return cls(
            id=proposal_id(lever, client, params),
            source=source,
            ref=ref,
            lever=lever,
            client=client,
            params=params,
            requested_by=requested_by,
            reason=reason,
            created=utc_now(),
        )


class QueueError(RuntimeError):
    """The proposal is unknown, invalid or no longer pending, or the queue file cannot be used."""


class DecisionDenied(QueueError):
    """The identity may not decide this proposal. The attempt is audited; nothing else changes."""


@dataclass(frozen=True)
class Decision:
    proposal: Proposal
    audit_seq: int
    result: InvokeResult | None = None  # the runner's execute result, when approved


class ProposalQueue:
    def __init__(self, path: Path, runner: LeverRunner) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.runner = runner

    def add(self, proposal: Proposal) -> Proposal:
        """Store a new pending proposal. Idempotent on id: a known id returns the stored one unchanged."""
        spec = self.runner.registry.get(proposal.lever)
        if spec is None or spec.lever_class != "write":
            raise QueueError(f"{proposal.lever!r} is not a registered write lever")
        errors = validate_params(spec.params, proposal.params)
        if errors:
            raise QueueError("invalid params: " + "; ".join(errors))
        if proposal.status != "pending":
            raise QueueError("only a pending proposal can be added")
        with self._locked():
            existing = self._load().get(proposal.id)
            if existing is not None:
                return existing
            self._append(proposal)
            return proposal

    def propose(self, proposal: Proposal, agent: str) -> tuple[Proposal, InvokeResult | None]:
        """Dry-run `proposal` through the runner as `agent` (audited), then queue it (STD-PR-1, DR-15).

        A proposal already in the queue is returned unchanged with no new dry-run. A dry-run that the
        runner does not allow raises QueueError and nothing is queued; its audit record stays.
        """
        known = self.get(proposal.id)
        if known is not None:
            return known, None
        result = self.runner.invoke(proposal.lever, proposal.params, agent, proposal.client, "dry-run")
        if not result.ok:
            raise QueueError(f"dry-run refused, not queued: {result.reason} (audit seq {result.audit_seq})")
        return self.add(proposal), result

    def get(self, proposal_id: str) -> Proposal | None:
        with self._locked():
            return self._load().get(proposal_id)

    def decide(
        self,
        proposal_id: str,
        approver: str,
        approve: bool,
        verification: Verification | None = None,
        auth: ApproverAuth | None = None,
    ) -> Decision:
        """Approve (execute through the runner) or reject one pending proposal, as `approver`.

        `verification` is how the requester was verified out of band; the runner refuses levers marked
        `verification: "requester"` without it (C-30, B-02). Capturing it on the page is B-03.
        `auth` is how the approver signed in (B-89); it must name `approver` and is kept on the record.
        """
        if auth is not None and auth.identity != approver:
            raise QueueError("the sign-in record names a different approver")
        with self._locked():
            proposal = self._load().get(proposal_id)
            if proposal is None:
                raise QueueError(f"no proposal {proposal_id!r}")
            if proposal.status != "pending":
                raise QueueError(f"{proposal_id} is already {proposal.status}")
            verb: Mode = "approve" if approve else "reject"
            denial = self._denial(proposal, approver)
            if denial:
                seq = self._audit(proposal, approver, verb, "denied", denial)
                raise DecisionDenied(f"{denial} (audit seq {seq})")

            decided = proposal.model_copy(
                update={"decided_by": approver, "decided_at": utc_now(), "approver_auth": auth}
            )
            if not approve:
                reason = "rejected by a lead; nothing was applied"
                seq = self._audit(proposal, approver, verb, "rejected", reason, auth)
                rejected = decided.model_copy(update={"status": "rejected"})
                self._append(rejected)
                return Decision(rejected, seq)

            self._append(decided.model_copy(update={"status": "approved", "verification": verification}))
            approval = Approval(
                approver=approver,
                lever=proposal.lever,
                client=proposal.client,
                params=proposal.params,
                verification=verification,
            )
            result = self.runner.invoke(
                proposal.lever, proposal.params, proposal.requested_by, proposal.client, "execute", approval
            )
            final = decided.model_copy(
                update={"status": "executed" if result.ok else "failed", "verification": verification}
            )
            self._append(final)
            return Decision(final, result.audit_seq, result)

    def refuse(self, proposal_id: str, approver: str, reason: str) -> int:
        """Audit an approval turned down before the runner (B03-2, STD-PR-4); the proposal stays pending.

        If the identity may not decide at all, that denial is the reason recorded and raised instead.
        Returns the audit seq.
        """
        with self._locked():
            proposal = self._load().get(proposal_id)
            if proposal is None:
                raise QueueError(f"no proposal {proposal_id!r}")
            if proposal.status != "pending":
                raise QueueError(f"{proposal_id} is already {proposal.status}")
            denial = self._denial(proposal, approver)
            seq = self._audit(proposal, approver, "approve", "denied", denial or reason)
        if denial:
            raise DecisionDenied(f"{denial} (audit seq {seq})")
        return seq

    def list(self, status: Status | None = None, viewer: str | None = None) -> tuple[Proposal, ...]:
        """Proposals in the order they were first added, optionally only those with `status`.

        With `viewer`, only proposals for clients in that identity's own list (DR-12, TEN-08). An
        unknown viewer sees nothing (fail closed).
        """
        clients: tuple[str, ...] | None = None
        if viewer is not None:
            try:
                clients = self.runner.identities.get(viewer).clients
            except UnknownIdentity:
                return ()
        with self._locked():
            current = self._load()
        return tuple(
            p
            for p in current.values()
            if (status is None or p.status == status) and (clients is None or p.client in clients)
        )

    # -- internals ------------------------------------------------------------------------

    def _denial(self, proposal: Proposal, approver: str) -> str | None:
        try:
            who = self.runner.identities.get(approver)
        except UnknownIdentity:
            return f"unknown identity {approver!r}"
        if who.role is not Role.LEAD:
            return f"{approver} is not a lead"
        if not who.can_act_for(proposal.client):
            return f"{approver} is not scoped to client {proposal.client!r}"
        if approver == proposal.requested_by:
            return "a requester cannot decide their own proposal (four-eyes rule)"
        return None

    def _audit(
        self, proposal: Proposal, actor: str, verb: Mode, status: str, reason: str, auth: ApproverAuth | None = None
    ) -> int:
        result: dict[str, Any] = {"status": status, "reason": reason, "applied": False, "proposal": proposal.id}
        if auth is not None:
            result["approver_auth"] = auth.model_dump(mode="json")
        record = self.runner.audit.append(
            agent=actor[:128],
            client=proposal.client,
            lever=proposal.lever,
            params=dict(proposal.params),
            mode=verb,
            result=result,
        )
        return int(record["seq"])

    def _load(self) -> dict[str, Proposal]:
        current: dict[str, Proposal] = {}
        if not self.path.exists():
            return current
        for number, line in enumerate(self.path.read_bytes().splitlines(), start=1):
            try:
                proposal = Proposal.model_validate_json(line)
            except ValueError as exc:  # pydantic's ValidationError is a ValueError
                raise QueueError(f"{self.path} line {number} is not a valid proposal: {exc}") from exc
            current[proposal.id] = proposal  # a later line for the same id supersedes the earlier one
        return current

    def _append(self, proposal: Proposal) -> None:
        with self.path.open("ab") as fh:
            fh.write(canonical_json(proposal.model_dump(mode="json")) + b"\n")
            fh.flush()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as fh:
            deadline = time.monotonic() + LOCK_TIMEOUT_S
            while not try_lock(fh):
                if time.monotonic() > deadline:
                    raise QueueError(f"queue is locked by another process: {self.lock_path}")
                time.sleep(0.05)
            try:
                yield
            finally:
                unlock(fh)


def open_queue(state_dir: Path = DEFAULT_STATE_DIR) -> ProposalQueue:
    """The queue, runner, mock tenant and audit chains of one state folder (tenant copied from fixtures on first use).

    The audit chains are `<state>/audit/<client>.jsonl` plus `_msp.jsonl`, one router for the page and the CLI (B42-3).
    """
    tenant_dir = Path(state_dir) / "tenant"
    if not tenant_dir.exists():
        shutil.copytree(DEFAULT_TENANT_DIR, tenant_dir)
    audit = AuditRouter(Path(state_dir) / "audit")
    runner = LeverRunner(Registry.load(), IdentityStore.load(), MockTenant(tenant_dir), audit)
    return ProposalQueue(Path(state_dir) / "queue.jsonl", runner)
