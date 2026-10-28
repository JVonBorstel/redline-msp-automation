"""B-52 regulatory evidence packs per client. Acceptance ids B52-1 to B52-4 are defined in specs/B-52.md.

Offline and deterministic: audit chains and output go under tmp_path, the committed fixtures are only read (edited
copies live under tmp_path), and the date is always passed as `as_of`.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/regpacks
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from core.audit.chain import verify_chain
from core.audit.router import AuditRouter
from workflows.regpacks import LABEL, RegpackError, VerifyError, build_pack, verify_pack
from workflows.regpacks.__main__ import main
from workflows.regpacks.pack import DEFAULT_FIXTURES

REPO = Path(__file__).resolve().parents[3]
AS_OF = "2026-10-27"
LEAD = "lead-lee"
GOV_ID = re.compile(r"^(BA|GLBA)-\d+$")
GOV_CELL = re.compile(r"\b(BA|GLBA)-\d+\b")
GOV_DOC = (REPO / "docs" / "map" / "05-governance.md").read_text(encoding="utf-8")
CONTROL_IDS = {c["id"] for c in json.loads((REPO / "map" / "controls.json").read_text(encoding="utf-8"))}
CLAIM_WORDS = re.compile(r"\b(compliant|certified|attested|passes|passed)\b", re.IGNORECASE)


def _pack(client: str, tmp_path: Path, **kw: Any) -> Any:
    kw.setdefault("by", LEAD)
    kw.setdefault("write", True)
    return build_pack(
        client,
        as_of=kw.pop("as_of", AS_OF),
        out_dir=tmp_path / "out",
        audit_dir=tmp_path / "audit",
        **kw,
    )


def _read(path: Path) -> Any:
    return json.loads(path.read_bytes())


def _lines(root: Path, regime: str) -> list[dict[str, Any]]:
    return _read(root / "mapping.json")["regimes"][regime]["lines"]


@pytest.fixture
def fixtures_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "fx"
    shutil.copytree(DEFAULT_FIXTURES, dest)
    return dest


def _set_regimes(fx: Path, client: str, regimes: list[str]) -> None:
    path = fx / "clients.json"
    data = _read(path)
    data["clients"][client]["regimes"] = regimes
    path.write_text(json.dumps(data), encoding="utf-8")


# -- B52-1 ----------------------------------------------------------------------------------------------------------
def test_b52_1_dental_client_maps_to_hipaa_308_and_312_only(tmp_path: Path) -> None:
    root = _pack("contoso-dental", tmp_path).root
    assert root is not None
    files = {p.name for p in root.iterdir()}
    assert "hipaa.md" in files and "glba-ftc-safeguards.md" not in files and "sec-reg-s-p.md" not in files
    lines = _lines(root, "hipaa")
    assert lines
    for line in lines:
        assert re.search(r"45 CFR 164\.(308|312)", line["cite"]), line
    # a finding lands on the item it is about
    by_item = {line["item"]: line for line in lines}
    assert "F-001" in by_item["H-08"]["findings"]
    assert "F-005" in by_item["H-05"]["findings"]


def test_b52_1_financial_client_maps_to_314_4_elements(tmp_path: Path) -> None:
    root = _pack("fabrikam-capital", tmp_path).root
    assert root is not None
    assert not (root / "hipaa.md").exists()
    lines = _lines(root, "glba-ftc-safeguards")
    assert lines and all(line["cite"].startswith("16 CFR 314.4") for line in lines)
    by_item = {line["item"]: line for line in lines}
    assert "F-104" in by_item["G-06"]["findings"] and "F-104" in by_item["G-07"]["findings"]


def test_b52_1_every_mapping_line_cites_a_governance_map_id_that_exists(tmp_path: Path) -> None:
    for client in ("contoso-dental", "fabrikam-capital"):
        root = _pack(client, tmp_path / client).root
        assert root is not None
        mapping = _read(root / "mapping.json")
        for regime in mapping["regimes"].values():
            for line in regime["lines"]:
                assert GOV_ID.fullmatch(line["governance_id"]), line
                assert f"`{line['governance_id']}`" in GOV_DOC
                assert set(line["controls"]) <= CONTROL_IDS
        for md in root.glob("*.md"):
            if md.name == "vendors.md":
                continue
            rows = [r for r in md.read_text(encoding="utf-8").splitlines() if re.match(r"\| [HGS]-\d+ ", r)]
            assert rows and all(GOV_CELL.search(r) for r in rows), md.name


def test_b52_1_items_without_a_finding_say_so_and_never_claim_a_pass(tmp_path: Path) -> None:
    root = _pack("contoso-dental", tmp_path).root
    assert root is not None
    empty = [line for line in _lines(root, "hipaa") if not line["findings"]]
    assert empty and all(line["status"] == "no finding supplied (not evidence that the item is met)" for line in empty)
    unmapped = _read(root / "mapping.json")["unmapped_findings"]
    assert [f["id"] for f in unmapped] == ["F-006"]
    for path in root.iterdir():
        assert not CLAIM_WORDS.search(path.read_text(encoding="utf-8")), path.name


def test_b52_1_a_pack_holds_one_client_only(tmp_path: Path) -> None:
    root = _pack("contoso-dental", tmp_path).root
    assert root is not None
    text = "".join(p.read_text(encoding="utf-8") for p in root.iterdir())
    for other in ("fabrikam", "Fabrikam", "F-101", "V-101", "litware-legal"):
        assert other not in text


def test_b52_1_unknown_control_or_governance_id_in_a_mapping_is_refused(tmp_path: Path, fixtures_copy: Path) -> None:
    path = fixtures_copy / "mappings.json"
    data = _read(path)
    data["regimes"]["hipaa"]["items"][0]["governance_id"] = "BA-99"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RegpackError, match="BA-99"):
        _pack("contoso-dental", tmp_path, fixtures_dir=fixtures_copy)
    data["regimes"]["hipaa"]["items"][0]["governance_id"] = "BA-2"
    data["regimes"]["hipaa"]["items"][0]["controls"] = ["C-999"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RegpackError, match="C-999"):
        _pack("contoso-dental", tmp_path, fixtures_dir=fixtures_copy)


# -- B52-2 ----------------------------------------------------------------------------------------------------------
def test_b52_2_vendor_tracker_lists_each_vendor_with_the_required_columns(tmp_path: Path) -> None:
    root = _pack("contoso-dental", tmp_path).root
    assert root is not None
    rows = _read(root / "vendors.json")["vendors"]
    assert [r["id"] for r in rows] == ["V-001", "V-002", "V-003", "V-004"]
    for row in rows:
        assert {"name", "data_classes", "contract_status", "baa_status", "review_date", "next_review_due"} <= set(row)
    page = (root / "vendors.md").read_text(encoding="utf-8")
    for row in rows:
        assert row["name"] in page and row["review_date"] in page
    assert "BA-1" in page and "C-43" in page


def test_b52_2_review_state_and_flags_follow_as_of_not_the_clock(tmp_path: Path) -> None:
    root = _pack("contoso-dental", tmp_path).root
    assert root is not None
    rows = {r["id"]: r for r in _read(root / "vendors.json")["vendors"]}
    assert rows["V-001"]["next_review_due"] == "2026-09-01" and rows["V-001"]["review_state"] == "overdue"
    assert rows["V-002"]["review_state"] == "current"
    assert "baa-not-signed" in rows["V-001"]["flags"] and "contract-expired" in rows["V-003"]["flags"]
    assert rows["V-004"]["flags"] == []
    later = _pack("contoso-dental", tmp_path / "later", as_of="2027-03-01").root
    assert later is not None
    assert {r["id"]: r["review_state"] for r in _read(later / "vendors.json")["vendors"]}["V-002"] == "due-soon"


def test_b52_2_financial_vendors_cite_service_provider_oversight_not_a_baa(tmp_path: Path) -> None:
    root = _pack("fabrikam-capital", tmp_path).root
    assert root is not None
    rows = {r["id"]: r for r in _read(root / "vendors.json")["vendors"]}
    assert set(rows) == {"V-101", "V-102", "V-103"}
    assert rows["V-101"]["review_state"] == "overdue" and "contract-unsigned" in rows["V-102"]["flags"]
    assert all("baa-not-signed" not in r["flags"] for r in rows.values())
    page = (root / "vendors.md").read_text(encoding="utf-8")
    assert "GLBA-3" in page and "C-43" in page


# -- B52-3 ----------------------------------------------------------------------------------------------------------
def test_b52_3_every_page_is_labelled_not_legal_advice(tmp_path: Path) -> None:
    assert LABEL == "mapping for the client's compliance owner; not legal advice"
    for client, count in (("contoso-dental", 2), ("fabrikam-capital", 3)):
        root = _pack(client, tmp_path / client).root
        assert root is not None
        pages = sorted(root.glob("*.md"))
        assert len(pages) == count
        for page in pages:
            text = page.read_text(encoding="utf-8")
            assert LABEL in text.splitlines()[2].lower(), page.name  # visible at the top, under the title
            assert LABEL in text.lower().splitlines()[-1], page.name  # and again at the foot
            assert "fixture-based" in text.lower() and "not a certification" in text.lower()


# -- B52-4 ----------------------------------------------------------------------------------------------------------
def test_b52_4_investment_adviser_maps_to_reg_s_p_and_is_marked_hedged(tmp_path: Path) -> None:
    root = _pack("fabrikam-capital", tmp_path).root
    assert root is not None
    lines = _lines(root, "sec-reg-s-p")
    assert [line["title"] for line in lines] == [
        "Incident response program",
        "Service-provider oversight",
        "Customer notice of unauthorized access",
    ]
    assert all(line["hedged"] is True and GOV_ID.fullmatch(line["governance_id"]) for line in lines)
    page = (root / "sec-reg-s-p.md").read_text(encoding="utf-8")
    assert page.count("HEDGED") >= 4  # banner plus each line
    assert "until checked against the rule text" in page
    assert _read(root / "mapping.json")["regimes"]["glba-ftc-safeguards"]["hedged"] is False


def test_b52_4_the_hipaa_pack_stays_for_a_healthcare_client_that_is_also_an_adviser(
    tmp_path: Path, fixtures_copy: Path
) -> None:
    _set_regimes(fixtures_copy, "contoso-dental", ["hipaa", "sec-reg-s-p"])
    root = _pack("contoso-dental", tmp_path, fixtures_dir=fixtures_copy).root
    assert root is not None
    assert (root / "hipaa.md").exists() and (root / "sec-reg-s-p.md").exists()
    assert not (root / "glba-ftc-safeguards.md").exists()


def test_b52_4_regimes_come_from_the_client_record_never_from_the_name(tmp_path: Path, fixtures_copy: Path) -> None:
    _set_regimes(fixtures_copy, "fabrikam-capital", [])
    with pytest.raises(RegpackError, match="no regimes"):
        _pack("fabrikam-capital", tmp_path, fixtures_dir=fixtures_copy)
    _set_regimes(fixtures_copy, "fabrikam-capital", ["made-up-regime"])
    with pytest.raises(RegpackError, match="made-up-regime"):
        _pack("fabrikam-capital", tmp_path, fixtures_dir=fixtures_copy)
    with pytest.raises(RegpackError, match="litware-legal"):  # regimes empty in the committed fixture too
        _pack("litware-legal", tmp_path)
    with pytest.raises(RegpackError, match="not a client"):
        _pack("Not A Client", tmp_path)


# -- dry run, determinism, verify, audit ----------------------------------------------------------------------------
def test_b52_dry_run_is_the_default_and_writes_nothing(tmp_path: Path) -> None:
    pack = _pack("contoso-dental", tmp_path, write=False)
    assert pack.written is False and pack.root is None
    assert not (tmp_path / "out").exists()
    assert {e["path"] for e in pack.manifest["files"]} >= {"hipaa.md", "mapping.json", "vendors.json", "vendors.md"}
    assert pack.manifest["labels"] == ["fixture-based", "not a certification", "not legal advice"]


def test_b52_same_inputs_give_the_same_manifest_hash_and_bytes(tmp_path: Path) -> None:
    a = _pack("fabrikam-capital", tmp_path / "a")
    b = _pack("fabrikam-capital", tmp_path / "b")
    dry = _pack("fabrikam-capital", tmp_path / "c", write=False)
    assert a.manifest_sha256 == b.manifest_sha256 == dry.manifest_sha256
    assert a.root is not None and b.root is not None
    for p in a.root.iterdir():
        assert p.read_bytes() == (b.root / p.name).read_bytes()
    assert _pack("fabrikam-capital", tmp_path / "d", as_of="2026-10-28").manifest_sha256 != a.manifest_sha256


def test_b52_manifest_has_unverified_list_and_makes_no_assertion(tmp_path: Path) -> None:
    pack = _pack("fabrikam-capital", tmp_path, write=False)
    unverified = " ".join(pack.manifest["unverified"])
    for needle in ("eCFR", "Regulation S-P", "applies", "synthetic"):
        assert needle in unverified
    assert pack.manifest["data_class"] == "DC-2" and pack.manifest["as_of"] == AS_OF
    assert "legal" in pack.manifest["note"].lower()


def test_b52_verify_passes_then_catches_edit_removal_and_extra_file(tmp_path: Path) -> None:
    pack = _pack("contoso-dental", tmp_path, write=True)
    root = pack.root
    assert root is not None
    assert verify_pack(root) == pack.manifest_sha256
    page = root / "hipaa.md"
    original = page.read_bytes()
    page.write_bytes(original + b"edit\n")
    with pytest.raises(VerifyError, match="hipaa.md"):
        verify_pack(root)
    page.write_bytes(original)
    page.unlink()
    with pytest.raises(VerifyError, match="missing"):
        verify_pack(root)
    page.write_bytes(original)
    (root / "extra.md").write_text("x", encoding="utf-8")
    with pytest.raises(VerifyError, match="extra.md"):
        verify_pack(root)
    (root / "extra.md").unlink()
    (root / "manifest.json.sha256").write_text("0" * 64 + "  manifest.json\n", encoding="ascii")
    with pytest.raises(VerifyError, match="sidecar"):
        verify_pack(root)


def test_b52_verify_with_audit_dir_needs_the_manifest_pinned_in_the_chain(tmp_path: Path) -> None:
    dry = _pack("contoso-dental", tmp_path, write=False)
    written = _pack("contoso-dental", tmp_path, write=True)
    assert written.root is not None
    assert verify_pack(written.root, tmp_path / "audit") == written.manifest_sha256 == dry.manifest_sha256
    other = _pack("contoso-dental", tmp_path / "other", as_of="2026-10-28", write=True)
    assert other.root is not None  # written under another audit dir; its hash is not in this chain
    with pytest.raises(VerifyError, match="not pinned"):
        verify_pack(other.root, tmp_path / "audit")
    with pytest.raises(VerifyError, match="no audit chain"):
        verify_pack(other.root, tmp_path / "audit-empty")
    chain = AuditRouter(tmp_path / "audit").path_for("contoso-dental")
    assert verify_chain(chain, None).ok


def test_b52_only_a_scoped_lead_may_build_and_refusals_are_audited(tmp_path: Path) -> None:
    for who in ("tech-ana", "triage-bot", "lead-nobody"):
        with pytest.raises(RegpackError):
            _pack("contoso-dental", tmp_path, by=who)
    with pytest.raises(RegpackError, match="not scoped"):
        _pack("litware-legal", tmp_path, by=LEAD)
    chain = AuditRouter(tmp_path / "audit").path_for("contoso-dental")
    records = [json.loads(x) for x in chain.read_text(encoding="utf-8").splitlines()]
    assert [r["result"]["status"] for r in records] == ["denied"] * 3
    assert {r["agent"] for r in records} == {"tech-ana", "triage-bot", "lead-nobody"}
    assert not (tmp_path / "out").exists()
    ok = _pack("contoso-dental", tmp_path, write=False)
    last = json.loads(chain.read_text(encoding="utf-8").splitlines()[-1])
    assert last["result"]["status"] == "ok" and last["mode"] == "dry-run" and last["lever"] == "regpack.build"
    assert "".join(last["result"]["sha256"].split()) == ok.manifest_sha256
    assert "F-001" not in json.dumps(last)  # rows never go into the audit record


def test_b52_cli_dry_run_write_and_verify(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = ["--as", LEAD, "--as-of", AS_OF, "--out", str(tmp_path / "out"), "--audit-dir", str(tmp_path / "audit")]
    assert main(["build", "contoso-dental", *base]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["written"] is False and not (tmp_path / "out").exists()
    assert main(["build", "contoso-dental", *base, "--write"]) == 0
    done = json.loads(capsys.readouterr().out)
    assert done["written"] is True and done["sha256"] == first["sha256"]
    assert main(["verify", done["path"], "--audit-dir", str(tmp_path / "audit")]) == 0
    assert capsys.readouterr().out.startswith("OK ")
    (Path(done["path"]) / "vendors.md").write_text("changed", encoding="utf-8")
    assert main(["verify", done["path"]]) == 1
    assert main(["build", "litware-legal", *base]) == 2
    assert main(["build", "contoso-dental", "--as", "tech-ana", "--as-of", AS_OF, *base[4:]]) == 2
