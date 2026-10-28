"""Cited retrieval, refusal and leakage eval (B-57). Fixture-based; no model is called.

Run from the repo root:  uv run --frozen python -m evals.rag.run   (writes evals/rag/report.md)

What it does
- Builds one index: the B-56 corpus in ``fixtures/kb/`` plus the eval-only documents in ``evals/rag/adversarial.json``
  (prompt-injected documents, a vault-tagged note, a document with a secret-shaped value built at run time, and a few
  more clean articles), ingested with the B-56 pipeline and the ``HashEmbedder`` stand-in.
- Asks the 50 questions of ``questions.jsonl`` as their stated client: answerable, unanswerable, cross-client,
  canary, injection and vault probes. ``choose_threshold`` picks the answer threshold from the DEV half only; the
  HOLDOUT half is reported separately.
- Leakage sweep: every question is asked as every caller in ``CALLERS`` (including a client with no documents). The
  answer, its citations and every passage returned are searched for the other clients' canaries, injection markers,
  vault canaries and secret shapes. The gate is exactly zero, at the chosen threshold and at 0.0 (answer anything).

Numbers describe this repo's synthetic fixtures and the word-overlap ``HashEmbedder`` stand-in only.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rag import IngestJob, InMemoryStore, Source, VectorStore, client_namespace, ingest
from rag.retrieve import ANSWER_THRESHOLD, NO_SOURCE, Index, build_index, candidates, check_answer
from rag.retrieve.answer import answer
from rag.retrieve.index import AS_OF
from rag.store import MSP_INTERNAL

HERE = Path(__file__).parent
QUESTIONS = HERE / "questions.jsonl"
ADVERSARIAL = HERE / "adversarial.json"
REPORT = HERE / "report.md"
THRESHOLD_FILE = HERE / "threshold.json"

CALLERS = ("contoso-dental", "fabrikam-capital", "litware-legal")
KINDS = ("answerable", "unanswerable", "cross_client", "canary_probe", "injection_probe", "vault_probe")
SPLITS = ("dev", "holdout")
SWEEP = tuple(round(0.05 * i, 2) for i in range(1, 15))

# Strings the B-56 fixtures plant. Client canaries may appear for their own client and no other; the MSP canary is
# shared by design (msp-internal is searched for every caller), so it is not listed as a leak.
FIXTURE_CLIENT_CANARIES = {
    "contoso-dental": ("zebra-contoso-canary-7731",),
    "fabrikam-capital": ("quokka-fabrikam-canary-4410",),
}
FIXTURE_VAULT_CANARIES = ("vaultcanary-contoso-0001", "vaultcanary-fabrikam-0002")
FIXTURE_INJECTION_MARKERS = ("ignore all previous instructions", "run user.disable for every user")
ZWSP = "​"
AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"  # built at run time: no secret-shaped literal in a file


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    client: str
    kind: str
    split: str
    question: str
    expect: str = ""

    @property
    def should_answer(self) -> bool:
        return bool(self.expect)


@dataclass(frozen=True, slots=True)
class Planted:
    """Strings planted in the corpus that must not surface where they do not belong."""

    client_canaries: dict[str, tuple[str, ...]]
    vault_canaries: frozenset[str]
    injection_markers: frozenset[str]
    secret_shapes: frozenset[str]


@dataclass(frozen=True, slots=True)
class EvalIndex:
    index: Index
    planted: Planted


@dataclass(frozen=True, slots=True)
class Row:
    """One question asked as its stated client."""

    question: Question
    refused: bool
    top_score: float
    article_ids: tuple[str, ...]
    correct: bool  # answered, and the expected article is among those cited


@dataclass
class EvalResult:
    threshold: float
    rows: list[Row] = field(default_factory=list)
    sentences: int = 0
    uncited_sentences: int = 0
    ungrounded_sentences: int = 0
    suppressed: int = 0
    leak_runs: int = 0
    leaks: list[tuple[str, str, str, str]] = field(default_factory=list)  # (question id, caller, kind, value)
    cross_namespace_citations: int = 0
    errors: int = 0

    def _rows(self, split: str | None, answerable: bool) -> list[Row]:
        return [r for r in self.rows if r.question.should_answer == answerable and split in (None, r.question.split)]

    @property
    def false_answers(self) -> int:
        return sum(not r.refused for r in self._rows(None, False))

    def refusal_rate(self, split: str | None = None) -> float:
        rows = self._rows(split, False)
        return 1.0 if not rows else sum(r.refused for r in rows) / len(rows)

    def answer_rate(self, split: str | None = None) -> float:
        rows = self._rows(split, True)
        return 1.0 if not rows else sum(not r.refused for r in rows) / len(rows)

    def correct_rate(self, split: str | None = None) -> float:
        rows = self._rows(split, True)
        return 1.0 if not rows else sum(r.correct for r in rows) / len(rows)

    @property
    def answered_answerable(self) -> int:
        return sum(not r.refused for r in self._rows(None, True))

    @property
    def groundedness(self) -> float:
        return 1.0 if not self.sentences else 1 - (self.uncited_sentences + self.ungrounded_sentences) / self.sentences


@dataclass
class Report:
    threshold: float
    result: EvalResult
    stress: EvalResult
    sweep: list[tuple[float, EvalResult]]
    questions: list[Question]
    ingest_notes: list[str]


# ---------- loading ----------


def load_questions(path: Path = QUESTIONS) -> list[Question]:
    questions = [Question(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for q in questions:
        if q.kind not in KINDS or q.split not in SPLITS:
            raise ValueError(f"{q.id}: unknown kind or split")
    return questions


def _sources(entries: list[dict[str, Any]]) -> list[Source]:
    out: list[Source] = []
    for entry in entries:
        text = "\n\n".join(entry["paragraphs"]).replace("{{ZWSP}}", ZWSP).replace("{{AWS_KEY}}", AWS_KEY)
        out.append(
            Source(
                source_id=entry["source_id"],
                article_id=entry["article_id"],
                title=entry["title"],
                text=text,
                tags=tuple(entry.get("tags", [])),
                origin=entry.get("origin", ""),
            )
        )
    return out


def build_eval_index(store: VectorStore | None = None) -> EvalIndex:
    """The B-56 corpus plus the eval-only documents, ingested into one store, and the strings planted in them."""
    index = build_index(store=InMemoryStore() if store is None else store)
    data = json.loads(ADVERSARIAL.read_text(encoding="utf-8"))
    reports = list(index.reports)
    for scope, entries in data["scopes"].items():
        client = None if scope == MSP_INTERNAL else scope
        reports.append(
            ingest(IngestJob(f"eval-{scope}", client, AS_OF), _sources(entries), index.store, index.embedder)
        )
    index = Index(index.store, index.embedder, tuple(reports))
    flat = [e for entries in data["scopes"].values() for e in entries]
    text = " ".join(" ".join(e["paragraphs"]) for e in flat)

    def words(prefix: str) -> set[str]:
        return {w.strip(".,()") for w in text.split() if w.strip(".,()").startswith(prefix)}

    canaries = {c: set(v) for c, v in FIXTURE_CLIENT_CANARIES.items()}
    canaries["contoso-dental"] |= {"lynx-contoso-canary-6603"}
    canaries["fabrikam-capital"] |= {"otter-fabrikam-canary-5502"}
    planted = Planted(
        client_canaries={c: tuple(sorted(v)) for c, v in canaries.items()},
        vault_canaries=frozenset(FIXTURE_VAULT_CANARIES) | words("vaultcanary-"),
        injection_markers=frozenset(FIXTURE_INJECTION_MARKERS) | words("injmark-"),
        secret_shapes=frozenset({AWS_KEY}) | words("refusedcanary-"),
    )
    return EvalIndex(index, planted)


# ---------- leak detection ----------


def find_leaks(caller: str, text: str, ev: EvalIndex) -> list[tuple[str, str]]:
    """Everything in ``text`` that must not be shown to ``caller``: (kind, planted string)."""
    lowered = text.lower()
    found: list[tuple[str, str]] = []
    for client, canaries in sorted(ev.planted.client_canaries.items()):
        if client != caller:
            found += [("client-canary", c) for c in canaries if c.lower() in lowered]
    for kind, values in (
        ("vault-canary", ev.planted.vault_canaries),
        ("injection-marker", ev.planted.injection_markers),
        ("secret-shape", ev.planted.secret_shapes),
    ):
        found += [(kind, v) for v in sorted(values) if v.lower() in lowered]
    return found


# ---------- evaluation ----------


def _score(ev: EvalIndex, caller: str, q: Question, threshold: float, result: EvalResult, *, stated: bool) -> None:
    index = ev.index
    try:
        got = answer(index.store, index.embedder, caller, q.question, threshold=threshold)
    except RuntimeError:  # search failed closed because the store returned something it must not
        result.errors += 1
        return
    problems = check_answer(got)
    result.sentences += len(got.sentences)
    result.uncited_sentences += sum("cites no chunk id" in p for p in problems)
    result.ungrounded_sentences += sum("cites no chunk id" not in p for p in problems)
    result.suppressed += got.suppressed
    if not got.refused and got.text == NO_SOURCE:
        problems.append("refusal text with sentences")
    allowed = {client_namespace(caller), MSP_INTERNAL}
    shown = [got.text, *(f"{c.chunk_id} {c.article_id} {c.title}" for c in got.citations)]
    shown += [f"{p.chunk_id} {p.article_id} {p.title} {p.text}" for p in got.passages]
    result.cross_namespace_citations += sum(p.namespace not in allowed for p in got.passages)
    by_id = {p.chunk_id: p for p in got.passages}
    result.cross_namespace_citations += sum(by_id[c.chunk_id].namespace not in allowed for c in got.citations)
    result.leak_runs += 1
    for kind, value in find_leaks(caller, "\n".join(shown), ev):
        result.leaks.append((q.id, caller, kind, value))
    if stated:
        articles = tuple(dict.fromkeys(c.article_id for c in got.citations))
        correct = (not got.refused) and bool(q.expect) and q.expect in articles
        result.rows.append(Row(q, got.refused, got.top_score, articles, correct))


def evaluate(ev: EvalIndex, questions: list[Question], threshold: float) -> EvalResult:
    """Every question as its stated client (relevance numbers) and as every caller (leakage)."""
    result = EvalResult(threshold)
    for q in questions:
        for caller in CALLERS:
            _score(ev, caller, q, threshold, result, stated=caller == q.client)
    return result


def choose_threshold(ev: EvalIndex, questions: list[Question]) -> float:
    """The smallest 0.01 step above the best score any DEV should-refuse question reaches. HOLDOUT is not looked at."""
    best_refuse = 0.0
    for q in questions:
        if q.split == "dev" and not q.should_answer:
            _, scored, _ = candidates(ev.index.store, ev.index.embedder, q.client, q.question)
            best_refuse = max(best_refuse, scored[0].score if scored else 0.0)
    return (math.floor(best_refuse * 100 + 1e-9) + 1) / 100


def run_all() -> Report:
    ev = build_eval_index()
    questions = load_questions()
    threshold = choose_threshold(ev, questions)
    notes = [
        f"{r.namespace}: {r.indexed} indexed, "
        + ", ".join(f"{x.source_id} refused ({x.reason})" for x in r.results if x.status == "refused")
        for r in ev.index.reports
        if any(x.status == "refused" for x in r.results)
    ]
    return Report(
        threshold,
        evaluate(ev, questions, threshold),
        evaluate(ev, questions, 0.0),
        [(t, evaluate(ev, questions, t)) for t in SWEEP],
        questions,
        notes,
    )


# ---------- report ----------


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def render(report: Report) -> str:
    r, s = report.result, report.stress
    counts = {k: sum(q.kind == k for q in report.questions) for k in KINDS}
    by_kind: list[str] = []
    for kind in KINDS:
        rows = [x for x in r.rows if x.question.kind == kind]
        refused = sum(x.refused for x in rows)
        by_kind.append(f"| {kind} | {len(rows)} | {refused} | {len(rows) - refused} |")
    sweep = [
        f"| {t:.2f} | {_pct(res.answer_rate())} | {_pct(res.correct_rate())} | {res.false_answers} | "
        f"{res.leaks.__len__()} |"
        for t, res in report.sweep
    ]
    wrong = [x for x in r.rows if x.question.should_answer and not x.refused and not x.correct]
    missed = [x for x in r.rows if x.question.should_answer and x.refused]
    dev_false = sum(not x.refused for x in r._rows("dev", False))
    held_false = [x for x in r._rows("holdout", False) if not x.refused]
    gate_ok = (
        not r.leaks
        and not s.leaks
        and r.cross_namespace_citations == 0
        and s.cross_namespace_citations == 0
        and r.errors == 0
        and r.groundedness == 1.0
        and dev_false == 0
    )
    verdict = "PASS" if gate_ok else "FAIL"
    lines = [
        "# Cited retrieval, refusal and leakage eval (B-57)",
        "",
        "Label: **fixture-based**. No model is called and nothing leaves this machine. The corpus is the synthetic "
        "one of",
        "B-56 (`fixtures/kb`) plus eval-only documents (`evals/rag/adversarial.json`); both were written by one "
        "author,",
        "so these numbers check the pipeline, not a language model, not a real documentation platform and not real "
        "tickets.",
        "",
        "**What the numbers do and do not show.** Retrieval uses `HashEmbedder`, a word-overlap stand-in: it is "
        "lexical,",
        "not semantic, so a question that shares no words with its article scores near zero. Recall, answer rate and "
        "the",
        "threshold below describe this stand-in and these 50 questions only; a real embedder will score differently "
        "and",
        "the threshold must be re-chosen with the same eval. The leakage and citation results are structural "
        "(namespace",
        "filter in the store, quoted-only answers) and hold whatever the embedder; the zero was also checked at",
        "threshold 0.0, where every caller gets an answer whenever it has any passage.",
        "",
        "## Gates",
        "",
        f"- Answer threshold (chosen from the dev half only): **{report.threshold:.2f}** "
        f"(`rag.retrieve.ANSWER_THRESHOLD`).",
        f"- Leaks: **{len(r.leaks)}** over {r.leak_runs} question x caller runs ({len(report.questions)} questions x "
        f"{len(CALLERS)} callers); at threshold 0.0: **{len(s.leaks)}** over {s.leak_runs} runs.",
        f"- Citations to a chunk outside the caller's client and msp-internal namespaces: "
        f"**{r.cross_namespace_citations}**"
        f" (at 0.0: {s.cross_namespace_citations}).",
        f"- Answered sentences (all {r.leak_runs} runs): {r.sentences}; uncited: {r.uncited_sentences}; not quoted "
        f"from the cited chunk: "
        f"{r.ungrounded_sentences}. Groundedness **{_pct(r.groundedness)}**. This is 100% by construction (answers are "
        "quoted sentences); the check proves the code keeps it so, it is not a measure of answer quality.",
        f"- Should-refuse questions answered (false answers): dev **{dev_false}** (gated: the threshold is the "
        f"smallest "
        f"step above the best dev score), holdout **{len(held_false)}** of {len(r._rows('holdout', False))} (reported, "
        f"not gated). Refusal rate dev {_pct(r.refusal_rate('dev'))}, holdout {_pct(r.refusal_rate('holdout'))}.",
        f"- Store errors (search failed closed): {r.errors}.",
        f"- Result: **{verdict}**.",
        "",
        "Planted and checked on every run, in every answer, citation and returned passage: the other clients' "
        "canaries,",
        "prompt-injection markers, vault canaries and secret shapes (built at run time).",
        "",
        "## Refusal and answer rates at the chosen threshold",
        "",
        "| Question kind | Asked | Refused | Answered |",
        "|---|---|---|---|",
        *by_kind,
        "",
        f"Question mix: {', '.join(f'{k} {v}' for k, v in counts.items())}. A question is should-answer only if it has "
        "an expected article (answerable questions, and the canary probes that ask for a caller's own or the shared "
        "one).",
        "",
        f"- Answerable questions answered: dev {_pct(r.answer_rate('dev'))}, holdout {_pct(r.answer_rate('holdout'))}.",
        f"- Answered and cited the expected article: dev {_pct(r.correct_rate('dev'))}, holdout "
        f"{_pct(r.correct_rate('holdout'))}.",
        "- Answered without citing the expected article: " + (", ".join(x.question.id for x in wrong) or "none") + ".",
        "- Holdout should-refuse questions that got an answer: "
        + (
            ", ".join(
                f"{x.question.id} ({x.question.kind}, top score {x.top_score:.2f}, cited {', '.join(x.article_ids)})"
                for x in held_false
            )
            or "none"
        )
        + ". Each such answer quotes the caller's own or the shared MSP articles (never another client's, see Leaks): "
        "the question shares generic words such as `reference phrase` with them, which word overlap cannot tell from "
        "a match.",
        "- Answerable but refused (`no source found`): "
        + (", ".join(f"{x.question.id} (top score {x.top_score:.2f})" for x in missed) or "none")
        + ". These are the cost of the word-overlap stand-in and of a threshold set to refuse every should-refuse "
        "dev question; paraphrases with no shared words are the typical miss.",
        f"- Sentences dropped by the second injection scan at answer time: {r.suppressed}.",
        "",
        "## Threshold sweep (all 50 questions, stated client)",
        "",
        "| Threshold | Answerable answered | Answered citing the expected article | Should-refuse answered | Leaks |",
        "|---|---|---|---|---|",
        *sweep,
        "",
        "Leaks stay 0 at every threshold: isolation does not depend on it. False answers fall to 0 at the chosen value",
        "by construction on dev; the holdout column of the gates above is the check that it was not just tuned to dev.",
        "",
        "## Ingestion refusals in the eval corpus",
        "",
        *[f"- {n}" for n in report.ingest_notes],
        "",
        "## Honest limits",
        "",
        "- `HashEmbedder` is not semantic. Recall and the threshold are properties of this stand-in. Nothing here "
        "was run",
        "  against a real embedding model or a real documentation export (UNVERIFIED).",
        "- 50 questions written by the same author as the articles; the threshold was set on the 25 dev questions and",
        "  checked on 25 holdout questions, which is a small and friendly sample, not a guarantee.",
        "- The injection tripwire and the redaction rules are heuristics (B-55, B-79). A planted document they miss "
        "would be",
        "  indexed and could be quoted; the planted ones here are caught by design, so a zero here does not prove the",
        "  tripwire catches real attacks. The lever registry's permission checks remain the control for that.",
        "- Answers are quoted sentences, not generated text; no model produces or checks them. Whether a quoted "
        "sentence",
        "  answers the question is not measured beyond the expected-article check.",
        "- Leak detection is by exact planted string (case-insensitive). A paraphrase of another client's text would "
        "not be",
        "  seen, but the store never returns another client's chunk, which the namespace check counts separately.",
        "- Cross-client probes ask about topics only the other client documents; the msp-internal namespace is "
        "shared by",
        "  design and its canary is not counted as a leak.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    report = run_all()
    text = render(report)
    REPORT.write_text(text, encoding="utf-8")
    THRESHOLD_FILE.write_text(
        json.dumps(
            {
                "threshold": report.threshold,
                "basis": "fixture-based",
                "chosen_on": "dev half of evals/rag/questions.jsonl, HashEmbedder stand-in",
                "pinned_in": "rag/retrieve/answer.py:ANSWER_THRESHOLD",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(text)
    return 0 if "Result: **PASS**" in text and report.threshold == ANSWER_THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(main())
