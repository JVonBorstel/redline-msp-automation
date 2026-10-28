"""New-hire change plan (B-35, specs/B-35.md; W-ONB-01, W-ONB-02, W-ONB-07; C-05, C-06, C-07, C-29, C-35).

One structured request (form fields, never free text) becomes one ordered plan of dry-run proposals: ``user.new`` (R3,
two distinct leads), ``license.add`` per license, ``group.add-member`` per group, ``mailbox.enable-archive`` when the
role asks for it, then ``user.new-tap``. The plan never executes anything: every step goes through the lever runner in
dry-run mode as the agent identity, so the registry, schema, client scope and pause checks all apply, and every call is
audited. Executing is the leads' act, step by step, through the runner.

Guarantees:
- ``build_plan`` asks ``contact.check`` first; if the requester is not authorized for ``new-account`` it raises
  ``PlanRefused`` with the lever's fixed words and makes no other call (B35-2);
- the license and group lists come from ``roles.json`` (versioned, cited, fails closed), not from code or from the
  request;
- a step the runner or the lever refuses (no free seat, a privileged group) stays in the plan as ``blocked`` with the
  reason; it is never dropped and never worked around;
- a step whose dry-run diff is empty is already done and is left out, so a re-run after a partial execution proposes
  only what remains (B35-3). The steps that follow ``user.new`` cannot be dry-run until the user exists, so while it
  is missing they run against a scratch copy of the tenant folder with ``user.new``'s diff replayed into it. They are
  marked ``simulated`` and are replaced by real dry-runs on the next build;
- ``welcome_and_handoff`` writes two drafts (welcome for the new hire, handoff for the manager) only when a fresh build
  finds nothing left to do. It sends nothing; the sign-in pass value is never read, so it cannot appear in a draft.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from string import Template
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

from core.identity import UnknownIdentity
from core.levers import MockTenant
from core.levers.models import APPROVER_MINIMUM, Change
from core.levers.runner import LeverRunner, mask_change
from workflows.notify import DRAFT_HEADER, TEMPLATES_DIR, load_contacts, template_path

HERE = Path(__file__).resolve().parent
DEFAULT_ROLES_PATH = HERE / "roles.json"
HANDOFF_TEMPLATE = HERE / "handoff.md"
CONTACT_LEVER = "contact.check"
CHANGE_TYPE = "new-account"  # a key of changeTypes in fixtures/psa/contacts-authorized.json
DEFAULT_TECHNICIAN = "tech-ana"
DEFAULT_AGENT = "triage-bot"

_SAFE_VALUE = re.compile(r"^[^\r\n${}<>]{1,120}$")  # the same rule workflows/notify applies to every value
_SLUG = r"^[a-z0-9][a-z0-9-]{0,62}$"
_UPN = r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,48}\.[A-Za-z]{2,}$"
_TEXT = r"^[A-Za-z0-9][A-Za-z0-9 ,&'.@_%+-]{0,112}$"  # same pattern as the user.new parameters
_SKU = r"^[A-Z][A-Z0-9_]{1,63}$"
_GUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


class OnboardingError(ValueError):
    """The request, the role table or a draft step is bad; nothing was proposed or written."""


class PlanRefused(OnboardingError):
    """The requester is not authorized (or could not be checked); no plan was built."""


class PlanIncomplete(OnboardingError):
    """Drafts need every step done, and some are not; nothing was written."""


class NewHireRequest(BaseModel):
    """The form. Every field has a pattern or a type; there is no free-text field and no extra field."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    client: Annotated[str, StringConstraints(pattern=_SLUG)]
    requester: Annotated[str, StringConstraints(pattern=_UPN, max_length=113)]
    upn: Annotated[str, StringConstraints(pattern=_UPN, max_length=113)]
    display_name: Annotated[str, StringConstraints(pattern=_TEXT)]
    job_title: Annotated[str, StringConstraints(pattern=_TEXT)]
    department: Annotated[str, StringConstraints(pattern=_TEXT)]
    manager_upn: Annotated[str, StringConstraints(pattern=_UPN, max_length=113)]
    start_date: date
    role: Annotated[str, StringConstraints(pattern=_SLUG)]


class _RoleSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    licenses: tuple[Annotated[str, StringConstraints(pattern=_SKU)], ...]
    groups: tuple[Annotated[str, StringConstraints(pattern=_GUID)], ...]
    archive: bool


class _ClientRoles(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    roles: dict[Annotated[str, StringConstraints(pattern=_SLUG)], _RoleSpec]


class _RolesFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int
    source: Annotated[str, StringConstraints(min_length=1)]
    clients: dict[Annotated[str, StringConstraints(pattern=_SLUG)], _ClientRoles]


@dataclass(frozen=True)
class RoleTable:
    source: str
    clients: dict[str, dict[str, _RoleSpec]]

    def get(self, client: str, role: str) -> _RoleSpec:
        spec = self.clients.get(client, {}).get(role)
        if spec is None:
            raise OnboardingError(f"no role {role!r} is defined for client {client!r} in roles.json")
        return spec


def load_roles(path: Path = DEFAULT_ROLES_PATH) -> RoleTable:
    """The role bundles. Fails closed on a missing or invalid file or an unknown version."""
    try:
        parsed = _RolesFile.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        raise OnboardingError(f"cannot load the role table from {path}: {exc}") from exc
    if parsed.version != 1:
        raise OnboardingError(f"{path}: unknown version {parsed.version}")
    return RoleTable(parsed.source, {c: dict(v.roles) for c, v in parsed.clients.items()})


def parse_request(raw: Any) -> NewHireRequest:
    """Form fields to a request; anything that is not exactly the form is refused."""
    try:
        return NewHireRequest.model_validate(raw)
    except ValidationError as exc:
        fields = ", ".join(sorted({".".join(str(p) for p in e["loc"]) or "request" for e in exc.errors()}))
        raise OnboardingError(f"the new-hire request is not valid ({fields}); no plan was built") from exc


@dataclass(frozen=True)
class PlanStep:
    lever: str
    params: dict[str, Any]
    status: str  # "proposed" (dry-run ok, diff to apply) or "blocked" (refused; see reason)
    reason: str
    risk_class: str
    approvals_needed: int
    diff: tuple[dict[str, Any], ...]
    simulated: bool  # dry-run on a scratch copy because the user does not exist yet
    audit_seq: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "lever": self.lever,
            "params": dict(self.params),
            "status": self.status,
            "reason": self.reason,
            "risk_class": self.risk_class,
            "approvals_needed": self.approvals_needed,
            "diff": list(self.diff),
            "simulated": self.simulated,
            "audit_seq": self.audit_seq,
            "executed": False,
        }


@dataclass(frozen=True)
class Plan:
    id: str
    client: str
    upn: str
    role: str
    requester: str
    authorization: dict[str, Any]
    steps: tuple[PlanStep, ...]  # the remaining steps, in order
    done: tuple[str, ...]  # steps whose dry-run diff was empty: already in the desired state
    executed: bool = False  # always False: this workflow never runs a write lever

    @property
    def complete(self) -> bool:
        """Nothing is left to propose and nothing is blocked."""
        return not self.steps

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.id,
            "client": self.client,
            "upn": self.upn,
            "role": self.role,
            "requester": self.requester,
            "authorization": self.authorization,
            "steps": [s.as_dict() for s in self.steps],
            "already_done": list(self.done),
            "complete": self.complete,
            "executed": False,
        }


def plan_id(request: NewHireRequest) -> str:
    canonical = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return "ONB-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _label(lever: str, params: dict[str, Any]) -> str:
    extra = params.get("sku") or params.get("group_id")
    return f"{lever} {extra}" if extra else lever


def _candidates(request: NewHireRequest, spec: _RoleSpec) -> list[tuple[str, dict[str, Any]]]:
    steps: list[tuple[str, dict[str, Any]]] = [
        (
            "user.new",
            {
                "upn": request.upn,
                "display_name": request.display_name,
                "job_title": request.job_title,
                "department": request.department,
                "manager_upn": request.manager_upn,
            },
        )
    ]
    steps += [("license.add", {"upn": request.upn, "sku": sku}) for sku in spec.licenses]
    steps += [("group.add-member", {"upn": request.upn, "group_id": gid}) for gid in spec.groups]
    if spec.archive:
        steps.append(("mailbox.enable-archive", {"upn": request.upn}))
    steps.append(("user.new-tap", {"upn": request.upn}))
    return steps


def _replay_into(scratch: Path, client: str, diff: Sequence[Change]) -> None:
    """Apply user.new's ``add`` changes to a scratch tenant folder so the later steps can be dry-run."""
    for change in diff:
        parts = change.path.strip("/").split("/")
        if change.op != "add" or len(parts) != 2 or parts[0] not in ("users", "mailboxes"):
            raise OnboardingError(f"cannot simulate {change.op} {change.path}; no plan was built")
        file = scratch / f"{client}.json" if parts[0] == "users" else scratch / client / "mailboxes.json"
        data = json.loads(file.read_text(encoding="utf-8"))
        data[parts[0]].append(copy.deepcopy(change.after))
        file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _outcome(result: Any) -> tuple[str, str]:
    """``done`` (nothing to change), ``proposed`` or ``blocked`` with the reason, from one dry-run result."""
    if not result.ok:
        return "blocked", result.reason or result.status
    data = result.data
    if isinstance(data, dict) and data.get("outcome") == "refused":
        return "blocked", str(data.get("message") or "refused")
    if not result.diff:
        return "done", ""
    return "proposed", ""


def build_plan(
    runner: LeverRunner,
    request: NewHireRequest,
    *,
    technician: str = DEFAULT_TECHNICIAN,
    agent: str = DEFAULT_AGENT,
    roles: RoleTable | None = None,
) -> Plan:
    """The remaining dry-run steps to get this person working. Raises ``PlanRefused`` or ``OnboardingError``."""
    client = request.client
    check = runner.invoke(
        CONTACT_LEVER,
        {"requester": request.requester, "change_type": CHANGE_TYPE},
        technician,
        client,
        mode="execute",
    )
    if not check.ok:
        raise PlanRefused(f"the requester could not be checked: {check.reason}; no plan was built")
    answer = check.data if isinstance(check.data, dict) else {}
    if answer.get("authorized") is not True:
        raise PlanRefused(f"{answer.get('message') or 'not authorized'}; no plan was built")
    raw_evidence = answer.get("evidence")
    evidence: dict[str, Any] = raw_evidence if isinstance(raw_evidence, dict) else {}
    authorization = {
        "authorized": True,
        "contact_id": evidence.get("contact_id"),
        "source": evidence.get("source"),
        "sets_verification": False,
        "note": "Evidence only. A lead still records the callback on file before approving (C-30).",
    }

    spec = (roles or load_roles()).get(client, request.role)
    steps: list[PlanStep] = []
    done: list[str] = []
    user_state = "done"  # state of user.new, which the later steps depend on
    with tempfile.TemporaryDirectory(prefix="onb-scratch-") as scratch_name:
        step_runner = runner
        for lever, params in _candidates(request, spec):
            simulated = step_runner is not runner
            if lever != "user.new" and user_state == "blocked":
                kind, reason, result = "blocked", "waits for user.new, which is blocked", None
            else:
                result = step_runner.invoke(lever, params, agent, client)
                kind, reason = _outcome(result)
            if lever == "user.new":
                user_state = kind
                if kind == "proposed":
                    scratch = Path(scratch_name) / "tenant"
                    shutil.copytree(runner.tenant.root, scratch)
                    assert result is not None
                    _replay_into(scratch, client, result.diff)
                    step_runner = LeverRunner(
                        runner.registry, runner.identities, MockTenant(scratch), runner.audit, pauses=runner.pauses
                    )
            if kind == "done":
                done.append(_label(lever, params))
                continue
            registry_spec = runner.registry.get(lever)
            risk = (registry_spec.risk_class if registry_spec else None) or "R1"
            shown = tuple(mask_change(c) for c in result.diff) if result is not None and kind == "proposed" else ()
            steps.append(
                PlanStep(
                    lever=lever,
                    params=params,
                    status=kind,
                    reason=reason,
                    risk_class=risk,
                    approvals_needed=APPROVER_MINIMUM[risk],
                    diff=shown,
                    simulated=simulated,
                    audit_seq=result.audit_seq if result is not None else 0,
                )
            )
    pid = plan_id(request)
    return Plan(pid, client, request.upn, request.role, request.requester, authorization, tuple(steps), tuple(done))


# -- drafts (B35-3) ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Drafts:
    plan_id: str
    welcome: str
    handoff: str
    paths: tuple[Path, ...] = ()


def _first_name(tenant: MockTenant, client: str, upn: str) -> str:
    for user in tenant.load(client).get("users", []):
        if isinstance(user, dict) and user.get("userPrincipalName") == upn:
            words = str(user.get("displayName", "")).split()
            if words:
                return words[0]
    raise OnboardingError(f"{upn} is not a user of {client}; no draft was written")


def _group_names(runner: LeverRunner, client: str, ids: Sequence[str]) -> str:
    try:
        groups = json.loads((runner.tenant.root / client / "groups.json").read_text(encoding="utf-8"))
        names = {str(g["id"]): str(g["displayName"]) for g in groups.get("value", []) if isinstance(g, dict)}
    except (OSError, ValueError, KeyError):
        names = {}  # no readable group list: the ids are shown instead of names
    return ", ".join(names.get(g, g) for g in ids) or "none"


def _approver_names(runner: LeverRunner, approvers: Sequence[str]) -> str:
    names = []
    for approver in approvers:
        try:
            who = runner.identities.get(approver)
        except UnknownIdentity as exc:
            raise OnboardingError(f"unknown approver {approver!r}; no draft was written") from exc
        names.append(who.display_name.split(" (")[0].strip() or approver)
    return " and ".join(names)


def _fill(path: Path, values: dict[str, str]) -> str:
    for key, value in values.items():
        if not _SAFE_VALUE.fullmatch(value):
            raise OnboardingError(f"value for ${key} is not a safe single line; no draft was written")
    try:
        body = Template(path.read_text(encoding="utf-8")).substitute(values)
    except (OSError, KeyError, ValueError) as exc:
        raise OnboardingError(f"template {path.name} cannot be filled: {exc}; no draft was written") from exc
    return DRAFT_HEADER + "\n\n" + body.strip() + "\n"


def _write(text: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + f".{os.getpid()}.tmp")
    tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, target)


def welcome_and_handoff(
    runner: LeverRunner,
    request: NewHireRequest,
    *,
    approvers: Sequence[str],
    state_dir: Path,
    technician: str = DEFAULT_TECHNICIAN,
    agent: str = DEFAULT_AGENT,
    roles: RoleTable | None = None,
) -> Drafts:
    """Write the welcome and manager-handoff drafts once every step is done. Never sends. Raises ``PlanIncomplete``."""
    table = roles or load_roles()
    plan = build_plan(runner, request, technician=technician, agent=agent, roles=table)
    if not plan.complete:
        marks = [_label(s.lever, s.params) + (" (blocked)" if s.status == "blocked" else "") for s in plan.steps]
        left = ", ".join(marks)
        raise PlanIncomplete(f"{len(plan.steps)} step(s) are not done yet: {left}; no draft was written")
    if not approvers:
        raise OnboardingError("name the leads who approved the plan; no draft was written")
    contacts = load_contacts()
    contact = contacts.get(request.client)
    if contact is None:
        raise OnboardingError(f"no fast-path contact for client {request.client!r}; no draft was written")
    spec = table.get(request.client, request.role)
    welcome_path = template_path("user.new", TEMPLATES_DIR)
    shared = {"team": contact.team, "fast_phone": contact.fast_phone, "hours": contact.hours}
    welcome = _fill(
        welcome_path,
        {
            "first_name": _first_name(runner.tenant, request.client, request.upn),
            "request": f"your workplace asked for it in onboarding request {plan.id}",
            "approver": _approver_names(runner, approvers),
            **shared,
        },
    )
    handoff = _fill(
        HANDOFF_TEMPLATE,
        {
            "manager_first_name": _first_name(runner.tenant, request.client, request.manager_upn),
            "new_hire_name": request.display_name,
            "job_title": request.job_title,
            "department": request.department,
            "start_date": request.start_date.isoformat(),
            "role": request.role,
            "licenses": ", ".join(spec.licenses) or "none",
            "groups": _group_names(runner, request.client, spec.groups),
            "archive": "on" if spec.archive else "not needed",
            "plan_id": plan.id,
            **shared,
        },
    )
    out = Path(state_dir) / "onboarding" / plan.id
    paths = (out / "welcome.md", out / "handoff.md")
    _write(welcome, paths[0])
    _write(handoff, paths[1])
    return Drafts(plan.id, welcome, handoff, paths)
