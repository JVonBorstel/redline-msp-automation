"""B-19 Graph mock adapter with per-family state.

Acceptance ids B19-1 to B19-3 are defined in specs/B-19.md. Offline and deterministic: tenant fixtures are
copied to tmp_path, committed files are only read.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/adapters/test_b19_graph.py
"""

from __future__ import annotations

import copy
import inspect
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

import adapters.graph.mock as graph_mock_module
from adapters import AdapterError, BoundBinding
from adapters.graph import GraphAdapter, GraphMock, build_graph_adapter
from core.audit import AuditLog
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, LeverRunner, MockTenant, Registry
from core.paths import REPO_ROOT

CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
TENANTS = {CONTOSO: "c0000000-0000-4000-8000-000000000001", FABRIKAM: "f0000000-0000-4000-8000-000000000002"}


def _binding(client: str, impl: str = "mock") -> BoundBinding:
    return BoundBinding(client, "m365", impl, TENANTS[client], f"client-{client}-m365")


def _family(client: str, **extra: Any) -> dict[str, Any]:
    return {"_meta": {"client": client, "note": "Synthetic test family."}, "items": [{"id": f"{client}-1"}], **extra}


def _put_family(root: Path, client: str, family: str, data: dict[str, Any]) -> Path:
    d = root / client
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{family}.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


@pytest.fixture()
def tenants(tmp_path: Path) -> Path:
    root = tmp_path / "tenant"
    shutil.copytree(DEFAULT_TENANT_DIR, root)
    return root


def _mock(root: Path, client: str = CONTOSO) -> GraphMock:
    return GraphMock(client, _binding(client), root)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# --- B19-1 ---------------------------------------------------------------------------------------------------
def test_b19_1_reads_the_base_tenant_file(tenants: Path) -> None:
    g = _mock(tenants)
    assert isinstance(g, GraphAdapter)
    assert g.client == CONTOSO
    base = json.loads((tenants / f"{CONTOSO}.json").read_text(encoding="utf-8"))
    assert g.state().data == base
    assert [u["id"] for u in g.list_users().data or []] == [u["id"] for u in base["users"]]
    upn = base["users"][0]["userPrincipalName"]
    assert (g.get_user(upn).data or {})["userPrincipalName"] == upn
    assert (g.get_user(upn.upper()).data or {})["id"] == base["users"][0]["id"]
    methods = g.list_authentication_methods(upn)
    assert methods.ok and methods.data == base["users"][0]["authentication"]["methods"]


def test_b19_1_reads_optional_family_files(tenants: Path) -> None:
    g = _mock(tenants)
    shipped = list(g.families().data or [])  # families other items ship (B-39 signins) are not this test's business
    assert "gizmos" not in shipped
    assert g.family_state("gizmos").reason == "no such family state for this client"
    _put_family(tenants, CONTOSO, "gizmos", _family(CONTOSO))
    _put_family(tenants, CONTOSO, "licenses", _family(CONTOSO))
    (tenants / CONTOSO / "Not A Slug.json").write_text("{}", encoding="utf-8")
    assert g.families().data == sorted({*shipped, "gizmos", "licenses"})  # B-31 ships a licenses family too
    fam = g.family_state("gizmos")
    assert fam.ok and (fam.data or {})["items"] == [{"id": f"{CONTOSO}-1"}]


def test_b19_1_a_family_file_for_another_client_is_never_read(tenants: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _put_family(tenants, FABRIKAM, "gizmos", _family(FABRIKAM))
    opened: list[str] = []
    real_read_text = Path.read_text

    def spy(self: Path, *a: Any, **k: Any) -> str:
        opened.append(str(self))
        return real_read_text(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", spy)
    g = _mock(tenants)
    assert not g.family_state("gizmos").ok  # Fabrikam has one, Contoso does not
    g.state()
    g.list_users()
    g.families()
    other = str(tenants / FABRIKAM)
    assert not [p for p in opened if p.startswith(other) or p.endswith(f"{FABRIKAM}.json")]


def test_b19_1_a_family_file_that_names_another_client_is_refused(tenants: Path) -> None:
    # Fabrikam's data copied under Contoso's folder: the _meta.client check refuses it.
    _put_family(tenants, CONTOSO, "gizmos", _family(FABRIKAM))
    r = _mock(tenants).family_state("gizmos")
    assert not r.ok and r.data is None
    assert r.reason == "family state does not belong to this client"
    _put_family(tenants, CONTOSO, "licenses", {"items": []})  # no _meta at all
    assert not _mock(tenants).family_state("licenses").ok


def test_b19_1_family_names_are_slugs_never_paths(tenants: Path) -> None:
    _put_family(tenants, FABRIKAM, "gizmos", _family(FABRIKAM))
    g = _mock(tenants)
    for bad in ("../fabrikam-capital/gizmos", "..", "a/b", "A", "", "x" * 40, "a.json"):
        r = g.family_state(bad)
        assert not r.ok and r.reason == "invalid family name"


def test_b19_1_binding_of_another_client_or_system_is_refused(tenants: Path) -> None:
    with pytest.raises(AdapterError, match="different client"):
        GraphMock(CONTOSO, _binding(FABRIKAM), tenants)
    with pytest.raises(AdapterError, match="not 'm365'"):
        GraphMock(CONTOSO, BoundBinding(CONTOSO, "psa", "mock", "30001"), tenants)


def test_b19_1_base_file_of_another_client_under_this_name_is_refused(tenants: Path) -> None:
    shutil.copy(tenants / f"{FABRIKAM}.json", tenants / f"{CONTOSO}.json")
    with pytest.raises(AdapterError, match="does not belong to this client"):
        _mock(tenants)


def test_b19_1_a_tenant_id_in_the_fixture_must_match_the_binding(tenants: Path) -> None:
    p = tenants / f"{CONTOSO}.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["_meta"]["tenantId"] = TENANTS[FABRIKAM]
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(AdapterError, match="tenant binding"):
        _mock(tenants)
    data["_meta"]["tenantId"] = TENANTS[CONTOSO]
    p.write_text(json.dumps(data), encoding="utf-8")
    assert _mock(tenants).state().ok


def test_b19_1_lookup_of_another_clients_user_looks_like_an_absent_one(tenants: Path) -> None:
    g = _mock(tenants)
    fab = json.loads((tenants / f"{FABRIKAM}.json").read_text(encoding="utf-8"))["users"][0]
    other = g.get_user(fab["userPrincipalName"])
    absent = g.get_user("nobody@contosodental.example")
    assert not other.ok and not absent.ok
    assert other.reason == absent.reason == "no such user for this client"
    assert not g.get_user(fab["id"]).ok
    assert not g.list_authentication_methods(fab["userPrincipalName"]).ok


def test_b19_1_invalid_client_id_and_missing_state_fail_closed(tenants: Path) -> None:
    for bad in ("../contoso-dental", "Contoso", "a/b", ""):
        with pytest.raises(AdapterError):
            GraphMock(bad, BoundBinding(bad, "m365", "mock", TENANTS[CONTOSO]), tenants)
    (tenants / f"{CONTOSO}.json").unlink()
    with pytest.raises(AdapterError, match="no readable tenant state"):
        _mock(tenants)


def _write_config(root: Path, client: str, impl: str = "mock", with_binding: bool = True) -> None:
    cfg: dict[str, Any] = {
        "version": 1,
        "_note": "Synthetic test client.",
        "id": client,
        "display_name": client,
        "psa_company_id": "30001",
        "industry": "other",
        "regimes": [],
        "model_processing": "none",
        "retention_class": "standard",
        "enabled_levers": ["user.disable"],
        "bindings": {"psa": {"implementation": "mock", "external_id": "30001"}},
    }
    if with_binding:
        cfg["bindings"]["m365"] = {
            "implementation": impl,
            "external_id": TENANTS[client],
            "credential_ref": f"client-{client}-m365",
            "access": "gdap",
        }
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{client}.json").write_text(json.dumps(cfg), encoding="utf-8")


def test_b19_1_builder_uses_the_clients_m365_binding_and_fails_closed(tmp_path: Path, tenants: Path) -> None:
    cfgs = tmp_path / "clients"
    _write_config(cfgs, CONTOSO)
    built = build_graph_adapter(CONTOSO, config_dir=cfgs, tenant_dir=tenants)
    assert built.ok and isinstance(built.adapter, GraphMock) and built.adapter.client == CONTOSO
    _write_config(cfgs, CONTOSO, impl="graph-live")
    real = build_graph_adapter(CONTOSO, config_dir=cfgs, tenant_dir=tenants)
    assert not real.ok and real.reason == "real adapter not configured" and real.adapter is None
    _write_config(cfgs, CONTOSO, with_binding=False)
    assert build_graph_adapter(CONTOSO, config_dir=cfgs, tenant_dir=tenants).reason == "client has no 'm365' binding"
    assert not build_graph_adapter("../x", config_dir=cfgs, tenant_dir=tenants).ok
    assert not build_graph_adapter("nobody", config_dir=cfgs, tenant_dir=tenants).ok


# --- B19-2 ---------------------------------------------------------------------------------------------------
def test_b19_2_state_reads_return_copies(tenants: Path) -> None:
    _put_family(tenants, CONTOSO, "gizmos", _family(CONTOSO))
    g = _mock(tenants)
    before = _snapshot(tenants)
    first = g.state().data or {}
    expected = copy.deepcopy(first)
    first["users"].clear()
    first["_meta"]["client"] = "evil"
    users = g.list_users().data or []
    users[0]["accountEnabled"] = "tampered"
    user = g.get_user(users[0]["id"]).data or {}
    user["authentication"]["methods"].clear()
    (g.list_authentication_methods(users[0]["id"]).data or []).clear()
    fam = g.family_state("gizmos").data or {}
    fam["items"].append({"id": "x"})
    assert g.state().data == expected
    assert (g.get_user(users[0]["id"]).data or {})["authentication"]["methods"]
    assert (g.family_state("gizmos").data or {})["items"] == [{"id": f"{CONTOSO}-1"}]
    assert _snapshot(tenants) == before


def test_b19_2_the_adapter_has_no_write_path() -> None:
    public = [n for n, _ in inspect.getmembers(GraphMock, inspect.isfunction) if not n.startswith("_")]
    assert {"state", "families", "family_state", "list_users", "get_user", "list_authentication_methods"} <= set(public)
    assert not [n for n in public if re.match(r"(set|save|write|update|delete|put|add|remove|create)", n)]
    src = inspect.getsource(graph_mock_module)
    assert not re.search(r"write_text|write_bytes|os\.replace|\.save\(|open\([^)]*[\"'][wa+]", src)


def test_b19_2_writes_go_only_through_the_runners_diff_and_save_path(tenants: Path, tmp_path: Path) -> None:
    g = _mock(tenants)
    before = _snapshot(tenants)
    runner = LeverRunner(Registry.load(), IdentityStore.load(), MockTenant(tenants), AuditLog(tmp_path / "audit.jsonl"))
    upn = "jamie.chen@contosodental.example"
    # A dry-run shows the diff and saves nothing: the adapter sees no change.
    res = runner.invoke(
        "user.disable", {"upn": upn, "reason": "Left the practice (ticket T-1002)"}, "triage-bot", CONTOSO
    )
    assert res.diff and _snapshot(tenants) == before
    assert (g.get_user(upn).data or {})["accountEnabled"] is True
    # The runner's save path (MockTenant.save) is what changes state; the adapter re-reads it on the next call.
    working = MockTenant(tenants).load(CONTOSO)
    for u in working["users"]:
        if u["userPrincipalName"] == upn:
            u["accountEnabled"] = False
    MockTenant(tenants).save(CONTOSO, working)
    assert (g.get_user(upn).data or {})["accountEnabled"] is False


def test_b19_2_a_read_through_the_runner_changes_nothing(tenants: Path, tmp_path: Path) -> None:
    before = _snapshot(tenants)
    g = _mock(tenants)
    g.state(), g.list_users(), g.families()
    assert _snapshot(tenants) == before


# --- B19-3 ---------------------------------------------------------------------------------------------------
SOURCES = REPO_ROOT / "fixtures" / "graph" / "SOURCES.md"


def test_b19_3_sources_lists_each_new_shape_with_learn_page_and_status() -> None:
    text = SOURCES.read_text(encoding="utf-8")
    assert "## Tenant state shapes (B-19)" in text
    section = text.split("## Tenant state shapes (B-19)", 1)[1]
    for page in (
        "learn.microsoft.com/en-us/graph/api/resources/user?view=graph-rest-1.0",
        "learn.microsoft.com/en-us/graph/api/authentication-list-methods?view=graph-rest-1.0",
        "learn.microsoft.com/en-us/graph/api/resources/phoneauthenticationmethod?view=graph-rest-1.0",
    ):
        assert page in section
    for shape in ("users[]", "users[].authentication.methods[]", "phoneAuthenticationMethod", "Family file"):
        assert shape in section
    rows = [ln for ln in section.splitlines() if ln.startswith("| `") or ln.startswith("| Family")]
    assert rows
    for row in rows:
        assert re.search(r"Verified 2026-10-21|UNVERIFIED|Synthetic", row), row


def test_b19_3_every_user_field_in_the_tenant_fixtures_is_listed_in_sources() -> None:
    section = SOURCES.read_text(encoding="utf-8").split("## Tenant state shapes (B-19)", 1)[1]
    fields: set[str] = set()
    for path in DEFAULT_TENANT_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for u in data["users"]:
            fields |= set(u) - {"authentication"}
            for m in u.get("authentication", {}).get("methods", []):
                fields |= set(m)
    missing = sorted(f for f in fields if f"`{f}`" not in section)
    assert not missing, missing
