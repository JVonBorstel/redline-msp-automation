"""Load levers/registry.json plus every levers/registry.d/*.json as one registry. Fails closed.

One bad lever, one bad fragment, or one never-automate match and nothing loads. Every error names the lever
it is about (and the fragment file, when it is not the main file). From B-01 every write lever must declare
its risk class and its impact trace (L1-L4), and an `undo` must name another registered write lever.

B-14 adds three things:
- fragments: lever families land as their own `levers/registry.d/<family>.json`, so they never touch one file;
- Python entries: a lever may carry `"entry": "levers.python.<module>:<function>"`, resolved only inside that
  package (`core.levers.handlers.resolve_python_entry`); `runtime` is `"python"` or, since B-16, `"powershell"`
  (entry `<Module>\\<Verb-Noun>`, run by the bridge) or, since B-66, `"bash"` (entry a bare `name.sh` pinned by hash
  in `levers/bash/manifest.json`, run by the bash bridge, with no free-form parameter);
- the never-automate gate: `governance/never-automate.json` lists the human-only work (inventory
  `none-keep-human`) with lever-name patterns, and no lever whose name matches can be registered (C-01, C-29).
"""

from __future__ import annotations

import fnmatch
import json
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from core.levers.bridge import (
    DEFAULT_BASH_ROOT,
    DEFAULT_POWERSHELL_ROOT,
    BashEntry,
    EntryFormatError,
    ManifestError,
    PowerShellEntry,
    check_bash_params,
    load_manifest,
    parse_bash_entry,
    parse_entry,
    read_pinned,
)
from core.levers.handlers import HANDLERS, EntryError, Handler, LeverFailed, resolve_python_entry
from core.levers.models import LeverDef

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = _REPO_ROOT / "levers" / "registry.json"
DEFAULT_NEVER_AUTOMATE_PATH = _REPO_ROOT / "governance" / "never-automate.json"
FRAGMENTS_DIRNAME = "registry.d"

_PATTERN_RE = re.compile(r"^[a-z0-9*.-]+$")
_INVENTORY_ID_RE = re.compile(r"^W-[A-Z0-9]+-[0-9]{2}$")


class RegistryError(ValueError):
    """The registry file is missing or invalid, a lever has no implementation, or a lever is never-automate."""


class _RegistryFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1, le=1)
    levers: list[dict[str, Any]]


class _NeverEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    inventory_id: str = Field(pattern=_INVENTORY_ID_RE.pattern)
    name: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=400)
    patterns: tuple[str, ...] = Field(min_length=1)

    @field_validator("patterns")
    @classmethod
    def _patterns_are_specific(cls, patterns: tuple[str, ...]) -> tuple[str, ...]:
        for pattern in patterns:
            # Lowercase lever-name characters and "*" only, with at least one "." so a pattern can never be
            # a bare "*" or "*.*" that would either match nothing useful or everything.
            if not _PATTERN_RE.match(pattern) or "." not in pattern or pattern.strip("*.") == "":
                raise ValueError(f"pattern {pattern!r} must be lowercase lever-name characters and '*', with a '.'")
        return patterns


class _NeverFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1, le=1)
    entries: tuple[_NeverEntry, ...] = Field(min_length=1)


class NeverAutomate:
    """The human-only work, as lever-name patterns. `check` raises RegistryError for a matching name."""

    def __init__(self, entries: tuple[_NeverEntry, ...]) -> None:
        self._entries = entries

    @classmethod
    def load(cls, path: Path = DEFAULT_NEVER_AUTOMATE_PATH) -> NeverAutomate:
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("_note"), str):
                raw = {key: value for key, value in raw.items() if key != "_note"}
            parsed = _NeverFile.model_validate(raw)
        except (OSError, ValueError, ValidationError) as exc:
            raise RegistryError(f"cannot load never-automate list {path}: {exc}") from exc
        return cls(parsed.entries)

    def inventory_ids(self) -> list[str]:
        return sorted(entry.inventory_id for entry in self._entries)

    def match(self, name: str) -> tuple[_NeverEntry, str] | None:
        for entry in self._entries:
            for pattern in entry.patterns:
                if fnmatch.fnmatchcase(name, pattern):
                    return entry, pattern
        return None

    def check(self, name: str) -> None:
        found = self.match(name)
        if found is not None:
            entry, pattern = found
            raise RegistryError(
                f"lever {name!r} is never automated: {entry.inventory_id} {entry.name} "
                f"(matches pattern {pattern!r}): {entry.reason}"
            )


@lru_cache(maxsize=1)
def _default_never_automate() -> NeverAutomate:
    return NeverAutomate.load()


def _lever_label(raw: Mapping[str, Any], index: int) -> str:
    name = raw.get("name")
    return repr(name) if isinstance(name, str) else f"#{index}"


def _parse_lever(raw: Mapping[str, Any], index: int) -> LeverDef:
    """Validate one registry entry; a write lever must also declare risk_class and impact (B01-1)."""
    label = _lever_label(raw, index)
    try:
        lever = LeverDef.model_validate(raw)
    except ValidationError as exc:
        raise RegistryError(f"lever {label} is invalid: {exc}") from exc
    if lever.lever_class == "write":
        missing = [field for field in ("risk_class", "impact") if getattr(lever, field) is None]
        if missing:
            raise RegistryError(f"write lever {label} must declare {' and '.join(missing)} (B-01, governance 6.1)")
    return lever


def _powershell_only(state: dict[str, Any], params: Mapping[str, Any]) -> Any:
    """Stand-in handler for a PowerShell lever: the runner dispatches by runtime and never calls this (B-16)."""
    raise LeverFailed("a PowerShell lever runs through the PowerShell bridge, not in-process")


def _bash_only(state: dict[str, Any], params: Mapping[str, Any]) -> Any:
    """Stand-in handler for a bash lever: the runner dispatches by runtime and never calls this (B-66)."""
    raise LeverFailed("a bash lever runs through the bash bridge, not in-process")


def _vet_bash_entry(entry: object, label: str, bash_root: Path) -> BashEntry:
    """A bash lever names a bare script that the manifest lists and whose bytes still match their pinned hash."""
    try:
        target = parse_bash_entry(entry)
    except EntryFormatError as exc:
        raise RegistryError(f"lever {label}: runtime 'bash': {exc}") from exc
    try:
        manifest = load_manifest(bash_root)
    except ManifestError as exc:
        raise RegistryError(f"lever {label}: runtime 'bash': {exc}") from exc
    if target.script not in manifest.scripts:
        raise RegistryError(
            f"lever {label}: runtime 'bash' entry {target.script!r} is not in levers/bash/manifest.json"
        )
    try:
        read_pinned(bash_root, manifest, target.script)
    except ManifestError as exc:
        raise RegistryError(f"lever {label}: runtime 'bash' entry {target.script!r}: {exc}") from exc
    return target


def _split_implementation(
    raw: Mapping[str, Any], label: str, powershell_root: Path, bash_root: Path = DEFAULT_BASH_ROOT
) -> tuple[dict[str, Any], Handler | None, PowerShellEntry | BashEntry | None]:
    """Take `runtime` and `entry` off a lever entry and resolve them (B14-2, B16-1).

    Python: `levers.python.<module>:<function>`, resolved only inside that package. PowerShell: `<Module>\\<Verb-Noun>`,
    whose module folder must exist under `powershell_root` (the host checks the function is exported when it runs).
    """
    clean = {key: value for key, value in raw.items() if key not in ("runtime", "entry")}
    if "runtime" not in raw and "entry" not in raw:
        return clean, None, None
    runtime = raw.get("runtime", "python")
    entry = raw.get("entry")
    if runtime == "powershell":
        try:
            target = parse_entry(entry)
        except EntryFormatError as exc:
            raise RegistryError(f"lever {label}: runtime 'powershell': {exc}") from exc
        if not (powershell_root / target.module / f"{target.module}.psd1").is_file():
            raise RegistryError(
                f"lever {label}: runtime 'powershell' entry {str(target)!r}: module {target.module} is not installed "
                "under levers/powershell"
            )
        return clean, _powershell_only, target
    if runtime == "bash":
        return clean, _bash_only, _vet_bash_entry(entry, label, bash_root)
    if runtime != "python":
        raise RegistryError(
            f"lever {label}: runtime {runtime!r} is not supported (use 'python', 'powershell' or 'bash')"
        )
    if entry is None:
        return clean, None, None
    if not isinstance(entry, str):
        raise RegistryError(f"lever {label}: entry must be a string like 'levers.python.<module>:<function>'")
    try:
        return clean, resolve_python_entry(entry), None
    except EntryError as exc:
        raise RegistryError(f"lever {label}: {exc}") from exc


def _read_registry_file(path: Path) -> _RegistryFile:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("_note"), str):
            raw = {key: value for key, value in raw.items() if key != "_note"}  # STD-CF-5: a human note
        return _RegistryFile.model_validate(raw)
    except (OSError, ValueError, ValidationError) as exc:
        kind = "lever registry" if path.parent.name != FRAGMENTS_DIRNAME else "lever registry fragment"
        raise RegistryError(f"cannot load {kind} {path}: {exc}") from exc


class Registry:
    """Registered levers and their implementations. A name not in here cannot be invoked."""

    def __init__(
        self,
        levers: list[LeverDef],
        handlers: Mapping[str, Handler] = HANDLERS,
        never: NeverAutomate | None = None,
        powershell: Mapping[str, PowerShellEntry] | None = None,
        bash: Mapping[str, BashEntry] | None = None,
    ) -> None:
        gate = never if never is not None else _default_never_automate()
        by_name: dict[str, LeverDef] = {}
        for lever in levers:
            gate.check(lever.name)
            if lever.name in by_name:
                raise RegistryError(f"lever {lever.name!r} is registered twice")
            if lever.name not in handlers:
                raise RegistryError(f"lever {lever.name!r} has no implementation")
            by_name[lever.name] = lever
        for lever in list(by_name.values()):
            if lever.undo_of is None:
                continue
            owner = by_name.get(lever.undo_of)
            if owner is None or owner.lever_class != "write" or lever.lever_class != "write":
                raise RegistryError(
                    f"lever {lever.name!r} is the undo of {lever.undo_of!r}, which is not a registered write lever"
                )
            if owner.undo not in (None, lever.name):
                raise RegistryError(f"lever {owner.name!r} already names undo {owner.undo!r}, not {lever.name!r}")
            by_name[owner.name] = owner.model_copy(update={"undo": lever.name})
        for lever in by_name.values():
            if lever.undo is None:
                continue
            target = by_name.get(lever.undo)
            if target is None or target.lever_class != "write":
                raise RegistryError(
                    f"lever {lever.name!r} names undo {lever.undo!r}, which is not a registered write lever"
                )
        bindings = dict(powershell or {})
        if set(bindings) - set(by_name):
            raise RegistryError(f"PowerShell entries for unregistered levers: {sorted(set(bindings) - set(by_name))}")
        self._powershell = bindings
        bash_bindings = dict(bash or {})
        if set(bash_bindings) - set(by_name):
            raise RegistryError(f"bash entries for unregistered levers: {sorted(set(bash_bindings) - set(by_name))}")
        for name in bash_bindings:
            problems = check_bash_params(by_name[name].params)
            if problems:
                raise RegistryError(f"lever {name!r}: runtime 'bash' (B66-3): " + "; ".join(problems))
        self._bash = bash_bindings
        self._levers = by_name
        self._handlers = {name: handlers[name] for name in by_name}

    @classmethod
    def load(
        cls,
        path: Path = DEFAULT_REGISTRY_PATH,
        handlers: Mapping[str, Handler] = HANDLERS,
        fragments_dir: Path | None = None,
        never: NeverAutomate | None = None,
        powershell_root: Path = DEFAULT_POWERSHELL_ROOT,
        bash_root: Path = DEFAULT_BASH_ROOT,
    ) -> Registry:
        """Load `path` and every `*.json` in `fragments_dir` (default: `registry.d` beside `path`) as one registry."""
        path = Path(path)
        folder = Path(fragments_dir) if fragments_dir is not None else path.parent / FRAGMENTS_DIRNAME
        files = [path]
        if folder.is_dir():
            files.extend(sorted(item for item in folder.glob("*.json") if item.is_file()))
        gate = never if never is not None else _default_never_automate()

        levers: list[LeverDef] = []
        all_handlers: dict[str, Handler] = dict(handlers)
        powershell: dict[str, PowerShellEntry] = {}
        bash: dict[str, BashEntry] = {}
        powershell_root = Path(powershell_root)
        bash_root = Path(bash_root)
        origin: dict[str, Path] = {}
        for file in files:
            parsed = _read_registry_file(file)
            for index, entry in enumerate(parsed.levers):
                label = _lever_label(entry, index)
                try:
                    name = entry.get("name")
                    if isinstance(name, str):
                        gate.check(name)
                    clean, handler, bound = _split_implementation(entry, label, powershell_root, bash_root)
                    lever = _parse_lever(clean, index)
                    if lever.name in origin:
                        raise RegistryError(
                            f"lever {lever.name!r} is registered twice (in {origin[lever.name].name} and {file.name})"
                        )
                    if handler is not None:
                        if lever.name in handlers:
                            raise RegistryError(
                                f"lever {lever.name!r} has both an entry and a built-in handler; keep one"
                            )
                        all_handlers[lever.name] = handler
                    if isinstance(bound, PowerShellEntry):
                        powershell[lever.name] = bound
                    elif isinstance(bound, BashEntry):
                        problems = check_bash_params(lever.params)
                        if problems:
                            raise RegistryError(f"lever {label}: runtime 'bash' (B66-3): " + "; ".join(problems))
                        bash[lever.name] = bound
                except RegistryError as exc:
                    if file == path:
                        raise
                    raise RegistryError(f"{file.name}: {exc}") from exc
                origin[lever.name] = file
                levers.append(lever)
        return cls(levers, all_handlers, gate, powershell, bash)

    def get(self, name: str) -> LeverDef | None:
        return self._levers.get(name)

    def handler(self, name: str) -> Handler:
        return self._handlers[name]

    def runtime(self, name: str) -> str:
        """`"powershell"` or `"bash"` for a lever that runs through a bridge, else `"python"`."""
        if name in self._bash:
            return "bash"
        return "powershell" if name in self._powershell else "python"

    def powershell_entry(self, name: str) -> PowerShellEntry | None:
        return self._powershell.get(name)

    def bash_entry(self, name: str) -> BashEntry | None:
        return self._bash.get(name)

    def names(self) -> list[str]:
        return sorted(self._levers)

    def __contains__(self, name: object) -> bool:
        return name in self._levers
