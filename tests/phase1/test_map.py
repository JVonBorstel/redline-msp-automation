"""Map integrity (docs/map/README.md section 6, rules MX-01 to MX-09): the checks in map/check_map.py run in CI.

The real maps must pass every check. Each negative test breaks one copy of the real data in memory and proves the
matching check notices, so a check that silently stopped working would fail here too. Nothing on disk is changed.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_map", REPO / "map" / "check_map.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_map"] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


cm = _load_checker()


@pytest.fixture(scope="module")
def data() -> Any:
    return cm.load(REPO)


@pytest.fixture(scope="module")
def docs() -> dict[str, str]:
    result: dict[str, str] = cm.read_docs(REPO)
    return result


def _copy(data: Any) -> Any:
    return cm.MapData(
        copy.deepcopy(data.inventory),
        copy.deepcopy(data.impact),
        copy.deepcopy(data.controls),
        copy.deepcopy(data.roadmap),
    )


def _item(d: Any, item_id: str) -> dict[str, Any]:
    for _, item in d.items():
        if item["id"] == item_id:
            found: dict[str, Any] = item
            return found
    raise KeyError(item_id)


def test_the_whole_map_is_consistent() -> None:
    assert cm.run_all(REPO) == []


def test_command_line_exits_zero_on_the_real_map(capsys: pytest.CaptureFixture[str]) -> None:
    assert cm.main([str(REPO)]) == 0
    assert "0 problem(s)" in capsys.readouterr().out


def test_each_check_passes_on_the_real_map(data: Any, docs: dict[str, str]) -> None:
    assert cm.check_ids(data) == []
    assert cm.check_impact(data) == []
    assert cm.check_controls(data, docs) == []
    assert cm.check_roadmap(data, docs["docs/STANDARDS.md"]) == []
    assert cm.check_docs(data, docs) == []


def test_duplicate_or_malformed_ids_are_reported(data: Any) -> None:
    d = _copy(data)
    d.inventory.append(copy.deepcopy(d.inventory[0]))
    d.controls[0]["id"] = "C-1"
    problems = cm.check_ids(d)
    assert any("duplicate inventory id W-SD-01" in p for p in problems)
    assert any("'C-1'" in p for p in problems)


def test_automatable_item_without_a_chain_is_reported(data: Any) -> None:
    d = _copy(data)
    removed = d.impact.pop(0)["inventory_id"]
    assert any(f"{removed} has an automation pattern but no impact chain" in p for p in cm.check_impact(d))


def test_chain_for_an_unknown_inventory_id_is_reported(data: Any) -> None:
    d = _copy(data)
    d.impact[0]["inventory_id"] = "W-SD-99"
    assert any("unknown inventory id W-SD-99" in p for p in cm.check_impact(d))


def test_undefined_control_is_reported_in_json_and_docs(data: Any) -> None:
    d = _copy(data)
    _item(d, "B-01")["controls"].append("C-99")
    d.impact[0]["safeguards"].append("C-98 Invented control (built)")
    problems = cm.check_controls(d, {"docs/x.md": "see C-97, and W-SEC-04 is not a control"})
    assert any("B-01: control C-99" in p for p in problems)
    assert any("undefined control C-98" in p for p in problems)
    assert any("docs/x.md: cites undefined control C-97" in p for p in problems)
    assert not any("C-04" in p for p in problems)


def test_safeguard_with_a_stale_status_is_reported(data: Any) -> None:
    d = _copy(data)
    chain = next(c for c in d.impact if any(s.startswith("C-30 ") for s in c["safeguards"]))
    chain["safeguards"] = [
        s.replace("(planned)", "(built)") if s.startswith("C-30 ") else s for s in chain["safeguards"]
    ]
    assert any("disagrees with controls.json" in p for p in cm.check_controls(d))


def test_roadmap_item_with_an_unknown_inventory_id_is_reported(data: Any) -> None:
    d = _copy(data)
    _item(d, "B-02")["inventory_ids"].append("W-XYZ-01")
    assert any("B-02: inventory id W-XYZ-01 does not exist" in p for p in cm.check_roadmap(d))


def test_uncovered_inventory_item_is_reported(data: Any) -> None:
    d = _copy(data)
    target = "W-BDR-01"
    for _, item in d.items():
        item["inventory_ids"] = [i for i in item["inventory_ids"] if i != target] or ["W-SD-01"]
    assert any(f"inventory {target} is covered by no roadmap item" in p for p in cm.check_roadmap(d))


def test_two_items_owning_one_path_in_a_wave_is_reported(data: Any) -> None:
    d = _copy(data)
    _item(d, "B-01")["owns"].append("no/such/new_path.py")
    _item(d, "B-02")["owns"].append("no/such/new_path.py")
    assert any("B-01" in p and "B-02" in p and "own the same path" in p for p in cm.check_roadmap(d))


def test_path_inside_another_items_folder_is_reported(data: Any) -> None:
    d = _copy(data)
    _item(d, "B-01")["owns"].append("workflows/notify/")
    _item(d, "B-02")["owns"].append("workflows/notify/templates/x.md")
    assert any("own the same path" in p for p in cm.check_roadmap(d))


def test_two_items_sharing_an_existing_file_in_a_wave_is_only_a_warning(data: Any) -> None:
    d = _copy(data)
    _item(d, "B-01")["owns"].append("map/check_map.py")
    _item(d, "B-02")["owns"].append("map/check_map.py")
    assert not any("B-01" in p and "B-02" in p for p in cm.check_roadmap(d, None, REPO))
    assert any("B-01" in w and "B-02" in w and "existing file" in w for w in cm.roadmap_warnings(d, REPO))


def test_dependency_on_a_later_wave_is_reported(data: Any) -> None:
    d = _copy(data)
    _item(d, "B-01")["depends_on"].append("B-98")
    assert any("B-01 (W1) depends on B-98 in a later wave" in p for p in cm.check_roadmap(d))


def test_dependency_cycle_is_reported(data: Any) -> None:
    d = _copy(data)
    _item(d, "B-01")["depends_on"].append("B-02")
    assert any("dependency cycle" in p for p in cm.check_roadmap(d))


def test_unknown_standard_section_is_reported(data: Any, docs: dict[str, str]) -> None:
    d = _copy(data)
    _item(d, "B-01")["standards"].append("STD-ZZ")
    assert any("standard STD-ZZ" in p for p in cm.check_roadmap(d, docs["docs/STANDARDS.md"]))


def test_markdown_twin_out_of_step_with_json_is_reported(data: Any, docs: dict[str, str]) -> None:
    d = _copy(data)
    _item(d, "B-03")["owns"].append("extra/path.py")
    changed = dict(docs)
    changed["docs/map/02-impact-chains.md"] = changed["docs/map/02-impact-chains.md"].replace(
        "#### `W-SD-03` ", "x ", 1
    )
    problems = cm.check_docs(d, changed)
    assert any("item blocks differ from map/roadmap.json near B-03" in p for p in problems)
    assert any("gen_roadmap_md.py" in p for p in problems)
    assert any("no section for W-SD-03" in p for p in problems)


def test_undefined_ids_and_missing_status_line_in_a_doc_are_reported(data: Any, docs: dict[str, str]) -> None:
    changed = dict(docs)
    changed["docs/map/README.md"] = "# Title\n\nNo status here. Cites W-SD-99, B-99, STD-LV-99, DR-99 and W1-X9.\n"
    problems = [p for p in cm.check_docs(data, changed) if p.startswith("docs/map/README.md")]
    for expected in ("W-SD-99", "B-99", "STD-LV-99", "DR-99", "W1-X9", "STD-DC-1"):
        assert any(expected in p for p in problems), expected


def test_b06_2_dependency_on_an_unknown_item_is_reported(data: Any) -> None:
    d = _copy(data)
    _item(d, "B-01")["depends_on"].append("B-zz")
    assert any("B-01: depends on unknown item B-zz" in p for p in cm.check_roadmap(d))


def test_b06_3_an_item_covered_only_by_a_not_now_entry_is_not_reported(data: Any) -> None:
    d = _copy(data)
    target = "W-BDR-01"
    for _, item in d.items():
        item["inventory_ids"] = [i for i in item["inventory_ids"] if i != target] or ["W-SD-01"]
    d.roadmap["not_now"].append({"id": "NN-99", "inventory_ids": [target]})
    assert not any(f"inventory {target} is covered by no" in p for p in cm.check_roadmap(d))


def test_b06_5_the_py_runner_prints_its_summary_line() -> None:
    text = (REPO / "tests" / "py" / "Test-Py.ps1").read_text(encoding="utf-8")
    assert 'Write-Host "Py tests: $pass passed, $fail failed in $secs s"' in text
    assert "uv run --frozen" in text


def test_b06_6_a_risk_class_mismatch_warns_without_failing(data: Any) -> None:
    d = _copy(data)
    for item in d.inventory:
        if item["id"] == "W-SD-01":
            item["risk_class"] = "R0" if item["risk_class"] != "R0" else "R1"
    saved = dict(cm.GOVERNANCE_RISK)
    cm.GOVERNANCE_RISK["W-SD-01"] = "R3"
    try:
        assert any("W-SD-01" in w for w in cm.check_risk_classes(d))
    finally:
        cm.GOVERNANCE_RISK.clear()
        cm.GOVERNANCE_RISK.update(saved)
    assert cm.run_all(REPO) == []


def test_b06_6_the_real_map_prints_the_warning_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert cm.main([str(REPO)]) == 0
    out = capsys.readouterr().out
    assert "WARNING: W-IDM-02" in out
    assert "0 problem(s)" in out
