"""B-78 routing evals and escalation thresholds.

Acceptance ids B78-1 to B78-3 are defined in specs/B-78.md. Everything is offline: the three tiers are mock keyword
backends (evals/routing/mock_backends.json), no model client is imported and nothing is downloaded. Results are
fixture-based. Run: uv run --frozen pytest tests/py/evals
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evals.routing.backends import Backend, BackendError, Backends, Decision, Fallback, Rule
from evals.routing.run import (
    DEFAULT_PROPOSAL,
    DEFAULT_REPORT,
    MIN_SUPPORT,
    TARGET_ACCURACY,
    Row,
    Thresholds,
    collect_rows,
    derive_thresholds,
    evaluate,
    main,
    render_proposal,
    render_report,
    simulate,
)
from workflows.triage import load_tickets
from workflows.triage.tickets import Category

ROOT = Path(__file__).resolve().parents[3]
CATEGORIES = {
    "security",
    "offboarding",
    "mfa",
    "account-access",
    "email",
    "network",
    "hardware",
    "software",
    "other",
}


def _lf(path: Path) -> bytes:
    """File bytes with Windows line endings normalised, so a CRLF checkout compares equal."""
    return path.read_bytes().replace(b"\r\n", b"\n")


def _d(category: Category, confidence: float) -> Decision:
    return Decision(category=category, confidence=confidence)


def _row(
    i: int,
    gold: Category,
    rules: tuple[Category, float],
    small: tuple[Category, float] = ("other", 0.1),
) -> Row:
    return Row(
        f"T-{i:04d}",
        gold,
        {"rules": _d(*rules), "small": _d(*small), "strong": _d(gold, 1.0)},
    )


# ---------------------------------------------------------------- B78-2: thresholds come from results


def test_b78_2_threshold_is_the_lowest_confidence_that_meets_the_target() -> None:
    rows = [_row(i, "mfa", ("mfa", 0.9)) for i in range(3)] + [_row(10 + i, "email", ("mfa", 0.6)) for i in range(2)]
    assert derive_thresholds(rows, target=0.95, min_support=3)["rules"]["mfa"] == 0.9


def test_b78_2_a_lower_threshold_is_chosen_when_the_data_allows_it() -> None:
    rows = [_row(i, "mfa", ("mfa", 0.6 + 0.1 * (i % 3))) for i in range(6)]
    assert derive_thresholds(rows, target=0.95, min_support=3)["rules"]["mfa"] == 0.6


def test_b78_2_no_threshold_reaching_the_target_means_always_escalate() -> None:
    rows = [_row(i, "email", ("mfa", 0.9)) for i in range(5)]
    assert derive_thresholds(rows, target=0.95, min_support=3)["rules"]["mfa"] is None


def test_b78_2_too_few_decisions_means_always_escalate() -> None:
    rows = [_row(i, "mfa", ("mfa", 0.9)) for i in range(2)]
    assert derive_thresholds(rows, target=0.95, min_support=3)["rules"]["mfa"] is None


def test_b78_2_thresholds_change_when_the_gold_labels_change() -> None:
    good = [_row(i, "mfa", ("mfa", 0.9)) for i in range(4)]
    bad = [_row(i, "email", ("mfa", 0.9)) for i in range(4)]
    assert derive_thresholds(good, target=0.95, min_support=3)["rules"]["mfa"] == 0.9
    assert derive_thresholds(bad, target=0.95, min_support=3)["rules"]["mfa"] is None


def test_b78_2_only_the_cheaper_tiers_get_thresholds() -> None:
    rows = [_row(i, "mfa", ("mfa", 0.9), ("mfa", 0.8)) for i in range(4)]
    assert set(derive_thresholds(rows, target=0.95, min_support=3)) == {"rules", "small"}


def test_b78_2_cascade_accepts_only_at_or_above_threshold_and_strong_is_final() -> None:
    backends = Backends.load()
    rows = [
        _row(1, "mfa", ("mfa", 0.9)),
        _row(2, "mfa", ("mfa", 0.7), ("mfa", 0.8)),
        _row(3, "mfa", ("email", 0.7), ("email", 0.4)),
    ]
    thresholds: Thresholds = {"rules": {"mfa": 0.9, "email": None}, "small": {"mfa": 0.8, "email": 0.9}}
    routed = simulate(rows, thresholds, backends)
    assert [r.final_tier for r in routed] == ["rules", "small", "strong"]
    assert [r.correct for r in routed] == [True, True, True]  # the strong stand-in answers the gold label here
    assert routed[2].cost == sum(backends.tiers[t].relative_cost for t in ("rules", "small", "strong"))


def test_b78_2_a_null_threshold_always_escalates() -> None:
    rows = [_row(1, "mfa", ("mfa", 1.0), ("mfa", 1.0))]
    routed = simulate(rows, {"rules": {"mfa": None}, "small": {"mfa": None}}, Backends.load())
    assert routed[0].final_tier == "strong"


# ---------------------------------------------------------------- B78-1: the eval on the gold tickets


def test_b78_1_every_gold_ticket_is_scored_by_all_three_tiers() -> None:
    result = evaluate()
    tickets = load_tickets()
    assert result.ticket_count == len(tickets) == len(result.rows)
    for row in result.rows:
        assert set(row.decisions) == {"rules", "small", "strong"}
        assert row.gold in CATEGORIES


def test_b78_1_gold_labels_are_the_fixture_labels() -> None:
    gold = {t.id: t.labels.category for t in load_tickets()}
    assert {r.ticket_id: r.gold for r in collect_rows(load_tickets(), [], Backends.load())} == gold


def test_b78_1_per_category_table_covers_every_gold_category_with_rates_in_range() -> None:
    result = evaluate()
    assert {c.category for c in result.categories} == {t.labels.category for t in load_tickets()}
    for c in result.categories:
        assert c.n > 0
        for accuracy in c.accuracy.values():
            assert 0.0 <= accuracy <= 1.0
        assert set(c.accuracy) == {"rules", "small", "strong"}
        assert 0.0 <= c.rules_escalated <= 1.0
        assert 0.0 <= c.small_escalated <= 1.0
        assert 0.0 <= c.cascade_accuracy <= 1.0
    assert sum(c.n for c in result.categories) == result.ticket_count


def test_b78_1_cost_table_compares_cascade_with_always_strong() -> None:
    result = evaluate()
    strong = result.backends.tiers["strong"].relative_cost
    assert result.always_cost["strong"] == strong * result.ticket_count
    assert result.cascade_cost == sum(r.cost for r in result.routed)


def test_b78_1_report_is_labelled_fixture_based_and_reports_no_latency_number() -> None:
    text = render_report(evaluate())
    assert "Fixture-based" in text
    assert "Latency: not measured" in text
    assert "relative cost units" in text


def test_b78_1_run_is_deterministic() -> None:
    a, b = evaluate(), evaluate()
    assert render_report(a) == render_report(b)
    assert render_proposal(a) == render_proposal(b)


def test_b78_1_holdout_check_is_reported_and_uses_other_tickets() -> None:
    result = evaluate()
    assert result.holdout_n > 0
    assert result.holdout_n + result.derive_n == result.ticket_count
    assert "holdout" in render_report(result).lower()


# ---------------------------------------------------------------- B78-2: proposed file, never applied


def test_b78_2_proposal_is_marked_proposed_fixture_based_and_not_applied() -> None:
    p = json.loads(render_proposal(evaluate()))
    assert p["status"] == "proposed"
    assert p["applied"] is False
    assert p["basis"] == "fixture-based"
    assert "never applied automatically" in p["note"]


def test_b78_2_proposal_names_the_eval_run_that_justifies_it() -> None:
    result = evaluate()
    p = json.loads(render_proposal(result))
    run = p["eval_run"]
    assert run["target_accuracy"] == TARGET_ACCURACY
    assert run["min_support"] == MIN_SUPPORT
    assert run["tickets"] == result.ticket_count
    assert run["report"] == "evals/routing/report.md"
    assert run["command"] == "uv run python -m evals.routing"
    assert set(run["inputs_sha256"]) == {"tickets", "corrections", "backends"}
    assert p["escalation_thresholds"] == json.loads(json.dumps(result.thresholds))


def test_b78_2_proposal_input_hash_matches_the_ticket_fixtures() -> None:
    p = json.loads(render_proposal(evaluate()))
    digest = hashlib.sha256()
    for path in sorted((ROOT / "fixtures" / "tickets").glob("*.json")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    assert p["eval_run"]["inputs_sha256"]["tickets"] == digest.hexdigest()


def test_b78_2_committed_report_and_proposal_match_a_fresh_run() -> None:
    result = evaluate()
    assert _lf(DEFAULT_REPORT) == render_report(result).encode()
    assert _lf(DEFAULT_PROPOSAL) == render_proposal(result).encode()


def test_b78_2_running_the_eval_never_touches_the_live_routing_config(tmp_path: Path) -> None:
    live = ROOT / "config" / "routing.json"
    before = live.read_bytes()
    assert main(["--report", str(tmp_path / "r.md"), "--proposal", str(tmp_path / "p.json")]) == 0
    assert live.read_bytes() == before
    assert _lf(tmp_path / "r.md") == _lf(DEFAULT_REPORT)
    assert _lf(tmp_path / "p.json") == _lf(DEFAULT_PROPOSAL)
    assert DEFAULT_PROPOSAL.parent.name == "routing"  # under evals/routing/, not config/


def test_b78_2_cascade_with_derived_thresholds_never_accepts_below_threshold() -> None:
    result = evaluate()
    for r in result.routed:
        if r.final_tier == "strong":
            continue
        threshold = result.thresholds[r.final_tier][r.predicted]
        assert threshold is not None
        assert r.confidence >= threshold


# ---------------------------------------------------------------- B78-3: no local model, no number


def test_b78_3_report_says_skipped_no_local_model_and_gives_no_local_numbers() -> None:
    text = render_report(evaluate())
    local_lines = [ln for ln in text.splitlines() if ln.startswith("| local")]
    assert len(local_lines) == 1
    assert "skipped: no local model" in local_lines[0]
    assert not any(ch.isdigit() for ch in local_lines[0])


# ---------------------------------------------------------------- backends and safety


def test_b78_backend_decides_by_first_matching_rule_else_fallback() -> None:
    b = Backend(
        relative_cost=1,
        fallback=Fallback(category="other", confidence=0.2),
        rules=[
            Rule(keywords=["alpha"], category="mfa", confidence=0.9),
            Rule(keywords=["a"], category="email", confidence=0.5),
        ],
    )
    assert b.decide("ALPHA here") == _d("mfa", 0.9)
    assert b.decide("banana") == _d("email", 0.5)
    assert b.decide("zzz") == _d("other", 0.2)


def test_b78_backend_fixture_with_a_missing_tier_or_bad_json_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "b.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(BackendError):
        Backends.load(bad)
    data = json.loads((ROOT / "evals" / "routing" / "mock_backends.json").read_text(encoding="utf-8"))
    del data["tiers"]["strong"]
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(BackendError):
        Backends.load(bad)
    with pytest.raises(BackendError):
        Backends.load(tmp_path / "absent.json")


def test_b78_the_eval_imports_no_model_client_or_network_library() -> None:
    forbidden = ("requests", "httpx", "urllib", "socket", "ollama", "anthropic", "openai", "core.gateway")
    for name in ("backends.py", "run.py"):
        source = (ROOT / "evals" / "routing" / name).read_text(encoding="utf-8")
        for line in source.splitlines():
            if line.startswith(("import ", "from ")):
                assert not any(f in line for f in forbidden), line
