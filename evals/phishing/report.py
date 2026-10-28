"""Phishing triage eval (B-45): verdict accuracy on the fixtures and injection handling. Fixture-based.

Run from the repo root:  uv run --frozen python -m evals.phishing.report   (writes evals/phishing/report.md)

- Verdicts: every reported message in ``fixtures/mailflow/reports`` (both shapes) against ``gold.json``.
- Injection: every ``source: email`` case of ``evals/injection/corpus.jsonl`` is put in a reported message whose
  headers alone would earn a lever suggestion; the run counts which are flagged and how many levers flagged reports got.

The fixtures, the gold verdicts and the rules have one author, so the numbers show the pipeline working, not
phishing-detection quality on real mail (D-022).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from evals.injection.report import load_corpus
from workflows.phishing import VERDICTS, ReportedMessage, load_reports, normalise, suggested_levers, triage

GOLD = Path(__file__).with_name("gold.json")
REPORT = Path(__file__).with_name("report.md")
CORPUS_DOMAINS = ("contosodental.example",)


def load_gold() -> dict[str, dict[str, str]]:
    clients: dict[str, dict[str, str]] = json.loads(GOLD.read_text(encoding="utf-8"))["clients"]
    return clients


def corpus_message(case_id: str, text: str) -> ReportedMessage:
    """A Defender-shaped report with ``text`` as its body and failing authentication (a high verdict on headers)."""
    number = sum(ord(c) for c in case_id) % 10000
    payload = {
        "reportedBy": "sam.patel@contosodental.example",
        "internetMessageId": f"<corpus.{case_id}@northwind-traders.example>",
        "headers": [
            {"name": "From", "value": "Northwind Billing <billing@northwind-traders.example>"},
            {"name": "Subject", "value": "Reported email"},
            {"name": "Authentication-Results", "value": "mx.contosodental.example; spf=fail; dkim=fail; dmarc=fail"},
        ],
        "urls": [],
        "attachments": [],
        "body": text,
    }
    return normalise(f"R-{number:04d}", "defender", payload)


def evaluate() -> dict[str, object]:
    gold = load_gold()
    per_client: dict[str, tuple[int, int]] = {}
    confusion: dict[tuple[str, str], int] = {(g, p): 0 for g in VERDICTS for p in VERDICTS}
    wrong: list[str] = []
    flagged: list[str] = []
    fixture_levers = 0
    disagreements: list[str] = []
    for client in sorted(gold):
        loaded = load_reports(client)
        seen: dict[str, str] = {}
        correct = 0
        for m in loaded.reports:
            t = triage(m, loaded.accepted_domains)
            truth = gold[client][m.report_id]
            confusion[(truth, t.verdict)] += 1
            correct += truth == t.verdict
            if truth != t.verdict:
                wrong.append(f"{client} {m.report_id} ({m.shape}): {t.verdict}, gold {truth}")
            if seen.setdefault(m.report_id, t.verdict) != t.verdict:
                disagreements.append(f"{client} {m.report_id}")
            if t.flagged:
                flagged.append(f"{client} {m.report_id} ({m.shape})")
                fixture_levers += len(suggested_levers(t))
        per_client[client] = (len(loaded.reports), correct)
    corpus: dict[str, list[int]] = {"injection": [0, 0, 0], "benign": [0, 0, 0]}
    for case in load_corpus():
        if case.source != "email":
            continue
        t = triage(corpus_message(case.id, case.text), CORPUS_DOMAINS)
        row = corpus[case.kind]
        row[0] += 1
        row[1] += t.flagged
        row[2] += len(suggested_levers(t)) if t.flagged else 0
    return {
        "per_client": per_client,
        "confusion": confusion,
        "wrong": wrong,
        "disagreements": disagreements,
        "flagged": flagged,
        "fixture_levers": fixture_levers,
        "corpus": corpus,
    }


def _pct(a: int, b: int) -> str:
    return "n/a" if b == 0 else f"{100 * a / b:.1f}%"


def render(result: dict[str, object]) -> str:
    per_client: dict[str, tuple[int, int]] = result["per_client"]  # type: ignore[assignment]
    confusion: dict[tuple[str, str], int] = result["confusion"]  # type: ignore[assignment]
    corpus: dict[str, list[int]] = result["corpus"]  # type: ignore[assignment]
    flagged: list[str] = result["flagged"]  # type: ignore[assignment]
    total = sum(n for n, _ in per_client.values()), sum(c for _, c in per_client.values())
    rows = [f"| {c} | {n} | {k} | {_pct(k, n)} |" for c, (n, k) in sorted(per_client.items())]
    matrix = [f"| {g} | " + " | ".join(str(confusion[(g, p)]) for p in VERDICTS) + " |" for g in VERDICTS]

    def listing(title: str, items: object) -> str:
        return f"**{title}:** " + (", ".join(items) if isinstance(items, list) and items else "none")

    lines = [
        "# Phishing triage: fixture-based eval (B-45)",
        "",
        "> Fixture-based and synthetic. The reported messages, the gold verdicts and the rules were all written by one "
        "author. This shows the pipeline working, not phishing-detection quality on real mail (D-022). Regenerate "
        "with `uv run --frozen python -m evals.phishing.report`.",
        "",
        "## Verdicts (every report, both shapes)",
        "",
        "| Client | Reports | Correct | Accuracy |",
        "|---|---|---|---|",
        *rows,
        f"| **all** | {total[0]} | {total[1]} | {_pct(total[1], total[0])} |",
        "",
        "Rows are gold, columns predicted:",
        "",
        "| Gold \\ Predicted | " + " | ".join(VERDICTS) + " |",
        "|---|---|---|---|",
        *matrix,
        "",
        listing("Wrong verdicts", result["wrong"]),
        "",
        listing("Defender and INKY shapes of one message that disagree", result["disagreements"]),
        "",
        "## Injection (hidden instructions in the message text)",
        "",
        "| Set | Reports | Flagged | Levers suggested on flagged reports |",
        "|---|---|---|---|",
        f"| Corpus emails, kind injection | {corpus['injection'][0]} | {corpus['injection'][1]} | "
        f"{corpus['injection'][2]} |",
        f"| Corpus emails, kind benign | {corpus['benign'][0]} | {corpus['benign'][1]} | {corpus['benign'][2]} |",
        f"| Fixture reports | {total[0]} | {len(flagged)} | {result['fixture_levers']} |",
        "",
        listing("Flagged fixture reports", flagged),
        "",
        "## Limits",
        "",
        "- Rules only, on headers, URLs and attachment names. A phish from a real, well-authenticated account with a "
        "clean link scores likely-clean; the draft is a starting point for a person, not a clearance.",
        "- The weights and thresholds were set with these fixtures in view; there is no held-out set.",
        "- The injection detector is a heuristic tripwire (P1-7); the lever registry is the real control.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    result = evaluate()
    text = render(result)
    REPORT.write_text(text, encoding="utf-8", newline="\n")
    print(text)
    corpus: dict[str, list[int]] = result["corpus"]  # type: ignore[assignment]
    ok = not result["wrong"] and corpus["injection"][1] == corpus["injection"][0] and result["fixture_levers"] == 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
