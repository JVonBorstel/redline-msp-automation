"""B-95 SOC 2 control mapping and risk register (acceptance B95-3), and the generated files.

The mapping and the register are generated from map/controls.json, the AIR table of docs/map/05-governance.md and two
small data files that hold only what the map cannot: what backs each control, what is not demonstrated, and the
owner and treatment of each risk. The checker fails when a mapped control cites a test or a file that does not exist.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/governance
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from workflows.assurance import render
from workflows.assurance.risk import check_register, load_register, parse_air_table, render_register
from workflows.assurance.soc2 import (
    check_mapping,
    control_status,
    load_controls,
    load_mapping,
    render_mapping,
)

REPO = Path(__file__).resolve().parents[3]
MAPPING_DOC = REPO / "governance" / "SOC2_CONTROL_MAPPING.md"
REGISTER_DOC = REPO / "governance" / "RISK_REGISTER.md"
GOV_MAP = REPO / "docs" / "map" / "05-governance.md"


@pytest.fixture(scope="module")
def controls() -> list[dict[str, Any]]:
    return load_controls(REPO)


@pytest.fixture(scope="module")
def mapping() -> dict[str, Any]:
    return load_mapping(REPO)


# -- the mapping ------------------------------------------------------------------------------------------------------
def test_b95_3_the_committed_mapping_passes_the_checker(
    controls: list[dict[str, Any]], mapping: dict[str, Any]
) -> None:
    assert check_mapping(mapping, controls, REPO) == []


def test_b95_3_every_control_is_mapped_and_none_is_invented(
    controls: list[dict[str, Any]], mapping: dict[str, Any]
) -> None:
    assert set(mapping["controls"]) == {c["id"] for c in controls}


def test_b95_3_status_follows_the_map_rule_used_by_the_map_check(controls: list[dict[str, Any]]) -> None:
    spec = importlib.util.spec_from_file_location("check_map_b95", REPO / "map" / "check_map.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        for control in controls:
            assert control_status(control) == module.control_status(control), control["id"]
    finally:
        sys.modules.pop(spec.name, None)


def test_b95_3_checker_fails_on_a_test_file_that_does_not_exist(
    controls: list[dict[str, Any]], mapping: dict[str, Any]
) -> None:
    bad = copy.deepcopy(mapping)
    bad["controls"]["C-01"]["tests"].append("tests/phase1/test_no_such_file.py::test_x")
    problems = check_mapping(bad, controls, REPO)
    assert any("C-01" in p and "test_no_such_file.py" in p for p in problems)


def test_b95_3_checker_fails_on_a_test_name_that_does_not_exist_in_the_file(
    controls: list[dict[str, Any]], mapping: dict[str, Any]
) -> None:
    bad = copy.deepcopy(mapping)
    bad["controls"]["C-02"]["tests"].append("tests/phase1/test_levers.py::test_there_is_no_such_test")
    problems = check_mapping(bad, controls, REPO)
    assert any("C-02" in p and "test_there_is_no_such_test" in p for p in problems)


def test_b95_3_checker_fails_on_a_file_or_folder_that_does_not_exist(
    controls: list[dict[str, Any]], mapping: dict[str, Any]
) -> None:
    bad = copy.deepcopy(mapping)
    bad["controls"]["C-03"]["files"] += ["core/identity/missing.py", "core/nowhere/"]
    problems = check_mapping(bad, controls, REPO)
    assert any("C-03" in p and "missing.py" in p for p in problems)
    assert any("C-03" in p and "nowhere" in p for p in problems)


def test_b95_3_checker_refuses_paths_that_climb_out_of_the_repo(
    controls: list[dict[str, Any]], mapping: dict[str, Any]
) -> None:
    bad = copy.deepcopy(mapping)
    bad["controls"]["C-04"]["files"].append("../outside.txt")
    assert any("C-04" in p and "outside" in p for p in check_mapping(bad, controls, REPO))


def test_b95_3_checker_fails_on_an_unmapped_unknown_or_unexplained_control(
    controls: list[dict[str, Any]], mapping: dict[str, Any]
) -> None:
    bad = copy.deepcopy(mapping)
    del bad["controls"]["C-05"]
    bad["controls"]["C-99"] = {"tests": [], "files": [], "not_demonstrated": ["x"]}
    bad["controls"]["C-06"]["not_demonstrated"] = []
    problems = check_mapping(bad, controls, REPO)
    assert any("C-05" in p and "no mapping" in p for p in problems)
    assert any("C-99" in p for p in problems)
    assert any("C-06" in p and "not demonstrated" in p for p in problems)


def test_b95_3_the_mapping_names_every_soc2_criterion_the_map_cites(controls: list[dict[str, Any]]) -> None:
    text = MAPPING_DOC.read_text(encoding="utf-8")
    cited = {ref.split(":", 1)[1] for c in controls for ref in c["framework_refs"] if ref.startswith("SOC2:")}
    assert cited
    for criterion in cited:
        assert re.search(rf"`{re.escape(criterion)}`", text), criterion


def test_b95_3_every_control_row_has_a_not_demonstrated_cell(
    controls: list[dict[str, Any]], mapping: dict[str, Any]
) -> None:
    text = render_mapping(controls, mapping)
    rows = [line for line in text.splitlines() if line.startswith("| C-")]
    assert len(rows) == len(controls)
    for line in rows:
        cells = [c.strip() for c in line.strip("|").split(" | ")]
        assert len(cells) == 7 and cells[6], line


def test_b95_3_the_mapping_makes_no_certification_claim(
    controls: list[dict[str, Any]], mapping: dict[str, Any]
) -> None:
    text = render_mapping(controls, mapping)
    assert "not a certification" in text.lower() and "not an attestation" in text.lower()
    for pattern in (
        r"\bis SOC 2 (compliant|certified)\b",
        r"\bwe are (compliant|certified)\b",
        r"\bpasses? (a |the )?audit\b",
    ):
        assert not re.search(pattern, text, flags=re.I), pattern


def test_b95_3_planned_controls_are_shown_as_nothing_demonstrated(
    controls: list[dict[str, Any]], mapping: dict[str, Any]
) -> None:
    # No control in the map is planned since 2026-10-27, so a copy marks C-30 planned.
    marked = [{**c, "implemented_in": "planned"} if c["id"] == "C-30" else c for c in controls]
    text = render_mapping(marked, mapping)
    row = next(line for line in text.splitlines() if line.startswith("| C-30 "))
    assert "planned" in row and "Not built" in row


def test_b95_3_a_built_control_with_no_test_is_listed_not_hidden(
    controls: list[dict[str, Any]], mapping: dict[str, Any]
) -> None:
    # C-24 cites tests since 2026-10-27, so a copy of the mapping drops them.
    bare = copy.deepcopy(mapping)
    bare["controls"]["C-24"]["tests"] = []
    text = render_mapping(controls, bare)
    assert "No test in this repo" in next(line for line in text.splitlines() if line.startswith("| C-24 "))


# -- the risk register ------------------------------------------------------------------------------------------------
def test_b95_3_the_air_table_parses_to_twelve_risks() -> None:
    rows = parse_air_table(GOV_MAP.read_text(encoding="utf-8"))
    assert [r["id"] for r in rows] == [f"AIR-{n}" for n in range(1, 13)]
    assert all(r["controls"] and r["residual"] for r in rows)


def test_b95_3_the_committed_register_passes_the_checker(controls: list[dict[str, Any]]) -> None:
    air = parse_air_table(GOV_MAP.read_text(encoding="utf-8"))
    assert check_register(load_register(REPO), air, controls) == []


def test_b95_3_every_risk_has_an_owner_role_and_a_treatment() -> None:
    text = render_register(REPO)
    rows = [line for line in text.splitlines() if line.startswith(("| AIR-", "| RR-"))]
    assert len(rows) == 16
    for line in rows:
        assert re.search(r"\| (mitigate|avoid|accept|transfer) \|", line), line
        assert "role" in line, line


def test_b95_3_checker_fails_on_a_missing_owner_unknown_control_or_unlisted_risk(
    controls: list[dict[str, Any]],
) -> None:
    air = parse_air_table(GOV_MAP.read_text(encoding="utf-8"))
    register = load_register(REPO)
    bad = copy.deepcopy(register)
    del bad["air"]["AIR-3"]
    bad["air"]["AIR-4"]["owner_role"] = ""
    bad["air"]["AIR-5"]["treatment"] = "ignore"
    bad["air"]["AIR-99"] = bad["air"]["AIR-1"]
    bad["extra"][0]["controls"] = ["C-99"]
    problems = check_register(bad, air, controls)
    assert any("AIR-3" in p for p in problems)
    assert any("AIR-4" in p and "owner" in p for p in problems)
    assert any("AIR-5" in p and "treatment" in p for p in problems)
    assert any("AIR-99" in p for p in problems)
    assert any("RR-1" in p and "C-99" in p for p in problems)


def test_b95_3_checker_fails_when_the_governance_map_cites_an_unknown_control(controls: list[dict[str, Any]]) -> None:
    text = GOV_MAP.read_text(encoding="utf-8").replace("C-12 wrap as untrusted", "C-98 wrap as untrusted", 1)
    air = parse_air_table(text)
    problems = check_register(load_register(REPO), air, controls)
    assert any("AIR-1" in p and "C-98" in p for p in problems)


def test_b95_3_an_accepted_risk_needs_a_rationale(controls: list[dict[str, Any]]) -> None:
    air = parse_air_table(GOV_MAP.read_text(encoding="utf-8"))
    bad = copy.deepcopy(load_register(REPO))
    bad["air"]["AIR-7"]["rationale"] = ""
    assert any("AIR-7" in p and "rationale" in p for p in check_register(bad, air, controls))


def test_b95_3_the_register_gives_no_invented_rating() -> None:
    text = render_register(REPO)
    assert "No likelihood or impact rating" in text
    assert not re.search(r"\b(likelihood|impact)\b *[:=] *(low|medium|high)", text, flags=re.I)


# -- generated files cannot drift -------------------------------------------------------------------------------------
def test_b95_3_generated_files_equal_the_committed_files() -> None:
    outputs = render.generate_all(REPO)
    assert set(outputs) == {
        "governance/USE_CASE_INTAKE.md",
        "governance/ROI_TRACKER.md",
        "governance/SOC2_CONTROL_MAPPING.md",
        "governance/RISK_REGISTER.md",
        "governance/use_case_intake.schema.json",
    }
    assert render.drift(REPO, outputs) == []


def test_b95_3_drift_is_reported_for_a_changed_or_missing_file() -> None:
    outputs = render.generate_all(REPO)
    outputs["governance/RISK_REGISTER.md"] += "edited by hand\n"
    outputs["governance/NEW_FILE.md"] = "x\n"
    drifted = render.drift(REPO, outputs)
    assert any("RISK_REGISTER.md" in d for d in drifted)
    assert any("NEW_FILE.md" in d for d in drifted)


def test_b95_3_every_generated_page_has_a_status_line_and_the_standard_labels() -> None:
    for name, text in render.generate_all(REPO).items():
        if not name.endswith(".md"):
            continue
        lines = text.splitlines()
        assert lines[0].startswith("# "), name
        assert re.match(r"^Status: \*\*(built|mocked|document-only)\*\*", lines[2]), name
        assert "Independently built prototype. Not affiliated with any vendor's or real company's systems." in text, (
            name
        )
        assert "Synthetic data only." in text, name
        assert "generated" in text.lower(), name


def test_b95_3_the_cli_check_exits_zero_on_the_committed_repo_and_dry_runs_by_default(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from workflows.assurance.__main__ import main

    assert main(["check"]) == 0
    assert main(["generate"]) == 0  # dry run: nothing is written, drift would be listed
    out = capsys.readouterr().out
    assert "in sync" in out


def test_b95_3_the_cli_score_prints_a_ranked_table_with_reasons(capsys: pytest.CaptureFixture[str]) -> None:
    from workflows.assurance.__main__ import main

    assert main(["score"]) == 0
    out = capsys.readouterr().out
    assert "UC-001" in out and "blocked" in out and "never-automate" in out
    assert main(["score", "--json"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert {p["id"] for p in parsed} == {f"UC-{n:03d}" for n in range(1, 11)}
