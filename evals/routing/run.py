"""B-78 routing eval: score rules-first, small-model and strong-model decisions on the gold tickets, then derive
escalation thresholds from the results.

Run from the repo root:  uv run python -m evals.routing
Writes ``evals/routing/report.md`` and ``evals/routing/routing.proposed.json``. The proposal is a file for a person
to review: nothing reads it, and ``config/routing.json`` is never touched.

Method (all of it mechanical, none of it opinion):
1. Each tier (``mock_backends.json``) classifies every gold ticket and returns a category and a confidence.
2. For a cheaper tier (rules, small) and each category it predicts, the threshold is the LOWEST confidence at which
   the decisions it accepts (confidence at or above the threshold) are at least ``TARGET_ACCURACY`` right and number
   at least ``MIN_SUPPORT``. If no confidence qualifies the threshold is null: that tier always escalates for that
   category.
3. The cascade (rules, then small, then strong) accepts a tier's answer at or above its threshold and otherwise
   escalates. The strong tier is final.
4. A holdout check derives thresholds from half the tickets (even positions in id order) and scores the cascade on
   the other half, to show how much the in-sample numbers flatter the result.

Fixture-based: synthetic tickets and mock keyword backends written by the same author. The numbers show the method
working end to end; they say nothing about real models or real tickets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from evals.routing.backends import DEFAULT_BACKENDS_PATH, TIERS, Backends, Decision, Tier
from workflows.triage import DEFAULT_CORRECTIONS_PATH, apply_corrections, load_corrections, load_tickets
from workflows.triage.corrections import Correction
from workflows.triage.tickets import DEFAULT_TICKETS_DIR, Category, LabelledTicket

HERE = Path(__file__).resolve().parent
DEFAULT_REPORT = HERE / "report.md"
DEFAULT_PROPOSAL = HERE / "routing.proposed.json"
TARGET_ACCURACY = 0.95
MIN_SUPPORT = 3
CHEAP_TIERS: tuple[Tier, ...] = ("rules", "small")
COMMAND = "uv run python -m evals.routing"

Thresholds = dict[Tier, dict[Category, float | None]]


@dataclass(frozen=True)
class Row:
    """One gold ticket and what each tier decided for it."""

    ticket_id: str
    gold: Category
    decisions: dict[Tier, Decision]


@dataclass(frozen=True)
class Routed:
    """Where the cascade settled a ticket."""

    ticket_id: str
    gold: Category
    final_tier: Tier
    predicted: Category
    confidence: float
    cost: float

    @property
    def correct(self) -> bool:
        return self.predicted == self.gold


@dataclass(frozen=True)
class CategoryStats:
    category: Category
    n: int
    accuracy: dict[Tier, float]
    rules_escalated: float  # share not settled by the rules tier
    small_escalated: float  # share that reached the strong tier
    cascade_accuracy: float


@dataclass(frozen=True)
class EvalResult:
    backends: Backends
    rows: list[Row]
    thresholds: Thresholds
    routed: list[Routed]
    categories: list[CategoryStats]
    always_cost: dict[Tier, float]
    cascade_cost: float
    derive_n: int
    holdout_n: int
    holdout_thresholds: Thresholds
    holdout_routed: list[Routed]
    inputs_sha256: dict[str, str]
    corrections: int
    ticket_count: int

    @property
    def misses(self) -> list[Routed]:
        return [r for r in self.routed if not r.correct]


def collect_rows(tickets: Sequence[LabelledTicket], corrections: Sequence[Correction], backends: Backends) -> list[Row]:
    rows: list[Row] = []
    for t in tickets:
        gold = apply_corrections(t.id, t.labels, corrections).category
        rows.append(Row(t.id, gold, {tier: backends.tiers[tier].decide(t.text) for tier in TIERS}))
    return rows


def derive_thresholds(rows: Sequence[Row], *, target: float, min_support: int) -> Thresholds:
    """Per cheaper tier and predicted category: the lowest confidence whose accepted decisions meet the target."""
    out: Thresholds = {}
    for tier in CHEAP_TIERS:
        by_category: dict[Category, list[tuple[float, bool]]] = {}
        for row in rows:
            d = row.decisions[tier]
            by_category.setdefault(d.category, []).append((d.confidence, d.category == row.gold))
        out[tier] = {}
        for category in sorted(by_category):
            decisions = by_category[category]
            chosen: float | None = None
            for candidate in sorted({c for c, _ in decisions}):
                accepted = [ok for c, ok in decisions if c >= candidate]
                if len(accepted) >= min_support and sum(accepted) / len(accepted) >= target:
                    chosen = candidate
                    break
            out[tier][category] = chosen
    return out


def simulate(rows: Sequence[Row], thresholds: Thresholds, backends: Backends) -> list[Routed]:
    """Run the cascade over the rows: rules, then small, then strong (final)."""
    routed: list[Routed] = []
    for row in rows:
        cost = 0.0
        for tier in TIERS:
            cost += backends.tiers[tier].relative_cost
            d = row.decisions[tier]
            limit = None if tier == "strong" else thresholds.get(tier, {}).get(d.category)
            if tier == "strong" or (limit is not None and d.confidence >= limit):
                routed.append(Routed(row.ticket_id, row.gold, tier, d.category, d.confidence, cost))
                break
    return routed


def _share(count: int, total: int) -> float:
    return count / total if total else 0.0


def _category_stats(rows: Sequence[Row], routed: Sequence[Routed]) -> list[CategoryStats]:
    by_id = {r.ticket_id: r for r in routed}
    stats: list[CategoryStats] = []
    for category in sorted({r.gold for r in rows}):
        mine = [r for r in rows if r.gold == category]
        placed = [by_id[r.ticket_id] for r in mine]
        stats.append(
            CategoryStats(
                category=category,
                n=len(mine),
                accuracy={t: _share(sum(r.decisions[t].category == category for r in mine), len(mine)) for t in TIERS},
                rules_escalated=_share(sum(p.final_tier != "rules" for p in placed), len(placed)),
                small_escalated=_share(sum(p.final_tier == "strong" for p in placed), len(placed)),
                cascade_accuracy=_share(sum(p.correct for p in placed), len(placed)),
            )
        )
    return stats


def _digest(parts: Sequence[tuple[str, bytes]]) -> str:
    h = hashlib.sha256()
    for name, data in parts:
        h.update(name.encode() + b"\0" + data.replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def _input_hashes(tickets_dir: Path, corrections_path: Path, backends_path: Path) -> dict[str, str]:
    tickets = _digest([(p.name, p.read_bytes()) for p in sorted(tickets_dir.glob("*.json"))])
    corrections = (
        _digest([(corrections_path.name, corrections_path.read_bytes())]) if corrections_path.exists() else "absent"
    )
    return {
        "tickets": tickets,
        "corrections": corrections,
        "backends": _digest([(backends_path.name, backends_path.read_bytes())]),
    }


def evaluate(
    tickets_dir: Path = DEFAULT_TICKETS_DIR,
    corrections_path: Path = DEFAULT_CORRECTIONS_PATH,
    backends_path: Path = DEFAULT_BACKENDS_PATH,
) -> EvalResult:
    backends = Backends.load(backends_path)
    corrections = load_corrections(corrections_path)
    rows = collect_rows(load_tickets(tickets_dir), corrections, backends)
    thresholds = derive_thresholds(rows, target=TARGET_ACCURACY, min_support=MIN_SUPPORT)
    routed = simulate(rows, thresholds, backends)
    derive_rows, holdout_rows = rows[0::2], rows[1::2]
    holdout_thresholds = derive_thresholds(derive_rows, target=TARGET_ACCURACY, min_support=MIN_SUPPORT)
    return EvalResult(
        backends=backends,
        rows=rows,
        thresholds=thresholds,
        routed=routed,
        categories=_category_stats(rows, routed),
        always_cost={t: backends.tiers[t].relative_cost * len(rows) for t in TIERS},
        cascade_cost=sum(r.cost for r in routed),
        derive_n=len(derive_rows),
        holdout_n=len(holdout_rows),
        holdout_thresholds=holdout_thresholds,
        holdout_routed=simulate(holdout_rows, holdout_thresholds, backends),
        inputs_sha256=_input_hashes(tickets_dir, corrections_path, backends_path),
        corrections=len(corrections),
        ticket_count=len(rows),
    )


def _pct(value: float) -> str:
    return f"{value:.1%}"


def _num(value: float) -> str:
    return f"{value:g}"


def _tier_accuracy(rows: Sequence[Row], tier: Tier) -> float:
    return _share(sum(r.decisions[tier].category == r.gold for r in rows), len(rows))


def render_report(result: EvalResult) -> str:
    n = result.ticket_count
    cascade_acc = _share(sum(r.correct for r in result.routed), n)
    hold_acc = _share(sum(r.correct for r in result.holdout_routed), result.holdout_n)
    hold_strong = _tier_accuracy(result.rows[1::2], "strong")
    hold_cost = sum(r.cost for r in result.holdout_routed)
    hold_strong_cost = result.backends.tiers["strong"].relative_cost * result.holdout_n
    settled = Counter(r.final_tier for r in result.routed)
    tiers = result.backends.tiers
    lines = [
        "# Routing eval (B-78)",
        "",
        f"> **Fixture-based.** {n} synthetic tickets (Contoso Dental, Fabrikam Capital) scored against their gold "
        "labels by three MOCK tiers: keyword deciders in `evals/routing/mock_backends.json` that stand in for a "
        "rules-first tier, a small model and a strong model. They were written by the same author as the tickets. "
        "These numbers show the method working end to end. They are not a measure of any real model or of real "
        "tickets.",
        "",
        "## Accuracy and cost per tier (task: classify the ticket category)",
        "",
        "| Tier | Accuracy | Cost per call (relative cost units) | Latency |",
        "|---|---|---|---|",
        *(
            f"| {t} | {_pct(_tier_accuracy(result.rows, t))} | {_num(tiers[t].relative_cost)} | not measured (mock) |"
            for t in TIERS
        ),
        "| local model | skipped: no local model | skipped: no local model | skipped: no local model |",
        f"| cascade (derived thresholds) | {_pct(cascade_acc)} | {_num(result.cascade_cost / n)} average | "
        "not measured (mock) |",
        "",
        "Latency: not measured. The mock tiers answer instantly, so a latency number would be meaningless. Relative "
        "cost units are an assumption written in the fixture (rules 0, small 1, strong 20), not money and not "
        "measured. The local-model row says `skipped: no local model` because this eval never calls a local "
        "model; it does not show a number it did not measure.",
        "",
        "## Cascade versus always using the strong tier",
        "",
        f"- Settled by rules: {settled['rules']}, by small: {settled['small']}, by strong: {settled['strong']} "
        f"(of {n}).",
        f"- Total cost {_num(result.cascade_cost)} units for the cascade against {_num(result.always_cost['strong'])} "
        f"for strong on everything. Cascade accuracy {_pct(cascade_acc)} against "
        f"{_pct(_tier_accuracy(result.rows, 'strong'))} for strong alone.",
        "- In-sample: the thresholds were derived from these same tickets, so this is the flattering number. "
        "The cascade can beat the strong tier here only because the mock strong tier is wrong on a few tickets "
        "where a cheaper mock tier happens to be right; that is a property of these hand-written mocks, not a "
        "finding about real models.",
        "",
        "## Per category (by gold category)",
        "",
        "Accuracy columns are each tier's own answers. `Left rules` is the share the rules tier did not settle "
        "(escalated to small or beyond). `Reached strong` is the share neither rules nor small settled. "
        "Cascade accuracy is the final answer after escalation.",
        "",
        "| Category | Tickets | Rules acc | Small acc | Strong acc | Left rules | Reached strong | Cascade acc |",
        "|---|---|---|---|---|---|---|---|",
        *(
            f"| {c.category} | {c.n} | {_pct(c.accuracy['rules'])} | {_pct(c.accuracy['small'])} | "
            f"{_pct(c.accuracy['strong'])} | {_pct(c.rules_escalated)} | {_pct(c.small_escalated)} | "
            f"{_pct(c.cascade_accuracy)} |"
            for c in result.categories
        ),
        "",
        "## Derived escalation thresholds",
        "",
        "Rule: per tier and predicted category, the lowest confidence whose accepted decisions are at least "
        f"{_pct(TARGET_ACCURACY)} correct, with at least {MIN_SUPPORT} of them. `never` means no confidence "
        "qualified: that tier always escalates for that category. Confidence values are declared in the mock "
        "fixture, so the thresholds are fixture-based and are a proposal for review, not applied.",
        "",
        "| Tier | Predicted category | Accept at confidence >= |",
        "|---|---|---|",
        *(
            f"| {tier} | {cat} | {'never' if value is None else _num(value)} |"
            for tier in CHEAP_TIERS
            for cat, value in result.thresholds[tier].items()
        ),
        "",
        "## Holdout check",
        "",
        f"Thresholds derived from {result.derive_n} tickets (even positions in id order) and the cascade scored on "
        f"the other {result.holdout_n} (holdout): accuracy {_pct(hold_acc)} (strong alone on the same tickets "
        f"{_pct(hold_strong)}), cost {_num(hold_cost)} units against {_num(hold_strong_cost)} for strong on "
        "everything. With this few tickets per category the holdout is a rough check, not a confidence interval.",
        "",
        "## Cascade misses",
        "",
    ]
    if result.misses:
        lines += ["| Ticket | Gold | Answered | Settled by | Confidence |", "|---|---|---|---|---|"]
        lines += [
            f"| {m.ticket_id} | {m.gold} | {m.predicted} | {m.final_tier} | {_num(m.confidence)} |"
            for m in result.misses
        ]
    else:
        lines.append("None.")
    lines += [
        "",
        f"{result.corrections} technician correction(s) applied from `evals/triage/corrections.jsonl`.",
        "",
        f"Regenerate: `{COMMAND}`",
        "",
    ]
    return "\n".join(lines)


def render_proposal(result: EvalResult) -> str:
    n = result.ticket_count
    proposal = {
        "status": "proposed",
        "applied": False,
        "basis": "fixture-based",
        "note": (
            "Proposed escalation thresholds for human review, never applied automatically. Derived from a "
            "fixture-based eval on synthetic tickets with MOCK tiers; not evidence about any real model. "
            "Nothing reads this file and config/routing.json is unchanged."
        ),
        "eval_run": {
            "command": COMMAND,
            "report": "evals/routing/report.md",
            "tickets": n,
            "target_accuracy": TARGET_ACCURACY,
            "min_support": MIN_SUPPORT,
            "rule": "per tier and predicted category: lowest confidence whose accepted decisions meet "
            "target_accuracy with at least min_support decisions; null means always escalate",
            "inputs_sha256": result.inputs_sha256,
            "cascade_accuracy_in_sample": round(_share(sum(r.correct for r in result.routed), n), 4),
            "cascade_accuracy_holdout": round(
                _share(sum(r.correct for r in result.holdout_routed), result.holdout_n), 4
            ),
            "cascade_cost_units": result.cascade_cost,
            "always_strong_cost_units": result.always_cost["strong"],
        },
        "escalation_thresholds": result.thresholds,
    }
    return json.dumps(proposal, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.routing", description="Routing eval (fixture-based).")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--proposal", type=Path, default=DEFAULT_PROPOSAL)
    args = parser.parse_args(argv)
    result = evaluate()
    report = render_report(result)
    args.report.write_text(report, encoding="utf-8", newline="\n")
    args.proposal.write_text(render_proposal(result), encoding="utf-8", newline="\n")
    print(report)
    print(f"written: {args.report}\nwritten: {args.proposal}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
