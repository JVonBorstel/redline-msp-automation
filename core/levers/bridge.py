"""The Python side of "Python orchestrates, PowerShell acts" (B-16, ARC-04, STD-LV-11).

The lever runner has already checked the registry, params, role, client scope, approval, pause and requester
verification before it calls here. The bridge only does the last step for a lever with `runtime: "powershell"`:

  - builds one `lever-request` document (schemas/lever-request.schema.json) and writes it to the stdin of
    `pwsh -NoProfile -NonInteractive -File levers/powershell/LeverHost/Invoke-LeverRequest.ps1`;
  - reads exactly one `lever-result` line from stdout (the host's subset of schemas/lever-result.schema.json) and
    checks it against what was asked: same lever, client and mode, and an exit code that agrees with the status;
  - kills the child process at `timeout_s` (SL-06) and reports `error` with nothing reported as applied.

It never raises to its caller for a missing `pwsh`, a crash, a timeout or a bad answer: each is a `BridgeResult`
with `status` `error` (STD-ER-1, STD-ER-5). The child gets a scrubbed environment (no secrets, no tokens) plus the
one folder the offline mock needs. No network, no credentials, synthetic data only.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr, ValidationError

from core.levers.models import Change, ParamSpec
from core.paths import REPO_ROOT

DEFAULT_POWERSHELL_ROOT = REPO_ROOT / "levers" / "powershell"
HOST_SCRIPT = DEFAULT_POWERSHELL_ROOT / "LeverHost" / "Invoke-LeverRequest.ps1"
REQUEST_VERSION = 1
# The offline mock reads its tenant files from here when it is set (see levers/powershell/Sample).
TENANT_DIR_ENV = "REDLINE_MOCK_TENANT_DIR"
MAX_OUTPUT_BYTES = 1_000_000
MAX_REASON = 300

# Mirrors schemas/lever-request.schema.json (a test keeps them in step).
MODULE_RE = re.compile(r"^[A-Z][A-Za-z0-9]{1,63}$")
FUNCTION_RE = re.compile(r"^[A-Z][a-z]+-[A-Z][A-Za-z0-9]{1,63}$")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,63}$")
_ENTRY_RE = re.compile(r"^([A-Z][A-Za-z0-9]{1,63})\\([A-Z][a-z]+-[A-Z][A-Za-z0-9]{1,63})$")

# What the child may inherit: enough for pwsh to start on Windows or Linux, nothing that holds a secret.
_ENV_ALLOWED = (
    "PATH",
    "SystemRoot",
    "SystemDrive",
    "windir",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "LOCALAPPDATA",
    "APPDATA",
    "ProgramFiles",
    "ProgramData",
    "COMPUTERNAME",
    "LANG",
    "LC_ALL",
    "REDLINE_OOB_DIR",
)
_ENV_FIXED = {"POWERSHELL_TELEMETRY_OPTOUT": "1", "POWERSHELL_UPDATECHECK": "Off", "DOTNET_NOLOGO": "1"}

Mode = Literal["dry-run", "execute"]
Status = Literal["ok", "denied", "error"]


class EntryFormatError(ValueError):
    """A registry `entry` for a PowerShell lever is not `<Module>\\<Verb-Noun>`."""


@dataclass(frozen=True, slots=True)
class PowerShellEntry:
    """Where a PowerShell lever lives: `levers/powershell/<module>/`, exported function `function`."""

    module: str
    function: str

    def __str__(self) -> str:
        return f"{self.module}\\{self.function}"


def parse_entry(text: object) -> PowerShellEntry:
    """`Module\\Verb-Noun` to a PowerShellEntry; anything else raises EntryFormatError (no path can be named)."""
    match = _ENTRY_RE.match(text) if isinstance(text, str) else None
    if match is None:
        raise EntryFormatError(
            f"entry {text!r} must look like 'Module\\Verb-Noun' (for example 'Sample\\Get-SampleUser')"
        )
    return PowerShellEntry(module=match.group(1), function=match.group(2))


class BridgeResult(BaseModel):
    """What the host said (lever-result minus identity, approver and audit_seq, which only Python knows)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Status
    reason: StrictStr = ""
    lever: StrictStr
    client: StrictStr
    mode: StrictStr
    data: Any = None
    diff: tuple[Change, ...] = ()
    applied: StrictBool = False

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _short(text: str) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= MAX_REASON else one_line[: MAX_REASON - 1] + "…"


class PowerShellBridge:
    """Runs one lever call in a child `pwsh`. Safe to share; each call is its own process."""

    def __init__(
        self,
        *,
        pwsh: str | None = None,
        host_script: Path = HOST_SCRIPT,
        modules_root: Path = DEFAULT_POWERSHELL_ROOT,
        tenant_dir: Path | None = None,
    ) -> None:
        self._pwsh = pwsh
        self.host_script = Path(host_script)
        self.modules_root = Path(modules_root)
        self.tenant_dir = None if tenant_dir is None else Path(tenant_dir)

    def pwsh_path(self) -> str | None:
        return self._pwsh or shutil.which("pwsh")

    def call(
        self,
        *,
        lever: str,
        lever_version: int,
        client: str,
        mode: Mode,
        params: Mapping[str, Any],
        entry: PowerShellEntry,
        timeout_s: float,
        request_id: str,
        as_of: str | None = None,
    ) -> BridgeResult:
        def fail(status: Status, reason: str) -> BridgeResult:
            return BridgeResult(status=status, reason=_short(reason), lever=lever, client=client, mode=mode)

        if not (MODULE_RE.match(entry.module) and FUNCTION_RE.match(entry.function)):
            return fail("error", "the lever entry is not a valid module and function; nothing ran")
        if not REQUEST_ID_RE.match(request_id):
            return fail("error", "the request id is not valid; nothing ran")
        pwsh = self.pwsh_path()
        if pwsh is None:
            return fail("error", "pwsh (PowerShell 7.4 or newer) is not installed; nothing ran")
        if not self.host_script.is_file():
            return fail("error", "the PowerShell lever host script is missing; nothing ran")

        request: dict[str, Any] = {
            "version": REQUEST_VERSION,
            "request_id": request_id,
            "lever": lever,
            "lever_version": lever_version,
            "client": client,
            "mode": mode,
            "params": dict(params),
            "entry": {"module": entry.module, "function": entry.function},
        }
        if as_of is not None:
            request["as_of"] = as_of
        try:
            payload = json.dumps(request, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError):
            return fail("error", "the request could not be written as JSON; nothing ran")

        argv = [
            pwsh,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(self.host_script),
            "-ModulesRoot",
            str(self.modules_root),
            "-TimeoutSeconds",
            str(max(1, math.ceil(timeout_s))),
        ]
        try:
            process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell; every value was validated above
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._child_env(),
                cwd=str(REPO_ROOT),
            )
        except OSError as exc:
            return fail("error", f"{lever} could not start pwsh ({type(exc).__name__}); nothing ran")
        try:
            stdout, _stderr = process.communicate(payload, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.communicate(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                pass
            return fail(
                "error",
                f"{lever} timed out after {timeout_s:g}s; the pwsh process was killed; nothing was reported as applied",
            )
        except OSError as exc:
            process.kill()
            return fail(
                "error", f"{lever} lost its pwsh process ({type(exc).__name__}); nothing was reported as applied"
            )
        return self._read_result(stdout, process.returncode, lever, client, mode)

    def _child_env(self) -> dict[str, str]:
        env = {key: os.environ[key] for key in _ENV_ALLOWED if key in os.environ}
        env.update(_ENV_FIXED)
        if self.tenant_dir is not None:
            env[TENANT_DIR_ENV] = str(self.tenant_dir)
        return env

    @staticmethod
    def _read_result(stdout: bytes, code: int, lever: str, client: str, mode: Mode) -> BridgeResult:
        def fail(reason: str) -> BridgeResult:
            return BridgeResult(status="error", reason=_short(reason), lever=lever, client=client, mode=mode)

        if len(stdout) > MAX_OUTPUT_BYTES:
            return fail(f"{lever} answered with more than {MAX_OUTPUT_BYTES} bytes; the answer was discarded")
        lines = [line for line in stdout.decode("utf-8", errors="replace").splitlines() if line.strip()]
        if len(lines) != 1:
            return fail(
                f"{lever}: the host must print exactly one JSON result line (exit code {code}); answer discarded"
            )
        try:
            result = BridgeResult.model_validate(json.loads(lines[0]))
        except (ValueError, ValidationError):
            return fail(
                f"{lever}: the host's answer is not a lever result (exit code {code}); the answer was discarded"
            )
        if (result.lever, result.client, result.mode) != (lever, client, mode) and result.status == "ok":
            return fail(f"{lever}: the host answered for a different lever, client or mode; the answer was discarded")
        expected = {0: ("ok",), 1: ("denied", "error")}.get(code, ("error",))
        if result.status not in expected:
            return fail(
                f"{lever}: exit code {code} does not agree with status {result.status!r}; the answer was discarded"
            )
        if result.mode == "dry-run" and result.applied:
            return fail(f"{lever} reported a change as applied during a dry-run; the answer was discarded")
        reason = _short(result.reason)
        return result.model_copy(update={"reason": reason, "lever": lever, "client": client, "mode": mode})


# -- B-66: the bash runtime (macOS and Linux levers) --------------------------------------------------------------
#
# "Python orchestrates, bash acts", with the same guarantees as the PowerShell bridge above:
#   - the runner has already decided; the bridge only starts one vetted script, `bash --noprofile --norc <script>`,
#     with no shell in between and no command or path taken from the request;
#   - the script is named in the registry by a bare file name, listed in `levers/bash/manifest.json` with its SHA-256,
#     and the exact bytes that were hashed are the bytes that run (they are copied into a private folder first);
#   - the child gets a scrubbed environment, a hard timeout, one JSON request line on stdin and nothing on argv except
#     `--what-if` for a dry-run;
#   - parameters are data: only a narrow character set reaches the child, so no quote, `$`, backtick, newline or
#     backslash can ever be present for a script to mishandle. The scripts also check them against an allowlist.
# One JSON result line comes back and is checked exactly like the PowerShell host's (same BridgeResult).

DEFAULT_BASH_ROOT = REPO_ROOT / "levers" / "bash"
MANIFEST_NAME = "manifest.json"
MOCK_DIR_ENV = "REDLINE_UNIX_MOCK_DIR"

# Applied with fullmatch only.
BASH_SCRIPT_RE = re.compile(r"[a-z][a-z0-9-]{1,48}\.sh")
BASH_LIB_RE = re.compile(r"[a-z][a-z0-9-]{1,48}\.sh")
SAFE_PARAM_RE = re.compile(r"[A-Za-z0-9._:@+-]{0,64}")
_LEVER_NAME_RE = re.compile(r"[a-z][a-z0-9]*(\.[a-z][a-z0-9-]*)+")
_CLIENT_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
_PARAM_NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_AS_OF_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9]{2}:[0-9]{2}:[0-9]{2}Z)?")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")

# Parameter names that would let a caller choose what runs or where (B66-3).
FREE_FORM_PARAM_NAMES = frozenset(
    {
        "command",
        "cmd",
        "shell",
        "script",
        "exec",
        "eval",
        "args",
        "argv",
        "arguments",
        "code",
        "run",
        "bash",
        "sh",
        "line",
        "expression",
        "options",
        "flags",
        "path",
        "file",
        "filename",
        "dir",
        "directory",
    }
)
_PROBE_CHARS = ";&|$`()<>\\\"'\n\r\t *?{}[]~!#%^=,\x00\u00fc"
_MAX_STRING_PARAM = 64


class ManifestError(ValueError):
    """`levers/bash/manifest.json` is missing, malformed, or does not match the files it pins."""


@dataclass(frozen=True, slots=True)
class BashEntry:
    """Where a bash lever lives: `levers/bash/scripts/<script>`, a bare file name listed in the manifest."""

    script: str

    def __str__(self) -> str:
        return self.script


def parse_bash_entry(text: object) -> BashEntry:
    """`name.sh` to a BashEntry; anything else (a path, a flag, a command) raises EntryFormatError."""
    if not isinstance(text, str) or BASH_SCRIPT_RE.fullmatch(text) is None:
        raise EntryFormatError(
            f"entry {text!r} must be a bare script file name like 'clear-cache.sh' (lowercase, digits, '-', '.sh')"
        )
    return BashEntry(script=text)


class BashManifest(BaseModel):
    """The allowlist: every script that may run, and every library it may source, with the SHA-256 of its bytes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1]
    scripts: dict[str, str]
    libs: dict[str, str]


def load_manifest(bash_root: Path = DEFAULT_BASH_ROOT) -> BashManifest:
    path = Path(bash_root) / MANIFEST_NAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("_note"), str):
            raw = {key: value for key, value in raw.items() if key != "_note"}
        manifest = BashManifest.model_validate(raw)
    except (OSError, ValueError, ValidationError) as exc:
        raise ManifestError(f"cannot load the bash manifest {path}: {type(exc).__name__}") from exc
    for names, pattern, kind in ((manifest.scripts, BASH_SCRIPT_RE, "script"), (manifest.libs, BASH_LIB_RE, "lib")):
        for name, digest in names.items():
            if pattern.fullmatch(name) is None or _SHA256_RE.fullmatch(digest) is None:
                raise ManifestError(f"the bash manifest {path} has a bad {kind} entry {name!r}")
    return manifest


def read_pinned(bash_root: Path, manifest: BashManifest, script: str) -> dict[str, bytes]:
    """The bytes of `script` and each lib, checked against their pinned hashes (keys `scripts/x.sh`, `lib/y.sh`)."""
    if script not in manifest.scripts:
        raise ManifestError(f"{script} is not in the manifest")
    wanted = [(f"scripts/{script}", manifest.scripts[script])]
    wanted.extend((f"lib/{name}", digest) for name, digest in sorted(manifest.libs.items()))
    found: dict[str, bytes] = {}
    for relative, digest in wanted:
        path = Path(bash_root) / relative
        try:
            if path.is_symlink() or not path.is_file():
                raise ManifestError(f"{relative} is missing or is not a plain file")
            data = path.read_bytes()
        except OSError as exc:
            raise ManifestError(f"{relative} cannot be read ({type(exc).__name__})") from exc
        if hashlib.sha256(data).hexdigest() != digest:
            raise ManifestError(f"{relative} does not match its pinned sha256")
        found[relative] = data
    return found


def check_bash_params(params: Mapping[str, ParamSpec]) -> list[str]:
    """Problems that would let a bash lever take a free-form value (B66-3). Empty means the parameters are tight."""
    problems: list[str] = []
    for name, spec in params.items():
        if name in FREE_FORM_PARAM_NAMES:
            problems.append(f"param '{name}': a bash lever takes no free-form command, script, path or argument")
            continue
        if spec.type != "string":
            continue
        if spec.enum is not None:
            for value in spec.enum:
                if str(value) == "" or SAFE_PARAM_RE.fullmatch(str(value)) is None:
                    problems.append(f"param '{name}': enum value {value!r} is outside the safe character set")
            continue
        if spec.pattern is None or spec.max_length is None or spec.max_length > _MAX_STRING_PARAM:
            problems.append(
                f"param '{name}': a string parameter of a bash lever needs an enum, or a pattern and a max_length "
                f"of at most {_MAX_STRING_PARAM}"
            )
            continue
        for char in _PROBE_CHARS:
            if any(re.fullmatch(spec.pattern, probe) for probe in (char, f"a{char}a", f"a{char}", f"{char}a")):
                problems.append(f"param '{name}': the pattern admits {char!r}, which a bash lever must never receive")
                break
    return problems


def is_wsl_launcher(path: str) -> bool:
    """`C:\\Windows\\System32\\bash.exe` starts WSL, a different machine view; it is never accepted as the bash."""
    lowered = path.replace("\\", "/").lower()
    return lowered.endswith(("/windows/system32/bash.exe", "/windows/syswow64/bash.exe", "/windowsapps/bash.exe"))


_WINDOWS_ENV_ALLOWED = ("PATH", "SystemRoot", "SystemDrive", "windir", "TEMP", "TMP", "COMSPEC", "PATHEXT")


class BashBridge:
    """Runs one lever call in a child `bash`. Safe to share; each call is its own process in its own private folder."""

    def __init__(
        self,
        *,
        bash: str | None = None,
        bash_root: Path = DEFAULT_BASH_ROOT,
        mock_dir: Path | None = None,
    ) -> None:
        self._bash = bash
        self.bash_root = Path(bash_root)
        self.mock_dir = Path(mock_dir) if mock_dir is not None else self.bash_root / "mock"

    def bash_path(self) -> str | None:
        if self._bash is not None:
            return self._bash
        found = shutil.which("bash")
        if found is not None and not is_wsl_launcher(found):
            return found
        if os.name == "nt":
            for var in ("ProgramFiles", "ProgramW6432"):
                base = os.environ.get(var)
                if base:
                    candidate = Path(base) / "Git" / "usr" / "bin" / "bash.exe"
                    if candidate.is_file():
                        return str(candidate)
        return None

    def child_env(self) -> dict[str, str]:
        """What the child may see: a fixed PATH and locale, the mock folder, nothing else (no secret can pass)."""
        env: dict[str, str] = {"LANG": "C", "LC_ALL": "C", MOCK_DIR_ENV: self.mock_dir.as_posix()}
        if os.name == "nt":
            for key in _WINDOWS_ENV_ALLOWED:
                if key in os.environ:
                    env[key] = os.environ[key]
        else:
            env["PATH"] = "/usr/bin:/bin"
        return env

    def call(
        self,
        *,
        lever: str,
        lever_version: int,
        client: str,
        mode: Mode,
        params: Mapping[str, Any],
        entry: BashEntry,
        timeout_s: float,
        request_id: str,
        as_of: str | None = None,
    ) -> BridgeResult:
        def fail(reason: str) -> BridgeResult:
            return BridgeResult(status="error", reason=_short(reason), lever=lever, client=client, mode=mode)

        refusal = self._refuse_request(lever, lever_version, client, mode, params, entry, timeout_s, request_id, as_of)
        if refusal is not None:
            return fail(f"{refusal}; nothing ran")
        try:
            manifest = load_manifest(self.bash_root)
            pinned = read_pinned(self.bash_root, manifest, entry.script)
        except ManifestError as exc:
            return fail(f"the bash script is not vetted: {exc}; nothing ran")
        bash = self.bash_path()
        if bash is None:
            return fail("bash is not installed or not usable here; nothing ran")

        request: dict[str, Any] = {
            "version": REQUEST_VERSION,
            "request_id": request_id,
            "lever": lever,
            "lever_version": lever_version,
            "client": client,
            "mode": mode,
        }
        if as_of is not None:
            request["as_of"] = as_of
        request["params"] = dict(params)
        payload = (json.dumps(request, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")

        with tempfile.TemporaryDirectory(prefix="lever-", ignore_cleanup_errors=True) as stage_name:
            stage = Path(stage_name)
            for relative, data in pinned.items():
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            argv = [bash, "--noprofile", "--norc", (stage / "scripts" / entry.script).as_posix()]
            if mode == "dry-run":
                argv.append("--what-if")
            return self._run(argv, payload, stage, lever, client, mode, timeout_s)

    def _run(
        self, argv: list[str], payload: bytes, stage: Path, lever: str, client: str, mode: Mode, timeout_s: float
    ) -> BridgeResult:
        def fail(reason: str) -> BridgeResult:
            return BridgeResult(status="error", reason=_short(reason), lever=lever, client=client, mode=mode)

        try:
            process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell; every value was validated above
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.child_env(),
                cwd=str(stage),
                start_new_session=sys.platform != "win32",
            )
        except OSError as exc:
            return fail(f"{lever} could not start bash ({type(exc).__name__}); nothing ran")
        try:
            stdout, _stderr = process.communicate(payload, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            self._kill(process)
            return fail(
                f"{lever} timed out after {timeout_s:g}s; the bash process was killed; nothing was reported as applied"
            )
        except OSError as exc:
            self._kill(process)
            return fail(f"{lever} lost its bash process ({type(exc).__name__}); nothing was reported as applied")
        return PowerShellBridge._read_result(stdout, process.returncode, lever, client, mode)

    @staticmethod
    def _kill(process: subprocess.Popen[bytes]) -> None:
        try:
            if sys.platform != "win32":
                os.killpg(process.pid, signal.SIGKILL)  # the whole group: a script's own children die with it
            else:
                process.kill()
        except OSError:
            pass
        try:
            process.communicate(timeout=5)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass

    @staticmethod
    def _refuse_request(
        lever: str,
        lever_version: int,
        client: str,
        mode: str,
        params: Mapping[str, Any],
        entry: BashEntry,
        timeout_s: float,
        request_id: str,
        as_of: str | None,
    ) -> str | None:
        """Why this request may not even reach bash, or None. Every value that will be written is checked here."""
        if BASH_SCRIPT_RE.fullmatch(entry.script) is None:
            return "the lever entry is not a bare script file name"
        if not isinstance(lever, str) or len(lever) > 64 or _LEVER_NAME_RE.fullmatch(lever) is None:
            return "the lever name is not valid"
        if type(lever_version) is not int or lever_version < 1:
            return "the lever version is not valid"
        if not isinstance(client, str) or _CLIENT_RE.fullmatch(client) is None:
            return "the client id is not a plain slug"
        if mode not in ("dry-run", "execute"):
            return "the mode is not dry-run or execute"
        if not isinstance(request_id, str) or REQUEST_ID_RE.fullmatch(request_id) is None:
            return "the request id is not valid"
        if as_of is not None and (not isinstance(as_of, str) or _AS_OF_RE.fullmatch(as_of) is None):
            return "as_of is not a date"
        if isinstance(timeout_s, bool) or not 0 < timeout_s <= 600:
            return "the timeout is not valid"
        for name, value in params.items():
            if not isinstance(name, str) or _PARAM_NAME_RE.fullmatch(name) is None:
                return "a parameter name is not valid"
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                if abs(value) > 10**9:
                    return f"parameter {name} is out of range"
                continue
            if not isinstance(value, str) or SAFE_PARAM_RE.fullmatch(value) is None:
                return (
                    f"parameter {name} has a character a bash lever never receives, or is not text, a number or a flag"
                )
        return None
