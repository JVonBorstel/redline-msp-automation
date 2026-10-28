"""Alert grouping eval (B-43): precision and recall against gold groups. Fixture-based, a pipeline check.

Run from the repo root:  uv run --frozen python -m evals.alerts.report   (writes evals/alerts/report.md)

All clients' alerts are put in ONE mixed list and each client is grouped from it, so the run also proves that nothing
of another client enters a group. Two views are scored:

- alert pairs: every pair of alerts in one gold group is a true pair; the workflow's groups give predicted pairs.
  Pair precision and recall are reported per client and overall.
- health group type: a gold ``health`` group (RMM agent plus endpoint sensor health) counts as found when its alerts
  sit in one predicted group of type ``health``; a predicted health group that is not inside a gold health group is
  a false health group.

The answer key (``evals/alerts/gold.json``), the fixtures and the grouping rule were written by one author, so the
numbers show the pipeline working and where it errs, not alert-grouping quality on real feeds (D-022).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

from adapters.alerts import Alert
from evals.alerts.gold import GoldGroup, load_all_alerts, load_gold
from workflows.alerts import AlertsConfig, group_alerts, load_config, pool_for

REPORT = Path(__file__).with_name("report.md")


@dataclass
class ClientStats:
    alerts: int = 0
    groups: int = 0
    gold_groups: int = 0
    pairs_true: int = 0
    pairs_predicted: int = 0
    pairs_correct: int = 0
    gold_health: int = 0
    health_found: int = 0
    health_false: int = 0
    cross_client: int = 0
    misses: list[str] = field(default_factory=list)
    false_pairs: list[str] = field(default_factory=list)


def _pairs(ids: tuple[str, ...]) -> set[tuple[str, str]]:
    return set(combinations(sorted(ids), 2))


def evaluate(
    alerts: list[Alert], gold: dict[str, tuple[GoldGroup, ...]], config: AlertsConfig
) -> dict[str, ClientStats]:
    owner = {a.id: a.client for a in alerts}
    stats: dict[str, ClientStats] = {}
    for client in sorted(gold):
        s = stats.setdefault(client, ClientStats())
        groups = group_alerts(pool_for(client, alerts), config)  # the mixed list; the pool drops other clients
        s.alerts = sum(1 for a in alerts if a.client == client)
        s.groups, s.gold_groups = len(groups), len(gold[client])
        true_pairs = {p for g in gold[client] for p in _pairs(g.alert_ids)}
        predicted = {p for g in groups for p in _pairs(g.alert_ids)}
        s.pairs_true, s.pairs_predicted = len(true_pairs), len(predicted)
        s.pairs_correct = len(true_pairs & predicted)
        s.misses = [f"{a}+{b}" for a, b in sorted(true_pairs - predicted)]
        s.false_pairs = [f"{a}+{b}" for a, b in sorted(predicted - true_pairs)]
        s.cross_client = sum(1 for g in groups for i in g.alert_ids if owner[i] != client)
        gold_health = [set(g.alert_ids) for g in gold[client] if g.group_type == "health"]
        health = [set(g.alert_ids) for g in groups if g.group_type == "health"]
        s.gold_health = len(gold_health)
        s.health_found = sum(1 for truth in gold_health if any(truth <= found for found in health))
        s.health_false = sum(
            1 for found in health if len(found) > 1 and not any(found <= truth for truth in gold_health)
        )
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


def render(stats: dict[str, ClientStats], config: AlertsConfig) -> str:
    total = totals(stats)
    rows = [
        "| Client | Alerts | Groups | Gold groups | True pairs | Predicted pairs | Correct pairs "
        "| Pair precision | Pair recall |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    health = [
        "| Client | Gold health groups | Found as one health group | False health groups |",
        "|---|---|---|---|",
    ]
    for client, s in [*sorted(stats.items()), ("**all**", total)]:
        rows.append(
            f"| {client} | {s.alerts} | {s.groups} | {s.gold_groups} | {s.pairs_true} | {s.pairs_predicted} | "
            f"{s.pairs_correct} | {_pct(s.pairs_correct, s.pairs_predicted)} | {_pct(s.pairs_correct, s.pairs_true)} |"
        )
        health.append(f"| {client} | {s.gold_health} | {s.health_found} | {s.health_false} |")

    def listing(title: str, items: list[str]) -> str:
        return f"**{title}:** " + (", ".join(items) if items else "none")

    lines = [
        "# Alert grouping: fixture-based eval (B-43)",
        "",
        "> Fixture-based and synthetic. The alerts, the gold groups and the grouping rule were all written by one "
        "author, with the alerts in view. This shows the pipeline working and where it errs, not alert-grouping "
        "quality on real feeds (D-022). Regenerate with `uv run --frozen python -m evals.alerts.report`.",
        "",
        f"Settings (from the workflow config): window {config.window_minutes} minutes; groups are keyed by client, "
        "group type (incident or health) and entity. All clients' alerts are mixed in one list before grouping.",
        "",
        "## Alert pairs",
        "",
        *rows,
        "",
        listing("Missed pairs", total.misses),
        "",
        listing("False pairs", total.false_pairs),
        "",
        "## Health group type (RMM agent and endpoint sensor health)",
        "",
        *health,
        "",
        "## Isolation",
        "",
        f"Alerts of another client found inside any group: {total.cross_client} (must be 0).",
        "",
        "## Limits",
        "",
        "- Grouping needs a shared entity id. An alert about a device and one about the person who used it do not "
        "group until an enrichment step links them (B-44); that is the missed pair above.",
        "- One window for every source. Slow-burn activity across hours is not grouped, by design for this item.",
        "- Gold singletons are not scored beyond the pairs: a group that wrongly absorbs one shows as false pairs.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    config = load_config()
    stats = evaluate(load_all_alerts(), load_gold(), config)
    text = render(stats, config)
    REPORT.write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return 0 if totals(stats).cross_client == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
