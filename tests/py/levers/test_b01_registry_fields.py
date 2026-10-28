"""B-01 registry fields: risk class, reversibility, undo, lever version, impact trace, verification rule.

Acceptance ids B01-1 to B01-4 are defined in specs/B-01.md. Every test is offline and works on a private
copy of the registry file (tmp_path) or of the synthetic mock tenant; committed files are never modified.
Run: uv run --frozen pytest tests/py/levers
"""

from __future__ import annotations

import copy
import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from core.audit import AuditLog
from core.identity import IdentityStore
from core.levers import (
    DEFAULT_REGISTRY_PATH,
    DEFAULT_TENANT_DIR,
    Approval,
    LeverDef,
    LeverRunner,
    MockTenant,
    Registry,
    RegistryError,
)
from core.levers.handlers import HANDLERS
from core.levers.models import Verification

CONTOSO = "contoso-dental"
JAMIE = "jamie.chen@contosodental.example"
DISABLE_JAMIE = {"upn": JAMIE, "reason": "Left the practice (ticket T-1002)"}
WRITE_LEVERS = ("user.reset-mfa", "user.disable")
READ_LEVERS = ("ticket.get", "kb.search")
AT = datetime(2026, 10, 21, 15, 30, tzinfo=UTC)

Mutate = Callable[[dict[str, Any]], None]


def _raw() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    return data


def _lever(raw: dict[str, Any], name: str) -> dict[str, Any]:
    entry: dict[str, Any] = next(x for x in raw["levers"] if x["name"] == name)
    return entry


def _write(tmp_path: Path, mutate: Mutate) -> Path:
    raw = _raw()
    mutate(raw)
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def _load_error(tmp_path: Path, mutate: Mutate, handlers: Any = HANDLERS) -> str:
    with pytest.raises(RegistryError) as info:
        Registry.load(_write(tmp_path, mutate), handlers)
    return str(info.value)


def _set(name: str, **fields: Any) -> Mutate:
    return lambda raw: _lever(raw, name).update(fields)


def _drop(name: str, field: str) -> Mutate:
    return lambda raw: _lever(raw, name).pop(field)


# -- B01-1 every lever declares the fields; write levers must -----------------------------


def test_b01_1_every_lever_in_the_registry_file_declares_the_new_fields() -> None:
    for entry in _raw()["levers"]:
        name = entry["name"]
        for field in ("risk_class", "reversibility", "undo", "lever_version", "impact"):
            assert field in entry, f"{name} does not declare {field}"
        assert entry["risk_class"] in {"R0", "R1", "R2", "R3"}
        assert isinstance(entry["lever_version"], int) and entry["lever_version"] >= 1
        assert set(entry["impact"]) == {"L1", "L2", "L3", "L4"}
        for line in entry["impact"].values():
            assert isinstance(line, str) and 0 < len(line) <= 200 and "\n" not in line


def test_b01_1_the_registry_loads_the_declared_values() -> None:
    registry = Registry.load()
    for name in WRITE_LEVERS:
        lever = registry.get(name)
        assert lever is not None and lever.impact is not None
        # D-024: identity changes (MFA reset, disable) are R3.
        undo = "user.enable" if name == "user.disable" else None  # B-29: user.enable is the registered undo of disable
        assert (lever.risk_class, lever.reversibility, lever.undo, lever.lever_version) == ("R3", "reversible", undo, 1)
        assert lever.impact.L1.startswith("One person")
    for name in READ_LEVERS:
        lever = registry.get(name)
        assert lever is not None and lever.impact is not None
        assert (lever.risk_class, lever.reversibility, lever.undo) == ("R0", "n/a", None)


@pytest.mark.parametrize("name", WRITE_LEVERS)
@pytest.mark.parametrize("field", ["risk_class", "impact"])
def test_b01_1_write_lever_without_risk_class_or_impact_fails_naming_the_lever(
    tmp_path: Path, name: str, field: str
) -> None:
    message = _load_error(tmp_path, _drop(name, field))
    assert name in message and field in message


def test_b01_1_write_lever_with_null_risk_class_fails(tmp_path: Path) -> None:
    assert "user.disable" in _load_error(tmp_path, _set("user.disable", risk_class=None))


def test_b01_1_read_lever_may_leave_the_new_fields_to_their_defaults(tmp_path: Path) -> None:
    def strip(raw: dict[str, Any]) -> None:
        for field in ("risk_class", "reversibility", "undo", "lever_version", "impact"):
            _lever(raw, "ticket.get").pop(field)

    lever = Registry.load(_write(tmp_path, strip)).get("ticket.get")
    assert lever is not None
    assert (lever.risk_class, lever.reversibility, lever.undo, lever.lever_version, lever.impact) == (
        "R0",
        "n/a",
        None,
        1,
        None,
    )


@pytest.mark.parametrize(
    ("label", "impact_change"),
    [
        ("empty line", {"L1": ""}),
        ("line break", {"L2": "first line\nsecond line"}),
        ("carriage return", {"L3": "first\rsecond"}),
        ("too long", {"L4": "x" * 201}),
        ("not a string", {"L1": 7}),
        ("unknown level", {"L5": "the planet"}),
    ],
)
def test_b01_1_bad_impact_lines_fail_the_load(tmp_path: Path, label: str, impact_change: dict[str, Any]) -> None:
    def mutate(raw: dict[str, Any]) -> None:
        _lever(raw, "user.reset-mfa")["impact"].update(impact_change)

    assert "user.reset-mfa" in _load_error(tmp_path, mutate), label


def test_b01_1_impact_missing_a_level_fails_the_load(tmp_path: Path) -> None:
    def mutate(raw: dict[str, Any]) -> None:
        _lever(raw, "user.disable")["impact"].pop("L4")

    assert "user.disable" in _load_error(tmp_path, mutate)


@pytest.mark.parametrize("version", [0, -1, "1", 1.5])
def test_b01_1_lever_version_must_be_a_positive_integer(tmp_path: Path, version: Any) -> None:
    assert "kb.search" in _load_error(tmp_path, _set("kb.search", lever_version=version))


# -- B01-2 class and risk must agree -------------------------------------------------------


@pytest.mark.parametrize("risk", ["R1", "R2", "R3"])
def test_b01_2_read_lever_declaring_r1_to_r3_fails(tmp_path: Path, risk: str) -> None:
    message = _load_error(tmp_path, _set("kb.search", risk_class=risk))
    assert "kb.search" in message and "R0" in message


def test_b01_2_write_lever_declaring_r0_fails(tmp_path: Path) -> None:
    message = _load_error(tmp_path, _set("user.disable", risk_class="R0"))
    assert "user.disable" in message and "R1-R3" in message


@pytest.mark.parametrize("risk", ["R4", "r3", "high", 3])
def test_b01_2_unknown_risk_class_fails(tmp_path: Path, risk: Any) -> None:
    assert "user.disable" in _load_error(tmp_path, _set("user.disable", risk_class=risk))


@pytest.mark.parametrize("risk", ["R1", "R2", "R3"])
def test_b01_2_write_lever_accepts_r1_to_r3(tmp_path: Path, risk: str) -> None:
    lever = Registry.load(_write(tmp_path, _set("user.disable", risk_class=risk))).get("user.disable")
    assert lever is not None and lever.risk_class == risk


@pytest.mark.parametrize(
    ("label", "mutate", "name"),
    [
        ("read lever not n/a", _set("ticket.get", reversibility="reversible"), "ticket.get"),
        ("write lever n/a", _set("user.disable", reversibility="n/a"), "user.disable"),
        ("unknown reversibility", _set("user.disable", reversibility="maybe"), "user.disable"),
        ("irreversible below R3", _set("user.disable", reversibility="irreversible", risk_class="R2"), "user.disable"),
        ("undo on a read lever", _set("ticket.get", undo="user.disable"), "ticket.get"),
        ("undo is itself", _set("user.disable", undo="user.disable"), "user.disable"),
        ("undo not a lever name", _set("user.disable", undo="Enable User"), "user.disable"),
    ],
)
def test_b01_2_inconsistent_risk_fields_fail_naming_the_lever(
    tmp_path: Path, label: str, mutate: Mutate, name: str
) -> None:
    assert name in _load_error(tmp_path, mutate), label


def test_b01_2_irreversible_r3_loads_and_cannot_name_an_undo(tmp_path: Path) -> None:
    ok = Registry.load(_write(tmp_path, _set("user.disable", reversibility="irreversible")))
    assert ok.get("user.disable") is not None and ok.get("user.disable").reversibility == "irreversible"  # type: ignore[union-attr]
    mutate = _set("user.disable", reversibility="irreversible", undo="user.reset-mfa")
    assert "user.disable" in _load_error(tmp_path, mutate)


def test_b01_2_undo_must_name_a_registered_write_lever(tmp_path: Path) -> None:
    unknown = _load_error(tmp_path, _set("user.disable", undo="user.enable"))
    assert "user.disable" in unknown and "user.enable" in unknown
    read_target = _load_error(tmp_path, _set("user.disable", undo="ticket.get"))
    assert "user.disable" in read_target and "ticket.get" in read_target


def test_b01_2_undo_naming_a_registered_write_lever_loads(tmp_path: Path) -> None:
    # A stand-in user.enable lever, registered for this test only, shows a valid undo link.
    def add_enable(raw: dict[str, Any]) -> None:
        enable = copy.deepcopy(_lever(raw, "user.disable"))
        enable.update(name="user.enable", description="Re-enable a user account. Mock (test only).")
        raw["levers"].append(enable)
        _lever(raw, "user.disable")["undo"] = "user.enable"
        enable["undo"] = "user.disable"

    handlers = {**HANDLERS, "user.enable": HANDLERS["user.disable"]}
    registry = Registry.load(_write(tmp_path, add_enable), handlers)
    assert registry.get("user.disable").undo == "user.enable"  # type: ignore[union-attr]


def test_b01_2_class_and_risk_are_checked_for_levers_built_in_code() -> None:
    base = {
        "name": "test.read",
        "description": "test lever",
        "client_scope": "any",
        "required_role": "agent",
        "class": "read",
        "approval": "none",
        "params": {},
        "dry_run": True,
        "timeout_s": 1,
    }
    with pytest.raises(ValidationError, match="R0"):
        LeverDef.model_validate({**base, "risk_class": "R2"})
    write = {**base, "class": "write", "approval": "lead", "required_role": "technician"}
    with pytest.raises(ValidationError, match="R1-R3"):
        LeverDef.model_validate({**write, "risk_class": "R0"})


# -- B01-3 verification rule ---------------------------------------------------------------


@pytest.mark.parametrize("name", WRITE_LEVERS)
def test_b01_3_identity_levers_declare_requester_verification(name: str) -> None:
    lever = Registry.load().get(name)
    assert lever is not None and lever.verification == "requester"


def test_b01_3_requester_verification_is_rejected_on_a_read_lever(tmp_path: Path) -> None:
    message = _load_error(tmp_path, _set("kb.search", verification="requester"))
    assert "kb.search" in message and "write levers only" in message


@pytest.mark.parametrize("value", ["callback", "approver", "", True])
def test_b01_3_other_lever_verification_values_fail(tmp_path: Path, value: Any) -> None:
    assert "user.disable" in _load_error(tmp_path, _set("user.disable", verification=value))


def test_b01_3_write_lever_without_verification_still_loads(tmp_path: Path) -> None:
    lever = Registry.load(_write(tmp_path, _drop("user.disable", "verification"))).get("user.disable")
    assert lever is not None and lever.verification is None


@pytest.mark.parametrize(
    ("method", "ref"),
    [
        ("callback-on-file", ""),
        ("in-person", ""),
        ("manager-confirmed", "T-1002"),
        ("finding-reference", "F-MFA-0042"),
    ],
)
def test_b01_3_approval_accepts_each_verification_method(method: str, ref: str) -> None:
    approval = Approval.model_validate(
        {
            "approver": "lead-lee",
            "lever": "user.disable",
            "client": CONTOSO,
            "params": DISABLE_JAMIE,
            "verification": {"method": method, "by": "tech-ana", "at": "2026-10-21T15:30:00Z", "ref": ref},
        }
    )
    assert approval.verification is not None
    v = approval.verification
    assert (v.method, v.by, v.at, v.ref) == (method, "tech-ana", AT, ref)


@pytest.mark.parametrize(
    ("label", "verification"),
    [
        ("unknown method", {"method": "email-reply", "by": "tech-ana", "at": "2026-10-21T15:30:00Z"}),
        ("method by text", {"method": "Callback on file", "by": "tech-ana", "at": "2026-10-21T15:30:00Z"}),
        ("missing method", {"by": "tech-ana", "at": "2026-10-21T15:30:00Z"}),
        ("missing by", {"method": "in-person", "at": "2026-10-21T15:30:00Z"}),
        ("empty by", {"method": "in-person", "by": "", "at": "2026-10-21T15:30:00Z"}),
        ("missing at", {"method": "in-person", "by": "tech-ana"}),
        ("naive at", {"method": "in-person", "by": "tech-ana", "at": "2026-10-21T15:30:00"}),
        ("not a time", {"method": "in-person", "by": "tech-ana", "at": "yesterday"}),
        ("extra key", {"method": "in-person", "by": "tech-ana", "at": "2026-10-21T15:30:00Z", "phone": "555-0100"}),
        ("finding without ref", {"method": "finding-reference", "by": "tech-ana", "at": "2026-10-21T15:30:00Z"}),
        ("ref with spaces", {"method": "in-person", "by": "tech-ana", "at": "2026-10-21T15:30:00Z", "ref": "a b"}),
        ("ref too long", {"method": "in-person", "by": "tech-ana", "at": "2026-10-21T15:30:00Z", "ref": "x" * 65}),
        ("by not a string", {"method": "in-person", "by": 7, "at": "2026-10-21T15:30:00Z"}),
    ],
)
def test_b01_3_bad_approval_verification_is_rejected(label: str, verification: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Approval.model_validate(
            {
                "approver": "lead-lee",
                "lever": "user.disable",
                "client": CONTOSO,
                "params": DISABLE_JAMIE,
                "verification": verification,
            }
        )


def test_b01_3_verification_is_frozen() -> None:
    v = Verification(method="callback-on-file", by="tech-ana", at=AT)
    with pytest.raises(ValidationError):
        v.method = "in-person"  # type: ignore[misc]


def test_b01_3_approval_verification_is_optional_on_the_model_and_enforced_by_the_runner(tmp_path: Path) -> None:
    plain = Approval(approver="lead-lee", lever="user.disable", client=CONTOSO, params=DISABLE_JAMIE)
    assert plain.verification is None
    verified = Approval(
        approver="lead-lee",
        lever="user.disable",
        client=CONTOSO,
        params=DISABLE_JAMIE,
        verification=Verification(method="callback-on-file", by="tech-ana", at=datetime.now(UTC)),
    )
    # The model accepts both; from B-02 the runner refuses the unverified one on a `requester` lever (B02-2).
    for index, (approval, allowed) in enumerate(((plain, False), (verified, True))):
        tenant_dir = tmp_path / f"tenant{index}"
        shutil.copytree(DEFAULT_TENANT_DIR, tenant_dir)
        audit_path = tmp_path / f"audit{index}.jsonl"
        runner = LeverRunner(Registry.load(), IdentityStore.load(), MockTenant(tenant_dir), AuditLog(audit_path))
        result = runner.invoke("user.disable", DISABLE_JAMIE, "tech-ana", CONTOSO, mode="execute", approval=approval)
        assert result.ok is allowed and result.applied is allowed


# -- B01-4 the four levers keep their names, params and approval rules ---------------------

EXPECTED = {
    "ticket.get": ("read", "none", "agent", None, "any", ("ticket_id",), ("ticket_id",)),
    "kb.search": (
        "read",
        "none",
        "agent",
        None,
        (CONTOSO, "fabrikam-capital"),
        ("query", "category"),
        ("category", "query", "top"),
    ),
    "user.reset-mfa": ("write", "lead", "technician", "agent", "any", ("upn",), ("upn",)),
    "user.disable": ("write", "lead", "technician", "agent", "any", ("upn",), ("reason", "upn")),
}


def test_b01_4_the_four_levers_keep_names_params_roles_and_approval_rules() -> None:
    registry = Registry.load()
    assert [n for n in registry.names() if n in EXPECTED] == sorted(EXPECTED)  # later fragments add levers
    for name, expected in EXPECTED.items():
        lever = registry.get(name)
        assert lever is not None
        actual = (
            lever.lever_class,
            lever.approval,
            lever.required_role.value,
            None if lever.dry_run_role is None else lever.dry_run_role.value,
            lever.client_scope,
            lever.idempotency_keys,
            tuple(sorted(lever.params)),
        )
        assert actual == expected, name
        assert lever.dry_run is True


def test_b01_4_write_rules_are_unchanged_by_the_new_fields(tmp_path: Path) -> None:
    # The Phase 1 safety rule still fires first: a write lever without lead approval fails even with R3 declared.
    assert "user.disable" in _load_error(tmp_path, _set("user.disable", approval="none"))
    # A lever built in code without the new fields (as tests/phase1 does) still constructs with safe defaults.
    lever = LeverDef.model_validate(
        {
            "name": "test.write",
            "description": "test lever",
            "client_scope": "any",
            "required_role": "technician",
            "class": "write",
            "approval": "lead",
            "params": {},
            "dry_run": True,
            "timeout_s": 1,
        }
    )
    assert (lever.risk_class, lever.reversibility, lever.verification, lever.impact) == (None, "reversible", None, None)
