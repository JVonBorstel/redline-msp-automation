"""Billing classification and note-quality eval (B-76, B76-3): accuracy against hand-written gold labels.

Run from the repo root:  uv run --frozen python -m evals.billing.report   (writes evals/billing/report.md)

Gold: ``gold.json``, 23 synthetic time entries in two invented clients. Numbers are fixture-based: the fixtures, the
rules and the gold labels have one author, so a perfect score shows the pipeline is consistent with that author's
reading, not that it would classify a real contract. No model is called. Results are by category, by element and
overall; nothing is grouped by technician, and the gold file does not name one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from workflows.billing.report import build_report

GOLD = Path(__file__).with_name("gold.json")
REPORT = Path(__file__).with_name("report.md")
AS_OF = "2026-10-27"


def score(gold_path: Path = GOLD) -> dict[str, Any]:
    gold = json.loads(gold_path.read_text(encoding="utf-8"))["entries"]
    total = cat_ok = clause_ok = missing_ok = vague_ok = 0
    wrong: list[str] = []
    per_cat: dict[str, list[int]] = {}
    for client, labels in gold.items():
        rows = {r["row_id"]: r for r in build_report(client, as_of=AS_OF, by="eval")["rows"]}
        if set(rows) != set(labels):
            raise ValueError(f"gold and fixture entries differ for {client}")
        for eid, want in labels.items():
            got_c = rows[eid]["classification"]
            got_q = rows[eid]["note_quality"]
            total += 1
            ok_cat = got_c["category"] == want["category"]
            cat_ok += ok_cat
            clause_ok += got_c["clause"] == want["clause"]
            missing_ok += sorted(got_q["missing"]) == sorted(want["missing"])
            vague_ok += bool(got_q["vague_terms"]) == want["vague"]
            hit = per_cat.setdefault(want["category"], [0, 0])
            hit[0] += ok_cat
            hit[1] += 1
            if not ok_cat:
                wrong.append(f"{client}/{eid}: expected {want['category']}, got {got_c['category']}")
    return {
        "entries": total,
        "category_correct": cat_ok,
        "clause_correct": clause_ok,
        "missing_set_correct": missing_ok,
        "vague_flag_correct": vague_ok,
        "per_category": {k: {"correct": v[0], "total": v[1]} for k, v in sorted(per_cat.items())},
        "wrong": wrong,
    }


def render(result: dict[str, Any]) -> str:
    n = result["entries"]

    def pct(k: str) -> str:
        return f"{result[k]}/{n} ({100 * result[k] / n:.0f}%)"

    lines = [
        "# B-76 billing eval report (fixture-based)",
        "",
        "> Synthetic data. Gold labels, fixtures and rules share one author: this shows consistency, not accuracy on a",
        "> real contract or real time entries. No model was called. No per-technician figure exists.",
        "",
        f"- Entries: {n}",
        f"- Category correct: {pct('category_correct')}",
        f"- Clause cited correctly: {pct('clause_correct')}",
        f"- Missing-element set exactly right (what/why/outcome/time): {pct('missing_set_correct')}",
        f"- Vague-wording flag right: {pct('vague_flag_correct')}",
        "",
        "| Gold category | Correct | Total |",
        "| --- | ---: | ---: |",
        *[f"| {k} | {v['correct']} | {v['total']} |" for k, v in result["per_category"].items()],
        "",
        "Wrong: " + ("; ".join(result["wrong"]) if result["wrong"] else "none"),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    result = score()
    REPORT.write_text(render(result), encoding="utf-8", newline="\n")
    print(render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
