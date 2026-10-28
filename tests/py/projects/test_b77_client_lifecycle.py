"""B-77 client lifecycle: discovery pack, offboarding runbook, migration pre-flight.

Acceptance ids B77-1 to B77-3 are defined in specs/B-77.md. Offline and deterministic; committed fixtures are only
read (a test hashes them before and after). The test that runs the real baseline skips without pwsh; the test that
runs the real B-61 reconciliation skips while workflows.device_reconcile is not on this branch.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/projects
"""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import workflows.client_lifecycle as pkg
import workflows.client_lifecycle.discovery as disc
import workflows.client_lifecycle.preflight as pre
from core.paths import REPO_ROOT
from workflows.client_lifecycle import DiscoveryError, PreflightError, discover, licence_report
from workflows.client_lifecycle.__main__ import main
from workflows.client_lifecycle.discovery import Context, body_sha256, load_config
from workflows.client_lifecycle.preflight import preflight

CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
PKG = Path(pkg.__file__).parent
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "client-offboarding.md"
HAS_PWSH = shutil.which("pwsh") is not None
HAS_B61 = disc._b61() is not None
AS_OF = "2026-10-01"


def _snapshot(*roots: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for root in roots:
        out.update({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()})
    return out


def _committed_inputs() -> tuple[Path, ...]:
    return REPO_ROOT / "fixtures" / "tenant", REPO_ROOT / "fixtures" / "graph", PKG / "data"


def _write(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _ok_step(name: str) -> Any:
    return lambda ctx: disc.StepOutcome(disc.Step(name, "ran", "stand-in", {}))


STAND_INS = {"baseline": _ok_step("baseline"), "devices": _ok_step("devices")}


# -- B77-1 -----------------------------------------------------------------------------------------------------------
@pytest.mark.skipif(not HAS_PWSH, reason="pwsh is not installed")
def test_b77_1_pack_runs_the_real_baseline_and_lists_gaps_read_only(tmp_path: Path) -> None:
    before = _snapshot(*_committed_inputs())
    pack = discover(CONTOSO, tmp_path, as_of=AS_OF)
    assert _snapshot(*_committed_inputs()) == before
    body = json.loads(pack.path.read_text(encoding="utf-8"))
    assert body["read_only"] is True and body["client"] == CONTOSO and body["as_of"] == AS_OF
    assert [s["name"] for s in body["steps"]] == ["baseline", "devices", "licences"]
    steps = {s["name"]: s for s in body["steps"]}
    assert steps["baseline"]["status"] == "ran" and steps["licences"]["status"] == "ran"
    sources = {g["source"] for g in body["gaps"]}
    assert {"baseline", "licences"} <= sources
    baseline = [g for g in body["gaps"] if g["source"] == "baseline"]
    assert baseline and all(g["next_step"].startswith(("proposal only:", "a person decides")) for g in baseline)
    assert body["gap_counts"] == {s: sum(g["severity"] == s for g in body["gaps"]) for s in ("High", "Medium", "Low")}
    assert len({g["id"] for g in body["gaps"]}) == len(body["gaps"])


@pytest.mark.skipif(not HAS_PWSH, reason="pwsh is not installed")
def test_b77_1_the_pack_is_deterministic_and_its_hash_verifies(tmp_path: Path) -> None:
    first = discover(FABRIKAM, tmp_path / "a", as_of=AS_OF).path.read_text(encoding="utf-8")
    second = discover(FABRIKAM, tmp_path / "b", as_of=AS_OF).path.read_text(encoding="utf-8")
    assert first == second
    body = json.loads(first)
    assert body["sha256"] == body_sha256(body)
    assert body["data_class"].startswith("DC-") and body["data_class_basis"]
    body["gaps"].append({"id": "X"})
    assert body["sha256"] != body_sha256(body)


def test_b77_1_licence_report_shows_seats_and_each_gap_kind() -> None:
    out = licence_report(CONTOSO, date.fromisoformat(AS_OF))
    assert out.step.status == "ran"
    seats = {s["sku"]: s for s in out.step.counts["seats"]}
    assert seats["O365_BUSINESS_PREMIUM"] == {"sku": "O365_BUSINESS_PREMIUM", "enabled": 6, "assigned": 6, "free": 0}
    assert seats["O365_BUSINESS_ESSENTIALS"]["free"] == 2
    by_id = {g.id: g for g in out.gaps}
    assert by_id["LIC-UNUSED-01"].severity == "Low"
    assert by_id["LIC-ORPHAN-01"].severity == "Medium" and "2026-09-15" in by_id["LIC-ORPHAN-01"].evidence
    assert by_id["LIC-ORPHAN-02"].severity == "Low"


def test_b77_1_licence_retention_window_depends_on_the_given_date_not_the_clock() -> None:
    inside = licence_report(CONTOSO, date(2026, 9, 1)).gaps
    after = licence_report(CONTOSO, date(2026, 10, 1)).gaps
    assert {g.severity for g in inside if g.id == "LIC-ORPHAN-01"} == {"Low"}
    assert {g.severity for g in after if g.id == "LIC-ORPHAN-01"} == {"Medium"}


def test_b77_1_licence_gap_kinds_over_assigned_disabled_unlicensed_unknown_sku(tmp_path: Path) -> None:
    c = "acme-test"
    _write(
        tmp_path / f"{c}.json",
        {
            "_meta": {"client": c},
            "users": [
                {"userPrincipalName": "a@acme.example", "accountEnabled": True},
                {"userPrincipalName": "b@acme.example", "accountEnabled": False},
                {"userPrincipalName": "c@acme.example", "accountEnabled": True},
            ],
        },
    )
    _write(
        tmp_path / c / "licenses.json",
        {
            "_meta": {"client": c},
            "skus": [{"skuId": "s1", "skuPartNumber": "SKU_ONE", "prepaidUnits": {"enabled": 1}}],
            "assignments": [
                {"userPrincipalName": "a@acme.example", "skuId": "s1"},
                {"userPrincipalName": "b@acme.example", "skuId": "s1"},
                {"userPrincipalName": "a@acme.example", "skuId": "s9", "skuPartNumber": "GONE"},
                {"userPrincipalName": "z@acme.example", "skuId": "s1"},
            ],
        },
    )
    out = licence_report(c, date.fromisoformat(AS_OF), tmp_path)
    kinds = {g.id.rsplit("-", 1)[0] for g in out.gaps}
    assert kinds == {"LIC-OVER", "LIC-UNKNOWNSKU", "LIC-ORPHAN", "LIC-DISABLED", "LIC-UNLICENSED"}
    over = next(g for g in out.gaps if g.id.startswith("LIC-OVER"))
    assert over.severity == "High" and over.evidence == "enabled=1; assigned=3"
    orphan = next(g for g in out.gaps if g.id.startswith("LIC-ORPHAN"))
    assert "no retention window" in orphan.evidence


def test_b77_1_missing_licence_data_is_a_high_gap_not_an_all_clear(tmp_path: Path) -> None:
    out = licence_report("litware-legal", date.fromisoformat(AS_OF))
    assert out.step.status == "not-run"
    assert [(g.id, g.severity) for g in out.gaps] == [("DISC-LICENCES", "High")]
    empty = licence_report(CONTOSO, date.fromisoformat(AS_OF), tmp_path)
    assert empty.step.status == "not-run" and empty.gaps[0].severity == "High"


def _edge_report(tmp_path: Path, skus: list[Any], assignments: list[Any], users: list[Any]) -> disc.StepOutcome:
    c = "edge-test"
    _write(tmp_path / f"{c}.json", {"_meta": {"client": c}, "users": users})
    _write(tmp_path / c / "licenses.json", {"_meta": {"client": c}, "skus": skus, "assignments": assignments})
    return licence_report(c, date.fromisoformat(AS_OF), tmp_path)


def test_b77_1_a_bad_retention_date_is_a_high_gap_and_never_aborts_the_pack(tmp_path: Path) -> None:
    sku = {"skuId": "s1", "skuPartNumber": "SKU_ONE", "prepaidUnits": {"enabled": 5}}
    users = [{"userPrincipalName": "a@acme.example", "accountEnabled": True}]
    assigned = [
        {"userPrincipalName": "gone@acme.example", "skuId": "s1", "retentionEndsOn": "next tuesday"},
        {"userPrincipalName": "a@acme.example", "skuId": "s1"},
        {"userPrincipalName": "gone2@acme.example", "skuId": "s1", "retentionEndsOn": "2026-09-15"},
    ]
    out = _edge_report(tmp_path, [sku], assigned, users)
    assert out.step.status == "ran"
    bad = [g for g in out.gaps if g.id.startswith("LIC-BADDATE")]
    assert [(g.severity, g.subject) for g in bad] == [("High", "gone@acme.example")]
    assert any(g.id.startswith("LIC-ORPHAN") and g.subject == "gone2@acme.example" for g in out.gaps)
    # through the whole pack: the run completes and writes the pack
    steps = {**STAND_INS, "licences": lambda ctx: licence_report("edge-test", ctx.as_of, tmp_path)}
    pack = discover("edge-test", tmp_path / "pack", as_of=AS_OF, steps=steps)
    assert pack.path.is_file() and any(g.id.startswith("LIC-BADDATE") for g in pack.gaps)


def test_b77_1_unknown_seat_counts_are_a_gap_not_a_false_over_assignment(tmp_path: Path) -> None:
    skus = [
        {"skuId": "s1", "skuPartNumber": "NO_UNITS", "prepaidUnits": {}},
        {"skuId": "s2", "skuPartNumber": "NO_BLOCK"},
        {"skuId": "s3", "skuPartNumber": "TEXT", "prepaidUnits": {"enabled": "many"}},
        {"skuId": "s4", "skuPartNumber": "NEGATIVE", "prepaidUnits": {"enabled": -3}},
        {"skuId": "s5", "skuPartNumber": "FLAG", "prepaidUnits": {"enabled": True}},
        {"skuId": "s6", "skuPartNumber": "FINE", "prepaidUnits": {"enabled": 2}},
    ]
    assigned = [
        {"userPrincipalName": f"u{i}@acme.example", "skuId": sid}
        for i, sid in enumerate(("s1", "s2", "s3", "s4", "s5"))
    ]
    out = _edge_report(tmp_path, skus, assigned, [])
    assert out.step.status == "ran"
    assert not any(g.id.startswith("LIC-OVER") for g in out.gaps)
    unknown = {g.subject: g for g in out.gaps if g.id.startswith("LIC-SEATS")}
    assert set(unknown) == {"NO_UNITS", "NO_BLOCK", "TEXT", "NEGATIVE", "FLAG"}
    assert all(g.severity == "High" and "unknown" in g.title for g in unknown.values())
    seats = {s["sku"]: s for s in out.step.counts["seats"]}
    assert seats["NO_UNITS"]["enabled"] is None and seats["NO_UNITS"]["free"] is None
    assert seats["FINE"] == {"sku": "FINE", "enabled": 2, "assigned": 0, "free": 2}


def test_b77_1_missing_account_state_or_user_name_is_a_gap_not_a_guess(tmp_path: Path) -> None:
    sku = {"skuId": "s1", "skuPartNumber": "SKU_ONE", "prepaidUnits": {"enabled": 5}}
    users = [
        {"userPrincipalName": "nostate@acme.example"},
        {"userPrincipalName": "ok@acme.example", "accountEnabled": True},
        {"displayName": "nameless"},
    ]
    assigned = [{"userPrincipalName": "ok@acme.example", "skuId": "s1"}, {"skuId": "s1"}]
    out = _edge_report(tmp_path, [sku], assigned, users)
    ids = [g.id.rsplit("-", 1)[0] for g in out.gaps]
    assert "LIC-ACCOUNTSTATE" in ids and "LIC-NOUPN" in ids
    state = next(g for g in out.gaps if g.id.startswith("LIC-ACCOUNTSTATE"))
    assert state.subject == "nostate@acme.example" and state.severity == "Medium"
    assert not any(g.id.startswith("LIC-UNLICENSED") for g in out.gaps)  # unknown state is not "enabled"
    assert all("None" not in g.subject for g in out.gaps)


def test_b77_1_a_licence_file_for_another_client_is_refused(tmp_path: Path) -> None:
    _write(tmp_path / CONTOSO / "licenses.json", {"_meta": {"client": FABRIKAM}, "skus": [], "assignments": []})
    _write(tmp_path / f"{CONTOSO}.json", {"_meta": {"client": CONTOSO}, "users": []})
    out = licence_report(CONTOSO, date.fromisoformat(AS_OF), tmp_path)
    assert out.step.status == "failed" and "does not belong to this client" in out.step.reason
    assert out.gaps[0].severity == "High"


def test_b77_1_a_step_that_did_not_run_is_listed_as_a_high_gap(tmp_path: Path) -> None:
    bad = {"devices": lambda ctx: disc._not_run("devices", "no data")}
    pack = discover(CONTOSO, tmp_path, as_of=AS_OF, steps={"baseline": STAND_INS["baseline"], **bad})
    assert [s.status for s in pack.steps] == ["ran", "not-run", "ran"]
    assert any(g.id == "DISC-DEVICES" and g.severity == "High" for g in pack.gaps)


def test_b77_1_baseline_without_pwsh_is_not_run_and_a_gap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(disc.shutil, "which", lambda _name: None)
    ctx = Context(CONTOSO, date.fromisoformat(AS_OF), tmp_path, tmp_path, load_config())
    out = disc.run_baseline(ctx)
    assert out.step.status == "not-run" and out.gaps[0].id == "DISC-BASELINE"


def test_b77_1_baseline_failure_text_never_copies_child_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        assert kw["env"]["B77_TENANT"] == CONTOSO and "contoso" not in argv[-1]  # values arrive as environment values
        return subprocess.CompletedProcess(argv, 1, "", "error for tenant fabrikam-capital secret-xyz")

    monkeypatch.setattr(disc.subprocess, "run", fake_run)
    ctx = Context(CONTOSO, date.fromisoformat(AS_OF), tmp_path, tmp_path, load_config(), pwsh="pwsh-stand-in")
    out = disc.run_baseline(ctx)
    assert out.step.status == "failed"
    assert "fabrikam" not in out.step.reason and "secret" not in out.step.reason


def test_b77_1_baseline_timeout_is_failed_not_clear(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: list[str], **kw: Any) -> Any:
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    monkeypatch.setattr(disc.subprocess, "run", fake_run)
    ctx = Context(CONTOSO, date.fromisoformat(AS_OF), tmp_path, tmp_path, load_config(), pwsh="pwsh-stand-in")
    out = disc.run_baseline(ctx)
    assert out.step.status == "failed" and out.gaps[0].severity == "High"


def test_b77_1_baseline_child_environment_holds_no_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def fake_run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        seen.update(kw["env"])
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setenv("GRAPH_CLIENT_SECRET", "do-not-pass")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "do-not-pass")
    monkeypatch.setattr(disc.subprocess, "run", fake_run)
    disc.run_baseline(Context(CONTOSO, date.fromisoformat(AS_OF), tmp_path, tmp_path, load_config(), pwsh="x"))
    assert seen and "do-not-pass" not in seen.values()


def _fake_b61(findings: list[Any], *, fail: bool = False) -> dict[str, Any]:
    class Err(Exception):
        pass

    class Mock:
        as_of = "2026-10-01T00:00:00Z"

        @classmethod
        def for_fixture(cls, client: str) -> Mock:
            if fail:
                raise OSError("no fixture")
            return cls()

    def reconcile(*_a: Any) -> Any:
        return SimpleNamespace(findings=findings, counts=lambda: {"devices": 3})

    return {
        "reconcile": reconcile,
        "load_config": lambda: None,
        "utc": lambda s: s,
        "errors": (Err,),
        "rmm": Mock,
        "intune": Mock,
        "psa": Mock,
    }


def test_b77_1_device_mismatches_become_gaps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    found = [
        SimpleNamespace(type="only-in-one-system", system="rmm", device="PC-1", detail="not in intune"),
        SimpleNamespace(type="stale", system="intune", device="PC-2", detail="old"),
        SimpleNamespace(type="duplicate", system="psa", device="PC-3", detail="twice"),
    ]
    monkeypatch.setattr(disc, "_b61", lambda: _fake_b61(found))
    ctx = Context(CONTOSO, date.fromisoformat(AS_OF), tmp_path, tmp_path, load_config())
    out = disc.run_devices(ctx)
    assert out.step.status == "ran"
    assert [(g.id, g.severity) for g in out.gaps] == [
        ("DEV-ONLYONE-01", "Medium"),
        ("DEV-STALE-01", "Low"),
        ("DEV-DUP-01", "Medium"),
    ]
    assert all("nothing is changed" in g.next_step for g in out.gaps)


def test_b77_1_device_step_without_b61_or_data_is_not_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = Context(CONTOSO, date.fromisoformat(AS_OF), tmp_path, tmp_path, load_config())
    monkeypatch.setattr(disc, "_b61", lambda: None)
    assert disc.run_devices(ctx).step.status == "not-run"
    monkeypatch.setattr(disc, "_b61", lambda: _fake_b61([], fail=True))
    out = disc.run_devices(ctx)
    assert out.step.status == "not-run" and out.gaps[0].id == "DISC-DEVICES"


@pytest.mark.skipif(not HAS_B61, reason="workflows.device_reconcile (B-61) is not on this branch")
def test_b77_1_real_b61_reconciliation_feeds_the_pack(tmp_path: Path) -> None:
    ctx = Context(CONTOSO, date.fromisoformat(AS_OF), tmp_path, tmp_path, load_config())
    out = disc.run_devices(ctx)
    assert out.step.status == "ran"
    assert [(g.id, g.severity, g.subject) for g in out.gaps] == [
        ("DEV-ONLYONE-01", "Medium", "serial:CD-0005-LT"),
        ("DEV-ONLYONE-02", "Medium", "serial:CD-0006-RC"),
        ("DEV-ONLYONE-03", "Medium", "serial:CD-0009-SP"),
        ("DEV-ONLYONE-04", "Medium", "serial:CD-0010-CS"),
        ("DEV-ONLYONE-05", "Medium", "serial:CD-0099-XX"),
        ("DEV-STALE-01", "Low", "serial:CD-0006-RC"),
        ("DEV-STALE-02", "Low", "serial:CD-0007-OM"),
        ("DEV-STALE-03", "Low", "serial:CD-0008-HY"),
        ("DEV-DUP-01", "Medium", "serial:CD-0008-HY"),
    ]
    counts = out.step.counts
    assert counts["findings"] == {"only-in-one-system": 5, "stale": 3, "duplicate": 1}
    assert (counts["High"], counts["Medium"], counts["Low"]) == (0, 6, 3)
    assert counts["devices"] == 11 and counts["in_all_three"] == 4
    # staleness is measured against the RMM snapshot's own time, not --as-of (specs/B-77.md)
    assert counts["as_of"] == "2026-10-22T12:00:00Z" != AS_OF


@pytest.mark.skipif(not HAS_B61, reason="workflows.device_reconcile (B-61) is not on this branch")
def test_b77_1_real_b61_clean_client_has_no_device_gaps(tmp_path: Path) -> None:
    ctx = Context(FABRIKAM, date.fromisoformat(AS_OF), tmp_path, tmp_path, load_config())
    out = disc.run_devices(ctx)
    assert out.step.status == "ran" and out.gaps == ()
    assert out.step.counts["devices"] == 4 and out.step.counts["in_all_three"] == 3


def test_b77_1_device_step_not_run_path_with_stand_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = Context(CONTOSO, date.fromisoformat(AS_OF), tmp_path, tmp_path, load_config())
    monkeypatch.setattr(disc, "_b61", lambda: None)
    out = disc.run_devices(ctx)
    assert out.step.status == "not-run" and out.step.reason == disc.NOT_ON_BRANCH
    assert [(g.id, g.severity) for g in out.gaps] == [("DISC-DEVICES", "High")]


def test_b77_1_bad_input_is_refused_before_anything_runs(tmp_path: Path) -> None:
    for bad in ("../x", "Contoso", "", "a b"):
        with pytest.raises(DiscoveryError):
            discover(bad, tmp_path, as_of=AS_OF, steps=STAND_INS)
    with pytest.raises(DiscoveryError):
        discover(CONTOSO, tmp_path, as_of="01/10/2026", steps=STAND_INS)
    with pytest.raises(DiscoveryError):
        discover(CONTOSO, tmp_path, as_of=AS_OF, steps={"nonsense": _ok_step("x")})
    assert not list(tmp_path.iterdir())


def test_b77_1_config_rejects_unknown_keys(tmp_path: Path) -> None:
    cfg = json.loads((PKG / "config.json").read_text(encoding="utf-8"))
    _write(tmp_path / "ok.json", cfg)
    assert load_config(tmp_path / "ok.json").baseline_timeout_s == cfg["baseline_timeout_s"]
    _write(tmp_path / "extra.json", {**cfg, "execute": True})
    with pytest.raises(DiscoveryError):
        load_config(tmp_path / "extra.json")
    with pytest.raises(DiscoveryError):
        load_config(tmp_path / "missing.json")


def test_b77_1_discover_cli_prints_json_and_exits_2_on_bad_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(disc.shutil, "which", lambda _name: None)
    assert main(["discover", "--client", FABRIKAM, "--as-of", AS_OF, "--out", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["read_only"] is True and {s["name"] for s in out["steps"]} == {"baseline", "devices", "licences"}
    assert any(g["id"] == "DISC-BASELINE" for g in out["gaps"])
    assert main(["discover", "--client", "Bad Id", "--out", str(tmp_path)]) == 2
    assert main(["discover", "--client", FABRIKAM, "--as-of", "nope", "--out", str(tmp_path)]) == 2
    assert "error:" in capsys.readouterr().err


# -- B77-2 -----------------------------------------------------------------------------------------------------------
def test_b77_2_runbook_covers_credentials_gdap_and_documentation() -> None:
    text = RUNBOOK.read_text(encoding="utf-8").lower()
    for needle in ("hand back credentials", "remove gdap", "export documentation", "confirm in writing", "break-glass"):
        assert needle in text, needle
    assert text.index("export documentation") < text.index("hand back credentials") < text.index("remove gdap")
    assert "none-keep-human" in text and "w-prj-02" in text
    assert "unverified" in text
    assert "synthetic" in text and "not affiliated" in text


def test_b77_2_runbook_names_roles_and_holds_no_secret_or_personal_contact() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "@" not in text and "password:" not in text.lower()
    assert "names roles, never people" in text
    assert "http://" not in text and "https://" not in text


def test_b77_2_nothing_in_offboarding_is_automated() -> None:
    registry = (REPO_ROOT / "levers" / "registry.json").read_text(encoding="utf-8").lower()
    assert "offboard-client" not in registry and "gdap" not in registry and "client.offboard" not in registry
    # the only commands are the two read-only ones
    for command in ("offboard", "gdap-remove", "hand-back"):
        with pytest.raises(SystemExit):
            main([command, "--client", CONTOSO])
    names = {n.name.lower() for n in ast.walk(_package_tree()) if isinstance(n, ast.FunctionDef)}
    assert not {n for n in names if any(w in n for w in ("offboard", "gdap", "remove", "revoke", "delete"))}
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "no lever, no workflow command and no queue entry" in text


def _package_tree() -> ast.Module:
    body: list[ast.stmt] = []
    for f in sorted(PKG.glob("*.py")):
        body.extend(ast.parse(f.read_text(encoding="utf-8")).body)
    return ast.Module(body=body, type_ignores=[])


# -- B77-3 -----------------------------------------------------------------------------------------------------------
def _plan(client: str = CONTOSO, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "_meta": {"client": client, "family": "migration-plan", "note": "synthetic test plan"},
        "version": 1,
        "client": client,
        "kind": "mailbox-move",
        "mailboxes": ["ana.lopez@contosodental.example", "tom.baker@contosodental.example"],
        "destination": {
            "label": "test",
            "domain": "dest.example",
            "mailbox_quota_gb": 50,
            "licence": {"skuPartNumber": "SKU_T", "enabled": 5, "assigned": 1},
            "addresses_in_use": [],
        },
    }
    base.update(over)
    return base


def test_b77_3_contoso_fails_each_check_with_every_problem_listed() -> None:
    before = _snapshot(*_committed_inputs())
    result = preflight(CONTOSO)
    assert _snapshot(*_committed_inputs()) == before
    assert result.ready is False
    checks = {c.name: c for c in result.checks}
    assert list(checks) == ["mailbox-sizes", "licence-availability", "conflicting-addresses"]
    assert all(c.status == "fail" for c in checks.values())
    assert checks["mailbox-sizes"].problems == (
        "sam.patel@contosodental.example is 21 GB, over the destination quota of 20 GB",
    )
    assert checks["mailbox-sizes"].counts["total_gb"] == 60.2
    assert (
        "6 user mailboxes" in checks["licence-availability"].problems[0]
        and "1 short" in checks["licence-availability"].problems[0]
    )
    assert checks["licence-availability"].counts["shared_mailboxes"] == 1
    assert "UNVERIFIED" in checks["licence-availability"].counts["shared_note"]
    assert "jamie.chen@contosodentalgroup.example" in checks["conflicting-addresses"].problems[0]


def test_b77_3_the_clean_twin_passes_every_check() -> None:
    result = preflight(FABRIKAM)
    assert result.ready is True and all(c.status == "pass" and not c.problems for c in result.checks)
    out = result.to_dict()
    assert out["read_only"] is True and "NN-04" in out["execution"]


def test_b77_3_all_problems_are_listed_not_only_the_first(tmp_path: Path) -> None:
    plan = _plan(
        mailboxes=[
            "ana.lopez@contosodental.example",
            "sam.patel@contosodental.example",
            "jamie.chen@contosodental.example",
        ],
    )
    plan["destination"]["mailbox_quota_gb"] = 9
    plan["destination"]["licence"] = {"skuPartNumber": "SKU_T", "enabled": 1, "assigned": 1}
    plan["destination"]["addresses_in_use"] = ["Ana.Lopez@dest.example", "jamie.chen@dest.example"]
    result = preflight(CONTOSO, _write(tmp_path / "p.json", plan))
    checks = {c.name: c for c in result.checks}
    assert len(checks["mailbox-sizes"].problems) == 3
    assert len(checks["conflicting-addresses"].problems) == 2  # case-insensitive match


def test_b77_3_two_mailboxes_mapping_to_one_destination_address_conflict(tmp_path: Path) -> None:
    mail = {
        "_meta": {"client": "dup-test"},
        "mailboxes": [
            {"userPrincipalName": "a@one.example", "recipientTypeDetails": "UserMailbox", "totalItemSizeGb": 1},
            {"userPrincipalName": "a@two.example", "recipientTypeDetails": "UserMailbox", "totalItemSizeGb": 1},
        ],
    }
    _write(tmp_path / "dup-test" / "mailboxes.json", mail)
    plan = _plan("dup-test", mailboxes=["a@one.example", "a@two.example"])
    result = preflight("dup-test", _write(tmp_path / "p.json", plan), tenant_dir=tmp_path)
    problems = {c.name: c.problems for c in result.checks}["conflicting-addresses"]
    assert problems == ("a@dest.example is the destination address of 2 planned mailboxes",)


def test_b77_3_shared_and_other_mailboxes_do_not_take_a_user_seat(tmp_path: Path) -> None:
    mail = {
        "_meta": {"client": "seat-test"},
        "mailboxes": [
            {"userPrincipalName": "u@x.example", "recipientTypeDetails": "UserMailbox", "totalItemSizeGb": 1},
            {"userPrincipalName": "s@x.example", "recipientTypeDetails": "SharedMailbox", "totalItemSizeGb": 1},
            {"userPrincipalName": "r@x.example", "recipientTypeDetails": "RoomMailbox", "totalItemSizeGb": 1},
        ],
    }
    _write(tmp_path / "seat-test" / "mailboxes.json", mail)
    plan = _plan("seat-test", mailboxes=["u@x.example", "s@x.example", "r@x.example"])
    plan["destination"]["licence"] = {"skuPartNumber": "SKU_T", "enabled": 1, "assigned": 0}
    result = preflight("seat-test", _write(tmp_path / "p.json", plan), tenant_dir=tmp_path)
    lic = {c.name: c for c in result.checks}["licence-availability"]
    assert lic.status == "pass" and lic.counts["user_mailboxes"] == 1
    assert lic.counts["shared_mailboxes"] == 1 and lic.counts["other_mailboxes"] == 1


def test_b77_3_a_planned_mailbox_of_another_client_is_reported_by_position_only(tmp_path: Path) -> None:
    plan = _plan(mailboxes=["ana.lopez@contosodental.example", "morgan.reyes@fabrikamcapital.example"])
    result = preflight(CONTOSO, _write(tmp_path / "p.json", plan))
    sizes = {c.name: c for c in result.checks}["mailbox-sizes"]
    assert sizes.status == "fail" and sizes.problems == ("planned mailbox #2 is not in this client's mailbox list",)
    assert "fabrikam" not in json.dumps(result.to_dict()).lower()


def test_b77_3_a_plan_for_another_client_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PreflightError, match="not for this client"):
        preflight(CONTOSO, PKG / "data" / "migrations" / f"{FABRIKAM}.json")
    wrong_meta = _plan()
    wrong_meta["_meta"]["client"] = FABRIKAM
    with pytest.raises(PreflightError, match="not for this client"):
        preflight(CONTOSO, _write(tmp_path / "m.json", wrong_meta))


def test_b77_3_mailbox_data_of_another_client_is_refused(tmp_path: Path) -> None:
    _write(tmp_path / CONTOSO / "mailboxes.json", {"_meta": {"client": FABRIKAM}, "mailboxes": []})
    with pytest.raises(PreflightError, match="does not belong"):
        preflight(CONTOSO, tenant_dir=tmp_path)
    with pytest.raises(PreflightError, match="no mailbox data"):
        preflight(CONTOSO, tenant_dir=tmp_path / "empty")


def test_b77_3_bad_or_unknown_plans_are_refused(tmp_path: Path) -> None:
    with pytest.raises(PreflightError, match="no migration plan"):
        preflight("litware-legal")
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(PreflightError, match="unreadable"):
        preflight(CONTOSO, tmp_path / "bad.json")
    with pytest.raises(PreflightError, match="not valid"):
        preflight(CONTOSO, _write(tmp_path / "extra.json", _plan(execute=True)))
    with pytest.raises(PreflightError, match="not valid"):
        preflight(CONTOSO, _write(tmp_path / "empty.json", _plan(mailboxes=[])))
    with pytest.raises(DiscoveryError):
        preflight("../etc")


def _mail_tenant(tmp_path: Path, client: str, boxes: list[dict[str, Any]]) -> Path:
    _write(tmp_path / client / "mailboxes.json", {"_meta": {"client": client}, "mailboxes": boxes})
    return tmp_path


def _box(upn: str, kind: Any = "UserMailbox", size: Any = 1) -> dict[str, Any]:
    box: dict[str, Any] = {"userPrincipalName": upn}
    if kind is not None:
        box["recipientTypeDetails"] = kind
    if size is not None:
        box["totalItemSizeGb"] = size
    return box


def test_b77_3_a_missing_mailbox_size_is_a_problem_and_not_ready(tmp_path: Path) -> None:
    tenant = _mail_tenant(tmp_path, "size-test", [_box("a@x.example"), _box("b@x.example", size=None)])
    plan = _plan("size-test", mailboxes=["a@x.example", "b@x.example"])
    result = preflight("size-test", _write(tmp_path / "p.json", plan), tenant_dir=tenant)
    sizes = {c.name: c for c in result.checks}["mailbox-sizes"]
    assert sizes.status == "fail" and result.ready is False
    assert sizes.problems == ("b@x.example has no size recorded, so it cannot be checked against the quota",)
    assert sizes.counts["unknown_size"] == 1


@pytest.mark.parametrize("bad", ["big", True, -2, float("nan"), float("inf"), [1]])
def test_b77_3_an_invalid_mailbox_size_is_refused_like_other_bad_input(tmp_path: Path, bad: Any) -> None:
    tenant = _mail_tenant(tmp_path, "size-test", [_box("a@x.example", size=bad)])
    plan = _plan("size-test", mailboxes=["a@x.example"])
    with pytest.raises(PreflightError, match="size"):
        preflight("size-test", _write(tmp_path / "p.json", plan), tenant_dir=tenant)


def test_b77_3_a_mailbox_with_no_recipient_type_is_flagged_and_takes_a_seat(tmp_path: Path) -> None:
    tenant = _mail_tenant(tmp_path, "type-test", [_box("a@x.example"), _box("b@x.example", kind=None)])
    plan = _plan("type-test", mailboxes=["a@x.example", "b@x.example"])
    plan["destination"]["licence"] = {"skuPartNumber": "SKU_T", "enabled": 1, "assigned": 0}
    result = preflight("type-test", _write(tmp_path / "p.json", plan), tenant_dir=tenant)
    lic = {c.name: c for c in result.checks}["licence-availability"]
    assert lic.status == "fail" and result.ready is False
    assert any("b@x.example has no recipient type" in p for p in lic.problems)
    assert any("1 short" in p for p in lic.problems)  # counted as needing a seat: 2 need, 1 free
    assert lic.counts["user_mailboxes"] == 1 and lic.counts["unknown_type_mailboxes"] == 1
    assert lic.counts["other_mailboxes"] == 0


def test_b77_3_destination_over_assignment_is_reported_apart_from_a_seat_shortfall(tmp_path: Path) -> None:
    tenant = _mail_tenant(tmp_path, "over-test", [_box("s@x.example", kind="SharedMailbox")])
    plan = _plan("over-test", mailboxes=["s@x.example"])
    plan["destination"]["licence"] = {"skuPartNumber": "SKU_T", "enabled": 3, "assigned": 5}
    result = preflight("over-test", _write(tmp_path / "p.json", plan), tenant_dir=tenant)
    lic = {c.name: c for c in result.checks}["licence-availability"]
    assert lic.status == "fail"
    assert len(lic.problems) == 1 and "over-assigned" in lic.problems[0] and "2 more" in lic.problems[0]
    assert not any("-2" in p or "need" in p for p in lic.problems)
    assert lic.counts["free"] == 0 and lic.counts["over_assigned"] == 2


def test_b77_3_over_assignment_and_a_shortfall_are_two_problems(tmp_path: Path) -> None:
    tenant = _mail_tenant(tmp_path, "over-test", [_box("a@x.example"), _box("b@x.example")])
    plan = _plan("over-test", mailboxes=["a@x.example", "b@x.example"])
    plan["destination"]["licence"] = {"skuPartNumber": "SKU_T", "enabled": 3, "assigned": 5}
    result = preflight("over-test", _write(tmp_path / "p.json", plan), tenant_dir=tenant)
    problems = {c.name: c for c in result.checks}["licence-availability"].problems
    assert len(problems) == 2 and "2 user mailboxes need a SKU_T seat and 0 are free; 2 short" in problems[1]


def test_b77_3_the_package_does_not_shadow_the_preflight_submodule() -> None:
    assert pkg.preflight is pre  # the attribute is the submodule; the function is exported as run_preflight
    assert pkg.run_preflight is pre.preflight and callable(pkg.run_preflight)


def test_b77_3_committed_plans_are_synthetic_and_use_reserved_domains() -> None:
    for plan in sorted((PKG / "data" / "migrations").glob("*.json")):
        data = json.loads(plan.read_text(encoding="utf-8"))
        assert "synthetic" in data["_meta"]["note"].lower()
        assert data["destination"]["domain"].endswith(".example")
        assert all(a.endswith(".example") for a in data["destination"]["addresses_in_use"] + data["mailboxes"])


def test_b77_3_preflight_cli_prints_json_and_exits_2_on_bad_input(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["preflight", "--client", CONTOSO]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ready"] is False and out["read_only"] is True
    assert main(["preflight", "--client", FABRIKAM]) == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True
    assert main(["preflight", "--client", "litware-legal"]) == 2
    assert main(["preflight", "--client", "Bad Id"]) == 2
    assert "error:" in capsys.readouterr().err


def test_b77_3_there_is_no_execute_path_and_execution_stays_not_now() -> None:
    with pytest.raises(SystemExit):
        main(["execute", "--client", CONTOSO])
    with pytest.raises(SystemExit):
        main(["migrate", "--client", CONTOSO])
    public = {n for n in dir(pkg) if not n.startswith("_")}
    assert not {n for n in public if any(w in n.lower() for w in ("execute", "migrate", "move", "apply"))}
    roadmap = json.loads((REPO_ROOT / "map" / "roadmap.json").read_text(encoding="utf-8"))
    nn04 = next(n for n in roadmap["not_now"] if n["id"] == "NN-04")
    assert "Executing" in nn04["what"] and "W-PRJ-03" in nn04["inventory_ids"]
    assert pre.NOT_NOW == "NN-04" and "NN-04" in pre.EXECUTION


# -- supporting: read-only by construction, item hygiene --------------------------------------------------------------
FORBIDDEN_PREFIXES = (
    "core.levers.runner",
    "core.queue",
    "core.approval",
    "levers",
    "ui",
    "workflows.notify",
    "requests",
    "httpx",
    "urllib",
    "socket",
)
FORBIDDEN_NAMES = {
    "LeverRunner",
    "Registry",
    "Approval",
    "AuditLog",
    "ProposalStore",
    "ProposalQueue",
    "invoke",
    "propose",
}


def _imports(path: Path) -> list[str]:
    out: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module)
    return out


def test_b77_the_package_imports_no_runner_queue_audit_writer_or_network() -> None:
    for f in sorted(PKG.glob("*.py")):
        for imported in _imports(f):
            assert not any(imported == p or imported.startswith(p + ".") for p in FORBIDDEN_PREFIXES), (
                f.name,
                imported,
            )
        tree = ast.parse(f.read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
        }
        assert not names & FORBIDDEN_NAMES, (f.name, names & FORBIDDEN_NAMES)


def test_b77_the_roadmap_item_and_the_spec_agree_on_acceptance_and_ownership() -> None:
    roadmap = json.loads((REPO_ROOT / "map" / "roadmap.json").read_text(encoding="utf-8"))
    item = next(i for w in roadmap["waves"] for i in w["items"] if i["id"] == "B-77")
    spec = (REPO_ROOT / "specs" / "B-77.md").read_text(encoding="utf-8")
    for line in item["acceptance"]:
        assert line.split(":", 1)[0] in spec
    for k in (1, 2, 3):
        assert any(f"test_b77_{k}_" in t for t in _own_test_names())
    for owned in item["owns"]:
        assert (REPO_ROOT / owned).exists(), owned
    assert {"W-PRJ-01", "W-PRJ-02", "W-PRJ-03"} == set(item["inventory_ids"])


def _own_test_names() -> list[str]:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    return [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
