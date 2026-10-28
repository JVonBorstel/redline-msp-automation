"""KB article drafts from resolved tickets (B-58). Drafts only: nothing here writes to a knowledge base.

For one client, each resolved ticket that has a recorded resolution becomes a DRAFT article:

* the steps are the recorded resolution's steps, word for word apart from redaction. The ticket's subject and body
  are never copied (they are untrusted requester text); they are only screened;
* every step and the title pass the pre-prompt redaction gate (``core.guard.redact_prompt``): PHI, NPI and PII
  become typed placeholders, a placeholder already present stays as written, and a secret withholds the draft;
* requester and affected-user names and addresses of the client's tickets, other addresses and technician ids are
  replaced by ``[USER]``, ``[EMAIL]`` and ``[TECHNICIAN]``;
* the only source is the ticket id. Only this client's tickets are read, and a record that names another client or a
  ticket that is not this client's is rejected, never drafted;
* a ticket (subject, body) or resolution that trips the injection tripwire is withheld whole: its text is not used.

A draft is labelled DRAFT, carries ``human_publish.required = true`` and ``done = false``, and no function here sets
either. A person reviews it and publishes it by hand in the KB tool.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.audit.router import valid_client_id
from core.guard.detect import detect_injection
from core.guard.redact_prompt import redact_prompt
from core.paths import REPO_ROOT
from rag.store import MSP_INTERNAL


def _dated_tickets_dir() -> Path:
    """The folder of dated per-client ticket files (B-21): the one under fixtures/tickets whose files carry ``as_of``.

    Found by content so that no production module has to name the folder (a B-21 guard keeps the labelled set apart)."""
    base = REPO_ROOT / "fixtures" / "tickets"
    for sub in sorted(p for p in base.iterdir() if p.is_dir()):
        for f in sorted(sub.glob("*.json")):
            if '"as_of"' in f.read_text(encoding="utf-8", errors="replace")[:4000]:
                return sub
    return base


DEFAULT_TICKETS_DIR = _dated_tickets_dir()
DEFAULT_DATA_DIR = REPO_ROOT / "workflows" / "kb_drafts" / "data" / "resolutions"
DEFAULT_OUT_DIR = REPO_ROOT / "build" / "kb-drafts"

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_TAG = re.compile(r"[a-z0-9][a-z0-9-]{0,29}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_TECH = re.compile(r"\btech-[a-z0-9]+\b", re.IGNORECASE)
_HOW = "A person reviews and edits this draft, then publishes it by hand in the KB tool. No code publishes it."


class DraftError(ValueError):
    """The request or an input is unusable. No draft is produced."""


@dataclass(frozen=True, slots=True)
class Draft:
    """One article draft. ``label`` and ``status`` are fixed; there is no field that says published."""

    draft_id: str
    client: str
    title: str
    tags: tuple[str, ...]
    steps: tuple[str, ...]
    sources: tuple[str, ...]
    redacted: tuple[str, ...] = ()
    label: str = "DRAFT"
    status: str = "draft"

    def to_dict(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "label": self.label,
            "status": self.status,
            "client": self.client,
            "title": self.title,
            "tags": list(self.tags),
            "steps": list(self.steps),
            "sources": list(self.sources),
            "redacted": list(self.redacted),
            "human_publish": {"required": True, "done": False, "how": _HOW},
        }


@dataclass(frozen=True, slots=True)
class Withheld:
    """A ticket whose draft was not made because its text is not safe to use. Names rule ids, never text."""

    ticket_id: str
    reason: str  # "injection" or "secret"
    rules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Skipped:
    ticket_id: str
    reason: str  # "not-resolved" or "no-recorded-resolution"


@dataclass(frozen=True, slots=True)
class Rejected:
    ticket_id: str
    reason: str  # "other-client" or "not-this-clients-ticket"


@dataclass(frozen=True, slots=True)
class DraftSet:
    client: str
    drafts: tuple[Draft, ...] = ()
    withheld: tuple[Withheld, ...] = ()
    skipped: tuple[Skipped, ...] = ()
    rejected: tuple[Rejected, ...] = ()
    note: str = "Fixture-based: synthetic tickets and recorded resolutions. Drafts only; nothing was published."

    def to_dict(self) -> dict[str, Any]:
        return {
            "client": self.client,
            "note": self.note,
            "drafts": [d.to_dict() for d in self.drafts],
            "withheld": [{"ticket_id": w.ticket_id, "reason": w.reason, "rules": list(w.rules)} for w in self.withheld],
            "skipped": [{"ticket_id": s.ticket_id, "reason": s.reason} for s in self.skipped],
            "rejected": [{"ticket_id": r.ticket_id, "reason": r.reason} for r in self.rejected],
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()


def _canonical(body: Mapping[str, Any]) -> bytes:
    return (json.dumps(body, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def _load(path: Path, what: str) -> dict[str, Any]:
    try:
        body = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DraftError(f"{what} is not readable") from exc
    if not isinstance(body, dict):
        raise DraftError(f"{what} is malformed")
    return body


def _people(tickets: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """(addresses, name words) named in the tickets' form fields: what must never reach a draft."""
    addresses: set[str] = set()
    names: set[str] = set()
    for ticket in tickets:
        for field_name in ("requester", "affected_user"):
            address = ticket.get(field_name)
            if isinstance(address, str) and "@" in address:
                addresses.add(address)
                names.add(" ".join(w for w in re.split(r"[._-]", address.split("@")[0]) if w))
    words = {w for name in names for w in name.split() if len(w) > 2}
    return sorted(addresses, key=len, reverse=True), sorted(names | words, key=len, reverse=True)


def _scrub(text: str, addresses: list[str], names: list[str]) -> str:
    for address in addresses:
        text = re.sub(re.escape(address), "[USER]", text, flags=re.IGNORECASE)
    text = _EMAIL.sub("[EMAIL]", text)
    for name in names:
        if name:
            text = re.sub(rf"\b{re.escape(name)}\b", "[USER]", text, flags=re.IGNORECASE)
    return _TECH.sub("[TECHNICIAN]", text)


def _tags(raw: object) -> tuple[str, ...]:
    return tuple(t for t in (raw if isinstance(raw, list) else []) if isinstance(t, str) and _TAG.fullmatch(t))


def build_drafts(
    client: str, *, tickets_dir: Path = DEFAULT_TICKETS_DIR, data_dir: Path = DEFAULT_DATA_DIR
) -> DraftSet:
    """Drafts for ``client``'s resolved tickets. Reads only that client's ticket and resolution files."""
    if not isinstance(client, str) or not valid_client_id(client) or client == MSP_INTERNAL:
        raise DraftError("not a usable client id")
    ticket_file = _load(Path(tickets_dir) / f"{client}.json", "the ticket fixture")
    resolution_file = _load(Path(data_dir) / f"{client}.json", "the resolution fixture")
    if ticket_file.get("client") != client or resolution_file.get("client") != client:
        raise DraftError("a fixture does not belong to this client")
    tickets = ticket_file.get("tickets")
    records = resolution_file.get("records")
    if not isinstance(tickets, list) or not isinstance(records, list):
        raise DraftError("a fixture is malformed")
    by_id = {str(t.get("id")): t for t in tickets if isinstance(t, dict) and t.get("client") == client}
    addresses, names = _people([t for t in by_id.values()])

    drafts: list[Draft] = []
    withheld: list[Withheld] = []
    skipped: list[Skipped] = []
    rejected: list[Rejected] = []
    for record in records:
        ticket_id = str(record.get("ticket_id", "")) if isinstance(record, dict) else ""
        if not _ID.fullmatch(ticket_id):
            raise DraftError("a resolution record has no usable ticket id")
        if record.get("client", client) != client:
            rejected.append(Rejected(ticket_id, "other-client"))
            continue
        ticket = by_id.get(ticket_id)
        if ticket is None:
            rejected.append(Rejected(ticket_id, "not-this-clients-ticket"))
            continue
        raw_steps = record.get("steps")
        if ticket.get("status") != "resolved":
            skipped.append(Skipped(ticket_id, "not-resolved"))
            continue
        if not isinstance(raw_steps, list) or not [s for s in raw_steps if str(s).strip()]:
            skipped.append(Skipped(ticket_id, "no-recorded-resolution"))
            continue
        title = " ".join(str(record.get("title", "")).split())
        steps = [" ".join(str(s).split()) for s in raw_steps if str(s).strip()]

        rules: set[str] = set()
        for text in (str(ticket.get("subject", "")), str(ticket.get("body", "")), title, *steps, "\n".join(steps)):
            rules |= detect_injection(text).rules
        if rules:
            withheld.append(Withheld(ticket_id, "injection", tuple(sorted(rules))))
            continue

        scrubbed = [_scrub(t, addresses, names) for t in (title, *steps)]
        gate = redact_prompt("\n".join(scrubbed))
        if gate.blocked:
            withheld.append(Withheld(ticket_id, "secret", ("secret",)))
            continue
        clean = gate.text.split("\n")
        if len(clean) != len(scrubbed):  # redaction must never merge or drop a step
            withheld.append(Withheld(ticket_id, "secret", ("redaction-mismatch",)))
            continue
        drafts.append(
            Draft(
                draft_id=f"DRAFT-{ticket_id}",
                client=client,
                title=clean[0],
                tags=_tags(record.get("tags")),
                steps=tuple(clean[1:]),
                sources=(ticket_id,),
                redacted=tuple(gate.redacted),
            )
        )
    drafts.sort(key=lambda d: d.sources[0])
    return DraftSet(
        client,
        tuple(drafts),
        tuple(sorted(withheld, key=lambda w: w.ticket_id)),
        tuple(sorted(skipped, key=lambda s: s.ticket_id)),
        tuple(sorted(rejected, key=lambda r: r.ticket_id)),
    )


def render_draft_markdown(draft: Draft) -> str:
    """The draft as a review page. It says DRAFT first and tells the reader a person must publish it."""
    out = [
        f"# DRAFT: {draft.title}",
        "",
        "**DRAFT. Not published.** A person must review, edit and publish this by hand in the KB tool. "
        "No code wrote it to any knowledge base.",
        "",
        f"Client: {draft.client}. Source: ticket {', '.join(draft.sources)}. Tags: {', '.join(draft.tags) or 'none'}.",
        "",
        "## Steps",
        "",
    ]
    out += [f"{n}. {step}" for n, step in enumerate(draft.steps, start=1)]
    out += [
        "",
        "## Before you publish",
        "",
        "- [ ] Each step is still right today and nothing is missing.",
        "- [ ] Placeholders such as [USER] or [PATIENT_NAME_1] are still placeholders: add no real name or number.",
        "- [ ] No other article on this topic says the opposite (run the stale and conflict check).",
        "",
    ]
    return "\n".join(out)


def write_drafts(draft_set: DraftSet, out_dir: Path = DEFAULT_OUT_DIR) -> list[Path]:
    """Write ``<out>/<client>/<draft_id>.md`` and ``.json`` per draft, plus ``index.md`` and ``index.json``."""
    folder = Path(out_dir) / draft_set.client
    folder.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for draft in draft_set.drafts:
        for suffix, content in ((".md", render_draft_markdown(draft)), (".json", _canonical(draft.to_dict()).decode())):
            path = folder / f"{draft.draft_id}{suffix}"
            path.write_text(content, encoding="utf-8", newline="\n")
            written.append(path)
    body = draft_set.to_dict()
    body["set_sha256"] = draft_set.sha256
    index_json = folder / "index.json"
    index_json.write_bytes(_canonical(body))
    lines = [
        f"# KB drafts: {draft_set.client}",
        "",
        f"{draft_set.note} Every draft below is a DRAFT for a person to publish by hand.",
        "",
        f"Drafts {len(draft_set.drafts)}, withheld {len(draft_set.withheld)}, skipped {len(draft_set.skipped)}, "
        f"rejected {len(draft_set.rejected)}.",
        "",
        "## Drafts",
        "",
        *[f"- `{d.draft_id}` from ticket {d.sources[0]}: {d.title}" for d in draft_set.drafts],
        "",
        "## Withheld (text not used)",
        "",
        *[f"- ticket {w.ticket_id}: {w.reason} ({', '.join(w.rules)})" for w in draft_set.withheld],
        "",
        "## Skipped",
        "",
        *[f"- ticket {s.ticket_id}: {s.reason}" for s in draft_set.skipped],
        "",
        "## Rejected (not this client's)",
        "",
        *[f"- ticket {r.ticket_id}: {r.reason}" for r in draft_set.rejected],
        "",
        f"Set SHA-256: `{draft_set.sha256}`",
        "",
    ]
    index_md = folder / "index.md"
    index_md.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return [*written, index_json, index_md]
