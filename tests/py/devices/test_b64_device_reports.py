"""B-64 device compliance, encryption and LAPS coverage reports; provisioning readiness.

Acceptance ids B64-1 to B64-3 are defined in specs/B-64.md. Every test is offline and works on committed fixtures
(read only) or private copies under tmp_path. Expected numbers are computed here from the raw fixture files, not from
the code under test. Run: uv run --frozen pytest -p no:cacheprovider tests/py/devices/test_b64_device_reports.py
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from workflows.device_reports import (
    ReportError,
    build_client_report,
    find_secrets,
    load_config,
    render_markdown,
    verify,
    write_report,
)
from workflows.device_reports.__main__ import main

REPO = Path(__file__).resolve().parents[3]
RMM_DIR = REPO / "fixtures" / "rmm"
INTUNE_DIR = REPO / "fixtures" / "intune"
PSA_DIR = REPO / "workflows" / "device_reconcile" / "psa_assets"
OVERLAY_DIR = REPO / "workflows" / "device_reports" / "fixtures"
CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
CLIENTS = (CONTOSO, FABRIKAM)
AS_OF = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
TENANTS = {CONTOSO: "c0000000-0000-4000-8000-000000000001", FABRIKAM: "f0000000-0000-4000-8000-000000000002"}
SITES = {CONTOSO: "c0000000-0000-4000-8000-0000000a0001", FABRIKAM: "f0000000-0000-4000-8000-0000000a0002"}
COMPANIES = {CONTOSO: "30001", FABRIKAM: "30002"}
BITLOCKER_KEY = "123456-234567-345678-456789-567890-678901-789012-890123"
LAPS_PASSWORD = "Zq7!pLm2$Xw9vRt4KbN8cYd3"  # noqa: S105 - invented test value
LAPS_B64 = "WnE3IXBMbTIkWHc5dlJ0NEtiTjhjWWQz"


def _raw(folder: Path, client: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((folder / f"{client}.json").read_text(encoding="utf-8"))
    return data


def _dirs(tmp_path: Path) -> dict[str, Path]:
    out = {"rmm_dir": tmp_path / "rmm", "intune_dir": tmp_path / "intune", "psa_dir": tmp_path / "psa"}
    out["overlay_dir"] = tmp_path / "overlay"
    for src, key in (
        (RMM_DIR, "rmm_dir"),
        (INTUNE_DIR, "intune_dir"),
        (PSA_DIR, "psa_dir"),
        (OVERLAY_DIR, "overlay_dir"),
    ):
        shutil.copytree(src, out[key])
    return out


def _report(client: str, **dirs: Path) -> dict[str, Any]:
    return build_client_report(client, as_of=AS_OF, **dirs)


def _row(report: dict[str, Any], name: str) -> dict[str, Any]:
    return next(d for d in report["devices"] if d["name"].casefold() == name.casefold())


def _edit(path: Path, change: Any) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _hire(report: dict[str, Any], hire_id: str) -> dict[str, Any]:
    return next(h for h in report["provisioning"]["hires"] if h["hire_id"] == hire_id)


# --- B64-1: per client, compliance with reason, encryption, LAPS, Autopilot readiness -----------------------------
def test_b64_1_the_seeded_client_lists_each_device_with_a_compliance_status_and_reason() -> None:
    report = _report(CONTOSO)
    assert report["client"] == CONTOSO and report["as_of"] == "2026-10-22T12:00:00Z"
    assert _row(report, "FRONTDESK-01")["compliance"] == {"status": "compliant", "reasons": []}
    stale = _row(report, "OFFICE-MGR")["compliance"]
    assert stale["status"] == "stale" and stale["reasons"] == ["stale-sync: last sync 2026-09-01T10:00:00Z"]
    server = _row(report, "DENTAL-SRV01")["compliance"]
    assert server["status"] == "not-in-intune" and server["reasons"] == ["not-in-intune: no Intune record"]


def test_b64_1_the_attention_list_holds_every_device_that_needs_a_follow_up_and_nothing_else() -> None:
    report = _report(CONTOSO)
    flagged = {d["device"] for d in report["attention"]}
    expected = {
        d["device"]
        for d in report["devices"]
        if d["compliance"]["status"] != "compliant"
        or d["encryption"] != "encrypted"
        or d["laps"]["status"] not in ("covered", "not-applicable")
    }
    assert flagged == expected and len(flagged) >= 7
    assert all(d["reasons"] for d in report["attention"])


def test_b64_1_a_noncompliant_unencrypted_device_is_listed_with_both_reasons(tmp_path: Path) -> None:
    dirs = _dirs(tmp_path)

    def worse(data: dict[str, Any]) -> None:
        row = data["managedDevices"]["value"][0]
        row["complianceState"] = "noncompliant"
        row["isEncrypted"] = False

    _edit(dirs["intune_dir"] / f"{CONTOSO}.json", worse)
    report = _report(CONTOSO, **dirs)
    front = _row(report, "FRONTDESK-01")
    assert front["compliance"] == {"status": "non-compliant", "reasons": ["intune-state: noncompliant"]}
    assert front["encryption"] == "not-encrypted"
    attention = next(d for d in report["attention"] if d["name"] == "FRONTDESK-01")
    assert attention["reasons"] == ["intune-state: noncompliant", "encryption: disk is not encrypted"]
    assert report["counts"]["compliance"]["non-compliant"] == 1


def test_b64_1_encryption_status_comes_from_intune_and_is_unknown_without_an_intune_record() -> None:
    report = _report(CONTOSO)
    assert _row(report, "FRONTDESK-01")["encryption"] == "encrypted"
    assert _row(report, "DENTAL-SRV01")["encryption"] == "unknown"
    assert report["counts"]["encryption"] == {"encrypted": 5, "not-encrypted": 0, "unknown": 6}


def test_b64_1_laps_coverage_separates_covered_old_missing_and_unknown() -> None:
    report = _report(CONTOSO)
    laps = {d["name"].casefold(): d["laps"] for d in report["devices"]}
    assert laps["frontdesk-01"] == {"status": "covered", "last_backup": "2026-10-12T03:00:00Z"}
    assert laps["laptop-pnair"] == {"status": "stale-backup", "last_backup": "2026-08-20T03:00:00Z"}
    assert laps["office-mgr"] == {"status": "not-backed-up", "last_backup": None}
    assert laps["dental-srv01"] == {"status": "unknown", "last_backup": None}
    assert report["counts"]["laps"] == {
        "applicable": 5,
        "covered": 3,
        "stale-backup": 1,
        "not-backed-up": 1,
        "not-applicable": 0,
        "unknown": 6,
    }


def test_b64_1_a_non_windows_intune_device_is_not_applicable_for_laps(tmp_path: Path) -> None:
    dirs = _dirs(tmp_path)
    _edit(
        dirs["intune_dir"] / f"{FABRIKAM}.json",
        lambda d: d["managedDevices"]["value"][0].update({"operatingSystem": "macOS"}),
    )
    report = _report(FABRIKAM, **dirs)
    assert _row(report, "FAB-WS01")["laps"]["status"] == "not-applicable"
    assert report["counts"]["laps"]["applicable"] == 2 and report["counts"]["laps"]["covered"] == 2


def test_b64_1_incoming_hires_are_ready_or_listed_with_what_is_missing() -> None:
    prov = _report(CONTOSO)["provisioning"]
    ready = _hire(_report(CONTOSO), "H-CD-001")
    assert ready["readiness"] == "ready" and ready["reasons"] == [] and ready["days_until_start"] == 11
    assert _hire(_report(CONTOSO), "H-CD-002")["reasons"] == ["autopilot-profile: notAssigned"]
    assert _hire(_report(CONTOSO), "H-CD-003")["reasons"] == ["no-device-assigned"]
    assert _hire(_report(CONTOSO), "H-CD-004")["reasons"] == ["serial-not-registered-in-autopilot"]
    assert [h["hire_id"] for h in prov["hires"] if h["urgent"]] == ["H-CD-002"]
    assert prov["counts"] == {"hires": 4, "ready": 1, "not-ready": 3, "autopilot_devices": 3, "autopilot_unassigned": 1}


def test_b64_1_the_clean_client_has_nothing_to_follow_up_but_its_server() -> None:
    report = _report(FABRIKAM)
    assert [a["name"] for a in report["attention"]] == ["FAB-FS01"]  # no Intune record; servers are not told apart
    assert report["counts"]["compliance"] == {"compliant": 3, "non-compliant": 0, "stale": 0, "not-in-intune": 1}
    assert report["provisioning"]["counts"]["not-ready"] == 0


def test_b64_1_the_report_is_written_as_json_and_markdown_with_a_hash_for_each(tmp_path: Path) -> None:
    written = write_report(_report(CONTOSO), tmp_path)
    assert written.json_path.name == "2026-10-22.json" and written.json_path.parent.name == CONTOSO
    assert written.md_path.name == "2026-10-22.md"
    for path in (written.json_path, written.md_path):
        side = path.with_name(path.name + ".sha256").read_text(encoding="ascii")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert side == f"{digest}  {path.name}\n"  # sha256sum format: re-checkable without this code
    assert written.sha256 == hashlib.sha256(written.json_path.read_bytes()).hexdigest()
    assert verify(written.json_path).startswith("ok")


def test_b64_1_the_markdown_names_each_section_and_pins_the_json_hash(tmp_path: Path) -> None:
    report = _report(CONTOSO)
    written = write_report(report, tmp_path)
    md = written.md_path.read_text(encoding="utf-8")
    for heading in (
        "## Compliance",
        "## Encryption",
        "## LAPS coverage",
        "## Provisioning readiness",
        "## Not verified",
    ):
        assert heading in md
    assert "fixture-based" in md and "OFFICE-MGR" in md and "H-CD-004" in md
    assert f"Report SHA-256 (JSON): {written.sha256}" in md
    assert md == render_markdown(report, written.sha256)


def test_b64_1_the_same_inputs_give_the_same_bytes(tmp_path: Path) -> None:
    a = write_report(_report(CONTOSO), tmp_path / "a")
    b = write_report(_report(CONTOSO), tmp_path / "b")
    assert a.json_path.read_bytes() == b.json_path.read_bytes()
    assert a.md_path.read_bytes() == b.md_path.read_bytes()


def test_b64_1_a_changed_json_or_markdown_fails_verification(tmp_path: Path) -> None:
    written = write_report(_report(CONTOSO), tmp_path)
    original_md = written.md_path.read_bytes()
    written.md_path.write_bytes(original_md.replace(b"OFFICE-MGR", b"OFFICE-XXX", 1))
    with pytest.raises(ReportError, match="2026-10-22.md"):
        verify(written.json_path)
    written.md_path.write_bytes(original_md)
    assert verify(written.json_path).startswith("ok")
    written.json_path.write_bytes(written.json_path.read_bytes().replace(b'"compliant": 4', b'"compliant": 5', 1))
    with pytest.raises(ReportError, match="2026-10-22.json"):
        verify(written.json_path)


def test_b64_1_a_markdown_with_a_fresh_sidecar_but_other_content_is_still_caught(tmp_path: Path) -> None:
    written = write_report(_report(CONTOSO), tmp_path)
    forged = written.md_path.read_bytes().replace(b"OFFICE-MGR", b"OFFICE-XXX", 1)
    written.md_path.write_bytes(forged)
    written.md_path.with_name("2026-10-22.md.sha256").write_text(
        f"{hashlib.sha256(forged).hexdigest()}  2026-10-22.md\n", encoding="ascii"
    )
    with pytest.raises(ReportError, match="does not match the report"):
        verify(written.json_path)


def test_b64_1_the_date_comes_from_as_of_and_never_the_clock(tmp_path: Path) -> None:
    later = build_client_report(CONTOSO, as_of=datetime(2026, 12, 1, 12, 0, tzinfo=UTC))
    assert later["as_of"] == "2026-12-01T12:00:00Z"
    assert _row(later, "FRONTDESK-01")["laps"]["status"] == "stale-backup"  # 50 days old by then
    default = build_client_report(CONTOSO)
    assert default["as_of"] == "2026-10-22T12:00:00Z"  # the RMM fixture's pinned time
    assert write_report(later, tmp_path).json_path.name == "2026-12-01.json"


def test_b64_1_the_report_says_which_figures_are_fixture_based_and_lists_what_is_unverified() -> None:
    report = _report(CONTOSO)
    assert report["data_class"] == "DC-3" and "fixture-based" in report["note"]
    assert len(report["unverified"]) >= 5
    text = "\n".join(report["unverified"])
    assert "deviceLocalCredentialInfo" in text and "windowsAutopilotDeviceIdentity" in text
    assert "compliance reason" in text


def test_b64_1_the_config_has_no_unknown_keys(tmp_path: Path) -> None:
    bad = tmp_path / "config.json"
    bad.write_text(json.dumps({"version": 1, "laps_max_backup_age_days": 35, "starts_soon_days": 7, "x": 1}))
    with pytest.raises(ReportError, match="cannot load"):
        load_config(bad)
    assert load_config().laps_max_backup_age_days == 35


# --- B64-2: status only; no secret in any output ----------------------------------------------------------------
def _walk_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _walk_keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _walk_keys(v)}
    return set()


def test_b64_2_planted_secrets_in_the_sources_never_reach_the_output(tmp_path: Path) -> None:
    dirs = _dirs(tmp_path)

    def plant(data: dict[str, Any]) -> None:
        for row in data["localCredentials"]["value"]:
            row["credentials"] = [{"accountName": "Administrator", "passwordBase64": LAPS_B64}]
            row["password"] = LAPS_PASSWORD
        data["bitlockerRecoveryKeys"] = [{"deviceId": "x", "key": BITLOCKER_KEY}]

    _edit(dirs["overlay_dir"] / f"{CONTOSO}.json", plant)
    _edit(
        dirs["intune_dir"] / f"{CONTOSO}.json",
        lambda d: d["managedDevices"]["value"][0].update({"recoveryKey": BITLOCKER_KEY, "laps": LAPS_PASSWORD}),
    )
    report = _report(CONTOSO, **dirs)
    written = write_report(report, tmp_path / "out")
    for path in (written.json_path, written.md_path):
        text = path.read_text(encoding="utf-8")
        for secret in (BITLOCKER_KEY, LAPS_PASSWORD, LAPS_B64):
            assert secret not in text
    assert report["gaps"]["ignored_laps_fields"] == 10  # two planted keys on each of the five LAPS entries


def test_b64_2_a_secret_shaped_value_in_an_output_field_stops_the_report(tmp_path: Path) -> None:
    dirs = _dirs(tmp_path)
    _edit(
        dirs["intune_dir"] / f"{CONTOSO}.json",
        lambda d: d["managedDevices"]["value"][0].update({"userPrincipalName": BITLOCKER_KEY}),
    )
    with pytest.raises(ReportError, match="secret-shaped"):
        _report(CONTOSO, **dirs)
    assert not (tmp_path / "out").exists()


def test_b64_2_find_secrets_recognises_keys_and_tokens_but_not_ids_or_hashes() -> None:
    assert find_secrets(f"key {BITLOCKER_KEY} end")
    assert find_secrets(f"x {LAPS_B64} y")
    assert find_secrets('{"passwordBase64": "x"}')
    assert find_secrets('{"recoveryKey": "x"}')
    assert not find_secrets(hashlib.sha256(b"x").hexdigest())
    assert not find_secrets("c0000000-0000-4000-8000-0000000f0001 CD-0001-FD 2026-10-22T12:00:00Z")
    assert not find_secrets("workflows/device_reports/fixtures/contoso-dental.json")


@pytest.mark.parametrize("client", CLIENTS)
def test_b64_2_no_committed_client_output_holds_a_secret_shaped_value(client: str, tmp_path: Path) -> None:
    written = write_report(build_client_report(client), tmp_path)
    key_shape = re.compile(r"\b\d{6}(?:-\d{6}){7}\b")
    token_shape = re.compile(
        r"(?<![A-Za-z0-9+/])(?=[A-Za-z0-9+/=]*[A-Z])(?=[A-Za-z0-9+/=]*[a-z])(?=[A-Za-z0-9+/=]*\d)[A-Za-z0-9+/=]{20,}"
    )
    for path in (written.json_path, written.md_path):
        text = path.read_text(encoding="utf-8")
        assert not key_shape.search(text) and not token_shape.search(text)
        assert find_secrets(text) == []
    keys = {k.casefold() for k in _walk_keys(json.loads(written.json_path.read_text(encoding="utf-8")))}
    assert not [k for k in keys if any(w in k for w in ("password", "recovery", "credential", "secret", "token"))]


def test_b64_2_the_overlay_loader_reads_only_the_listed_laps_fields() -> None:
    src = (REPO / "workflows" / "device_reports" / "reports.py").read_text(encoding="utf-8")
    assert "LAPS_FIELDS" in src
    for word in ("passwordBase64", "recoveryKey", "bitlockerRecoveryKeys", "getRecoveryKey"):
        assert word not in src.replace("find_secrets", ""), word


# --- B64-3: counts reconcile to the fixtures; one client at a time -------------------------------------------------
def _expected(client: str) -> dict[str, Any]:
    """Everything below is computed from the raw fixture files, with none of this item's code."""
    intune = _raw(INTUNE_DIR, client)["managedDevices"]["value"]
    overlay = _raw(OVERLAY_DIR, client)
    rmm = _raw(RMM_DIR, client)
    psa = _raw(PSA_DIR, client)
    site = rmm["site"]["uid"]
    rmm_n = len([d for d in rmm["devices"]["devices"] if d["siteUid"] == site])
    psa_n = len([i for i in psa["configurationItems"]["items"] if i["companyID"] == psa["companyID"]])
    cutoff = AS_OF - timedelta(days=30)
    stale = [d for d in intune if datetime.fromisoformat(d["lastSyncDateTime"]) < cutoff]
    bad = [d for d in intune if d["complianceState"] != "compliant"]
    backups = {e["id"]: e["lastBackupDateTime"] for e in overlay["localCredentials"]["value"]}
    mine = [d for d in intune if d["azureADDeviceId"] in backups]
    fresh = [d for d in mine if datetime.fromisoformat(backups[d["azureADDeviceId"]]) >= AS_OF - timedelta(days=35)]
    return {
        "rmm": rmm_n,
        "intune": len(intune),
        "psa": psa_n,
        "stale": len(stale),
        "noncompliant": len(bad),
        "encrypted": len([d for d in intune if d["isEncrypted"]]),
        "laps_covered": len(fresh),
        "laps_stale": len(mine) - len(fresh),
        "laps_missing": len(intune) - len(mine),
        "laps_orphans": len(backups) - len(mine),
        "hires": len(overlay["incomingHires"]),
        "autopilot": len(overlay["autopilotDevices"]["value"]),
    }


@pytest.mark.parametrize("client", CLIENTS)
def test_b64_3_every_count_reconciles_to_the_raw_fixtures(client: str) -> None:
    exp, report = _expected(client), _report(client)
    counts = report["counts"]
    assert counts["reconcile"]["records"] == {"rmm": exp["rmm"], "intune": exp["intune"], "psa": exp["psa"]}
    assert counts["reconcile"]["reconciles"] is True
    n = counts["devices"]
    assert n == len(report["devices"])
    comp = counts["compliance"]
    assert sum(comp.values()) == n
    assert comp["stale"] == exp["stale"] and comp["non-compliant"] == exp["noncompliant"]
    assert comp["not-in-intune"] == n - exp["intune"]
    assert comp["compliant"] == exp["intune"] - exp["stale"] - exp["noncompliant"]
    enc = counts["encryption"]
    assert sum(enc.values()) == n and enc["encrypted"] == exp["encrypted"] and enc["unknown"] == n - exp["intune"]
    laps = counts["laps"]
    assert sum(laps.values()) - laps["applicable"] == n
    assert laps["covered"] == exp["laps_covered"] and laps["stale-backup"] == exp["laps_stale"]
    assert laps["not-backed-up"] == exp["laps_missing"] and laps["applicable"] == exp["intune"]
    assert report["gaps"]["orphan_laps_records"] == exp["laps_orphans"] == 1
    prov = report["provisioning"]["counts"]
    assert prov["hires"] == exp["hires"] == prov["ready"] + prov["not-ready"]
    assert prov["autopilot_devices"] == exp["autopilot"]
    assert len(report["provisioning"]["hires"]) == exp["hires"]


def test_b64_3_the_expected_table_for_the_committed_fixtures_is_stable() -> None:
    contoso, fabrikam = _report(CONTOSO)["counts"], _report(FABRIKAM)["counts"]
    assert (contoso["devices"], fabrikam["devices"]) == (11, 4)
    assert contoso["compliance"] == {"compliant": 4, "non-compliant": 0, "stale": 1, "not-in-intune": 6}
    assert fabrikam["laps"]["covered"] == 3 and fabrikam["encryption"]["unknown"] == 1  # the server


def test_b64_3_device_counts_match_the_b61_reconciliation() -> None:
    from adapters.intune import IntuneMock
    from adapters.rmm import RmmMock
    from workflows.device_reconcile import PsaAssetsMock, load_config, reconcile

    rec = reconcile(
        RmmMock.for_fixture(CONTOSO),
        IntuneMock.for_fixture(CONTOSO),
        PsaAssetsMock.for_fixture(CONTOSO),
        AS_OF,
        load_config(),
    )
    report = _report(CONTOSO)
    assert [d["device"] for d in report["devices"]] == sorted(d.key for d in rec.devices)
    assert report["counts"]["reconcile"] == rec.counts()


def test_b64_3_one_clients_report_never_holds_the_other_clients_records() -> None:
    contoso, fabrikam = json.dumps(_report(CONTOSO)), json.dumps(_report(FABRIKAM))
    assert "f0000000" not in contoso and "FAB-WS01" not in contoso and "fabrikamcapital" not in contoso
    assert "c0000000" not in fabrikam and "FRONTDESK-01" not in fabrikam and "contosodental" not in fabrikam


def test_b64_3_an_overlay_of_another_client_or_tenant_is_refused(tmp_path: Path) -> None:
    dirs = _dirs(tmp_path)
    shutil.copy(dirs["overlay_dir"] / f"{FABRIKAM}.json", dirs["overlay_dir"] / f"{CONTOSO}.json")
    with pytest.raises(ReportError, match="does not belong"):
        _report(CONTOSO, **dirs)
    _edit(dirs["overlay_dir"] / f"{CONTOSO}.json", lambda d: d.update({"client": CONTOSO}))
    with pytest.raises(ReportError, match="does not belong"):  # right client name, other client's tenant
        _report(CONTOSO, **dirs)


def test_b64_3_a_laps_record_of_the_other_client_is_counted_as_a_gap_and_never_as_coverage(tmp_path: Path) -> None:
    dirs = _dirs(tmp_path)
    _edit(
        dirs["overlay_dir"] / f"{FABRIKAM}.json",
        lambda d: d["localCredentials"]["value"].pop(0),  # FAB-WS01 loses its own record; the decoy stays
    )
    report = _report(FABRIKAM, **dirs)
    assert _row(report, "FAB-WS01")["laps"]["status"] == "not-backed-up"
    assert report["counts"]["laps"]["covered"] == 2 and report["gaps"]["orphan_laps_records"] == 1


def test_b64_3_a_hire_whose_serial_is_also_the_other_clients_is_not_found_in_this_autopilot_list(
    tmp_path: Path,
) -> None:
    dirs = _dirs(tmp_path)
    fab_serial = _raw(OVERLAY_DIR, FABRIKAM)["autopilotDevices"]["value"][0]["serialNumber"]
    _edit(
        dirs["overlay_dir"] / f"{CONTOSO}.json", lambda d: d["incomingHires"][2].update({"assignedSerial": fab_serial})
    )
    report = _report(CONTOSO, **dirs)
    assert _hire(report, "H-CD-003")["reasons"] == ["serial-not-registered-in-autopilot"]


def test_b64_3_real_adapter_selection_fails_closed(tmp_path: Path) -> None:
    ref = "client-contoso-dental"
    cfg = {
        "version": 1,
        "_note": "Synthetic test client.",
        "id": CONTOSO,
        "display_name": CONTOSO,
        "psa_company_id": COMPANIES[CONTOSO],
        "industry": "other",
        "regimes": [],
        "model_processing": "none",
        "retention_class": "standard",
        "enabled_levers": ["user.disable"],
        "bindings": {
            "psa": {"implementation": "mock", "external_id": COMPANIES[CONTOSO]},
            "rmm": {"implementation": "real", "external_id": SITES[CONTOSO], "credential_ref": f"{ref}-rmm"},
            "m365": {
                "implementation": "mock",
                "external_id": TENANTS[CONTOSO],
                "credential_ref": f"{ref}-m365",
                "access": "gdap",
            },
        },
    }
    (tmp_path / f"{CONTOSO}.json").write_text(json.dumps(cfg), encoding="utf-8")
    with pytest.raises(ReportError, match="real adapter not configured"):
        build_client_report(CONTOSO, as_of=AS_OF, config_dir=tmp_path)


def test_b64_3_the_report_only_reads_the_fixtures_and_writes_only_where_told(tmp_path: Path) -> None:
    def snapshot() -> dict[str, str]:
        return {
            p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for d in (RMM_DIR, INTUNE_DIR, PSA_DIR, OVERLAY_DIR)
            for p in sorted(d.rglob("*.json"))
        }

    before = snapshot()
    out = tmp_path / "out"
    write_report(_report(CONTOSO), out)
    assert snapshot() == before
    assert sorted(p.name for p in out.rglob("*") if p.is_file()) == [
        "2026-10-22.json",
        "2026-10-22.json.sha256",
        "2026-10-22.md",
        "2026-10-22.md.sha256",
    ]


def test_b64_3_the_module_holds_no_write_or_run_call_on_any_system() -> None:
    src = (REPO / "workflows" / "device_reports" / "reports.py").read_text(encoding="utf-8")
    for word in ("subprocess", "requests", "urllib", "httpx", "socket", "os.system", "rmm.run", "retire", "wipe"):
        assert word not in src, word


# --- command line -----------------------------------------------------------------------------------------------------
def test_b64_cli_writes_verifies_and_exits_2_on_bad_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["report", CONTOSO, "--out", str(tmp_path)]) == 0
    json_path = tmp_path / CONTOSO / "2026-10-22.json"
    assert json_path.is_file() and "sha256" in capsys.readouterr().out
    assert main(["verify", str(json_path)]) == 0
    json_path.write_bytes(json_path.read_bytes() + b" ")
    assert main(["verify", str(json_path)]) == 1
    assert main(["report", "no-such-client", "--out", str(tmp_path)]) == 2
    assert main(["report", "../x", "--out", str(tmp_path)]) == 2
    assert main(["report", CONTOSO, "--as-of", "not-a-time", "--out", str(tmp_path)]) == 2


def test_b64_1_every_overlay_fixture_field_is_marked_verified_or_unverified() -> None:
    table = (OVERLAY_DIR / "SOURCES.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| (\S+) \| `([^`]+)` \| (Verified|UNVERIFIED)\b", table, re.MULTILINE)
    marked = {(entity, field) for entity, field, _ in rows}

    def keys(node: Any, entity: str) -> set[tuple[str, str]]:
        out: set[tuple[str, str]] = set()
        if isinstance(node, dict):
            for k, v in node.items():
                out.add((entity, k))
                out |= keys(v, k)
        elif isinstance(node, list):
            for v in node:
                out |= keys(v, entity)
        return out

    for client in CLIENTS:
        missing = keys(_raw(OVERLAY_DIR, client), "file") - marked
        assert not missing, sorted(missing)
