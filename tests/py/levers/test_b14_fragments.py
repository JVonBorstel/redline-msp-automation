"""B-14 registry fragments, Python lever modules and the never-automate gate.

Acceptance ids B14-1 to B14-4 are defined in specs/B-14.md. Every test is offline and works on private copies
in tmp_path; committed files are never modified. Run: uv run --frozen pytest tests/py/levers
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

import levers.python as lever_package
from core.levers import DEFAULT_REGISTRY_PATH, Registry, RegistryError
from core.levers.handlers import HANDLERS, EntryError, resolve_python_entry
from core.levers.registry import DEFAULT_NEVER_AUTOMATE_PATH, NeverAutomate

REPO = Path(__file__).resolve().parents[3]
FOUR = ["kb.search", "ticket.get", "user.disable", "user.reset-mfa"]
IMPACT = {
    "L1": "One person at one client sees a widget list; nothing about the person changes.",
    "L2": "The client office reads its own widgets only.",
    "L3": "The MSP can show who looked at what.",
    "L4": "Client data never mixes across tenants.",
}


def read_lever(name: str, **extra: Any) -> dict[str, Any]:
    lever: dict[str, Any] = {
        "name": name,
        "description": "Mock read of one synthetic list.",
        "client_scope": "any",
        "required_role": "agent",
        "class": "read",
        "approval": "none",
        "idempotency_keys": [],
        "params": {},
        "dry_run": True,
        "timeout_s": 2,
    }
    lever.update(extra)
    return lever


def write_lever(name: str, **extra: Any) -> dict[str, Any]:
    lever = read_lever(name, **{"class": "write", "approval": "lead", "required_role": "technician"})
    lever.update({"risk_class": "R2", "impact": IMPACT})
    lever.update(extra)
    return lever


def fragment(*levers: dict[str, Any], **top: Any) -> dict[str, Any]:
    return {"version": 1, "levers": list(levers), **top}


def workspace(tmp_path: Path, **fragments: Any) -> Path:
    """A private copy of the real registry with registry.d/<key>.json fragments; returns the main file path."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    main = tmp_path / "registry.json"
    shutil.copy(DEFAULT_REGISTRY_PATH, main)
    folder = tmp_path / "registry.d"
    folder.mkdir(exist_ok=True)
    for key, content in fragments.items():
        text = content if isinstance(content, str) else json.dumps(content)
        (folder / f"{key}.json").write_text(text, encoding="utf-8")
    return main


def load_error(main: Path, handlers: Any = HANDLERS) -> str:
    with pytest.raises(RegistryError) as info:
        Registry.load(main, handlers)
    return str(info.value)


@pytest.fixture
def family(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private folder that counts as part of the levers.python package, for fixture modules only."""
    folder = tmp_path / "pkg"
    folder.mkdir()
    monkeypatch.setattr(lever_package, "__path__", [*lever_package.__path__, str(folder)])
    before = set(sys.modules)
    yield folder  # type: ignore[misc]
    for name in set(sys.modules) - before:
        if name.startswith("levers.python."):
            del sys.modules[name]


def put_module(folder: Path, name: str, source: str) -> None:
    (folder / f"{name}.py").write_text(source, encoding="utf-8")


GOOD_MODULE = """
from collections.abc import Mapping
from typing import Any

from core.levers.handlers import LeverFailed


def widgets(state: dict[str, Any], params: Mapping[str, Any]) -> Any:
    if params.get("fail"):
        raise LeverFailed("no widgets")
    return state.get("widgets", [])
"""


# --- B14-1: main file plus fragments load as one registry --------------------------------------------


def test_b14_1_fragments_load_together_with_the_main_file(tmp_path: Path, family: Path) -> None:
    put_module(family, "b14_good", GOOD_MODULE)
    main = workspace(
        tmp_path,
        widgets=fragment(
            read_lever("widget.list", entry="levers.python.b14_good:widgets", runtime="python"), _note="a family"
        ),
        more=fragment(read_lever("gadget.list", description="Mock read, uses a built-in handler?", entry=None)),
    )
    # gadget.list has no handler: the whole load fails, naming the lever (no partial load)
    assert "gadget.list" in load_error(main) and "no implementation" in load_error(main)
    (tmp_path / "registry.d" / "more.json").unlink()

    registry = Registry.load(main)
    assert registry.names() == sorted([*FOUR, "widget.list"])
    handler = registry.handler("widget.list")
    assert handler({"widgets": [1]}, {}) == [1]
    assert registry.get("widget.list") is not None and "widget.list" in registry


def test_b14_1_fragments_load_in_name_order_and_ignore_other_files(tmp_path: Path, family: Path) -> None:
    put_module(family, "b14_good", GOOD_MODULE)
    entry = "levers.python.b14_good:widgets"
    main = workspace(
        tmp_path,
        b=fragment(read_lever("beta.list", entry=entry)),
        a=fragment(read_lever("alpha.list", entry=entry)),
    )
    (tmp_path / "registry.d" / "README.md").write_text("not json, ignored", encoding="utf-8")
    (tmp_path / "registry.d" / "notes.txt").write_text("{", encoding="utf-8")
    assert Registry.load(main).names() == sorted([*FOUR, "alpha.list", "beta.list"])


def test_b14_1_a_duplicate_name_across_files_fails_the_whole_load(tmp_path: Path, family: Path) -> None:
    put_module(family, "b14_good", GOOD_MODULE)
    entry = "levers.python.b14_good:widgets"
    main = workspace(
        tmp_path,
        one=fragment(read_lever("widget.list", entry=entry)),
        two=fragment(read_lever("widget.list", entry=entry)),
    )
    message = load_error(main)
    assert "'widget.list' is registered twice" in message and "one.json" in message and "two.json" in message

    clash = workspace(tmp_path / "clash", only=fragment(read_lever("ticket.get")))
    message = load_error(clash)
    assert "'ticket.get' is registered twice" in message and "registry.json" in message and "only.json" in message


def test_b14_1_a_fragment_without_version_fails_the_whole_load(tmp_path: Path) -> None:
    main = workspace(tmp_path, bad={"levers": []})
    message = load_error(main)
    assert "bad.json" in message and "version" in message


def test_b14_1_a_wrong_version_or_unreadable_fragment_fails_the_whole_load(tmp_path: Path) -> None:
    assert "version" in load_error(workspace(tmp_path / "a", bad={"version": 2, "levers": []}))
    assert "bad.json" in load_error(workspace(tmp_path / "b", bad="{not json"))
    assert "bad.json" in load_error(workspace(tmp_path / "c", bad=[1, 2]))


def test_b14_1_an_unknown_field_fails_the_whole_load(tmp_path: Path) -> None:
    on_file = workspace(tmp_path / "file", f=fragment(read_lever("widget.list"), colour="red"))
    assert "colour" in load_error(on_file)
    on_lever = workspace(tmp_path / "lever", f=fragment(read_lever("widget.list", colour="red")))
    message = load_error(on_lever)
    assert "'widget.list'" in message and "colour" in message and "f.json" in message
    bad_note = workspace(tmp_path / "note", f=fragment(read_lever("widget.list"), _note=5))
    assert "_note" in load_error(bad_note)
    other_underscore = workspace(tmp_path / "us", f=fragment(read_lever("widget.list"), _extra="x"))
    assert "_extra" in load_error(other_underscore)


def test_b14_1_one_bad_lever_in_a_fragment_registers_nothing(tmp_path: Path, family: Path) -> None:
    put_module(family, "b14_good", GOOD_MODULE)
    entry = "levers.python.b14_good:widgets"
    broken = write_lever("widget.set", entry=entry, impact=None)
    main = workspace(tmp_path, f=fragment(read_lever("widget.list", entry=entry), broken))
    message = load_error(main)
    assert "f.json" in message and "'widget.set'" in message


def test_b14_1_fragment_levers_follow_every_main_file_rule(tmp_path: Path, family: Path) -> None:
    put_module(family, "b14_good", GOOD_MODULE)
    entry = "levers.python.b14_good:widgets"
    no_risk = workspace(tmp_path / "a", f=fragment(write_lever("widget.set", entry=entry, risk_class=None)))
    assert "must declare risk_class" in load_error(no_risk)
    bad_undo = workspace(tmp_path / "b", f=fragment(write_lever("widget.set", entry=entry, undo="widget.unset")))
    assert "widget.unset" in load_error(bad_undo)
    ok = workspace(
        tmp_path / "c",
        f=fragment(
            write_lever("widget.set", entry=entry, undo="widget.unset"), write_lever("widget.unset", entry=entry)
        ),
    )
    assert "widget.set" in Registry.load(ok).names()


def test_b14_1_a_missing_main_file_fails(tmp_path: Path) -> None:
    assert "registry.json" in load_error(tmp_path / "registry.json")


def test_b14_1_explicit_fragment_folder_and_the_default_folder_next_to_the_file(tmp_path: Path, family: Path) -> None:
    put_module(family, "b14_good", GOOD_MODULE)
    main = workspace(tmp_path / "w", f=fragment(read_lever("widget.list", entry="levers.python.b14_good:widgets")))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert "widget.list" not in Registry.load(main, fragments_dir=elsewhere)
    assert "widget.list" in Registry.load(main, fragments_dir=tmp_path / "w" / "registry.d")


# --- B14-2: Python entries resolve only inside levers.python ------------------------------------------


def test_b14_2_a_good_entry_resolves_to_the_function_in_the_package(family: Path) -> None:
    put_module(family, "b14_good", GOOD_MODULE)
    handler = resolve_python_entry("levers.python.b14_good:widgets")
    assert callable(handler) and handler.__module__ == "levers.python.b14_good"


@pytest.mark.parametrize(
    "entry",
    [
        "os:getcwd",
        "subprocess:run",
        "builtins:eval",
        "core.levers.handlers:ticket_get",
        "levers:python",
        "levers.pythonx.thing:run",
        "levers.python/../core:run",
        "levers.python..x:run",
        "levers.python.b14_good",
        "levers.python.b14_good:",
        "levers.python.B14_Good:widgets",
        "levers.python.b14_good:widgets.__call__",
        "",
    ],
)
def test_b14_2_any_other_module_path_is_refused(entry: str, family: Path) -> None:
    put_module(family, "b14_good", GOOD_MODULE)
    with pytest.raises(EntryError):
        resolve_python_entry(entry)


def test_b14_2_a_missing_module_or_function_is_refused(family: Path) -> None:
    put_module(family, "b14_good", GOOD_MODULE)
    for entry in ("levers.python.b14_nothing:widgets", "levers.python.b14_good:nothing"):
        with pytest.raises(EntryError):
            resolve_python_entry(entry)


def test_b14_2_a_function_that_the_module_only_imports_is_refused(family: Path) -> None:
    put_module(family, "b14_reexport", "from os import getcwd\nfrom core.levers.handlers import ticket_get\nX = 5\n")
    for entry in ("levers.python.b14_reexport:getcwd", "levers.python.b14_reexport:ticket_get"):
        with pytest.raises(EntryError, match="defined in"):
            resolve_python_entry(entry)
    with pytest.raises(EntryError, match="no callable"):
        resolve_python_entry("levers.python.b14_reexport:x")


def test_b14_2_the_load_refuses_a_bad_entry_and_names_the_lever(tmp_path: Path, family: Path) -> None:
    put_module(family, "b14_good", GOOD_MODULE)
    for k, entry in enumerate(("os:getcwd", "levers.python.b14_good:nothing", "levers.python.nope:widgets")):
        main = workspace(tmp_path / str(k), f=fragment(read_lever("widget.list", entry=entry)))
        message = load_error(main)
        assert "'widget.list'" in message and entry in message and "f.json" in message
    not_text = workspace(tmp_path / "t", f=fragment(read_lever("widget.list", entry=7)))
    assert "entry must be a string" in load_error(not_text)


def test_b14_2_entry_in_the_main_file_is_checked_the_same_way(tmp_path: Path) -> None:
    raw = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    raw["levers"].append(read_lever("widget.list", entry="os:getcwd"))
    main = tmp_path / "registry.json"
    main.write_text(json.dumps(raw), encoding="utf-8")
    assert "os:getcwd" in load_error(main)


def test_b14_2_only_the_python_runtime_loads_until_the_bridge_exists(tmp_path: Path, family: Path) -> None:
    put_module(family, "b14_good", GOOD_MODULE)
    entry = "levers.python.b14_good:widgets"
    ps = workspace(tmp_path / "ps", f=fragment(read_lever("widget.list", runtime="powershell", entry="Mod\\Fn")))
    assert "runtime 'powershell'" in load_error(ps)
    junk = workspace(tmp_path / "junk", f=fragment(read_lever("widget.list", runtime="ruby", entry=entry)))
    assert "runtime 'ruby'" in load_error(junk)


def test_b14_2_an_entry_cannot_replace_a_built_in_handler(tmp_path: Path, family: Path) -> None:
    put_module(family, "b14_good", GOOD_MODULE)
    main = workspace(tmp_path, f=fragment(read_lever("ticket.search", entry="levers.python.b14_good:widgets")))
    handlers = {**HANDLERS, "ticket.search": HANDLERS["ticket.get"]}
    assert "both an entry and a built-in handler" in load_error(main, handlers)


def test_b14_2_a_lever_without_entry_still_needs_a_built_in_handler(tmp_path: Path) -> None:
    main = workspace(tmp_path, f=fragment(read_lever("widget.list")))
    assert "no implementation" in load_error(main)


# --- B14-3: the never-automate gate --------------------------------------------------------------------


def never_entries() -> list[dict[str, Any]]:
    raw = json.loads(DEFAULT_NEVER_AUTOMATE_PATH.read_text(encoding="utf-8"))
    entries: list[dict[str, Any]] = raw["entries"]
    return entries


def test_b14_3_the_list_covers_every_none_keep_human_inventory_id() -> None:
    inventory = json.loads((REPO / "map" / "inventory.json").read_text(encoding="utf-8"))
    human = {item["id"] for item in inventory if "none-keep-human" in item["automation_pattern"]}
    listed = [entry["inventory_id"] for entry in never_entries()]
    assert len(listed) == len(set(listed))
    assert set(listed) == human
    names = {item["id"]: item["name"] for item in inventory}
    assert all(entry["name"] == names[entry["inventory_id"]] for entry in never_entries())


@pytest.mark.parametrize(
    "name", ["role.grant-admin", "ca.set-policy", "hold.create", "vault.read", "license.purchase-seat"]
)
def test_b14_3_the_named_examples_are_refused_with_inventory_id_and_reason(name: str, tmp_path: Path) -> None:
    main = workspace(tmp_path, f=fragment(read_lever(name)))
    message = load_error(main, {**HANDLERS, name: HANDLERS["ticket.get"]})
    assert f"lever {name!r} is never automated" in message
    assert any(entry["inventory_id"] in message and entry["reason"] in message for entry in never_entries())


def test_b14_3_every_pattern_in_the_list_blocks_a_lever(tmp_path: Path) -> None:
    gate = NeverAutomate.load()
    for entry in never_entries():
        for pattern in entry["patterns"]:
            name = pattern.replace("*", "x")
            found = gate.match(name)
            assert found is not None, name
            with pytest.raises(RegistryError) as info:
                gate.check(name)
            assert entry["inventory_id"] in str(info.value) or found[0].inventory_id in str(info.value)
    assert gate.inventory_ids() == sorted(entry["inventory_id"] for entry in never_entries())


def test_b14_3_a_write_lever_cannot_slip_through_as_a_fragment(tmp_path: Path) -> None:
    lever = write_lever("role.grant-admin")
    main = workspace(tmp_path, f=fragment(lever))
    handlers = {**HANDLERS, "role.grant-admin": HANDLERS["user.disable"]}
    message = load_error(main, handlers)
    assert "W-IDM-07" in message and "role.grant*" in message and "f.json" in message


def test_b14_3_the_gate_also_holds_for_a_registry_built_in_code(tmp_path: Path) -> None:
    from core.levers import LeverDef

    lever = LeverDef.model_validate(read_lever("vault.read"))
    with pytest.raises(RegistryError, match="W-KB-07"):
        Registry([lever], {"vault.read": HANDLERS["ticket.get"]})


def test_b14_3_the_gate_in_the_main_file_names_the_inventory_id(tmp_path: Path) -> None:
    raw = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    raw["levers"].append(read_lever("hold.list"))
    main = tmp_path / "registry.json"
    main.write_text(json.dumps(raw), encoding="utf-8")
    message = load_error(main, {**HANDLERS, "hold.list": HANDLERS["ticket.get"]})
    assert "W-M365-12" in message and "hold.*" in message


def test_b14_3_levers_on_the_roadmap_that_are_not_human_only_are_not_blocked() -> None:
    gate = NeverAutomate.load()
    allowed = [
        "user.revoke-sessions", "user.reset-password", "user.set-properties", "user.new", "user.new-tap",
        "user.enable", "user.disable", "user.reset-mfa", "user.require-mfa", "license.add", "license.remove",
        "ticket.get", "ticket.link", "kb.search", "rag.search", "site.new", "signins.list", "risk.list-users",
        "restore.to-alternate", "quarantine.release", "message.trace", "inboxrule.list", "inboxrule.enable",
        "inboxrule.disable", "group.add-member", "group.remove-member", "device.install-app", "role.remove-member",
        "role.list", "ca.list", "backup.retry-job", "contact.check",
    ]  # fmt: skip
    assert [name for name in allowed if gate.match(name)] == []


def test_b14_3_a_missing_or_malformed_list_stops_the_load(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="never-automate"):
        NeverAutomate.load(tmp_path / "missing.json")

    def write(content: Any) -> Path:
        path = tmp_path / "n.json"
        path.write_text(json.dumps(content), encoding="utf-8")
        return path

    good = json.loads(DEFAULT_NEVER_AUTOMATE_PATH.read_text(encoding="utf-8"))
    bad_cases: list[dict[str, Any]] = []
    for mutate in (
        lambda d: d.pop("version"),
        lambda d: d.update(entries=[]),
        lambda d: d.update(extra=1),
        lambda d: d["entries"][0].update(patterns=["*"]),
        lambda d: d["entries"][0].update(patterns=["*.*"]),
        lambda d: d["entries"][0].update(patterns=["Role.Grant*"]),
        lambda d: d["entries"][0].update(patterns=[]),
        lambda d: d["entries"][0].update(reason=""),
        lambda d: d["entries"][0].update(inventory_id="idm-07"),
        lambda d: d["entries"][0].update(colour="red"),
    ):
        data = copy.deepcopy(good)
        mutate(data)
        bad_cases.append(data)
    for data in bad_cases:
        with pytest.raises(RegistryError, match="never-automate"):
            NeverAutomate.load(write(data))
    assert NeverAutomate.load(write(good)).inventory_ids() == NeverAutomate.load().inventory_ids()


def test_b14_3_a_custom_list_can_be_passed_to_the_loader(tmp_path: Path, family: Path) -> None:
    put_module(family, "b14_good", GOOD_MODULE)
    custom = tmp_path / "custom.json"
    custom.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [{"inventory_id": "W-TST-01", "name": "t", "reason": "test only", "patterns": ["widget.*"]}],
            }
        ),
        encoding="utf-8",
    )
    main = workspace(tmp_path, f=fragment(read_lever("widget.list", entry="levers.python.b14_good:widgets")))
    with pytest.raises(RegistryError, match="W-TST-01"):
        Registry.load(main, never=NeverAutomate.load(custom))
    assert "widget.list" in Registry.load(main)


# --- B14-4: the four existing levers load unchanged -----------------------------------------------------


def test_b14_4_the_four_existing_levers_load_unchanged() -> None:
    registry = Registry.load()
    assert [n for n in registry.names() if n in FOUR] == FOUR  # later fragments add levers beside them
    raw = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    assert [lever["name"] for lever in raw["levers"]] == ["ticket.get", "kb.search", "user.reset-mfa", "user.disable"]
    for name in FOUR:
        assert registry.handler(name) is HANDLERS[name]


def test_b14_4_the_committed_fragment_folder_loads_with_the_main_file() -> None:
    folder = REPO / "levers" / "registry.d"
    assert (folder / "README.md").is_file()
    assert Registry.load(fragments_dir=folder).names() == Registry.load().names()


def test_b14_4_a_registry_file_in_a_folder_with_no_fragments_loads_as_before(tmp_path: Path) -> None:
    main = tmp_path / "registry.json"
    shutil.copy(DEFAULT_REGISTRY_PATH, main)
    assert Registry.load(main).names() == FOUR


def _fragment_entries() -> list[str]:
    entries: list[str] = []
    for path in sorted((REPO / "levers" / "registry.d").glob("*.json")):
        for lever in json.loads(path.read_text(encoding="utf-8"))["levers"]:
            if "entry" in lever and lever.get("runtime", "python") == "python":  # PowerShell entries are modules
                entries.append(lever["entry"])
    return entries


def test_b14_4_the_python_package_for_levers_exists_and_is_empty_of_levers() -> None:
    package = REPO / "levers" / "python"
    assert (package / "__init__.py").is_file()
    # every module beside __init__.py is a lever family named by a committed registry.d fragment (B-23: ticket.py)
    modules = {p.name for p in package.glob("*.py")} - {"__init__.py"}
    assert modules == {entry.split(":")[0].rsplit(".", 1)[-1] + ".py" for entry in _fragment_entries()}
