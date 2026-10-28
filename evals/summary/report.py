"""Summary and escalation-package eval (B-22): matching, fact recall, unsupported facts and injection handling.

Run from the repo root:  uv run --frozen python -m evals.summary.report   (writes evals/summary/report.md)

The gold set is the 210 synthetic Phase 2 tickets (B-21). Every package fact is traced to its source field against
data rebuilt from the raw ticket, tenant and note files (``build_psa.build``), not against what the workflow loaded.
Numbers are fixture-based: the tickets, contacts and notes are synthetic and written by one author, so they test the
pipeline, not a model and not real tickets. No model is called; the rule-based summary is what is scored.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from core.levers import DEFAULT_TENANT_DIR, MockTenant
from evals.summary.build_psa import COMPANY_IDS, build, person_name
from evals.summary.gold import GoldTicket, load_gold_tickets
from workflows.summary import (
    SUMMARY_MAX,
    DeviceFacts,
    build_package,
    load_adapters,
    propose,
)
from workflows.summary.intake import PART_SEP

REPORT = Path(__file__).with_name("report.md")
NOTES = Path(__file__).with_name("notes.json")
RECALL_FLOOR = 0.90
_REF = re.compile(r"^(?P<kind>psa:ticket|psa:ticket-note|psa:contact)/(?P<id>[^#]+)#(?P<path>[A-Za-z]+)$")
_TENANT_REF = re.compile(
    r"^tenant:user/(?P<upn>[^#]+)#(?P<path>accountEnabled|authentication\.methods\[\d+\]\.displayName)$"
)
_FIELD = {"body": "description", "subject": "title"}


@dataclass
class Stats:
    tickets: int = 0
    client_correct: int = 0
    wrong_client: int = 0
    no_client: int = 0
    contact_correct: int = 0
    affected_checked: int = 0
    affected_wrong: int = 0
    summaries_untraced: int = 0
    summaries_too_long: int = 0
    injection_expected: int = 0
    injection_caught: int = 0
    false_flags: int = 0
    flagged_free_text: int = 0
    summariser_calls_on_flagged: int = 0
    packages: int = 0
    facts: int = 0
    unsupported: int = 0
    cross_client: int = 0
    gold_facts: int = 0
    gold_found: int = 0
    with_related: int = 0
    with_device: int = 0
    with_requester_steps: int = 0
    note_sentences: int = 0
    note_found: int = 0
    problems: list[str] = field(default_factory=list)


class _Raw:
    """Resolve a fact source against data rebuilt from the raw fixture files (independent of the workflow's load)."""

    def __init__(self, client: str) -> None:
        self.psa = build(client)
        tenant = json.loads((DEFAULT_TENANT_DIR / f"{client}.json").read_text(encoding="utf-8"))
        self.users = {str(u["userPrincipalName"]).lower(): u for u in tenant["users"]}

    def resolve(self, ref: str) -> str | None:
        found = _REF.fullmatch(ref)
        if found:
            kind, ident, path = found["kind"], found["id"], found["path"]
            rows = {
                "psa:ticket": [t for t in self.psa["tickets"] if t["ticketNumber"] == ident],
                "psa:ticket-note": [n for n in self.psa["ticketNotes"] if str(n["id"]) == ident],
                "psa:contact": [c for c in self.psa["contacts"] if str(c["id"]) == ident],
            }[kind]
            return str(rows[0][path]) if rows and path in rows[0] else None
        tenant = _TENANT_REF.fullmatch(ref)
        if tenant:
            user = self.users.get(tenant["upn"].lower())
            if user is None:
                return None
            if tenant["path"] == "accountEnabled":
                return str(user["accountEnabled"])
            index = int(re.search(r"\[(\d+)\]", tenant["path"]).group(1))  # type: ignore[union-attr]
            methods = user["authentication"]["methods"]
            return str(methods[index].get("displayName")) if index < len(methods) else None
        return None


def _check_summary(gold: GoldTicket, text: str, stats: Stats) -> None:
    if len(text) > SUMMARY_MAX:
        stats.summaries_too_long += 1
    if gold.labels.injection:
        return
    ticket = gold.ticket()
    for part in text.split(PART_SEP):
        if part != ticket.subject.strip() and part not in ticket.body:
            stats.summaries_untraced += 1
            stats.problems.append(f"{gold.id}: summary part not in the ticket: {part[:40]!r}")


def _expected_contact(gold: GoldTicket, raw: _Raw) -> str | None:
    user = raw.users.get(gold.requester.lower())
    return None if user is None else person_name(str(user["displayName"]))


def evaluate() -> dict[str, Stats]:
    adapters = load_adapters()
    devices = DeviceFacts(MockTenant(DEFAULT_TENANT_DIR))
    raws = {client: _Raw(client) for client in COMPANY_IDS}
    notes = json.loads(NOTES.read_text(encoding="utf-8"))["notes"]
    note_by_ticket = {n["ticket"]: n for n in notes}
    stats = {client: Stats() for client in COMPANY_IDS}
    calls: list[str] = []

    def recorder(subject: str, body: str) -> str:
        calls.append(subject)
        return subject

    for gold in load_gold_tickets():
        client = gold.client
        s = stats[client]
        s.tickets += 1
        ticket = gold.ticket()
        before = len(calls)
        proposal = propose(ticket, adapters, summariser=recorder)
        match = proposal.match
        s.summariser_calls_on_flagged += (len(calls) - before) if gold.labels.injection else 0
        # -- B22-1: client, contact, affected user ------------------------------------------------------------
        if match.client == client:
            s.client_correct += 1
        elif match.client is None:
            s.no_client += 1
        else:
            s.wrong_client += 1
            s.problems.append(f"{gold.id}: matched {match.client}")
        if match.contact_name == _expected_contact(gold, raws[client]):
            s.contact_correct += 1
        if gold.affected_user and gold.affected_user.lower() != gold.requester.lower():
            s.affected_checked += 1
            known = gold.affected_user.lower() in raws[client].users
            want = "contact" if known else "not-a-contact-of-this-client"
            if match.affected.state != want:
                s.affected_wrong += 1
                s.problems.append(f"{gold.id}: affected user state {match.affected.state}, wanted {want}")
        _check_summary(gold, proposal.summary.text, s)
        if gold.labels.injection:
            s.injection_expected += 1
            s.injection_caught += 1 if proposal.summary.flagged and proposal.summary.text.startswith("Flagged:") else 0
        elif proposal.summary.flagged:
            s.false_flags += 1
        # -- B22-2: the package ------------------------------------------------------------------------------
        if match.client is None:
            continue
        result = build_package(ticket.id, adapters[match.client], devices)
        if result.package is None:
            s.problems.append(f"{gold.id}: no package ({result.reason})")
            continue
        package = result.package
        s.packages += 1
        facts = package.facts()
        s.facts += len(facts)
        raw = raws[match.client]
        for fact in facts:
            resolved = raw.resolve(fact.source)
            if resolved is None or fact.value not in resolved:
                s.unsupported += 1
                s.problems.append(f"{gold.id}: untraced fact {fact.source}")
            if any(other is not raw and other.resolve(fact.source) is not None for other in raws.values()):
                s.cross_client += 1
                s.problems.append(f"{gold.id}: fact resolves in another client's data: {fact.source}")
        s.with_related += 1 if package.related_tickets else 0
        s.with_device += 1 if package.device_facts else 0
        s.with_requester_steps += 1 if any(f.label == "Requester says they tried" for f in package.steps_tried) else 0
        if gold.labels.injection:
            own = (f"psa:ticket/{gold.id}#description", f"psa:ticket/{gold.id}#title")
            s.flagged_free_text += sum(1 for f in facts if f.source in own) + (0 if package.flagged else 1)
        else:
            for item in gold.labels.summary_facts:
                s.gold_facts += 1
                ref = f"psa:ticket/{gold.id}#{_FIELD[item.field]}"
                if any(f.source == ref and item.fact in f.value for f in facts):
                    s.gold_found += 1
                else:
                    s.problems.append(f"{gold.id}: gold fact not in package: {item.fact!r}")
        note = note_by_ticket.get(gold.id)
        if note is not None:
            for sentence in re.split(r"(?<=[.!?])\s+", note["description"]):
                s.note_sentences += 1
                if any(f.value == sentence and f.source.startswith("psa:ticket-note/") for f in package.steps_tried):
                    s.note_found += 1
    return stats


def total(stats: dict[str, Stats]) -> Stats:
    out = Stats()
    for s in stats.values():
        for name, value in vars(s).items():
            if isinstance(value, int):
                setattr(out, name, getattr(out, name) + value)
            else:
                out.problems.extend(value)
    return out


def gates(t: Stats) -> list[tuple[str, bool, str]]:
    recall = t.gold_found / t.gold_facts if t.gold_facts else 0.0
    return [
        (
            "Client proposed correctly for every ticket",
            t.client_correct == t.tickets,
            f"{t.client_correct} of {t.tickets}",
        ),
        ("Wrong-client matches", t.wrong_client == 0, str(t.wrong_client)),
        (
            "Contact proposed correctly for every ticket",
            t.contact_correct == t.tickets,
            f"{t.contact_correct} of {t.tickets}",
        ),
        (
            "Affected user matched inside the client only",
            t.affected_wrong == 0,
            f"{t.affected_checked - t.affected_wrong} of {t.affected_checked}",
        ),
        ("Summaries over 400 characters", t.summaries_too_long == 0, str(t.summaries_too_long)),
        ("Summary parts not found in the ticket", t.summaries_untraced == 0, str(t.summaries_untraced)),
        (
            f"Fact recall at least {RECALL_FLOOR:.0%}",
            recall >= RECALL_FLOOR,
            f"{recall:.1%} ({t.gold_found} of {t.gold_facts})",
        ),
        ("Unsupported facts", t.unsupported == 0, f"{t.unsupported} of {t.facts}"),
        ("Facts that resolve in another client's data", t.cross_client == 0, str(t.cross_client)),
        (
            "Technician-note sentences found under steps tried",
            t.note_found == t.note_sentences,
            f"{t.note_found} of {t.note_sentences}",
        ),
        (
            "Injection tickets summarised as flagged",
            t.injection_caught == t.injection_expected,
            f"{t.injection_caught} of {t.injection_expected}",
        ),
        ("Free text from a flagged ticket in its package", t.flagged_free_text == 0, str(t.flagged_free_text)),
        ("Summariser calls on flagged tickets", t.summariser_calls_on_flagged == 0, str(t.summariser_calls_on_flagged)),
    ]


def render(stats: dict[str, Stats]) -> str:
    t = total(stats)
    rows = gates(t)
    lines = [
        "# Summary and escalation package eval (B-22)",
        "",
        "**Fixture-based.** 210 synthetic tickets across three synthetic clients, hand-written by one author, with "
        "synthetic PSA contacts and 12 synthetic technician notes. No model is called: the rule-based summary and the "
        "fact pack are scored. These numbers test the pipeline; they say nothing about a model or about real tickets.",
        "",
        "## Gates",
        "",
        "| Check | Result | Pass |",
        "|---|---|---|",
        *[f"| {name} | {value} | {'yes' if ok else 'NO'} |" for name, ok, value in rows],
        "",
        "## By client",
        "",
        "| Client | Tickets | Client ok | Contact ok | Facts | Unsupported | Gold found | Flagged | Related | Device |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for client, s in stats.items():
        lines.append(
            f"| {client} | {s.tickets} | {s.client_correct} | {s.contact_correct} | {s.facts} | {s.unsupported} | "
            f"{s.gold_found} of {s.gold_facts} | {s.injection_caught} of {s.injection_expected} | {s.with_related} | "
            f"{s.with_device} |"
        )
    lines += [
        "",
        f"Packages built: {t.packages} of {t.tickets}; average {t.facts / t.packages:.1f} facts each. Clean tickets "
        f"flagged by mistake: {t.false_flags}. Packages with at least one related ticket: {t.with_related}. "
        "Packages with a requester-stated step: "
        f"{t.with_requester_steps}.",
        "",
        "## What these numbers do not show",
        "",
        "- Recall is high partly because the package quotes every sentence of the description; it is not a measure of "
        "how well a model picks the important facts. Precision is not scored.",
        "- Steps tried are mostly the 12 hand-written technician notes; the tickets themselves rarely say what the "
        "requester tried, so most packages say `none recorded` there.",
        "- Related tickets are found by contact and by shared wording; they are not scored against the duplicate "
        "groups (that is B-23).",
        "- Device facts are registered sign-in devices from the tenant. There is no RMM adapter, so laptop health, "
        "patches and backup are not covered.",
        "- The injection tickets were written with the detector's rules in view (B-21), so 15 of 15 is a consistency "
        "check, not a detection rate.",
        "- No model was evaluated, so `summarize.v1` stays `draft` (C-41 gate not met by this report).",
        "",
        "Overall: " + ("all gates pass." if all(ok for _, ok, _ in rows) else "AT LEAST ONE GATE FAILED."),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    stats = evaluate()
    text = render(stats)
    REPORT.write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return 0 if all(ok for _, ok, _ in gates(total(stats))) else 1


if __name__ == "__main__":
    sys.exit(main())
