"""Model and tool approval records and the checker that holds the repo to them (B-93; W-GOV-02; C-28, C-43).

``governance/model_tool_approvals.json`` holds one request record per thing that may run: a model, a provider, the
MCP server, a lever namespace or an adapter. A record names an owner role, a purpose, the data classes, the risk
class, evidence links (an eval report, a contract test, a redaction test), the reviewer roles that decided and a
rollback. ``check`` fails when something in ``config/models.json``, the lever registry, ``adapters/`` or the MCP server
has no approved, in-date record, when an approval cites evidence that is not in the repo, when a reviewer rule is
broken, and when ``governance/ai-vendor-register.json`` holds an approved vendor that no approved provider record
authorises (the register is reached only through this process).

What it does not do: it reads files and the date it is given, never a network or a model. It proves a cited test is
defined in its file (a ``def name(`` match), not that the test passes or still checks the claim. It records that roles
approved; it cannot prove a person was who the role says. Not a certification, an attestation or legal advice.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from core.gateway.gateway import HOSTED_PROVIDERS
from core.gateway.vendor_register import VendorRegister
from core.paths import REPO_ROOT

RECORDS_FILE = Path("governance/model_tool_approvals.json")
SCHEMA_FILE = Path("governance/model_tool_approval.schema.json")
MODELS_FILE = Path("config/models.json")
REGISTER_FILE = Path("governance/ai-vendor-register.json")

Kind = Literal["model", "provider", "mcp-server", "lever-namespace", "adapter"]
Role = Literal[
    "technician",
    "automation-engineer",
    "lead",
    "technical-reviewer",
    "ai-change-approver",
    "security-lead",
    "compliance-owner",
]
ReviewerRole = Literal["technical-reviewer", "ai-change-approver", "security-lead", "compliance-owner"]
EvidenceType = Literal["eval_report", "contract_test", "redaction_test"]
RiskClass = Literal["R0", "R1", "R2", "R3"]
DataClassId = Literal["DC-0", "DC-1", "DC-2", "DC-3", "DC-4", "DC-5", "DC-6"]
Status = Literal["draft", "approved", "revoked", "rejected"]

REQUIRED_EVIDENCE: Mapping[str, tuple[EvidenceType, ...]] = {
    "model": ("eval_report", "redaction_test"),
    "provider": ("contract_test", "redaction_test"),
    "mcp-server": ("contract_test", "redaction_test"),
    "lever-namespace": ("contract_test", "redaction_test"),
    "adapter": ("contract_test", "redaction_test"),
}
EXTRA_APPROVERS: tuple[ReviewerRole, ...] = ("security-lead", "compliance-owner")
CODES: tuple[str, ...] = (
    "missing-record",
    "not-approved",
    "expired",
    "not-yet-in-effect",
    "duplicate-subject",
    "evidence-required",
    "evidence-missing",
    "evidence-bad-ref",
    "approver-missing",
    "self-approval",
    "reviewer-rejected",
    "review-after-approval",
    "hosting-mismatch",
    "baa-required",
    "vendor-unknown",
    "vendor-wrong-provider",
    "vendor-not-approved",
    "vendor-overdue",
    "vendor-classes-exceed",
    "vendor-unrecorded",
)
_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")
_TEST_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ApprovalError(ValueError):
    """A records file or an input of the check is unreadable or invalid."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Evidence(_Strict):
    type: EvidenceType = Field(description="What kind of evidence this link is.")
    ref: str = Field(
        min_length=1,
        max_length=200,
        description="Repo-relative path; a test link is path::test_name. Must exist when the record is checked.",
    )


class Reviewer(_Strict):
    role: ReviewerRole = Field(description="The role that decided, never a person's name.")
    decision: Literal["approve", "reject"]
    on: date = Field(description="The day the decision was recorded.")


class ApprovalRecord(_Strict):
    id: str = Field(pattern=r"^AC-\d{3}$", description="Request id, AC-nnn.")
    kind: Kind = Field(description="What is being approved.")
    subject: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,100}$",
        description="model: provider/model-name; provider: name; mcp-server: server name; "
        "lever-namespace: the part of a lever name before the dot; adapter: folder name under adapters/.",
    )
    title: str = Field(min_length=1, max_length=120)
    inventory_ids: tuple[str, ...] = Field(min_length=1, description="Work inventory ids (W-AREA-nn) it serves.")
    owner_role: str = Field(pattern=r"^[a-z][a-z0-9-]{2,40}$", description="Role that owns it, never a person's name.")
    proposed_by_role: Role = Field(description="Role that proposed it. It may not also approve it.")
    purpose: str = Field(min_length=1, max_length=300, description="What it is for and what it is not for.")
    risk_class: RiskClass
    data_classes: tuple[DataClassId, ...] = Field(min_length=1, description="Every class it may touch. DC-6 never.")
    hosting: Literal["local", "hosted", "none"] = Field(
        description="Where it runs. hosted needs terms and a vendor id."
    )
    retention_terms: str | None = Field(max_length=400, description="Provider retention and training terms (hosted).")
    baa_status: Literal["not-applicable", "signed", "none"]
    zdr_status: Literal["not-applicable", "confirmed", "none"]
    vendor_approval_id: str | None = Field(
        pattern=r"^[a-z][a-z0-9-]{2,63}$", description="Entry id in governance/ai-vendor-register.json (hosted only)."
    )
    evidence: tuple[Evidence, ...]
    reviewers: tuple[Reviewer, ...]
    rollback: str = Field(min_length=1, max_length=400, description="How to switch it off and what that changes.")
    status: Status
    approved_on: date | None
    review_date: date | None = Field(description="After this day the approval stops covering anything.")

    @field_validator("inventory_ids")
    @classmethod
    def _inventory(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            if not re.fullmatch(r"W-[A-Z]{2,6}-\d{2}", item):
                raise ValueError(f"{item!r} is not an inventory id (W-AREA-nn)")
        return value

    @field_validator("data_classes")
    @classmethod
    def _no_secrets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if "DC-6" in value:
            raise ValueError("DC-6 (credentials and secrets) is never an approved data class")
        return value

    @model_validator(mode="after")
    def _complete(self) -> Self:
        if self.hosting == "hosted":
            if not self.retention_terms:
                raise ValueError("a hosted record needs retention_terms")
            if not self.vendor_approval_id:
                raise ValueError("a hosted record needs vendor_approval_id")
        elif self.vendor_approval_id:
            raise ValueError("vendor_approval_id belongs only on a hosted record")
        if self.status == "approved":
            if self.approved_on is None or self.review_date is None:
                raise ValueError("an approved record needs approved_on and review_date")
            if self.approved_on > self.review_date:
                raise ValueError("approved_on is after review_date")
            if not self.reviewers:
                raise ValueError("an approved record needs reviewers")
        return self


class ApprovalFile(_Strict):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    version: Literal[1]
    data_basis: Literal["synthetic"]
    note: str = Field(default="", alias="_note")
    records: tuple[ApprovalRecord, ...]

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        ids = [r.id for r in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate record ids")
        return self

    @classmethod
    def load(cls, path: Path) -> Self:
        try:
            return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, ValidationError) as exc:
            raise ApprovalError(f"cannot load {path}: {exc}") from exc


@dataclass(frozen=True, slots=True)
class Problem:
    code: str
    record_id: str
    detail: str

    def __str__(self) -> str:
        return f"{self.record_id} {self.code}: {self.detail}"


@dataclass(frozen=True, slots=True)
class World:
    """What exists in the repo and must therefore be approved."""

    config: dict[str, Any]
    lever_names: tuple[str, ...]
    adapters: tuple[str, ...]
    mcp_servers: tuple[str, ...]
    vendors: VendorRegister

    def replace(self, **changes: Any) -> World:
        return replace(self, **changes)


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ApprovalError(f"cannot read {path}: {exc}") from exc


def load_world(root: Path = REPO_ROOT) -> World:
    config = _json(root / MODELS_FILE)
    if not isinstance(config, dict) or not isinstance(config.get("providers"), dict):
        raise ApprovalError("config/models.json has no providers object")
    levers: list[str] = []
    for file in [root / "levers" / "registry.json", *sorted((root / "levers" / "registry.d").glob("*.json"))]:
        document = _json(file)
        entries = document.get("levers", []) if isinstance(document, dict) else []
        levers += [str(entry["name"]) for entry in entries if isinstance(entry, dict) and "name" in entry]
    adapters = sorted(p.name for p in (root / "adapters").iterdir() if p.is_dir() and (p / "__init__.py").is_file())
    servers: list[str] = []
    server_file = root / "mcp" / "server.py"
    if server_file.is_file():
        match = re.search(r'^SERVER_NAME\s*=\s*"([^"]+)"', server_file.read_text(encoding="utf-8"), flags=re.M)
        if match:
            servers.append(match.group(1))
    try:
        vendors = VendorRegister.load(root / REGISTER_FILE)
    except (OSError, ValueError) as exc:
        raise ApprovalError(f"cannot load the vendor register: {exc}") from exc
    return World(config, tuple(levers), tuple(adapters), tuple(servers), vendors)


def required(world: World) -> dict[tuple[str, str], str]:
    """Every (kind, subject) that must have an approved, in-date record, with the line to print if it has none."""
    need: dict[tuple[str, str], str] = {}
    tail = "but has no approved, in-date record"
    for provider, cfg in world.config["providers"].items():
        if cfg.get("enabled"):
            need[("provider", provider)] = f"provider {provider} is enabled in config/models.json {tail}"
        for name in dict(cfg.get("models", {})).values():
            need[("model", f"{provider}/{name}")] = f"model {provider}/{name} is in config/models.json {tail}"
    for lever in world.lever_names:
        space = lever.split(".")[0]
        need.setdefault(
            ("lever-namespace", space), f"lever namespace {space} (lever {lever}) is in the lever registry {tail}"
        )
    for adapter in world.adapters:
        need[("adapter", adapter)] = f"adapter {adapter} is in adapters/ {tail}"
    for server in world.mcp_servers:
        need[("mcp-server", server)] = f"mcp-server {server} is in mcp/server.py {tail}"
    return need


def _standing(rec: ApprovalRecord, today: date) -> str | None:
    """None when the record approves today, else the code that says why not."""
    if rec.status != "approved":
        return "not-approved"
    if rec.approved_on is not None and rec.approved_on > today:
        return "not-yet-in-effect"
    if rec.review_date is not None and today > rec.review_date:
        return "expired"
    return None


def _provider_of(rec: ApprovalRecord) -> str:
    return rec.subject.split("/")[0]


def _evidence(rec: ApprovalRecord, root: Path) -> list[Problem]:
    out: list[Problem] = []
    have = {e.type for e in rec.evidence}
    for needed in REQUIRED_EVIDENCE[rec.kind]:
        if needed not in have:
            out.append(
                Problem("evidence-required", rec.id, f"{rec.kind} {rec.subject} needs evidence of type {needed}")
            )
    for item in rec.evidence:
        path_part, _, name = item.ref.partition("::")
        is_test = item.type != "eval_report"
        in_place = path_part.startswith("tests/") if is_test else path_part.startswith("evals/")
        bad = (
            not _PATH.fullmatch(path_part)
            or ".." in path_part.split("/")
            or not in_place
            or (is_test and (not path_part.endswith(".py") or not _TEST_NAME.fullmatch(name)))
            or (not is_test and "::" in item.ref)
        )
        if bad:
            where = "tests/<file>.py::test_name" if is_test else "a file under evals/"
            out.append(Problem("evidence-bad-ref", rec.id, f"{item.type} {item.ref!r} must be {where}"))
            continue
        file = root / path_part
        if not file.is_file():
            out.append(Problem("evidence-missing", rec.id, f"{item.type} file {path_part} does not exist"))
        elif is_test and not re.search(
            rf"^\s*(?:async\s+)?def {re.escape(name)}\(", file.read_text(encoding="utf-8"), flags=re.M
        ):
            out.append(Problem("evidence-missing", rec.id, f"{item.type} {name} is not defined in {path_part}"))
    return out


def _reviewers(rec: ApprovalRecord) -> list[Problem]:
    out: list[Problem] = []
    approving = {r.role for r in rec.reviewers if r.decision == "approve"}
    if any(r.decision == "reject" for r in rec.reviewers):
        out.append(Problem("reviewer-rejected", rec.id, "a reviewer rejected this request"))
    needed: set[str] = {"ai-change-approver"}
    heavy = rec.risk_class in ("R2", "R3") or rec.hosting == "hosted" or bool({"DC-4", "DC-5"} & set(rec.data_classes))
    if heavy:
        needed |= set(EXTRA_APPROVERS)
    for role in sorted(needed - approving):
        out.append(
            Problem("approver-missing", rec.id, f"{role} has not approved (needed for this risk, class or hosting)")
        )
    if rec.proposed_by_role in approving:
        out.append(Problem("self-approval", rec.id, f"{rec.proposed_by_role} proposed this and also approved it"))
    if rec.approved_on is not None:
        for review in rec.reviewers:
            if review.on > rec.approved_on:
                out.append(
                    Problem("review-after-approval", rec.id, f"{review.role} decided on {review.on}, after approval")
                )
    return out


def _hosting(rec: ApprovalRecord) -> list[Problem]:
    out: list[Problem] = []
    if rec.kind in ("model", "provider"):
        expected = "hosted" if _provider_of(rec) in HOSTED_PROVIDERS else "local"
        if rec.hosting != expected:
            out.append(
                Problem(
                    "hosting-mismatch",
                    rec.id,
                    f"provider {_provider_of(rec)} runs {expected}, record says {rec.hosting}",
                )
            )
    if rec.hosting == "hosted":
        classes = set(rec.data_classes)
        if "DC-4" in classes and rec.baa_status != "signed":
            out.append(Problem("baa-required", rec.id, "DC-4 on a hosted route needs a signed BAA for that service"))
        if "DC-5" in classes and rec.baa_status != "signed" and rec.zdr_status != "confirmed":
            out.append(Problem("baa-required", rec.id, "DC-5 on a hosted route needs a signed BAA or confirmed ZDR"))
    return out


def _vendor(rec: ApprovalRecord, world: World, today: date) -> list[Problem]:
    if not rec.vendor_approval_id:
        return []
    entry = world.vendors.get(rec.vendor_approval_id)
    if entry is None:
        return [Problem("vendor-unknown", rec.id, f"{rec.vendor_approval_id} is not in the vendor register")]
    out: list[Problem] = []
    if entry.provider != _provider_of(rec):
        out.append(Problem("vendor-wrong-provider", rec.id, f"{entry.id} is for {entry.provider}"))
    if entry.status != "approved":
        out.append(Problem("vendor-not-approved", rec.id, f"{entry.id} is {entry.status} in the vendor register"))
    elif entry.review_date is None or today > entry.review_date:
        out.append(Problem("vendor-overdue", rec.id, f"{entry.id} passed its review date"))
    extra = sorted(set(entry.allowed_data_classes) - set(rec.data_classes))
    if extra:
        out.append(
            Problem("vendor-classes-exceed", rec.id, f"{entry.id} allows {', '.join(extra)}, which the record does not")
        )
    return out


def check(file: ApprovalFile, world: World, root: Path, today: date) -> list[Problem]:
    """Every way the repo is not held by an approved, in-date, evidenced record. Empty means clean."""
    problems: list[Problem] = []
    need = required(world)
    counts = Counter((r.kind, r.subject) for r in file.records)
    for (kind, subject), n in sorted(counts.items()):
        if n > 1:
            ids = ", ".join(r.id for r in file.records if (r.kind, r.subject) == (kind, subject))
            problems.append(Problem("duplicate-subject", ids, f"{kind} {subject} has {n} records"))
    covered: set[tuple[str, str]] = set()
    for rec in file.records:
        key = (rec.kind, rec.subject)
        why = _standing(rec, today)
        if why is None:
            covered.add(key)
            problems += _evidence(rec, root) + _reviewers(rec) + _hosting(rec)
        elif key in need:
            problems.append(
                Problem(
                    why,
                    rec.id,
                    f"{rec.kind} {rec.subject} is {rec.status}, approved {rec.approved_on}, review {rec.review_date}",
                )
            )
        if rec.status == "approved":
            problems += _vendor(rec, world, today)
    for wanted, line in sorted(need.items()):
        if wanted not in covered:
            problems.append(Problem("missing-record", "-", line))
    by_id = {r.id: r for r in file.records}
    for vendor in world.vendors.vendors:
        if vendor.status != "approved":
            continue
        ref = by_id.get(vendor.approval_ref or "")
        if not (
            ref is not None
            and ref.kind == "provider"
            and ref.status == "approved"
            and ref.vendor_approval_id == vendor.id
        ):
            problems.append(
                Problem(
                    "vendor-unrecorded",
                    vendor.approval_ref or "-",
                    f"vendor {vendor.id} is approved but no approved provider record names it (approval_ref)",
                )
            )
    return problems


def check_repo(root: Path, today: date) -> list[Problem]:
    return check(ApprovalFile.load(root / RECORDS_FILE), load_world(root), root, today)


def schema_text() -> str:
    return json.dumps(ApprovalFile.model_json_schema(), indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.assurance.approvals", description="Model and tool approval records (B-93)."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    chk = sub.add_parser("check", help="fail when something has no approved, in-date, evidenced record")
    chk.add_argument("--as-of", default=None, help="YYYY-MM-DD (default: today)")
    sch = sub.add_parser("schema", help="compare the committed JSON Schema with the model; --write rewrites it")
    sch.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "schema":
            target = REPO_ROOT / SCHEMA_FILE
            current = target.read_text(encoding="utf-8") if target.is_file() else ""
            if args.write:
                target.write_text(schema_text(), encoding="utf-8", newline="\n")
                print("schema written")
            else:
                print("schema in sync (dry run)" if current == schema_text() else "schema differs (dry run)")
            return 0
        try:
            today = date.fromisoformat(args.as_of) if args.as_of else date.today()
        except ValueError:
            print(f"--as-of must be YYYY-MM-DD, got {args.as_of!r}")
            return 2
        found = check_repo(REPO_ROOT, today)
    except ApprovalError as exc:
        print(exc)
        return 2
    for problem in found:
        print(problem)
    print("approval checks: ok" if not found else f"approval checks: {len(found)} problem(s)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
