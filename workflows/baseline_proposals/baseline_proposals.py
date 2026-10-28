"""Baseline-sourced proposals for stale accounts and expired guests (B-38, specs/B-38.md).

Inventory W-ONB-17, W-IDM-11; controls C-30, C-05, C-32.

For one client this reads the TenantBaseline ``findings.json`` and the client's guest fixture and turns each stale
member (finding ``STALE`` with ``FixLever user.disable``) and each expired, still enabled guest into a ``user.disable``
proposal for the normal queue. Each proposal is dry-run first through the runner (audited, STD-PR-1), carries the
finding id as its ``ref``, and comes with the ``finding-reference`` verification (C-30) the approving lead records.

It proposes only: a lead still approves (IR-3) and nothing here runs a write lever. Break-glass accounts are never
proposed (B38-2); the rule is read from the baseline config, not kept here. At most
``max_proposals_per_client_per_run`` proposals are queued per run and the rest are listed as deferred (B38-3).
No model is called, and dates come from the baseline's ``asOf`` or the caller, never from the clock.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from core.identity import Role
from core.levers import DEFAULT_TENANT_DIR
from core.levers.models import Verification
from core.queue import Proposal, ProposalQueue, QueueError

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.json")
BASELINE_CONFIG_PATH = ROOT / "levers" / "powershell" / "TenantBaseline" / "TenantBaseline.config.json"
GRAPH_FIXTURE_DIR = ROOT / "fixtures" / "graph"
LEVER = "user.disable"
STALE_CHECK = "STALE"
BREAK_GLASS_REASON = "break-glass account: never proposed"
Kind = Literal["stale", "expired-guest"]
_SEVERITY_RANK = {"High": 0, "Medium": 1, "Low": 2}
_GUEST_RANK = 3  # expired guests come after every baseline finding
_SLUG = r"^[a-z0-9][a-z0-9-]{0,62}$"


class BaselineProposalsError(ValueError):
    """The input is bad (config, findings, guests, as-of date); nothing was proposed."""


class WorkflowConfig(BaseModel):
    """The workflow's configuration; unknown keys fail the load (STD-CF-3). Booleans, 0 and negatives are refused."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    version: Literal[1]
    note: str = Field(default="", alias="_note")
    max_proposals_per_client_per_run: StrictInt = Field(ge=1, le=1000)
    requested_by: str = Field(pattern=_SLUG)


class Finding(BaseModel):
    """One findings.json entry (schemas/finding.schema.json). Keys are PascalCase in the file, so they are aliases."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    id: str = Field(alias="Id", pattern=r"^TB-[A-Z]+-[0-9]{2,}$")
    check_id: str = Field(alias="CheckId", pattern=r"^[A-Z][A-Z0-9]{1,31}$")
    severity: Literal["High", "Medium", "Low"] = Field(alias="Severity")
    title: str = Field(alias="Title", min_length=1, max_length=200)
    subject: str = Field(alias="Subject", min_length=1, max_length=256)
    evidence: str = Field(alias="Evidence", min_length=1, max_length=1000)
    fix_lever: str = Field(alias="FixLever", pattern=r"^$|^[a-z][a-z0-9]*(\.[a-z][a-z0-9-]*)+$")
    fix_mode: Literal["dry-run", "manual"] = Field(alias="FixMode")
    fix_target: str = Field(alias="FixTarget", max_length=256)


class Guest(BaseModel):
    """A guest fixture record. Field names are the Graph user property names; ``expiresOn`` is this repo's own."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9._:#/-]{1,64}$")
    displayName: str = Field(min_length=1, max_length=256)
    userPrincipalName: str = Field(min_length=3, max_length=256)
    userType: Literal["Guest"]
    accountEnabled: bool
    expiresOn: str  # UNVERIFIED against Graph


@dataclass(frozen=True)
class BreakGlass:
    prefix: str
    pattern: re.Pattern[str]

    def matches(self, upn: str, display_name: str) -> bool:
        return upn.lower().startswith(self.prefix.lower()) or bool(self.pattern.search(display_name))


@dataclass(frozen=True)
class Candidate:
    ref: str  # the finding id, or the guest record id when the baseline has no finding for that guest
    upn: str
    kind: Kind
    rank: tuple[int, str, str]
    reason: str


@dataclass(frozen=True)
class Proposed:
    """One proposal and where it came from. ``queued`` is False when no queue was given (nothing was dry-run)."""

    proposal: Proposal
    kind: Kind
    ref: str
    status: str
    queued: bool

    def verification(self, by: str, at: datetime) -> Verification:
        """The ``finding-reference`` record the approving lead passes to ``queue.decide``.

        A pending proposal cannot hold a verification, so it is built at approval time.
        """
        return Verification(method="finding-reference", by=by, at=at, ref=self.ref)


@dataclass(frozen=True)
class Deferred:
    ref: str
    upn: str
    kind: Kind
    reason: str


@dataclass(frozen=True)
class Skipped:
    ref: str
    upn: str
    reason: str


@dataclass(frozen=True)
class Plan:
    client: str
    as_of: str
    cap: int
    proposals: list[Proposed] = field(default_factory=list)
    already_queued: list[Proposed] = field(default_factory=list)
    deferred: list[Deferred] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    findings_read: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def nothing_to_propose(self) -> bool:
        return not (self.proposals or self.already_queued or self.deferred)


def _read_json(path: Path, what: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BaselineProposalsError(f"cannot read {what} {path}: {exc}") from exc


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> WorkflowConfig:
    data = _read_json(path, "baseline proposals config")
    try:
        return WorkflowConfig.model_validate(data)
    except ValidationError as exc:
        raise BaselineProposalsError(f"bad baseline proposals config {path}: {exc}") from exc


def _utc(text: str, what: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise BaselineProposalsError(f"{what} {text!r} is not an ISO 8601 date") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _baseline_settings(client: str, path: Path) -> tuple[BreakGlass, Path]:
    """The break-glass rule and this client's graph snapshot folder, both from the baseline's own config."""
    data = _read_json(path, "baseline config")
    try:
        rule = data["breakGlass"]
        prefix, pattern = str(rule["namePrefix"]), str(rule["candidateDisplayNamePattern"])
        tenants: Mapping[str, Any] = data["tenants"]
        info = next(i for name, i in tenants.items() if client == name or client in i.get("aliases", []))
        fixture_dir = str(info["fixtureDir"])
        compiled = re.compile(pattern)
    except (KeyError, TypeError, AttributeError, StopIteration, re.error) as exc:
        raise BaselineProposalsError(
            f"baseline config {path} has no usable break-glass rule or tenant {client!r}"
        ) from exc
    if not prefix:
        raise BaselineProposalsError(f"baseline config {path} has an empty break-glass name prefix")
    return BreakGlass(prefix, compiled), GRAPH_FIXTURE_DIR / fixture_dir


def _directory(snapshot_dir: Path) -> dict[str, dict[str, Any]]:
    """UPN (lower case) -> graph user, from the baseline's snapshot of this client."""
    data = _read_json(snapshot_dir / "users.json", "graph user snapshot")
    users = data.get("value") if isinstance(data, dict) else None
    if not isinstance(users, list):
        raise BaselineProposalsError(f"graph user snapshot in {snapshot_dir} has no 'value' list")
    return {str(u["userPrincipalName"]).lower(): u for u in users if isinstance(u, dict) and "userPrincipalName" in u}


def read_findings(path: Path, client: str) -> tuple[str, list[Finding]]:
    """(asOf, findings) of a TenantBaseline findings.json for ``client``. A file for another tenant is refused."""
    data = _read_json(path, "findings")
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        raise BaselineProposalsError(f"{path} is not a TenantBaseline findings.json (no 'findings' list)")
    if data.get("tenant") != client:
        raise BaselineProposalsError(f"{path} is for tenant {data.get('tenant')!r}, not {client!r}; nothing proposed")
    try:
        findings = [Finding.model_validate(f) for f in data["findings"]]
    except ValidationError as exc:
        raise BaselineProposalsError(f"{path} has a finding that breaks schemas/finding.schema.json: {exc}") from exc
    return str(data.get("asOf") or ""), findings


def read_guests(client: str, tenant_dir: Path) -> list[Guest]:
    """The client's guest fixture; no file means no guests. A file naming another client is refused (C-27)."""
    path = Path(tenant_dir) / client / "guests.json"
    if not path.exists():
        return []
    data = _read_json(path, "guest fixture")
    meta = data.get("_meta") if isinstance(data, dict) else None
    if not isinstance(meta, dict) or meta.get("client") != client or not isinstance(data.get("value"), list):
        raise BaselineProposalsError(f"{path} does not belong to {client!r} or has no 'value' list")
    try:
        return [Guest.model_validate(g) for g in data["value"]]
    except ValidationError as exc:
        raise BaselineProposalsError(f"{path} has a bad guest record: {exc}") from exc


def _stale_candidates(
    findings: list[Finding], directory: dict[str, dict[str, Any]], break_glass: BreakGlass, result: Plan
) -> dict[str, Candidate]:
    found: dict[str, Candidate] = {}
    for f in findings:
        if f.check_id != STALE_CHECK or f.fix_lever != LEVER:
            continue  # not ours: only stale accounts whose fix is user.disable
        user = directory.get(f.subject.lower())
        if user is None:
            if break_glass.matches(f.subject, ""):
                reason = BREAK_GLASS_REASON
            else:
                reason = "not in this client's directory snapshot, so break-glass cannot be checked"
            result.skipped.append(Skipped(f.id, f.subject, reason))
        elif break_glass.matches(f.subject, str(user.get("displayName") or "")):
            result.skipped.append(Skipped(f.id, f.subject, BREAK_GLASS_REASON))
        elif user.get("accountEnabled") is False:
            result.skipped.append(Skipped(f.id, f.subject, "already disabled"))
        else:
            why = f"Baseline finding {f.id}: no successful sign-in within the stale limit; disable after lead review"
            found[f.subject.lower()] = Candidate(f.id, f.subject, "stale", (_SEVERITY_RANK[f.severity], "", f.id), why)
    return found


def _guest_candidates(
    guests: list[Guest], cutoff: datetime, break_glass: BreakGlass, found: dict[str, Candidate], result: Plan
) -> None:
    for g in guests:
        upn = g.userPrincipalName
        try:
            expires = _utc(g.expiresOn, f"guest {g.id} expiresOn")
        except BaselineProposalsError as exc:
            result.skipped.append(Skipped(g.id, upn, f"{exc}; not proposed"))
            continue
        if break_glass.matches(upn, g.displayName):
            result.skipped.append(Skipped(g.id, upn, BREAK_GLASS_REASON))
        elif not g.accountEnabled:
            result.skipped.append(Skipped(g.id, upn, "already disabled"))
        elif expires >= cutoff:
            result.skipped.append(Skipped(g.id, upn, f"guest access runs until {g.expiresOn}: not expired"))
        elif upn.lower() in found:
            twin = found[upn.lower()].ref
            result.notes.append(f"{g.id} ({upn}) is also baseline finding {twin}; proposed once, under {twin}")
        else:
            why = f"Guest access {g.id} expired on {g.expiresOn}; disable after lead review"
            found[upn.lower()] = Candidate(g.id, upn, "expired-guest", (_GUEST_RANK, g.expiresOn, g.id), why)


def _requester(queue: ProposalQueue | None, client: str, agent: str) -> str:
    """The identity that owns the request: the queue executes as it, and ``user.disable`` needs a technician to execute.

    The agent only dry-runs. The first technician (by id) who may act for ``client`` is named as requester, so the
    lead is a different person (four-eyes). With no queue nothing is executed, so the agent is named.
    """
    if queue is None:
        return agent
    for who in sorted(queue.runner.identities, key=lambda i: i.id):
        if who.role is Role.TECHNICIAN and who.can_act_for(client):
            return who.id
    raise BaselineProposalsError(f"no technician identity may act for client {client!r}, so nobody can own the request")


def plan(
    client: str,
    findings_path: Path,
    queue: ProposalQueue | None = None,
    *,
    config: WorkflowConfig | None = None,
    tenant_dir: Path = DEFAULT_TENANT_DIR,
    baseline_config: Path = BASELINE_CONFIG_PATH,
    as_of: str | None = None,
) -> Plan:
    """Propose ``user.disable`` for ``client``'s stale members and expired guests; queue them if a ``queue`` is given.

    Without a queue nothing is dry-run or stored and each proposal is marked ``unqueued``. A dry-run the runner
    refuses is listed under ``skipped`` ("not queued: ...") and does not use the cap.
    """
    cfg = config or load_config()
    break_glass, snapshot_dir = _baseline_settings(client, baseline_config)
    directory = _directory(snapshot_dir)
    file_as_of, findings = read_findings(findings_path, client)
    as_of_text = as_of or file_as_of
    if not as_of_text:
        raise BaselineProposalsError("no as-of date: the findings file has no asOf and none was given")
    cutoff = _utc(as_of_text, "as-of date")
    cap = cfg.max_proposals_per_client_per_run
    result = Plan(client=client, as_of=as_of_text, cap=cap, findings_read=len(findings))

    found = _stale_candidates(findings, directory, break_glass, result)
    _guest_candidates(read_guests(client, tenant_dir), cutoff, break_glass, found, result)

    requester = _requester(queue, client, cfg.requested_by)
    for cand in sorted(found.values(), key=lambda c: c.rank):
        proposal = Proposal.new(
            source="baseline",
            ref=cand.ref,
            lever=LEVER,
            client=client,
            params={"upn": cand.upn, "reason": cand.reason[:200]},
            requested_by=requester,
            reason=cand.reason[:200],
        )
        known = queue.get(proposal.id) if queue is not None else None
        if known is not None:
            result.already_queued.append(Proposed(known, cand.kind, cand.ref, known.status, True))
        elif len(result.proposals) >= cap:
            why = f"over the cap of {cap} proposals per client per run; a later run picks it up"
            result.deferred.append(Deferred(cand.ref, cand.upn, cand.kind, why))
        elif queue is None:
            result.proposals.append(Proposed(proposal, cand.kind, cand.ref, "unqueued", False))
        else:
            try:
                queued, _ = queue.propose(proposal, cfg.requested_by)
            except QueueError as exc:
                result.skipped.append(Skipped(cand.ref, cand.upn, f"not queued: {exc}"))
            else:
                result.proposals.append(Proposed(queued, cand.kind, cand.ref, queued.status, True))
    return result


def _item(p: Proposed) -> dict[str, Any]:
    return {
        "proposal_id": p.proposal.id,
        "ref": p.ref,
        "kind": p.kind,
        "upn": p.proposal.params["upn"],
        "status": p.status,
        "queued": p.queued,
        "verification": {"method": "finding-reference", "ref": p.ref},
    }


def summary(result: Plan) -> dict[str, Any]:
    return {
        "client": result.client,
        "as_of": result.as_of,
        "cap": result.cap,
        "findings_read": result.findings_read,
        "nothing_to_propose": result.nothing_to_propose,
        "proposals": [_item(p) for p in result.proposals],
        "already_queued": [_item(p) for p in result.already_queued],
        "deferred": [vars(d) for d in result.deferred],
        "skipped": [vars(s) for s in result.skipped],
        "notes": list(result.notes),
        "executed": False,  # this workflow never runs a write lever
    }
