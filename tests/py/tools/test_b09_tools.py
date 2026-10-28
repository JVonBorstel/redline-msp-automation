"""B-09 acceptance tests: roadmap exporter and change-fragment folder (offline)."""

from __future__ import annotations

import csv
import io
import json
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ROADMAP = REPO_ROOT / "map" / "roadmap.json"
EXPORTER = REPO_ROOT / "tools" / "roadmap_issues.py"
FOLDER = REPO_ROOT / "tools" / "fold_changes.py"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell, local interpreter and repo scripts
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _wave_items(wave: str) -> list[dict[str, object]]:
    data = json.loads(ROADMAP.read_text(encoding="utf-8"))
    for w in data["waves"]:
        if w["id"] == wave:
            items: list[dict[str, object]] = w["items"]
            return items
    raise AssertionError(wave)


def test_b09_1_gh_commands_one_per_item() -> None:
    result = _run(EXPORTER, "--wave", "W1")
    assert result.returncode == 0, result.stderr
    tokens = shlex.split(result.stdout)
    starts = [i for i, t in enumerate(tokens) if t == "gh"]
    commands = [tokens[a:b] for a, b in zip(starts, [*starts[1:], len(tokens)], strict=True)]
    items = _wave_items("W1")
    assert len(commands) == len(items)
    for command, item in zip(commands, items, strict=True):
        assert command[:3] == ["gh", "issue", "create"]
        assert command[command.index("--title") + 1] == f"{item['id']}: {item['title']}"
        assert command[command.index("--milestone") + 1] == "W1"
        assert "wave:W1" in command
        body = command[command.index("--body") + 1]
        for field in ("inventory_ids", "controls", "depends_on", "owns", "acceptance", "standards"):
            for value in item[field]:  # type: ignore[attr-defined]
                assert str(value) in body
        assert str(item["why"]) in body
        assert str(item["size"]) in body


def test_b09_1_exporter_runs_nothing() -> None:
    source = EXPORTER.read_text(encoding="utf-8")
    for word in ("subprocess", "os.system", "os.popen", "urllib", "socket"):
        assert word not in source


def test_b09_2_ado_csv_same_items() -> None:
    result = _run(EXPORTER, "--wave", "W1", "--format", "ado-csv")
    assert result.returncode == 0, result.stderr
    rows = list(csv.DictReader(io.StringIO(result.stdout)))
    items = _wave_items("W1")
    assert list(rows[0]) == ["Work Item Type", "Title", "Tags", "Iteration Path", "Description"]
    assert [r["Title"] for r in rows] == [f"{i['id']}: {i['title']}" for i in items]
    assert all(r["Iteration Path"] == "W1" and r["Work Item Type"] for r in rows)
    assert "wave:W1" in rows[0]["Tags"]


def test_b09_4_unknown_wave_refused() -> None:
    result = _run(EXPORTER, "--wave", "W99")
    assert result.returncode != 0
    assert "W1" in result.stderr


def _fake_repo(root: Path) -> None:
    (root / "map").mkdir()
    (root / "docs" / "changes").mkdir(parents=True)
    roadmap = {"waves": [{"id": "W1", "items": [{"id": "B-01"}, {"id": "B-02"}]}]}
    (root / "map" / "roadmap.json").write_text(json.dumps(roadmap), encoding="utf-8")
    (root / "docs" / "changes" / "B-01.md").write_text(
        "## DECISIONS\n\nDecided one.\n\n## CHANGELOG\n\n- Added one.\n\n## RUNBOOKS\n\nnone\n",
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_b09_3_dry_run_prints_and_changes_nothing(tmp_path: Path) -> None:
    _fake_repo(tmp_path)
    before = _snapshot(tmp_path)
    result = _run(FOLDER, "--wave", "W1", "--dry-run", "--root", str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert "docs/DECISIONS.md" in result.stdout and "Decided one." in result.stdout
    assert "- Added one." in result.stdout
    assert "RUNBOOKS" not in result.stdout
    assert _snapshot(tmp_path) == before


def test_b09_3_fold_appends_then_is_idempotent(tmp_path: Path) -> None:
    _fake_repo(tmp_path)
    first = _run(FOLDER, "--wave", "W1", "--root", str(tmp_path))
    assert first.returncode == 0, first.stderr
    decisions = (tmp_path / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "<!-- fold:B-01:DECISIONS -->" in decisions and "Decided one." in decisions
    assert changelog.startswith("# Changelog\n") and "- Added one." in changelog
    after_first = _snapshot(tmp_path)
    second = _run(FOLDER, "--wave", "W1", "--root", str(tmp_path))
    assert second.returncode == 0, second.stderr
    assert "nothing to fold" in second.stdout
    assert _snapshot(tmp_path) == after_first
