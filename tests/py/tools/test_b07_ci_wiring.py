"""B-07 CI wiring, checked offline against this repository's own workflow (.github/workflows/ci.yml). Runs nothing.

The promise that matters: every push and pull request runs lint, types, the Python suites, the PowerShell suites and
the demo smoke test, the Bicep templates compile, the container runs the demo, and the token stays read-only.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/tools/test_b07_ci_wiring.py
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CI = REPO / ".github" / "workflows" / "ci.yml"


def _ci() -> str:
    assert CI.is_file(), ".github/workflows/ci.yml is missing"
    return CI.read_text(encoding="utf-8")


def test_b07_1_ci_runs_the_roadmap_item_tests_and_the_demo_smoke_test() -> None:
    text = _ci()
    for needed in (
        "ruff check",
        "ruff format --check",
        "mypy --strict",
        "tests/phase1",
        "tests/demo/Test-Demo.ps1",
        "tests/ps/Test-Modules.ps1",
        "tests/sliceb/Test-SliceB.ps1",
    ):
        assert needed in text, f"CI does not run {needed}"
    assert re.search(r"uv run --frozen pytest\b[^\n]*\btests/py\b", text), "CI does not run pytest over tests/py"
    assert "runs-on: windows-latest" in text, "the PowerShell suites need a Windows runner"


def test_b07_1_ci_compiles_the_infrastructure_and_runs_the_container() -> None:
    text = _ci()
    assert "az bicep build" in text and "az bicep lint" in text
    assert "docker compose build" in text and "run --rm demo" in text


def test_b07_1_every_action_is_pinned_to_a_full_commit_sha() -> None:
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", _ci(), flags=re.M)
    assert uses, "no actions found in ci.yml"
    loose = [u for u in uses if not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", u)]
    assert not loose, f"actions not pinned to a 40-character commit SHA: {loose}"


def test_b07_1_the_token_stays_read_only() -> None:
    text = _ci()
    assert re.search(r"^permissions:\s*\n\s+contents:\s*read\s*$", text, flags=re.M), "top-level permissions changed"
    assert not re.search(r":\s*write\b", text), "a job asks for a write permission"
    assert "persist-credentials: false" in text
