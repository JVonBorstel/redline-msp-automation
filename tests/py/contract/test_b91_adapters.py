"""B-91 shared adapter contract suite: every adapter, mock and real stub, must pass the same rules.

Acceptance ids B91-1 to B91-4 are defined in specs/B-91.md. Offline: committed fixtures are read only, builder tests
use private config folders under tmp_path, and nothing here opens a socket. The suite is driven by one table
(``CASES``) and by ``adapters.real.REAL_STUBS``: a real implementation added to that registry is picked up and has to
pass every rule below before it can be selected (B91-1). Synthetic data only.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/contract/test_b91_adapters.py
"""

from __future__ import annotations

import copy
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from adapters import build_adapter
from adapters.alerts import AlertsAdapter, AlertsMock
from adapters.backup import BackupAdapter, BackupMock
from adapters.base import REAL_ADAPTER_NOT_CONFIGURED, Adapter, AdapterError, AdapterResult
from adapters.binding import BoundBinding
from adapters.graph import GraphAdapter, GraphMock, build_graph_adapter
from adapters.intune import IntuneAdapter, IntuneMock, build_intune_adapter
from adapters.psa import PsaAdapter, PsaMock
from adapters.real import REAL_STUBS, RealStub
from adapters.rmm import RmmAdapter, RmmMock, build_rmm_adapter

REPO = Path(__file__).resolve().parents[3]
CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
CLIENTS = (CONTOSO, FABRIKAM)
OTHER = {CONTOSO: FABRIKAM, FABRIKAM: CONTOSO}
# A value-shaped string that must never appear in a repr, a result, an error or a log line (STD-CF-7, STD-AU-5).
SECRET = "SENTINEL-value-that-must-never-leak-7f3a"  # noqa: S105 - a test sentinel, not a credential

Lookup = tuple[str, Any, Any]  # method, an argument that exists for this client, an argument that exists for nobody


@dataclass(frozen=True)
class Case:
    """Everything the generic rules need to know about one adapter interface."""

    name: str
    interface: type[Adapter]
    binding_system: str
    external: dict[str, str]
    make_mock: Callable[[str, BoundBinding], Adapter]
    make_mock_in: Callable[[str, BoundBinding, Path], Adapter]  # same, reading fixtures from another folder
    reads: tuple[tuple[str, tuple[Any, ...]], ...]  # one call for EVERY public method of the interface
    lookups: dict[str, tuple[Lookup, ...]]
    markers: dict[str, tuple[str, ...]]  # text that only the named client's data contains


CASES: tuple[Case, ...] = (
    Case(
        "psa",
        PsaAdapter,
        "psa",
        {CONTOSO: "30001", FABRIKAM: "30002"},
        lambda c, b: PsaMock(c, b),
        lambda c, b, r: PsaMock(c, b, r),
        (
            ("get_company", ()),
            ("list_contacts", ()),
            ("get_contact", (40001,)),
            ("list_tickets", ()),
            ("get_ticket", ("T-3101",)),
            ("list_ticket_notes", ("T-3101",)),
            ("list_resources", ()),
            ("get_sla_settings", ()),
        ),
        {
            CONTOSO: (
                ("get_ticket", "T-3101", "T-9999"),
                ("list_ticket_notes", "T-3101", "T-9999"),
                ("get_contact", 40001, 999999),
            ),
            FABRIKAM: (
                ("get_ticket", "T-3201", "T-9999"),
                ("list_ticket_notes", "T-3201", "T-9999"),
                ("get_contact", 40101, 999999),
            ),
        },
        {
            CONTOSO: ("Contoso Dental", "contosodental", "T-31"),
            FABRIKAM: ("Fabrikam Capital", "fabrikamcapital", "T-32"),
        },
    ),
    Case(
        "rmm",
        RmmAdapter,
        "rmm",
        {CONTOSO: "c0000000-0000-4000-8000-0000000a0001", FABRIKAM: "f0000000-0000-4000-8000-0000000a0002"},
        lambda c, b: RmmMock(c, b),
        lambda c, b, r: RmmMock(c, b, r),
        (
            ("get_site", ()),
            ("list_devices", ()),
            ("get_device", ("d",)),
            ("get_device_audit", ("d",)),
            ("list_open_alerts", ()),
            ("list_jobs", ()),
            ("get_job", ("j",)),
            ("list_components", ()),
        ),
        {
            CONTOSO: (
                ("get_device", "c0000000-0000-4000-8000-0000000d0001", "00000000-0000-4000-8000-000000000000"),
                ("get_device_audit", "c0000000-0000-4000-8000-0000000d0001", "00000000-0000-4000-8000-000000000000"),
                ("get_job", "c0000000-0000-4000-8000-0000000j0001", "00000000-0000-4000-8000-000000000000"),
            ),
            FABRIKAM: (
                ("get_device", "f0000000-0000-4000-8000-0000000d0001", "00000000-0000-4000-8000-000000000000"),
                ("get_device_audit", "f0000000-0000-4000-8000-0000000d0001", "00000000-0000-4000-8000-000000000000"),
                ("get_job", "f0000000-0000-4000-8000-0000000j0001", "00000000-0000-4000-8000-000000000000"),
            ),
        },
        {
            CONTOSO: ("c0000000-", "Contoso Dental", "contosodental"),
            FABRIKAM: ("f0000000-", "Fabrikam Capital", "fabrikamcapital"),
        },
    ),
    Case(
        "intune",
        IntuneAdapter,
        "m365",
        {CONTOSO: "c0000000-0000-4000-8000-000000000001", FABRIKAM: "f0000000-0000-4000-8000-000000000002"},
        lambda c, b: IntuneMock(c, b),
        lambda c, b, r: IntuneMock(c, b, r),
        (("list_managed_devices", ()), ("get_managed_device", ("d",))),
        {
            CONTOSO: (("get_managed_device", "c0000000-0000-4000-8000-0000000e0001", "00000000-0000-4000-8000-0"),),
            FABRIKAM: (("get_managed_device", "f0000000-0000-4000-8000-0000000e0001", "00000000-0000-4000-8000-0"),),
        },
        {
            CONTOSO: ("c0000000-", "Contoso Dental", "contosodental"),
            FABRIKAM: ("f0000000-", "Fabrikam Capital", "fabrikamcapital"),
        },
    ),
    Case(
        "graph",
        GraphAdapter,
        "m365",
        {CONTOSO: "c0000000-0000-4000-8000-000000000001", FABRIKAM: "f0000000-0000-4000-8000-000000000002"},
        lambda c, b: GraphMock(c, b),
        lambda c, b, r: GraphMock(c, b, r),
        (
            ("state", ()),
            ("families", ()),
            ("family_state", ("licenses",)),
            ("list_users", ()),
            ("get_user", ("u",)),
            ("list_authentication_methods", ("u",)),
        ),
        {
            CONTOSO: (
                ("get_user", "ana.lopez@contosodental.example", "nobody@nowhere.example"),
                ("list_authentication_methods", "ana.lopez@contosodental.example", "nobody@nowhere.example"),
            ),
            FABRIKAM: (
                ("get_user", "morgan.reyes@fabrikamcapital.example", "nobody@nowhere.example"),
                ("list_authentication_methods", "morgan.reyes@fabrikamcapital.example", "nobody@nowhere.example"),
            ),
        },
        {CONTOSO: ("Contoso Dental", "contosodental"), FABRIKAM: ("Fabrikam Capital", "fabrikamcapital")},
    ),
    Case(
        "backup",
        BackupAdapter,
        "backup",
        {CONTOSO: "81001", FABRIKAM: "81002"},
        lambda c, b: BackupMock(c, b),
        lambda c, b, r: BackupMock(c, b, r),
        (("get_organization", ()), ("list_jobs", ()), ("get_job", ("BJ-1001",))),
        {
            CONTOSO: (("get_job", "BJ-1001", "BJ-9999"),),
            FABRIKAM: (("get_job", "BJ-2001", "BJ-9999"),),
        },
        {CONTOSO: ("Contoso Dental", "BJ-10"), FABRIKAM: ("Fabrikam Capital", "BJ-20")},
    ),
    Case(
        "alerts",
        AlertsAdapter,
        "alerts",
        {CONTOSO: "alerts-contoso-001", FABRIKAM: "alerts-fabrikam-001"},
        lambda c, b: AlertsMock(c, b),
        lambda c, b, r: AlertsMock(c, b, r),
        (("list_alerts", ()), ("get_alert", ("A-1009",))),
        {
            CONTOSO: (("get_alert", "A-1009", "A-9999"),),
            FABRIKAM: (("get_alert", "A-2007", "A-9999"),),
        },
        {CONTOSO: ("Contoso Dental", "contoso", "A-10"), FABRIKAM: ("Fabrikam Capital", "fabrikam", "A-20")},
    ),
)
BY_NAME = {c.name: c for c in CASES}
IMPLS = ("mock", "stub")
MATRIX = [(c, i) for c in CASES for i in IMPLS]
MATRIX_IDS = [f"{c.name}-{i}" for c, i in MATRIX]


def _binding(case: Case, client: str, impl: str, *, credential: str | None = None, external: str | None = None) -> Any:
    return BoundBinding(
        client,
        case.binding_system,
        "mock" if impl == "mock" else "vendor-x",
        external if external is not None else case.external[client],
        credential,
    )


def _make(case: Case, impl: str, client: str = CONTOSO, **kw: Any) -> Adapter:
    binding = _binding(case, client, impl, **kw)
    if impl == "mock":
        return case.make_mock(client, binding)
    return REAL_STUBS[case.name](client, binding)


def _call(adapter: Adapter, method: str, args: tuple[Any, ...]) -> AdapterResult[Any]:
    result: AdapterResult[Any] = getattr(adapter, method)(*args)
    return result


def _public_methods(interface: type[Adapter]) -> set[str]:
    abstract: frozenset[str] = getattr(interface, "__abstractmethods__", frozenset())
    return set(abstract)


# --- B91-1: one suite, every implementation -------------------------------------------------------------------
def test_b91_1_the_table_covers_every_interface_and_every_public_method() -> None:
    assert set(REAL_STUBS) == set(BY_NAME), "every adapter interface needs a real stub and a contract case"
    for case in CASES:
        assert {m for m, _ in case.reads} == _public_methods(case.interface), case.name
        assert len({m for m, _ in case.reads}) == len(case.reads)
        assert set(case.external) == set(CLIENTS) == set(case.lookups) == set(case.markers)


def test_b91_1_every_stub_is_a_real_stub_of_its_interface_and_not_a_mock() -> None:
    for name, cls in REAL_STUBS.items():
        assert issubclass(cls, BY_NAME[name].interface)
        assert issubclass(cls, RealStub)
        assert "Mock" not in cls.__name__


@pytest.mark.parametrize(("case", "impl"), MATRIX, ids=MATRIX_IDS)
def test_b91_1_implementation_is_an_instance_of_the_vendor_neutral_interface(case: Case, impl: str) -> None:
    adapter = _make(case, impl)
    assert isinstance(adapter, case.interface)
    assert adapter.client == CONTOSO
    assert adapter.system == case.interface.system


@pytest.mark.parametrize(("case", "impl"), MATRIX, ids=MATRIX_IDS)
def test_b91_1_no_call_ever_raises_and_every_result_is_typed(case: Case, impl: str) -> None:
    adapter = _make(case, impl)
    for method, args in case.reads:
        result = _call(adapter, method, args)
        assert isinstance(result, AdapterResult), method
        assert isinstance(result.ok, bool) and isinstance(result.reason, str) and result.reason, method
        assert (result.data is not None) == result.ok, method  # data only on success (STD-ER-1)
    # hostile arguments of the right and wrong type: still a result, never an exception
    for method, _ in case.reads:
        fn = getattr(adapter, method)
        n = fn.__code__.co_argcount - 1
        for hostile in ("", "../../etc/passwd", "x" * 5000, None, -1, 3.5, ["a"], {"a": 1}):
            assert isinstance(fn(*([hostile] * n)), AdapterResult), (method, hostile)


@pytest.mark.parametrize(("case", "impl"), MATRIX, ids=MATRIX_IDS)
def test_b91_1_a_crash_inside_a_call_becomes_a_deterministic_reason_without_the_message(case: Case, impl: str) -> None:
    adapter = _make(case, impl)

    def boom() -> AdapterResult[Any]:
        raise RuntimeError(f"connection string {SECRET}")

    first = adapter._guard(boom)
    second = _make(case, impl)._guard(boom)
    assert first == second
    assert first.reason == f"{type(adapter).__name__} crashed: RuntimeError"
    assert not first.ok and first.data is None
    assert SECRET not in repr(first)


# --- one-client binding (TEN-04) ------------------------------------------------------------------------------
@pytest.mark.parametrize(("case", "impl"), MATRIX, ids=MATRIX_IDS)
def test_b91_one_client_adapter_refuses_another_clients_binding_at_construction(case: Case, impl: str) -> None:
    other_binding = _binding(case, FABRIKAM, impl)
    factory = case.make_mock if impl == "mock" else REAL_STUBS[case.name]
    with pytest.raises(AdapterError) as exc:
        factory(CONTOSO, other_binding)
    text = str(exc.value)
    assert FABRIKAM not in text and case.external[FABRIKAM] not in text  # the refusal names nobody's data


@pytest.mark.parametrize(("case", "impl"), MATRIX, ids=MATRIX_IDS)
def test_b91_one_client_adapter_refuses_a_binding_for_a_different_system(case: Case, impl: str) -> None:
    wrong = BoundBinding(CONTOSO, "documentation", "mock" if impl == "mock" else "vendor-x", "x-1", None)
    factory = case.make_mock if impl == "mock" else REAL_STUBS[case.name]
    with pytest.raises(AdapterError):
        factory(CONTOSO, wrong)


@pytest.mark.parametrize(("case", "impl"), MATRIX, ids=MATRIX_IDS)
def test_b91_one_client_the_client_cannot_be_rebound_after_construction(case: Case, impl: str) -> None:
    adapter = _make(case, impl)
    with pytest.raises(AttributeError):
        adapter.client = FABRIKAM  # type: ignore[misc]
    assert adapter.client == CONTOSO


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_b91_one_client_a_mock_refuses_another_clients_external_id(case: Case) -> None:
    # The binding names the right client but another client's vendor id: the fixture cannot be pointed at it.
    swapped = _binding(case, CONTOSO, "mock", external=case.external[FABRIKAM])
    if case.name == "graph":
        # Known gap (imperative xfail; delete this branch once fixed): GraphMock checks the tenant id only when
        # the base file carries one and the committed tenant fixtures carry none (adapters/graph/mock.py, B-19).
        # Reported in specs/B-91.md.
        pytest.xfail("GraphMock does not bind the tenant id when the fixture has none")
    with pytest.raises(AdapterError):
        case.make_mock(CONTOSO, swapped)


@pytest.mark.parametrize(("case", "impl"), MATRIX, ids=MATRIX_IDS)
def test_b91_one_client_an_implementation_name_that_does_not_fit_is_refused(case: Case, impl: str) -> None:
    if impl == "mock":
        wrong = BoundBinding(CONTOSO, case.binding_system, "vendor-x", case.external[CONTOSO])
        with pytest.raises(AdapterError):
            case.make_mock(CONTOSO, wrong)
    else:
        wrong = BoundBinding(CONTOSO, case.binding_system, "mock", case.external[CONTOSO])
        with pytest.raises(AdapterError):
            REAL_STUBS[case.name](CONTOSO, wrong)  # a stub never poses as the mock


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
@pytest.mark.parametrize("client", CLIENTS)
def test_b91_one_client_another_clients_object_answers_exactly_like_a_missing_one(case: Case, client: str) -> None:
    adapter = _make(case, "mock", client)
    for method, own, _missing in case.lookups[client]:
        assert _call(adapter, method, (own,)).ok, (method, own)  # the object exists for its own client
    for method, foreign, missing in case.lookups[OTHER[client]]:
        asked_foreign = _call(adapter, method, (foreign,))
        asked_missing = _call(adapter, method, (missing,))
        assert not asked_foreign.ok and asked_foreign.data is None, (method, foreign)
        assert asked_foreign == asked_missing, (method, "no existence oracle: same ok, same words")


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
@pytest.mark.parametrize("client", CLIENTS)
def test_b91_one_client_no_result_contains_data_that_belongs_to_another_client(case: Case, client: str) -> None:
    adapter = _make(case, "mock", client)
    foreign_markers = case.markers[OTHER[client]]
    own = {m: a for m, a, _ in case.lookups[client]}
    for method, args in case.reads:
        method_args = (own[method],) if method in own else args
        text = repr(_call(adapter, method, method_args))
        for marker in foreign_markers:
            assert marker not in text, (method, marker)


def _poison(name: str, data: dict[str, Any]) -> tuple[str, Any]:
    """Slip one record of the OTHER client into this client's fixture; return (method, id) that would expose it."""
    if name == "psa":
        data["tickets"].append({**data["tickets"][0], "id": 79999, "ticketNumber": "T-9999-X", "companyID": 30002})
        return "get_ticket", "T-9999-X"
    if name == "backup":
        data["jobs"].append({**data["jobs"][0], "id": "BJ-9999", "organizationId": 81002})
        return "get_job", "BJ-9999"
    if name == "alerts":
        data["alerts"].append({**data["alerts"][0], "id": "A-9999", "client": FABRIKAM})
        return "get_alert", "A-9999"
    row = {**data["devices"]["devices"][0], "uid": "f0000000-0000-4000-8000-0000000d0777"}
    row["siteUid"] = "f0000000-0000-4000-8000-0000000a0002"
    data["devices"]["devices"].append(row)
    return "get_device", row["uid"]


@pytest.mark.parametrize("name", ["psa", "backup", "alerts", "rmm"])
def test_b91_one_client_a_record_of_another_client_filed_in_this_clients_fixture_is_never_served(
    name: str, tmp_path: Path
) -> None:
    # The committed fixtures hold no stray rows, so a mock that forgot to filter would still pass the tests above.
    # Intune and Graph rows carry no owner field to poison; their isolation is the one-file-per-client rule above.
    case = BY_NAME[name]
    data = json.loads((REPO / "fixtures" / name / f"{CONTOSO}.json").read_text(encoding="utf-8"))
    method, foreign_id = _poison(name, data)
    (tmp_path / f"{CONTOSO}.json").write_text(json.dumps(data), encoding="utf-8")
    adapter = case.make_mock_in(CONTOSO, _binding(case, CONTOSO, "mock"), tmp_path)
    result = _call(adapter, method, (foreign_id,))
    assert not result.ok and result.data is None
    for list_method in ("list_tickets", "list_jobs", "list_alerts", "list_devices"):
        if hasattr(adapter, list_method):
            assert str(foreign_id) not in repr(_call(adapter, list_method, ())), list_method


# --- fail closed when not configured (B91-3) ------------------------------------------------------------------
@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_b91_3_a_real_stub_fails_every_call_with_the_same_clear_reason(case: Case) -> None:
    stub = _make(case, "stub")
    for method, args in case.reads:
        result = _call(stub, method, args)
        assert result == AdapterResult(False, REAL_ADAPTER_NOT_CONFIGURED, None), method
    # hostile arguments cannot change the answer
    for method, _ in case.reads:
        n = getattr(stub, method).__code__.co_argcount - 1
        assert _call(stub, method, tuple(["../x"] * n)).reason == REAL_ADAPTER_NOT_CONFIGURED


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_b91_3_a_stub_never_returns_mock_fixture_data_even_when_fixtures_exist(case: Case) -> None:
    stub = _make(case, "stub")
    for method, own, _missing in case.lookups[CONTOSO]:
        result = _call(stub, method, (own,))
        assert not result.ok and result.data is None


def test_b91_3_stub_registry_is_the_only_door_and_builders_agree(tmp_path: Path) -> None:
    for client in CLIENTS:
        _write_client(tmp_path, client, implementation="vendor-x")
    for client in CLIENTS:
        for result in (
            build_adapter(client, "psa", config_dir=tmp_path),
            build_graph_adapter(client, config_dir=tmp_path),
            build_intune_adapter(client, config_dir=tmp_path),
            build_rmm_adapter(client, config_dir=tmp_path),
        ):
            assert result.ok is False
            assert result.reason == REAL_ADAPTER_NOT_CONFIGURED
            assert result.adapter is None


def test_b91_3_builders_still_build_the_mock_when_the_binding_says_mock(tmp_path: Path) -> None:
    _write_client(tmp_path, CONTOSO, implementation="mock")
    assert build_adapter(CONTOSO, "psa", config_dir=tmp_path).ok
    assert build_graph_adapter(CONTOSO, config_dir=tmp_path).ok
    assert build_intune_adapter(CONTOSO, config_dir=tmp_path).ok
    assert build_rmm_adapter(CONTOSO, config_dir=tmp_path).ok


def test_b91_3_a_missing_or_broken_client_file_fails_closed_for_every_builder(tmp_path: Path) -> None:
    (tmp_path / f"{CONTOSO}.json").write_text("{not json", encoding="utf-8")
    for result in (
        build_adapter(CONTOSO, "psa", config_dir=tmp_path),
        build_graph_adapter(CONTOSO, config_dir=tmp_path),
        build_intune_adapter(CONTOSO, config_dir=tmp_path),
        build_rmm_adapter(CONTOSO, config_dir=tmp_path / "missing"),
    ):
        assert result.ok is False and result.adapter is None


# --- credentials by name only; no secret in repr, results, errors or logs -------------------------------------
@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_b91_credentials_a_stub_refuses_a_value_where_a_secret_name_belongs(
    case: Case, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG), pytest.raises(AdapterError) as exc:
        REAL_STUBS[case.name](CONTOSO, _binding(case, CONTOSO, "stub", credential=SECRET))
    assert SECRET not in str(exc.value) and SECRET not in repr(exc.value)
    assert SECRET not in caplog.text


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_b91_credentials_a_stub_refuses_another_clients_secret_name(case: Case) -> None:
    with pytest.raises(AdapterError):
        REAL_STUBS[case.name](CONTOSO, _binding(case, CONTOSO, "stub", credential=f"client-{FABRIKAM}-{case.name}"))


@pytest.mark.parametrize(("case", "impl"), MATRIX, ids=MATRIX_IDS)
def test_b91_credentials_the_secret_name_is_exposed_as_a_name_and_nothing_else(case: Case, impl: str) -> None:
    name = f"client-{CONTOSO}-{case.name}"
    adapter = _make(case, impl, credential=name)
    assert adapter.credential_ref == name
    assert adapter.external_id == case.external[CONTOSO]
    assert re.fullmatch(r"client-[a-z0-9-]+", adapter.credential_ref or "")


@pytest.mark.parametrize(("case", "impl"), MATRIX, ids=MATRIX_IDS)
def test_b91_credentials_no_secret_in_repr_str_results_or_logs(
    case: Case, impl: str, caplog: pytest.LogCaptureFixture
) -> None:
    # A mock does not validate the reference (the binding loader does, STD-CF-7); even so a value that slipped
    # through a hand-built binding must not surface anywhere an adapter writes text. A stub cannot hold one at all.
    if impl == "stub":
        adapter = _make(case, impl, credential=f"client-{CONTOSO}-{case.name}")
    else:
        adapter = _make(case, impl, credential=SECRET)
    with caplog.at_level(logging.DEBUG):
        texts = [repr(adapter), str(adapter)]
        for method, args in case.reads:
            result = _call(adapter, method, args)
            texts += [repr(result), result.reason]
        texts.append(repr(adapter._guard(lambda: 1 / 0)))  # type: ignore[arg-type, return-value]
    texts.append(caplog.text)
    assert all(SECRET not in t for t in texts)


# --- deterministic errors and results -------------------------------------------------------------------------
@pytest.mark.parametrize(("case", "impl"), MATRIX, ids=MATRIX_IDS)
def test_b91_deterministic_same_call_same_result_on_one_instance_and_on_two(case: Case, impl: str) -> None:
    a, b = _make(case, impl), _make(case, impl)
    for method, args in case.reads:
        first = _call(a, method, args)
        assert first == _call(a, method, args), method
        assert first == _call(b, method, args), method


@pytest.mark.parametrize(("case", "impl"), MATRIX, ids=MATRIX_IDS)
def test_b91_deterministic_reasons_carry_no_address_path_traceback_or_other_noise(case: Case, impl: str) -> None:
    adapter = _make(case, impl)
    reasons: list[str] = []
    for method, args in case.reads:
        reasons.append(_call(adapter, method, args).reason)
    for method, _own, missing in case.lookups[CONTOSO]:
        reasons.append(_call(adapter, method, (missing,)).reason)
    for reason in reasons:
        assert "0x" not in reason and "Traceback" not in reason and "\n" not in reason
        assert str(REPO) not in reason and "\\" not in reason and "/" not in reason.replace("n/a", "")
        assert len(reason) <= 120


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_b91_deterministic_a_caller_cannot_change_what_the_next_call_returns(case: Case) -> None:
    adapter = _make(case, "mock")
    for method, args in case.reads:
        first = _call(adapter, method, args)
        snapshot = copy.deepcopy(first.data)
        if isinstance(first.data, list):
            first.data.clear()
        elif isinstance(first.data, dict):
            first.data.clear()
        assert _call(adapter, method, args).data == snapshot, method


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_b91_deterministic_the_mock_never_writes_to_its_fixtures(case: Case) -> None:
    before = _fixture_digest()
    adapter = _make(case, "mock")
    for method, args in case.reads:
        _call(adapter, method, args)
    assert _fixture_digest() == before


# --- helpers --------------------------------------------------------------------------------------------------
def _fixture_digest() -> dict[str, int]:
    root = REPO / "fixtures"
    return {str(p.relative_to(root)): p.stat().st_mtime_ns for p in sorted(root.rglob("*.json"))}


def _write_client(root: Path, client: str, *, implementation: str) -> None:
    ids = {
        CONTOSO: ("30001", "c0000000-0000-4000-8000-0000000a0001", "c0000000-0000-4000-8000-000000000001"),
        FABRIKAM: ("30002", "f0000000-0000-4000-8000-0000000a0002", "f0000000-0000-4000-8000-000000000002"),
    }[client]
    cfg = {
        "version": 1,
        "_note": "Synthetic test client.",
        "id": client,
        "display_name": client,
        "psa_company_id": ids[0],
        "industry": "other",
        "regimes": [],
        "model_processing": "none",
        "retention_class": "standard",
        "enabled_levers": ["ticket.get"],
        "bindings": {
            "psa": {"implementation": implementation, "external_id": ids[0], "credential_ref": f"client-{client}-psa"},
            "rmm": {"implementation": implementation, "external_id": ids[1], "credential_ref": f"client-{client}-rmm"},
            "m365": {
                "implementation": implementation,
                "external_id": ids[2],
                "credential_ref": f"client-{client}-m365",
                "access": "gdap",
            },
        },
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{client}.json").write_text(json.dumps(cfg), encoding="utf-8")
