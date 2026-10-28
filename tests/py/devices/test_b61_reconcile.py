"""B-61 RMM and Intune mock adapters and device reconciliation across RMM, Intune and PSA assets.

Acceptance ids B61-1 to B61-4 are defined in specs/B-61.md. Every test is offline and works on committed fixtures
(read only) or private copies under tmp_path. Run: uv run --frozen pytest -p no:cacheprovider tests/py/devices
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import random
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from adapters.base import REAL_ADAPTER_NOT_CONFIGURED, AdapterError
from adapters.binding import BoundBinding
from adapters.intune import IntuneAdapter, IntuneMock, build_intune_adapter
from adapters.rmm import RmmAdapter, RmmMock, build_rmm_adapter
from core.levers import Registry
from workflows.device_reconcile import (
    MISMATCH_TYPES,
    DeviceRecord,
    PsaAssetsMock,
    ReconcileError,
    build_psa_assets,
    build_sources,
    component_inventory,
    load_config,
    match,
    reconcile,
    summary,
)
from workflows.device_reconcile.__main__ import main

REPO = Path(__file__).resolve().parents[3]
RMM_DIR = REPO / "fixtures" / "rmm"
INTUNE_DIR = REPO / "fixtures" / "intune"
PSA_DIR = REPO / "workflows" / "device_reconcile" / "psa_assets"
CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
CLIENTS = (CONTOSO, FABRIKAM)
AS_OF = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
TENANTS = {CONTOSO: "c0000000-0000-4000-8000-000000000001", FABRIKAM: "f0000000-0000-4000-8000-000000000002"}
SITES = {CONTOSO: "c0000000-0000-4000-8000-0000000a0001", FABRIKAM: "f0000000-0000-4000-8000-0000000a0002"}
COMPANIES = {CONTOSO: "30001", FABRIKAM: "30002"}


def _raw(folder: Path, client: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((folder / f"{client}.json").read_text(encoding="utf-8"))
    return data


def _run(client: str, rmm_dir: Path = RMM_DIR, intune_dir: Path = INTUNE_DIR, psa_dir: Path = PSA_DIR) -> Any:
    return reconcile(
        RmmMock.for_fixture(client, rmm_dir),
        IntuneMock.for_fixture(client, intune_dir),
        PsaAssetsMock.for_fixture(client, psa_dir),
        AS_OF,
        load_config(),
    )


def _device(rec: Any, key: str) -> Any:
    return next(d for d in rec.devices if d.key == key)


def _ids(rec: Any, system: str) -> list[str]:
    return [r.record_id for d in rec.devices for r in d.records if r.system == system]


def _copy(tmp_path: Path) -> tuple[Path, Path, Path]:
    dirs = (tmp_path / "rmm", tmp_path / "intune", tmp_path / "psa")
    for src, dst in zip((RMM_DIR, INTUNE_DIR, PSA_DIR), dirs, strict=True):
        shutil.copytree(src, dst)
    return dirs


def _write_config(root: Path, client: str, rmm: str = "mock", m365: str = "mock", psa: str = "mock") -> Path:
    cfg = {
        "version": 1,
        "_note": "Synthetic test client.",
        "id": client,
        "display_name": client,
        "psa_company_id": COMPANIES[client],
        "industry": "other",
        "regimes": [],
        "model_processing": "none",
        "retention_class": "standard",
        "enabled_levers": ["user.disable"],
        "bindings": {
            "psa": {"implementation": psa, "external_id": COMPANIES[client]},
            "rmm": {"implementation": rmm, "external_id": SITES[client], "credential_ref": f"client-{client}-rmm"},
            "m365": {
                "implementation": m365,
                "external_id": TENANTS[client],
                "credential_ref": f"client-{client}-m365",
                "access": "gdap",
            },
        },
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{client}.json").write_text(json.dumps(cfg), encoding="utf-8")
    return root


# --- B61-1: serial first, then name; every mismatch type listed ----------------------------------------------
def test_b61_1_devices_are_matched_by_serial_across_rmm_intune_and_psa() -> None:
    rec = _run(CONTOSO)
    front = _device(rec, "serial:CD-0001-FD")
    assert front.matched_by == "serial" and front.systems == ("rmm", "intune", "psa")
    # Intune writes the name in lower case; the serial still matches.
    assert _device(rec, "serial:CD-0002-OP").systems == ("rmm", "intune", "psa")
    # The PSA writes the server's serial in lower case; serials ignore case.
    assert _device(rec, "serial:CD-0003-SV").systems == ("rmm", "psa")
    assert rec.counts()["in_all_three"] == 4


def test_b61_1_a_record_without_a_usable_serial_is_matched_by_name() -> None:
    rec = _run(CONTOSO)
    xray = _device(rec, "name:xray-ws01")
    assert xray.matched_by == "name" and xray.systems == ("rmm", "psa")
    names = {r.system: r.name for r in xray.records}
    assert names == {"rmm": "XRAY-WS01", "psa": "xray-ws01.contosodental.example"}  # case and DNS suffix ignored
    assert all(r.serial is None for r in xray.records)  # 'To be filled by O.E.M.' and '' are not serials


def test_b61_1_records_whose_serials_differ_are_never_merged_by_name() -> None:
    rec = _run(CONTOSO)
    rmm_side, psa_side = _device(rec, "serial:CD-0010-CS"), _device(rec, "serial:CD-0099-XX")
    assert rmm_side.systems == ("rmm",) and psa_side.systems == ("psa",)
    assert {r.name for r in rmm_side.records} == {r.name for r in psa_side.records} == {"CHAIRSIDE-04"}


def test_b61_1_every_mismatch_type_is_listed_for_the_seeded_client() -> None:
    rec = _run(CONTOSO)
    got = {(f.type, f.system, f.device, f.record_ids) for f in rec.findings}
    c = "c0000000-0000-4000-8000-0000000"
    assert got == {
        ("only-in-one-system", "intune", "serial:CD-0005-LT", (f"{c}e0003",)),
        ("only-in-one-system", "rmm", "serial:CD-0006-RC", (f"{c}d0005",)),
        ("only-in-one-system", "psa", "serial:CD-0009-SP", ("70007",)),
        ("only-in-one-system", "rmm", "serial:CD-0010-CS", (f"{c}d0009",)),
        ("only-in-one-system", "psa", "serial:CD-0099-XX", ("70008",)),
        ("stale", "rmm", "serial:CD-0006-RC", (f"{c}d0005",)),
        ("stale", "intune", "serial:CD-0007-OM", (f"{c}e0004",)),
        ("stale", "rmm", "serial:CD-0008-HY", (f"{c}d0007",)),
        ("duplicate", "rmm", "serial:CD-0008-HY", (f"{c}d0007", f"{c}d0008")),
    }
    assert set(MISMATCH_TYPES) == {f.type for f in rec.findings}
    out = summary(rec)
    assert out["counts"]["findings"] == {"only-in-one-system": 5, "stale": 3, "duplicate": 1}
    stale = next(f for f in out["findings"] if f["type"] == "stale" and f["system"] == "intune")
    assert stale["detail"] == "last seen 2026-09-01T10:00:00Z"


def test_b61_1_the_clean_twin_has_no_mismatch() -> None:
    rec = _run(FABRIKAM)
    assert rec.findings == ()
    assert rec.counts()["devices"] == 4 and rec.counts()["in_all_three"] == 3


def test_b61_1_an_ambiguous_name_is_not_guessed() -> None:
    a = DeviceRecord("rmm", "r1", "SHARED-PC", "S-1", None, False)
    b = DeviceRecord("intune", "i1", "shared-pc", "S-2", None, False)
    c = DeviceRecord("psa", "p1", "SHARED-PC", None, None, False)
    devices = match([a, b, c])
    assert len(devices) == 3  # two serial devices share the name, so the serial-less PSA item joins neither
    psa_only = next(d for d in devices if d.systems == ("psa",))
    assert psa_only.matched_by == "name" and psa_only.key.startswith("name:shared-pc#")


def test_b61_1_the_result_does_not_depend_on_input_order() -> None:
    rec = _run(CONTOSO)
    records = [r for d in rec.devices for r in d.records]
    first = [(d.key, [r.record_id for r in d.records]) for d in match(records)]
    random.Random(61).shuffle(records)  # noqa: S311 - a fixed test order, not cryptography
    assert [(d.key, [r.record_id for r in d.records]) for d in match(records)] == first


def test_b61_1_unreadable_last_seen_is_stale_and_epoch_milliseconds_are_read(tmp_path: Path) -> None:
    rmm_dir, intune_dir, psa_dir = _copy(tmp_path)
    data = _raw(rmm_dir, FABRIKAM)
    devices = data["devices"]["devices"]
    devices[0]["lastSeen"] = None
    devices[1]["lastSeen"] = int(datetime(2026, 10, 22, 8, 0, tzinfo=UTC).timestamp() * 1000)
    (rmm_dir / f"{FABRIKAM}.json").write_text(json.dumps(data), encoding="utf-8")
    rec = _run(FABRIKAM, rmm_dir, intune_dir, psa_dir)
    assert [(f.type, f.record_ids[0], f.detail) for f in rec.findings] == [
        ("stale", devices[0]["uid"], "no readable last-seen time")
    ]
    seen = next(r for d in rec.devices for r in d.records if r.record_id == devices[1]["uid"])
    assert seen.last_seen == "2026-10-22T08:00:00Z"


def test_b61_1_the_cli_prints_the_reconciliation(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([CONTOSO]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["client"] == CONTOSO and out["as_of"] == "2026-10-22T12:00:00Z"
    assert out["counts"]["devices"] == 11 and len(out["findings"]) == 9
    assert main(["../etc"]) == 2


# --- B61-2: counts reconcile; another client's devices are never compared --------------------------------------
@pytest.mark.parametrize("client", CLIENTS)
def test_b61_2_counts_reconcile_to_the_fixtures(client: str) -> None:
    rmm, intune, psa = _raw(RMM_DIR, client), _raw(INTUNE_DIR, client), _raw(PSA_DIR, client)
    own_rmm = [d["uid"] for d in rmm["devices"]["devices"] if d["siteUid"] == rmm["site"]["uid"]]
    own_intune = [d["id"] for d in intune["managedDevices"]["value"]]
    own_psa = [str(c["id"]) for c in psa["configurationItems"]["items"] if c["companyID"] == psa["companyID"]]
    rec = _run(client)
    counts = rec.counts()
    assert counts["records"] == {"rmm": len(own_rmm), "intune": len(own_intune), "psa": len(own_psa)}
    assert counts["placed"] == counts["records"] and counts["reconciles"] is True
    for system, expected in (("rmm", own_rmm), ("intune", own_intune), ("psa", own_psa)):
        assert sorted(_ids(rec, system)) == sorted(expected)  # every record in exactly one device
    assert rmm["site"]["devicesStatus"]["numberOfDevices"] == len(own_rmm)
    expected_table = {CONTOSO: (11, 4), FABRIKAM: (4, 3)}  # specs/B-61.md "Expected result on the fixtures"
    assert (counts["devices"], counts["in_all_three"]) == expected_table[client]


@pytest.mark.parametrize("client", CLIENTS)
def test_b61_2_decoys_of_another_client_are_never_listed_matched_or_counted(client: str) -> None:
    rmm, psa = _raw(RMM_DIR, client), _raw(PSA_DIR, client)
    decoy_devices = [d for d in rmm["devices"]["devices"] if d["siteUid"] != rmm["site"]["uid"]]
    decoy_items = [c for c in psa["configurationItems"]["items"] if c["companyID"] != psa["companyID"]]
    assert len(decoy_devices) == 1 and len(decoy_items) == 1  # the fixtures really hold a decoy each
    out = json.dumps(summary(_run(client), component_inventory(RmmMock.for_fixture(client))))
    assert decoy_devices[0]["uid"] not in out and f'"id": "{decoy_items[0]["id"]}"' not in out
    other = FABRIKAM if client == CONTOSO else CONTOSO
    assert SITES[other] not in out and TENANTS[other] not in out
    # The decoy carries this client's first serial, yet that device holds one record per system only.
    first_serial = decoy_items[0]["serialNumber"]
    device = _device(_run(client), f"serial:{first_serial}")
    assert sorted(r.system for r in device.records) == ["intune", "psa", "rmm"]


def test_b61_2_adapters_of_different_clients_are_never_compared() -> None:
    with pytest.raises(ReconcileError, match="different clients"):
        reconcile(
            RmmMock.for_fixture(CONTOSO),
            IntuneMock.for_fixture(FABRIKAM),
            PsaAssetsMock.for_fixture(CONTOSO),
            AS_OF,
            load_config(),
        )
    with pytest.raises(ReconcileError, match="different clients"):
        reconcile(
            RmmMock.for_fixture(CONTOSO),
            IntuneMock.for_fixture(CONTOSO),
            PsaAssetsMock.for_fixture(FABRIKAM),
            AS_OF,
            load_config(),
        )


def test_b61_2_an_rmm_site_linked_to_another_psa_company_is_refused(tmp_path: Path) -> None:
    rmm_dir, intune_dir, psa_dir = _copy(tmp_path)
    data = _raw(rmm_dir, CONTOSO)
    data["site"]["autotaskCompanyId"] = COMPANIES[FABRIKAM]
    (rmm_dir / f"{CONTOSO}.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ReconcileError, match="another PSA company"):
        _run(CONTOSO, rmm_dir, intune_dir, psa_dir)


def test_b61_2_adapters_refuse_a_binding_or_fixture_of_another_client() -> None:
    with pytest.raises(AdapterError):
        RmmMock(CONTOSO, BoundBinding(CONTOSO, "rmm", "mock", SITES[FABRIKAM]))
    with pytest.raises(AdapterError):
        RmmMock(CONTOSO, BoundBinding(FABRIKAM, "rmm", "mock", SITES[FABRIKAM]))
    with pytest.raises(AdapterError):
        IntuneMock(CONTOSO, BoundBinding(CONTOSO, "m365", "mock", TENANTS[FABRIKAM]))
    with pytest.raises(AdapterError):
        IntuneMock(CONTOSO, BoundBinding(CONTOSO, "rmm", "mock", TENANTS[CONTOSO]))  # wrong system
    with pytest.raises(AdapterError):
        PsaAssetsMock(CONTOSO, BoundBinding(CONTOSO, "psa", "mock", COMPANIES[FABRIKAM]))
    for bad in ("../fabrikam-capital", "Contoso", ""):
        with pytest.raises(AdapterError):
            RmmMock.for_fixture(bad)


def test_b61_2_a_lookup_of_another_clients_record_answers_like_an_absent_one() -> None:
    rmm = RmmMock.for_fixture(CONTOSO)
    raw = _raw(RMM_DIR, CONTOSO)
    decoy = next(d["uid"] for d in raw["devices"]["devices"] if d["siteUid"] != SITES[CONTOSO])
    absent = "c0000000-0000-4000-8000-0000000d9999"
    assert rmm.get_device(decoy).reason == rmm.get_device(absent).reason == "no such RMM device for this client"
    assert rmm.get_device_audit(decoy).reason == rmm.get_device_audit(absent).reason
    assert not rmm.get_device_audit(decoy).ok and decoy in raw["deviceAudits"]
    decoy_job = raw["jobsBySite"][SITES[FABRIKAM]][0]["uid"]
    assert rmm.get_job(decoy_job).reason == rmm.get_job("nope").reason == "no such RMM job for this client"
    alerts = rmm.list_open_alerts().data or []
    assert len(alerts) == 1 and all(a["alertSourceInfo"]["siteUid"] == SITES[CONTOSO] for a in alerts)
    intune = IntuneMock.for_fixture(CONTOSO)
    assert (
        intune.get_managed_device("f0000000-0000-4000-8000-0000000e0001").reason
        == "no such Intune device for this client"
    )


# --- B61-3: real adapter selection fails closed -----------------------------------------------------------------
def test_b61_3_mock_bindings_select_all_three_adapters(tmp_path: Path) -> None:
    cfgs = _write_config(tmp_path / "clients", CONTOSO)
    built = build_sources(CONTOSO, config_dir=cfgs)
    assert built.ok and built.sources is not None
    assert {built.sources.rmm.client, built.sources.intune.client, built.sources.psa.client} == {CONTOSO}
    assert built.sources.rmm.credential_ref == f"client-{CONTOSO}-rmm"  # a NAME, never a value


@pytest.mark.parametrize(
    ("override", "system"),
    [({"rmm": "datto-rmm"}, "rmm"), ({"m365": "graph-live"}, "intune"), ({"psa": "autotask"}, "psa")],
)
def test_b61_3_real_adapter_selection_fails_closed(
    tmp_path: Path, override: dict[str, str], system: str, capsys: pytest.CaptureFixture[str]
) -> None:
    cfgs = _write_config(tmp_path / "clients", CONTOSO, **override)
    builder = {"rmm": build_rmm_adapter, "intune": build_intune_adapter, "psa": build_psa_assets}[system]
    one = builder(CONTOSO, config_dir=cfgs)
    assert not one.ok and one.reason == REAL_ADAPTER_NOT_CONFIGURED and one.adapter is None
    built = build_sources(CONTOSO, config_dir=cfgs)
    assert not built.ok and built.sources is None and built.reason == f"{system}: real adapter not configured"
    assert main([CONTOSO, "--clients", str(cfgs)]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "real adapter not configured" in captured.err


def test_b61_3_a_missing_config_or_binding_fails_closed(tmp_path: Path) -> None:
    cfgs = tmp_path / "clients"
    assert not build_sources(CONTOSO, config_dir=cfgs).ok  # no file at all
    _write_config(cfgs, CONTOSO)
    data = json.loads((cfgs / f"{CONTOSO}.json").read_text(encoding="utf-8"))
    del data["bindings"]["rmm"]
    (cfgs / f"{CONTOSO}.json").write_text(json.dumps(data), encoding="utf-8")
    assert build_sources(CONTOSO, config_dir=cfgs).reason == "rmm: client has no 'rmm' binding"
    assert build_rmm_adapter(CONTOSO, config_dir=cfgs).adapter is None


# --- B61-4: Datto-RMM-shaped mock, every field marked, components read-only and never run -----------------------
_ROW = re.compile(r"^\| *([A-Za-z@][\w@]*) *\| *`([^`]+)` *\| *(.+?) *\|$")


def _table(path: Path) -> dict[tuple[str, str], str]:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _ROW.match(line.strip())
        if m:
            rows[(m.group(1), m.group(2))] = m.group(3)
    return rows


def _pairs(node: Any, parent: str, out: set[tuple[str, str]], id_maps: dict[str, str]) -> None:
    """Every (holding key, field) pair in a fixture; maps keyed by ids are labelled by ``id_maps``."""
    if isinstance(node, dict):
        for key, value in node.items():
            if parent in id_maps:
                _pairs(value, id_maps[parent], out, id_maps)
                continue
            out.add((parent, key))
            _pairs(value, key, out, id_maps)
    elif isinstance(node, list):
        for item in node:
            _pairs(item, parent, out, id_maps)


def _check_marked(source: Path, fixtures: list[Path], id_maps: dict[str, str]) -> None:
    table = _table(source)
    assert table, f"no field table in {source}"
    assert all(status.startswith(("Verified", "UNVERIFIED")) for status in table.values())
    for fixture in fixtures:
        pairs: set[tuple[str, str]] = set()
        _pairs(json.loads(fixture.read_text(encoding="utf-8")), "file", pairs, id_maps)
        missing = sorted(pairs - set(table))
        assert not missing, f"{fixture.name}: fields not marked in {source.name}: {missing}"


def test_b61_4_every_rmm_fixture_field_is_marked_verified_or_unverified() -> None:
    fixtures = sorted(RMM_DIR.glob("*.json"))
    assert [f.stem for f in fixtures] == list(CLIENTS)
    # deviceAudits and jobsBySite are keyed by ids; their records are labelled deviceAudit and job in the table.
    _check_marked(RMM_DIR / "SOURCES.md", fixtures, {"deviceAudits": "deviceAudit", "jobsBySite": "job"})
    statuses = _table(RMM_DIR / "SOURCES.md")
    assert statuses[("bios", "serialNumber")].startswith("Verified")
    assert statuses[("devices", "devices")].startswith("UNVERIFIED")


def test_b61_4_every_intune_and_psa_fixture_field_is_marked() -> None:
    _check_marked(INTUNE_DIR / "SOURCES.md", sorted(INTUNE_DIR.glob("*.json")), {})
    _check_marked(PSA_DIR / "SOURCES.md", sorted(PSA_DIR.glob("*.json")), {})
    for folder in (RMM_DIR, INTUNE_DIR, PSA_DIR):  # STD-FX-3: self-labelled, client matches file name
        for fixture in folder.glob("*.json"):
            data = json.loads(fixture.read_text(encoding="utf-8"))
            assert data["client"] == fixture.stem and "Synthetic" in data["_note"]


def test_b61_4_the_rmm_mock_serves_sites_devices_alerts_jobs_and_components() -> None:
    rmm = RmmMock.for_fixture(CONTOSO)
    site = rmm.get_site().data or {}
    assert site["uid"] == SITES[CONTOSO] and set(site["devicesStatus"]) == {
        "numberOfDevices",
        "numberOfOnlineDevices",
        "numberOfOfflineDevices",
    }
    devices = rmm.list_devices().data or []
    assert len(devices) == 9 and all(d["siteUid"] == SITES[CONTOSO] for d in devices)
    assert {"uid", "hostname", "deviceType", "lastSeen", "deviceClass"} <= set(devices[0])
    audit = rmm.get_device_audit(devices[0]["uid"]).data or {}
    assert set(audit["bios"]) == {"instance", "releaseDate", "serialNumber", "smBiosVersion"}
    assert [j["status"] for j in rmm.list_jobs().data or []] == ["completed"]
    assert {c["name"] for c in rmm.list_components().data or []} == {
        "Clear temp files (synthetic)",
        "Restart print spooler (synthetic)",
    }
    alert = (rmm.list_open_alerts().data or [])[0]
    assert alert["alertSourceInfo"]["deviceName"] == "HYGIENE-03" and "@class" in alert["alertContext"]


def test_b61_4_components_are_listed_read_only_and_never_run_until_vetted() -> None:
    rmm = RmmMock.for_fixture(CONTOSO)
    inventory = component_inventory(rmm)
    assert len(inventory) == 2
    assert all(c["vetted"] is False and c["run_by_program"] is False and "D6-26" in c["status"] for c in inventory)
    # No interface or mock method runs, creates or changes anything.
    write_words = re.compile(r"run|exec|quick|create|put|post|delete|update|set|resolve|move|wipe|retire|lock|sync")
    for cls in (RmmAdapter, RmmMock, IntuneAdapter, IntuneMock, PsaAssetsMock):
        public = [n for n, _ in inspect.getmembers(cls, inspect.isfunction) if not n.startswith("_")]
        assert not [n for n in public if write_words.search(n) and n != "for_fixture"], (cls.__name__, public)
    # Not vetted: no registered lever names any of these components.
    registry = Registry.load()
    lever_text = json.dumps([str(registry.get(n)) for n in registry.names()])
    for c in inventory:
        assert c["uid"] not in lever_text and str(c["name"]) not in lever_text
    # The code has no network or process imports: it cannot reach an RMM or start a script.
    banned = {"socket", "urllib", "http", "requests", "subprocess", "httpx", "asyncio"}
    code = [*(REPO / "adapters" / "rmm").glob("*.py"), *(REPO / "adapters" / "intune").glob("*.py")]
    code += list((REPO / "workflows" / "device_reconcile").glob("*.py"))
    for path in code:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not names & banned, (path.name, names & banned)


def test_b61_4_results_are_copies_and_fixtures_are_never_modified() -> None:
    folders = (RMM_DIR, INTUNE_DIR, PSA_DIR)
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for f in folders for p in f.glob("*.json")}
    rmm = RmmMock.for_fixture(CONTOSO)
    first = rmm.list_devices().data or []
    first[0]["hostname"] = "CHANGED"
    assert (rmm.list_devices().data or [])[0]["hostname"] != "CHANGED"
    intune = IntuneMock.for_fixture(CONTOSO)
    (intune.list_managed_devices().data or [])[0]["serialNumber"] = "CHANGED"
    assert "CHANGED" not in json.dumps(intune.list_managed_devices().data)
    for client in CLIENTS:
        assert main([client]) == 0
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for f in folders for p in f.glob("*.json")}
    assert after == before
