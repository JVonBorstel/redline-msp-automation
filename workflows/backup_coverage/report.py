"""M365 backup coverage, retention and immutability review, and DR plan upkeep (B-70, specs/B-70.md).

For one client this reads one synthetic fixture (``data/<client>.json``) and reports:

* B70-1: which in-scope users, mailboxes and SharePoint sites no active backup policy covers, and which policies keep
  data for less than the client's requirement or are not immutable when the client requires it;
* B70-2: which disaster recovery plan sections have not been reviewed in the client's number of months, and a draft
  tabletop exercise outline built from those sections and the coverage gaps;
* B70-3: counts that reconcile (every object is in scope or out of scope, and covered or not; every policy is clean or
  has a finding; every DR section is current or stale).

Read-only (W-BDR-05, W-BDR-06, W-BDR-08 are all R0 reports). Nothing here changes a policy, a plan or a tenant; the one
write is the report pair, a JSON file and a Markdown file, each with a ``sha256sum``-format sidecar. Dates come from
``as_of``, never from the clock, and the same inputs give the same bytes.

One client per report (C-27): the fixture must name the client it is filed under, and the output names no other client.
Free text from the fixture (names, titles) is untrusted: text the injection detector flags is replaced by a fixed
sentence and counted.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from core.guard import detect_injection
from core.guard.classify import DataClass
from core.paths import REPO_ROOT

DEFAULT_DATA_DIR = Path(__file__).with_name("data")
DEFAULT_OUT_DIR = REPO_ROOT / "build" / "backup-coverage"
CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9:._-]{1,100}$")
KIND = "backup-coverage"
VERSION = 1
WITHHELD = "(text withheld)"
NOTE = "Synthetic data (fixture-based). A read-only report: no policy, plan or tenant setting was changed."
BANNER = "Draft. A person owns the plan and runs the exercise; this outline is a starting point, not the plan."
DATA_CLASS = DataClass.DC3  # it names tenant users and mailboxes
SERVICE_KIND = {"Exchange": "mailboxes", "OneDrive": "users", "SharePoint": "sites"}
KINDS = ("users", "mailboxes", "sites")
_STATE_WORDS = {"never-reviewed": "never reviewed", "stale": "stale"}
UNVERIFIED = (
    "Every fixture field name (policies, scope, retention_days, immutable, state) is an invented stand-in; no backup "
    "product's API or documentation was read, so nothing here claims how any vendor reports coverage or immutability.",
    "The client's retention and immutability requirement and the DR review age are synthetic values in the fixture, "
    "not read from a contract or a plan.",
    "Coverage is judged from policy scope only. No restore was tried and no job result was read, so a covered object "
    "may still fail to back up (that is the daily review, B-68).",
    "The fixture inventory is a hand-made snapshot; it was not read from Microsoft Graph or Exchange Online.",
    "A policy's immutability setting is taken as stated; whether the storage really refuses deletes was not tested.",
)


class BackupCoverageError(ValueError):
    """The input is bad (client, date, fixture); nothing was written."""


class VerifyError(ValueError):
    """A file does not match its hash, or the JSON does not match the Markdown it names."""


# -- fixture model -------------------------------------------------------------------------------------------------
def _safe_id(value: str) -> str:
    if not SAFE_ID.fullmatch(value):
        raise ValueError("not a safe id")
    return value


def _iso_date(value: str) -> str:
    date.fromisoformat(value)
    return value


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class Requirements(_Model):
    min_retention_days: int = Field(ge=1, le=36500)
    immutability_required: bool
    dr_max_age_months: int = Field(ge=1, le=120)


class User(_Model):
    id: str
    upn: str = Field(min_length=1, max_length=200)
    user_type: Literal["Member", "Guest"]
    account_enabled: bool

    _id = field_validator("id")(_safe_id)


class Mailbox(_Model):
    id: str
    address: str = Field(min_length=1, max_length=200)
    kind: Literal["user", "shared", "room"]

    _id = field_validator("id")(_safe_id)


class Site(_Model):
    id: str
    name: str = Field(min_length=1, max_length=200)

    _id = field_validator("id")(_safe_id)


class Inventory(_Model):
    users: tuple[User, ...]
    mailboxes: tuple[Mailbox, ...]
    sites: tuple[Site, ...]


class Scope(_Model):
    mode: Literal["all", "selected"]
    ids: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()


class Policy(_Model):
    id: str
    name: str = Field(min_length=1, max_length=200)
    service: Literal["Exchange", "OneDrive", "SharePoint"]
    state: Literal["active", "paused"]
    retention_days: int | None = Field(ge=0)
    immutable: bool | None
    scope: Scope

    _id = field_validator("id")(_safe_id)


class Section(_Model):
    id: str
    title: str = Field(min_length=1, max_length=200)
    owner: str
    last_reviewed: str | None

    _id = field_validator("id", "owner")(_safe_id)

    @field_validator("last_reviewed")
    @classmethod
    def _date(cls, value: str | None) -> str | None:
        return None if value is None else _iso_date(value)


class DrPlan(_Model):
    document: str = Field(min_length=1, max_length=200)
    sections: tuple[Section, ...]


class Fixture(_Model):
    note: str = Field(default="", alias="_note")
    client: str
    as_of: str
    requirements: Requirements
    inventory: Inventory
    policies: tuple[Policy, ...]
    dr_plan: DrPlan

    _as_of = field_validator("as_of")(_iso_date)


# -- helpers -------------------------------------------------------------------------------------------------------
def canonical_bytes(body: dict[str, Any]) -> bytes:
    """The exact bytes a JSON report is written as: sorted keys, two-space indent, ASCII, one trailing newline."""
    return (json.dumps(body, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sidecar_for(path: Path) -> Path:
    return path.with_name(path.name + ".sha256")


def months_before(day: date, months: int) -> date:
    """`day` minus whole calendar months; a day past the end of the target month is clamped to its last day."""
    total = day.year * 12 + (day.month - 1) - months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _client_id(client: str) -> str:
    if not isinstance(client, str) or not CLIENT_ID.fullmatch(client):
        raise BackupCoverageError(f"{client!r} is not a client id")
    return client


def _parse_date(value: str, what: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise BackupCoverageError(f"{what} must be an ISO date (YYYY-MM-DD), got {value!r}") from None


class _Text:
    """Cleans untrusted free text once per field and counts what was withheld."""

    def __init__(self) -> None:
        self.withheld = 0

    def __call__(self, text: str) -> str:
        if detect_injection(text).flagged:
            self.withheld += 1
            return WITHHELD
        return " ".join(text.split())


def load_fixture(client: str, data_dir: Path) -> tuple[Fixture, Path]:
    _client_id(client)
    path = Path(data_dir) / f"{client}.json"
    try:
        fixture = Fixture.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except OSError:
        raise BackupCoverageError(f"no readable backup coverage data for {client}") from None
    except (ValueError, ValidationError) as exc:
        raise BackupCoverageError(f"backup coverage data for {client} is not valid: {exc}") from None
    if fixture.client != client:
        raise BackupCoverageError(f"the data file for {client} names client {fixture.client!r}; refused")
    return fixture, path


def _source(path: Path) -> dict[str, str]:
    path = path.resolve()
    try:
        shown = path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        shown = path.name
    return {"path": shown, "sha256": sha256_hex(path.read_bytes())}


# -- B70-1 coverage ------------------------------------------------------------------------------------------------
def policy_issues(policy: Policy, req: Requirements) -> list[str]:
    issues: list[str] = []
    if policy.retention_days is None:
        issues.append("retention-not-stated")
    elif policy.retention_days < req.min_retention_days:
        issues.append("retention-below-requirement")
    if req.immutability_required:
        if policy.immutable is None:
            issues.append("immutability-not-stated")
        elif policy.immutable is False:
            issues.append("not-immutable")
    return issues


def _covers(policy: Policy, object_id: str) -> bool:
    scope = policy.scope
    if object_id in scope.excluded:
        return False
    return scope.mode == "all" or object_id in scope.ids


def _uncovered_reason(policies: list[Policy], object_id: str) -> str:
    paused = [p.id for p in policies if p.state == "paused" and _covers(p, object_id)]
    if paused:
        return f"only paused policy {paused[0]} covers it"
    excluded = [
        p.id for p in policies if p.state == "active" and p.scope.mode == "all" and object_id in p.scope.excluded
    ]
    if excluded:
        return f"excluded from policy {excluded[0]}"
    return "no policy lists it"


def _objects(fixture: Fixture, kind: str, clean: _Text) -> list[tuple[str, str, str | None]]:
    """(id, shown name, out-of-scope reason or None) for every object of one kind."""
    inv = fixture.inventory
    if kind == "users":
        out: list[tuple[str, str, str | None]] = []
        for u in inv.users:
            reason = (
                "account disabled" if not u.account_enabled else "guest account" if u.user_type == "Guest" else None
            )
            out.append((u.id, clean(u.upn), reason))
        return out
    if kind == "mailboxes":
        return [(m.id, clean(m.address), None) for m in inv.mailboxes]
    return [(s.id, clean(s.name), None) for s in inv.sites]


def _coverage(fixture: Fixture, clean: _Text, gaps: dict[str, int]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for kind in KINDS:
        service = next(s for s, k in SERVICE_KIND.items() if k == kind)
        policies = [p for p in fixture.policies if p.service == service]
        active = [p for p in policies if p.state == "active"]
        objects = _objects(fixture, kind, clean)
        known = {o[0] for o in objects}
        for p in policies:
            gaps["unknown_scope_ids"] += sum(1 for i in (*p.scope.ids, *p.scope.excluded) if i not in known)
        in_scope = [(i, n) for i, n, reason in objects if reason is None]
        out_of_scope = [{"id": i, "name": n, "reason": reason} for i, n, reason in objects if reason is not None]
        covered = [(i, n) for i, n in in_scope if any(_covers(p, i) for p in active)]
        covered_ids = {i for i, _ in covered}
        uncovered = [
            {"id": i, "name": n, "reason": _uncovered_reason(policies, i)} for i, n in in_scope if i not in covered_ids
        ]
        result[kind] = {
            "service": service,
            "total": len(objects),
            "in_scope": len(in_scope),
            "out_of_scope": out_of_scope,
            "covered": len(covered),
            "uncovered": uncovered,
        }
    return result


def _policies(fixture: Fixture, clean: _Text) -> dict[str, Any]:
    rows = []
    for p in fixture.policies:
        rows.append(
            {
                "id": p.id,
                "name": clean(p.name),
                "service": p.service,
                "state": p.state,
                "retention_days": p.retention_days,
                "immutable": p.immutable,
                "scope": p.scope.mode,
                "issues": policy_issues(p, fixture.requirements),
            }
        )
    with_findings = sum(1 for r in rows if r["issues"])
    return {"total": len(rows), "with_findings": with_findings, "clean": len(rows) - with_findings, "rows": rows}


# -- B70-2 DR plan -------------------------------------------------------------------------------------------------
def _dr_plan(fixture: Fixture, as_of: date, months: int, clean: _Text) -> dict[str, Any]:
    cutoff = months_before(as_of, months)
    rows = []
    for s in fixture.dr_plan.sections:
        reviewed = date.fromisoformat(s.last_reviewed) if s.last_reviewed else None
        if reviewed is None:
            status = "never-reviewed"
        elif reviewed < cutoff:
            status = "stale"
        else:
            status = "current"
        rows.append(
            {
                "id": s.id,
                "title": clean(s.title),
                "owner": s.owner,
                "last_reviewed": s.last_reviewed,
                "age_days": None if reviewed is None else (as_of - reviewed).days,
                "status": status,
            }
        )
    stale = sum(1 for r in rows if r["status"] != "current")
    return {
        "document": clean(fixture.dr_plan.document),
        "max_age_months": months,
        "cutoff": cutoff.isoformat(),
        "total": len(rows),
        "current": len(rows) - stale,
        "stale": stale,
        "rows": rows,
    }


def _tabletop(client: str, coverage: dict[str, Any], policies: dict[str, Any], dr: dict[str, Any]) -> dict[str, Any]:
    stale = [r for r in dr["rows"] if r["status"] != "current"]
    owners = sorted({r["owner"] for r in (stale or dr["rows"])})
    injects: list[str] = [
        "06:10: ransomware encrypts the file shares and the synced OneDrive and SharePoint content. Staff cannot open "
        "files. Who is called, in what order, and who decides what is restored first?"
    ]
    for kind, label, text in (
        ("mailboxes", "mailbox", "is found deleted by a compromised account"),
        ("users", "OneDrive of", "is wiped by a compromised account"),
        ("sites", "site", "is deleted by a compromised account"),
    ):
        gone = coverage[kind]["uncovered"]
        if gone:
            more = f" (and {len(gone) - 1} more not covered)" if len(gone) > 1 else ""
            injects.append(
                f"Mid-morning: the {label} {gone[0]['name']}{more} {text}. The backup review shows no copy. "
                "What is lost, who tells the owner, and what do we do next?"
            )
    weak = [r for r in policies["rows"] if r["issues"]]
    if weak:
        ids = ", ".join(r["id"] for r in weak)
        injects.append(
            f"Afternoon: an attacker with admin rights tries to shorten retention or delete backup data. Policies with "
            f"open findings: {ids}. Which of them would let that succeed, and who is told?"
        )
    discussion = [
        {
            "section_id": r["id"],
            "title": r["title"],
            "owner": r["owner"],
            "status": r["status"],
            "question": (
                f"Section {r['id']} ({r['title']}) is {_STATE_WORDS[r['status']]}. "
                "Does it still match how the client works today, and what must change?"
            ),
        }
        for r in stale
    ]
    return {
        "status": "draft",
        "banner": BANNER,
        "title": f"Tabletop exercise outline: {client}",
        "scenario": "Ransomware and account compromise in the client's Microsoft 365 tenant.",
        "objectives": [
            "Check that the people named in the plan know their part.",
            "Find out which backed-up items could not be restored, using the coverage gaps in this report.",
            "Record every stale section that the exercise shows is wrong.",
        ],
        "participants": owners,
        "injects": injects,
        "discussion": discussion,
        "evidence_to_record": [
            "Date, attendees and who ran the exercise.",
            "What each inject exposed (a gap, a wrong contact, a missing step).",
            "Actions, owners and due dates; the sections to update.",
        ],
    }


# -- report --------------------------------------------------------------------------------------------------------
def reconciles(body: dict[str, Any]) -> bool:
    """Recheck the arithmetic of a report body from its own rows: nothing is counted twice or dropped."""
    try:
        for kind in KINDS:
            sec = body["coverage"][kind]
            if sec["total"] != sec["in_scope"] + len(sec["out_of_scope"]):
                return False
            if sec["in_scope"] != sec["covered"] + len(sec["uncovered"]):
                return False
        pol = body["policies"]
        if not (pol["total"] == len(pol["rows"]) == pol["with_findings"] + pol["clean"]):
            return False
        if pol["with_findings"] != sum(1 for r in pol["rows"] if r["issues"]):
            return False
        dr = body["dr_plan"]
        if not (dr["total"] == len(dr["rows"]) == dr["current"] + dr["stale"]):
            return False
        return bool(dr["stale"] == sum(1 for r in dr["rows"] if r["status"] != "current"))
    except (KeyError, TypeError):
        return False


@dataclass(frozen=True)
class Report:
    body: dict[str, Any]


def build_report(
    client: str,
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    as_of: str | None = None,
    stale_months: int | None = None,
) -> Report:
    """The full report for one client. Reads one fixture; writes nothing."""
    fixture, path = load_fixture(client, data_dir)
    day = _parse_date(as_of or fixture.as_of, "as_of")
    months = fixture.requirements.dr_max_age_months if stale_months is None else stale_months
    if isinstance(months, bool) or not isinstance(months, int) or not 1 <= months <= 120:
        raise BackupCoverageError("stale_months must be a whole number from 1 to 120")
    clean = _Text()
    gaps = {"unknown_scope_ids": 0, "text_withheld": 0}
    coverage = _coverage(fixture, clean, gaps)
    policies = _policies(fixture, clean)
    dr = _dr_plan(fixture, day, months, clean)
    gaps["text_withheld"] = clean.withheld
    req = fixture.requirements
    counts = {
        "objects_total": sum(coverage[k]["total"] for k in KINDS),
        "objects_in_scope": sum(coverage[k]["in_scope"] for k in KINDS),
        "objects_covered": sum(coverage[k]["covered"] for k in KINDS),
        "objects_uncovered": sum(len(coverage[k]["uncovered"]) for k in KINDS),
        "policies_total": policies["total"],
        "policies_with_findings": policies["with_findings"],
        "dr_sections_total": dr["total"],
        "dr_sections_stale": dr["stale"],
    }
    body: dict[str, Any] = {
        "kind": KIND,
        "version": VERSION,
        "client": client,
        "as_of": day.isoformat(),
        "data_class": DATA_CLASS.label,
        "note": NOTE,
        "requirements": {
            "min_retention_days": req.min_retention_days,
            "immutability_required": req.immutability_required,
            "dr_max_age_months": months,
        },
        "sources": [_source(path)],
        "coverage": coverage,
        "policies": policies,
        "dr_plan": dr,
        "tabletop": _tabletop(client, coverage, policies, dr),
        "counts": counts,
        "gaps": gaps,
        "unverified": list(UNVERIFIED),
    }
    body["reconciles"] = reconciles(body)
    return Report(body)


# -- Markdown ------------------------------------------------------------------------------------------------------
def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return " ".join(text.split()).replace("|", "\\|")


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    if not rows:
        return ["None.", ""]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return [*lines, ""]


def render_markdown(body: dict[str, Any]) -> str:
    """The human-readable form of a report body. Deterministic; the JSON names its hash."""
    req, counts = body["requirements"], body["counts"]
    out = [
        f"# Microsoft 365 backup coverage and DR plan review: {body['client']}",
        "",
        "> Independently built prototype. Not affiliated with any vendor's or real company's systems.",
        f"> Fixture-based, synthetic data. {body['note']}",
        "",
        f"As of {body['as_of']}. Data class {body['data_class']}. "
        f"Client requirement: retention at least {req['min_retention_days']} days; immutability "
        f"{'required' if req['immutability_required'] else 'not required'}; DR plan sections reviewed within "
        f"{req['dr_max_age_months']} months.",
        "",
        "## Summary",
        "",
        f"- Objects in scope: {counts['objects_in_scope']} of {counts['objects_total']}; covered "
        f"{counts['objects_covered']}; not covered {counts['objects_uncovered']}.",
        f"- Policies with a finding: {counts['policies_with_findings']} of {counts['policies_total']}.",
        f"- DR plan sections stale or never reviewed: {counts['dr_sections_stale']} of {counts['dr_sections_total']}.",
        f"- Counts reconcile: {'yes' if body['reconciles'] else 'NO, do not rely on this report'}.",
        "",
        "## Not covered by backup",
        "",
    ]
    for kind in KINDS:
        sec = body["coverage"][kind]
        out += [
            f"### {kind.capitalize()} ({sec['service']})",
            "",
            f"{sec['total']} listed, {sec['in_scope']} in scope, {sec['covered']} covered, "
            f"{len(sec['uncovered'])} not covered, {len(sec['out_of_scope'])} out of scope.",
            "",
            *_table(["Name", "Id", "Why not covered"], [[r["name"], r["id"], r["reason"]] for r in sec["uncovered"]]),
        ]
        if sec["out_of_scope"]:
            out += [
                "Out of scope:",
                "",
                *_table(["Name", "Id", "Reason"], [[r["name"], r["id"], r["reason"]] for r in sec["out_of_scope"]]),
            ]
    pol = body["policies"]
    out += [
        "## Retention and immutability",
        "",
        f"{pol['with_findings']} of {pol['total']} policies have a finding.",
        "",
    ]
    out += _table(
        ["Policy", "Name", "Service", "State", "Retention days", "Immutable", "Findings"],
        [
            [r["id"], r["name"], r["service"], r["state"], r["retention_days"], r["immutable"], ", ".join(r["issues"])]
            for r in pol["rows"]
        ],
    )
    dr = body["dr_plan"]
    out += [
        "## DR plan checklist",
        "",
        f"{dr['document']}. Sections last reviewed before {dr['cutoff']} ({dr['max_age_months']} months before "
        f"{body['as_of']}) are stale. {dr['stale']} of {dr['total']} need review.",
        "",
        *_table(
            ["Section", "Title", "Owner", "Last reviewed", "Age (days)", "Status"],
            [
                [
                    r["id"],
                    r["title"],
                    r["owner"],
                    r["last_reviewed"] or "never reviewed",
                    r["age_days"],
                    r["status"],
                ]
                for r in dr["rows"]
            ],
        ),
    ]
    tt = body["tabletop"]
    out += [
        "## Tabletop exercise outline (draft)",
        "",
        f"**{tt['banner']}**",
        "",
        f"Scenario: {tt['scenario']}",
        "",
        "Objectives:",
        "",
        *[f"- {x}" for x in tt["objectives"]],
        "",
        f"Participants (section owners): {', '.join(tt['participants']) or 'none named'}.",
        "",
        "Injects:",
        "",
        *[f"{n}. {x}" for n, x in enumerate(tt["injects"], 1)],
        "",
        "Plan sections to walk through:",
        "",
        *([f"- {d['question']}" for d in tt["discussion"]] or ["- No stale section; walk the plan in order."]),
        "",
        "Evidence to record:",
        "",
        *[f"- {x}" for x in tt["evidence_to_record"]],
        "",
        "## Not verified",
        "",
        *[f"- {x}" for x in body["unverified"]],
        "",
        f"Gaps: {body['gaps']['unknown_scope_ids']} policy scope ids not in the inventory; "
        f"{body['gaps']['text_withheld']} text fields withheld.",
        "",
    ]
    return "\n".join(out)


# -- files ---------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Written:
    json_path: Path
    md_path: Path
    json_sha256: str
    md_sha256: str


def _write(path: Path, data: bytes) -> str:
    digest = sha256_hex(data)
    path.write_bytes(data)
    # sha256sum format, so `sha256sum -c` (or Get-FileHash) re-verifies it without this code.
    sidecar_for(path).write_text(f"{digest}  {path.name}\n", encoding="ascii", newline="\n")
    return digest


def write_report(
    client: str,
    out_dir: Path = DEFAULT_OUT_DIR,
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    as_of: str | None = None,
    stale_months: int | None = None,
) -> Written:
    """Build the report and write ``<out>/<client>/<client>.json`` and ``.md`` with a sidecar each."""
    body = build_report(client, data_dir=data_dir, as_of=as_of, stale_months=stale_months).body
    md = render_markdown(body).encode("utf-8")
    body["markdown_sha256"] = sha256_hex(md)
    folder = Path(out_dir) / client
    folder.mkdir(parents=True, exist_ok=True)
    md_path, json_path = folder / f"{client}.md", folder / f"{client}.json"
    md_digest = _write(md_path, md)
    json_digest = _write(json_path, canonical_bytes(body))
    return Written(json_path, md_path, json_digest, md_digest)


def verify(path: Path) -> str:
    """Re-hash a report file against its sidecar. For the JSON also check it is canonical, its arithmetic holds and
    the sibling Markdown is the one it names. Returns the file's SHA-256; raises VerifyError on any mismatch."""
    path = Path(path)
    side = sidecar_for(path)
    try:
        data = path.read_bytes()
        line = side.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise VerifyError(f"cannot read {Path(exc.filename or str(path)).name}") from None
    except ValueError:
        raise VerifyError(f"{side.name}: sidecar is not ASCII text") from None
    expected, _, name = line.partition("  ")
    actual = sha256_hex(data)
    if name != path.name or actual != expected:
        raise VerifyError(f"{path.name}: SHA-256 {actual} does not match the sidecar ({expected or 'empty'})")
    if path.suffix != ".json":
        return actual
    try:
        body = json.loads(data)
    except ValueError:
        raise VerifyError(f"{path.name}: matches its sidecar but is not valid JSON") from None
    if not isinstance(body, dict) or body.get("kind") != KIND:
        raise VerifyError(f"{path.name}: not a backup coverage report")
    if canonical_bytes(body) != data:
        raise VerifyError(f"{path.name}: not in canonical form")
    if body.get("reconciles") is not True or not reconciles(body):
        raise VerifyError(f"{path.name}: counts do not reconcile")
    md_path = path.with_suffix(".md")
    try:
        md_digest = sha256_hex(md_path.read_bytes())
    except OSError:
        raise VerifyError(f"{md_path.name}: the Markdown this report names is missing") from None
    if md_digest != body.get("markdown_sha256"):
        raise VerifyError(f"{md_path.name}: does not match the Markdown hash pinned in {path.name}")
    return actual
