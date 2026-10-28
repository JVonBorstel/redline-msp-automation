"""Restore requests to an alternate location and scheduled restore tests (B-69, specs/B-69.md; W-BDR-03, W-BDR-04).

Two things, both per client and both mock-only:

**Restore request** (B69-1). :func:`propose_restore` dry-runs ``restore.to-alternate`` for one item of the client's own
restore catalog. The item is looked up in that client's catalog first (STD-LV-9): another client's item answers like an
absent one and the lever is not called. A request to restore over the item's ORIGINAL location is refused here with
its reason, and the lever cannot take it either (its location pattern starts with ``ALT-``). In-place overwrite is not
a lever; it would need its own approval outside this workflow. Nothing here executes: a person turns an ok dry-run into
a proposal, a technician verifies the requester (B69-3, ``verification: requester``) and a lead approves.

**Restore test** (B69-2). :func:`run_restore_test` picks one restorable item of the client (a deterministic
pseudo-random choice from client, date and an optional seed, so a re-run of the same day picks the same item), restores
it in the mock into a throw-away alternate location held in memory, hashes what came back and compares it with the hash
recorded at backup time. The result (``passed``, ``failed`` or ``not-run``) goes into an evidence file: canonical JSON
plus a ``sha256sum``-format sidecar, and one record in the client's audit chain that pins the file's SHA-256.
:func:`verify_evidence` re-checks the file, its internal consistency and, with the audit folder, the pin. A failed test
is recorded as failed, never retried until it passes. Nothing else is written: no tenant state, no fixture.

No model is called (D-022). Dates come from ``as_of`` (STD-TS-4).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.audit.chain import ActorKind, head_path_for, verify_chain
from core.audit.router import AuditRouter
from core.identity import IdentityStore, Role, UnknownIdentity
from core.levers import InvokeResult, LeverRunner
from core.paths import REPO_ROOT
from core.scheduler.models import Every, Unit, UnitResult
from workflows.restore_tests.catalog import NO_SUCH_ITEM, RestoreCatalog, sha256_hex

DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.json")
DEFAULT_OUT_DIR = REPO_ROOT / "build" / "restore-tests"
# The lever CLI's audit folder (core/levers/__main__.py DEMO_DIR / "audit"): one chain per client, shared.
DEFAULT_AUDIT_DIR = REPO_ROOT / ".tmp" / "demo" / "audit"
REQUEST_AGENT = "triage-bot"
RESTORE_LEVER = "restore.to-alternate"
AUDIT_LEVER = "restore-test.run"
EVIDENCE_KIND = "restore-test"
VERSION = 1
ALTERNATE_PREFIX = "ALT-"
NOTE = "Synthetic data (fixture-based). A mock restore into a throw-away location in memory: nothing real was restored."
IN_PLACE_REFUSED = (
    "restoring over the original location is not a lever; an alternate location name starts with ALT-. "
    "Overwriting the original needs its own approval outside this workflow"
)
Result = Literal["passed", "failed", "not-run"]
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SEED = re.compile(r"^[A-Za-z0-9._-]{0,32}$")
_HEX = re.compile(r"^[0-9a-f]{64}$")


class RestoreError(ValueError):
    """Bad input, a refused caller or unreadable data; nothing was restored and no evidence was written."""


class VerifyError(ValueError):
    """An evidence file does not match its hash, is inconsistent, or is not pinned in the audit chain."""


class RestoreConfig(BaseModel):
    """The workflow's configuration; unknown keys fail the load (STD-CF-3)."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    version: Literal[1]
    note: str = Field(default="", alias="_note")
    every: Every  # how often the scheduler runs one test per client
    test_location: str = Field(pattern=r"^ALT-[A-Z0-9][A-Z0-9-]{2,39}$")
    agent: str = Field(min_length=1, max_length=64)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> RestoreConfig:
    try:
        return RestoreConfig.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        raise RestoreError(f"cannot load restore test config from {path}: {exc}") from exc


# -- restore requests (B69-1, B69-3) ---------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RestoreProposal:
    item_id: str
    ok: bool
    reason: str
    result: InvokeResult | None = None


def _same_place(first: str, second: str) -> bool:
    def norm(value: str) -> str:
        return value.strip().replace("\\", "/").rstrip("/").casefold()

    return norm(first) == norm(second)


def propose_restore(
    item_id: str,
    alternate_location: str,
    catalog: RestoreCatalog,
    runner: LeverRunner,
    *,
    agent: str = REQUEST_AGENT,
) -> RestoreProposal:
    """Dry-run ``restore.to-alternate`` for one item of this client. Nothing is ever executed here.

    Refused before the lever is called: an item that is not this client's (same words as an absent one), an item whose
    backup job did not succeed, the item's original location, and any location that is not an ``ALT-`` name.
    """
    found = catalog.restorable(item_id)
    if not found.ok or found.data is None:
        return RestoreProposal(item_id, False, found.reason)
    original = str(found.data.get("originalLocation"))
    if _same_place(alternate_location, original) or not alternate_location.startswith(ALTERNATE_PREFIX):
        return RestoreProposal(item_id, False, IN_PLACE_REFUSED)
    result = runner.invoke(
        RESTORE_LEVER,
        {"item_id": item_id, "alternate_location": alternate_location},
        identity=agent,
        client=catalog.client,
        mode="dry-run",
    )
    return RestoreProposal(item_id, result.ok, result.reason, result)


# -- evidence files (B69-2) ------------------------------------------------------------------------------------------
def canonical_bytes(body: dict[str, Any]) -> bytes:
    """The exact bytes evidence is written as: sorted keys, two-space indent, ASCII, one trailing newline."""
    return (json.dumps(body, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def audit_digest(hex_digest: str) -> str:
    """A SHA-256 as eight groups of eight hex digits, the form it takes in an audit record (STD-AU-5 redactor)."""
    return " ".join(hex_digest[i : i + 8] for i in range(0, len(hex_digest), 8))


def sidecar_for(path: Path) -> Path:
    return path.with_name(path.name + ".sha256")


@dataclass(frozen=True, slots=True)
class TestRecord:
    __test__ = False  # not a pytest class

    client: str
    result: Result
    path: Path
    sha256: str
    item_id: str | None
    reason: str


def pick_item(client: str, day: str, seed: str, candidates: list[str]) -> str:
    """A deterministic pseudo-random choice: same client, day and seed give the same item (a re-run is idempotent)."""
    ordered = sorted(candidates)
    digest = hashlib.sha256(f"{client}|{day}|{seed}".encode()).hexdigest()
    return ordered[int(digest, 16) % len(ordered)]


def _actor_kind(identities: IdentityStore, who: str) -> ActorKind:
    if who not in identities:
        return "unknown"
    return "agent" if identities.get(who).role is Role.AGENT else "human"


def _audit(
    audit: AuditRouter,
    identities: IdentityStore,
    *,
    who: str,
    client: str,
    params: dict[str, Any],
    result: dict[str, Any],
) -> None:
    audit.append(
        agent=who,
        client=client,
        lever=AUDIT_LEVER,
        params=params,
        mode="execute",
        result=result,
        event="job.run",
        actor_kind=_actor_kind(identities, who),
        lever_version=VERSION,
    )


def _check_runner(identities: IdentityStore, who: str, client: str) -> str | None:
    try:
        ident = identities.get(who)
    except UnknownIdentity:
        return f"unknown identity {who!r}"
    if not ident.can_act_for(client):
        return f"{who} is not scoped to {client!r}"
    return None


def run_restore_test(
    catalog: RestoreCatalog,
    as_of: str,
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    audit_dir: Path = DEFAULT_AUDIT_DIR,
    seed: str = "",
    item_id: str | None = None,
    by: str | None = None,
    config: RestoreConfig | None = None,
    identities: IdentityStore | None = None,
) -> TestRecord:
    """Restore one random synthetic item of the client to the alternate test location and record the evidence.

    ``item_id`` forces the item (a lead re-testing one thing); by default it is picked from the client's restorable
    items. The same day for the same client writes the same bytes; a different result for a day that already has
    evidence is refused, never overwritten.
    """
    cfg = config or load_config()
    ids = identities or IdentityStore.load()
    who = by or cfg.agent
    client = catalog.client
    try:
        date.fromisoformat(as_of)
    except ValueError:
        raise RestoreError(f"as_of must be an ISO date (YYYY-MM-DD), got {as_of!r}") from None
    if not _DAY.fullmatch(as_of):
        raise RestoreError(f"as_of must be an ISO date (YYYY-MM-DD), got {as_of!r}")
    if not _SEED.fullmatch(seed):
        raise RestoreError("seed is at most 32 letters, digits, dots, dashes or underscores")
    audit = AuditRouter(audit_dir)
    refusal = _check_runner(ids, who, client)
    if refusal is not None:
        _audit(
            audit,
            ids,
            who=who,
            client=client,
            params={"as_of": as_of},
            result={"status": "refused", "reason": refusal},
        )
        raise RestoreError(refusal)

    candidates = catalog.restorable_ids()
    chosen: str | None
    if item_id is not None:
        chosen = item_id
    else:
        chosen = pick_item(client, as_of, seed, candidates) if candidates else None

    item: dict[str, Any] | None = None
    restored_hash: str | None = None
    restore_info: dict[str, Any] | None = None
    expected: str | None = None
    if chosen is None:
        result: Result = "not-run"
        reason = "The client has no restorable item, so no test was run."
    else:
        found = catalog.restorable(chosen)
        if not found.ok or found.data is None:
            raise RestoreError(found.reason or NO_SUCH_ITEM)
        item = found.data
        expected = str(item["sha256"])
        sink: dict[str, bytes] = {}
        done = catalog.restore(chosen, cfg.test_location, sink)
        if not done.ok or cfg.test_location not in sink:
            result, reason = "failed", f"The mock restore did not complete: {done.reason}"
        else:
            restored_hash = sha256_hex(sink[cfg.test_location])
            restore_info = {"location": cfg.test_location, "bytes": len(sink[cfg.test_location])}
            if restored_hash == expected:
                result, reason = "passed", "The restored copy has the same SHA-256 as the backup recorded."
            else:
                result, reason = "failed", "The restored copy does not have the SHA-256 the backup recorded."

    body: dict[str, Any] = {
        "version": VERSION,
        "kind": EVIDENCE_KIND,
        "note": NOTE,
        "client": client,
        "as_of": as_of,
        "run_by": who,
        "selection": {
            "method": "sha256(client|as_of|seed) modulo the sorted restorable item ids",
            "seed": seed,
            "forced": item_id is not None,
            "candidates": len(candidates),
        },
        "item": None
        if item is None
        else {
            "id": item["id"],
            "kind": item["kind"],
            "name": item["name"],
            "source_job_id": item["sourceJobId"],
            "original_location": item["originalLocation"],
        },
        "restore": restore_info,
        "expected_sha256": expected,
        "restored_sha256": restored_hash,
        "result": result,
        "reason": reason,
        "catalog_sha256": catalog.source_sha256,
    }
    data = canonical_bytes(body)
    digest = sha256_hex(data)
    path = Path(out_dir) / client / f"{as_of}.json"
    if path.is_file() and path.read_bytes() != data:
        _audit(
            audit,
            ids,
            who=who,
            client=client,
            params={"as_of": as_of},
            result={"status": "refused", "reason": "evidence for this day already exists and differs"},
        )
        raise RestoreError(f"{path.name} already holds evidence for {as_of} that differs; it is not overwritten")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    # sha256sum format, so `sha256sum -c` (or Get-FileHash) re-verifies it without this code.
    sidecar_for(path).write_text(f"{digest}  {path.name}\n", encoding="ascii", newline="\n")
    _audit(
        audit,
        ids,
        who=who,
        client=client,
        params={"as_of": as_of, "seed": seed},
        result={
            "status": "ok",
            "test": result,
            "item_id": None if item is None else item["id"],
            "sha256": audit_digest(digest),
        },
    )
    return TestRecord(client, result, path, digest, None if item is None else str(item["id"]), reason)


def verify_evidence(path: Path, audit_dir: Path | None = None) -> str:
    """Re-hash an evidence file against its sidecar, check it agrees with itself, and optionally check its audit pin.

    Returns the file's SHA-256. Raises VerifyError on any mismatch. A file that records a FAILED test verifies fine:
    verification is about the record being intact, not about the restore having worked.
    """
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
    if not isinstance(body, dict) or body.get("kind") != EVIDENCE_KIND:
        raise VerifyError(f"{path.name}: not a restore test evidence file")
    if canonical_bytes(body) != data:
        raise VerifyError(f"{path.name}: not in canonical form")
    _check_consistent(path.name, body)
    if audit_dir is not None:
        _pinned(path.name, actual, body, Path(audit_dir))
    return actual


def _check_consistent(name: str, body: dict[str, Any]) -> None:
    result, item, restore = body.get("result"), body.get("item"), body.get("restore")
    exp, got = body.get("expected_sha256"), body.get("restored_sha256")
    if result == "not-run":
        if any(v is not None for v in (exp, got, restore, item)):
            raise VerifyError(f"{name}: a test that did not run carries no item, restore or hash")
        return
    if result not in ("passed", "failed") or not isinstance(item, dict) or not isinstance(exp, str):
        raise VerifyError(f"{name}: result and item do not agree")
    if not _HEX.fullmatch(exp):
        raise VerifyError(f"{name}: expected_sha256 is not a SHA-256")
    if got is None:
        if result != "failed" or restore is not None:
            raise VerifyError(f"{name}: a restore with no restored hash can only be a failed test")
        return
    if not isinstance(got, str) or not _HEX.fullmatch(got) or not isinstance(restore, dict):
        raise VerifyError(f"{name}: restored_sha256 is not a SHA-256 or the restore is missing")
    if (result == "passed") != (got == exp):
        raise VerifyError(f"{name}: the result does not agree with the two hashes")
    location = str(restore.get("location"))
    if not location.startswith(ALTERNATE_PREFIX) or _same_place(location, str(item.get("original_location"))):
        raise VerifyError(f"{name}: the restore went to the original location, not an alternate one")


def _pinned(name: str, digest: str, body: dict[str, Any], audit_dir: Path) -> None:
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
            record.get("lever") == AUDIT_LEVER
            and res.get("status") == "ok"
            and "".join(str(res.get("sha256")).split()) == digest
        ):
            return
    raise VerifyError(f"{name}: SHA-256 {digest} is not pinned by any {AUDIT_LEVER} record in {chain.name}")


# -- the scheduler seam ----------------------------------------------------------------------------------------------
def restore_test_workflow(
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    audit_dir: Path = DEFAULT_AUDIT_DIR,
    catalog_for: Callable[[str], RestoreCatalog] = RestoreCatalog.for_fixture,
    config: RestoreConfig | None = None,
) -> Callable[[Unit], UnitResult]:
    """A workflow for ``core.scheduler.Scheduler``: one restore test for the unit's client and period.

    The unit's client is the only client touched. It proposes no action: a failed test is a line in the report and an
    evidence file for a person to read, not a lever to pull.
    """

    def run(unit: Unit) -> UnitResult:
        record = run_restore_test(
            catalog_for(unit.client),
            unit.as_of.date().isoformat(),
            out_dir=out_dir,
            audit_dir=audit_dir,
            config=config,
        )
        item = f" of {record.item_id}" if record.item_id else ""
        return UnitResult(report=f"restore test{item}: {record.result.upper()}. Evidence {record.sha256[:16]}.")

    return run
