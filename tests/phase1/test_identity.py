"""Identity store (specs/phase-1.md deliverable 1): per-client scoping, unknown ids, fail-closed loading."""

import json
from pathlib import Path

import pytest

from core.identity import Identity, IdentityConfigError, IdentityStore, Role, UnknownIdentity, role_satisfies

CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"


@pytest.fixture(scope="module")
def store() -> IdentityStore:
    return IdentityStore.load()


def test_config_has_the_five_synthetic_identities(store: IdentityStore) -> None:
    expected = {
        "tech-ana": (Role.TECHNICIAN, (CONTOSO,)),
        "tech-ben": (Role.TECHNICIAN, (FABRIKAM,)),
        "lead-lee": (Role.LEAD, (CONTOSO, FABRIKAM)),
        # B-28 dual approval (D-067, W3-E1): a second synthetic lead, so an R3 lever can get two distinct approvers.
        "lead-mia": (Role.LEAD, (CONTOSO, FABRIKAM)),
        "triage-bot": (Role.AGENT, (CONTOSO, FABRIKAM)),
    }
    assert len(store) == len(expected)
    for identity_id, (role, clients) in expected.items():
        identity = store.get(identity_id)
        assert (identity.role, identity.clients) == (role, clients)


def test_p1_1_technician_is_scoped_to_its_own_client(store: IdentityStore) -> None:
    ana = store.get("tech-ana")
    assert ana.can_act_for(CONTOSO)
    assert not ana.can_act_for(FABRIKAM)


def test_unknown_identity_is_refused(store: IdentityStore) -> None:
    with pytest.raises(UnknownIdentity):
        store.get("mallory")
    assert "mallory" not in store


def test_roles_are_ranked_agent_technician_lead() -> None:
    assert role_satisfies(Role.LEAD, Role.TECHNICIAN)
    assert role_satisfies(Role.TECHNICIAN, Role.TECHNICIAN)
    assert not role_satisfies(Role.AGENT, Role.TECHNICIAN)
    assert not role_satisfies(Role.TECHNICIAN, Role.LEAD)


def test_identity_is_immutable(store: IdentityStore) -> None:
    with pytest.raises(ValueError, match="frozen"):
        store.get("tech-ana").role = Role.LEAD  # type: ignore[misc]


GOOD = {"id": "tech-x", "display_name": "X", "role": "technician", "clients": [CONTOSO]}


@pytest.mark.parametrize(
    ("label", "content"),
    [
        ("not json", "{nope"),
        ("wrong version", json.dumps({"version": 2, "identities": [GOOD]})),
        ("no identities", json.dumps({"version": 1, "identities": []})),
        ("unknown role", json.dumps({"version": 1, "identities": [{**GOOD, "role": "admin"}]})),
        ("empty client list", json.dumps({"version": 1, "identities": [{**GOOD, "clients": []}]})),
        ("duplicate client", json.dumps({"version": 1, "identities": [{**GOOD, "clients": [CONTOSO, CONTOSO]}]})),
        ("unexpected field", json.dumps({"version": 1, "identities": [{**GOOD, "is_admin": True}]})),
        ("bad id", json.dumps({"version": 1, "identities": [{**GOOD, "id": "../etc"}]})),
        ("duplicate id", json.dumps({"version": 1, "identities": [GOOD, GOOD]})),
    ],
)
def test_bad_identity_file_fails_closed(tmp_path: Path, label: str, content: str) -> None:
    path = tmp_path / "identities.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(IdentityConfigError):
        IdentityStore.load(path)


def test_missing_identity_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(IdentityConfigError):
        IdentityStore.load(tmp_path / "absent.json")


def test_store_can_be_built_in_code() -> None:
    store = IdentityStore([Identity(id="lead-zoe", display_name="Zoe", role=Role.LEAD, clients=(FABRIKAM,))])
    assert store.get("lead-zoe").role is Role.LEAD
