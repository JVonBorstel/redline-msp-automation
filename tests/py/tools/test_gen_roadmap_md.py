"""tools/gen_roadmap_md.py and the generated-block check in map/check_map.py (order J260).

Every test works on temporary copies of the real map/roadmap.json and docs/ROADMAP.md; nothing in the repo changes.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]


def _load(name: str, rel: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


gen = _load("gen_roadmap_md", "tools/gen_roadmap_md.py")
cm = _load("check_map", "map/check_map.py")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "map").mkdir()
    (tmp_path / "docs").mkdir()
    shutil.copy(REPO / "map" / "roadmap.json", tmp_path / "map" / "roadmap.json")
    shutil.copy(REPO / "docs" / "ROADMAP.md", tmp_path / "docs" / "ROADMAP.md")
    return tmp_path


def _roadmap(root: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((root / "map" / "roadmap.json").read_text(encoding="utf-8"))
    return loaded


def _outside(text: str) -> list[str]:
    return gen._PAIR.split(text.replace("\r\n", "\n"))[::2]


def _data(roadmap: dict[str, Any]) -> Any:
    return cm.MapData([], [], [], roadmap)


def _wave(owns: dict[str, list[str]]) -> dict[str, Any]:
    return {"waves": [{"id": "W1", "items": [{"id": i, "owns": o} for i, o in owns.items()]}]}


def test_generating_twice_changes_nothing(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = root / "docs" / "ROADMAP.md"
    assert gen.main([str(root)]) == 0
    once = path.read_bytes()
    capsys.readouterr()
    assert gen.main([str(root)]) == 0
    assert path.read_bytes() == once
    assert "unchanged" in capsys.readouterr().out
    assert gen.main([str(root), "--check"]) == 0


def test_generating_keeps_a_crlf_file_crlf(root: Path) -> None:
    path = root / "docs" / "ROADMAP.md"
    lf = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    path.write_bytes(lf.replace("\n", "\r\n").encode("utf-8"))
    assert gen.main([str(root)]) == 0
    after = path.read_bytes()
    assert after.count(b"\n") == after.count(b"\r\n")
    assert gen.main([str(root)]) == 0
    assert path.read_bytes() == after


def test_owns_edit_in_json_alone_fails_the_check_with_the_fix_command(root: Path) -> None:
    gen.main([str(root)])
    md = (root / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    roadmap = _roadmap(root)
    roadmap["waves"][0]["items"][2]["owns"].append("extra/path.py")
    problems = cm.check_docs(_data(roadmap), {"docs/ROADMAP.md": md})
    assert any("near B-03" in p and f"fix with: {gen.FIX_COMMAND}" in p for p in problems)
    (root / "map" / "roadmap.json").write_text(json.dumps(roadmap), encoding="utf-8")
    assert gen.main([str(root)]) == 0
    fixed = (root / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    assert not any("item blocks differ" in p for p in cm.check_docs(_data(roadmap), {"docs/ROADMAP.md": fixed}))
    assert "`extra/path.py`" in fixed


def test_prose_outside_the_markers_is_unchanged(root: Path) -> None:
    path = root / "docs" / "ROADMAP.md"
    before = path.read_bytes().decode("utf-8")
    roadmap = _roadmap(root)
    roadmap["waves"][0]["items"][0]["title"] = "A new title"
    (root / "map" / "roadmap.json").write_text(json.dumps(roadmap), encoding="utf-8")
    assert gen.main([str(root)]) == 0
    after = path.read_bytes().decode("utf-8")
    assert after != before
    assert _outside(after) == _outside(before)
    assert before.count(gen.START) == before.count(gen.END) == len(roadmap["waves"])


def test_two_same_wave_items_owning_an_existing_file_give_a_warning(tmp_path: Path) -> None:
    (tmp_path / "shared.py").write_text("x = 1\n", encoding="utf-8")
    roadmap = _wave({"B-01": ["shared.py"], "B-02": ["shared.py"]})
    problems, warnings = cm._wave_overlaps(_data(roadmap), tmp_path)
    assert problems == []
    assert len(warnings) == 1 and "B-01" in warnings[0] and "B-02" in warnings[0]
    assert cm.roadmap_warnings(_data(roadmap), tmp_path) == warnings


def test_two_items_owning_the_same_new_path_are_still_a_problem(tmp_path: Path) -> None:
    roadmap = _wave({"B-01": ["new.py"], "B-02": ["new.py"]})
    problems, warnings = cm._wave_overlaps(_data(roadmap), tmp_path)
    assert warnings == []
    assert len(problems) == 1 and "own the same path" in problems[0]


def test_a_shared_folder_stays_a_problem_even_when_a_file_is_inside(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("", encoding="utf-8")
    roadmap = _wave({"B-01": ["pkg/"], "B-02": ["pkg/b.py"]})
    problems, warnings = cm._wave_overlaps(_data(roadmap), tmp_path)
    assert len(problems) == 1 and warnings == []


def test_a_malformed_acceptance_line_raises_and_names_the_item() -> None:
    item = {"id": "B-77", "title": "t", "why": "w", "owns": ["a"], "standards": ["STD"], "acceptance": ["no id here"]}
    with pytest.raises(ValueError, match="B-77"):
        gen.render_item(item)


def test_wrong_marker_counts_raise() -> None:
    with pytest.raises(ValueError, match="marker pairs"):
        gen.splice("no markers\n", ["a"])
    with pytest.raises(ValueError, match="marker pairs"):
        gen.splice(f"{gen.START}\nx\n", ["a"])
    nested = f"{gen.START}\n{gen.START}\nx\n{gen.END}\n{gen.END}\n"
    with pytest.raises(ValueError, match="marker pairs"):
        gen.splice(nested, ["a"])


def test_check_exits_1_on_a_stale_file_and_writes_nothing(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    roadmap = _roadmap(root)
    stale = copy.deepcopy(roadmap)
    stale["waves"][0]["items"][0]["why"] = "changed"
    (root / "map" / "roadmap.json").write_text(json.dumps(stale), encoding="utf-8")
    before = (root / "docs" / "ROADMAP.md").read_bytes()
    assert gen.main([str(root), "--check"]) == 1
    assert (root / "docs" / "ROADMAP.md").read_bytes() == before
    assert gen.FIX_COMMAND in capsys.readouterr().out


def test_a_missing_roadmap_file_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert gen.main([str(tmp_path)]) == 2
    assert "cannot generate" in capsys.readouterr().out


def test_the_real_roadmap_is_in_step_with_the_json() -> None:
    assert gen.main([str(REPO), "--check"]) == 0
