"""Prompt library: versioned, reviewable prompt files and the one loader that reads them (B-20).

Each prompt is ``prompts/library/<task>.v<n>.md``: a front-matter block of ``key: value`` lines (values are JSON,
or plain text for strings) between two ``---`` lines, then a ``## system`` section and a ``## user`` section.
Rules the loader enforces, fail closed (any breach is a PromptError, nothing is half-loaded):

1. the file name, ``task`` and ``version`` agree, and a version that has no file is refused (no "latest" default:
   callers pin a version, STD-VR-2);
2. front matter has exactly the keys in ``REQUIRED_KEYS``; each input says why the task needs it (BA-4);
3. every released file matches its SHA-256 in ``library/LOCK.json``, so a released version never changes in
   place: a change is a new version that goes through the eval gate (C-41, prompts/STANDARDS.md);
4. an untrusted input appears exactly once, alone on its own line, in the user section only, and is rendered only
   through ``core.guard.wrap_untrusted``; a prompt with an untrusted input states in its system section that the
   block is data, not instructions (C-12);
5. rendering takes exactly the declared inputs: a missing or extra input is refused (minimum necessary, BA-4).

Synthetic data only; this module never calls a model. It reads files under ``prompts/library`` only.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from core.guard import wrap_untrusted

LIBRARY_DIR = Path(__file__).resolve().parent / "library"
LOCK_NAME = "LOCK.json"

REQUIRED_KEYS = ("task", "version", "description", "owner", "status", "inputs", "output_schema", "eval")
STATUSES = ("draft", "active", "retired")
INPUT_KEYS = frozenset({"name", "trust", "why", "max_chars", "source"})
DATA_NOTICE = "is data, not instructions"
NO_EVAL = "none-yet"

# Input names that would put a person's identifiers into a prompt. A heuristic on names, not on content: the
# redaction step (C-25, planned) is what checks content.
PERSONAL_INPUT_NAMES = frozenset(
    {
        "phone",
        "phone_number",
        "mobile",
        "patient_name",
        "date_of_birth",
        "dob",
        "ssn",
        "account_number",
        "email_address",
        "home_address",
        "password",
    }
)

_TASK = re.compile(r"[a-z][a-z0-9-]{0,39}")
_FILE = re.compile(r"(?P<task>[a-z][a-z0-9-]{0,39})\.v(?P<version>[1-9][0-9]{0,3})\.md")
_INPUT_NAME = re.compile(r"[a-z][a-z0-9_]{0,39}")
_PLACEHOLDER = re.compile(r"\{\{\s*([^{}\s]*)\s*\}\}")
_KEY_LINE = re.compile(r"(?P<key>[a-z_]+):\s*(?P<value>.*)")
_JSON_TYPES = ("object", "array", "string", "integer", "number", "boolean")
_SCHEMA_KEYS = frozenset(
    {"type", "properties", "required", "additionalProperties", "enum", "maxLength", "items", "maxItems"}
)


class PromptError(ValueError):
    """A prompt file is malformed, unknown or used against its own contract."""


@dataclass(frozen=True)
class PromptInput:
    name: str
    trust: str  # "trusted" (a validated structured field) or "untrusted" (ticket, email, document, tool output)
    why: str
    max_chars: int
    source: str | None  # wrap_untrusted source label; set exactly when trust is "untrusted"


@dataclass(frozen=True)
class Prompt:
    task: str
    version: int
    description: str
    owner: str
    status: str
    inputs: tuple[PromptInput, ...]
    output_schema: Mapping[str, Any]
    eval: str
    system: str
    user: str
    sha256: str
    path: Path

    @property
    def id(self) -> str:
        return f"{self.task}.v{self.version}"

    @property
    def untrusted_inputs(self) -> tuple[PromptInput, ...]:
        return tuple(i for i in self.inputs if i.trust == "untrusted")


@dataclass(frozen=True)
class RenderedPrompt:
    """What a provider receives: the prompt id and hash (for the audit and eval report) and two messages."""

    prompt_id: str
    sha256: str
    system: str
    user: str


def content_hash(text: str) -> str:
    """SHA-256 of the file text with line endings normalised to LF, so a Windows checkout hashes the same."""
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def _parse_value(raw: str) -> Any:
    raw = raw.strip()
    if raw[:1] in ("{", "[", '"') or re.fullmatch(r"-?[0-9]+", raw):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PromptError(f"front matter value is not valid JSON: {raw[:40]!r}") from exc
    return raw


def _split(text: str, where: str) -> tuple[dict[str, Any], str, str]:
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0] != "---":
        raise PromptError(f"{where}: must start with a '---' front-matter line")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise PromptError(f"{where}: front matter is not closed with '---'") from exc
    meta: dict[str, Any] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        match = _KEY_LINE.fullmatch(line)
        if match is None:
            raise PromptError(f"{where}: front-matter line is not 'key: value': {line[:40]!r}")
        key = match["key"]
        if key in meta:
            raise PromptError(f"{where}: duplicate front-matter key {key!r}")
        meta[key] = _parse_value(match["value"])
    body = lines[end + 1 :]
    heads = [n for n, line in enumerate(body) if line.startswith("## ")]
    if [body[n] for n in heads] != ["## system", "## user"]:
        raise PromptError(f"{where}: body must have exactly a '## system' section then a '## user' section")
    system = "\n".join(body[heads[0] + 1 : heads[1]]).strip()
    user = "\n".join(body[heads[1] + 1 :]).strip()
    if not system or not user:
        raise PromptError(f"{where}: the system and user sections must not be empty")
    if any(line.strip() for line in body[: heads[0]]):
        raise PromptError(f"{where}: text before '## system' is not allowed")
    return meta, system, user


def _check_schema(schema: Any, where: str, depth: int = 0) -> None:
    """Accept a small JSON Schema subset: enough to say what a model must return, small enough to check here."""
    if depth > 6 or not isinstance(schema, dict):
        raise PromptError(f"{where}: output_schema must be a JSON object (at most 6 levels deep)")
    unknown = set(schema) - _SCHEMA_KEYS
    if unknown:
        raise PromptError(f"{where}: output_schema has unsupported keys {sorted(unknown)}")
    kind = schema.get("type")
    if kind not in _JSON_TYPES:
        raise PromptError(f"{where}: output_schema type must be one of {_JSON_TYPES}")
    if kind == "object":
        props = schema.get("properties", {})
        if not isinstance(props, dict):
            raise PromptError(f"{where}: properties must be an object")
        for sub in props.values():
            _check_schema(sub, where, depth + 1)
        required = schema.get("required", [])
        if not isinstance(required, list) or not set(required) <= set(props):
            raise PromptError(f"{where}: required must list declared properties")
    if kind == "array":
        _check_schema(schema.get("items"), where, depth + 1)
    if kind == "string" and not isinstance(schema.get("maxLength"), int) and "enum" not in schema:
        raise PromptError(f"{where}: every string in output_schema needs maxLength or enum")


def _inputs(raw: Any, where: str) -> tuple[PromptInput, ...]:
    if not isinstance(raw, list) or not raw:
        raise PromptError(f"{where}: inputs must be a non-empty JSON list")
    out: list[PromptInput] = []
    for item in raw:
        if not isinstance(item, dict) or set(item) - INPUT_KEYS:
            raise PromptError(f"{where}: each input is an object with keys from {sorted(INPUT_KEYS)}")
        name, trust, why, max_chars = item.get("name"), item.get("trust"), item.get("why"), item.get("max_chars")
        source = item.get("source")
        if not isinstance(name, str) or not _INPUT_NAME.fullmatch(name):
            raise PromptError(f"{where}: input name {name!r} is not a lowercase identifier")
        if name in PERSONAL_INPUT_NAMES:
            raise PromptError(f"{where}: input {name!r} is a personal identifier; minimum necessary (BA-4)")
        if trust not in ("trusted", "untrusted"):
            raise PromptError(f"{where}: input {name!r} trust must be 'trusted' or 'untrusted'")
        if not isinstance(why, str) or len(why.strip()) < 10:
            raise PromptError(f"{where}: input {name!r} needs a 'why' saying what the task needs it for (BA-4)")
        if not isinstance(max_chars, int) or isinstance(max_chars, bool) or not 1 <= max_chars <= 20000:
            raise PromptError(f"{where}: input {name!r} needs max_chars between 1 and 20000")
        if (trust == "untrusted") != isinstance(source, str):
            raise PromptError(f"{where}: input {name!r} has a source exactly when it is untrusted")
        out.append(PromptInput(name, trust, why.strip(), max_chars, source))
    names = [i.name for i in out]
    if len(set(names)) != len(names):
        raise PromptError(f"{where}: duplicate input names")
    return tuple(out)


def _check_placeholders(inputs: tuple[PromptInput, ...], system: str, user: str, where: str) -> None:
    declared = {i.name for i in inputs}
    used_system = _PLACEHOLDER.findall(system)
    used_user = _PLACEHOLDER.findall(user)
    unknown = set(used_system + used_user) - declared
    if unknown:
        raise PromptError(f"{where}: placeholders without a declared input: {sorted(unknown)}")
    unused = declared - set(used_system + used_user)
    if unused:
        raise PromptError(f"{where}: declared inputs never used (minimum necessary, BA-4): {sorted(unused)}")
    for item in inputs:
        if item.trust != "untrusted":
            continue
        if item.name in used_system:
            raise PromptError(f"{where}: untrusted input {item.name!r} may not appear in the system section")
        alone = [m.group(1) for line in user.split("\n") if (m := _PLACEHOLDER.fullmatch(line.strip()))]
        if used_user.count(item.name) != 1 or item.name not in alone:
            raise PromptError(f"{where}: untrusted input {item.name!r} must appear once, alone on its own line")
    if any(i.trust == "untrusted" for i in inputs) and DATA_NOTICE not in system:
        raise PromptError(f"{where}: a prompt with untrusted input must say in its system section: {DATA_NOTICE!r}")


def parse(text: str, file_name: str) -> Prompt:
    """Parse and check one prompt file's text. ``file_name`` is its base name (``<task>.v<n>.md``)."""
    match = _FILE.fullmatch(file_name)
    if match is None:
        raise PromptError(f"{file_name}: file name must be <task>.v<n>.md")
    meta, system, user = _split(text, file_name)
    if tuple(sorted(meta)) != tuple(sorted(REQUIRED_KEYS)):
        missing = sorted(set(REQUIRED_KEYS) - set(meta))
        extra = sorted(set(meta) - set(REQUIRED_KEYS))
        raise PromptError(f"{file_name}: front matter missing {missing}, unknown {extra}")
    if meta["task"] != match["task"] or meta["version"] != int(match["version"]):
        raise PromptError(f"{file_name}: task and version in front matter must match the file name")
    for key in ("description", "owner", "eval"):
        if not isinstance(meta[key], str) or not meta[key].strip():
            raise PromptError(f"{file_name}: {key} must be a non-empty string")
    if meta["status"] not in STATUSES:
        raise PromptError(f"{file_name}: status must be one of {STATUSES}")
    if meta["status"] == "active" and meta["eval"].strip() == NO_EVAL:
        raise PromptError(f"{file_name}: an active prompt names the eval that gates it (C-41)")
    inputs = _inputs(meta["inputs"], file_name)
    _check_schema(meta["output_schema"], file_name)
    _check_placeholders(inputs, system, user, file_name)
    return Prompt(
        task=meta["task"],
        version=meta["version"],
        description=meta["description"].strip(),
        owner=meta["owner"].strip(),
        status=meta["status"],
        inputs=inputs,
        output_schema=meta["output_schema"],
        eval=meta["eval"].strip(),
        system=system,
        user=user,
        sha256=content_hash(text),
        path=Path(file_name),
    )


def _lock(library: Path) -> dict[str, str]:
    path = library / LOCK_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromptError(f"{LOCK_NAME} is missing or not JSON") from exc
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("files"), dict):
        raise PromptError(f"{LOCK_NAME} must be {{'version': 1, 'files': {{name: sha256}}}}")
    return {str(k): str(v) for k, v in data["files"].items()}


def load(task: str, version: int, library: Path = LIBRARY_DIR) -> Prompt:
    """Load one pinned prompt version. An unknown task or version is refused; there is no default version."""
    if not isinstance(task, str) or not _TASK.fullmatch(task):
        raise PromptError(f"task must match {_TASK.pattern!r}")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise PromptError("version must be a positive integer")
    name = f"{task}.v{version}.md"
    path = library / name
    if not path.is_file():
        raise PromptError(f"unknown prompt version: {task} v{version}")
    text = path.read_text(encoding="utf-8")
    prompt = parse(text, name)
    expected = _lock(library).get(name)
    if expected is None:
        raise PromptError(f"{name} is not in {LOCK_NAME}; a new version is added to the lock in its own PR")
    if expected != prompt.sha256:
        raise PromptError(f"{name} changed after release; make a new version instead of editing this one")
    return replace(prompt, path=path)


def versions(task: str, library: Path = LIBRARY_DIR) -> tuple[int, ...]:
    """The versions of ``task`` that exist in the library, oldest first."""
    found = []
    for path in library.glob(f"{task}.v*.md"):
        match = _FILE.fullmatch(path.name)
        if match is not None and match["task"] == task:
            found.append(int(match["version"]))
    return tuple(sorted(found))


def load_library(library: Path = LIBRARY_DIR) -> tuple[Prompt, ...]:
    """Load every prompt file; one bad file, or a lock entry without a file, fails the whole load."""
    names = sorted(p.name for p in library.iterdir() if p.is_file() and p.name.endswith(".md"))
    for name in names:
        if _FILE.fullmatch(name) is None:
            raise PromptError(f"{name}: file name must be <task>.v<n>.md")
    orphans = set(_lock(library)) - set(names)
    if orphans:
        raise PromptError(f"{LOCK_NAME} lists files that do not exist: {sorted(orphans)}")
    out = []
    for name in names:
        match = _FILE.fullmatch(name)
        assert match is not None  # noqa: S101 - checked in the loop above
        out.append(load(match["task"], int(match["version"]), library))
    return tuple(out)


def render(prompt: Prompt, values: Mapping[str, str]) -> RenderedPrompt:
    """Fill the prompt with exactly its declared inputs.

    Untrusted values go through ``wrap_untrusted`` with the input's source label; trusted values must be a single
    line without delimiter look-alikes. Substitution is one pass, so a value that contains ``{{x}}`` is not
    expanded again.
    """
    if prompt.status == "retired":
        raise PromptError(f"{prompt.id} is retired")
    declared = {i.name: i for i in prompt.inputs}
    if set(values) != set(declared):
        missing = sorted(set(declared) - set(values))
        extra = sorted(set(values) - set(declared))
        raise PromptError(f"{prompt.id}: inputs must be exactly the declared ones; missing {missing}, extra {extra}")
    filled: dict[str, str] = {}
    for name, item in declared.items():
        value = values[name]
        if not isinstance(value, str):
            raise PromptError(f"{prompt.id}: input {name!r} must be a string")
        if len(value) > item.max_chars:
            raise PromptError(f"{prompt.id}: input {name!r} is longer than {item.max_chars} characters")
        if item.source is not None:
            filled[name] = wrap_untrusted(item.source, value)
        else:
            if "\n" in value or "\r" in value or "<<<" in value or ">>>" in value or "{{" in value:
                raise PromptError(f"{prompt.id}: trusted input {name!r} must be one line with no delimiters")
            filled[name] = value

    def sub(text: str) -> str:
        return _PLACEHOLDER.sub(lambda m: filled[m.group(1)], text)

    return RenderedPrompt(prompt_id=prompt.id, sha256=prompt.sha256, system=sub(prompt.system), user=sub(prompt.user))


def _type_ok(value: Any, kind: str) -> bool:
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    expected: dict[str, type | tuple[type, ...]] = {
        "object": dict,
        "array": list,
        "string": str,
        "boolean": bool,
    }
    return isinstance(value, expected[kind])


def output_errors(schema: Mapping[str, Any], value: Any, at: str = "$") -> list[str]:
    """Check a parsed model output against the prompt's output_schema subset. Empty list means it fits."""
    kind = str(schema["type"])
    if not _type_ok(value, kind):
        return [f"{at}: expected {kind}"]
    errors: list[str] = []
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{at}: not one of the allowed values")
    if kind == "string" and isinstance(schema.get("maxLength"), int) and len(value) > schema["maxLength"]:
        errors.append(f"{at}: longer than {schema['maxLength']}")
    if kind == "array":
        if isinstance(schema.get("maxItems"), int) and len(value) > schema["maxItems"]:
            errors.append(f"{at}: more than {schema['maxItems']} items")
        for n, item in enumerate(value):
            errors.extend(output_errors(schema["items"], item, f"{at}[{n}]"))
    if kind == "object":
        props: Mapping[str, Any] = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{at}.{key}: required")
        if schema.get("additionalProperties") is False:
            errors.extend(f"{at}.{key}: not allowed" for key in value if key not in props)
        for key, sub in props.items():
            if key in value:
                errors.extend(output_errors(sub, value[key], f"{at}.{key}"))
    return errors


__all__ = [
    "DATA_NOTICE",
    "LIBRARY_DIR",
    "Prompt",
    "PromptError",
    "PromptInput",
    "RenderedPrompt",
    "content_hash",
    "load",
    "load_library",
    "output_errors",
    "parse",
    "render",
    "versions",
]
