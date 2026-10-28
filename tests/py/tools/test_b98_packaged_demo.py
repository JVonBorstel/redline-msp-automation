"""B-98 packaged demo and README tests (specs/B-98.md: B98-1 to B98-3, B98-9). Offline, synthetic, no network.

`uv run --frozen python tools/packaged_demo.py` runs the end-to-end path (triage, injection flag, runner denials,
verified approval, notice draft, pause, audit verify, tamper detection) into a fresh state folder and prints a short
transcript. The smoke test here runs it as a user would and checks each marker, the time budget and that nothing
outside the given state folder changed.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/tools/test_b98_packaged_demo.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DEMO = REPO / "tools" / "packaged_demo.py"
README = REPO / "README.md"
LABEL = "Independently built prototype. Not affiliated with any vendor's or real company's systems."
T3101 = "P-d01c53bdf1dc"
BUDGET_S = 120


def _run(*args: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, local interpreter, repo script
        [sys.executable, str(DEMO), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO,
        timeout=timeout,
        check=False,
    )


@pytest.fixture(scope="module")
def ran(tmp_path_factory: pytest.TempPathFactory) -> tuple[subprocess.CompletedProcess[str], Path, float, set[str]]:
    state = tmp_path_factory.mktemp("packaged") / "state"
    repo_tmp = REPO / ".tmp"
    before = {p.as_posix() for p in repo_tmp.rglob("*")} if repo_tmp.exists() else set()
    start = time.monotonic()
    done = _run("--state", str(state))
    seconds = time.monotonic() - start
    after = {p.as_posix() for p in repo_tmp.rglob("*")} if repo_tmp.exists() else set()
    return done, state, seconds, after - before


# -- B98-1: one command, a short transcript ------------------------------------------------------------------------


def test_b98_1_one_command_exits_zero_and_every_step_passes(
    ran: tuple[subprocess.CompletedProcess[str], Path, float, set[str]],
) -> None:
    done, _, _, _ = ran
    assert done.returncode == 0, done.stdout + done.stderr
    steps = re.findall(r"^\[(\d+)/(\d+)\] .*$", done.stdout, re.M)
    assert len(steps) >= 8 and {total for _, total in steps} == {str(len(steps))}
    assert done.stdout.count("  PASS") == len(steps)
    assert "FAIL" not in done.stdout
    assert re.search(rf"Packaged demo: {len(steps)} of {len(steps)} steps passed", done.stdout)


def test_b98_1_transcript_shows_the_whole_story_in_order(
    ran: tuple[subprocess.CompletedProcess[str], Path, float, set[str]],
) -> None:
    out = ran[0].stdout
    markers = [
        LABEL,
        f"queued: {T3101} (pending)",
        "Before approval: call back on the number on file",
        "Injection check: FLAGGED",
        "needs a lead approval record",
        "needs a recorded requester verification (C-30)",
        f"{T3101} executed",
        "Draft. A person reviews and sends this.",
        "lever paused by lead-lee",
        "OK: ",
        "BROKEN at seq",
        "fixture-based",
        "Not run here",
    ]
    last = -1
    for marker in markers:
        at = out.find(marker, last + 1)
        assert at > last, f"{marker!r} is missing or out of order in the transcript"
        last = at


def test_b98_1_transcript_is_short(ran: tuple[subprocess.CompletedProcess[str], Path, float, set[str]]) -> None:
    lines = ran[0].stdout.splitlines()
    assert 20 <= len(lines) <= 90, len(lines)
    assert all(len(line) <= 160 for line in lines)


# -- B98-2: offline, bounded, contained ----------------------------------------------------------------------------


def test_b98_2_finishes_inside_the_budget(ran: tuple[subprocess.CompletedProcess[str], Path, float, set[str]]) -> None:
    assert ran[2] < BUDGET_S, f"{ran[2]:.1f} s"


def test_b98_2_writes_only_under_the_given_state_folder(
    ran: tuple[subprocess.CompletedProcess[str], Path, float, set[str]],
) -> None:
    _, state, _, new_in_repo_tmp = ran
    assert not new_in_repo_tmp, sorted(new_in_repo_tmp)
    assert (state / "queue.jsonl").is_file() and (state / "audit" / "contoso-dental.jsonl").is_file()
    assert (state / "notices" / f"{T3101}.md").is_file()


def test_b98_2_tamper_step_works_on_a_copy_and_the_real_chain_stays_intact(
    ran: tuple[subprocess.CompletedProcess[str], Path, float, set[str]],
) -> None:
    _, state, _, _ = ran
    check = subprocess.run(  # noqa: S603 - fixed argv, local interpreter, repo module
        [sys.executable, "-m", "core.audit.verify", str(state / "audit" / "contoso-dental.jsonl")],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert check.returncode == 0, check.stdout + check.stderr
    assert "OK:" in check.stdout


def test_b98_2_refuses_a_state_folder_that_already_has_content(tmp_path: Path) -> None:
    (tmp_path / "old.txt").write_text("x", encoding="utf-8")
    done = _run("--state", str(tmp_path))
    assert done.returncode == 2
    assert "not empty" in (done.stdout + done.stderr)


def test_b98_2_without_state_it_makes_its_own_temp_folder(tmp_path: Path) -> None:
    done = _run("--list-steps")
    assert done.returncode == 0
    assert len([line for line in done.stdout.splitlines() if line.strip()]) >= 8


def test_b98_2_no_network_or_install_commands_in_the_script() -> None:
    text = DEMO.read_text(encoding="utf-8")
    for banned in ("urllib", "requests", "http.client", "socket", "pip install", "uv add", "uv pip", "curl", "docker"):
        assert banned not in text, banned


# -- B98-3: container files ----------------------------------------------------------------------------------------


def test_b98_3_container_files_exist_and_stay_loopback_and_offline() -> None:
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    compose = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    assert "tools/packaged_demo.py" in compose and "tools/packaged_demo.py" in dockerfile
    assert "--frozen" in dockerfile
    assert "0.0.0.0" not in compose and "0.0.0.0" not in dockerfile  # noqa: S104 - asserting absence
    assert "ports:" not in compose or "127.0.0.1:" in compose
    assert 'network_mode: "none"' in compose or "network_mode: none" in compose
    assert "USER " in dockerfile  # not root


# -- B98-9: the README ---------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


def test_b98_9_readme_keeps_the_label_and_the_phase0_phrases(readme: str) -> None:
    assert LABEL in readme
    for phrase in ("At a glance", "Not proven"):
        assert phrase in readme, phrase
    assert "no security review by anyone outside it" in readme


def test_b98_9_readme_has_the_sections_the_roadmap_asks_for(readme: str) -> None:
    headings = re.findall(r"^#{1,3} (.+)$", readme, re.M)
    joined = " | ".join(headings).lower()
    for needed in (
        "what this is",
        "architecture",
        "real and what is mock",
        "packaged demo",
        "test suites",
        "roadmap status",
    ):
        assert needed in joined, needed
    for needed in ("limits", "trade-offs", "adapting"):
        assert needed in joined, needed


def test_b98_9_readme_makes_no_employer_or_production_claims(readme: str) -> None:
    lowered = readme.lower()
    for banned in ("in production at", "soc 2 certified", "hipaa compliant"):
        assert banned not in lowered, banned
    assert not re.search(r"\b\d+(\.\d+)?\s?% (faster|reduction|fewer|less|improvement|saving)", lowered)
    assert "nothing here has been used in production" in lowered or "not used in production" in lowered


def test_b98_9_readme_real_versus_mock_table_is_a_table_with_known_words(readme: str) -> None:
    rows = [
        line for line in readme.splitlines() if re.match(r"^\| [^|]+ \| (Real|Mock|Document-only|Not built)\b", line)
    ]
    assert len(rows) >= 10
    assert {re.match(r"^\| [^|]+ \| (\w[\w-]*)", r).group(1) for r in rows} >= {"Real", "Mock", "Document-only"}  # type: ignore[union-attr]
    assert any("Not built" in line for line in rows)


def test_b98_9_every_path_and_command_in_the_readme_exists(readme: str) -> None:
    for rel in sorted(
        set(re.findall(r"\b((?:tools|tests|docs|scripts|governance|levers|workflows)/[\w./-]+\.\w+)", readme))
    ):
        assert (REPO / rel).exists(), rel
    for module in sorted(set(re.findall(r"python -m ([\w.]+)", readme))):
        assert (REPO / Path(*module.split("."))).exists() or (REPO / Path(*module.split("."))).with_suffix(
            ".py"
        ).exists(), module


def test_b98_9_readme_commands_name_the_packaged_demo_and_both_gates(readme: str) -> None:
    assert "uv run --frozen python tools/packaged_demo.py" in readme
    assert "uv run --frozen python tools/coverage_audit.py" in readme
    assert "tests/demo/Test-Demo.ps1" in readme and "tests/sliceb/Test-SliceB.ps1" in readme
