"""Business email compromise containment plan and inbox-rule audit (B-46, specs/B-46.md; W-SEC-04, W-M365-05).

``contain`` builds the containment plan for ONE user: it reads the user's inbox rules through ``inboxrule.list`` (R0),
then proposes, in this order, block sign-in (``user.disable``), revoke sessions (``user.revoke-sessions``), reset MFA
(``user.reset-mfa``) and one ``inboxrule.disable`` per flagged rule that is on. Each step is dry-run through the runner
(audited) and queued as one proposal for a lead (STD-PR-1, C-06); nothing is executed here. Lever params come from the
validated target and the rule ids that ``inboxrule.list`` returned, never from rule text (STD-LV-9).

The evidence (which rules were found, why each is flagged, and when it was made) goes into an incident timeline
(``timeline``/``write_timeline``) built after the audit chain verifies. ``prompt_text`` is the only text meant for a
model: step names, statuses and a count, with no rule id, name, address or time. Rule names are written by whoever
controls the mailbox, so they are untrusted (C-12): a name the injection detector flags is withheld everywhere.

``audit_rules`` is the read-only client-wide audit: every flagged rule of every mailbox of one client.
No model is called.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from core.audit import head_path_for, verify_chain
from core.guard import detect_injection
from core.levers import LeverRunner
from core.queue import Proposal, ProposalQueue, QueueError

PACKAGE_DIR = Path(__file__).resolve().parent
CONFIG: dict[str, Any] = json.loads((PACKAGE_DIR / "config.json").read_text(encoding="utf-8"))
LIST_LEVER = "inboxrule.list"
WITHHELD = "[rule name withheld: it looks like instructions]"
# One userPrincipalName, the same pattern the levers' upn param uses (one target per plan).
_ONE_UPN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_INCIDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,39}$")

StepStatus = Literal["proposed", "planned", "already-met", "refused"]


class BecError(ValueError):
    """The input cannot be used (bad incident id, audit chain does not verify); nothing was concluded."""


@dataclass
class Step:
    key: str
    label: str
    lever: str
    params: dict[str, Any]
    status: StepStatus
    reason: str
    needs_approval: bool = True
    proposal_id: str | None = None
    dry_run_audit_seq: int | None = None


@dataclass
class ContainmentPlan:
    client: str
    upn: str
    incident: str
    requester: str
    outcome: Literal["planned", "refused"]
    reason: str
    steps: list[Step] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    list_audit_seq: int | None = None
    notes: list[str] = field(default_factory=list)
    executed: bool = False  # always False: this workflow never executes a write lever

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_name(value: Any) -> str:
    text = str(value or "")
    return WITHHELD if text and detect_injection(text).flagged else text


def incident_id(client: str, upn: str) -> str:
    """A stable incident id for one client and user, when none is given."""
    return "BEC-" + hashlib.sha256(f"{client}|{upn.lower()}".encode()).hexdigest()[:10]


def _evidence(row: dict[str, Any], seq: int | None) -> dict[str, Any]:
    flags = [f for f in row.get("flags", []) if isinstance(f, dict)]
    return {
        "rule_id": str(row.get("id", "")),
        "mailbox": str(row.get("mailbox", "")),
        "name": _safe_name(row.get("displayName")),
        "isEnabled": bool(row.get("isEnabled")),
        "flags": [str(f.get("kind")) for f in flags],
        "why": [str(f.get("why")) for f in flags],
        "createdDateTime": row.get("createdDateTime"),
        "lastModifiedDateTime": row.get("lastModifiedDateTime"),
        "source": {"lever": LIST_LEVER, "audit_seq": seq},
    }


def _dry_run_and_queue(
    runner: LeverRunner, step: Step, client: str, requester: str, queue: ProposalQueue | None, ref: str
) -> None:
    dry = runner.invoke(step.lever, step.params, requester, client, "dry-run")
    step.dry_run_audit_seq = dry.audit_seq
    if not dry.ok:
        step.status, step.reason = "refused", f"the dry-run was refused: {dry.reason}"
        return
    if not dry.diff:
        step.status, step.reason = "already-met", "the dry-run shows no change: the target state is already in place"
        return
    step.reason = "dry-run shows a change; a lead approves it before it runs (C-06)"
    if queue is None:
        return
    reason = f"BEC containment {ref}: {step.label}"
    if step.lever == "inboxrule.disable":
        reason += f" {step.params['rule_id']}"
    try:
        stored = queue.add(
            Proposal.new(
                source=CONFIG["queue_source"],
                ref=ref,
                lever=step.lever,
                client=client,
                params=step.params,
                requested_by=requester,
                reason=reason[:200],
            )
        )
    except QueueError as exc:
        step.status, step.reason = "refused", f"not queued: {exc}"
        return
    step.proposal_id = stored.id
    if stored.status == "pending":
        step.status = "proposed"
    else:
        step.status = "refused"
        step.reason = f"an earlier proposal with the same id is already {stored.status}; nothing new was queued"


def _drafts(upn: str, evidence: list[dict[str, Any]]) -> list[Step]:
    spec: dict[str, dict[str, str]] = CONFIG["steps"]
    out: list[Step] = []
    for key in CONFIG["order"]:
        lever, label = spec[key]["lever"], spec[key]["label"]
        if key == "block-sign-in":
            out.append(Step(key, label, lever, {"upn": upn, "reason": CONFIG["block_reason"]}, "planned", ""))
        elif key in ("revoke-sessions", "reset-mfa"):
            out.append(Step(key, label, lever, {"upn": upn}, "planned", ""))
        elif key == "disable-rules":
            for row in evidence:
                params = {"upn": upn, "rule_id": row["rule_id"]}
                if row["isEnabled"]:
                    out.append(Step(key, label, lever, params, "planned", ""))
                else:
                    why = "inboxrule.list shows this flagged rule is already off; nothing to propose"
                    out.append(Step(key, label, lever, params, "already-met", why, needs_approval=False))
    return out


def contain(
    runner: LeverRunner,
    client: str,
    upn: Any,
    requester: str,
    incident: str | None = None,
    queue: ProposalQueue | None = None,
) -> ContainmentPlan:
    """Build the containment plan for ONE user ``upn`` of ``client``; ``requester`` is the proposing technician."""
    target = upn if isinstance(upn, str) else ""

    def refused(reason: str) -> ContainmentPlan:
        return ContainmentPlan(client, target, incident or "", requester, "refused", reason)

    if not isinstance(upn, str) or not _ONE_UPN.fullmatch(upn):
        return refused("a containment plan has exactly one target: one userPrincipalName; nothing was planned")
    ref = incident or incident_id(client, upn)
    if not _INCIDENT.fullmatch(ref):
        raise BecError(f"incident id {ref!r} must be 1-40 letters, digits or dashes")
    listed = runner.invoke(LIST_LEVER, {"upn": upn}, requester, client, "execute")
    if not listed.ok:
        plan = refused(f"the inbox rules could not be read, so nothing was planned: {listed.reason}")
        plan.incident, plan.list_audit_seq = ref, listed.audit_seq
        return plan
    data = listed.data if isinstance(listed.data, dict) else {}
    rows = [r for r in data.get("value", []) if isinstance(r, dict) and r.get("flagged")]
    evidence = [_evidence(r, listed.audit_seq) for r in rows]
    steps = _drafts(upn, evidence)
    for step in steps:
        if step.status == "planned":
            _dry_run_and_queue(runner, step, client, requester, queue, ref)
    plan = ContainmentPlan(client, upn, ref, requester, "planned", "plan built; nothing was executed")
    plan.steps, plan.evidence, plan.list_audit_seq = steps, evidence, listed.audit_seq
    if not evidence:
        plan.notes.append("no flagged inbox rule was found for this user; no rule step planned")
    note = data.get("note")
    if isinstance(note, str) and note:
        plan.notes.append(note)
    return plan


def prompt_text(plan: ContainmentPlan) -> str:
    """The only text of a plan meant for a model: step names and statuses. The evidence stays out (B46-3)."""
    lines = [
        f"Containment plan for one user of {plan.client}: {plan.outcome}. Nothing has run; a lead approves each step."
    ]
    lines += [f"{n}. {s.label}: {s.status}" for n, s in enumerate(plan.steps, start=1)]
    lines.append(f"Flagged inbox rules: {len(plan.evidence)}. Their details are in the incident timeline only.")
    return "\n".join(lines)


def _audit_records(audit_path: Path) -> list[dict[str, Any]]:
    if not audit_path.exists():
        return []
    return [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def timeline(plan: ContainmentPlan, audit_path: Path) -> list[dict[str, Any]]:
    """The plan's evidence as an incident timeline: a header line, then one event per line, oldest first.

    The audit chain is verified first; a chain that does not verify gives no timeline. Only this client's records
    are read. Format ``incident-timeline/1`` is defined here because B-48 is not built yet (specs/B-46.md).
    """
    path = Path(audit_path)
    if not path.exists():
        raise BecError(f"no audit log at {path}, so no timeline was built")
    head = head_path_for(path)
    checked = verify_chain(path, head if head.exists() else None)
    if not checked.ok:
        raise BecError(f"the audit chain does not verify, so no timeline was built: {checked.reason}")
    header = {
        "format": CONFIG["timeline_format"],
        "notice": CONFIG["timeline_notice"],
        "client": plan.client,
        "incident": plan.incident,
        "target": plan.upn,
        "audit_chain": {"verified": True, "records": checked.records},
    }
    events: list[dict[str, Any]] = []
    for row in plan.evidence:
        base = {"source": LIST_LEVER, "ref": row["rule_id"], "mailbox": row["mailbox"], "flags": row["flags"]}
        if isinstance(row["createdDateTime"], str):
            events.append({"at": row["createdDateTime"], "kind": "inbox-rule.created", **base, "name": row["name"]})
        if isinstance(row["lastModifiedDateTime"], str) and row["lastModifiedDateTime"] != row["createdDateTime"]:
            events.append({"at": row["lastModifiedDateTime"], "kind": "inbox-rule.modified", **base})
    wanted = {s.dry_run_audit_seq for s in plan.steps if s.dry_run_audit_seq is not None}
    if plan.list_audit_seq is not None:
        wanted.add(plan.list_audit_seq)
    for record in _audit_records(path):
        if record.get("seq") not in wanted or record.get("client") != plan.client:
            continue
        result = record.get("result") if isinstance(record.get("result"), dict) else {}
        events.append(
            {
                "at": record.get("ts"),
                "kind": f"lever.{record.get('mode')}",
                "source": "audit",
                "ref": f"audit seq {record.get('seq')}",
                "lever": record.get("lever"),
                "status": (result or {}).get("status"),
            }
        )
    events.sort(key=lambda e: (str(e.get("at")), str(e.get("ref"))))
    return [header, *events]


def write_timeline(plan: ContainmentPlan, audit_path: Path, out_dir: Path) -> Path:
    """Write the timeline as JSON Lines to ``<out_dir>/timelines/<client>/<incident>.jsonl``; returns the path."""
    lines = timeline(plan, audit_path)
    target = Path(out_dir) / "timelines" / plan.client / f"{plan.incident}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines), encoding="utf-8")
    return target


def audit_rules(runner: LeverRunner, client: str, identity: str) -> dict[str, Any]:
    """Read-only audit of one client: every flagged inbox rule of every mailbox, through ``inboxrule.list``."""
    listed = runner.invoke(LIST_LEVER, {"flagged_only": True}, identity, client, "execute")
    if not listed.ok:
        return {"client": client, "ok": False, "reason": listed.reason, "rules": [], "executed": False}
    data = listed.data if isinstance(listed.data, dict) else {}
    rules = [_evidence(r, listed.audit_seq) for r in data.get("value", []) if isinstance(r, dict)]
    return {"client": client, "ok": True, "reason": "", "rules": rules, "note": data.get("note"), "executed": False}


def summary(plan: ContainmentPlan) -> dict[str, Any]:
    """The plan as JSON-ready data (technician view: holds the evidence)."""
    return plan.to_dict()
