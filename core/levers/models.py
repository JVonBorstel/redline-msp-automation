"""Typed shapes for lever definitions, approvals, diffs and invoke results."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from core.identity import Role

Mode = Literal["dry-run", "execute"]
LeverName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9-]*)+$", max_length=64)]
GraphScope = Annotated[StrictStr, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9.]{2,63}$")]
ClientId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")]

_FROZEN = ConfigDict(frozen=True, extra="forbid")

# Risk classes from docs/map/05-governance.md section 6.1 (control C-29). Identity changes are R3 (D-024).
RiskClass = Literal["R0", "R1", "R2", "R3"]
Reversibility = Literal["reversible", "irreversible", "n/a"]
VerificationMethod = Literal["callback-on-file", "in-person", "manager-confirmed", "finding-reference"]
# Where the number called back came from (D6-06). A callback record keeps `ref = number-on-file:<source>`, never the
# number (the same list and prefix as core/queue/store.py, which the approval page offers).
NUMBER_ON_FILE_PREFIX = "number-on-file:"
NUMBER_ON_FILE_SOURCES: tuple[str, ...] = ("psa-contact", "onboarding-form", "client-contact-list")
# Fewest distinct human leads that must approve one execute, by risk class (D6-05, STD-LV-4). A lever or a client
# may raise this number, never lower it (B28-7).
APPROVER_MINIMUM: dict[str, int] = {"R0": 1, "R1": 1, "R2": 1, "R3": 2}
# One line of the impact trace: non-empty, at most 200 characters, no line break.
ImpactLine = Annotated[StrictStr, StringConstraints(min_length=1, max_length=200, pattern=r"^[^\r\n]+$")]


class ParamSpec(BaseModel):
    """Schema for one lever parameter: type, required, enum, max length, regex (and integer bounds)."""

    model_config = _FROZEN

    type: Literal["string", "integer", "boolean"]
    required: bool = False
    description: str = ""
    enum: tuple[str | int, ...] | None = None
    max_length: int | None = Field(default=None, ge=1)
    pattern: str | None = None
    minimum: int | None = None
    maximum: int | None = None

    @model_validator(mode="after")
    def _consistent(self) -> ParamSpec:
        if self.type != "string" and (self.max_length is not None or self.pattern is not None):
            raise ValueError("max_length and pattern apply to string params only")
        if self.type != "integer" and (self.minimum is not None or self.maximum is not None):
            raise ValueError("minimum and maximum apply to integer params only")
        if self.pattern is not None:
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError(f"pattern does not compile: {exc}") from exc
        if self.enum is not None:
            want = str if self.type == "string" else int
            if not self.enum or any(type(v) is not want for v in self.enum):
                raise ValueError(f"enum values must be non-empty and all {self.type}")
        return self


class Impact(BaseModel):
    """Who a lever affects, one line per level: L1 one person, L2 the client business, L3 the MSP, L4 the community."""

    model_config = _FROZEN

    L1: ImpactLine
    L2: ImpactLine
    L3: ImpactLine
    L4: ImpactLine


class LeverCaps(BaseModel):
    """Blast-radius limits of one write lever (B-42, HO-6)."""

    model_config = _FROZEN

    targets_per_run: StrictInt = Field(ge=1)
    executes_per_client_per_hour: StrictInt = Field(ge=1)
    clients_per_day: StrictInt = Field(ge=1)


class LeverDef(BaseModel):
    """One registered lever. Permissions live here, not in the model's output."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    name: LeverName
    description: str = Field(min_length=1)
    client_scope: Literal["any"] | tuple[ClientId, ...]
    required_role: Role
    # Who may ask for a dry-run (a proposal). Defaults to required_role; set lower so agents can
    # propose a write that only a human may execute.
    dry_run_role: Role | None = None
    lever_class: Literal["read", "write"] = Field(alias="class")
    approval: Literal["none", "lead"]
    idempotency_keys: tuple[str, ...] = ()
    params: dict[str, ParamSpec]
    dry_run: bool
    timeout_s: float = Field(gt=0, le=60)
    # B-01 (STD-LV-10). Optional here so a lever built in code keeps working; Registry.load requires
    # risk_class and impact on every write lever in the registry file.
    risk_class: RiskClass | None = None
    reversibility: Reversibility
    undo: LeverName | None = None
    # B-29: this lever is the undo of another one (`user.enable` of `user.disable`). The registry sets the other
    # lever's `undo` when both are loaded, so a registry file that holds only the other lever still loads on its own.
    undo_of: LeverName | None = None
    lever_version: StrictInt = Field(default=1, ge=1)
    impact: Impact | None = None
    # "requester": execute needs an approval that records out-of-band verification (C-30, enforced in B-02).
    # "requester+contact" (B-28, D6-06): also confirmation by the client's authorized contact; the target may not
    # hold a privileged directory role.
    verification: Literal["requester", "requester+contact"] | None = None
    # B-28 (D6-05): raise the number of distinct approvers above the risk class minimum for this lever.
    min_approvers: StrictInt | None = Field(default=None, ge=1, le=10)
    # B-29 (STD-SC-4): least-privilege Microsoft Graph permissions the real adapter would need. Documentation and review
    # input only; the mock never calls Graph, and the names are UNVERIFIED unless the lever's README says otherwise.
    graph_scopes: tuple[GraphScope, ...] = ()
    # B-42 (HO-6): the lever's own caps; without them a write lever gets its risk class default (core/levers/caps.py).
    caps: LeverCaps | None = None
    # B-42 (D6-08): the lever may run only inside the client's business hours or maintenance window.
    window: Literal["business-hours", "maintenance"] | None = None
    # B-42 (D6-08): on a client that opts in, one on-call approval is enough and a second review follows. The runner
    # refuses this path for an irreversible lever, whatever the registry says.
    preauthorized_containment: StrictBool = False

    @model_validator(mode="before")
    @classmethod
    def _defaults_by_class(cls, data: Any) -> Any:
        # Defaults that depend on class: a read lever is R0 and n/a; a write lever is reversible unless it says not.
        if isinstance(data, dict):
            lever_class = data.get("class", data.get("lever_class"))
            if lever_class == "read":
                return {"risk_class": "R0", "reversibility": "n/a", **data}
            if lever_class == "write":
                return {"reversibility": "reversible", **data}
        return data

    @model_validator(mode="after")
    def _safe_by_construction(self) -> LeverDef:
        if self.lever_class == "write" and (self.approval != "lead" or not self.dry_run):
            raise ValueError("a write lever must require lead approval and support dry-run (docs/BLUEPRINT.md rule 5)")
        self._risk_agrees_with_class()
        floor = APPROVER_MINIMUM.get(self.risk_class or "R1", 1)
        if self.min_approvers is not None and self.min_approvers < floor:
            raise ValueError(f"min_approvers {self.min_approvers} is below the {floor} that {self.risk_class} needs")
        unknown = set(self.idempotency_keys) - set(self.params)
        if unknown:
            raise ValueError(f"idempotency_keys name unknown params: {sorted(unknown)}")
        if self.client_scope != "any" and not self.client_scope:
            raise ValueError("client_scope must be 'any' or a non-empty list")
        return self

    def _risk_agrees_with_class(self) -> None:
        if self.lever_class == "read":
            if self.risk_class != "R0":
                raise ValueError(f"a read lever is risk class R0, not {self.risk_class} (governance 6.1)")
            if self.reversibility != "n/a":
                raise ValueError("a read lever's reversibility is 'n/a'")
            if self.verification is not None or self.undo is not None:
                raise ValueError("verification and undo apply to write levers only")
            if self.caps is not None or self.window is not None or self.preauthorized_containment:
                raise ValueError("caps, window and preauthorized_containment apply to write levers only")
            return
        if self.risk_class == "R0":
            raise ValueError("a write lever is risk class R1-R3, not R0 (governance 6.1)")
        if self.reversibility == "n/a":
            raise ValueError("a write lever is 'reversible' or 'irreversible', not 'n/a'")
        if self.reversibility == "irreversible":
            if self.risk_class is not None and self.risk_class != "R3":
                raise ValueError(f"an irreversible lever is risk class R3, not {self.risk_class} (governance 6.1)")
            if self.undo is not None:
                raise ValueError("an irreversible lever cannot name an undo lever")
        if self.undo_of == self.name:
            raise ValueError("a lever cannot be the undo of itself")
        if self.undo == self.name:
            raise ValueError("a lever cannot be its own undo")

    @property
    def proposal_role(self) -> Role:
        return self.dry_run_role or self.required_role

    def allows_client(self, client: str) -> bool:
        return self.client_scope == "any" or client in self.client_scope


class Verification(BaseModel):
    """How the requester was verified out of band before an approval (C-30, governance HO-4)."""

    model_config = _FROZEN

    method: VerificationMethod
    by: StrictStr = Field(min_length=1, max_length=64)
    at: AwareDatetime
    # A short pointer (ticket, finding or call-log id), never a phone number or free text.
    ref: StrictStr = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9._:#/-]*$")

    @model_validator(mode="after")
    def _ref_when_needed(self) -> Verification:
        if self.method == "finding-reference" and not self.ref:
            raise ValueError("method 'finding-reference' needs a ref (the finding id)")
        return self


class ContactConfirmation(BaseModel):
    """The client's authorized contact confirmed the request (D6-06); a human at the MSP records it."""

    model_config = _FROZEN

    by: StrictStr = Field(min_length=1, max_length=64)
    at: AwareDatetime
    # The authorized contact's record id (as kept on the client record), never a name, number or free text.
    contact: StrictStr = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:#/-]+$")


class Approval(BaseModel):
    """A lead's approval, bound to one exact action (lever, client and params)."""

    model_config = _FROZEN

    approver: str = Field(min_length=1, max_length=64)
    lever: str
    client: str
    params: dict[str, StrictStr | StrictInt | StrictBool]
    note: str = Field(default="", max_length=200)
    verification: Verification | None = None
    # B-28: the client's authorized contact confirmed the request (`requester+contact` levers, D6-06).
    contact_verification: ContactConfirmation | None = None
    # B-28: when the approver decided. An irreversible lever executes only on an approval younger than 24 hours.
    approved_at: AwareDatetime | None = None
    # B-28 (B28-6): the approver's Entra ID token, checked by the runner's B-89 validator. Never logged or dumped.
    token: StrictStr | None = Field(default=None, repr=False, exclude=True)
    # B-28 (B28-6): the approval came from the demo identity picker (STD-ID-7); audited as `demo`.
    demo: StrictBool = False
    # B-42 (D6-08): the approver is the on-call lead; for a client that opts in, one such approval can contain.
    on_call: StrictBool = False
    # B-42 (D6-08, RQ-13): a named override of the business-hours or maintenance window. A short name, never free text.
    window_override: StrictStr | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")

    @model_validator(mode="after")
    def _one_way_to_sign_in(self) -> Approval:
        if self.demo and self.token is not None:
            raise ValueError("an approval is either a demo pick or a token, not both")
        return self


class Change(BaseModel):
    """One field-level difference between the tenant state before and after a lever."""

    model_config = _FROZEN

    op: Literal["add", "remove", "replace"]
    path: str
    before: Any = None
    after: Any = None


Status = Literal["ok", "denied", "error"]


class InvokeResult(BaseModel):
    model_config = _FROZEN

    status: Status
    reason: str = ""
    lever: str
    client: str
    identity: str
    mode: str
    approver: str | None = None
    data: Any = None
    diff: tuple[Change, ...] = ()
    applied: bool = False
    audit_seq: int

    @property
    def ok(self) -> bool:
        return self.status == "ok"
