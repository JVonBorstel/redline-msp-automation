"""B-63 software deployment from an approved catalog and third-party update review.

Acceptance ids B63-1 to B63-3 are defined in specs/B-63.md. Every test is offline and works on committed fixtures
(read only) or private copies under tmp_path. Run: uv run --frozen pytest -p no:cacheprovider tests/py/devices
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from adapters.rmm import RmmMock
from core.audit import AuditLog, verify_chain
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, Approval, LeverRunner, MockTenant, Registry
from core.levers.schema import validate_params
from levers.python.software import (
    DEFAULT_CATALOG,
    DEFAULT_INSTALLED,
    CatalogError,
    load_catalog,
    propose_updates,
)
from workflows.notify import TEMPLATES_DIR, missing_templates

REPO = Path(__file__).resolve().parents[3]
CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
LEVER = "device.install-app"
DEVICE = "c0000000-0000-4000-8000-0000000d0002"
INSTALL = {"device_uid": DEVICE, "package_id": "7zip"}
FAB_DEVICE = "f0000000-0000-4000-8000-0000000d0001"


def _raw(path: Path = DEFAULT_CATALOG) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


@pytest.fixture
def runner(tmp_path: Path) -> LeverRunner:
    shutil.copytree(DEFAULT_TENANT_DIR, tmp_path / "tenant")
    return LeverRunner(
        Registry.load(), IdentityStore.load(), MockTenant(tmp_path / "tenant"), AuditLog(tmp_path / "audit.jsonl")
    )


def _approval(params: dict[str, Any], client: str = CONTOSO) -> Approval:
    return Approval(approver="lead-lee", lever=LEVER, client=client, params=params, verification=None)


def _chain_ok(tmp_path: Path) -> bool:
    return verify_chain(tmp_path / "audit.jsonl", tmp_path / "audit.jsonl.head").ok


def _review(client: str, installed: Path = DEFAULT_INSTALLED, catalog_path: Path = DEFAULT_CATALOG) -> Any:
    return propose_updates(client, RmmMock.for_fixture(client), catalog=load_catalog(catalog_path), installed=installed)


def _tmp_catalog(tmp_path: Path, mutate: Any) -> Path:
    data = _raw()
    mutate(data)
    out = tmp_path / "catalog.json"
    out.write_text(json.dumps(data), encoding="utf-8")
    return out


# -- B63-1 the catalog and device.install-app (R2) ---------------------------------------------------------------


def test_b63_1_every_catalog_entry_is_versioned_and_hash_pinned_and_the_hash_re_derives() -> None:
    catalog = load_catalog()
    assert len(catalog.packages) >= 5
    for package in catalog.packages.values():
        assert re.fullmatch(r"[0-9]+(\.[0-9]+)*", package.version)
        assert re.fullmatch(r"[0-9a-f]{64}", package.sha256)
        derived = hashlib.sha256(f"synthetic-installer:{package.id}:{package.version}".encode()).hexdigest()
        assert package.sha256 == derived


def test_b63_1_a_bad_catalog_is_refused_whole(tmp_path: Path) -> None:
    def no_hash(d: dict[str, Any]) -> None:
        del d["packages"][0]["sha256"]

    def short_hash(d: dict[str, Any]) -> None:
        d["packages"][0]["sha256"] = "abc123"

    def no_version(d: dict[str, Any]) -> None:
        d["packages"][0]["version"] = "latest"

    def duplicate(d: dict[str, Any]) -> None:
        d["packages"].append(dict(d["packages"][0]))

    def unknown_approved(d: dict[str, Any]) -> None:
        d["clients"][CONTOSO]["approved"].append("not-in-catalog")

    def extra_field(d: dict[str, Any]) -> None:
        d["packages"][0]["silent_args"] = "/S && calc"

    def bad_id(d: dict[str, Any]) -> None:
        d["packages"][0]["id"] = "7zip; rm"

    for mutate in (no_hash, short_hash, no_version, duplicate, unknown_approved, extra_field, bad_id):
        with pytest.raises(CatalogError):
            load_catalog(_tmp_catalog(tmp_path, mutate))
    with pytest.raises(CatalogError):
        load_catalog(tmp_path / "missing.json")


def test_b63_1_the_registry_enum_is_the_catalog_and_the_lever_is_a_registered_r2_write_lever() -> None:
    registry = Registry.load()
    spec = registry.get(LEVER)
    assert spec is not None
    assert (spec.lever_class, spec.risk_class, spec.approval, spec.dry_run) == ("write", "R2", "lead", True)
    assert spec.dry_run_role is not None and spec.dry_run_role.value == "agent"
    assert spec.required_role.value == "technician"
    assert spec.impact is not None
    enum = spec.params["package_id"].enum
    assert enum is not None and set(enum) == set(load_catalog().packages)
    assert (TEMPLATES_DIR / "device.install-app.md").is_file()
    assert missing_templates(registry) == []


def test_b63_1_an_unknown_package_is_refused_before_any_handler_runs(runner: LeverRunner, tmp_path: Path) -> None:
    path = tmp_path / "tenant" / f"{CONTOSO}.json"
    before = path.read_bytes()
    for bad in (
        {"device_uid": DEVICE, "package_id": "evil-installer"},
        {"device_uid": DEVICE, "package_id": "https://example.invalid/setup.exe"},
        {"device_uid": DEVICE, "package_id": "7zip", "url": "https://example.invalid/x.msi"},
        {"device_uid": "not-a-uid", "package_id": "7zip"},
        {"device_uid": DEVICE},
        {},
    ):
        for mode in ("dry-run", "execute"):
            result = runner.invoke(LEVER, bad, identity="tech-ana", client=CONTOSO, mode=mode)
            assert not result.ok, (bad, mode)
    assert path.read_bytes() == before


def test_b63_1_a_package_the_client_has_not_approved_is_refused_even_though_it_is_in_the_catalog(
    runner: LeverRunner, tmp_path: Path
) -> None:
    only_contoso = {"device_uid": FAB_DEVICE, "package_id": "dental-imaging-viewer"}
    result = runner.invoke(LEVER, only_contoso, identity="triage-bot", client=FABRIKAM)
    assert not result.ok and result.status == "error" and "approved" in result.reason
    only_fabrikam = {"device_uid": DEVICE, "package_id": "vlc"}
    result = runner.invoke(LEVER, only_fabrikam, identity="triage-bot", client=CONTOSO)
    assert not result.ok and result.status == "error"
    assert _chain_ok(tmp_path)


def test_b63_1_dry_run_shows_the_pinned_version_and_hash_as_an_agent_and_saves_nothing(
    runner: LeverRunner, tmp_path: Path
) -> None:
    path = tmp_path / "tenant" / f"{CONTOSO}.json"
    before = path.read_bytes()
    result = runner.invoke(LEVER, INSTALL, identity="triage-bot", client=CONTOSO)
    assert result.ok and result.mode == "dry-run" and not result.applied
    assert [(c.op, c.path) for c in result.diff] == [("add", "/softwareInstallRequests")]
    package = load_catalog().packages["7zip"]
    assert result.diff[0].after == {
        f"{DEVICE}:7zip": {
            "package_id": "7zip",
            "version": package.version,
            "sha256": package.sha256,
            "status": "requested",
        }
    }
    assert path.read_bytes() == before
    assert _chain_ok(tmp_path)


def test_b63_1_executing_needs_a_technician_and_a_leads_approval_bound_to_device_and_package(
    runner: LeverRunner, tmp_path: Path
) -> None:
    path = tmp_path / "tenant" / f"{CONTOSO}.json"
    before = path.read_bytes()
    other = _approval({**INSTALL, "package_id": "firefox-esr"})
    for who, approval in (("triage-bot", None), ("tech-ana", None), ("tech-ana", other)):
        denied = runner.invoke(LEVER, INSTALL, identity=who, client=CONTOSO, mode="execute", approval=approval)
        assert denied.status == "denied" and path.read_bytes() == before
    ok = _approval(INSTALL)
    done = runner.invoke(LEVER, INSTALL, identity="tech-ana", client=CONTOSO, mode="execute", approval=ok)
    assert done.ok and done.applied and done.approver == "lead-lee"
    state = json.loads(path.read_text(encoding="utf-8"))
    assert list(state["softwareInstallRequests"]) == [f"{DEVICE}:7zip"]
    again = runner.invoke(LEVER, INSTALL, identity="tech-ana", client=CONTOSO, mode="execute", approval=ok)
    assert again.ok and not again.applied and again.diff == ()  # one request however often it is asked
    assert _chain_ok(tmp_path)


def test_b63_1_the_other_clients_tenant_is_never_touched(runner: LeverRunner, tmp_path: Path) -> None:
    other = tmp_path / "tenant" / f"{FABRIKAM}.json"
    before = other.read_bytes()
    ok = _approval(INSTALL)
    runner.invoke(LEVER, INSTALL, identity="tech-ana", client=CONTOSO, mode="execute", approval=ok)
    assert other.read_bytes() == before
    denied = runner.invoke(LEVER, INSTALL, identity="tech-ana", client=FABRIKAM, mode="execute", approval=ok)
    assert denied.status == "denied" and other.read_bytes() == before


def test_b63_1_the_template_says_what_changed_and_how_to_undo() -> None:
    text = (TEMPLATES_DIR / "device.install-app.md").read_text(encoding="utf-8")
    assert "$approver" in text and "$request" in text and "$first_name" in text
    assert "undo" in text.lower() and "approved" in text.lower()


# -- B63-2 third-party updates proposed per ring with the device count -------------------------------------------


def test_b63_2_contoso_updates_are_proposed_per_ring_with_the_device_count() -> None:
    review = _review(CONTOSO)
    got = {(p.ring, p.package_id): tuple(sorted(u[-4:] for u in p.device_uids)) for p in review.proposals}
    assert got == {
        ("pilot", "7zip"): ("0002",),
        ("pilot", "firefox-esr"): ("0002",),
        ("broad", "7zip"): ("0004", "0005", "0007", "0008"),
        ("broad", "adobe-reader"): ("0004",),
        ("broad", "dental-imaging-viewer"): ("0004",),
        ("broad", "notepadpp"): ("0006",),
        ("broad", "firefox-esr"): ("0006",),
    }
    assert {(p.ring, p.package_id): p.device_count for p in review.proposals}[("broad", "7zip")] == 4
    assert sum(p.device_count for p in review.proposals) == 10
    rings = [p.ring for p in review.proposals]
    assert rings == sorted(rings, key=["pilot", "broad"].index)  # the pilot ring is listed first
    assert all(p.after_ring == ("pilot" if p.ring == "broad" else None) for p in review.proposals)


def test_b63_2_each_proposal_carries_the_pinned_version_and_hash_from_the_catalog() -> None:
    catalog = load_catalog()
    for p in _review(CONTOSO).proposals:
        assert (p.version, p.sha256) == (catalog.packages[p.package_id].version, catalog.packages[p.package_id].sha256)


def test_b63_2_a_device_already_at_the_version_or_newer_is_not_proposed_and_the_review_is_idempotent() -> None:
    review = _review(CONTOSO)
    proposed = {(u[-4:], p.package_id) for p in review.proposals for u in p.device_uids}
    assert ("0001", "7zip") not in proposed and ("0001", "adobe-reader") not in proposed  # at the version
    assert ("0006", "7zip") not in proposed  # newer than the catalog: never downgraded
    kinds = {(f.device_uid[-4:], f.package_id): f.kind for f in review.findings}
    assert kinds[("0006", "7zip")] == "newer-than-catalog"
    assert kinds[("0009", "7zip")] == "unreadable-version"
    assert kinds[("0003", "7zip")] == "held" and kinds[("0003", "firefox-esr")] == "held"
    assert kinds[("0005", "legacy-pdf-tool")] == "not-approved"
    assert review == _review(CONTOSO)


def test_b63_2_once_every_device_is_at_the_version_nothing_is_proposed(tmp_path: Path) -> None:
    catalog = load_catalog()
    data = _raw(DEFAULT_INSTALLED)
    for dev in data["clients"][CONTOSO]["devices"].values():
        for package_id in dev["installed"]:
            if package_id in catalog.packages:
                dev["installed"][package_id] = catalog.packages[package_id].version
    patched = tmp_path / "installed.json"
    patched.write_text(json.dumps(data), encoding="utf-8")
    assert _review(CONTOSO, installed=patched).proposals == ()


def test_b63_2_fabrikam_the_clean_twin_has_nothing_to_propose() -> None:
    review = _review(FABRIKAM)
    assert review.proposals == ()
    assert review.findings == ()


def test_b63_2_a_device_of_another_client_is_never_proposed() -> None:
    decoys = {CONTOSO: "f0000000-0000-4000-8000-0000000d0900", FABRIKAM: "c0000000-0000-4000-8000-0000000d0900"}
    for client, decoy in decoys.items():
        review = _review(client)
        every = {u for p in review.proposals for u in p.device_uids} | {f.device_uid for f in review.findings}
        assert decoy not in every
        assert review.ignored_devices == 1
        mine = {str(d["uid"]) for d in RmmMock.for_fixture(client).list_devices().data or []}
        assert every <= mine


def test_b63_2_a_package_the_client_has_not_approved_is_never_proposed(tmp_path: Path) -> None:
    def drop(d: dict[str, Any]) -> None:
        d["clients"][CONTOSO]["approved"].remove("notepadpp")

    review = _review(CONTOSO, catalog_path=_tmp_catalog(tmp_path, drop))
    assert "notepadpp" not in {p.package_id for p in review.proposals}
    assert any(f.package_id == "notepadpp" and f.kind == "not-approved" for f in review.findings)


def test_b63_2_a_client_the_catalog_does_not_know_is_refused() -> None:
    with pytest.raises(CatalogError):
        propose_updates(
            "no-such-client", RmmMock.for_fixture(CONTOSO), catalog=load_catalog(), installed=DEFAULT_INSTALLED
        )
    with pytest.raises(CatalogError):
        # an RMM adapter of one client with the catalog entry of another is not a review of either
        propose_updates(FABRIKAM, RmmMock.for_fixture(CONTOSO), catalog=load_catalog(), installed=DEFAULT_INSTALLED)


# -- B63-3 deployment is a proposal; nothing installs without approval -------------------------------------------


def test_b63_3_every_proposal_is_a_lever_call_in_dry_run_that_needs_a_lead_and_nothing_is_executed() -> None:
    spec = Registry.load().get(LEVER)
    assert spec is not None
    for p in _review(CONTOSO).proposals:
        assert p.status == "proposed" and p.lever == LEVER and p.approval == "lead"
        assert len(p.calls) == p.device_count
        for call in p.calls:
            assert call["mode"] == "dry-run" and call["lever"] == LEVER
            assert validate_params(spec.params, call["params"]) == []


def test_b63_3_running_the_review_and_its_dry_runs_changes_no_state_and_an_unapproved_execute_is_denied(
    runner: LeverRunner, tmp_path: Path
) -> None:
    tenant = tmp_path / "tenant" / f"{CONTOSO}.json"
    before = tenant.read_bytes()
    fixtures = {p: p.read_bytes() for p in (DEFAULT_CATALOG, DEFAULT_INSTALLED)}
    for p in _review(CONTOSO).proposals:
        for call in p.calls:
            dry = runner.invoke(LEVER, call["params"], identity="triage-bot", client=CONTOSO)
            assert dry.ok and not dry.applied
            hot = runner.invoke(LEVER, call["params"], identity="tech-ana", client=CONTOSO, mode="execute")
            assert hot.status == "denied"
    assert tenant.read_bytes() == before
    assert all(p.read_bytes() == b for p, b in fixtures.items())
    assert _chain_ok(tmp_path)


def test_b63_3_the_module_has_no_install_run_or_network_path() -> None:
    tree = ast.parse((REPO / "levers" / "python" / "software.py").read_text(encoding="utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not names & {"subprocess", "socket", "http", "urllib", "requests", "httpx", "os", "ctypes", "asyncio"}
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"eval", "exec", "compile", "__import__"}
