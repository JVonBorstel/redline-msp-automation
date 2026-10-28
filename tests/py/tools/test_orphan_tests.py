"""J259 orphan-test guard: every test file lives under a root some runner collects (offline, synthetic temp trees)."""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# The one list of places a runner collects tests from. Each root must be named in a runner (see RUNNER_FILES).
ALLOWED_ROOTS = [
    "tests/py",
    "tests/phase1",
    "tests/demo",
    "tests/sliceb",
    "tests/ps",
    "levers/powershell/*/tests",
    "site/tests",
]
TEST_PATTERNS = ["test_*.py", "*.Tests.ps1", "Test-*.ps1"]
# Test-looking files outside the roots that are not lost: path -> the file inside a root that runs it.
KNOWN_ORPHANS = {
    "levers/powershell/TenantBaseline/Test-SummaryReconciles.ps1": "tests/sliceb/Test-SliceB.ps1",
}
RUNNER_FILES = ["tests/py/Test-Py.ps1", "tests/ps/Test-Modules.ps1"]
RUNNER_GLOBS = [".github/workflows/*.yml", ".github/workflows/*.yaml"]


def list_test_files(root: Path) -> list[str]:
    """Test-looking files under root (git files plus untracked when it is a git tree), .venv excluded."""
    paths: list[str] = []
    git = shutil.which("git")
    if (root / ".git").exists() and git:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [git, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout
        paths = [p for p in out.split("\0") if p and (root / p).is_file()]
    else:
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in (".git", ".venv")]
            paths += [(Path(folder) / f).relative_to(root).as_posix() for f in files]
    found = []
    for p in paths:
        parts = p.replace("\\", "/").split("/")
        if ".venv" in parts:
            continue
        if any(fnmatch.fnmatchcase(parts[-1], pat) for pat in TEST_PATTERNS):
            found.append("/".join(parts))
    return sorted(found)


def is_under_root(path: str, root: str) -> bool:
    pattern = "^" + re.escape(root).replace(r"\*", "[^/]+") + "/"
    return re.match(pattern, path) is not None


def find_orphans(root: Path, known: dict[str, str] | None = None) -> list[str]:
    known = KNOWN_ORPHANS if known is None else known
    return [p for p in list_test_files(root) if p not in known and not any(is_under_root(p, r) for r in ALLOWED_ROOTS)]


def roots_missing_from_runners(roots: list[str], runner_texts: list[str]) -> list[str]:
    text = "\n".join(runner_texts).replace("\\", "/")
    missing = []
    for r in roots:
        # "*" also matches a placeholder such as <Module>; the lookahead keeps tests/py from matching tests/pytest.
        pattern = re.escape(r).replace(r"\*", r"(?:[^/\s]+|<[^>/]+>)") + r"(?![\w-])"
        if re.search(pattern, text) is None:
            missing.append(r)
    return missing


def _runner_texts() -> list[str]:
    paths = [REPO_ROOT / f for f in RUNNER_FILES]
    for g in RUNNER_GLOBS:
        paths += sorted(REPO_ROOT.glob(g))
    return [p.read_text(encoding="utf-8") for p in paths if p.is_file()]


def _touch(base: Path, rel: str) -> None:
    f = base / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# synthetic\n", encoding="utf-8")


def test_orphan_in_temp_tree_fails_naming_the_file(tmp_path: Path) -> None:
    _touch(tmp_path, "workflows/x/tests/test_a.py")
    _touch(tmp_path, "tests/py/tools/test_ok.py")
    _touch(tmp_path, "levers/powershell/Mod/tests/Mod.Tests.ps1")
    _touch(tmp_path, ".venv/lib/test_x.py")
    orphans = find_orphans(tmp_path)
    assert orphans == ["workflows/x/tests/test_a.py"]
    with pytest.raises(AssertionError, match=r"workflows/x/tests/test_a\.py"):
        assert not orphans, f"test files no runner collects: {orphans}"


def test_names_that_only_look_like_tests_are_ignored_and_an_empty_tree_is_clean(tmp_path: Path) -> None:
    assert find_orphans(tmp_path) == []
    _touch(tmp_path, "workflows/x/conftest.py")
    _touch(tmp_path, "workflows/x/testing_notes.md")
    assert find_orphans(tmp_path) == []


def test_real_repo_has_no_unlisted_orphans() -> None:
    orphans = find_orphans(REPO_ROOT)
    assert not orphans, f"test files outside every allowed root (move them or list them in KNOWN_ORPHANS): {orphans}"


def test_known_orphans_are_not_stale() -> None:
    for path, runner in KNOWN_ORPHANS.items():
        assert (REPO_ROOT / path).is_file(), f"{path} no longer exists; drop it from KNOWN_ORPHANS"
        assert not any(is_under_root(path, r) for r in ALLOWED_ROOTS), f"{path} is now inside a root; drop it"
        assert any(is_under_root(runner, r) for r in ALLOWED_ROOTS), f"{runner} is not inside a root"
        text = (REPO_ROOT / runner).read_text(encoding="utf-8")
        assert Path(path).name in text, f"{runner} does not mention {Path(path).name}"


def test_root_missing_from_every_runner_fails_naming_the_root() -> None:
    texts = ["pytest tests/pytest tests/py/x", "dir levers\\powershell\\<Module>\\tests"]
    assert roots_missing_from_runners(["tests/py", "levers/powershell/*/tests"], texts) == []
    assert roots_missing_from_runners(["tools/zzz"], texts) == ["tools/zzz"]
    # near miss: tests/pytest must not satisfy tests/phase
    assert roots_missing_from_runners(["tests/pyt"], ["tests/pytest"]) == ["tests/pyt"]
    with pytest.raises(AssertionError, match=r"tools/zzz"):
        missing = roots_missing_from_runners(["tools/zzz"], texts)
        assert not missing, f"roots named in no runner: {missing}"


def test_every_real_root_is_named_in_a_runner() -> None:
    missing = roots_missing_from_runners(ALLOWED_ROOTS, _runner_texts())
    assert not missing, f"roots named in no runner (Test-Py.ps1, a CI workflow, Test-Modules.ps1): {missing}"


def test_py_runner_prints_wall_time_summary(tmp_path: Path) -> None:
    runner = REPO_ROOT / "tests" / "py" / "Test-Py.ps1"
    assert 'Write-Host "Py tests: $pass passed, $fail failed in $secs s"' in runner.read_text(encoding="utf-8")
    pwsh, uv = shutil.which("pwsh"), shutil.which("uv")
    if not pwsh or not uv:
        pytest.skip("pwsh or uv not found")
    # A one-test folder: the default tests/py would run this test again, forever.
    one_test = tmp_path / "one" / "test_synthetic_ok.py"
    one_test.parent.mkdir(parents=True)
    one_test.write_text("def test_ok() -> None:\n    assert True\n", encoding="utf-8")
    done = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [pwsh, "-NoProfile", "-File", str(runner), "-TestPath", str(tmp_path / "one")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        cwd=REPO_ROOT,
    )
    lines = [ln.strip() for ln in done.stdout.splitlines()]
    assert any(re.fullmatch(r"Py tests: \d+ passed, 0 failed in \d+(\.\d+)? s", ln) for ln in lines), done.stdout[-800:]
