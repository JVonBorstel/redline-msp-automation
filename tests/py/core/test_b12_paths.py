"""B-12 repo paths, gateway and guard drift, config version field (DR-07, DR-08, DR-14).

Acceptance ids B12-1 to B12-3 are defined in specs/B-12.md. Every test is offline: config is read from the
committed files or from private copies under tmp_path, and the gateway runs on the mock provider only.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/core
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from core.gateway import Gateway, GatewayConfig
from core.gateway.config import CONFIG_VERSION, MODELS_FILE, ROUTING_FILE
from core.paths import REPO_ROOT

GATEWAY_AND_GUARD = sorted(
    [*(REPO_ROOT / "core" / "gateway").glob("*.py"), *(REPO_ROOT / "core" / "guard").glob("*.py")]
)


def _copy_config(tmp_path: Path) -> Path:
    """A private repo-shaped root with the committed gateway config and mock fixture."""
    root = tmp_path / "repo"
    for rel in (MODELS_FILE, ROUTING_FILE, Path("fixtures/gateway/mock_responses.json")):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / rel, root / rel)
    return root


def _set_version(root: Path, rel: Path, version: Any) -> None:
    path = root / rel
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = version
    path.write_text(json.dumps(data), encoding="utf-8")


# --- B12-1: REPO_ROOT is the default root -------------------------------------------------------------------------


def test_b12_1_repo_root_is_the_repository_not_the_working_directory() -> None:
    assert REPO_ROOT.is_absolute()
    assert (REPO_ROOT / "core" / "paths.py").is_file()
    assert (REPO_ROOT / MODELS_FILE).is_file()
    assert (REPO_ROOT / ROUTING_FILE).is_file()
    assert (REPO_ROOT / "pyproject.toml").is_file()


def test_b12_1_loader_defaults_to_repo_root() -> None:
    config = GatewayConfig.load()
    assert config.root == REPO_ROOT
    assert config == GatewayConfig.load(REPO_ROOT)
    assert config.mock_fixture_path == REPO_ROOT / "fixtures" / "gateway" / "mock_responses.json"


def test_b12_1_running_from_another_directory_loads_the_same_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = GatewayConfig.load(REPO_ROOT)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    config = GatewayConfig.load()
    assert config == expected
    completion = Gateway(config).complete("classify", "Locked out after MFA reset")
    assert completion.ok
    assert completion == Gateway(expected).complete("classify", "Locked out after MFA reset").model_copy(
        update={"ms": completion.ms}
    )


def test_b12_1_cli_run_from_another_directory_uses_the_repo_config(tmp_path: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    result = subprocess.run(
        [sys.executable, "-m", "core.gateway", "classify", "Locked out after MFA reset"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    completion = json.loads(result.stdout)
    assert completion["ok"] is True
    assert completion["provider"] == "mock"


def test_b12_1_an_explicit_root_still_wins(tmp_path: Path) -> None:
    root = _copy_config(tmp_path)
    config = GatewayConfig.load(root)
    assert config.root == root
    assert config.mock_fixture_path == root / "fixtures" / "gateway" / "mock_responses.json"


# --- B12-2: from __future__ import annotations, no behaviour change ----------------------------------------------


def _first_statement_after_docstring(path: Path) -> ast.stmt:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = tree.body
    assert body, f"{path.name}: empty module"
    assert isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant), f"{path.name}: no docstring"
    assert len(body) > 1, f"{path.name}: nothing after the docstring"
    return body[1]


def test_b12_2_the_module_list_is_the_one_dr14_names() -> None:
    names = {p.relative_to(REPO_ROOT).as_posix() for p in GATEWAY_AND_GUARD}
    for required in (
        "core/gateway/base.py",
        "core/gateway/config.py",
        "core/gateway/gateway.py",
        "core/gateway/hosted.py",
        "core/gateway/loopback.py",
        "core/gateway/mock.py",
        "core/gateway/ollama.py",
        "core/guard/wrap.py",
        "core/guard/detect.py",
    ):
        assert required in names


@pytest.mark.parametrize("path", GATEWAY_AND_GUARD, ids=lambda p: p.relative_to(REPO_ROOT).as_posix())
def test_b12_2_every_gateway_and_guard_module_has_future_annotations(path: Path) -> None:
    statement = _first_statement_after_docstring(path)
    assert isinstance(statement, ast.ImportFrom), f"{path.name}: first statement is not the __future__ import"
    assert statement.module == "__future__"
    assert [alias.name for alias in statement.names] == ["annotations"]


def test_b12_2_paths_module_has_future_annotations() -> None:
    statement = _first_statement_after_docstring(REPO_ROOT / "core" / "paths.py")
    assert isinstance(statement, ast.ImportFrom) and statement.module == "__future__"


def test_b12_2_p1_7_and_p1_8_still_pass() -> None:
    """The Phase 1 injection (P1-7) and gateway (P1-8) tests run unchanged against the edited modules."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=",
            "tests/phase1/test_guard.py",
            "tests/phase1/test_gateway.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert " passed" in result.stdout
    assert " failed" not in result.stdout


# --- B12-3: version field -----------------------------------------------------------------------------------------


def test_b12_3_version_one_is_accepted(tmp_path: Path) -> None:
    root = _copy_config(tmp_path)
    _set_version(root, MODELS_FILE, 1)
    _set_version(root, ROUTING_FILE, 1)
    config = GatewayConfig.load(root)
    assert CONFIG_VERSION == 1
    assert config.version == 1
    assert config.resolve("classify") == GatewayConfig.load(REPO_ROOT).resolve("classify")


@pytest.mark.parametrize("bad", [0, 2, -1, "1", True, 1.0, None, [1]], ids=repr)
@pytest.mark.parametrize("rel", [MODELS_FILE, ROUTING_FILE], ids=lambda p: p.name)
def test_b12_3_any_other_version_is_rejected(tmp_path: Path, rel: Path, bad: Any) -> None:
    root = _copy_config(tmp_path)
    _set_version(root, rel, bad)
    with pytest.raises(ValueError, match="version"):
        GatewayConfig.load(root)


@pytest.mark.parametrize("bad", [0, 2, "1", True, 1.0], ids=repr)
def test_b12_3_the_model_itself_rejects_other_versions(bad: Any) -> None:
    data = GatewayConfig.load(REPO_ROOT).model_dump()
    data["version"] = bad
    with pytest.raises(ValidationError):
        GatewayConfig.model_validate(data)


def test_b12_3_a_bad_version_in_one_file_is_rejected_even_when_the_other_is_good(tmp_path: Path) -> None:
    root = _copy_config(tmp_path)
    _set_version(root, MODELS_FILE, 1)
    _set_version(root, ROUTING_FILE, 2)
    with pytest.raises(ValueError, match="routing.json"):
        GatewayConfig.load(root)


def test_b12_3_absent_version_is_still_accepted_until_owner_wiring(tmp_path: Path) -> None:
    """DR-07 tracked: the committed files have no version yet. When the owner adds it, this test flips."""
    committed = [json.loads((REPO_ROOT / rel).read_text(encoding="utf-8")) for rel in (MODELS_FILE, ROUTING_FILE)]
    root = _copy_config(tmp_path)
    assert GatewayConfig.load(root).version is None
    if all("version" in doc for doc in committed):
        assert GatewayConfig.load(REPO_ROOT).version == 1
    else:
        assert GatewayConfig.load(REPO_ROOT).version in (None, 1)


def test_b12_3_one_file_versioned_and_the_other_absent_is_accepted(tmp_path: Path) -> None:
    root = _copy_config(tmp_path)
    _set_version(root, MODELS_FILE, 1)
    assert GatewayConfig.load(root).version == 1
