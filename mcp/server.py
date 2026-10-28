"""MCP server over the registered levers (B-87): JSON-RPC 2.0 over stdio, standard library only.

This module is a thin door. It lists levers as tools and turns a tool call into ONE call to `LeverRunner.invoke`
in `dry-run` mode, as the caller's identity. It decides nothing about permission: role, client scope, lever scope,
pauses, parameter validation and the audit record all belong to the runner (docs/BLUEPRINT.md section 3).
What the server adds is only what a door must do:

- expose only what is registered, never a never-automate lever, and write levers only when asked and only as
  proposals (the mode is the constant "dry-run"; no argument, header or token can change it, and no approval is
  ever passed);
- build each tool's input schema from the lever's own parameter schema, and refuse arguments of any other shape;
- take the caller from the server's start-up (a fixed identity, or an Entra ID token whose audience, issuer, tenant
  and expiry are checked on every call); never from the arguments;
- keep the token out of the runner, the audit, the results and the logs;
- hand lever output back as labelled untrusted data and flag instruction-like text (core.guard), never act on it.

Every refusal the server makes itself (bad token, a name that is not an exposed tool, arguments of the wrong shape)
is written to the audit chain, so a fooled client leaves a trace. Everything else is refused and audited by the
runner.

The protocol subset (initialize, ping, tools/list, tools/call, notifications) is written from memory of the Model
Context Protocol specification and has NOT been checked against it or against a real MCP client
(docs/BLUEPRINT.md rule 7).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, BinaryIO, Final, Literal

from core.audit.chain import ActorKind
from core.auth import AuthError, TokenValidator
from core.guard import detect_injection, wrap_untrusted
from core.identity import Role, UnknownIdentity
from core.levers import LeverRunner
from core.levers.models import InvokeResult, LeverDef
from core.levers.registry import NeverAutomate
from core.levers.runner import mask_change
from core.queue.store import proposal_id

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_NAME = "redline-levers"
SERVER_VERSION = "0.1.0"
MAX_LINE_BYTES = 1_048_576
MAX_DATA_CHARS = 65_536
UNAUTHENTICATED = "unauthenticated"
# Every call the server makes to the runner uses this mode. It is a constant, never read from a request.
CALL_MODE: Final[Literal["dry-run"]] = "dry-run"

_CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_CLIENT_PATTERN = r"^[a-z0-9][a-z0-9-]{0,62}$"
_NAME_MAX = 128

Rpc = dict[str, Any]

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603


def tool_name_for(lever: str) -> str:
    """MCP tool names allow letters, digits, `_` and `-`; lever names use `.` and never `_`, so this is reversible."""
    return lever.replace(".", "_")


def _error(request_id: Any, code: int, message: str) -> Rpc:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _param_schema(lever: LeverDef) -> Rpc:
    properties: dict[str, Any] = {}
    for name, spec in lever.params.items():
        entry: dict[str, Any] = {"type": spec.type}
        if spec.description:
            entry["description"] = spec.description
        if spec.enum is not None:
            entry["enum"] = list(spec.enum)
        if spec.max_length is not None:
            entry["maxLength"] = spec.max_length
        if spec.pattern is not None:
            entry["pattern"] = spec.pattern
        if spec.minimum is not None:
            entry["minimum"] = spec.minimum
        if spec.maximum is not None:
            entry["maximum"] = spec.maximum
        properties[name] = entry
    return {
        "type": "object",
        "properties": properties,
        "required": [name for name, spec in lever.params.items() if spec.required],
        "additionalProperties": False,
    }


def _tool_description(lever: LeverDef) -> str:
    if lever.lever_class == "write":
        return (
            f"{lever.description} PROPOSAL ONLY ({lever.risk_class}): returns a dry-run diff and a pending-approval "
            "proposal. This server never executes it; a lead approves and runs it elsewhere."
        )
    return f"{lever.description} Read-only ({lever.risk_class}); runs through the lever runner as the caller."


def _tool(lever: LeverDef) -> Rpc:
    return {
        "name": tool_name_for(lever.name),
        "description": _tool_description(lever),
        "inputSchema": {
            "type": "object",
            "properties": {
                "client": {"type": "string", "pattern": _CLIENT_PATTERN, "maxLength": 63, "description": "Client id"},
                "params": _param_schema(lever),
            },
            "required": ["client", "params"],
            "additionalProperties": False,
        },
    }


def _text(text: str) -> Rpc:
    return {"type": "text", "text": text}


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, ensure_ascii=True)


class LeverMcpServer:
    """One MCP session over one `LeverRunner`. `handle` takes one decoded message; `serve` runs the stdio loop."""

    def __init__(
        self,
        runner: LeverRunner,
        *,
        identity: str | None = None,
        validator: TokenValidator | None = None,
        token: str | None = None,
        include_writes: bool = False,
        clock: Callable[[], datetime] | None = None,
        never: NeverAutomate | None = None,
    ) -> None:
        if (identity is None) == (validator is None):
            raise ValueError("give exactly one of identity (a fixed caller) or validator (a token)")
        if identity is not None:
            try:
                runner.identities.get(identity)
            except UnknownIdentity:
                raise ValueError(f"unknown identity {identity!r}") from None
        self._runner = runner
        self._identity = identity
        self._validator = validator
        self._token = token
        self._clock = clock if clock is not None else (lambda: datetime.now(UTC))
        self._initialized = False
        gate = never if never is not None else NeverAutomate.load()
        self._exposed: dict[str, LeverDef] = {}
        self._registered_tools: dict[str, str] = {}
        for name in runner.registry.names():
            lever = runner.registry.get(name)
            if lever is None:
                continue
            self._registered_tools[tool_name_for(name)] = name
            if gate.match(name) is not None:
                continue  # defence in depth: the registry already refuses these (C-01)
            if lever.lever_class == "write" and not include_writes:
                continue
            self._exposed[tool_name_for(name)] = lever

    # -- who is calling ---------------------------------------------------------------------

    def _caller(self) -> tuple[str, str | None]:
        """(identity, None) for a known caller, else (UNAUTHENTICATED, the validator's fixed failure code)."""
        if self._identity is not None:
            return self._identity, None
        assert self._validator is not None
        try:
            return self._validator.validate(self._token, self._clock()).identity, None
        except AuthError as exc:
            return UNAUTHENTICATED, exc.code

    def _actor_kind(self, identity: str) -> ActorKind:
        try:
            who = self._runner.identities.get(identity)
        except UnknownIdentity:
            return "unknown"
        return "agent" if who.role is Role.AGENT else "human"

    # -- protocol ---------------------------------------------------------------------------

    def handle(self, message: Any) -> Rpc | None:
        """One decoded JSON-RPC message in, the reply out (None for a notification)."""
        if not isinstance(message, dict):
            return _error(None, INVALID_REQUEST, "a request must be a JSON object (batches are not supported)")
        has_id = "id" in message
        request_id = message.get("id")
        id_ok = not has_id or (isinstance(request_id, (str, int)) and not isinstance(request_id, bool))
        method = message.get("method")
        if message.get("jsonrpc") != "2.0" or not isinstance(method, str) or not id_ok:
            return _error(request_id if id_ok else None, INVALID_REQUEST, "not a JSON-RPC 2.0 request")
        params = message.get("params")
        if params is not None and not isinstance(params, dict):
            return None if not has_id else _error(request_id, INVALID_PARAMS, "params must be an object")
        if not has_id:
            return None  # notifications (initialized, cancelled, ...) get no reply
        try:
            return self._dispatch(request_id, method, params or {})
        except Exception:  # never leak internals to the client; the runner has audited what it did
            return _error(request_id, INTERNAL_ERROR, "internal error; nothing was executed")

    def _dispatch(self, request_id: Any, method: str, params: Rpc) -> Rpc:
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "initialize":
            asked = params.get("protocolVersion")
            version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            self._initialized = True
            result = {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            }
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        if method not in ("tools/list", "tools/call"):
            return _error(request_id, METHOD_NOT_FOUND, f"method {method[:64]!r} is not supported")
        if not self._initialized:
            return _error(request_id, INVALID_REQUEST, "the server is not initialized")
        if method == "tools/list":
            _, failure = self._caller()
            listed = [] if failure is not None else [_tool(lever) for _, lever in sorted(self._exposed.items())]
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": listed}}
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return _error(request_id, INVALID_PARAMS, "tools/call needs a tool name")
        return {"jsonrpc": "2.0", "id": request_id, "result": self._call_tool(name, params.get("arguments"))}

    # -- tools/call -------------------------------------------------------------------------

    def _call_tool(self, name: str, arguments: Any) -> Rpc:
        identity, failure = self._caller()
        client = self._client_of(arguments)
        lever = self._exposed.get(name)
        if lever is None:
            # A registered lever that is not an exposed tool (a write lever without --include-writes, or a dotted
            # lever name) is refused here; a name that is not registered at all goes to the runner to be denied.
            registered = name if name in self._registered_tools.values() else self._registered_tools.get(name)
            if registered is not None:
                return self._refuse(identity, client, registered, f"tool {name[:64]!r} is not exposed by this server")
        if failure is not None:
            known = lever.name if lever is not None else name[:_NAME_MAX]
            return self._refuse(identity, client, known, f"authentication failed: {failure}")
        problem = self._shape_problem(arguments)
        if problem is not None:
            return self._refuse(identity, client, lever.name if lever else name[:_NAME_MAX], problem)
        assert isinstance(arguments, dict) and client is not None
        lever_name = lever.name if lever is not None else name[:_NAME_MAX]
        result = self._runner.invoke(lever_name, arguments["params"], identity, client, mode=CALL_MODE)
        return self._present(result, lever, arguments["params"])

    @staticmethod
    def _client_of(arguments: Any) -> str | None:
        client = arguments.get("client") if isinstance(arguments, dict) else None
        return client if isinstance(client, str) and _CLIENT_ID.fullmatch(client) else None

    @staticmethod
    def _shape_problem(arguments: Any) -> str | None:
        """Why `arguments` is not exactly {"client": <id>, "params": {...}}; None when it is."""
        if not isinstance(arguments, dict):
            return "invalid arguments: expected an object with client and params"
        extra = sorted(str(k)[:32] for k in arguments if k not in ("client", "params"))
        if extra:
            return f"invalid arguments: not in the tool schema: {', '.join(extra[:5])}"
        if not isinstance(arguments.get("client"), str) or not _CLIENT_ID.fullmatch(arguments["client"]):
            return "invalid arguments: client must be a client id"
        if not isinstance(arguments.get("params"), dict):
            return "invalid arguments: params must be an object"
        return None

    def _refuse(self, identity: str, client: str | None, lever: str, reason: str) -> Rpc:
        """A refusal made by the door itself: audited like the runner's, and no runner call is made."""
        spec = self._runner.registry.get(lever)
        record = self._runner.audit.append(
            agent=identity[:_NAME_MAX],
            client=client,
            lever=lever[:_NAME_MAX],
            params={},
            mode=CALL_MODE,
            result={"status": "denied", "reason": reason, "applied": False, "changes": []},
            actor_kind=self._actor_kind(identity),
            lever_version=spec.lever_version if spec is not None else None,
        )
        meta = {
            "status": "denied",
            "reason": reason,
            "lever": lever[:_NAME_MAX],
            "client": client or "*",
            "identity": identity,
            "mode": CALL_MODE,
            "applied": False,
            "audit_seq": record["seq"],
            "injection_flags": [],
        }
        return {"content": [_text(_json(meta))], "isError": True}

    def _present(self, result: InvokeResult, lever: LeverDef | None, params: Mapping[str, Any]) -> Rpc:
        """The runner's result as MCP content: trusted facts first, then lever output as labelled untrusted data."""
        write = lever is not None and lever.lever_class == "write"
        if result.ok:
            if write:
                data = _json([mask_change(c) for c in result.diff])
            else:
                data = _json(result.data)
        else:
            data = ""
        truncated = len(data) > MAX_DATA_CHARS
        data = data[:MAX_DATA_CHARS]
        flags = sorted(detect_injection(data).rules) if data else []
        meta: dict[str, Any] = {
            "status": result.status,
            "reason": result.reason,
            "lever": result.lever,
            "client": result.client,
            "identity": result.identity,
            "mode": result.mode,
            "applied": False,
            "audit_seq": result.audit_seq,
            "injection_flags": flags,
        }
        if truncated:
            meta["truncated"] = True
        content = [_text(_json(meta))]
        if result.ok:
            content.append(_text(wrap_untrusted("tool_output", data)))
            if write and lever is not None and result.diff:
                content.append(_text(_json({"proposal": self._proposal(lever, result, params)})))
        return {"content": content, "isError": not result.ok}

    @staticmethod
    def _proposal(lever: LeverDef, result: InvokeResult, params: Mapping[str, Any]) -> Rpc:
        """The pending-approval proposal for a write: same id contract as the approval queue (core.queue.store)."""
        return {
            "id": proposal_id(lever.name, result.client, params),
            "status": "pending-approval",
            "executes": False,
            "lever": lever.name,
            "client": result.client,
            "params": dict(params),
            "requested_by": result.identity,
            "risk_class": lever.risk_class,
            "approval": lever.approval,
            "next_step": "A lead reviews the diff and approves it in the approval queue; this server cannot run it.",
        }

    # -- stdio loop -------------------------------------------------------------------------

    def serve(self, stdin: BinaryIO, stdout: BinaryIO) -> None:
        """Read newline-delimited JSON-RPC from `stdin`, write replies to `stdout`, until end of input."""
        while True:
            line = stdin.readline(MAX_LINE_BYTES + 1)
            if not line:
                return
            if len(line) > MAX_LINE_BYTES:
                while not line.endswith(b"\n"):  # drain the rest of an oversize line
                    line = stdin.readline(MAX_LINE_BYTES + 1)
                    if not line:
                        break
                self._write(stdout, _error(None, INVALID_REQUEST, "message too large"))
                continue
            if not line.strip():
                continue
            try:
                message = json.loads(line.decode("utf-8"))
            except (ValueError, RecursionError):
                self._write(stdout, _error(None, PARSE_ERROR, "parse error"))
                continue
            reply = self.handle(message)
            if reply is not None:
                self._write(stdout, reply)

    @staticmethod
    def _write(stdout: BinaryIO, reply: Mapping[str, Any]) -> None:
        stdout.write(json.dumps(reply, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n")
        stdout.flush()
