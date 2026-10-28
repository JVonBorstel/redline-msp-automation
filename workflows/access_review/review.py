"""Quarterly access review (B-49, specs/B-49.md; W-IDM-09, W-GOV-03; C-38, C-03, C-08).

Two kinds of export, each one file plus a ``.sha256`` sidecar:

- **Client export** (``<quarter>/<client>.json``). The members of every directory role in that client's tenant (from
  the Graph-shaped mock in ``fixtures/graph/<folder>/directoryRoles.json``) and every repo identity
  (``config/identities.json``) that may act for that client, with its role. Other clients are never named in it: an
  identity's wider scope shows only as a count (STD-ID-6, the same rule as a client's audit chain in B42-2).
- **MSP export** (``<quarter>/_msp.json``). Every repo identity with its role and full client list.

Each row has a ``decision`` field (``keep``, ``remove`` or ``investigate``) that is empty in the export. A lead fills it
with :func:`decide`, which writes a separate ``.decided.json`` that names the export's SHA-256. :func:`verify` re-hashes
a file against its sidecar and, for a decided file, rebuilds the original export bytes from it and checks them
against the export hash it names, so neither the population nor a decision can change unnoticed (B49-2).

Agents are flagged (B49-3) when they hold any execute capability (a registered write lever whose required role an
agent satisfies, for a client in its scope) or more clients than their workflow needs (``needs.json`` beside this
module: the clients each agent's workflow serves). An agent with no declared need is flagged too.

Every export, decision and refusal is audited through the per-client audit router (B-42): a client export and its
decisions in ``<audit>/<client>.jsonl``, the MSP export in ``<audit>/_msp.jsonl``. The record carries the file's
SHA-256, never its rows. Only a lead scoped to the client may export or decide; for the MSP export, a lead scoped to
every client in the identity file. Dates come from ``as_of`` (STD-TS-4). Nothing here changes a role, an identity or
a tenant: removing access is a person's job through the levers.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from core.audit.chain import ActorKind, head_path_for, verify_chain
from core.audit.router import MSP_LOG, AuditRouter
from core.guard.classify import DataClass
from core.identity import Identity, IdentityConfigError, IdentityStore, Role, UnknownIdentity, role_satisfies
from core.levers.models import LeverDef
from core.levers.registry import Registry, RegistryError
from core.paths import REPO_ROOT

DEFAULT_GRAPH_DIR = REPO_ROOT / "fixtures" / "graph"
DEFAULT_IDENTITIES = REPO_ROOT / "config" / "identities.json"
DEFAULT_REGISTRY = REPO_ROOT / "levers" / "registry.json"
DEFAULT_NEEDS = Path(__file__).with_name("needs.json")
DEFAULT_OUT_DIR = REPO_ROOT / "build" / "access-review"
# The lever CLI's audit folder (core/levers/__main__.py DEMO_DIR / "audit"): one chain per client, shared.
DEFAULT_AUDIT_DIR = REPO_ROOT / ".tmp" / "demo" / "audit"
# Graph mock folder per client (fixtures/graph/SOURCES.md; the folder names are not canonical ids yet, DR-05/DR-22).
GRAPH_FOLDER: dict[str, str] = {"contoso-dental": "contoso", "fabrikam-capital": "clean"}
DECISIONS: tuple[str, ...] = ("keep", "remove", "investigate")
EXPORT_KIND = "access-review"
DECIDED_KIND = "access-review-decided"
VERSION = 1
CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
ROW_ID = re.compile(r"^[A-Za-z0-9:._-]{1,200}$")
NOTE = "Synthetic data (fixture-based). A review export only: nothing was removed or changed. A lead decides."
# A client export names people in the client's tenant (UPNs): end-user PII. The MSP export names MSP staff and agents.
CLIENT_DATA_CLASS = DataClass.DC3
MSP_DATA_CLASS = DataClass.DC1
LEVER_EXPORT = "access-review.export"
LEVER_DECIDE = "access-review.decide"


class AccessReviewError(ValueError):
    """Bad input, missing data, or a refused caller; nothing was written except the audit record of a refusal."""


class VerifyError(ValueError):
    """A file does not match its hash, or a decided file does not match the export it names."""


@dataclass(frozen=True)
class Written:
    path: Path
    sha256: str
    rows: int


# -- hashing -------------------------------------------------------------------------------------------------------
def canonical_bytes(body: dict[str, Any]) -> bytes:
    """The exact bytes an export is written as: sorted keys, two-space indent, ASCII, one trailing newline."""
    return (json.dumps(body, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def audit_digest(hex_digest: str) -> str:
    """A SHA-256 as eight space-separated groups of eight hex digits, the form it takes in an audit record.

    The audit redactor replaces any run of 32 or more hex digits (STD-AU-5), which would blank the very hash the
    record is meant to pin. Grouped, it stays readable; ``"".join(value.split())`` gives the hash back.
    """
    return " ".join(hex_digest[i : i + 8] for i in range(0, len(hex_digest), 8))


def sidecar_for(path: Path) -> Path:
    return path.with_name(path.name + ".sha256")


def _write(path: Path, body: dict[str, Any]) -> Written:
    data = canonical_bytes(body)
    digest = sha256_hex(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    # sha256sum format, so `sha256sum -c` (or Get-FileHash) re-verifies it without this code.
    sidecar_for(path).write_text(f"{digest}  {path.name}\n", encoding="ascii", newline="\n")
    return Written(path, digest, len(body["rows"]))


# -- inputs --------------------------------------------------------------------------------------------------------
def quarter_of(as_of: str) -> str:
    try:
        day = date.fromisoformat(as_of)
    except ValueError:
        raise AccessReviewError(f"as_of must be an ISO date (YYYY-MM-DD), got {as_of!r}") from None
    return f"{day.year}-Q{(day.month - 1) // 3 + 1}"


def _client_id(client: str) -> str:
    if not isinstance(client, str) or not CLIENT_ID.fullmatch(client):
        raise AccessReviewError(f"{client!r} is not a client id")
    return client


def _load_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AccessReviewError(f"cannot read {Path(path).name}: {exc}") from None


def _source(path: Path) -> dict[str, str]:
    """A source file's repo-relative path (or bare name outside the repo) and its SHA-256."""
    path = Path(path).resolve()
    try:
        shown = path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        shown = path.name
    return {"path": shown, "sha256": sha256_hex(path.read_bytes())}


def load_needs(path: Path = DEFAULT_NEEDS) -> dict[str, dict[str, Any]]:
    """Agent id -> {"workflow": str, "clients": [client ids]}: what each agent's workflow needs (B49-3)."""
    raw = _load_json(path)
    if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("agents"), dict):
        raise AccessReviewError(f"{Path(path).name}: expected {{'version': 1, 'agents': {{...}}}}")
    needs: dict[str, dict[str, Any]] = {}
    for agent, entry in raw["agents"].items():
        clients = entry.get("clients") if isinstance(entry, dict) else None
        workflow = entry.get("workflow") if isinstance(entry, dict) else None
        if not isinstance(workflow, str) or not workflow or not isinstance(clients, list):
            raise AccessReviewError(f"{Path(path).name}: agent {agent!r} needs a workflow and a client list")
        needs[str(agent)] = {"workflow": workflow, "clients": sorted(_client_id(c) for c in clients)}
    return needs


def _directory_roles(client: str, graph_dir: Path) -> tuple[Path, list[dict[str, Any]]]:
    folder = GRAPH_FOLDER.get(client)
    path = Path(graph_dir) / folder / "directoryRoles.json" if folder else None
    if path is None or not path.is_file():
        raise AccessReviewError(f"no directory role data for client {client!r}; nothing exported")
    body = _load_json(path)
    values = body.get("value") if isinstance(body, dict) else None
    if not isinstance(values, list):
        raise AccessReviewError(f"{path.name}: expected a Graph collection with a 'value' list")
    return path, [v for v in values if isinstance(v, dict)]


# -- agent flags (B49-3) -------------------------------------------------------------------------------------------
def execute_levers(identity: Identity, registry: Registry, clients: tuple[str, ...] | None = None) -> list[str]:
    """Write levers this identity's role may execute for at least one of `clients` (default: its own clients)."""
    scope = clients if clients is not None else identity.clients
    found = []
    for name in registry.names():
        lever: LeverDef | None = registry.get(name)
        if lever is None or lever.lever_class != "write" or not role_satisfies(identity.role, lever.required_role):
            continue
        if any(lever.allows_client(c) for c in scope):
            found.append(name)
    return sorted(found)


def agent_flags(
    identity: Identity,
    registry: Registry,
    needs: dict[str, dict[str, Any]],
    client: str | None = None,
) -> list[dict[str, Any]]:
    """B49-3 flags for an agent identity; humans get none. With `client`, only that client is looked at and no other
    client is named (the client export); without it, the whole scope (the MSP export)."""
    if identity.role is not Role.AGENT:
        return []
    flags: list[dict[str, Any]] = []
    scope = (client,) if client is not None else identity.clients
    levers = execute_levers(identity, registry, scope)
    if levers:
        flags.append({"flag": "execute-capability", "levers": levers})
    need = needs.get(identity.id)
    if need is None:
        flags.append({"flag": "no-declared-need", "detail": "no workflow need is declared for this agent"})
        return flags
    excess = sorted(set(scope) - set(need["clients"]))
    # Client export: the exported client is needed, but the agent holds others the workflow does not need. Count only.
    other_excess = len(set(identity.clients) - set(need["clients"]) - {client}) if client is not None else 0
    if client is not None and not excess and other_excess:
        flags.append({"flag": "excess-other-clients", "workflow": need["workflow"], "count": other_excess})
    if excess:
        entry: dict[str, Any] = {"flag": "excess-clients", "workflow": need["workflow"]}
        if client is None:
            entry["clients"] = excess
            entry["needed"] = need["clients"]
        else:
            entry["detail"] = f"workflow {need['workflow']!r} does not need this client"
            entry["excess_other_clients"] = other_excess
        flags.append(entry)
    return flags


# -- exports (B49-1) -----------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class _Inputs:
    identities: IdentityStore
    registry: Registry
    needs: dict[str, dict[str, Any]]
    sources: dict[str, dict[str, str]]


def _inputs(identities_path: Path, registry_path: Path, needs_path: Path) -> _Inputs:
    try:
        identities = IdentityStore.load(identities_path)
        registry = Registry.load(registry_path)
    except (IdentityConfigError, RegistryError) as exc:
        raise AccessReviewError(str(exc)) from None
    needs = load_needs(needs_path)
    unknown = sorted(a for a in needs if a not in identities)
    if unknown:
        raise AccessReviewError(f"{Path(needs_path).name} names identities that do not exist: {unknown}")
    sources = {"identities": _source(identities_path), "needs": _source(needs_path)}
    return _Inputs(identities, registry, needs, sources)


def _header(scope: str, client: str | None, as_of: str, data_class: DataClass, by: str) -> dict[str, Any]:
    return {
        "kind": EXPORT_KIND,
        "version": VERSION,
        "scope": scope,
        "client": client,
        "quarter": quarter_of(as_of),
        "as_of": as_of,
        "exported_by": by,
        "data_class": data_class.label,
        "decision_options": list(DECISIONS),
        "note": NOTE,
    }


def build_client_export(
    client: str,
    *,
    as_of: str,
    by: str,
    graph_dir: Path = DEFAULT_GRAPH_DIR,
    identities_path: Path = DEFAULT_IDENTITIES,
    registry_path: Path = DEFAULT_REGISTRY,
    needs_path: Path = DEFAULT_NEEDS,
) -> dict[str, Any]:
    """The client export body (not yet written). Rows: directory role members, then repo identities for `client`."""
    _client_id(client)
    inputs = _inputs(identities_path, registry_path, needs_path)
    roles_path, roles = _directory_roles(client, graph_dir)
    rows: list[dict[str, Any]] = []
    gaps = {"duplicate_members": 0, "members_with_invalid_id": 0, "members_without_id": 0}
    seen: set[str] = set()
    for role in sorted(roles, key=lambda r: (str(r.get("displayName")), str(r.get("id")))):
        for m in sorted((m for m in role.get("members", []) if isinstance(m, dict)), key=lambda m: str(m.get("id"))):
            template, member = role.get("roleTemplateId"), m.get("id")
            if not (isinstance(template, str) and template and isinstance(member, str) and member):
                gaps["members_without_id"] += 1  # no id or no role template id: no stable key, skipped and counted
                continue
            row_id = f"role:{template}:{member}"
            if not ROW_ID.fullmatch(row_id):
                gaps["members_with_invalid_id"] += 1  # Graph text becomes a key in the decisions file: validate it
                continue
            if row_id in seen:
                gaps["duplicate_members"] += 1  # the same member listed twice in a role must not give a twin row id
                continue
            seen.add(row_id)
            user_type, enabled = m.get("userType"), m.get("accountEnabled")
            user_type = user_type if isinstance(user_type, str) else None
            enabled = enabled if isinstance(enabled, bool) else None
            flags: list[dict[str, Any]] = []
            if user_type is not None and user_type.lower() == "guest":
                flags.append({"flag": "guest-holds-role"})
            if enabled is False:
                flags.append({"flag": "disabled-account-holds-role"})
            rows.append(
                {
                    "row_id": row_id,
                    "kind": "directory-role-member",
                    "role": role.get("displayName"),
                    "role_template_id": template,
                    "member_id": member,
                    "member_type": str(m.get("@odata.type", "")).removeprefix("#microsoft.graph."),
                    "user_type": user_type,
                    "account_enabled": enabled,
                    "user_principal_name": m.get("userPrincipalName"),
                    "display_name": m.get("displayName"),
                    "flags": flags,
                    "decision": None,
                }
            )
    for ident in sorted((i for i in inputs.identities if i.can_act_for(client)), key=lambda i: i.id):
        if not ROW_ID.fullmatch(f"identity:{ident.id}"):
            raise AccessReviewError(f"identity id {ident.id!r} is not usable as a row id")
        rows.append(
            {
                "row_id": f"identity:{ident.id}",
                "kind": "repo-identity",
                "identity": ident.id,
                "role": ident.role.value,
                "clients": [client],
                "other_clients": len(ident.clients) - 1,
                "flags": agent_flags(ident, inputs.registry, inputs.needs, client),
                "decision": None,
            }
        )
    body = _header("client", client, as_of, CLIENT_DATA_CLASS, by)
    body["sources"] = {"directory_roles": _source(roles_path), **inputs.sources}
    body["gaps"] = gaps
    body["rows"] = rows
    return body


def build_msp_export(
    *,
    as_of: str,
    by: str,
    identities_path: Path = DEFAULT_IDENTITIES,
    registry_path: Path = DEFAULT_REGISTRY,
    needs_path: Path = DEFAULT_NEEDS,
) -> dict[str, Any]:
    """The MSP export body: every repo identity with its role and full client list, agents flagged (B49-3)."""
    inputs = _inputs(identities_path, registry_path, needs_path)
    bad = sorted(i.id for i in inputs.identities if not ROW_ID.fullmatch(f"identity:{i.id}"))
    if bad:
        raise AccessReviewError(f"identity ids not usable as row ids: {bad}")
    rows = [
        {
            "row_id": f"identity:{ident.id}",
            "kind": "repo-identity",
            "identity": ident.id,
            "display_name": ident.display_name,
            "role": ident.role.value,
            "clients": sorted(ident.clients),
            "flags": agent_flags(ident, inputs.registry, inputs.needs),
            "decision": None,
        }
        for ident in sorted(inputs.identities, key=lambda i: i.id)
    ]
    body = _header("msp", None, as_of, MSP_DATA_CLASS, by)
    body["sources"] = inputs.sources
    body["rows"] = rows
    return body


def _lead(identities: IdentityStore, who: str, clients: tuple[str, ...]) -> str | None:
    """None when `who` is a lead scoped to every client in `clients`, else the refusal reason."""
    try:
        ident = identities.get(who)
    except UnknownIdentity:
        return f"unknown identity {who!r}"
    if ident.role is not Role.LEAD:
        return f"role {ident.role.value!r} cannot run an access review (needs lead)"
    missing = [c for c in clients if not ident.can_act_for(c)]
    if missing:
        return (
            f"{who} is not scoped to every client under review"
            if len(clients) > 1
            else f"{who} is not scoped to {missing[0]!r}"
        )
    return None


def _actor_kind(identities: IdentityStore, who: str) -> ActorKind:
    if who not in identities:
        return "unknown"
    return "agent" if identities.get(who).role is Role.AGENT else "human"


def _audit(
    audit: AuditRouter,
    identities: IdentityStore,
    *,
    who: str,
    client: str | None,
    lever: str,
    params: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """One `job.run` record in the client's chain (the MSP chain when `client` is None), allowed or refused."""
    audit.append(
        agent=who,
        client=client,
        lever=lever,
        params=params,
        mode="execute",
        result=result,
        event="job.run",
        actor_kind=_actor_kind(identities, who),
        lever_version=VERSION,
    )


def export(
    client: str | None,
    *,
    as_of: str,
    by: str,
    out_dir: Path = DEFAULT_OUT_DIR,
    audit_dir: Path = DEFAULT_AUDIT_DIR,
    graph_dir: Path = DEFAULT_GRAPH_DIR,
    identities_path: Path = DEFAULT_IDENTITIES,
    registry_path: Path = DEFAULT_REGISTRY,
    needs_path: Path = DEFAULT_NEEDS,
) -> Written:
    """Write one export (`client`, or the MSP export when `client` is None) and its sidecar; audit it either way."""
    if client is not None:
        _client_id(client)
    quarter = quarter_of(as_of)
    audit = AuditRouter(audit_dir)
    try:
        identities = IdentityStore.load(identities_path)
    except IdentityConfigError as exc:
        raise AccessReviewError(str(exc)) from None
    scope = (client,) if client is not None else tuple(sorted({c for i in identities for c in i.clients}))
    params = {"scope": "client" if client else "msp", "quarter": quarter, "as_of": as_of}
    refused = _lead(identities, by, scope)
    if refused is not None:
        _audit(
            audit,
            identities,
            who=by,
            client=client,
            lever=LEVER_EXPORT,
            params=params,
            result={"status": "denied", "reason": refused},
        )
        raise AccessReviewError(refused)
    try:
        if client is not None:
            body = build_client_export(
                client,
                as_of=as_of,
                by=by,
                graph_dir=graph_dir,
                identities_path=identities_path,
                registry_path=registry_path,
                needs_path=needs_path,
            )
        else:
            body = build_msp_export(
                as_of=as_of, by=by, identities_path=identities_path, registry_path=registry_path, needs_path=needs_path
            )
    except AccessReviewError as exc:  # missing Graph mock, bad needs, bad registry: refused, so audited too
        _audit(
            audit,
            identities,
            who=by,
            client=client,
            lever=LEVER_EXPORT,
            params=params,
            result={"status": "denied", "reason": str(exc)},
        )
        raise
    written = _write(Path(out_dir) / quarter / f"{client or MSP_LOG}.json", body)
    flagged = sum(1 for r in body["rows"] if r["flags"])
    _audit(
        audit,
        identities,
        who=by,
        client=client,
        lever=LEVER_EXPORT,
        params=params,
        result={
            "status": "ok",
            "sha256": audit_digest(written.sha256),
            "rows": written.rows,
            "flagged": flagged,
            "skipped": sum(v for v in body.get("gaps", {}).values() if isinstance(v, int)),
        },
    )
    return written


# -- decisions and verification (B49-2) ----------------------------------------------------------------------------
def verify(path: Path, audit_dir: Path | None = None) -> str:
    """Re-hash `path` against its sidecar; for a decided file also rebuild the export it names and check that hash.

    With `audit_dir`, the file's hash must also be pinned by a successful record in the scope's audit chain, and that
    chain must verify: a decision edited after the fact, with a fresh sidecar, is caught there. Returns the file's
    SHA-256. Raises VerifyError on any mismatch."""
    path = Path(path)
    side = sidecar_for(path)
    try:
        data = path.read_bytes()
        line = side.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise VerifyError(f"cannot read {exc.filename}") from None
    except ValueError:
        raise VerifyError(f"{side.name}: sidecar is not ASCII text") from None
    expected, _, name = line.partition("  ")
    actual = sha256_hex(data)
    if name != path.name or actual != expected:
        raise VerifyError(f"{path.name}: SHA-256 {actual} does not match the sidecar ({expected or 'empty'})")
    try:
        body = json.loads(data)
    except ValueError:
        raise VerifyError(f"{path.name}: matches its sidecar but is not valid JSON") from None
    if not isinstance(body, dict):
        raise VerifyError(f"{path.name}: not an access review file")
    if canonical_bytes(body) != data:
        raise VerifyError(f"{path.name}: not in canonical form")
    _check_rows(body)
    if body.get("kind") == DECIDED_KIND:
        rebuilt = sha256_hex(canonical_bytes(undecided(body)))
        if rebuilt != body.get("export_sha256"):
            raise VerifyError(
                f"{path.name}: rows do not rebuild the export {body.get('export_sha256')} (got {rebuilt})"
            )
        for row in body["rows"]:
            if row["decision"] not in DECISIONS:
                raise VerifyError(f"{path.name}: row {row['row_id']} has no valid decision")
    elif body.get("kind") == EXPORT_KIND:
        if any(row["decision"] is not None for row in body["rows"]):
            raise VerifyError(f"{path.name}: an export carries no decisions; decisions go in a decided file")
    else:
        raise VerifyError(f"{path.name}: not an access review file")
    if audit_dir is not None:
        _pinned(path.name, actual, body, Path(audit_dir))
    return actual


def _pinned(name: str, digest: str, body: dict[str, Any], audit_dir: Path) -> None:
    lever = LEVER_DECIDE if body.get("kind") == DECIDED_KIND else LEVER_EXPORT
    chain = AuditRouter(audit_dir).path_for(body.get("client"))
    if not chain.is_file():
        raise VerifyError(f"{name}: no audit chain at {chain.name}")
    result = verify_chain(chain, head_path_for(chain) if head_path_for(chain).exists() else None)
    if not result.ok:
        raise VerifyError(f"{name}: audit chain {chain.name} does not verify at seq {result.broken_seq}")
    for line in chain.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        res = record.get("result") or {}
        if (
            record.get("lever") == lever
            and res.get("status") == "ok"
            and "".join(str(res.get("sha256")).split()) == digest
        ):
            return
    raise VerifyError(f"{name}: SHA-256 {digest} is not pinned by any {lever} record in {chain.name}")


def _check_rows(body: dict[str, Any]) -> None:
    rows = body.get("rows")
    if not isinstance(rows, list):
        raise VerifyError("no rows")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or "decision" not in row or not isinstance(row.get("row_id"), str):
            raise VerifyError("a row has no row_id or no decision field")
        if row["row_id"] in seen:
            raise VerifyError(f"row {row['row_id']} appears twice")
        seen.add(row["row_id"])


def undecided(decided: dict[str, Any]) -> dict[str, Any]:
    """The export body a decided body was made from: decision fields emptied, decision metadata removed."""
    body = {k: v for k, v in decided.items() if k not in _DECIDED_KEYS}
    body["kind"] = EXPORT_KIND
    body["rows"] = [{k: v for k, v in r.items() if k != "note"} | {"decision": None} for r in decided["rows"]]
    return body


_DECIDED_KEYS = frozenset({"kind", "export_sha256", "decided_by", "decided_on"})


def decide(
    export_path: Path,
    decisions: dict[str, str],
    *,
    by: str,
    decided_on: str,
    notes: dict[str, str] | None = None,
    audit_dir: Path = DEFAULT_AUDIT_DIR,
    identities_path: Path = DEFAULT_IDENTITIES,
) -> Written:
    """Write `<export>.decided.json`: the export with a lead's decision on every row. Audited, allowed or refused."""
    export_path = Path(export_path)
    try:
        export_sha = verify(export_path)
    except VerifyError as exc:
        raise AccessReviewError(f"export does not verify, nothing decided: {exc}") from None
    body = json.loads(export_path.read_bytes())
    if body["kind"] != EXPORT_KIND:
        raise AccessReviewError("decide takes an export, not a decided file")
    quarter_of(decided_on)  # a valid ISO date, or refuse
    client = body.get("client")
    audit = AuditRouter(audit_dir)
    try:
        identities = IdentityStore.load(identities_path)
    except IdentityConfigError as exc:
        raise AccessReviewError(str(exc)) from None
    scope = (client,) if client else tuple(sorted({c for r in body["rows"] for c in r.get("clients", [])}))
    params = {"scope": body["scope"], "quarter": body["quarter"], "export_sha256": audit_digest(export_sha)}
    refused = _lead(identities, by, scope)
    notes = notes or {}
    if refused is None:
        ids = {r["row_id"] for r in body["rows"]}
        unknown = sorted((set(decisions) | set(notes)) - ids)
        missing = sorted(ids - set(decisions))
        bad = sorted(k for k, v in decisions.items() if v not in DECISIONS)
        if unknown:
            refused = f"decisions name rows not in the export: {unknown}"
        elif bad:
            refused = f"decision must be one of {', '.join(DECISIONS)} (rows {bad})"
        elif missing:
            refused = f"every row needs a decision; missing {len(missing)}: {missing[:5]}"
    if refused is not None:
        _audit(
            audit,
            identities,
            who=by,
            client=client,
            lever=LEVER_DECIDE,
            params=params,
            result={"status": "denied", "reason": refused},
        )
        raise AccessReviewError(refused)
    rows = []
    for row in body["rows"]:
        out = {**row, "decision": decisions[row["row_id"]]}
        if row["row_id"] in notes:
            out["note"] = str(notes[row["row_id"]])[:500]
        rows.append(out)
    decided = {**body, "kind": DECIDED_KIND, "export_sha256": export_sha, "decided_by": by, "decided_on": decided_on}
    decided["rows"] = rows
    written = _write(export_path.with_name(export_path.stem + ".decided.json"), decided)
    counts = {d: sum(1 for r in rows if r["decision"] == d) for d in DECISIONS}
    _audit(
        audit,
        identities,
        who=by,
        client=client,
        lever=LEVER_DECIDE,
        params=params,
        result={"status": "ok", "sha256": audit_digest(written.sha256), "rows": written.rows, **counts},
    )
    return written
