"""B-98 coverage audit tests (specs/B-98.md: B98-4 to B98-8). Offline, synthetic temp repos plus the real repo.

The audit tool (tools/coverage_audit.py) reads map/, change notes, specs, tests, the lever registry and the workflow
folders, and reports where the map and the code disagree. Detection is proven on small synthetic repos with known
gaps; the real repo's committed report and README status block must equal what the tool computes now.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/tools/test_b98_coverage_audit.py
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[3]
TOOL = REPO / "tools" / "coverage_audit.py"
REPORT = REPO / "docs" / "COVERAGE_AUDIT.md"
PATCH = REPO / "docs" / "changes" / "B-98-map-status.patch"
README = REPO / "README.md"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("coverage_audit_under_test", TOOL)
    assert spec and spec.loader, "tools/coverage_audit.py is missing"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ca() -> ModuleType:
    return _load()


def _w(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _item(item_id: str, owns: list[str], inv: list[str], ctl: list[str], owner_only: bool = False) -> dict[str, object]:
    return {
        "id": item_id,
        "title": f"title {item_id}",
        "inventory_ids": inv,
        "controls": ctl,
        "depends_on": [],
        "owns": owns,
        "acceptance": [f"{item_id.replace('-', '')}-1: x"],
        "owner_only": owner_only,
    }


def make_repo(root: Path) -> Path:
    """A tiny repo with known gaps. B-01 is complete, B-02 lacks a spec, B-03 has nothing."""
    roadmap = {
        "waves": [
            {
                "id": "W1",
                "items": [
                    _item(
                        "B-01",
                        ["workflows/good/", "tests/py/test_b01_good.py", "specs/B-01.md", "docs/changes/B-01.md"],
                        ["W-AAA-01"],
                        ["C-01"],
                    ),
                    _item(
                        "B-02",
                        ["workflows/nospec/", "tests/py/test_b02_missing.py", "docs/changes/B-02.md"],
                        ["W-AAA-04"],
                        ["C-02"],
                    ),
                    _item("B-03", ["workflows/later/", "specs/B-03.md"], ["W-AAA-02", "W-AAA-03"], ["C-04"]),
                ],
            }
        ],
        "not_now": [],
    }
    inventory = [
        {"id": "W-AAA-01", "name": "one", "repo_status": "planned: Phase 3"},
        {"id": "W-AAA-02", "name": "two", "repo_status": "exists: core/ghost/thing.py"},
        {"id": "W-AAA-03", "name": "three", "repo_status": "planned: Phase 9"},
        {"id": "W-AAA-04", "name": "four", "repo_status": "partial: workflows/nospec"},
    ]
    controls = [
        {
            "id": "C-01",
            "name": "ok",
            "implemented_in": "workflows/good/run.py",
            "evidence": "tests/py/test_b01_good.py::test_good (fixture-based)",
        },
        {
            "id": "C-02",
            "name": "gone file",
            "implemented_in": "workflows/good/run.py",
            "evidence": "tests/py/test_gone.py::test_x",
        },
        {
            "id": "C-03",
            "name": "gone name",
            "implemented_in": "workflows/good/run.py",
            "evidence": "tests/py/test_b01_good.py::test_good, ::test_not_there",
        },
        {"id": "C-04", "name": "planned", "implemented_in": "planned (workflows/later/)", "evidence": "planned: x"},
    ]
    _w(root, "map/roadmap.json", json.dumps(roadmap))
    _w(root, "map/inventory.json", json.dumps(inventory, indent=2))
    _w(root, "map/controls.json", json.dumps(controls))
    _w(root, "levers/registry.json", json.dumps({"levers": [{"name": "alpha.read"}, {"name": "beta.write"}]}))
    _w(root, "workflows/good/run.py", "x = 1\n")
    _w(root, "workflows/good/README.md", "# good\n")
    _w(root, "workflows/nospec/run.py", "x = 1\n")
    _w(root, "workflows/stray/run.py", "x = 1\n")
    _w(root, "tests/py/test_b01_good.py", 'def test_good():\n    assert "alpha.read"\n')
    _w(root, "specs/B-01.md", "# B-01\n")
    _w(root, "docs/changes/B-01.md", "# B-01 change note\n\nStatus: **built** (tested).\n")
    _w(root, "docs/changes/B-02.md", "# B-02 change note\n\nStatus: **built**.\n")
    _w(root, "docs/changes/B-77.md", "# B-77 change note for an item that is not in the roadmap\n")
    return root


@pytest.fixture()
def mini(tmp_path: Path, ca: ModuleType) -> tuple[ModuleType, object]:
    root = make_repo(tmp_path / "repo")
    return ca, ca.run_audit(root)


def _kinds(audit: object, subject: str) -> set[str]:
    return {f.kind for f in audit.findings if f.subject == subject}  # type: ignore[attr-defined]


def _status(rows: list[object], row_id: str) -> str:
    return next(r.status for r in rows if r.id == row_id)  # type: ignore[attr-defined]


# -- B98-4: roadmap items ------------------------------------------------------------------------------------------


def test_b98_4_item_status_comes_from_files_not_from_words(mini: tuple[ModuleType, object]) -> None:
    _, audit = mini
    assert _status(audit.items, "B-01") == "built"  # type: ignore[attr-defined]
    assert _status(audit.items, "B-02") == "partial"  # type: ignore[attr-defined]  (note says built; no spec)
    assert _status(audit.items, "B-03") == "planned"  # type: ignore[attr-defined]
    assert {"ITEM-NO-SPEC", "ITEM-MISSING-OWNED", "ITEM-NOTE-SAYS-BUILT"} <= _kinds(audit, "B-02")
    assert "ITEM-NO-NOTE" in _kinds(audit, "B-03")


def test_b98_4_a_change_note_with_no_roadmap_item_is_reported(mini: tuple[ModuleType, object]) -> None:
    _, audit = mini
    assert "NOTE-NO-ITEM" in _kinds(audit, "B-77")


# -- B98-5: inventory and controls ---------------------------------------------------------------------------------


def test_b98_5_stale_planned_inventory_row_is_flagged_and_patched(mini: tuple[ModuleType, object]) -> None:
    ca, audit = mini
    assert "INV-STALE-PLANNED" in _kinds(audit, "W-AAA-01")
    assert _status(audit.inventory, "W-AAA-01") == "built"  # type: ignore[attr-defined]
    assert _status(audit.inventory, "W-AAA-03") == "planned"  # type: ignore[attr-defined]
    assert "INV-STALE-PLANNED" not in _kinds(audit, "W-AAA-03")
    patch = ca.propose_patch(audit.root, audit)  # type: ignore[attr-defined]
    assert "--- a/map/inventory.json" in patch and "+++ b/map/inventory.json" in patch
    assert "W-AAA-01" in patch or "Phase 3" in patch
    assert "Phase 9" not in patch  # only clear cases are proposed


def test_b98_5_unsupported_claims_are_flagged(mini: tuple[ModuleType, object]) -> None:
    _, audit = mini
    kinds = _kinds(audit, "W-AAA-02")
    assert "INV-UNSUPPORTED" in kinds and "INV-MISSING-PATH" in kinds
    assert _status(audit.inventory, "W-AAA-02") == "planned"  # type: ignore[attr-defined]
    assert _status(audit.inventory, "W-AAA-04") == "partial"  # type: ignore[attr-defined]


def test_b98_5_control_citing_a_missing_test_is_flagged(mini: tuple[ModuleType, object]) -> None:
    _, audit = mini
    assert _status(audit.controls, "C-01") == "built"  # type: ignore[attr-defined]
    assert "CTL-MISSING-TEST-FILE" in _kinds(audit, "C-02")
    assert "CTL-MISSING-TEST-NAME" in _kinds(audit, "C-03")
    assert _status(audit.controls, "C-02") == "partial"  # type: ignore[attr-defined]
    assert _status(audit.controls, "C-04") == "planned"  # type: ignore[attr-defined]
    assert not _kinds(audit, "C-01")


# -- B98-6: levers, workflows --------------------------------------------------------------------------------------


def test_b98_6_lever_without_a_test_is_flagged(mini: tuple[ModuleType, object]) -> None:
    _, audit = mini
    assert not _kinds(audit, "alpha.read")
    assert "LEVER-NO-TEST" in _kinds(audit, "beta.write")


def test_b98_6_workflow_folder_without_spec_or_owner_is_flagged(mini: tuple[ModuleType, object]) -> None:
    _, audit = mini
    assert "WF-NO-SPEC" in _kinds(audit, "workflows/nospec")
    assert "WF-NO-TEST" in _kinds(audit, "workflows/nospec")
    assert {"WF-UNOWNED", "WF-NO-SPEC"} <= _kinds(audit, "workflows/stray")
    assert not _kinds(audit, "workflows/good") - {"WF-NO-TEST"}


# -- B98-7: headline, report, determinism --------------------------------------------------------------------------


def test_b98_7_headline_counts_and_is_deterministic(mini: tuple[ModuleType, object]) -> None:
    ca, audit = mini
    head = audit.headline()  # type: ignore[attr-defined]
    assert head["items_total"] == 3 and head["items_built"] == 1
    assert head["items_partial"] == 1 and head["items_planned"] == 1
    assert ca.render_report(audit) == ca.render_report(ca.run_audit(audit.root))  # type: ignore[attr-defined]
    assert "1 of 3" in ca.headline_line(audit)


def test_b98_7_report_lists_every_gap_with_its_id(mini: tuple[ModuleType, object]) -> None:
    ca, audit = mini
    text = ca.render_report(audit)
    for needle in ("ITEM-NO-SPEC", "CTL-MISSING-TEST-NAME", "LEVER-NO-TEST", "WF-NO-SPEC", "INV-STALE-PLANNED", "B-77"):
        assert needle in text, needle
    assert "fixture-based" in text or "synthetic" in text.lower()


def test_b98_7_cli_check_fails_on_a_stale_report(tmp_path: Path, ca: ModuleType) -> None:
    root = make_repo(tmp_path / "repo")
    stale = root / "docs" / "COVERAGE_AUDIT.md"
    _w(root, "docs/COVERAGE_AUDIT.md", "old\n")
    out = subprocess.run(  # noqa: S603 - fixed argv, local interpreter, repo script
        [sys.executable, str(TOOL), "--root", str(root), "--check"], capture_output=True, text=True, check=False
    )
    assert out.returncode == 1 and "stale" in (out.stdout + out.stderr).lower()
    write = subprocess.run(  # noqa: S603
        [sys.executable, str(TOOL), "--root", str(root), "--write"], capture_output=True, text=True, check=False
    )
    assert write.returncode == 0, write.stderr
    assert stale.read_text(encoding="utf-8") == ca.render_report(ca.run_audit(root))
    again = subprocess.run(  # noqa: S603
        [sys.executable, str(TOOL), "--root", str(root), "--check"], capture_output=True, text=True, check=False
    )
    assert again.returncode == 0, again.stdout + again.stderr


# -- B98-8: the real repo ------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real(ca: ModuleType) -> object:
    return ca.run_audit(REPO)


def test_b98_8_real_repo_headline_and_committed_report_agree(ca: ModuleType, real: object) -> None:
    head = real.headline()  # type: ignore[attr-defined]
    assert head["items_total"] == 98
    assert head["items_built"] + head["items_partial"] + head["items_planned"] + head["items_not_demonstrated"] == 98
    assert head["inventory_total"] == 152 and head["controls_total"] == 45
    assert REPORT.is_file(), "run: uv run --frozen python tools/coverage_audit.py --write"
    assert REPORT.read_text(encoding="utf-8") == ca.render_report(real), (
        "docs/COVERAGE_AUDIT.md is stale; rerun --write"
    )


def test_b98_8_readme_status_block_is_the_one_the_tool_computes(ca: ModuleType, real: object) -> None:
    text = README.read_text(encoding="utf-8")
    start, end = ca.README_START, ca.README_END
    assert text.count(start) == 1 and text.count(end) == 1
    block = text.split(start, 1)[1].split(end, 1)[0]
    assert block.strip() == ca.readme_block(real).strip()
    assert f"of {real.headline()['items_total']}" in block  # type: ignore[attr-defined]


def test_b98_8_real_repo_gaps_are_listed_not_hidden(ca: ModuleType, real: object) -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert real.findings, "the audit found nothing, which this repo's own history says is not credible"  # type: ignore[attr-defined]
    for finding in real.findings:  # type: ignore[attr-defined]
        assert finding.kind in text and finding.subject in text
    # The map was brought up to date on 2026-10-27 (the B-98 patch applied and extended). What stays open is real and
    # listed: the Bicep of B-85 and B-86 has never been compiled, so the audit must keep saying "not demonstrated".
    not_demonstrated = {f.subject for f in real.findings if f.kind == "ITEM-NOT-DEMONSTRATED"}  # type: ignore[attr-defined]
    assert {"B-85", "B-86"} <= not_demonstrated


def test_b98_8_every_lever_and_workflow_folder_is_accounted_for(real: object) -> None:
    levers = {r.id for r in real.levers}  # type: ignore[attr-defined]
    registry = json.loads((REPO / "levers" / "registry.json").read_text(encoding="utf-8"))["levers"]
    assert {entry["name"] for entry in registry} <= levers
    folders = {p.name for p in (REPO / "workflows").iterdir() if p.is_dir() and p.name != "__pycache__"}
    assert folders == {r.id.split("/", 1)[1] for r in real.workflows}  # type: ignore[attr-defined]


def test_b98_8_patch_file_applies_cleanly_to_the_map(ca: ModuleType, real: object, tmp_path: Path) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not on PATH")
    assert PATCH.is_file(), "run: uv run --frozen python tools/coverage_audit.py --write"
    proposed = ca.propose_patch(REPO, real)
    assert PATCH.read_text(encoding="utf-8") == proposed
    if not proposed:
        # Nothing is stale: the patch was applied to map/inventory.json and the tool now proposes no change.
        assert not real.stale_inventory  # type: ignore[attr-defined]
        return
    work = tmp_path / "copy"
    (work / "map").mkdir(parents=True)
    lf = (REPO / "map" / "inventory.json").read_bytes().replace(b"\r\n", b"\n")  # a Windows checkout may be CRLF
    (work / "map" / "inventory.json").write_bytes(lf)
    lf_patch = tmp_path / "map-status.patch"  # a Windows checkout (autocrlf) may hold the patch as CRLF
    lf_patch.write_bytes(PATCH.read_bytes().replace(b"\r\n", b"\n"))
    check = subprocess.run(  # noqa: S603 - fixed argv, temp copy of one file
        [git, "apply", "--check", str(lf_patch)],
        capture_output=True,
        text=True,
        cwd=work,
        check=False,
    )
    assert check.returncode == 0, check.stderr
