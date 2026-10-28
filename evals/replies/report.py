"""Reply-draft eval (B-25): citation coverage and cross-client citations on the Phase 2 gold set.

Run from the repo root:  uv run --frozen python -m evals.replies.report   (writes evals/replies/report.md)

The gold set is the 210 synthetic Phase 2 tickets (B-21). Each run uses a throwaway state folder: an audit log, a
copy of the lever registry whose ``kb.search`` scope also lists ``litware-legal`` and an eval-only agent identity
scoped to the three clients (the committed registry and identities are not changed; see docs/changes/B-25.md).
Two numbers are gated, both must be exact: citation coverage 100% (every sentence of every draft cites an article
of the ticket's own client) and zero cross-client citations. Source recall and false drafts are reported, not gated.
Numbers are fixture-based: the KB articles and tickets are synthetic and were written by one author, so they test the
pipeline, not a model and not real tickets.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from core.audit import AuditLog
from core.identity import IdentityStore
from core.levers import DEFAULT_REGISTRY_PATH, LeverRunner, MockTenant, Registry
from core.levers.tenant import DEFAULT_TENANT_DIR
from evals.replies.gold import GoldTicket, load_gold_tickets
from workflows.replies import FLAGGED, NO_SOURCE, check_citations, draft_closure, draft_reply, kb_ids

REPORT = Path(__file__).with_name("report.md")
EVAL_AGENT = "reply-eval-bot"
_CITATION = re.compile(r"\[(KB-[A-Z]{2,4}-[0-9]{3})\]")


@dataclass
class ClientStats:
    tickets: int = 0
    drafted: int = 0
    no_source: int = 0
    flagged: int = 0
    other_no_draft: int = 0
    sentences: int = 0
    cited_sentences: int = 0
    cross_client: int = 0
    labelled_with_source: int = 0
    source_recalled: int = 0
    source_wrong: int = 0
    labelled_none: int = 0
    drafted_without_label: int = 0
    closures_drafted: int = 0
    closures_labelled: int = 0
    problems: list[str] = field(default_factory=list)


def eval_runner(root: Path) -> LeverRunner:
    """A runner over a throwaway audit log, a registry with litware-legal added to kb.search and an eval agent."""
    registry = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    for lever in registry["levers"]:
        if lever["name"] == "kb.search":
            lever["client_scope"] = sorted({*lever["client_scope"], "litware-legal"})
    (root / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
    identities = {
        "version": 1,
        "identities": [
            {
                "id": EVAL_AGENT,
                "display_name": "Reply eval agent (synthetic)",
                "role": "agent",
                "clients": ["contoso-dental", "fabrikam-capital", "litware-legal"],
            }
        ],
    }
    (root / "identities.json").write_text(json.dumps(identities), encoding="utf-8")
    return LeverRunner(
        Registry.load(root / "registry.json"),
        IdentityStore.load(root / "identities.json"),
        MockTenant(DEFAULT_TENANT_DIR),
        AuditLog(root / "audit.jsonl"),
    )


def evaluate(tickets: list[GoldTicket], runner: LeverRunner) -> dict[str, ClientStats]:
    stats: dict[str, ClientStats] = {}
    allowed = {c: kb_ids(runner.tenant, c) for c in {t.client for t in tickets}}
    for gold in tickets:
        s = stats.setdefault(gold.client, ClientStats())
        s.tickets += 1
        ticket = gold.ticket()
        draft = draft_reply(ticket, runner=runner, agent=EVAL_AGENT)
        expected = set(gold.labels.reply_sources)
        if draft.drafted:
            s.drafted += 1
            body = [ln for ln in draft.text.split("\n")[1:] if ln.strip()][1:]
            s.sentences += len(body)
            s.problems.extend(f"{gold.id}: {p}" for p in check_citations(draft.text, allowed[gold.client]))
            s.cited_sentences += sum(1 for ln in body if _CITATION.search(ln))
            s.cross_client += sum(1 for c in _CITATION.findall(draft.text) if c not in allowed[gold.client])
        elif draft.text == NO_SOURCE:
            s.no_source += 1
        elif draft.text == FLAGGED:
            s.flagged += 1
        else:
            s.other_no_draft += 1
        if expected:
            s.labelled_with_source += 1
            s.source_recalled += int(draft.drafted and expected <= set(draft.sources))
            s.source_wrong += int(draft.drafted and not expected & set(draft.sources))
        else:
            s.labelled_none += 1
            s.drafted_without_label += int(draft.drafted and not gold.labels.injection)
        if gold.status == "resolved":
            closure = draft_closure(ticket, runner=runner, agent=EVAL_AGENT)
            if closure.drafted:
                s.closures_drafted += 1
            s.closures_labelled += 1
    return stats


def render(stats: dict[str, ClientStats]) -> str:
    total = ClientStats()
    for s in stats.values():
        for name in vars(total):
            if name != "problems":
                setattr(total, name, getattr(total, name) + getattr(s, name))
        total.problems.extend(s.problems)

    def pct(a: int, b: int) -> str:
        return "n/a" if b == 0 else f"{100 * a / b:.1f}%"

    rows = [
        "| Client | Tickets | Drafted | No source | Flagged | Sentences | Cited | Cross-client |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for client, s in sorted(stats.items()):
        rows.append(
            f"| {client} | {s.tickets} | {s.drafted} | {s.no_source} | {s.flagged} | "
            f"{s.sentences} | {s.cited_sentences} | {s.cross_client} |"
        )
    rows.append(
        f"| **all** | {total.tickets} | {total.drafted} | {total.no_source} | {total.flagged} | "
        f"{total.sentences} | {total.cited_sentences} | {total.cross_client} |"
    )
    gate_ok = total.cited_sentences == total.sentences and total.cross_client == 0 and not total.problems
    return "\n".join(
        [
            "# Reply draft eval (B-25)",
            "",
            "Label: **fixture-based**. 210 synthetic Phase 2 tickets (B-21) and the synthetic KB articles of three",
            "invented clients; one author wrote both, so this checks the pipeline, not a model and not real tickets.",
            "No model is called: draft sentences are quoted from the ticket's own client's KB.",
            "",
            "## Gates (B25-3)",
            "",
            f"- Citation coverage: **{pct(total.cited_sentences, total.sentences)}** "
            f"({total.cited_sentences} of {total.sentences} sentences cite an article of the ticket's own client).",
            f"- Cross-client citations: **{total.cross_client}**.",
            f"- Result: **{'PASS' if gate_ok else 'FAIL'}**.",
            "",
            "## Per client",
            "",
            *rows,
            "",
            "## Reported, not gated",
            "",
            f"- Source recall on tickets labelled with a reply source: {total.source_recalled} of "
            f"{total.labelled_with_source} ({pct(total.source_recalled, total.labelled_with_source)}).",
            f"- Drafts that cite none of the labelled articles: {total.source_wrong} of {total.labelled_with_source} "
            "labelled tickets. Still cited and from the right client, but a person must catch the wrong article.",
            f"- Drafts made for tickets labelled with no source and no injection: {total.drafted_without_label} of "
            f"{total.labelled_none} ({pct(total.drafted_without_label, total.labelled_none)}). A draft here is "
            "grounded in a real article, but a person must still check it answers the ticket.",
            f"- Closure follow-ups drafted for resolved tickets: {total.closures_drafted} of {total.closures_labelled} "
            "(a client without a fast-path contact in `fixtures/notify/contacts.json` gets `no draft`; litware-legal "
            "has none).",
            f"- Other no-draft outcomes: {total.other_no_draft}.",
            "",
            "## Honest limits",
            "",
            "- `MIN_SCORE` (2 keyword hits) was chosen by looking at these same fixtures, so recall is optimistic.",
            "- The KB articles are written for technicians; a quoted sentence is correct but not always in the",
            "  right voice for an end user. A person edits before sending (HO-9).",
            "- Contoso and Fabrikam have 3 and 2 articles, so most of their tickets correctly get `no source`.",
            "",
        ]
    )


def main() -> int:
    tickets = load_gold_tickets()
    with tempfile.TemporaryDirectory() as tmp:
        stats = evaluate(tickets, eval_runner(Path(tmp)))
    text = render(stats)
    REPORT.write_text(text, encoding="utf-8")
    print(text)
    return 0 if "Result: **PASS**" in text else 1


if __name__ == "__main__":
    sys.exit(main())
