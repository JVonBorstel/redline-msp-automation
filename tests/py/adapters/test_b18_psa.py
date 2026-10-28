"""B-18 adapter base, per-client bindings and the PSA mock.

Acceptance ids B18-1 to B18-4 are defined in specs/B-18.md. Offline and deterministic: client configs are
private files under tmp_path, committed fixtures are only read.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/adapters
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from adapters import (
    REAL_ADAPTER_NOT_CONFIGURED,
    AdapterError,
    BoundBinding,
    ClientConfigError,
    PsaAdapter,
    PsaMock,
    build_adapter,
    load_client,
)
from adapters.psa.mock import DEFAULT_PSA_DIR
from core.paths import REPO_ROOT

COMPANIES = {"contoso-dental": "30001", "fabrikam-capital": "30002"}


def _config(client: str, **overrides: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "version": 1,
        "_note": "Synthetic test client.",
        "id": client,
        "display_name": client,
        "psa_company_id": COMPANIES[client],
        "industry": "other",
        "regimes": [],
        "model_processing": "none",
        "retention_class": "standard",
        "enabled_levers": ["ticket.get"],
        "bindings": {
            "psa": {
                "implementation": "mock",
                "external_id": COMPANIES[client],
                "credential_ref": f"client-{client}-psa",
            }
        },
    }
    cfg.update(overrides)
    return cfg


def _write(root: Path, cfg: dict[str, Any], name: str | None = None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name or cfg['id']}.json").write_text(json.dumps(cfg), encoding="utf-8")


@pytest.fixture()
def cfg_dir(tmp_path: Path) -> Path:
    root = tmp_path / "clients"
    for client in COMPANIES:
        _write(root, _config(client))
    return root


def _mock(cfg_dir: Path, client: str) -> PsaMock:
    built = build_adapter(client, "psa", config_dir=cfg_dir)
    assert built.ok, built.reason
    assert isinstance(built.adapter, PsaMock)
    return built.adapter


# --- B18-1 ---------------------------------------------------------------------------------------------------
def test_b18_1_adapter_is_built_for_one_client_from_its_binding(cfg_dir: Path) -> None:
    a = _mock(cfg_dir, "contoso-dental")
    assert isinstance(a, PsaAdapter)
    assert a.client == "contoso-dental"
    assert a.external_id == "30001"
    assert a.credential_ref == "client-contoso-dental-psa"


def test_b18_1_binding_of_another_client_is_refused_at_construction() -> None:
    other = BoundBinding("fabrikam-capital", "psa", "mock", "30002", "client-fabrikam-capital-psa")
    with pytest.raises(AdapterError, match="different client"):
        PsaMock("contoso-dental", other)


def test_b18_1_binding_for_another_system_is_refused() -> None:
    rmm = BoundBinding("contoso-dental", "rmm", "mock", "30001")
    with pytest.raises(AdapterError, match="not 'psa'"):
        PsaMock("contoso-dental", rmm)


def test_b18_1_a_binding_cannot_be_pointed_at_another_clients_fixture(tmp_path: Path) -> None:
    # Contoso's binding (company 30001) with Fabrikam's data copied under Contoso's file name: refused.
    root = tmp_path / "psa"
    root.mkdir()
    data = json.loads((DEFAULT_PSA_DIR / "fabrikam-capital.json").read_text(encoding="utf-8"))
    (root / "contoso-dental.json").write_text(json.dumps(data), encoding="utf-8")
    binding = BoundBinding("contoso-dental", "psa", "mock", "30001")
    with pytest.raises(AdapterError, match="does not belong"):
        PsaMock("contoso-dental", binding, root)
    # And a fixture whose company id does not match the binding's external id is refused too.
    data["client"] = "contoso-dental"
    (root / "contoso-dental.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(AdapterError, match="does not belong"):
        PsaMock("contoso-dental", binding, root)


def test_b18_1_asking_for_another_clients_ticket_is_refused_without_an_oracle(cfg_dir: Path) -> None:
    a = _mock(cfg_dir, "contoso-dental")
    other = a.get_ticket("T-3201")  # Fabrikam's ticket
    absent = a.get_ticket("T-9999")
    assert not other.ok and not absent.ok
    assert other.reason == absent.reason == "no such ticket for this client"
    assert other.data is None
    assert not a.list_ticket_notes("T-3201").ok
    assert a.get_ticket("70201").ok is False  # numeric id of Fabrikam's ticket
    assert a.get_contact(40101).ok is False  # Fabrikam's contact


def test_b18_1_listings_hold_only_the_bound_company(cfg_dir: Path) -> None:
    for client, company in COMPANIES.items():
        a = _mock(cfg_dir, client)
        tickets = a.list_tickets().data or []
        contacts = a.list_contacts().data or []
        assert tickets and contacts
        assert {str(t["companyID"]) for t in tickets} == {company}
        assert {str(c["companyID"]) for c in contacts} == {company}
        assert str((a.get_company().data or {})["id"]) == company


def test_b18_1_client_id_is_a_slug_never_a_path(cfg_dir: Path) -> None:
    for bad in ("../contoso-dental", "Contoso", "a/b", ""):
        built = build_adapter(bad, "psa", config_dir=cfg_dir)
        assert not built.ok
        with pytest.raises(ClientConfigError):
            load_client(bad, cfg_dir)
    with pytest.raises(AdapterError):
        PsaMock("../x", BoundBinding("../x", "psa", "mock", "30001"))


def test_b18_1_config_id_must_match_file_name(cfg_dir: Path) -> None:
    _write(cfg_dir, _config("fabrikam-capital"), name="contoso-dental")
    built = build_adapter("contoso-dental", "psa", config_dir=cfg_dir)
    assert not built.ok and "does not match the file name" in built.reason


def test_b18_1_psa_binding_must_equal_psa_company_id(cfg_dir: Path) -> None:
    cfg = _config("contoso-dental")
    cfg["bindings"]["psa"]["external_id"] = "30002"
    _write(cfg_dir, cfg)
    built = build_adapter("contoso-dental", "psa", config_dir=cfg_dir)
    assert not built.ok and "psa_company_id" in built.reason


def test_b18_1_missing_unreadable_and_unknown_field_configs_fail_closed(cfg_dir: Path) -> None:
    assert not build_adapter("litware-legal", "psa", config_dir=cfg_dir).ok  # no file
    (cfg_dir / "litware-legal.json").write_text("{not json", encoding="utf-8")
    assert "litware-legal.json" in build_adapter("litware-legal", "psa", config_dir=cfg_dir).reason
    _write(cfg_dir, _config("contoso-dental", surprise=1))
    built = build_adapter("contoso-dental", "psa", config_dir=cfg_dir)
    assert not built.ok and "contoso-dental.json" in built.reason
    cfg = _config("contoso-dental")
    del cfg["model_processing"]  # no silent default for the model switch (D6-11)
    _write(cfg_dir, cfg)
    assert not build_adapter("contoso-dental", "psa", config_dir=cfg_dir).ok


def test_b18_1_missing_binding_is_a_result_not_an_exception(cfg_dir: Path) -> None:
    built = build_adapter("contoso-dental", "rmm", config_dir=cfg_dir)
    assert not built.ok and built.adapter is None and "no 'rmm' binding" in built.reason


# --- B18-2 ---------------------------------------------------------------------------------------------------
def test_b18_2_mock_serves_tickets_contacts_companies_and_sla_settings(cfg_dir: Path) -> None:
    a = _mock(cfg_dir, "contoso-dental")
    ticket = a.get_ticket("T-3101")
    assert ticket.ok and ticket.reason == "ok"
    assert (ticket.data or {})["title"] == "Phone in the lake, Authenticator gone"
    assert a.get_ticket("70101").data == ticket.data  # by numeric id too
    assert (a.get_contact(40001).data or {})["lastName"] == "Nair"
    assert (a.get_company().data or {})["companyName"].startswith("Contoso Dental")
    sla = a.get_sla_settings()
    assert sla.ok and (sla.data or [])[0]["firstResponseHours"] == 1
    assert [n["id"] for n in a.list_ticket_notes("T-3101").data or []] == [90001]
    assert a.list_ticket_notes("T-3102").data == []
    assert [r["userName"] for r in a.list_resources().data or []] == ["tech-ana"]
    assert [t["ticketNumber"] for t in a.list_tickets(status=1).data or []] == ["T-3101", "T-3102"]
    assert a.list_tickets(status=5).data == []


def test_b18_2_results_are_copies_and_fixtures_are_never_modified(cfg_dir: Path) -> None:
    before = (DEFAULT_PSA_DIR / "contoso-dental.json").read_bytes()
    a = _mock(cfg_dir, "contoso-dental")
    t = a.get_ticket("T-3101").data or {}
    t["title"] = "tampered"
    (a.list_tickets().data or []).clear()
    assert (a.get_ticket("T-3101").data or {})["title"] != "tampered"
    assert len(a.list_tickets().data or []) == 2
    assert (DEFAULT_PSA_DIR / "contoso-dental.json").read_bytes() == before


def test_b18_2_a_crash_inside_a_call_becomes_a_failed_result(cfg_dir: Path) -> None:
    a = _mock(cfg_dir, "contoso-dental")
    a._data["tickets"] = [None]  # corrupt state after construction: .get on None raises AttributeError
    res = a.get_ticket("T-3101")
    assert res.ok is False and res.data is None
    assert res.reason == "PsaMock crashed: AttributeError"


def test_b18_2_every_public_call_returns_a_typed_result(cfg_dir: Path) -> None:
    a = _mock(cfg_dir, "contoso-dental")
    calls = [
        a.get_company(),
        a.list_contacts(),
        a.get_contact(1),
        a.list_tickets(),
        a.get_ticket("x"),
        a.list_ticket_notes("x"),
        a.list_resources(),
        a.get_sla_settings(),
    ]
    for res in calls:
        assert isinstance(res.ok, bool) and isinstance(res.reason, str) and res.reason
        assert (res.data is not None) == res.ok


# --- B18-3 ---------------------------------------------------------------------------------------------------
def _fake_secret() -> str:
    return "sk-" + "a1B2c3D4" * 4  # built at runtime; looks like a key, is not one


def test_b18_3_a_credential_value_in_a_binding_fails_validation(cfg_dir: Path) -> None:
    secret = _fake_secret()
    for value in (secret, "hunter2", "Bearer " + secret, "client-contoso-dental"):
        cfg = _config("contoso-dental")
        cfg["bindings"]["psa"]["credential_ref"] = value
        _write(cfg_dir, cfg)
        with pytest.raises(ClientConfigError) as err:
            load_client("contoso-dental", cfg_dir)
        assert "credential_ref" in str(err.value)
        assert value not in str(err.value)  # the value is never echoed (it may be a real secret)
        assert not build_adapter("contoso-dental", "psa", config_dir=cfg_dir).ok


def test_b18_3_a_credential_name_must_carry_the_clients_own_id(cfg_dir: Path) -> None:
    cfg = _config("contoso-dental")
    cfg["bindings"]["psa"]["credential_ref"] = "client-fabrikam-capital-psa"
    _write(cfg_dir, cfg)
    with pytest.raises(ClientConfigError, match="own secret"):
        load_client("contoso-dental", cfg_dir)


def test_b18_3_real_implementations_fail_closed(cfg_dir: Path) -> None:
    cfg = _config("contoso-dental")
    cfg["bindings"]["psa"]["implementation"] = "autotask"
    _write(cfg_dir, cfg)
    built = build_adapter("contoso-dental", "psa", config_dir=cfg_dir)
    assert not built.ok and built.adapter is None
    assert built.reason == REAL_ADAPTER_NOT_CONFIGURED == "real adapter not configured"
    # The mock class itself also refuses a binding that names a real implementation.
    with pytest.raises(AdapterError):
        PsaMock("contoso-dental", BoundBinding("contoso-dental", "psa", "autotask", "30001"))


def test_b18_3_config_pattern_matches_the_committed_schema() -> None:
    schema = json.loads((REPO_ROOT / "schemas" / "client.schema.json").read_text(encoding="utf-8"))
    from adapters import binding

    defs = schema["$defs"]
    assert defs["CredentialRef"]["pattern"] == binding.CREDENTIAL_REF.pattern
    assert defs["Implementation"]["pattern"] == binding.IMPLEMENTATION.pattern
    assert defs["Binding"]["properties"]["external_id"]["pattern"] == binding.EXTERNAL_ID.pattern
    assert schema["properties"]["id"]["pattern"] == binding.CLIENT_ID.pattern


def test_b18_3_no_secret_shaped_values_in_fixtures_or_package() -> None:
    pattern = re.compile(r"sk-[A-Za-z0-9]{16,}|eyJ[A-Za-z0-9_-]{10,}|Bearer\s+\S{16,}")
    for path in [*(REPO_ROOT / "adapters").rglob("*.py"), *(REPO_ROOT / "fixtures" / "psa").glob("*")]:
        assert not pattern.search(path.read_text(encoding="utf-8")), path


# --- B18-4 ---------------------------------------------------------------------------------------------------
_ENTITIES = {
    "company": "Companies",
    "contacts": "Contacts",
    "tickets": "Tickets",
    "ticketNotes": "TicketNotes",
    "resources": "Resources",
    "slaSettings": "ServiceLevelAgreements",
}


def _spec_rows() -> dict[tuple[str, str], str]:
    text = (REPO_ROOT / "specs" / "B-18.md").read_text(encoding="utf-8")
    rows = {}
    for m in re.finditer(r"^\| (\w+) \| `(\w+)` \| (.+) \|$", text, re.M):
        rows[(m.group(1), m.group(2))] = m.group(3)
    return rows


def test_b18_4_every_fixture_field_is_marked_verified_or_unverified_in_the_spec() -> None:
    rows = _spec_rows()
    for client in COMPANIES:
        data = json.loads((DEFAULT_PSA_DIR / f"{client}.json").read_text(encoding="utf-8"))
        for key, entity in _ENTITIES.items():
            records = data[key] if isinstance(data[key], list) else [data[key]]
            for rec in records:
                for field in rec:
                    status = rows.get((entity, field))
                    assert status is not None, f"{entity}.{field} missing from specs/B-18.md"
                    assert "Verified" in status or "UNVERIFIED" in status


def test_b18_4_fixtures_are_synthetic_labelled_and_match_their_file_name() -> None:
    for client, company in COMPANIES.items():
        data = json.loads((DEFAULT_PSA_DIR / f"{client}.json").read_text(encoding="utf-8"))
        assert data["client"] == client
        assert "synthetic" in data["_note"].lower()
        assert str(data["company"]["id"]) == company
        text = json.dumps(data)
        assert ".example" in text
        assert not re.search(r"@(?!.*\.example)[\w.-]+\.(com|net|org)\b", text.replace("msp.example", ""))
        assert (DEFAULT_PSA_DIR / "SOURCES.md").is_file()


def test_b18_4_the_interface_is_vendor_neutral() -> None:
    src = (REPO_ROOT / "adapters" / "psa" / "base.py").read_text(encoding="utf-8")
    assert "autotask" not in src.lower().replace("public autotask rest entities", "")
    # No Autotask-only call shape (query filters, picklist ids) leaks into the method signatures.
    names = {n for n in dir(PsaAdapter) if not n.startswith("_") and callable(getattr(PsaAdapter, n))}
    assert {"get_company", "list_contacts", "get_ticket", "list_ticket_notes", "get_sla_settings"} <= names


def test_b18_4_a_second_vendor_is_the_same_seam(cfg_dir: Path) -> None:
    class HaloStub(PsaAdapter):
        """A stand-in for a ConnectWise or Halo adapter: it only has to implement the interface."""

        def get_company(self) -> Any: ...
        def list_contacts(self) -> Any: ...
        def get_contact(self, contact_id: int) -> Any: ...
        def list_tickets(self, status: int | None = None) -> Any: ...
        def get_ticket(self, ticket: str) -> Any: ...
        def list_ticket_notes(self, ticket: str) -> Any: ...
        def list_resources(self) -> Any: ...
        def get_sla_settings(self) -> Any: ...

    b = BoundBinding("contoso-dental", "psa", "halo", "30001", "client-contoso-dental-psa")
    stub = HaloStub("contoso-dental", b)
    assert stub.client == "contoso-dental"
    with pytest.raises(AdapterError):  # the one-client rule is in the base, so every vendor gets it
        HaloStub("fabrikam-capital", b)


def test_adapters_do_not_import_network_libraries() -> None:
    for path in (REPO_ROOT / "adapters").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import|from)\s+(socket|http|urllib|requests|httpx|ssl)\b", text, re.M), path
