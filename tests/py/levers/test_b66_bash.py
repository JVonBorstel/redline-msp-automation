"""B-66 macOS and Linux levers through a bash runtime (specs/B-66.md).

Acceptance ids B66-1 to B66-3. Every test is offline and works on private copies in tmp_path: the synthetic mock
unix hosts, the audit log and (for the timeout, environment and tamper tests) small fixture scripts with their own
manifest. Committed files are never modified. Tests that start bash skip when no usable bash is found; the golden
tests need nothing else. The shellcheck test reports SKIPPED, never passed, when shellcheck is not installed.
Run: uv run --frozen pytest tests/py/levers/test_b66_bash.py
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from core.audit import AuditLog, verify_chain
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, Approval, LeverRunner, MockTenant, Registry, RegistryError
from core.levers import bridge as bridge_module
from core.levers.bridge import (
    BASH_SCRIPT_RE,
    MOCK_DIR_ENV,
    SAFE_PARAM_RE,
    BashBridge,
    BashEntry,
    BridgeResult,
    EntryFormatError,
    ManifestError,
    is_wsl_launcher,
    load_manifest,
    parse_bash_entry,
)

REPO = Path(__file__).resolve().parents[3]
BASH_SRC = REPO / "levers" / "bash"
FRAGMENT = REPO / "levers" / "registry.d" / "unix.json"
CONTOSO, FABRIKAM, LITWARE = "contoso-dental", "fabrikam-capital", "litware-legal"
LEVERS = ("unix.disk-usage", "unix.restart-service", "unix.clear-cache")
needs_bash = pytest.mark.skipif(BashBridge().bash_path() is None, reason="no usable bash (Git Bash, Linux or macOS)")
FIXTURE_IMPACT = {
    "L1": "One synthetic host is affected in a test.",
    "L2": "One synthetic client is affected in a test.",
    "L3": "The MSP sees the call in the audit.",
    "L4": "Nothing leaves the test.",
}
METACHARS = ";&|$`()<>\\\"'\n\t *?{}[]~!#%^=,"


# -- helpers --------------------------------------------------------------------------------------------------


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_bytes(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


@dataclass
class Env:
    runner: LeverRunner
    registry: Registry
    bridge: BashBridge
    bash_root: Path
    mock_dir: Path
    audit_path: Path

    def records(self) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        return [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines()]

    def chain_ok(self) -> bool:
        return verify_chain(self.audit_path, self.audit_path.with_name("audit.jsonl.head")).ok

    def state(self) -> dict[str, bytes]:
        return tree_bytes(self.mock_dir)


class SpyBridge(BashBridge):
    """The real bridge, keeping every call's mode (to prove what never reached bash)."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.modes: list[str] = []

    def call(self, **kwargs: Any) -> BridgeResult:
        self.modes.append(kwargs["mode"])
        return super().call(**kwargs)


def copy_bash_tree(tmp_path: Path) -> Path:
    root = tmp_path / "bash"
    shutil.copytree(BASH_SRC, root)
    return root


def make_env(tmp_path: Path, bash_root: Path | None = None, fragment: Path = FRAGMENT) -> Env:
    root = bash_root or copy_bash_tree(tmp_path)
    fragments = tmp_path / "registry.d"
    fragments.mkdir(exist_ok=True)
    shutil.copy(fragment, fragments / "unix.json")
    registry = Registry.load(fragments_dir=fragments, bash_root=root)
    tenant_dir = tmp_path / "tenant"
    if not tenant_dir.exists():
        shutil.copytree(DEFAULT_TENANT_DIR, tenant_dir)
    audit_path = tmp_path / "audit.jsonl"
    bridge = SpyBridge(bash_root=root, mock_dir=root / "mock")
    runner = LeverRunner(
        registry, IdentityStore.load(), MockTenant(tenant_dir), AuditLog(audit_path), bash_bridge=bridge
    )
    return Env(runner, registry, bridge, root, root / "mock", audit_path)


def approval(lever: str, params: Mapping[str, Any], client: str = CONTOSO, approver: str = "lead-lee") -> Approval:
    return Approval(approver=approver, lever=lever, client=client, params=dict(params))


def execute(env: Env, lever: str, params: Mapping[str, Any], client: str = CONTOSO) -> Any:
    return env.runner.invoke(
        lever, params, "tech-ana", client, mode="execute", approval=approval(lever, params, client)
    )


def call_bridge(
    bridge: BashBridge,
    entry: str,
    lever: str,
    mode: str,
    params: Mapping[str, Any],
    client: str = CONTOSO,
    **extra: Any,
) -> BridgeResult:
    return bridge.call(
        lever=lever,
        lever_version=1,
        client=client,
        mode=mode,  # type: ignore[arg-type]
        params=params,
        entry=BashEntry(entry),
        timeout_s=extra.pop("timeout_s", 20),
        request_id="req-b66-test-0001",
        **extra,
    )


def write_fixture_root(tmp_path: Path, scripts: Mapping[str, str], name: str = "fixroot") -> Path:
    """A private bash root with the real lib, the given fixture scripts, a matching manifest and a mock host."""
    root = tmp_path / name
    (root / "lib").mkdir(parents=True)
    (root / "scripts").mkdir()
    lib = (BASH_SRC / "lib" / "lever.sh").read_bytes()
    (root / "lib" / "lever.sh").write_bytes(lib)
    entries = {}
    for script_name, text in scripts.items():
        data = text.replace("\r\n", "\n").encode("utf-8")
        (root / "scripts" / script_name).write_bytes(data)
        entries[script_name] = sha(data)
    manifest = {"version": 1, "scripts": entries, "libs": {"lever.sh": sha(lib)}}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    host = root / "mock" / CONTOSO
    host.mkdir(parents=True)
    return root


PRELUDE = '#!/usr/bin/env bash\n. "${BASH_SOURCE[0]%/*}/../lib/lever.sh"\nlever_init "$@"\n'


def fixture_fragment(tmp_path: Path, script: str, name: str = "fix.probe", write: bool = False) -> Path:
    lever: dict[str, Any] = {
        "name": name,
        "runtime": "bash",
        "entry": script,
        "description": "Test fixture lever.",
        "client_scope": "any",
        "required_role": "technician" if write else "agent",
        "class": "write" if write else "read",
        "approval": "lead" if write else "none",
        "idempotency_keys": [],
        "params": {},
        "dry_run": True,
        "timeout_s": 3,
    }
    if write:
        lever.update(
            {
                "dry_run_role": "agent",
                "risk_class": "R1",
                "reversibility": "reversible",
                "impact": FIXTURE_IMPACT,
            }
        )
    path = tmp_path / f"{name}.fragment.json"
    path.write_text(json.dumps({"version": 1, "levers": [lever]}), encoding="utf-8")
    return path


def run_raw(root: Path, script: str, stdin: str, args: tuple[str, ...] = ()) -> subprocess.CompletedProcess[str]:
    """Start a script directly (no bridge) to test the script's own refusals. Not how levers are run."""
    bash = BashBridge().bash_path()
    assert bash is not None
    return subprocess.run(  # noqa: S603 - test helper, fixed argv
        [bash, "--noprofile", "--norc", (root / "scripts" / script).as_posix(), *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=BashBridge(mock_dir=root / "mock").child_env(),
        timeout=20,
        check=False,
    )


def request_line(lever: str, mode: str, params: str, client: str = CONTOSO) -> str:
    head = f'{{"version":1,"request_id":"req-b66-raw-0001","lever":"{lever}","lever_version":1,'
    return head + f'"client":"{client}","mode":"{mode}","params":{{{params}}}}}\n'


# -- B66-1: runtime "bash" through the bridge ---------------------------------------------------------------------


def test_b66_1_the_fragment_loads_with_runtime_bash_and_other_runtimes_are_unchanged(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    for name in LEVERS:
        assert name in env.registry
        assert env.registry.runtime(name) == "bash"
        assert env.registry.powershell_entry(name) is None
    assert env.registry.bash_entry("unix.restart-service") == BashEntry("restart-service.sh")
    assert env.registry.bash_entry("kb.search") is None
    assert env.registry.runtime("kb.search") == "python"
    shipped = Registry.load()
    assert set(LEVERS) <= set(shipped.names())
    assert all(shipped.runtime(name) == "bash" for name in LEVERS)


def test_b66_1_the_shipped_manifest_pins_every_script_and_lib_by_sha256() -> None:
    manifest = load_manifest(BASH_SRC)
    on_disk = {p.name for p in (BASH_SRC / "scripts").glob("*") if p.is_file()}
    assert set(manifest.scripts) == on_disk == {"disk-usage-report.sh", "restart-service.sh", "clear-cache.sh"}
    assert set(manifest.libs) == {"lever.sh"}
    for name, digest in manifest.scripts.items():
        assert sha((BASH_SRC / "scripts" / name).read_bytes()) == digest
    assert sha((BASH_SRC / "lib" / "lever.sh").read_bytes()) == manifest.libs["lever.sh"]


@pytest.mark.parametrize(
    "text",
    [
        "../evil.sh",
        "/bin/sh",
        "scripts/clear-cache.sh",
        "clear-cache.sh;id",
        "clear-cache.sh ",
        "Clear-Cache.sh",
        "clear-cache.py",
        "clear-cache",
        "$(id).sh",
        "a" * 80 + ".sh",
        "",
        7,
        None,
    ],
)
def test_b66_1_a_malformed_bash_entry_names_no_path(text: object) -> None:
    with pytest.raises(EntryFormatError):
        parse_bash_entry(text)


def test_b66_1_the_entry_pattern_is_a_bare_file_name() -> None:
    assert BASH_SCRIPT_RE.fullmatch("clear-cache.sh")
    assert not BASH_SCRIPT_RE.fullmatch("../clear-cache.sh")
    assert parse_bash_entry("clear-cache.sh") == BashEntry("clear-cache.sh")


def test_b66_1_registry_load_refuses_a_bad_unlisted_or_missing_script(tmp_path: Path) -> None:
    raw = json.loads(FRAGMENT.read_text(encoding="utf-8"))
    root = copy_bash_tree(tmp_path)
    cases = {
        "../restart-service.sh": "must be a bare script file name",
        "nope.sh": "is not in levers/bash/manifest.json",
        "restart-service": "must be a bare script file name",
    }
    for index, (entry, message) in enumerate(cases.items()):
        broken = copy.deepcopy(raw)
        broken["levers"][1]["entry"] = entry
        folder = tmp_path / f"case{index}"
        folder.mkdir()
        (folder / "f.json").write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(RegistryError, match=message):
            Registry.load(fragments_dir=folder, bash_root=root)
    missing = copy.deepcopy(raw)
    del missing["levers"][1]["entry"]
    folder = tmp_path / "noentry"
    folder.mkdir()
    (folder / "f.json").write_text(json.dumps(missing), encoding="utf-8")
    with pytest.raises(RegistryError, match="runtime 'bash'"):
        Registry.load(fragments_dir=folder, bash_root=root)
    (root / "scripts" / "restart-service.sh").unlink()
    folder = tmp_path / "gone"
    folder.mkdir()
    (folder / "f.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RegistryError, match="restart-service.sh"):
        Registry.load(fragments_dir=folder, bash_root=root)


def test_b66_1_registry_load_refuses_a_script_that_no_longer_matches_its_pinned_hash(tmp_path: Path) -> None:
    root = copy_bash_tree(tmp_path)
    script = root / "scripts" / "clear-cache.sh"
    script.write_bytes(script.read_bytes() + b"\n# a late edit\n")
    folder = tmp_path / "frag"
    folder.mkdir()
    shutil.copy(FRAGMENT, folder / "unix.json")
    with pytest.raises(RegistryError, match="does not match its pinned sha256"):
        Registry.load(fragments_dir=folder, bash_root=root)


def test_b66_1_a_missing_or_broken_manifest_fails_the_load_closed(tmp_path: Path) -> None:
    root = copy_bash_tree(tmp_path)
    folder = tmp_path / "frag"
    folder.mkdir()
    shutil.copy(FRAGMENT, folder / "unix.json")
    (root / "manifest.json").write_text('{"version": 1, "scripts": {"x.sh": "nothex"}, "libs": {}}', encoding="utf-8")
    with pytest.raises(RegistryError, match="manifest"):
        Registry.load(fragments_dir=folder, bash_root=root)
    (root / "manifest.json").unlink()
    with pytest.raises(RegistryError, match="manifest"):
        Registry.load(fragments_dir=folder, bash_root=root)
    with pytest.raises(ManifestError):
        load_manifest(root)


@needs_bash
def test_b66_1_a_script_edited_after_load_is_refused_at_call_time_and_never_runs(tmp_path: Path) -> None:
    marker = tmp_path / "ran.marker"
    root = write_fixture_root(tmp_path, {"probe.sh": PRELUDE + 'lever_emit ok "fine" null "[]" false\n'})
    bridge = BashBridge(bash_root=root, mock_dir=root / "mock")
    ok = call_bridge(bridge, "probe.sh", "fix.probe", "execute", {})
    assert ok.status == "ok", ok.reason
    (root / "scripts" / "probe.sh").write_text(f': > "{marker.as_posix()}"\n', encoding="utf-8")
    refused = call_bridge(bridge, "probe.sh", "fix.probe", "execute", {})
    assert refused.status == "error" and "pinned sha256" in refused.reason
    assert not marker.exists()
    (root / "lib" / "lever.sh").write_text(f': > "{marker.as_posix()}"\n', encoding="utf-8")
    (root / "scripts" / "probe.sh").write_bytes((PRELUDE + 'lever_emit ok "fine" null "[]" false\n').encode())
    refused = call_bridge(bridge, "probe.sh", "fix.probe", "execute", {})
    assert refused.status == "error" and "pinned sha256" in refused.reason
    assert not marker.exists()


@needs_bash
def test_b66_1_a_script_not_in_the_manifest_is_refused_even_if_it_is_on_disk(tmp_path: Path) -> None:
    root = write_fixture_root(tmp_path, {"probe.sh": PRELUDE + 'lever_emit ok "fine" null "[]" false\n'})
    marker = tmp_path / "ran.marker"
    (root / "scripts" / "extra.sh").write_text(f': > "{marker.as_posix()}"\n', encoding="utf-8")
    bridge = BashBridge(bash_root=root, mock_dir=root / "mock")
    result = call_bridge(bridge, "extra.sh", "fix.probe", "execute", {})
    assert result.status == "error" and "not in the manifest" in result.reason
    assert not marker.exists()


@needs_bash
def test_b66_1_bash_starts_without_a_shell_or_profile_and_dry_run_is_the_what_if_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[dict[str, Any]] = []
    real_popen = subprocess.Popen

    def spy(argv: list[str], **kwargs: Any) -> Any:
        started.append({"argv": list(argv), "kwargs": dict(kwargs)})
        return real_popen(argv, **kwargs)

    monkeypatch.setattr(bridge_module.subprocess, "Popen", spy)
    env = make_env(tmp_path)
    assert env.runner.invoke("unix.restart-service", {"service": "cups"}, "triage-bot", CONTOSO).status == "ok"
    assert execute(env, "unix.restart-service", {"service": "cups"}).applied
    assert [("--what-if" in s["argv"]) for s in started] == [True, True, False]
    for item in started:
        argv = item["argv"]
        assert argv[1:3] == ["--noprofile", "--norc"]
        assert not item["kwargs"].get("shell")
        assert argv[-1] in ("--what-if",) or argv[-1].endswith(".sh")
        assert len([a for a in argv if a.startswith("-") and a != "--what-if"]) == 2
    assert env.chain_ok()


@needs_bash
def test_b66_1_the_request_is_the_lever_request_without_entry_and_params_never_reach_argv_or_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}
    real_popen = subprocess.Popen

    class Spy:
        def __init__(self, argv: list[str], **kwargs: Any) -> None:
            seen["argv"], seen["env"] = list(argv), dict(kwargs["env"])
            self.inner = real_popen(argv, **kwargs)
            self.returncode = 0

        def communicate(self, payload: bytes | None = None, timeout: float | None = None) -> tuple[bytes, bytes]:
            seen["stdin"] = payload
            out, err = self.inner.communicate(payload, timeout=timeout)
            self.returncode = self.inner.returncode
            return out, err

        def kill(self) -> None:
            self.inner.kill()

    monkeypatch.setattr(bridge_module.subprocess, "Popen", Spy)
    env = make_env(tmp_path)
    result = call_bridge(env.bridge, "restart-service.sh", "unix.restart-service", "dry-run", {"service": "chronyd"})
    assert result.status == "ok", result.reason
    line = seen["stdin"].decode("utf-8")
    assert line.endswith("\n") and line.count("\n") == 1
    request = json.loads(line)
    schema = json.loads((REPO / "schemas" / "lever-request.schema.json").read_text(encoding="utf-8"))
    assert set(request) <= set(schema["properties"]) and set(request) == set(schema["required"]) - {"entry"}
    assert request["version"] == 1 and request["mode"] == "dry-run" and request["params"] == {"service": "chronyd"}
    assert "chronyd" not in " ".join(seen["argv"])
    assert "chronyd" not in " ".join(seen["env"].values())


@needs_bash
@pytest.mark.parametrize("lever", ["unix.restart-service", "unix.clear-cache"])
def test_b66_1_dry_run_changes_nothing_and_execute_applies_exactly_the_dry_run_diff(tmp_path: Path, lever: str) -> None:
    env = make_env(tmp_path)
    params = {"service": "chronyd"} if lever == "unix.restart-service" else {"scope": "user-cache"}
    before = env.state()
    proposal = env.runner.invoke(lever, params, "triage-bot", CONTOSO)
    assert proposal.status == "ok" and not proposal.applied and proposal.diff, proposal.reason
    assert env.state() == before
    done = execute(env, lever, params)
    assert done.status == "ok" and done.applied, done.reason
    assert done.diff == proposal.diff
    assert env.state() != before
    again = execute(env, lever, params) if lever == "unix.clear-cache" else None
    if again is not None:
        assert again.status == "ok" and not again.applied and again.reason.startswith("no change")
    records = env.records()
    assert [r["mode"] for r in records][:2] == ["dry-run", "execute"]
    assert records[1]["result"]["applied"] is True
    assert env.chain_ok()


@needs_bash
def test_b66_1_every_registered_bash_write_lever_honours_what_if(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    examples = {"unix.restart-service": {"service": "rsyslog"}, "unix.clear-cache": {"scope": "app-cache"}}
    scripts = {"unix.restart-service": "restart-service.sh", "unix.clear-cache": "clear-cache.sh"}
    for name in env.registry.names():
        spec = env.registry.get(name)
        if spec is None or env.registry.runtime(name) != "bash" or spec.lever_class != "write":
            continue
        before = env.state()
        result = call_bridge(env.bridge, scripts[name], name, "dry-run", examples[name])
        assert result.status == "ok" and not result.applied and result.diff, name
        assert env.state() == before, f"{name} changed state during --what-if"


@needs_bash
def test_b66_1_a_script_that_changes_state_in_what_if_is_caught_by_the_diff_equality_check(tmp_path: Path) -> None:
    liar = (
        PRELUDE
        + 'lever_find_host\nn=0\n[[ -f "$LEVER_HOST/n" ]] && read -r n <"$LEVER_HOST/n"\nnext=$((n + 1))\n'
        + 'printf "%s" "$next" >"$LEVER_HOST/n"\n'
        + 'lever_emit ok "x" null "[{\\"op\\":\\"replace\\",\\"path\\":\\"/n\\",\\"before\\":$n,\\"after\\":$next}]" '
        + "$([[ $LEVER_WHAT_IF -eq 1 ]] && echo false || echo true)\n"
    )
    root = write_fixture_root(tmp_path, {"liar.sh": liar})
    fragment = fixture_fragment(tmp_path, "liar.sh", name="fix.liar", write=True)
    env = make_env(tmp_path, bash_root=root, fragment=fragment)
    result = env.runner.invoke("fix.liar", {}, "tech-ana", CONTOSO, mode="execute", approval=approval("fix.liar", {}))
    assert result.status == "error" and "did not match the dry-run diff" in result.reason
    assert env.chain_ok()


@needs_bash
def test_b66_1_a_read_lever_is_sent_without_what_if_and_a_change_from_it_is_discarded(tmp_path: Path) -> None:
    script = (
        PRELUDE
        + 'lever_emit ok "r" null "[{\\"op\\":\\"add\\",\\"path\\":\\"/x\\",\\"before\\":null,\\"after\\":1}]" false\n'
    )
    root = write_fixture_root(tmp_path, {"snoop.sh": script})
    env = make_env(tmp_path, bash_root=root, fragment=fixture_fragment(tmp_path, "snoop.sh", name="fix.snoop"))
    result = env.runner.invoke("fix.snoop", {}, "triage-bot", CONTOSO)
    assert result.status == "error" and "read lever tried to change state" in result.reason
    assert isinstance(env.bridge, SpyBridge) and env.bridge.modes == ["execute"]


@needs_bash
def test_b66_1_denials_happen_in_python_before_any_bash_starts(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    spy = env.bridge
    assert isinstance(spy, SpyBridge)
    before = env.state()
    lever, params = "unix.restart-service", {"service": "cups"}
    cases: list[tuple[str, Any, str]] = [
        ("triage-bot", approval(lever, params), "cannot execute"),
        ("tech-ana", None, "needs a lead approval record"),
        ("tech-ana", approval(lever, {"service": "rsyslog"}), "does not match this lever, client and params"),
        ("tech-ben", approval(lever, params), "not scoped to client"),
    ]
    for identity, given, expected in cases:
        result = env.runner.invoke(lever, params, identity, CONTOSO, mode="execute", approval=given)
        assert result.status == "denied" and expected in result.reason, (identity, result.reason)
    assert spy.modes == []
    assert env.state() == before
    assert env.chain_ok()


@needs_bash
def test_b66_1_the_child_gets_a_scrubbed_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret_name = "REDLINE_TEST_" + "TOKEN"  # built at runtime: a secret-shaped variable name, not a real secret
    marker = tmp_path / "bashenv.marker"
    startup = tmp_path / "startup.sh"
    startup.write_text(f': > "{marker.as_posix()}"\n', encoding="utf-8")
    monkeypatch.setenv(secret_name, "not-a-real-value")
    monkeypatch.setenv("BASH_ENV", startup.as_posix())
    monkeypatch.setenv("ENV", startup.as_posix())
    script = (
        PRELUDE
        + 'names=""\nfor n in $(compgen -e); do\n'
        + '  [[ "$n" =~ ^[A-Za-z0-9_]+$ ]] && names="${names:+$names,}\\"$n\\""\ndone\n'
        + 'lever_emit ok "env" "[$names]" "[]" false\n'
    )
    root = write_fixture_root(tmp_path, {"probe.sh": script})
    bridge = BashBridge(bash_root=root, mock_dir=root / "mock")
    result = call_bridge(bridge, "probe.sh", "fix.probe", "execute", {})
    assert result.status == "ok", result.reason
    names = set(result.data)
    assert secret_name not in names and "BASH_ENV" not in names and "ENV" not in names
    assert MOCK_DIR_ENV in names and "PATH" in names
    assert not marker.exists(), "BASH_ENV was honoured"


@needs_bash
def test_b66_1_the_child_is_killed_at_the_timeout_and_nothing_is_reported_as_applied(tmp_path: Path) -> None:
    root = write_fixture_root(tmp_path, {"hang.sh": PRELUDE + "while :; do :; done\n"})
    bridge = BashBridge(bash_root=root, mock_dir=root / "mock")
    started = time.monotonic()
    result = call_bridge(bridge, "hang.sh", "fix.hang", "execute", {}, timeout_s=1.5)
    assert time.monotonic() - started < 12
    assert result.status == "error" and "timed out after 1.5s" in result.reason and "killed" in result.reason
    assert not result.applied and result.diff == ()


def test_b66_1_a_missing_bash_is_an_error_result_and_nothing_runs(tmp_path: Path) -> None:
    bridge = BashBridge(bash=str(tmp_path / "no-such-bash"), bash_root=BASH_SRC, mock_dir=BASH_SRC / "mock")
    result = call_bridge(bridge, "restart-service.sh", "unix.restart-service", "dry-run", {"service": "cups"})
    assert result.status == "error" and "nothing ran" in result.reason


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("C:\\Windows\\System32\\bash.exe", True),
        ("c:/windows/system32/bash.exe", True),
        ("C:\\Users\\x\\AppData\\Local\\Microsoft\\WindowsApps\\bash.exe", True),
        ("C:\\Program Files\\Git\\usr\\bin\\bash.exe", False),
        ("/bin/bash", False),
        ("/usr/local/bin/bash", False),
    ],
)
def test_b66_1_the_windows_wsl_launcher_is_not_accepted_as_the_bash(path: str, expected: bool) -> None:
    assert is_wsl_launcher(path) is expected


@needs_bash
def test_b66_1_a_script_answering_wrongly_is_discarded(tmp_path: Path) -> None:
    scripts = {
        "two.sh": PRELUDE + 'echo extra\nlever_emit ok "x" null "[]" false\n',
        "other.sh": PRELUDE
        + r"""printf '{"status":"ok","reason":"","lever":"x.y","client":"%s",' "$LEVER_CLIENT"
"""
        + r"""printf '"mode":"%s",' "$LEVER_MODE"
"""
        + r"""printf '"data":null,"diff":[],"applied":false}\n'
""",
        "dryapplied.sh": PRELUDE + 'lever_emit ok "x" null "[]" true\n',
        "crash.sh": PRELUDE + "exit 7\n",
    }
    root = write_fixture_root(tmp_path, scripts)
    bridge = BashBridge(bash_root=root, mock_dir=root / "mock")
    for script in scripts:
        result = call_bridge(bridge, script, "fix.probe", "dry-run", {})
        assert result.status == "error" and not result.applied, (script, result)


# -- B66-2: three levers with golden-output tests ------------------------------------------------------------------


GOLDEN_CASES = [
    ("disk-usage-contoso-dental", "disk-usage-report.sh", "unix.disk-usage", "execute", {}, CONTOSO),
    (
        "disk-usage-fabrikam-capital-threshold-50",
        "disk-usage-report.sh",
        "unix.disk-usage",
        "execute",
        {"threshold_pct": 50},
        FABRIKAM,
    ),
    (
        "restart-service-contoso-dental-chronyd-dry-run",
        "restart-service.sh",
        "unix.restart-service",
        "dry-run",
        {"service": "chronyd"},
        CONTOSO,
    ),
    (
        "restart-service-contoso-dental-chronyd-execute",
        "restart-service.sh",
        "unix.restart-service",
        "execute",
        {"service": "chronyd"},
        CONTOSO,
    ),
    (
        "clear-cache-contoso-dental-user-cache-dry-run",
        "clear-cache.sh",
        "unix.clear-cache",
        "dry-run",
        {"scope": "user-cache"},
        CONTOSO,
    ),
    (
        "clear-cache-contoso-dental-user-cache-execute",
        "clear-cache.sh",
        "unix.clear-cache",
        "execute",
        {"scope": "user-cache"},
        CONTOSO,
    ),
]


@needs_bash
@pytest.mark.parametrize(("golden", "script", "lever", "mode", "params", "client"), GOLDEN_CASES)
def test_b66_2_golden_output(
    tmp_path: Path, golden: str, script: str, lever: str, mode: str, params: dict[str, Any], client: str
) -> None:
    root = copy_bash_tree(tmp_path)
    bridge = BashBridge(bash_root=root, mock_dir=root / "mock")
    result = call_bridge(bridge, script, lever, mode, params, client)
    expected = json.loads((BASH_SRC / "golden" / f"{golden}.json").read_text(encoding="utf-8"))
    assert result.model_dump(mode="json") == expected


@needs_bash
def test_b66_2_the_golden_files_are_not_stale_every_golden_has_a_case() -> None:
    names = {p.stem for p in (BASH_SRC / "golden").glob("*.json")}
    assert names == {case[0] for case in GOLDEN_CASES}


@needs_bash
def test_b66_2_the_clear_cache_execute_removes_the_planned_files_and_only_those(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    cache = env.mock_dir / CONTOSO / "cache"
    other_scope = tree_bytes(cache / "app-cache")
    other_client = tree_bytes(env.mock_dir / FABRIKAM)
    result = execute(env, "unix.clear-cache", {"scope": "user-cache"})
    assert result.applied and sorted(c.path for c in result.diff) == [
        "/cache/user-cache/fonts.cache",
        "/cache/user-cache/thumbs.db.cache",
    ]
    assert list((cache / "user-cache").iterdir()) == []
    assert tree_bytes(cache / "app-cache") == other_scope
    assert tree_bytes(env.mock_dir / FABRIKAM) == other_client


@needs_bash
def test_b66_2_restart_of_a_running_service_changes_only_its_counter(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    result = execute(env, "unix.restart-service", {"service": "cups"})
    assert [c.model_dump() for c in result.diff] == [
        {"op": "replace", "path": "/services/cups/restarts", "before": 2, "after": 3}
    ]
    table = (env.mock_dir / CONTOSO / "services.tsv").read_text(encoding="utf-8")
    assert table.replace("\r", "") == "cups\trunning\t3\nchronyd\tstopped\t0\nrsyslog\trunning\t5\n"


@needs_bash
def test_b66_2_one_client_never_sees_or_changes_another_clients_host(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    other = tree_bytes(env.mock_dir / FABRIKAM)
    execute(env, "unix.restart-service", {"service": "cups"})
    execute(env, "unix.clear-cache", {"scope": "app-cache"})
    assert tree_bytes(env.mock_dir / FABRIKAM) == other
    report = env.runner.invoke("unix.disk-usage", {}, "triage-bot", FABRIKAM)
    assert report.status == "ok" and [m["mount"] for m in report.data["mounts"]] == ["/", "/var"]


@needs_bash
def test_b66_2_a_client_without_a_mock_host_is_an_error_not_an_empty_report(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    result = call_bridge(env.bridge, "disk-usage-report.sh", "unix.disk-usage", "execute", {}, client=LITWARE)
    assert result.status == "error" and "no mock unix host" in result.reason and result.data is None


@needs_bash
@pytest.mark.parametrize("value", ["0", "101", "-5", "abc", "99999999999999999999"])
def test_b66_2_a_bad_threshold_is_refused_by_the_script_even_if_the_registry_check_is_bypassed(
    tmp_path: Path, value: str
) -> None:
    root = copy_bash_tree(tmp_path)
    raw = request_line("unix.disk-usage", "execute", f'"threshold_pct":"{value}"')
    done = run_raw(root, "disk-usage-report.sh", raw)
    assert done.returncode == 1 and '"status":"error"' in done.stdout


def test_b66_2_shellcheck_runs_clean_or_is_reported_skipped_never_passed() -> None:
    shellcheck = shutil.which("shellcheck")
    if shellcheck is None:
        pytest.skip("shellcheck is not installed; the B66-2 lint check did NOT run")
    files = sorted(str(p) for p in BASH_SRC.rglob("*.sh"))
    done = subprocess.run(  # noqa: S603 - fixed argv, repo files
        [shellcheck, "--shell=bash", "--external-sources", "--source-path=SCRIPTDIR", *files],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout


# -- B66-3: no free-form command, injection safe -------------------------------------------------------------------


def load_fragment() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(FRAGMENT.read_text(encoding="utf-8"))
    return loaded


def refuse_with(tmp_path: Path, mutate: Any, message: str) -> None:
    raw = load_fragment()
    mutate(raw["levers"][1])
    folder = tmp_path / "bad"
    folder.mkdir(exist_ok=True)
    (folder / "f.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RegistryError, match=message):
        Registry.load(fragments_dir=folder, bash_root=BASH_SRC)


@pytest.mark.parametrize(
    "name", ["command", "cmd", "shell", "script", "exec", "eval", "args", "argv", "code", "run", "bash", "path", "file"]
)
def test_b66_3_a_free_form_parameter_name_is_refused_at_load(tmp_path: Path, name: str) -> None:
    def add(lever: dict[str, Any]) -> None:
        lever["params"][name] = {"type": "string", "required": False, "max_length": 20, "enum": ["cups"]}

    refuse_with(tmp_path, add, "free-form")


@pytest.mark.parametrize(
    "spec",
    [
        {"type": "string", "required": True},
        {"type": "string", "required": True, "max_length": 40},
        {"type": "string", "required": True, "max_length": 40, "pattern": ".*"},
        {"type": "string", "required": True, "max_length": 40, "pattern": "^[a-z ;]+$"},
        {"type": "string", "required": True, "max_length": 40, "pattern": "^[^\\n]+$"},
        {"type": "string", "required": True, "max_length": 400, "pattern": "^[a-z]+$"},
        {"type": "string", "required": True, "enum": ["cups", "x; id"]},
        {"type": "string", "required": True, "enum": ["$(id)"]},
    ],
)
def test_b66_3_a_string_parameter_must_be_an_enum_or_a_tight_pattern(tmp_path: Path, spec: dict[str, Any]) -> None:
    def swap(lever: dict[str, Any]) -> None:
        lever["params"] = {"service": spec}

    refuse_with(tmp_path, swap, "param 'service'")


def test_b66_3_every_shipped_bash_lever_parameter_is_an_enum_or_a_tight_pattern() -> None:
    registry = Registry.load()
    for name in LEVERS:
        spec = registry.get(name)
        assert spec is not None
        for pname, param in spec.params.items():
            assert pname not in {"command", "cmd", "shell", "script", "args", "path"}
            if param.type == "string":
                assert param.enum is not None or (param.pattern and param.max_length and param.max_length <= 64)
                for value in param.enum or ():
                    assert SAFE_PARAM_RE.fullmatch(str(value))


def test_b66_3_the_scripts_contain_no_eval_exec_or_dynamic_code() -> None:
    forbidden = (
        "eval ",
        "eval\t",
        "bash -c",
        "sh -c",
        "exec ",
        "`",
        "xargs",
        "ssh ",
        "curl",
        "wget",
        "source ",
        "sudo",
    )
    only_source = '. "${BASH_SOURCE[0]%/*}/../lib/lever.sh"'
    for path in sorted(BASH_SRC.rglob("*.sh")):
        data = path.read_bytes()
        assert b"\r" not in data, f"{path.name} has CR line endings"
        code = [ln for ln in data.decode("utf-8").splitlines() if not ln.lstrip().startswith("#")]
        for line in code:
            for token in forbidden:
                assert token not in line, f"{path.name} contains {token!r}: {line}"
            if line.startswith(". "):
                assert line == only_source, f"{path.name} sources something else: {line}"


@needs_bash
@pytest.mark.parametrize(
    "payload",
    [
        "cups; touch {m}",
        "cups && touch {m}",
        "cups | touch {m}",
        "$(touch {m})",
        "`touch {m}`",
        "cups\ntouch {m}",
        "cups' ; touch {m} ; '",
        'cups" ; touch {m} ; "',
        "cups\\",
        "cups}",
        "{cups}",
        "cups touch",
        "cups>{m}",
        "../cups",
        "cups\x00",
        "ü",
    ],
)
def test_b66_3_shell_metacharacters_in_a_parameter_never_reach_bash(tmp_path: Path, payload: str) -> None:
    env = make_env(tmp_path)
    marker = tmp_path / "pwned.marker"
    value = payload.replace("{m}", marker.as_posix())
    spy = env.bridge
    assert isinstance(spy, SpyBridge)
    before = env.state()
    result = call_bridge(env.bridge, "restart-service.sh", "unix.restart-service", "execute", {"service": value})
    assert result.status == "error" and "nothing ran" in result.reason and not result.applied
    assert not marker.exists() and env.state() == before
    via_runner = env.runner.invoke("unix.restart-service", {"service": value}, "triage-bot", CONTOSO)
    assert via_runner.status == "denied" and "invalid params" in via_runner.reason
    assert spy.modes == ["execute"]  # only the direct call above; the runner refused the other one before the bridge
    assert not marker.exists()


@needs_bash
def test_b66_3_a_charset_safe_value_outside_the_allowlist_is_refused_by_the_script_itself(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    before = env.state()
    for lever, script, key, value in (
        ("unix.restart-service", "restart-service.sh", "service", "sshd"),
        ("unix.restart-service", "restart-service.sh", "service", "CUPS"),
        ("unix.restart-service", "restart-service.sh", "service", ".."),
        ("unix.clear-cache", "clear-cache.sh", "scope", ".."),
        ("unix.clear-cache", "clear-cache.sh", "scope", "user-cache.."),
        ("unix.clear-cache", "clear-cache.sh", "scope", ""),
    ):
        result = call_bridge(env.bridge, script, lever, "execute", {key: value})
        assert result.status == "error" and not result.applied and "nothing ran" in result.reason, (value, result)
    assert env.state() == before


@needs_bash
@pytest.mark.parametrize(
    "client", ["../contoso-dental", "contoso dental", "Contoso", "a;b", "", "x" * 70, "contoso-dental/../x"]
)
def test_b66_3_a_hostile_client_id_never_becomes_a_path(tmp_path: Path, client: str) -> None:
    env = make_env(tmp_path)
    result = call_bridge(env.bridge, "disk-usage-report.sh", "unix.disk-usage", "execute", {}, client=client)
    assert result.status == "error" and "nothing ran" in result.reason


@needs_bash
def test_b66_3_a_request_id_or_lever_name_with_shell_characters_is_refused_before_bash_starts(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    spy = env.bridge
    assert isinstance(spy, SpyBridge)
    bad = env.bridge.call(
        lever="unix.disk-usage",
        lever_version=1,
        client=CONTOSO,
        mode="execute",
        params={},
        entry=BashEntry("disk-usage-report.sh"),
        timeout_s=5,
        request_id="x; id",
    )
    assert bad.status == "error" and "nothing ran" in bad.reason
    bad = call_bridge(env.bridge, "disk-usage-report.sh", "unix.disk-usage;id", "execute", {})
    assert bad.status == "error" and "nothing ran" in bad.reason


@needs_bash
def test_b66_3_hostile_file_names_in_a_cache_folder_are_never_run_or_followed(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    folder = env.mock_dir / CONTOSO / "cache" / "user-cache"
    marker = tmp_path / "pwned.marker"
    odd = ["a;touch pwned", "$(touch pwned)", "`touch pwned`", "x y", "a&b", "(sub)", "ünï.cache"]
    created = []
    for name in odd:
        try:
            (folder / name).write_text(f"touch {marker}", encoding="utf-8")
            created.append(name)
        except OSError:
            continue
    (folder / "nested").mkdir()
    (folder / "nested" / "keep.cache").write_text("keep", encoding="utf-8")
    option_like = folder / "-rf"
    option_like.write_text("plain", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("must survive", encoding="utf-8")
    try:
        (folder / "link.cache").symlink_to(outside)
    except (OSError, NotImplementedError):
        pass
    result = execute(env, "unix.clear-cache", {"scope": "user-cache"})
    assert result.status == "ok" and result.applied, result.reason
    assert {c.path.rsplit("/", 1)[1] for c in result.diff} == {"thumbs.db.cache", "fonts.cache", "-rf"}
    assert result.data["skipped"] >= len(created) + 1
    for name in created:
        assert (folder / name).exists(), name
    assert (folder / "nested" / "keep.cache").read_text(encoding="utf-8") == "keep"
    assert outside.read_text(encoding="utf-8") == "must survive"
    assert not marker.exists()
    assert not option_like.exists()


@needs_bash
def test_b66_3_the_script_alone_rejects_a_forged_request(tmp_path: Path) -> None:
    root = copy_bash_tree(tmp_path)
    marker = tmp_path / "pwned.marker"
    before = tree_bytes(root / "mock")
    good = request_line("unix.restart-service", "dry-run", '"service":"cups"')
    assert run_raw(root, "restart-service.sh", good, ("--what-if",)).returncode == 0
    forged = {
        "wrong flag": (good, ("--what-if", "--force")),
        "flag word": (good, (f"--what-if; touch {marker.as_posix()}",)),
        "mode and flag disagree": (good, ()),
        "execute with what-if": (request_line("unix.restart-service", "execute", '"service":"cups"'), ("--what-if",)),
        "not json": ("service=cups\n", ()),
        "empty": ("", ()),
        "extra field": (good.replace('"params"', '"entry":"x","params"'), ("--what-if",)),
        "brace in value": (request_line("unix.restart-service", "dry-run", '"service":"cups}"'), ("--what-if",)),
        "client path": (request_line("unix.restart-service", "dry-run", '"service":"cups"', "../x"), ("--what-if",)),
    }
    for label, (stdin, args) in forged.items():
        done = run_raw(root, "restart-service.sh", stdin, args)
        assert done.returncode == 2, (label, done.stdout, done.stderr)
        assert json.loads(done.stdout.strip().splitlines()[-1])["status"] == "error", label
    assert not marker.exists()
    assert tree_bytes(root / "mock") == before


@needs_bash
def test_b66_3_a_parameter_cannot_smuggle_another_parameter_or_a_second_value(tmp_path: Path) -> None:
    root = copy_bash_tree(tmp_path)
    before = tree_bytes(root / "mock")
    smuggled = request_line("unix.restart-service", "dry-run", '"scope":"x","service":"cups"')
    done = run_raw(root, "restart-service.sh", smuggled, ("--what-if",))
    assert done.returncode == 0 and '"service":"cups"' in done.stdout
    hidden = request_line("unix.restart-service", "dry-run", '"note":"service\\":\\"rsyslog","service":"cups"')
    done = run_raw(root, "restart-service.sh", hidden, ("--what-if",))
    assert done.returncode == 0 and '"service":"cups"' in done.stdout and "rsyslog" not in done.stdout
    quoted = request_line("unix.restart-service", "dry-run", '"service":"cups\\"; touch x"')
    done = run_raw(root, "restart-service.sh", quoted, ("--what-if",))
    assert done.returncode == 1 and '"status":"error"' in done.stdout  # not a value it can read: no service
    assert tree_bytes(root / "mock") == before


def test_b66_3_the_bridge_charset_admits_no_shell_or_json_metacharacter() -> None:
    for char in METACHARS + "\x00\x7f\u00fc":
        assert SAFE_PARAM_RE.fullmatch(f"a{char}a") is None, repr(char)
    assert SAFE_PARAM_RE.fullmatch("user-cache") and SAFE_PARAM_RE.fullmatch("a.b_c:d@e+f-g")
