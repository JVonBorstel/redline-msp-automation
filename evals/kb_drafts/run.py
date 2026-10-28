"""B-58 eval: step coverage of KB drafts, outcomes per ticket, stale/conflict detection, and a leak sweep.

Run from the repo root:  uv run --frozen python -m evals.kb_drafts.run   (writes evals/kb_drafts/report.md)

Fixture-based: the tickets, recorded resolutions, planted KB and gold answers are synthetic and written by one author.
No model is called. Step coverage is the share of gold step fragments that appear in the drafts of tickets that should
produce one; because steps are copied from the recorded resolution, a miss means redaction or a rule dropped
something. The leak sweep searches every file the workflow writes for planted canaries, requester names and PHI.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from workflows.kb_drafts import build_drafts, detect_report, write_detect_report, write_drafts
from workflows.kb_drafts.detect import DEFAULT_MAX_AGE_DAYS

HERE = Path(__file__).parent
GOLD = HERE / "gold.json"
REPORT = HERE / "report.md"
REPO = HERE.parents[1]
PLANTED_KB = REPO / "workflows" / "kb_drafts" / "data" / "kb"
REVIEWS = REPO / "workflows" / "kb_drafts" / "data" / "reviews"
AS_OF = "2026-10-27"


def run() -> dict[str, Any]:
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    found_steps = expected_steps = 0
    outcome_errors: list[str] = []
    missed_steps: list[str] = []
    clients: dict[str, Any] = {}
    leaks = 0
    for client, want in gold["drafts"].items():
        drafts = build_drafts(client)
        by_ticket = {d.sources[0]: d for d in drafts.drafts}
        got = {
            "withheld": {w.ticket_id: w.reason for w in drafts.withheld},
            "skipped": {s.ticket_id: s.reason for s in drafts.skipped},
            "rejected": {r.ticket_id: r.reason for r in drafts.rejected},
        }
        for kind in ("withheld", "skipped", "rejected"):
            if got[kind] != want[kind]:
                outcome_errors.append(f"{client}: {kind} {got[kind]} != {want[kind]}")
        if set(by_ticket) != set(want["steps"]):
            outcome_errors.append(f"{client}: drafted {sorted(by_ticket)} != {sorted(want['steps'])}")
        client_expected = client_found = 0
        for ticket, fragments in want["steps"].items():
            text = " ".join(by_ticket[ticket].steps).lower() if ticket in by_ticket else ""
            for fragment in fragments:
                client_expected += 1
                if fragment.lower() in text:
                    client_found += 1
                else:
                    missed_steps.append(f"{client}/{ticket}: {fragment}")
        found_steps += client_found
        expected_steps += client_expected
        with tempfile.TemporaryDirectory() as tmp:
            blob = "\n".join(p.read_text(encoding="utf-8") for p in write_drafts(drafts, Path(tmp))).lower()
        leaks += sum(1 for token in want["forbidden"] if token.lower() in blob)
        clients[client] = {
            "drafts": len(drafts.drafts),
            "withheld": len(drafts.withheld),
            "skipped": len(drafts.skipped),
            "rejected": len(drafts.rejected),
            "steps_expected": client_expected,
            "steps_found": client_found,
        }

    missed: list[str] = []
    spurious: list[str] = []
    detection: dict[str, Any] = {}
    for client, want in gold["detection"].items():
        report = detect_report(client, kb_dir=PLANTED_KB, reviews_dir=REVIEWS, as_of=AS_OF)
        stale = {s.article_id for s in report.stale}
        pairs = {tuple(sorted(c.articles)) for c in report.conflicts}
        want_stale = set(want["stale"])
        want_pairs = {tuple(sorted(p)) for p in want["conflicts"]}
        missed += [f"{client}: stale {a}" for a in sorted(want_stale - stale)]
        missed += [f"{client}: conflict {' / '.join(p)}" for p in sorted(want_pairs - pairs)]
        spurious += [f"{client}: stale {a}" for a in sorted(stale - want_stale)]
        spurious += [f"{client}: conflict {' / '.join(p)}" for p in sorted(pairs - want_pairs)]
        if list(report.flagged_articles) != want["flagged"]:
            spurious.append(f"{client}: flagged {list(report.flagged_articles)} != {want['flagged']}")
        with tempfile.TemporaryDirectory() as tmp:
            blob = "\n".join(p.read_text(encoding="utf-8") for p in write_detect_report(report, Path(tmp))).lower()
        leaks += sum(1 for token in want["forbidden"] if token.lower() in blob)
        detection[client] = {"stale": len(stale), "conflicts": len(pairs), "flagged": len(report.flagged_articles)}

    return {
        "coverage": {
            "steps_expected": expected_steps,
            "steps_found": found_steps,
            "rate": 0.0 if not expected_steps else round(found_steps / expected_steps, 4),
            "missed": missed_steps,
        },
        "outcome_errors": outcome_errors,
        "clients": clients,
        "detection": {
            "per_client": detection,
            "missed": missed,
            "spurious": spurious,
            "max_age_days": DEFAULT_MAX_AGE_DAYS,
        },
        "leaks": leaks,
    }


def render(result: dict[str, Any]) -> str:
    cov = result["coverage"]
    det = result["detection"]
    lines = [
        "# B-58 eval: KB drafts and stale/conflict detection",
        "",
        "Fixture-based. Synthetic tickets, recorded resolutions and a planted KB, gold answers by one author, no model "
        "called, word-overlap retrieval stand-in. It describes these fixtures only.",
        "",
        "## Step coverage",
        "",
        f"Gold step fragments found in drafts: {cov['steps_found']} of {cov['steps_expected']} ({cov['rate']:.0%}).",
        "",
        "| Client | Drafts | Withheld | Skipped | Rejected | Steps found |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for client, row in result["clients"].items():
        lines.append(
            f"| {client} | {row['drafts']} | {row['withheld']} | {row['skipped']} | {row['rejected']} | "
            f"{row['steps_found']} of {row['steps_expected']} |"
        )
    lines += ["", f"Missed steps: {', '.join(cov['missed']) or 'none'}.", ""]
    lines += [
        f"Outcome errors (withheld, skipped, rejected, drafted set): {', '.join(result['outcome_errors']) or 'none'}.",
        "",
    ]
    lines += [
        "## Stale and conflict detection (planted KB)",
        "",
        f"Age limit {det['max_age_days']} days.",
        "",
        "| Client | Stale | Conflicting pairs | Flagged articles |",
        "| --- | --- | --- | --- |",
    ]
    for client, row in det["per_client"].items():
        lines.append(f"| {client} | {row['stale']} | {row['conflicts']} | {row['flagged']} |")
    lines += [
        "",
        f"Missed: {', '.join(det['missed']) or 'none'}. Spurious: {', '.join(det['spurious']) or 'none'}.",
        "",
        "## Leak sweep",
        "",
        f"Planted canaries, other clients' text, requester names and PHI found in any written file: {result['leaks']}.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    result = run()
    REPORT.write_text(render(result), encoding="utf-8", newline="\n")
    ok = (
        result["coverage"]["rate"] == 1.0
        and not result["outcome_errors"]
        and not result["detection"]["missed"]
        and not result["detection"]["spurious"]
        and result["leaks"] == 0
    )
    print(f"coverage {result['coverage']['rate']:.0%}, leaks {result['leaks']}, {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
