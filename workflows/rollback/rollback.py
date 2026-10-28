"""Rollback from the recorded before-state (B-41, specs/B-41.md; W-GOV-04, W-CMP-04; C-33, C-31, C-08).

``plan`` reads one applied audit record. If the lever has a registered ``undo``, it dry-runs that undo through the
runner (audited) and checks that the undo's diff is exactly the recorded changes with before and after swapped;
only then does it build a ``rollback`` proposal for the normal queue (IR-3: a lead still approves it). If the lever
has no ``undo`` it returns the manual steps from the lever README and proposes nothing. It never executes a write lever.

The audit copy of a diff is masked (DR-02), so a diff that holds a masked value cannot be compared and is reported as
``drifted`` rather than guessed. No model is called.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from core.audit import verify_chain
from core.levers import LeverRunner
from core.levers.runner import mask_change
from core.queue import Proposal, ProposalQueue, QueueError

LEVERS_DIR = Path(__file__).resolve().parents[2] / "levers"
Outcome = Literal["proposed", "manual", "nothing-to-undo", "drifted", "refused"]
OK_OUTCOMES: frozenset[str] = frozenset({"proposed", "manual", "nothing-to-undo"})
_SECTION = re.compile(r"^## (\S+)\s*$")


class RollbackError(ValueError):
    """The audit log cannot be read; nothing was concluded."""


@dataclass(frozen=True)
class Rollback:
    outcome: Outcome
    reason: str
    audit_seq: int
    lever: str | None = None
    client: str | None = None
    undo_lever: str | None = None
    params: dict[str, Any] | None = None
    before_state: tuple[dict[str, Any], ...] = ()
    manual_steps: str | None = None
    proposal: Proposal | None = None
    dry_run_audit_seq: int | None = None
    executed: bool = False  # always False: this workflow never runs a write lever
    notes: list[str] = field(default_factory=list)


def _read_records(audit_path: Path) -> list[dict[str, Any]]:
    try:
        lines = Path(audit_path).read_text(encoding="utf-8").splitlines()
        return [r for r in (json.loads(line) for line in lines if line.strip()) if isinstance(r, dict)]
    except (OSError, ValueError) as exc:
        raise RollbackError(f"cannot read the audit log {audit_path}: {exc}") from exc


def readme_section(lever: str, levers_dir: Path = LEVERS_DIR) -> str | None:
    """The ``## <lever>`` section of a lever module README, or None if no README has one."""
    for readme in sorted(Path(levers_dir).glob("*/*/README.md")):
        lines = readme.read_text(encoding="utf-8").splitlines()
        start = next((i for i, line in enumerate(lines) if (m := _SECTION.match(line)) and m.group(1) == lever), None)
        if start is None:
            continue
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        return "\n".join(lines[start:end]).strip()
    return None


def _key(change: dict[str, Any]) -> str:
    return json.dumps(
        [change.get("op"), change.get("path"), change.get("before"), change.get("after")], sort_keys=True, default=str
    )


def _inverse(change: dict[str, Any]) -> dict[str, Any]:
    swap = {"add": "remove", "remove": "add", "replace": "replace"}
    return {
        "op": swap.get(str(change.get("op")), "?"),
        "path": change.get("path"),
        "before": change.get("after"),
        "after": change.get("before"),
    }


def _refused(seq: int, reason: str, record: dict[str, Any] | None = None) -> Rollback:
    return Rollback("refused", reason, seq, lever=(record or {}).get("lever"), client=(record or {}).get("client"))


def plan(
    runner: LeverRunner,
    audit_path: Path,
    audit_seq: int,
    requester: str,
    queue: ProposalQueue | None = None,
    levers_dir: Path = LEVERS_DIR,
) -> Rollback:
    """Build the rollback for the applied change at ``audit_seq``; ``requester`` is the technician proposing it."""
    audit_path = Path(audit_path)
    chain = verify_chain(audit_path)
    if not chain.ok:
        return _refused(audit_seq, f"the audit chain does not verify ({chain.reason}); its before-state is not trusted")
    record = next((r for r in _read_records(audit_path) if r.get("seq") == audit_seq), None)
    if record is None:
        return _refused(audit_seq, f"no audit record with seq {audit_seq}")
    raw_result = record.get("result")
    result: dict[str, Any] = raw_result if isinstance(raw_result, dict) else {}
    lever, client, params = record.get("lever"), record.get("client"), record.get("params")
    if record.get("mode") != "execute" or result.get("applied") is not True:
        return _refused(audit_seq, "that record is not an applied change (mode execute, applied true)", record)
    spec = runner.registry.get(str(lever))
    if spec is None or spec.lever_class != "write" or not isinstance(client, str) or not isinstance(params, dict):
        return _refused(audit_seq, f"{lever!r} is not a registered write lever, or the record has no client", record)
    recorded = tuple(c for c in result.get("changes", []) if isinstance(c, dict))
    base: dict[str, Any] = {"lever": spec.name, "client": client, "before_state": recorded}

    if spec.undo is None:
        steps = readme_section(spec.name, levers_dir)
        note = "No README section for this lever documents manual steps." if steps is None else ""
        reason = f"{spec.name} has no registered undo lever; follow the manual steps and propose nothing. {note}"
        return Rollback("manual", reason.strip(), audit_seq, manual_steps=steps, **base)

    undo = runner.registry.get(spec.undo)
    assert undo is not None  # the registry refuses an undo that is not a registered write lever
    undo_params = {name: params[name] for name in undo.params if name in params}
    missing = [name for name, p in undo.params.items() if p.required and name not in undo_params]
    if missing:
        reason = f"cannot build {undo.name} params from the record: missing {', '.join(missing)}"
        return Rollback("refused", reason, audit_seq, undo_lever=undo.name, **base)

    dry = runner.invoke(undo.name, undo_params, requester, client, "dry-run")
    base["dry_run_audit_seq"] = dry.audit_seq
    if not dry.ok:
        reason = f"the dry-run of {undo.name} was refused: {dry.reason}"
        return Rollback("refused", reason, audit_seq, undo_lever=undo.name, **base)
    shared = {"undo_lever": undo.name, "params": undo_params, **base}
    if not dry.diff:
        reason = "the current state already equals the recorded before-state; nothing proposed"
        return Rollback("nothing-to-undo", reason, audit_seq, **shared)
    expected = sorted(_key(_inverse(c)) for c in recorded)
    actual = sorted(_key(mask_change(c)) for c in dry.diff)
    if not recorded or expected != actual:
        reason = (
            "the undo would not restore exactly the recorded before-state (the state changed since, or the record "
            "holds masked values); nothing proposed, a person should read the current state first"
        )
        return Rollback("drifted", reason, audit_seq, **shared)

    proposal = Proposal.new(
        source="rollback",
        ref=f"audit-{audit_seq}",
        lever=undo.name,
        client=client,
        params=undo_params,
        requested_by=requester,
        reason=f"Rollback of audit seq {audit_seq} ({spec.name}): restore the recorded before-state",
    )
    if queue is not None:
        try:
            proposal = queue.add(proposal)
        except QueueError as exc:
            return Rollback("refused", f"not queued: {exc}", audit_seq, **shared)
        if proposal.status != "pending":
            reason = f"an earlier proposal with the same id is already {proposal.status}; nothing new was queued"
            return Rollback("refused", reason, audit_seq, **shared)
    reason = f"{undo.name} proposed from the recorded before-state; a lead approves it like any other change (IR-3)"
    return Rollback("proposed", reason, audit_seq, proposal=proposal, **shared)


def summary(rb: Rollback) -> dict[str, Any]:
    return {
        "outcome": rb.outcome,
        "reason": rb.reason,
        "audit_seq": rb.audit_seq,
        "lever": rb.lever,
        "client": rb.client,
        "undo_lever": rb.undo_lever,
        "params": rb.params,
        "before_state": list(rb.before_state),
        "manual_steps": rb.manual_steps,
        "proposal_id": rb.proposal.id if rb.proposal else None,
        "dry_run_audit_seq": rb.dry_run_audit_seq,
        "executed": rb.executed,
    }
