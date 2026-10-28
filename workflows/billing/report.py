"""Billing classification and time-entry note quality report (B-76; W-BIL-01, W-BIL-03; C-14, C-41).

Read-only. For one client, reads its synthetic billing fixture (contract scope, tickets, time entries), classifies each
entry (``rules``), scores each note (``notes``), and writes one review file plus a ``.sha256`` sidecar (JSON), and a
Markdown rendering of the same rows. Every correction is a *proposal*: ``status: proposed``, ``approval: null``,
``applied: false``. Nothing here writes to a PSA, an invoice or the fixture; a person approves and applies any change.

Nothing is scored or grouped per technician (B76-3): the technician is not copied into the report, and note quality
is summarised by element and by client only.

Only a lead scoped to the client may run it. Every run and refusal is one ``job.run`` record in the client's audit
chain (B-42); the record carries the file's SHA-256 (grouped, STD-AU-5), never the rows.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from core.audit.chain import ActorKind
from core.audit.router import AuditRouter
from core.guard.classify import DataClass
from core.identity import IdentityConfigError, IdentityStore, Role, UnknownIdentity
from core.paths import REPO_ROOT
from workflows.access_review.review import audit_digest, canonical_bytes, sha256_hex, sidecar_for
from workflows.billing import notes
from workflows.billing.rules import (
    CATEGORIES,
    PSA_CODE_TO_CATEGORY,
    UNCLASSIFIED,
    BillingError,
    Classification,
    classify_entries,
)

DEFAULT_FIXTURES = Path(__file__).with_name("fixtures")
DEFAULT_OUT_DIR = REPO_ROOT / "build" / "billing"
DEFAULT_IDENTITIES = REPO_ROOT / "config" / "identities.json"
DEFAULT_AUDIT_DIR = REPO_ROOT / ".tmp" / "demo" / "audit"
KIND = "billing-review"
VERSION = 1
LEVER = "billing.review"
CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
DATA_CLASS = DataClass.DC3
NOTE = (
    "Synthetic data (fixture-based). A suggestion for a lead to review. Classification never changes an invoice, a "
    "PSA billing code or a time entry: every correction below is a proposal that a person approves and applies."
)


class VerifyError(ValueError):
    """A file does not match its hash, or it claims something this workflow never does (an applied proposal)."""


@dataclass(frozen=True)
class Written:
    json_path: Path
    md_path: Path
    sha256: str
    rows: int


def _client_id(client: str) -> str:
    if not isinstance(client, str) or not CLIENT_ID.fullmatch(client):
        raise BillingError(f"{client!r} is not a client id")
    return client


def load_fixture(client: str, fixtures_dir: Path = DEFAULT_FIXTURES) -> tuple[dict[str, Any], Path]:
    path = Path(fixtures_dir) / f"{_client_id(client)}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BillingError(f"no readable billing fixture for {client}: {type(exc).__name__}") from None
    if (
        not isinstance(data, dict)
        or data.get("client") != client
        or not isinstance(data.get("contract"), dict)
        or not isinstance(data.get("tickets"), list)
        or not isinstance(data.get("entries"), list)
    ):
        raise BillingError(f"billing fixture for {client} is malformed or belongs to another client")
    ids = [e.get("id") if isinstance(e, dict) else None for e in data["entries"]]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise BillingError("every time entry needs a unique string id")
    return data, path


def _valid_hours(entry: dict[str, Any]) -> float:
    h = entry.get("hours")
    return float(h) if isinstance(h, (int, float)) and not isinstance(h, bool) and h > 0 else 0.0


def _proposals(entry: dict[str, Any], cls: Classification, quality: notes.NoteQuality) -> list[dict[str, Any]]:
    base = {"status": "proposed", "approval": None, "applied": False}
    out: list[dict[str, Any]] = []
    current = entry.get("psa_billing_code")
    if cls.category == UNCLASSIFIED:
        out.append(
            {
                **base,
                "proposal_id": f"{entry['id']}:billing",
                "kind": "classify-by-hand",
                "from": current,
                "to": None,
                "why": "no contract clause matches; a person must decide the category",
            }
        )
    elif current is not None and PSA_CODE_TO_CATEGORY.get(str(current)) != cls.category:
        out.append(
            {
                **base,
                "proposal_id": f"{entry['id']}:billing",
                "kind": "billing-code-change",
                "from": current,
                "to": cls.category,
                "why": f"clause {cls.clause_id} says {cls.category}; the PSA code says {current!r}",
            }
        )
    if quality.band != "good":
        out.append(
            {
                **base,
                "proposal_id": f"{entry['id']}:note",
                "kind": "note-rewrite",
                "from": entry.get("note"),
                "to": quality.draft,
                "why": "missing: " + ", ".join(quality.missing) if quality.missing else "vague wording",
            }
        )
    return out


def build_report(client: str, *, as_of: str, by: str, fixtures_dir: Path = DEFAULT_FIXTURES) -> dict[str, Any]:
    try:
        date.fromisoformat(as_of)
    except ValueError:
        raise BillingError(f"as_of must be an ISO date (YYYY-MM-DD), got {as_of!r}") from None
    data, path = load_fixture(client, fixtures_dir)
    tickets = {str(t["ticket"]): t for t in data["tickets"]}
    entries: list[dict[str, Any]] = data["entries"]
    for e in entries:
        if str(e.get("ticket")) not in tickets:
            raise BillingError(f"entry {e['id']} names a ticket the fixture does not have")
    classes = classify_entries(data["contract"], tickets, entries)
    rows: list[dict[str, Any]] = []
    counts = dict.fromkeys((*CATEGORIES, UNCLASSIFIED), 0)
    hours = dict.fromkeys((*CATEGORIES, UNCLASSIFIED), 0.0)
    missing_counts = dict.fromkeys(("what", "why", "outcome", "time"), 0)
    vague_entries = 0
    proposals_total = 0
    for entry in entries:
        cls = classes[entry["id"]]
        title = tickets[str(entry["ticket"])].get("title")
        quality = notes.assess(entry, title if isinstance(title, str) else None)
        props = _proposals(entry, cls, quality)
        proposals_total += len(props)
        counts[cls.category] += 1
        if cls.covered_hours is not None and cls.billable_hours:
            hours["contract-covered"] += cls.covered_hours
            hours[cls.category] += cls.billable_hours
        else:
            hours[cls.category] += _valid_hours(entry)
        for m in quality.missing:
            missing_counts[m] += 1
        vague_entries += 1 if quality.vague_terms else 0
        rows.append(
            {
                "row_id": entry["id"],
                "ticket": entry["ticket"],
                "ticket_title": title,
                "date": entry.get("date"),
                "hours": entry.get("hours"),
                "work_type": entry.get("work_type"),
                "classification": {
                    "category": cls.category,
                    "clause": cls.clause_id,
                    "clause_text": cls.clause_text,
                    "reasons": cls.reasons,
                    "flags": cls.flags,
                    "covered_hours": cls.covered_hours,
                    "billable_hours": cls.billable_hours,
                    "psa_billing_code": entry.get("psa_billing_code"),
                },
                "note_quality": {
                    "score": quality.score,
                    "band": quality.band,
                    "missing": quality.missing,
                    "vague_terms": quality.vague_terms,
                    "reasons": quality.reasons,
                },
                "proposals": props,
                "decision": None,
            }
        )
    good = sum(1 for r in rows if r["note_quality"]["band"] == "good")
    dates = sorted(str(e.get("date")) for e in entries)
    return {
        "kind": KIND,
        "version": VERSION,
        "client": client,
        "as_of": as_of,
        "period": {"first": dates[0] if dates else None, "last": dates[-1] if dates else None},
        "generated_by": by,
        "data_class": DATA_CLASS.value,
        "label": "fixture-based",
        "note": NOTE,
        "invoice_effect": "none",
        "contract": {"id": data["contract"].get("id")},
        "sources": [{"path": f"workflows/billing/fixtures/{path.name}", "sha256": sha256_hex(path.read_bytes())}],
        "decision_options": ["approve", "reject", "investigate"],
        "summary": {
            "entries": len(rows),
            "entries_by_category": counts,
            "hours_by_category": {k: round(v, 2) for k, v in hours.items()},
            "notes_good": good,
            "notes_needs_work": len(rows) - good,
            "notes_missing_by_element": missing_counts,
            "notes_with_vague_wording": vague_entries,
            "proposals": {"total": proposals_total, "applied": 0},
        },
        "rows": rows,
    }


def render_markdown(body: dict[str, Any]) -> str:
    s = body["summary"]
    lines = [
        f"# Billing review: {body['client']} ({body['period']['first']} to {body['period']['last']})",
        "",
        f"> {body['note']}",
        "",
        f"Label: {body['label']}. As of {body['as_of']}. Invoice effect: {body['invoice_effect']}.",
        "",
        "## Summary (fixture-based)",
        "",
        "| Category | Entries | Hours |",
        "| --- | ---: | ---: |",
    ]
    for cat in (*CATEGORIES, UNCLASSIFIED):  # fixed order: the JSON is key-sorted, the Markdown must not depend on it
        lines.append(f"| {cat} | {s['entries_by_category'][cat]} | {s['hours_by_category'][cat]:g} |")
    miss = ", ".join(f"{k} {s['notes_missing_by_element'][k]}" for k in ("what", "why", "outcome", "time"))
    lines += [
        "",
        f"Notes: {s['notes_good']} good, {s['notes_needs_work']} need work. Missing by element: {miss}. "
        f"Vague wording in {s['notes_with_vague_wording']} notes. Proposals: {s['proposals']['total']} "
        f"(applied: {s['proposals']['applied']}).",
        "",
        "## Entries",
    ]
    for r in body["rows"]:
        c, q = r["classification"], r["note_quality"]
        lines += [
            "",
            f"### {r['row_id']} ({r['ticket']}: {r['ticket_title']})",
            "",
            f"- Suggested category: **{c['category']}**"
            + (f", clause {c['clause']}: {c['clause_text']}" if c["clause"] else ""),
            *[f"  - {x}" for x in c["reasons"]],
            *([f"- Flags: {', '.join(c['flags'])}"] if c["flags"] else []),
            f"- Note quality: {q['score']}/100 ({q['band']})",
            *[f"  - {x['rule']} ({x['element']}): {x['evidence']}" for x in q["reasons"]],
        ]
        for p in r["proposals"]:
            lines.append(f"- Proposal {p['proposal_id']} [{p['kind']}], status {p['status']}, not applied: {p['why']}")
            if p["kind"] == "note-rewrite":
                lines.append(f"  - {p['to']}")
    return "\n".join(lines) + "\n"


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _lead(identities: IdentityStore, who: str, client: str) -> str | None:
    try:
        ident = identities.get(who)
    except UnknownIdentity:
        return f"unknown identity {who!r}"
    if ident.role is not Role.LEAD:
        return f"role {ident.role.value!r} cannot run a billing review (needs lead)"
    if not ident.can_act_for(client):
        return f"{who} is not scoped to {client!r}"
    return None


def _actor_kind(identities: IdentityStore, who: str) -> ActorKind:
    if who not in identities:
        return "unknown"
    return "agent" if identities.get(who).role is Role.AGENT else "human"


def export(
    client: str,
    *,
    as_of: str,
    by: str,
    out_dir: Path = DEFAULT_OUT_DIR,
    audit_dir: Path = DEFAULT_AUDIT_DIR,
    fixtures_dir: Path = DEFAULT_FIXTURES,
    identities_path: Path = DEFAULT_IDENTITIES,
) -> Written:
    """Write ``<out>/<client>.json`` (+ ``.sha256``) and ``<client>.md``; audit the run or the refusal."""
    _client_id(client)
    try:
        identities = IdentityStore.load(identities_path)
    except IdentityConfigError as exc:
        raise BillingError(str(exc)) from None
    audit = AuditRouter(audit_dir)
    params = {"as_of": as_of}

    def record(result: dict[str, Any]) -> None:
        audit.append(
            agent=by,
            client=client,
            lever=LEVER,
            params=params,
            mode="execute",
            result=result,
            event="job.run",
            actor_kind=_actor_kind(identities, by),
            lever_version=VERSION,
        )

    refused = _lead(identities, by, client)
    if refused is not None:
        record({"status": "denied", "reason": refused})
        raise BillingError(refused)
    try:
        body = build_report(client, as_of=as_of, by=by, fixtures_dir=fixtures_dir)
    except BillingError as exc:
        record({"status": "denied", "reason": str(exc)[:200]})
        raise
    data = canonical_bytes(body)
    digest = sha256_hex(data)
    json_path = Path(out_dir) / f"{client}.json"
    _write(json_path, data)
    sidecar_for(json_path).write_text(f"{digest}  {json_path.name}\n", encoding="ascii", newline="\n")
    md_path = json_path.with_suffix(".md")
    _write(md_path, render_markdown(body).encode("utf-8"))
    record(
        {
            "status": "ok",
            "sha256": audit_digest(digest),
            "rows": len(body["rows"]),
            "proposals": body["summary"]["proposals"]["total"],
        }
    )
    return Written(json_path, md_path, digest, len(body["rows"]))


def verify(path: Path) -> str:
    """Re-hash the JSON against its sidecar and check it claims nothing was applied or decided."""
    path = Path(path)
    side = sidecar_for(path)
    try:
        data = path.read_bytes()
        want = side.read_text(encoding="ascii").split()[0]
    except (OSError, IndexError, UnicodeDecodeError) as exc:
        raise VerifyError(f"cannot read {path.name} or its sidecar: {type(exc).__name__}") from None
    digest = sha256_hex(data)
    if digest != want:
        raise VerifyError(f"{path.name} does not match its sidecar")
    try:
        body = json.loads(data)
        rows = body["rows"]
    except (ValueError, KeyError, TypeError):
        raise VerifyError(f"{path.name} is not a billing review") from None
    if body.get("kind") != KIND or body.get("invoice_effect") != "none":
        raise VerifyError(f"{path.name} is not a billing review")
    for r in rows:
        if r.get("decision") is not None:
            raise VerifyError(f"row {r.get('row_id')} has a decision filled in; reviews are decided elsewhere")
        for p in r.get("proposals", []):
            if p.get("applied") is not False or p.get("status") != "proposed" or p.get("approval") is not None:
                raise VerifyError(f"proposal {p.get('proposal_id')} is not a plain proposal; nothing is applied here")
    return digest
