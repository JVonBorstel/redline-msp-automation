"""B-27 mypy strict across workflows, evals and ui (code side of DR-06).

Acceptance ids B27-1 and B27-2 are defined in specs/B-27.md. Offline: mypy and pytest run as child processes
on the committed tree; nothing touches the network.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/core/test_b27_mypy_strict.py
"""

from __future__ import annotations

import subprocess
import sys

from core.paths import REPO_ROOT


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
        [sys.executable, "-m", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )


def test_b27_1_mypy_strict_clean_on_workflows_evals_ui() -> None:
    result = _run("mypy", "--strict", "workflows", "evals", "ui")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Success: no issues found" in result.stdout


def test_b27_1_mypy_strict_clean_on_core_too() -> None:
    result = _run("mypy", "--strict", "core", "workflows", "evals", "ui")
    assert result.returncode == 0, result.stdout + result.stderr


def test_b27_2_phase1_suite_passes_unchanged() -> None:
    result = _run("pytest", "-p", "no:cacheprovider", "-q", "tests/phase1")
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-1000:]


def test_b27_2_demo_smoke_passes_unchanged() -> None:
    result = _run("pytest", "-p", "no:cacheprovider", "-q", "tests/demo/test_b10_demo_smoke.py")
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-1000:]
