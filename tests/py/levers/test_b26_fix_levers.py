"""B-26 drift fixes (specs/B-26.md): one proposal contract, canonical TenantBaseline ids, fix levers accounted for.

B26-1  triage takes proposal_id, Source and the UTC clock from core.queue (DR-01); the contract test is unchanged.
B26-2  TenantBaseline accepts -Tenant contoso-dental and keeps contoso and clean as aliases (DR-05); demo command works.
B26-3  every fix lever in the config is registered or explicitly planned (DR-10); the manifest says 7.4 (DR-09);
       SB-1 to SB-4 pass.

Synthetic fixtures only. The PowerShell tests run a local pwsh (no network) and skip when pwsh is not installed.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import core.queue.store as queue_store
import workflows.triage.proposal as triage_proposal
from core.queue import Proposal

ROOT = Path(__file__).resolve().parents[3]
MODULE_DIR = ROOT / "levers" / "powershell" / "TenantBaseline"
CONFIG = MODULE_DIR / "TenantBaseline.config.json"
MANIFEST = MODULE_DIR / "TenantBaseline.psd1"
PSM1 = MODULE_DIR / "TenantBaseline.psm1"
PWSH = shutil.which("pwsh")
needs_pwsh = pytest.mark.skipif(PWSH is None, reason="pwsh is not installed")


def _config() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(CONFIG.read_text(encoding="utf-8"))
    return data


def _pwsh(script: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    assert PWSH is not None
    return subprocess.run(  # noqa: S603 - fixed local pwsh, script text built in this file
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _report(tenant: str) -> dict[str, Any]:
    done = _pwsh(
        f"Import-Module '{MANIFEST}' -Force; "
        f"Get-TenantBaselineReport -Tenant '{tenant}' | ConvertTo-Json -Depth 8 -Compress"
    )
    assert done.returncode == 0, done.stderr
    data: dict[str, Any] = json.loads(done.stdout)
    return data


# --- B26-1 -------------------------------------------------------------------------------------------------------


def test_b26_1_triage_uses_the_queue_definitions() -> None:
    assert triage_proposal.proposal_id is queue_store.proposal_id
    assert triage_proposal.Source is queue_store.Source
    assert triage_proposal.utc_stamp is queue_store.utc_now


def test_b26_1_proposal_module_defines_no_second_contract() -> None:
    tree = ast.parse((ROOT / "workflows" / "triage" / "proposal.py").read_text(encoding="utf-8"))
    defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef | ast.ClassDef)}
    assigned = {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    imported = {(n.module, a.name) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "proposal_id" not in defined and "Source" not in assigned
    assert ("core.queue.store", "proposal_id") in imported and ("core.queue.store", "Source") in imported
    assert ("core.queue.store", "utc_now") in imported
    assert not any(isinstance(n, ast.Import) and any(a.name == "hashlib" for a in n.names) for n in ast.walk(tree))


def test_b26_1_make_proposal_is_a_valid_queue_proposal() -> None:
    created = datetime(2026, 10, 1, 9, 30, tzinfo=timezone(timedelta(hours=-6)))
    params = {"upn": "dana.lopez@contosodental.example", "reason": "left the practice"}
    p = triage_proposal.make_proposal(
        source="triage",
        ref="T-1001",
        lever="user.disable",
        client="contoso-dental",
        params=params,
        requested_by="tech-tara",
        reason="T-1001 triaged as offboarding:\n user.disable",
        created=created,
    )
    assert list(p) == [
        "id",
        "source",
        "ref",
        "lever",
        "client",
        "params",
        "requested_by",
        "reason",
        "created",
        "status",
        "decided_by",
        "decided_at",
        "approver_auth",  # W2 integration: B-89 records how the approver signed in
    ]
    assert p["approver_auth"] is None
    assert p["id"] == queue_store.proposal_id("user.disable", "contoso-dental", params)
    assert p["created"] == "2026-10-01T15:30:00Z" and p["reason"] == "T-1001 triaged as offboarding: user.disable"
    assert (p["status"], p["decided_by"], p["decided_at"]) == ("pending", None, None)
    assert Proposal(**p).id == p["id"]


def test_b26_1_make_proposal_refuses_what_the_queue_would_refuse() -> None:
    kwargs: dict[str, Any] = {
        "source": "triage",
        "ref": "T-1",
        "lever": "user.disable",
        "client": "contoso-dental",
        "params": {"upn": "a@contosodental.example"},
        "requested_by": "tech-tara",
        "reason": "r",
        "created": datetime(2026, 10, 1, tzinfo=UTC),
    }
    with pytest.raises(ValueError, match="timezone-aware"):
        triage_proposal.make_proposal(**{**kwargs, "created": datetime(2026, 10, 1)})  # noqa: DTZ001
    with pytest.raises(ValueError):
        triage_proposal.make_proposal(**{**kwargs, "requested_by": "Not A Slug"})
    with pytest.raises(ValueError):
        triage_proposal.make_proposal(**{**kwargs, "source": "email"})


def test_b26_1_utc_now_is_aware_utc() -> None:
    now = triage_proposal.utc_now()
    assert now.utcoffset() == timedelta(0)
    assert abs((datetime.now(UTC) - now).total_seconds()) < 5


def test_b26_1_the_contract_test_is_still_there() -> None:
    text = (ROOT / "tests" / "phase1" / "test_triage.py").read_text(encoding="utf-8")
    assert "def test_proposals_follow_the_shared_contract(" in text
    assert "def test_proposal_id_ignores_key_order_but_not_the_client(" in text


# --- B26-2 -------------------------------------------------------------------------------------------------------


def test_b26_2_tenants_are_keyed_by_canonical_client_ids() -> None:
    tenants = _config()["tenants"]
    canonical = {p.stem for p in (ROOT / "fixtures" / "tenant").glob("*.json")}
    assert set(tenants) <= canonical, set(tenants) - canonical
    assert set(tenants) == {"contoso-dental", "fabrikam-capital"}
    aliases = [a for t in tenants.values() for a in t.get("aliases", [])]
    assert sorted(aliases) == ["clean", "contoso"]
    assert not set(aliases) & set(tenants), "an alias must not shadow a canonical id"
    for key, info in tenants.items():
        assert (ROOT / "fixtures" / "graph" / info.get("fixtureDir", key)).is_dir(), key


@needs_pwsh
@pytest.mark.parametrize(
    ("tenant", "client", "name", "total"),
    [
        ("contoso-dental", "contoso-dental", "Contoso Dental", 14),
        ("contoso", "contoso-dental", "Contoso Dental", 14),
        ("fabrikam-capital", "fabrikam-capital", "Fabrikam Capital", 0),
        ("clean", "fabrikam-capital", "Fabrikam Capital", 0),
    ],
)
def test_b26_2_canonical_id_and_aliases_give_the_same_report(tenant: str, client: str, name: str, total: int) -> None:
    report = _report(tenant)
    assert (report["tenant"], report["tenantDisplayName"], report["counts"]["total"]) == (client, name, total)


@needs_pwsh
def test_b26_2_unknown_tenant_is_refused() -> None:
    done = _pwsh(f"Import-Module '{MANIFEST}' -Force; Get-TenantBaselineReport -Tenant 'northwind' | Out-Null")
    assert done.returncode != 0 and "Unknown tenant 'northwind'" in done.stderr + done.stdout


@needs_pwsh
def test_b26_2_the_demo_command_still_works(tmp_path: Path) -> None:
    demo = (ROOT / "docs" / "DEMO.md").read_text(encoding="utf-8")
    lines = [ln for ln in demo.splitlines() if "Invoke-TenantBaseline -Tenant" in ln and ln.startswith("pwsh ")]
    assert len(lines) == 1, lines
    m = re.search(r'-Command "(?P<cmd>.*)"$', lines[0])
    assert m is not None
    out = tmp_path / "baseline"
    cmd = re.sub(r"-OutDir \S+", lambda _: f"-OutDir '{out}'", m.group("cmd"))
    done = _pwsh(cmd)
    assert done.returncode == 0, done.stderr
    report = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    assert report["tenant"] == "contoso-dental" and report["counts"]["total"] == 14
    for f in ("findings.csv", "report.html", "summary.txt"):
        assert (out / f).is_file()


# --- B26-3 -------------------------------------------------------------------------------------------------------


def test_b26_3_every_fix_lever_is_registered_or_planned() -> None:
    cfg = _config()
    registered = {
        lv["name"] for lv in json.loads((ROOT / "levers" / "registry.json").read_text(encoding="utf-8"))["levers"]
    }
    planned = set(cfg["plannedFixLevers"])
    named = {v for v in cfg["fixLevers"].values() if v}
    assert named, "the config names fix levers"
    assert named <= registered | planned, named - registered - planned
    assert not planned & registered, f"registered levers must leave the planned list: {planned & registered}"
    assert planned <= named, f"planned levers nothing names: {planned - named}"
    assert "user.disable" in named & registered


def test_b26_3_manifest_and_module_declare_powershell_7_4() -> None:
    manifest = MANIFEST.read_text(encoding="utf-8")
    assert re.search(r"^\s*PowerShellVersion\s*=\s*'7\.4'\s*$", manifest, re.MULTILINE)
    assert PSM1.read_text(encoding="utf-8").splitlines()[0].strip() == "#requires -Version 7.4"


@needs_pwsh
def test_b26_3_slice_b_suite_passes() -> None:
    done = _pwsh(f"& '{ROOT / 'tests' / 'sliceb' / 'Test-SliceB.ps1'}'; exit $LASTEXITCODE", timeout=300)
    m = re.search(r"SliceB tests: (\d+) passed, (\d+) failed", done.stdout)
    assert m is not None, done.stdout[-2000:]
    assert done.returncode == 0 and int(m.group(2)) == 0 and int(m.group(1)) > 0, done.stdout[-2000:]
