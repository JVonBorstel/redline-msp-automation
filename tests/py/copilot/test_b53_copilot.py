"""B-53 Copilot readiness. Acceptance ids B53-1 to B53-3 are defined in specs/B-53.md.

Offline and deterministic: dates are pinned with as_of, nothing touches the network, committed fixtures are never
modified (tests that change a fixture work on a copy under tmp_path).
Run: uv run --frozen pytest -p no:cacheprovider tests/py/copilot
"""

from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

import workflows.copilot_readiness.copilot_readiness as module
from workflows.copilot_readiness import (
    DEFAULT_FIXTURE_DIR,
    FORMULA,
    WEIGHTS,
    ReadinessError,
    build_report,
    render_markdown,
)
from workflows.copilot_readiness.__main__ import main

AS_OF = "2026-10-22"
KINDS = ("everyone-link", "external-share", "unlabelled-sensitive-site")


def _fixture(client: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((DEFAULT_FIXTURE_DIR / f"{client}.json").read_text(encoding="utf-8"))
    return data


@pytest.fixture()
def copies(tmp_path: Path) -> Path:
    target = tmp_path / "sharepoint"
    shutil.copytree(DEFAULT_FIXTURE_DIR, target)
    return target


def _write(directory: Path, client: str, data: Any) -> None:
    (directory / f"{client}.json").write_text(json.dumps(data), encoding="utf-8")


# ------------------------------------------------------------------------------------------------ B53-1


def test_b53_1_each_seeded_problem_yields_its_finding() -> None:
    report = build_report("contoso-dental", as_of=AS_OF)
    by_kind = {f.kind: f for f in report.findings}
    assert sorted(by_kind) == sorted(KINDS) and len(report.findings) == 3
    assert by_kind["everyone-link"].site == "Patient Records" and by_kind["everyone-link"].points == 15
    assert (
        by_kind["external-share"].site == "Front Desk OneDrive"
        and "partner-lab.example" in by_kind["external-share"].detail
    )
    assert by_kind["unlabelled-sensitive-site"].site == "Patient Records"
    assert by_kind["unlabelled-sensitive-site"].points == 20
    assert report.score == 55


def test_b53_1_organization_and_internal_sharing_and_labelled_sites_are_not_flagged() -> None:
    sites = {f.site for f in build_report("contoso-dental").findings}
    assert "Billing" not in sites and "Marketing" not in sites  # labelled / org link only / general and unshared
    assert not [f for f in build_report("contoso-dental").findings if "contosodental.example" in f.detail]


def test_b53_1_the_clean_twin_scores_100_with_no_findings() -> None:
    report = build_report("fabrikam-capital", as_of=AS_OF)
    assert report.findings == () and report.recommendations == () and report.score == 100


def test_b53_1_every_point_is_traced_to_a_finding() -> None:
    for client in ("contoso-dental", "fabrikam-capital"):
        report = build_report(client, as_of=AS_OF)
        deducted = 100 - report.score
        assert deducted == sum(f.points for f in report.findings)
        ids = [f.id for f in report.findings]
        assert len(ids) == len(set(ids))
        for row in report.to_dict()["findings"]:
            assert row["points"] == WEIGHTS[row["kind"]] > 0 and row["site"] and row["detail"] and row["id"]
        assert sum(report.points_by_kind.values()) == deducted


def test_b53_1_score_never_goes_below_zero(copies: Path) -> None:
    data = _fixture("contoso-dental")
    site = data["sites"][0]
    site["links"] = [{"id": f"L{i}", "scope": "anyone", "target": "x"} for i in range(10)]
    _write(copies, "contoso-dental", data)
    report = build_report("contoso-dental", fixture_dir=copies)
    assert sum(f.points for f in report.findings) > 100
    assert report.score == 0


def test_b53_1_one_client_never_sees_the_other() -> None:
    contoso = build_report("contoso-dental", as_of=AS_OF).to_dict()
    fabrikam = build_report("fabrikam-capital", as_of=AS_OF).to_dict()
    assert {f["client"] for f in contoso["findings"]} == {"contoso-dental"}
    assert "Client Portfolios" not in json.dumps(contoso) and "Patient Records" not in json.dumps(fabrikam)
    assert "fabrikam" not in json.dumps(contoso).lower()


def test_b53_1_a_file_whose_client_differs_from_its_name_is_refused(copies: Path) -> None:
    data = _fixture("fabrikam-capital")
    _write(copies, "contoso-dental", data)  # fabrikam's data under contoso's name
    with pytest.raises(ReadinessError, match="'client' must equal"):
        build_report("contoso-dental", fixture_dir=copies)


def test_b53_1_a_field_that_could_hold_a_secret_is_refused(copies: Path) -> None:
    data = _fixture("contoso-dental")
    risky_field = "pass" + "word"  # built at runtime so no literal credential-named assignment sits in the source
    data["sites"][0]["links"][0][risky_field] = "x"
    _write(copies, "contoso-dental", data)
    with pytest.raises(ReadinessError, match="could hold a secret"):
        build_report("contoso-dental", fixture_dir=copies)


def test_b53_1_an_empty_site_list_scores_100_and_says_so(copies: Path) -> None:
    data = _fixture("contoso-dental")
    data["sites"] = []
    _write(copies, "contoso-dental", data)
    report = build_report("contoso-dental", fixture_dir=copies)
    assert report.score == 100 and report.findings == () and report.recommendations == ()
    assert report.totals == {"sites": 0, "links": 0, "shares": 0}
    assert "no sites in fixture" in report.to_dict()["notes"]
    assert "no sites in fixture" in render_markdown(report)


@pytest.mark.parametrize("client", ["", "Contoso Dental", "../contoso-dental", "-x", None, 5])
def test_b53_1_a_bad_client_id_is_refused(client: Any) -> None:
    with pytest.raises(ReadinessError, match="slug"):
        build_report(client)


def test_b53_1_an_unknown_client_is_refused() -> None:
    with pytest.raises(ReadinessError, match="no fixture for client"):
        build_report("no-such-client")


def test_b53_1_a_malformed_file_is_refused(copies: Path) -> None:
    (copies / "contoso-dental.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ReadinessError, match="cannot read"):
        build_report("contoso-dental", fixture_dir=copies)


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda d: d["sites"][0].update(kind="mystery"), "'kind' must be one of"),
        (lambda d: d["sites"][0].update(sensitivity="secret-ish"), "'sensitivity' must be one of"),
        (lambda d: d["sites"][0]["links"][0].update(scope="world"), "'scope' must be one of"),
        (lambda d: d["sites"][1]["shares"][0].update(recipientType="alien"), "'recipientType' must be one of"),
        (lambda d: d["sites"][0].update(id=""), "'id' must be a non-empty string"),
        (lambda d: d["sites"][1].update(id=d["sites"][0]["id"]), "duplicate site id"),
        (lambda d: d["sites"][0].update(links="all"), "must be a list of objects"),
        (lambda d: d.update(tenant=[]), "'tenant' must be an object"),
        (lambda d: d["tenant"]["labels"][0].update(covers=["bogus"]), "'covers' must list"),
        (lambda d: d.update(as_of="yesterday"), "not an ISO date"),
    ],
)
def test_b53_1_a_malformed_field_is_refused(copies: Path, edit: Any, message: str) -> None:
    data = _fixture("contoso-dental")
    edit(data)
    _write(copies, "contoso-dental", data)
    with pytest.raises(ReadinessError, match=message):
        build_report("contoso-dental", fixture_dir=copies)


def test_b53_1_dates_come_from_as_of_not_the_clock() -> None:
    assert build_report("contoso-dental").as_of == AS_OF  # default: the fixture's pinned date
    assert build_report("contoso-dental", as_of="2027-01-02").as_of == "2027-01-02"


def test_b53_1_a_missing_label_on_a_non_sensitive_site_is_not_a_finding() -> None:
    report = build_report("fabrikam-capital")
    assert [s["sensitivity"] for s in _fixture("fabrikam-capital")["sites"]].count("general") == 1
    assert report.findings == ()


# ------------------------------------------------------------------------------------------------ B53-2


def test_b53_2_label_and_dlp_gaps_are_recommendations_only() -> None:
    recs = build_report("contoso-dental", as_of=AS_OF).to_dict()["recommendations"]
    assert [(r["kind"], r["category"]) for r in recs] == [("label-gap", "health"), ("dlp-gap", "health")]
    assert all(r["action"] == "recommendation-only" and r["points"] == 0 for r in recs)
    findings = build_report("contoso-dental").to_dict()["findings"]
    assert not [f for f in findings if f["kind"] in ("label-gap", "dlp-gap")]


def test_b53_2_a_recommendation_costs_points_only_where_the_weight_table_says_so() -> None:
    assert WEIGHTS["label-gap"] == 0 and WEIGHTS["dlp-gap"] == 0
    assert all(WEIGHTS[k] > 0 for k in KINDS)
    # Closing the gaps changes the recommendations, not the score.
    report = build_report("contoso-dental")
    assert report.score == 100 - sum(WEIGHTS[f.kind] for f in report.findings)


def test_b53_2_closing_a_gap_removes_its_recommendation(copies: Path) -> None:
    data = _fixture("contoso-dental")
    data["tenant"]["labels"].append({"name": "Patient", "covers": ["health"]})
    _write(copies, "contoso-dental", data)
    kinds = [r.kind for r in build_report("contoso-dental", fixture_dir=copies).recommendations]
    assert kinds == ["dlp-gap"]


def test_b53_2_no_lever_or_policy_change_is_proposed(capsys: pytest.CaptureFixture[str]) -> None:
    body = json.dumps(build_report("contoso-dental").to_dict())
    assert main(["contoso-dental", "--markdown"]) == 0
    text = (body + capsys.readouterr().out).lower()
    for word in ("lever", "apply_policy", "set_policy", "remediate", "execute", "dry-run", "dry_run"):
        assert word not in text, word

    def keys(node: object) -> set[str]:
        if isinstance(node, dict):
            return {k.lower() for k in node} | {k2 for v in node.values() for k2 in keys(v)}
        if isinstance(node, list):
            return {k for v in node for k in keys(v)}
        return set()

    assert not [k for k in keys(json.loads(body)) if any(w in k for w in ("lever", "policy", "change", "apply"))]


def test_b53_2_the_module_imports_no_lever_runner_and_has_no_write_path() -> None:
    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        n.module if isinstance(n, ast.ImportFrom) else a.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in (n.names if isinstance(n, ast.Import) else [None])
    }
    assert not [m for m in imported if m and m.startswith(("core", "socket", "urllib", "subprocess"))]
    assert not [m for m in imported if m and "requests" in m]
    assert "write_text" not in source and "open(" not in source  # reads only
    assert "nothing was changed" in render_markdown(build_report("contoso-dental"))


# ------------------------------------------------------------------------------------------------ B53-3


def test_b53_3_the_formula_and_weights_are_printed_with_the_report(capsys: pytest.CaptureFixture[str]) -> None:
    out = build_report("contoso-dental").to_dict()
    assert out["formula"] == FORMULA and out["weights"] == WEIGHTS
    text = render_markdown(build_report("contoso-dental"))
    assert FORMULA in text
    for kind in KINDS:
        assert f"| {kind} | " in text and str(WEIGHTS[kind]) in text
    assert main(["contoso-dental"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["formula"] == FORMULA and printed["weights"] == WEIGHTS


def test_b53_3_counts_reconcile_to_the_fixture() -> None:
    for client in ("contoso-dental", "fabrikam-capital"):
        data = _fixture(client)
        sites = data["sites"]
        # Computed independently of the module, straight from the raw fixture.
        broad = sum(1 for s in sites for ln in s["links"] if ln["scope"] in ("anyone", "everyone-except-external"))
        guests = sum(1 for s in sites for sh in s["shares"] if sh["recipientType"] == "guest")
        unlabelled = sum(1 for s in sites if s["sensitivity"] in ("health", "finance", "legal") and not s["label"])
        report = build_report(client)
        assert report.counts == {
            "everyone-link": broad,
            "external-share": guests,
            "unlabelled-sensitive-site": unlabelled,
        }
        assert report.totals == {
            "sites": len(sites),
            "links": sum(len(s["links"]) for s in sites),
            "shares": sum(len(s["shares"]) for s in sites),
        }


def test_b53_3_points_per_kind_equal_count_times_weight() -> None:
    report = build_report("contoso-dental")
    for kind in KINDS:
        assert report.points_by_kind[kind] == report.counts[kind] * WEIGHTS[kind]
    assert report.score == 100 - sum(report.counts[k] * WEIGHTS[k] for k in KINDS)
    text = render_markdown(report)
    assert "| everyone-link | 1 | 15 | 15 |" in text
    assert "| external-share | 1 | 10 | 10 |" in text
    assert "| unlabelled-sensitive-site | 1 | 20 | 20 |" in text
    assert "| total | 3 | - | 45 |" in text and "**Score: 55 / 100**" in text
    assert "Counted in the fixture: 4 site(s), 3 link(s), 2 share(s)." in text


def test_b53_3_the_clean_report_says_so_in_markdown() -> None:
    text = render_markdown(build_report("fabrikam-capital"))
    assert "**Score: 100 / 100**" in text and "nothing oversharing found" in text and "no label or DLP gap" in text


def test_b53_3_every_fixture_field_is_documented_as_unverified_or_invented() -> None:
    sources = (DEFAULT_FIXTURE_DIR / "SOURCES.md").read_text(encoding="utf-8")
    rows = {line.split("|")[1].strip(" `"): line for line in sources.splitlines() if line.startswith("| `")}

    def names(node: object) -> set[str]:
        if isinstance(node, dict):
            return set(node) | {n for v in node.values() for n in names(v)}
        if isinstance(node, list):
            return {n for v in node for n in names(v)}
        return set()

    found: set[str] = set()
    for path in DEFAULT_FIXTURE_DIR.glob("*.json"):
        found |= names(json.loads(path.read_text(encoding="utf-8")))
    found -= {"client", "as_of", "_note"}
    assert "`client`, `as_of`, `_note`" in sources
    assert not sorted(n for n in found if n not in rows), "fields missing from SOURCES.md"
    assert all("UNVERIFIED" in rows[n] or "invented" in rows[n] for n in found)
    assert "Verified (" not in sources.replace("UNVERIFIED", "")


# ------------------------------------------------------------------------------------------------ CLI and fixtures


def test_b53_cli_prints_json_markdown_and_exits_two_on_bad_input(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["contoso-dental", "--as-of", AS_OF]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["client"] == "contoso-dental" and out["score"] == 55 and len(out["findings"]) == 3
    assert main(["fabrikam-capital", "--markdown"]) == 0
    assert "nothing oversharing found" in capsys.readouterr().out
    assert main(["no such client"]) == 2
    assert "error:" in capsys.readouterr().err
    assert main(["contoso-dental", "--as-of", "yesterday"]) == 2
    assert "not an ISO date" in capsys.readouterr().err


def test_b53_running_the_report_changes_no_fixture() -> None:
    before = {p: p.read_bytes() for p in DEFAULT_FIXTURE_DIR.glob("*")}
    build_report("contoso-dental", as_of=AS_OF)
    build_report("fabrikam-capital", as_of=AS_OF)
    main(["contoso-dental"])
    assert before == {p: p.read_bytes() for p in before}


def test_b53_fixtures_are_synthetic_and_named_for_their_client() -> None:
    for path in DEFAULT_FIXTURE_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["client"] == path.stem and "Synthetic" in data["_note"]
        assert data["sites"], path.name
