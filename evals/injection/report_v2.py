"""Injection guard eval v2 (B-79): detection and false-positive rates per channel on corpus-v2.jsonl.

Run from the repo root:  uv run --frozen python -m evals.injection.report_v2 [corpus.jsonl]

The corpus is hand-written, synthetic and small. Every number here is fixture-based: it says what the tripwire does
on these cases, not what it would do against real attackers. The tripwire is not the control (D-019): the lever
registry's permission checks are (D-016), and a missed injection still cannot press a button its caller may not press.
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

if __package__ in (None, ""):  # run as a file path: make the repo root importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pydantic import BaseModel, ConfigDict, ValidationError  # noqa: E402

from core.guard import detect_injection  # noqa: E402
from core.guard.detect import Detection  # noqa: E402

CORPUS_V2 = Path(__file__).with_name("corpus-v2.jsonl")
LABEL = "fixture-based, synthetic corpus"
CHANNELS = ("email", "document", "tool_output")
SPLITS = ("dev", "held_out")
Detector = Callable[[str], Detection]


class CaseV2(BaseModel):
    """One corpus line. ``split`` and ``author_pass`` say which pass wrote it; ``category`` is the technique."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: Literal["injection", "benign"]
    channel: Literal["email", "document", "tool_output"]
    category: str
    split: Literal["dev", "held_out"]
    author_pass: Literal["pass-1-dev", "pass-2-held-out"]
    text: str
    note: str


@dataclass
class Tally:
    """Confusion counts with injection as the positive class."""

    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    @property
    def injections(self) -> int:
        return self.tp + self.fn

    @property
    def benign(self) -> int:
        return self.fp + self.tn

    @property
    def total(self) -> int:
        return self.injections + self.benign

    @property
    def precision(self) -> float | None:
        flagged = self.tp + self.fp
        return self.tp / flagged if flagged else None

    @property
    def recall(self) -> float | None:
        return self.tp / self.injections if self.injections else None

    @property
    def false_positive_rate(self) -> float | None:
        return self.fp / self.benign if self.benign else None

    def add(self, injection: bool, flagged: bool) -> None:
        if injection:
            self.tp, self.fn = self.tp + flagged, self.fn + (not flagged)
        else:
            self.fp, self.tn = self.fp + flagged, self.tn + (not flagged)


@dataclass(frozen=True)
class Error:
    kind: Literal["MISSED", "FALSE+"]
    id: str
    channel: str
    split: str
    category: str
    note: str


@dataclass
class ReportV2:
    overall: Tally = field(default_factory=Tally)
    by_channel: dict[str, Tally] = field(default_factory=dict)
    by_split: dict[str, Tally] = field(default_factory=dict)
    by_channel_split: dict[tuple[str, str], Tally] = field(default_factory=dict)
    by_category: dict[tuple[str, str], Tally] = field(default_factory=dict)  # (kind, category)
    errors: list[Error] = field(default_factory=list)
    rule_hits: Counter[str] = field(default_factory=Counter)


class CorpusError(ValueError):
    """The corpus file is missing or malformed."""


def load_corpus_v2(path: Path = CORPUS_V2) -> list[CaseV2]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        cases = [CaseV2.model_validate_json(line) for line in lines if line.strip()]
    except (OSError, ValidationError) as exc:
        raise CorpusError(f"cannot load corpus {path}: {exc}") from exc
    ids = [c.id for c in cases]
    if len(set(ids)) != len(ids):
        raise CorpusError(f"duplicate case ids in {path}")
    return cases


def evaluate_v2(cases: Sequence[CaseV2], detector: Detector = detect_injection) -> ReportV2:
    report = ReportV2()
    for case in cases:
        detection = detector(case.text)
        injection = case.kind == "injection"
        report.rule_hits.update(detection.rules)
        for table, key in (
            (report.by_channel, case.channel),
            (report.by_split, case.split),
            (report.by_channel_split, (case.channel, case.split)),
            (report.by_category, (case.kind, case.category)),
        ):
            table.setdefault(key, Tally()).add(injection, detection.flagged)  # type: ignore[arg-type]
        report.overall.add(injection, detection.flagged)
        if injection != detection.flagged:
            kind: Literal["MISSED", "FALSE+"] = "MISSED" if injection else "FALSE+"
            report.errors.append(Error(kind, case.id, case.channel, case.split, case.category, case.note))
    return report


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _table(rows: Sequence[tuple[str, Tally]], first: str) -> list[str]:
    head = f"  {first:<22s} {'inj':>4s} {'ben':>4s} {'precision':>10s} {'recall':>8s} {'false-pos':>10s}"
    lines = [head]
    for name, t in rows:
        lines.append(
            f"  {name:<22s} {t.injections:4d} {t.benign:4d} {_pct(t.precision):>10s} {_pct(t.recall):>8s} "
            f"{_pct(t.false_positive_rate):>10s}"
        )
    return lines


def _category_table(report: ReportV2, kind: str) -> list[str]:
    """Per-category counts: injections caught (recall) or benign look-alikes flagged (false-positive rate)."""
    rows = sorted((c, t) for (k, c), t in report.by_category.items() if k == kind)
    first, noun = ("attack category", "caught") if kind == "injection" else ("look-alike category", "flagged")
    lines = [f"  {first:<22s} {'cases':>5s} {noun:>8s} {'rate':>7s}"]
    for name, t in rows:
        n, hit = (t.injections, t.tp) if kind == "injection" else (t.benign, t.fp)
        lines.append(f"  {name:<22s} {n:5d} {hit:8d} {_pct(hit / n if n else None):>7s}")
    return lines


def _channel_rows(report: ReportV2, split: str | None) -> list[tuple[str, Tally]]:
    if split is None:
        return [(c, report.by_channel[c]) for c in CHANNELS if c in report.by_channel]
    return [(c, report.by_channel_split[(c, split)]) for c in CHANNELS if (c, split) in report.by_channel_split]


def render_v2(report: ReportV2, source: str = "corpus-v2.jsonl") -> str:
    o = report.overall
    held, dev = report.by_split.get("held_out", Tally()), report.by_split.get("dev", Tally())
    out = [
        f"Injection guard eval v2 ({LABEL})",
        f"Corpus: {o.total} cases from {source} ({o.injections} injection, {o.benign} benign look-alikes; "
        f"dev {dev.total}, held-out {held.total})",
        "",
        "The tripwire is not the control. It reports instruction-like text; the real control is the lever registry's",
        "permission checks (D-016, D-019). A case it misses still cannot press a button its caller may not press.",
        "",
        f"All cases: precision {_pct(o.precision)}, recall {_pct(o.recall)}, false-positive rate "
        f"{_pct(o.false_positive_rate)}",
        "",
        "By channel, all cases (inj = injections, ben = benign look-alikes; false-pos = benign cases flagged):",
        *_table(_channel_rows(report, None), "channel"),
        "",
        "Dev cases only (written in the first pass, with the rules in view; the rules were tuned beside them):",
        *_table(_channel_rows(report, "dev"), "channel"),
        "",
        "Held-out cases only (second pass, written after the dev cases were run and before any guard change.",
        "  Same author as the dev pass and aware of the rules, so less independent than a different author.",
        "  Guard changes made since were designed from dev gaps; docs/changes/B-79.md gives before and after):",
        *_table(_channel_rows(report, "held_out"), "channel"),
        "",
        "Recall by attack category, all cases (caught = injections flagged):",
        *_category_table(report, "injection"),
        "",
        "False-positive rate by benign look-alike category, all cases (flagged = benign cases wrongly flagged):",
        *_category_table(report, "benign"),
        "",
        "Rule hits across the corpus:",
        *(f"  {rule:22s} {n:3d}" for rule, n in sorted(report.rule_hits.items())),
    ]
    if report.errors:
        out += ["", "Errors (MISSED = injection not flagged, FALSE+ = benign flagged):"]
        out += [f"  {e.kind:<7s} {e.id} ({e.channel}, {e.split}, {e.category}): {e.note}" for e in report.errors]
    out += [
        "",
        f"Labelled: {LABEL}. Not a measure of real-world attack coverage; the cases are few and were written by "
        "the same author who had read the rules.",
    ]
    return "\n".join(out)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    path = Path(args[0]) if args else CORPUS_V2
    try:
        cases = load_corpus_v2(path)
    except CorpusError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(render_v2(evaluate_v2(cases), path.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
