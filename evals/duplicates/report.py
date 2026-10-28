"""Duplicate and outage grouping eval (B-23): precision and recall on the gold duplicate groups.

Run from the repo root:  uv run --frozen python -m evals.duplicates.report   (writes evals/duplicates/report.md)

The gold set is the 210 synthetic Phase 2 tickets (B-21), 13 gold duplicate groups. The workflow groups each client's
tickets in history mode (resolved tickets included, because the groups are about what happened) and the answer key
is read here only. Two views are scored:

- duplicate pairs: every pair of tickets that share a gold group is a true pair; the workflow's duplicate groups give
  predicted pairs. Pair precision and recall are reported per client and overall.
- outage groups: a gold group with at least N tickets (N from the workflow config) is a true outage; it is found when
  all its tickets sit in one outage group. An outage group that is not inside one gold group is a false alarm.

Numbers are fixture-based: the topic words in ``workflows/duplicates/config.json`` were written by the same author as
the tickets and their labels, with those tickets in view. They show the pipeline working and where it errs, not the
quality of duplicate detection on real tickets (D-022). Nothing here is gated except that no ticket of another client
is ever grouped with a client's tickets.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

from evals.duplicates.gold import GoldTicket, gold_groups, load_gold_tickets
from workflows.duplicates import DuplicateConfig, group_client, load_config

REPORT = Path(__file__).with_name("report.md")


@dataclass
class ClientStats:
    tickets: int = 0
    flagged: int = 0
    gold_groups: int = 0
    pairs_true: int = 0
    pairs_predicted: int = 0
    pairs_correct: int = 0
    gold_outages: int = 0
    outages_found: int = 0
    outages_raised: int = 0
    outages_false: int = 0
    cross_client: int = 0
    misses: list[str] = field(default_factory=list)
    false_pairs: list[str] = field(default_factory=list)
    false_outages: list[str] = field(default_factory=list)


def _pairs(ids: tuple[str, ...]) -> set[tuple[str, str]]:
    return {(a, b) for a, b in combinations(sorted(ids), 2)}


def evaluate(tickets: list[GoldTicket], config: DuplicateConfig) -> dict[str, ClientStats]:
    plain = [t.ticket() for t in tickets]
    owner = {t.id: t.client for t in tickets}
    stats: dict[str, ClientStats] = {}
    for client in sorted({t.client for t in tickets}):
        mine = [t for t in tickets if t.client == client]
        s = stats.setdefault(client, ClientStats())
        grouping = group_client(client, plain, config, open_only=False)
        s.tickets = len(mine)
        s.flagged = len(grouping.flagged)
        gold = gold_groups(mine)
        s.gold_groups = len(gold)
        true_pairs = {p for ids in gold.values() for p in _pairs(ids)}
        predicted = {p for g in grouping.duplicate_groups for p in _pairs(g.ticket_ids)}
        s.pairs_true, s.pairs_predicted = len(true_pairs), len(predicted)
        s.pairs_correct = len(true_pairs & predicted)
        s.misses = [f"{a}+{b}" for a, b in sorted(true_pairs - predicted)]
        s.false_pairs = [f"{a}+{b}" for a, b in sorted(predicted - true_pairs)]
        for group in (*grouping.duplicate_groups, *grouping.outage_groups):
            s.cross_client += sum(1 for ticket_id in group.ticket_ids if owner[ticket_id] != client)
        gold_sets = [set(ids) for ids in gold.values()]
        big = [set(ids) for ids in gold.values() if len(ids) >= config.outage_min_tickets]
        raised = [set(g.ticket_ids) for g in grouping.outage_groups]
        s.gold_outages, s.outages_raised = len(big), len(raised)
        s.outages_found = sum(1 for truth in big if any(truth <= found for found in raised))
        for group, found in zip(grouping.outage_groups, raised, strict=True):
            if not any(found <= truth for truth in gold_sets):
                s.outages_false += 1
                s.false_outages.append(f"{group.id} ({', '.join(group.ticket_ids)})")
    return stats


def _pct(a: int, b: int) -> str:
    return "n/a" if b == 0 else f"{100 * a / b:.1f}%"


def totals(stats: dict[str, ClientStats]) -> ClientStats:
    total = ClientStats()
    for s in stats.values():
        for name, value in vars(s).items():
            if isinstance(value, int):
                setattr(total, name, getattr(total, name) + value)
            else:
                getattr(total, name).extend(value)
    return total


def render(stats: dict[str, ClientStats], config: DuplicateConfig) -> str:
    total = totals(stats)
    rows = [
        "| Client | Tickets | Gold groups | True pairs | Predicted pairs | Correct pairs "
        "| Pair precision | Pair recall |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for client, s in [*sorted(stats.items()), ("**all**", total)]:
        rows.append(
            f"| {client} | {s.tickets} | {s.gold_groups} | {s.pairs_true} | {s.pairs_predicted} | {s.pairs_correct} | "
            f"{_pct(s.pairs_correct, s.pairs_predicted)} | {_pct(s.pairs_correct, s.pairs_true)} |"
        )
    outage = [
        "| Client | Gold outages | Found | Outage groups raised | False alarms | Outage recall | Outage precision |",
        "|---|---|---|---|---|---|---|",
    ]
    for client, s in [*sorted(stats.items()), ("**all**", total)]:
        outage.append(
            f"| {client} | {s.gold_outages} | {s.outages_found} | {s.outages_raised} | {s.outages_false} | "
            f"{_pct(s.outages_found, s.gold_outages)} | {_pct(s.outages_raised - s.outages_false, s.outages_raised)} |"
        )

    def listing(title: str, items: list[str]) -> list[str]:
        return [f"**{title}:** " + (", ".join(items) if items else "none")]

    lines = [
        "# Duplicate and outage grouping: fixture-based eval (B-23)",
        "",
        "> Fixture-based and synthetic. The 210 tickets, their gold duplicate groups and the topic words in "
        "`workflows/duplicates/config.json` were all written by one author, with the tickets in view. This shows "
        "the pipeline working and where it errs, not duplicate-detection quality on real tickets (D-022). "
        "Regenerate with `uv run --frozen python -m evals.duplicates.report`.",
        "",
        f"Settings (from the workflow config): window {config.window_hours:g} hours, outage at "
        f"{config.outage_min_tickets} or more tickets of one category from at least {config.outage_min_requesters} "
        "people. History mode: resolved tickets are included. Tickets the injection detector flags "
        f"({total.flagged}) are left out of grouping and counted as neither true nor predicted.",
        "",
        "## Duplicate pairs",
        "",
        *rows,
        "",
        *listing("Missed pairs", total.misses),
        "",
        *listing("False pairs", total.false_pairs),
        "",
        "## Outage groups",
        "",
        *outage,
        "",
        *listing("False alarms", total.false_outages),
        "",
        "## Isolation",
        "",
        f"Tickets of another client found inside any group: {total.cross_client} (must be 0).",
        "",
        "## Limits",
        "",
        "- A ticket with no topic word is never grouped, so wording the config does not know is a missed pair.",
        "- Gold groups are defined as same client, same category and within four hours; the workflow uses topic "
        "(duplicates) and category (outages) over the same window, so the two can disagree on borderline tickets.",
        "- The lexicon covers incident-type topics only (printers, VPN, portals and so on). Account, MFA and "
        "offboarding tickets are not grouped on purpose: two people losing a phone on one day is not an outage.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    config = load_config()
    stats = evaluate(load_gold_tickets(), config)
    text = render(stats, config)
    REPORT.write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return 0 if totals(stats).cross_client == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
