"""B-95 ROI tracker: every number is fixture-based and labelled so (acceptance B95-2).

The acceptance rate of each row is read from a committed eval report: the row names the report and a line (the anchor)
that must appear in it, and both counts must be numbers in that line. Minutes, runs and effort are assumptions and the
tracker says so in every row. Run: uv run --frozen pytest -p no:cacheprovider tests/py/governance
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from workflows.assurance.roi import RoiRow, check_roi, load_roi, render_roi
from workflows.assurance.rubric import load_rubric, priority

REPO = Path(__file__).resolve().parents[3]
DOC = REPO / "governance" / "ROI_TRACKER.md"
FIXTURES = REPO / "governance" / "roi_fixtures.json"


def _rows() -> list[RoiRow]:
    return load_roi()


def test_b95_2_the_committed_rows_pass_the_check() -> None:
    assert check_roi(_rows(), REPO) == []


def test_b95_2_every_row_is_fixture_based_and_reads_a_committed_report() -> None:
    rows = _rows()
    assert len(rows) >= 6
    for row in rows:
        assert row.basis == "fixture-based"
        assert (REPO / row.report).is_file()
        assert row.anchor in (REPO / row.report).read_text(encoding="utf-8")


def test_b95_2_acceptance_is_the_reported_count_not_a_typed_percentage() -> None:
    by_id = {r.id: r for r in _rows()}
    assert by_id["triage-category"].acceptance == pytest.approx(58 / 60)
    assert by_id["replies-source-recall"].acceptance == pytest.approx(34 / 49)
    assert by_id["alerts-pair-recall"].acceptance == pytest.approx(13 / 14)


def test_b95_2_the_tracker_marks_every_row_and_every_assumption() -> None:
    text = render_roi(_rows(), load_rubric())
    table = [line for line in text.splitlines() if line.startswith("| ") and "---" not in line][1:]
    assert len(table) == len(_rows())
    for line in table:
        assert "fixture-based" in line
    header = next(line for line in text.splitlines() if line.startswith("| Automation"))
    for word in ("(assumed)", "(fixture)"):
        assert word in header
    assert "Not a saving" in text
    assert "$" not in text  # no money figures: nothing here is a price or a measured saving


def test_b95_2_the_committed_tracker_equals_the_generated_one() -> None:
    assert DOC.read_text(encoding="utf-8") == render_roi(_rows(), load_rubric())


def test_b95_2_priority_in_the_table_uses_the_shared_formula() -> None:
    rubric = load_rubric()
    for row in _rows():
        expected = priority(
            hours=row.minutes_per_run * row.runs_per_month / 60,
            acceptance=row.acceptance,
            effort_days=row.effort_days,
            weight=rubric.risk_weights[row.risk_class],
        )
        assert f"{expected:.2f}" in render_roi(_rows(), rubric)


# -- the check catches a spoiled copy ---------------------------------------------------------------------------------
def _spoil(**over: object) -> list[RoiRow]:
    raw = json.loads(FIXTURES.read_text(encoding="utf-8"))
    rows = copy.deepcopy(raw["rows"])
    rows[0].update(over)
    return [RoiRow.model_validate({**r, "basis": "fixture-based"}) for r in rows]


def test_b95_2_check_rejects_an_anchor_that_is_not_in_the_report() -> None:
    problems = check_roi(_spoil(anchor="| category | 59/60 | 98.3% |", numerator=59), REPO)
    assert any("anchor" in p and "triage-category" in p for p in problems)


def test_b95_2_check_rejects_counts_that_the_anchor_does_not_contain() -> None:
    problems = check_roi(_spoil(numerator=57), REPO)
    assert any("57" in p for p in problems)


def test_b95_2_check_rejects_a_missing_report() -> None:
    problems = check_roi(_spoil(report="evals/triage/no-such-report.md"), REPO)
    assert any("no-such-report.md" in p for p in problems)


def test_b95_2_check_rejects_a_duplicate_row_id() -> None:
    rows = _rows()
    assert any("duplicate" in p for p in check_roi([*rows, rows[0]], REPO))


def test_b95_2_the_model_rejects_a_row_not_labelled_fixture_based_or_with_more_hits_than_cases() -> None:
    raw = json.loads(FIXTURES.read_text(encoding="utf-8"))["rows"][0]
    with pytest.raises(ValidationError):
        RoiRow.model_validate({**raw, "basis": "measured"})
    with pytest.raises(ValidationError):
        RoiRow.model_validate({**raw, "basis": "fixture-based", "numerator": 61})
