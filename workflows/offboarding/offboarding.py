"""Offboarding change plan with completion proof (B-36, specs/B-36.md; W-ONB-08 to 14; C-05, C-06, C-08, C-33).

``plan`` orders the leaver's access removal as lever steps (block sign-in, revoke sessions, mailbox to shared and
auto-reply, OneDrive grant, group removal, license removal after the retention window), dry-runs each one through the
runner (audited) and queues one proposal per change for a lead (C-06). It never executes a write lever. Device steps
are listed ``manual until W6`` and the line-of-business apps become a checklist.

``verify`` is read-only: it reads every target state from the tenant files, lists each step that is not in its target
state (nothing is hidden, W-ONB-14) and writes a completion record. ``reconcile`` checks that record against the
audit log: the chain verifies, every audit record the plan made is there and says the same thing, and every applied
step has its execute record (B36-3). No model is called.

B-42: ``audit_path`` is the client's own chain (``audit/<client>.jsonl``), so the completion record's ``audit_head``
and every ``dry_run_audit_seq`` are seqs in that chain, and ``reconcile`` verifies that chain alone.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

from core.audit import canonical_json, head_path_for, redact, verify_chain
from core.levers import LeverRunner, MockTenant
from core.levers.tenant import TenantError
from core.queue import Proposal, ProposalQueue, QueueError

PACKAGE_DIR = Path(__file__).resolve().parent
CONFIG: dict[str, Any] = json.loads((PACKAGE_DIR / "config.json").read_text(encoding="utf-8"))
LOB_FILE = PACKAGE_DIR / "data" / "lob-apps.json"

PlanStatus = Literal["proposed", "planned", "deferred", "already-met", "refused", "skipped"]
StepState = Literal["met", "not-met", "pending-retention", "not-applicable"]
# Steps whose lever must have been executed (an applied audit record) once the target state is met.
EXPECT_EXECUTE: tuple[str, ...] = ("proposed", "planned", "deferred")
# Steps whose plan must carry the audit seq of their dry-run.
EXPECT_DRY_RUN: tuple[str, ...] = ("proposed", "planned", "already-met", "refused")


class OffboardingError(ValueError):
    """The input cannot be used (no plan file, unreadable audit log); nothing was concluded."""


@dataclass
class Step:
    key: str
    label: str
    lever: str
    params: dict[str, Any]
    status: PlanStatus
    reason: str
    due_on: str | None = None
    proposal_id: str | None = None
    dry_run_audit_seq: int | None = None


@dataclass
class OffboardPlan:
    client: str
    upn: str
    as_of: str
    requester: str
    leave_at: str | None
    outcome: Literal["planned", "refused"]
    reason: str
    steps: list[Step] = field(default_factory=list)
    manual: list[dict[str, str]] = field(default_factory=list)
    lob_checklist: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    executed: bool = False  # always False: this workflow never runs a write lever

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _day(value: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise OffboardingError(f"{value!r} is not a date (YYYY-MM-DD)") from exc


def _facts(tenant: MockTenant, client: str) -> dict[str, Any]:
    """The read-only state the plan and the verify step compare against (client file plus family files)."""
    state = tenant.load_for_read(client)
    families: dict[str, Any] = state.get("_families", {})

    def rows(family: str, key: str) -> list[dict[str, Any]]:
        return [r for r in families.get(family, {}).get(key, []) if isinstance(r, dict)]

    return {
        "users": [u for u in state.get("users", []) if isinstance(u, dict)],
        "sessions": rows("sessions", "value"),
        "groups": rows("groups", "value"),
        "mailboxes": rows("mailboxes", "mailboxes"),
        "onedrive": rows("mailboxes", "oneDrive"),
        "assignments": rows("licenses", "assignments"),
        "as_of": str(families.get("mailboxes", {}).get("_meta", {}).get("as_of", ""))[:10] or None,
    }


def _same(a: object, b: str) -> bool:
    return isinstance(a, str) and a.lower() == b.lower()


def _mailbox(facts: dict[str, Any], upn: str) -> dict[str, Any] | None:
    return next((m for m in facts["mailboxes"] if _same(m.get("userPrincipalName"), upn)), None)


def _groups_of(facts: dict[str, Any], upn: str) -> list[dict[str, Any]]:
    return [g for g in facts["groups"] if any(_same(m.get("userPrincipalName"), upn) for m in g.get("members", []))]


def _licenses_of(facts: dict[str, Any], upn: str) -> list[dict[str, Any]]:
    return [a for a in facts["assignments"] if _same(a.get("userPrincipalName"), upn)]


def lob_checklist(client: str, lob_path: Path = LOB_FILE) -> list[dict[str, Any]]:
    """Line-of-business apps to close by hand, one checkbox each. Empty if the client has none listed."""
    data = json.loads(Path(lob_path).read_text(encoding="utf-8"))
    return [
        {
            "app": app,
            "action": "Remove or disable the person's account in this app",
            "done": False,
            "source": "synthetic stand-in for the client record",
        }
        for app in data.get("clients", {}).get(client, [])
    ]


def _drafts(upn: str, facts: dict[str, Any], as_of: date, manager: str | None) -> list[Step]:
    """Every step, in config order, with its lever params. A step that cannot be built says why (status skipped)."""
    box = _mailbox(facts, upn)
    spec: dict[str, dict[str, str]] = CONFIG["steps"]
    out: list[Step] = []

    def add(
        key: str,
        params: dict[str, Any],
        status: PlanStatus = "planned",
        reason: str = "",
        label: str = "",
        due_on: str | None = None,
    ) -> None:
        out.append(Step(key, label or spec[key]["label"], spec[key]["lever"], params, status, reason, due_on))

    for key in CONFIG["order"]:
        if key == "block-sign-in":
            add(key, {"upn": upn, "reason": CONFIG["block_reason"]})
        elif key == "revoke-sessions":
            add(key, {"upn": upn})
        elif key in ("convert-mailbox", "auto-reply", "onedrive-grant") and box is None:
            add(key, {"upn": upn}, "skipped", f"no mailbox for {upn}; nothing to do here")
        elif key == "convert-mailbox":
            add(key, {"upn": upn})
        elif key == "auto-reply":
            add(key, {"upn": upn, "message": CONFIG["auto_reply_message"]})
        elif key == "onedrive-grant":
            ends = (as_of + timedelta(days=int(CONFIG["onedrive_days"]))).isoformat()
            params = {"upn": upn, "manager": manager or "", "expires_on": ends}
            if manager is None:
                why = "no manager was named, so no OneDrive grant was planned (name one with --manager)"
                add(key, params, "skipped", why)
            else:
                add(key, params)
        elif key == "remove-group":
            for group in _groups_of(facts, upn):
                label = f"{spec[key]['label']} {group.get('displayName', group['id'])}"
                add(key, {"upn": upn, "group_id": str(group["id"])}, label=label)
        elif key == "remove-license":
            for row in _licenses_of(facts, upn):
                sku, ends_on = str(row["skuPartNumber"]), row.get("retentionEndsOn")
                params = {"upn": upn, "sku": sku}
                label = f"{spec[key]['label']} ({sku})"
                if not isinstance(ends_on, str):
                    why = f"no retention window is recorded for {sku}, so it is not due for removal"
                    add(key, params, "skipped", why, label)
                elif as_of <= _day(ends_on):
                    why = f"the retention window for {sku} ends {ends_on}; not proposed before then"
                    add(key, params, "deferred", why, label, ends_on)
                else:
                    add(key, params, label=label, due_on=ends_on)
    return out


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
    proposal = Proposal.new(
        source=CONFIG["queue_source"],
        ref=ref,
        lever=step.lever,
        client=client,
        params=step.params,
        requested_by=requester,
        reason=f"Offboarding: {step.label}"[:200],
    )
    try:
        stored = queue.add(proposal)
    except QueueError as exc:
        step.status, step.reason = "refused", f"not queued: {exc}"
        return
    step.proposal_id = stored.id
    if stored.status == "pending":
        step.status = "proposed"
    else:
        step.status = "refused"
        step.reason = f"an earlier proposal with the same id is already {stored.status}; nothing new was queued"


def plan(
    runner: LeverRunner,
    client: str,
    upn: str,
    requester: str,
    manager: str | None = None,
    leave_at: str | None = None,
    as_of: str | None = None,
    queue: ProposalQueue | None = None,
    lob_path: Path = LOB_FILE,
) -> OffboardPlan:
    """Build the offboarding plan for ``upn``; ``requester`` is the technician proposing it. ``as_of`` is a date."""

    def refused(reason: str, day: str = "") -> OffboardPlan:
        return OffboardPlan(client, upn, day, requester, leave_at, "refused", reason)

    try:
        facts = _facts(runner.tenant, client)
    except TenantError as exc:
        return refused(f"no readable tenant state for {client}: {exc}")
    day = (as_of or facts["as_of"] or "")[:10]
    if not day:
        return refused("no as-of date: pass one, the client's mailbox state has none")
    if not any(_same(u.get("userPrincipalName"), upn) for u in facts["users"]):
        return refused(f"{upn} is not a user of {client}; nothing was planned", day)
    steps = _drafts(upn, facts, _day(day), manager)
    for index, step in enumerate(steps):
        if step.status == "planned":
            _dry_run_and_queue(runner, step, client, requester, queue, f"offboard-{upn.split('@')[0]}-{index + 1}")
    result = OffboardPlan(client, upn, day, requester, leave_at, "planned", "plan built; nothing was executed")
    result.steps = steps
    result.manual = [{"step": text, "status": str(CONFIG["device_label"])} for text in CONFIG["device_steps"]]
    result.lob_checklist = lob_checklist(client, lob_path)
    if not result.lob_checklist:
        result.notes.append("no line-of-business apps are listed for this client; ask the client")
    if not any(s.key == "remove-group" for s in steps):
        result.notes.append("the person is in no group; no group removal planned")
    if not any(s.key == "remove-license" for s in steps):
        result.notes.append("the person holds no license; no license removal planned")
    return result


# -- verify: read-only, writes the completion record ----------------------------------------------------------


def _observe(step: dict[str, Any], facts: dict[str, Any], as_of: date) -> tuple[StepState, str]:
    """Compare one step's target state with the tenant files. Returns (state, what was observed)."""
    key, params = step["key"], step["params"]
    upn = str(params.get("upn", ""))
    box = _mailbox(facts, upn)
    if key in ("convert-mailbox", "auto-reply", "onedrive-grant") and box is None:
        return "not-applicable", "no mailbox"
    if key == "onedrive-grant" and step["status"] == "skipped":
        return "not-met", step["reason"]
    if key == "block-sign-in":
        user = next((u for u in facts["users"] if _same(u.get("userPrincipalName"), upn)), None)
        if user is None:
            return "not-met", "user not found"
        enabled = user.get("accountEnabled")
        return ("met" if enabled is False else "not-met"), f"accountEnabled is {enabled}"
    if key == "revoke-sessions":
        row = next((s for s in facts["sessions"] if _same(s.get("userPrincipalName"), upn)), None)
        if row is None:
            return "not-met", "no session record for the user"
        count = row.get("activeSessionCount")
        return ("met" if count == 0 else "not-met"), f"{count} active sessions"
    if key == "convert-mailbox" and box is not None:
        kind = box.get("recipientTypeDetails")
        return ("met" if kind == "SharedMailbox" else "not-met"), f"mailbox type is {kind}"
    if key == "auto-reply" and box is not None:
        state = (box.get("autoReply") or {}).get("state")
        return ("met" if state == "Enabled" else "not-met"), f"auto-reply is {state}"
    if key == "onedrive-grant":
        drive = next((d for d in facts["onedrive"] if _same(d.get("owner"), upn)), None)
        grants = [g for g in (drive or {}).get("access", []) if _same(g.get("grantee"), str(params.get("manager")))]
        match = [g for g in grants if g.get("expiresOn") == params.get("expires_on")]
        seen = f"grant until {match[0]['expiresOn']}" if match else "no matching grant"
        return ("met" if match else "not-met"), seen
    if key == "remove-group":
        group = next((g for g in facts["groups"] if g.get("id") == params.get("group_id")), None)
        member = group is not None and any(_same(m.get("userPrincipalName"), upn) for m in group.get("members", []))
        return ("not-met" if member else "met"), ("still a member" if member else "not a member")
    if key == "remove-license":
        held = [a for a in _licenses_of(facts, upn) if a.get("skuPartNumber") == params.get("sku")]
        if not held:
            return "met", "license not assigned"
        due = step.get("due_on")
        if isinstance(due, str) and as_of <= _day(due):
            return "pending-retention", f"license still assigned; the retention window ends {due}"
        return "not-met", "license still assigned"
    return "not-met", f"unknown step {key!r}"


def _read_records(audit_path: Path) -> list[dict[str, Any]]:
    try:
        lines = Path(audit_path).read_text(encoding="utf-8").splitlines()
        return [r for r in (json.loads(x) for x in lines if x.strip()) if isinstance(r, dict)]
    except (OSError, ValueError) as exc:
        raise OffboardingError(f"cannot read the audit log {audit_path}: {exc}") from exc


def record_path(out_dir: Path, client: str, upn: str, kind: str) -> Path:
    """Where the plan (``kind`` plan) or the completion record (``kind`` completion) of one leaver is kept."""
    return Path(out_dir) / f"{client}--{upn.split('@')[0]}.{kind}.json"


def verify(
    plan_data: dict[str, Any],
    tenant: MockTenant,
    audit_path: Path,
    as_of: str | None = None,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Read every target state, list every step not in it, and write the completion record (when ``out_dir``).

    Changes nothing in the tenant or the audit log. ``complete`` is true only when no step is not-met and no license
    is still inside its retention window.
    """
    client, upn = str(plan_data["client"]), str(plan_data["upn"])
    facts = _facts(tenant, client)
    day = (as_of or facts["as_of"] or str(plan_data["as_of"]))[:10]
    steps: list[dict[str, Any]] = []
    for raw in plan_data["steps"]:
        state, observed = _observe(raw, facts, _day(day))
        steps.append(
            {
                "key": raw["key"],
                "label": raw["label"],
                "lever": raw["lever"],
                "params": raw["params"],
                "planned_status": raw["status"],
                "due_on": raw.get("due_on"),
                "proposal_id": raw.get("proposal_id"),
                "dry_run_audit_seq": raw.get("dry_run_audit_seq"),
                "state": state,
                "observed": observed,
            }
        )
    not_met = [{"step": s["label"], "reason": s["observed"]} for s in steps if s["state"] == "not-met"]
    pending = [{"step": s["label"], "reason": s["observed"]} for s in steps if s["state"] == "pending-retention"]
    records = _read_records(audit_path) if Path(audit_path).exists() else []
    body: dict[str, Any] = {
        "kind": "offboarding-completion",
        "client": client,
        "upn": upn,
        "as_of": day,
        "complete": not not_met and not pending,
        "not_met": not_met,
        "pending_retention": pending,
        "steps": steps,
        "manual_until_w6": plan_data.get("manual", []),
        "lob_checklist": plan_data.get("lob_checklist", []),
        "audit_seqs": sorted({s["dry_run_audit_seq"] for s in steps if s["dry_run_audit_seq"] is not None}),
        "audit_head": {"seq": records[-1]["seq"], "hash": records[-1]["hash"]} if records else None,
    }
    record = {**body, "sha256": hashlib.sha256(canonical_json(body)).hexdigest()}
    if out_dir is not None:
        target = record_path(out_dir, client, upn, "completion")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return record


# -- reconcile: the completion record against the audit log (B36-3) -------------------------------------------


def reconcile(record: dict[str, Any], audit_path: Path) -> dict[str, Any]:
    """Check ``record`` against the audit log. ``ok`` is false when anything does not match; each problem is listed."""
    problems: list[str] = []
    body = {k: v for k, v in record.items() if k != "sha256"}
    if record.get("sha256") != hashlib.sha256(canonical_json(body)).hexdigest():
        problems.append("the completion record's own sha256 does not match its content (it was edited)")
    head_file = head_path_for(Path(audit_path))
    chain = verify_chain(Path(audit_path), head_file if head_file.exists() else None)
    if not chain.ok:
        problems.append(f"the audit chain does not verify ({chain.reason}); nothing in it is trusted")
        return {"ok": False, "problems": problems, "checked": 0}
    by_seq = {r["seq"]: r for r in _read_records(audit_path)}
    pinned = record.get("audit_head")
    if isinstance(pinned, dict) and by_seq.get(pinned.get("seq"), {}).get("hash") != pinned.get("hash"):
        problems.append(f"the audit head the record pinned (seq {pinned.get('seq')}) is not in the log")
    checked = 0
    for step in record.get("steps", []):
        label, params, client = step["label"], redact(step["params"]), record["client"]
        seq = step.get("dry_run_audit_seq")
        if seq is None:
            if step["planned_status"] in EXPECT_DRY_RUN:
                problems.append(f"{label}: the plan has no dry-run audit seq")
        elif (found := by_seq.get(seq)) is None:
            problems.append(f"{label}: audit seq {seq} is missing from the log")
        else:
            checked += 1
            if (found["lever"], found["client"], found["mode"], found["params"]) != (
                step["lever"],
                client,
                "dry-run",
                params,
            ):
                problems.append(f"{label}: audit seq {seq} is not the dry-run of this step (lever, client or params)")
        if step["state"] == "met" and step["planned_status"] in EXPECT_EXECUTE:
            applied = [
                r
                for r in by_seq.values()
                if (r["mode"], r["lever"], r["client"], r["params"]) == ("execute", step["lever"], client, params)
                and (r.get("result") or {}).get("applied") is True
            ]
            if not applied:
                problems.append(f"{label}: the step is in its target state but no applied audit record matches it")
    return {"ok": not problems, "problems": problems, "checked": checked}


def summary(result: OffboardPlan) -> dict[str, Any]:
    return result.to_dict()
