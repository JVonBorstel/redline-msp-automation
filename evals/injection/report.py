"""Injection detector eval (P1-7): precision, recall and confusion counts on the synthetic corpus.

Run from the repo root:  uv run python -m evals.injection.report   (or: uv run python evals/injection/report.py)
Numbers are fixture-based: a hand-written synthetic corpus, not real tickets or real attacks seen in the wild.
"""

import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

if __package__ in (None, ""):  # run as a file path: make the repo root importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pydantic import BaseModel, ConfigDict  # noqa: E402

from core.guard import detect_injection  # noqa: E402
from core.guard.detect import Detection  # noqa: E402

CORPUS = Path(__file__).with_name("corpus.jsonl")
LABEL = "fixture-based, synthetic corpus"


class Case(BaseModel):
    """One corpus line."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: Literal["injection", "benign"]
    source: Literal["ticket", "email", "document", "tool_output"]
    text: str
    note: str


@dataclass
class Score:
    """Confusion counts with injection as the positive class, plus the cases the detector got wrong."""

    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0
    misses: list[str] = field(default_factory=list)
    rule_hits: Counter[str] = field(default_factory=Counter)

    @property
    def precision(self) -> float | None:
        flagged = self.tp + self.fp
        return self.tp / flagged if flagged else None

    @property
    def recall(self) -> float | None:
        positives = self.tp + self.fn
        return self.tp / positives if positives else None


def load_corpus(path: Path = CORPUS) -> list[Case]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [Case.model_validate_json(line) for line in lines if line.strip()]


def evaluate(cases: list[Case]) -> tuple[Score, dict[str, Detection]]:
    score = Score()
    detections: dict[str, Detection] = {}
    for case in cases:
        detection = detections[case.id] = detect_injection(case.text)
        score.rule_hits.update(detection.rules)
        injection = case.kind == "injection"
        if injection and detection.flagged:
            score.tp += 1
        elif injection:
            score.fn += 1
            score.misses.append(f"MISSED   {case.id} ({case.source}): {case.note}")
        elif detection.flagged:
            score.fp += 1
            reasons = "; ".join(str(r) for r in detection.reasons)
            score.misses.append(f"FALSE+   {case.id} ({case.source}): {reasons}")
        else:
            score.tn += 1
    return score, detections


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def render(score: Score, cases: list[Case]) -> str:
    kinds = Counter(c.kind for c in cases)
    out = [
        f"Injection detector eval ({LABEL})",
        f"Corpus: {len(cases)} cases ({kinds['injection']} injection, {kinds['benign']} benign)",
        "",
        f"Precision: {_pct(score.precision)}",
        f"Recall:    {_pct(score.recall)}",
        "",
        "Confusion (positive = injection):",
        f"  true positives  {score.tp:3d}   false negatives {score.fn:3d}",
        f"  false positives {score.fp:3d}   true negatives  {score.tn:3d}",
        "",
        "Rule hits across the corpus:",
        *(f"  {rule:22s} {n:3d}" for rule, n in sorted(score.rule_hits.items())),
    ]
    if score.misses:
        out += ["", "Errors:", *(f"  {m}" for m in score.misses)]
    out += ["", f"Labelled: {LABEL}. Not a measure of real-world attack coverage."]
    return "\n".join(out)


def main() -> int:
    cases = load_corpus()
    score, _ = evaluate(cases)
    print(render(score, cases))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
