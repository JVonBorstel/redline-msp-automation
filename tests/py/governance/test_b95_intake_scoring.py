"""B-95 use-case intake and scoring rubric.

Acceptance id B95-1 is defined in specs/B-95.md. The intake shape is a pydantic model with a committed JSON Schema,
the examples are synthetic files in fixtures/governance/intakes/, and the score is a pure function of the intake, the
rubric file, the ROI fixture rows and the never-automate list: same inputs, same score, and every verdict carries the
rules that produced it.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/governance
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from core.levers.registry import NeverAutomate
from workflows.assurance.intake import (
    IntakeError,
    UseCaseIntake,
    load_intake,
    load_intakes,
    rank,
    score,
)
from workflows.assurance.roi import RoiRow, load_roi
from workflows.assurance.rubric import Rubric, load_rubric, monthly_hours, priority

REPO = Path(__file__).resolve().parents[3]
INTAKES = REPO / "fixtures" / "governance" / "intakes"
SCHEMA = REPO / "governance" / "use_case_intake.schema.json"
SYNTHETIC_CLIENTS = {"contoso-dental", "fabrikam-capital", "litware-legal", None}

EXPECTED_VERDICT = {
    "UC-001": "candidate",
    "UC-002": "below-acceptance-bar",
    "UC-003": "candidate",
    "UC-004": "needs-measurement",
    "UC-005": "design-review-required",
    "UC-006": "blocked",
    "UC-007": "blocked",
    "UC-008": "blocked",
    "UC-009": "needs-inventory-mapping",
    "UC-010": "candidate",
}


@pytest.fixture(scope="module")
def rubric() -> Rubric:
    return load_rubric()


@pytest.fixture(scope="module")
def roi() -> dict[str, RoiRow]:
    return {row.id: row for row in load_roi()}


@pytest.fixture(scope="module")
def never() -> NeverAutomate:
    return NeverAutomate.load()


def _base(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "version": 1,
        "data_basis": "synthetic",
        "submitter_role": "Service desk lead role",
        "id": "UC-900",
        "title": "Test idea",
        "client_scope": "msp-internal",
        "client": None,
        "problem": "A test problem.",
        "effect": "read-only",
        "data_classes": ["DC-1"],
        "model_route": "none",
        "proposed_levers": [],
        "inventory_ids": ["W-SD-10"],
        "minutes_per_run": 6,
        "runs_per_month": 600,
        "effort_days": 5,
        "roi_row": None,
    }
    data.update(over)
    return data


def _score(rubric: Rubric, roi: dict[str, RoiRow], never: NeverAutomate, **over: Any):  # noqa: ANN202
    return score(UseCaseIntake.model_validate(_base(**over)), rubric=rubric, roi=roi, never=never)


# -- the intake shape -----------------------------------------------------------------------------------------------
def test_b95_1_every_example_intake_validates_and_is_synthetic() -> None:
    intakes = load_intakes(INTAKES)
    assert [i.id for i in intakes] == sorted(EXPECTED_VERDICT)
    for intake in intakes:
        assert intake.data_basis == "synthetic"
        assert intake.client in SYNTHETIC_CLIENTS


def test_b95_1_the_schema_rejects_unknown_fields_and_bad_values() -> None:
    for over in (
        {"surprise": 1},
        {"id": "UC-1"},
        {"data_basis": "real"},
        {"minutes_per_run": 0},
        {"runs_per_month": 0},
        {"effort_days": -1},
        {"data_classes": []},
        {"data_classes": ["DC-9"]},
        {"effect": "write"},
        {"client_scope": "one-client", "client": None},
        {"client_scope": "msp-internal", "client": "contoso-dental"},
        {"proposed_levers": ["NotALever"]},
        {"inventory_ids": ["x"]},
    ):
        with pytest.raises(ValidationError):
            UseCaseIntake.model_validate(_base(**over))


def test_b95_1_the_committed_json_schema_matches_the_model() -> None:
    committed = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert committed == UseCaseIntake.model_json_schema()


def test_b95_1_a_bad_intake_file_is_named_in_the_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_base(effect="nope")), encoding="utf-8")
    with pytest.raises(IntakeError, match="bad.json"):
        load_intake(bad)
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(IntakeError, match="broken.json"):
        load_intake(broken)


def test_b95_1_example_references_resolve() -> None:
    inventory = {i["id"] for i in json.loads((REPO / "map" / "inventory.json").read_text(encoding="utf-8"))}
    rows = {r.id for r in load_roi()}
    for intake in load_intakes(INTAKES):
        assert set(intake.inventory_ids) <= inventory, intake.id
        assert intake.roi_row is None or intake.roi_row in rows, intake.id


# -- the formula ----------------------------------------------------------------------------------------------------
def test_b95_1_priority_is_hours_times_acceptance_over_effort_times_weight() -> None:
    assert monthly_hours(6, 600) == 60.0
    assert priority(hours=60.0, acceptance=0.9, effort_days=5, weight=2) == 5.4
    assert priority(hours=60.0, acceptance=0.0, effort_days=5, weight=2) == 0.0


def test_b95_1_risk_weights_and_bars_come_from_the_rubric_file(rubric: Rubric) -> None:
    assert rubric.risk_weights == {"R0": 1, "R1": 2, "R2": 4, "R3": 8}
    assert rubric.acceptance_bar == 0.9


@pytest.mark.parametrize(
    ("over", "risk_class"),
    [
        ({}, "R0"),
        ({"effect": "reversible-one-object"}, "R1"),
        ({"effect": "reversible-access-or-many"}, "R2"),
        ({"effect": "irreversible-or-identity-or-tenant-wide"}, "R3"),
        ({"client_scope": "many-clients"}, "R0"),
        ({"effect": "reversible-one-object", "client_scope": "many-clients"}, "R3"),
        ({"effect": "reversible-access-or-many", "client_scope": "many-clients"}, "R3"),
        ({"data_classes": ["DC-6"]}, "R3"),
    ],
)
def test_b95_1_risk_class_is_derived_from_effect_scope_and_secrets(
    rubric: Rubric, roi: dict[str, RoiRow], never: NeverAutomate, over: dict[str, Any], risk_class: str
) -> None:
    scored = _score(rubric, roi, never, **over)
    assert scored.risk_class == risk_class
    assert any(r.startswith("RC-") for r in scored.reasons)


@pytest.mark.parametrize(
    ("classes", "band"),
    [
        (["DC-0"], "low"),
        (["DC-1", "DC-0"], "low"),
        (["DC-3"], "moderate"),
        (["DC-1", "DC-4"], "high"),
        (["DC-5"], "high"),
    ],
)
def test_b95_1_data_sensitivity_is_the_highest_class_named(
    rubric: Rubric, roi: dict[str, RoiRow], never: NeverAutomate, classes: list[str], band: str
) -> None:
    assert _score(rubric, roi, never, data_classes=classes).sensitivity == band


def test_b95_1_value_band_uses_assumed_hours(rubric: Rubric, roi: dict[str, RoiRow], never: NeverAutomate) -> None:
    assert _score(rubric, roi, never, minutes_per_run=60, runs_per_month=20).value_band == "high"
    assert _score(rubric, roi, never, minutes_per_run=60, runs_per_month=5).value_band == "medium"
    assert _score(rubric, roi, never, minutes_per_run=60, runs_per_month=4).value_band == "low"


def test_b95_1_acceptance_comes_from_the_roi_row_not_from_the_submitter(
    rubric: Rubric, roi: dict[str, RoiRow], never: NeverAutomate
) -> None:
    scored = _score(rubric, roi, never, roi_row="triage-category")
    assert scored.acceptance == pytest.approx(58 / 60)
    assert scored.priority == pytest.approx(60 * (58 / 60) / (5 * 1), abs=0.01)
    with pytest.raises(IntakeError, match="no-such-row"):
        _score(rubric, roi, never, roi_row="no-such-row")


# -- verdicts ---------------------------------------------------------------------------------------------------------
def test_b95_1_each_example_gets_its_expected_verdict(
    rubric: Rubric, roi: dict[str, RoiRow], never: NeverAutomate
) -> None:
    got = {s.id: s.verdict for s in (score(i, rubric=rubric, roi=roi, never=never) for i in load_intakes(INTAKES))}
    assert got == EXPECTED_VERDICT


def test_b95_1_the_never_automate_check_reads_lever_names_and_inventory_ids(
    rubric: Rubric, roi: dict[str, RoiRow], never: NeverAutomate
) -> None:
    by_lever = _score(rubric, roi, never, proposed_levers=["laps.get"])
    assert by_lever.blocked and any("never-automate" in r and "W-EP-11" in r for r in by_lever.reasons)
    by_inventory = _score(rubric, roi, never, inventory_ids=["W-IDM-04"])
    assert by_inventory.blocked and by_inventory.verdict == "blocked"
    clear = _score(rubric, roi, never, proposed_levers=["user.disable"], inventory_ids=["W-ONB-08"])
    assert not clear.blocked


def test_b95_1_secrets_and_hosted_regulated_data_are_blocked(
    rubric: Rubric, roi: dict[str, RoiRow], never: NeverAutomate
) -> None:
    secret = _score(rubric, roi, never, data_classes=["DC-6"])
    assert secret.blocked and any(r.startswith("BL-DC6") for r in secret.reasons)
    hosted = _score(rubric, roi, never, data_classes=["DC-5"], model_route="hosted")
    assert hosted.blocked and any(r.startswith("BL-HOSTED") for r in hosted.reasons)
    assert not _score(rubric, roi, never, data_classes=["DC-3"], model_route="hosted").blocked
    assert not _score(rubric, roi, never, data_classes=["DC-5"], model_route="local").blocked


def test_b95_1_an_intake_with_no_lever_and_no_inventory_id_cannot_be_cleared(
    rubric: Rubric, roi: dict[str, RoiRow], never: NeverAutomate
) -> None:
    scored = _score(rubric, roi, never, inventory_ids=[], proposed_levers=[])
    assert scored.verdict == "needs-inventory-mapping"
    assert scored.priority is None


def test_b95_1_unmeasured_ideas_get_no_priority_and_a_below_bar_idea_says_so(
    rubric: Rubric, roi: dict[str, RoiRow], never: NeverAutomate
) -> None:
    unmeasured = _score(rubric, roi, never)
    assert unmeasured.verdict == "needs-measurement" and unmeasured.priority is None and unmeasured.acceptance is None
    below = _score(rubric, roi, never, roi_row="replies-source-recall")
    assert below.verdict == "below-acceptance-bar" and below.priority is not None


def test_b95_1_r3_needs_design_review_before_anything_else(
    rubric: Rubric, roi: dict[str, RoiRow], never: NeverAutomate
) -> None:
    scored = _score(rubric, roi, never, effect="irreversible-or-identity-or-tenant-wide", roi_row="triage-category")
    assert scored.verdict == "design-review-required"
    assert any(r.startswith("VD-R3") for r in scored.reasons)


# -- determinism and explanation --------------------------------------------------------------------------------------
def test_b95_1_scores_are_deterministic_and_ranking_ignores_input_order(
    rubric: Rubric, roi: dict[str, RoiRow], never: NeverAutomate
) -> None:
    intakes = load_intakes(INTAKES)
    first = [score(i, rubric=rubric, roi=roi, never=never) for i in intakes]
    second = [score(i, rubric=rubric, roi=roi, never=never) for i in reversed(intakes)]
    assert rank(first) == rank(second)
    ranked = rank(first)
    assert [s.id for s in ranked] == ["UC-001", "UC-010", "UC-003", "UC-002"]
    assert all(not s.blocked and s.priority is not None for s in ranked)
    assert [s.priority for s in ranked] == sorted((s.priority for s in ranked), reverse=True)  # type: ignore[type-var]


def test_b95_1_blocked_ideas_are_never_ranked(rubric: Rubric, roi: dict[str, RoiRow], never: NeverAutomate) -> None:
    blocked = _score(rubric, roi, never, proposed_levers=["laps.get"], roi_row="triage-category")
    assert blocked.priority is None
    assert rank([blocked]) == []


def test_b95_1_every_verdict_lists_the_rules_that_produced_it(
    rubric: Rubric, roi: dict[str, RoiRow], never: NeverAutomate
) -> None:
    for intake in load_intakes(INTAKES):
        scored = score(intake, rubric=rubric, roi=roi, never=never)
        assert scored.reasons, intake.id
        assert any(r.startswith(("VD-", "BL-")) for r in scored.reasons), intake.id
        assert any(r.startswith("RC-") for r in scored.reasons), intake.id
        for reason in scored.reasons:
            assert reason.split(":")[0].replace("-", "").isalnum() and ": " in reason, reason
