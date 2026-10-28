"""SOC 2 evidence bundle and change records (B-51, specs/B-51.md; W-CMP-01/04/05/07; C-08, C-37, C-38, C-39).

A bundle is a folder of files plus ``manifest.json`` (every file with its SHA-256) and a ``manifest.json.sha256``
sidecar in ``sha256sum`` format. One bundle per period (``YYYY-MM``) per scope: a client, or the MSP.

- **Client bundle**: the client's audit-chain verification, an approvals and denials summary, the registry snapshot
  with lever versions, and copies of that client's B-49 access-review files. It names no other client.
- **MSP bundle**: the same from the MSP chain, the full registry, the MSP access review, and change records generated
  from a local ``git log --first-parent`` (merged pull requests). Reviewer, CI result and approval are not in a local
  git log, so they stay ``null``.

Dry run is the default: the manifest is built and returned, nothing is written. The bundle supports a human's
management assertion and makes none (W-CMP-07): there is no signature field and no claim of compliance. Dates come
from ``as_of`` and from the records themselves, never the wall clock, so the same inputs give the same manifest hash.
The bundle's own audit records are left out of every count so that running it does not change the next run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from core.audit.chain import ActorKind, head_path_for, verify_chain
from core.audit.router import MSP_LOG, AuditRouter
from core.guard.classify import DataClass
from core.identity import IdentityConfigError, IdentityStore, Role, UnknownIdentity
from core.levers.models import LeverDef
from core.levers.registry import Registry, RegistryError
from core.paths import REPO_ROOT
from workflows.access_review import VerifyError as ReviewVerifyError
from workflows.access_review import audit_digest, canonical_bytes, quarter_of, sidecar_for
from workflows.access_review import verify as verify_review

DEFAULT_IDENTITIES = REPO_ROOT / "config" / "identities.json"
DEFAULT_REGISTRY = REPO_ROOT / "levers" / "registry.json"
DEFAULT_OUT_DIR = REPO_ROOT / "build" / "evidence"
DEFAULT_REVIEW_DIR = REPO_ROOT / "build" / "access-review"
# The lever CLI's audit folder, the same default as the access review (B-49).
DEFAULT_AUDIT_DIR = REPO_ROOT / ".tmp" / "demo" / "audit"
LEVER = "evidence.bundle"
VERSION = 1
KIND = "evidence-bundle"
MANIFEST = "manifest.json"
PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
LABELS = ["fixture-based", "not a certification", "not an attestation"]
NOTE = (
    "Evidence collected from this repo's synthetic fixtures and local files. It supports review by a person "
    "and by an assessor; it is not a SOC 2 report."
)
ASSERTION_NOTE = (
    "This bundle supports a human's management assertion and makes none. Whether to assert, and the signing, "
    "are a person's decision outside this workflow."
)
OUTCOMES = ("approved", "rejected", "denied", "executed", "dry_run", "other")
GUARDRAIL_PATHS = ("docs/BLUEPRINT.md",)
GUARDRAIL_PREFIXES = ("scripts/", ".github/")
CLIENT_DATA_CLASS = DataClass.DC3  # copies of a client's access review name people in the client's tenant
MSP_DATA_CLASS = DataClass.DC1
GIT_FIELDS = "%H%x1f%P%x1f%cI%x1f%an%x1f%s%x1e"
PR_MERGE = re.compile(r"^Merge pull request #(\d+)\b")
PR_SQUASH = re.compile(r"\(#(\d+)\)\s*$")
ROADMAP_ID = re.compile(r"\bB-\d{2,3}\b")
TITLE_MAX = 200


class EvidenceError(ValueError):
    """Bad input, a refused caller, or unreadable sources; nothing was written except a refusal's audit record."""


class VerifyError(ValueError):
    """A bundle does not match its manifest, or its manifest is not pinned in the audit chain."""


@dataclass(frozen=True)
class Bundle:
    manifest: dict[str, Any]
    manifest_sha256: str
    target: Path
    root: Path | None  # the folder written; None for a dry run
    written: bool


# -- small helpers -------------------------------------------------------------------------------------------------
def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _plain(value: object) -> Any:
    return value.value if isinstance(value, Enum) else value


def _check_inputs(client: str | None, period: str, as_of: str) -> None:
    if client is not None and (not isinstance(client, str) or not CLIENT_ID.fullmatch(client)):
        raise EvidenceError(f"{client!r} is not a client id")
    if not isinstance(period, str) or not PERIOD.fullmatch(period):
        raise EvidenceError(f"period must be YYYY-MM, got {period!r}")
    try:
        day = date.fromisoformat(as_of)
    except ValueError:
        raise EvidenceError(f"as_of must be an ISO date (YYYY-MM-DD), got {as_of!r}") from None
    if day < date.fromisoformat(f"{period}-01"):
        raise EvidenceError(f"as_of {as_of} is before the period {period}")


def _lead_refusal(identities: IdentityStore, who: str, clients: tuple[str, ...]) -> str | None:
    try:
        ident = identities.get(who)
    except UnknownIdentity:
        return f"unknown identity {who!r}"
    if ident.role is not Role.LEAD:
        return f"role {ident.role.value!r} cannot build an evidence bundle (needs lead)"
    missing = [c for c in clients if not ident.can_act_for(c)]
    if missing:
        return f"{who} is not scoped to {missing[0]!r}" if len(clients) == 1 else f"{who} is not scoped to every client"
    return None


def _actor_kind(identities: IdentityStore, who: str) -> ActorKind:
    if who not in identities:
        return "unknown"
    return "agent" if identities.get(who).role is Role.AGENT else "human"


# -- audit chain evidence ------------------------------------------------------------------------------------------
def _in_period(chain: Path, period: str) -> list[dict[str, Any]]:
    """The chain's records dated in `period`, minus this workflow's own records (so a run never changes the next)."""
    found: list[dict[str, Any]] = []
    for line in chain.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue  # verify_chain reports it; the summary just skips what it cannot read
        if isinstance(record, dict) and str(record.get("ts", ""))[:7] == period and record.get("lever") != LEVER:
            found.append(record)
    return found


def _audit_verify(chain: Path, period: str) -> dict[str, Any]:
    out: dict[str, Any] = {"chain": chain.name, "present": chain.is_file()}
    if not out["present"]:
        return {**out, "ok": None, "broken_seq": None, "reason": "no chain file", "head_pin_present": False}
    head = head_path_for(chain)
    result = verify_chain(chain, head if head.exists() else None)
    records = _in_period(chain, period)
    seqs = [r.get("seq") for r in records]
    return {
        **out,
        "ok": result.ok,
        "broken_seq": result.broken_seq,
        "reason": result.reason.replace(str(head), head.name),
        "head_pin_present": head.exists(),
        "period": {
            "records": len(records),
            "first_seq": seqs[0] if seqs else None,
            "last_seq": seqs[-1] if seqs else None,
            "last_hash": records[-1].get("hash") if records else None,
        },
    }


def _approvals(chain: Path, period: str) -> dict[str, Any]:
    totals = dict.fromkeys(OUTCOMES, 0)
    by_lever: dict[str, dict[str, int]] = {}
    kinds = {"agent": 0, "human": 0, "unknown": 0}
    approvers: set[str] = set()
    for record in _in_period(chain, period) if chain.is_file() else []:
        result = record.get("result")
        status = result.get("status") if isinstance(result, dict) else None
        mode = record.get("mode")
        if status == "denied":
            outcome = "denied"
        elif mode == "approve":
            outcome = "approved"
        elif mode == "reject":
            outcome = "rejected"
        elif mode == "execute":
            outcome = "executed"
        elif mode == "dry-run":
            outcome = "dry_run"
        else:
            outcome = "other"
        totals[outcome] += 1
        by_lever.setdefault(str(record.get("lever")), dict.fromkeys(OUTCOMES, 0))[outcome] += 1
        kind = record.get("actor_kind")
        kinds[kind if kind in kinds else "unknown"] += 1
        if isinstance(record.get("approver"), str):
            approvers.add(record["approver"])
    return {
        "chain": chain.name,
        "period": period,
        "totals": totals,
        "by_lever": dict(sorted(by_lever.items())),
        "by_actor_kind": kinds,
        "approvers": sorted(approvers),
        "note": "Counts of audit records dated in the period. No parameters or free text are copied.",
    }


# -- registry snapshot ---------------------------------------------------------------------------------------------
def _registry_snapshot(registry_path: Path, client: str | None) -> dict[str, Any]:
    try:
        registry = Registry.load(registry_path)
    except (RegistryError, OSError, ValueError) as exc:
        raise EvidenceError(f"registry cannot be loaded: {exc}") from None
    levers = []
    for name in sorted(registry.names()):
        lever: LeverDef | None = registry.get(name)
        if lever is None or (client is not None and not lever.allows_client(client)):
            continue
        levers.append(
            {
                "name": lever.name,
                "lever_version": lever.lever_version,
                "class": lever.lever_class,
                "risk_class": _plain(lever.risk_class),
                "required_role": _plain(lever.required_role),
                "approval": lever.approval,
                "reversibility": _plain(lever.reversibility),
            }
        )
    folder = registry_path.parent / "registry.d"
    fragments = sorted(folder.glob("*.json")) if folder.is_dir() else []
    return {
        "registry": registry_path.name,
        "registry_sha256": _sha(registry_path.read_bytes()),
        "fragments": [{"name": f.name, "sha256": _sha(f.read_bytes())} for f in fragments],
        "scope": client or "msp",
        "levers": levers,
    }


# -- access reviews (B-49) -----------------------------------------------------------------------------------------
def _review_files(review_dir: Path, period: str, scope: str) -> tuple[dict[str, tuple[bytes, bool | None]], list[str]]:
    """Copies of the scope's B-49 files for the quarter: {bundle path: (bytes, verified; None for a sidecar)}."""
    quarter = quarter_of(f"{period}-01")
    folder = Path(review_dir) / quarter
    found: dict[str, tuple[bytes, bool | None]] = {}
    for stem in (f"{scope}.json", f"{scope}.decided.json"):
        path = folder / stem
        if not path.is_file():
            continue
        try:
            verify_review(path)
            verified = True
        except ReviewVerifyError:
            verified = False
        found[f"access-review/{stem}"] = (path.read_bytes(), verified)
        side = sidecar_for(path)
        if side.is_file():
            found[f"access-review/{side.name}"] = (side.read_bytes(), None)
    gaps = []
    if f"access-review/{scope}.json" not in found:
        gaps.append(f"access review missing for {quarter}")
    elif f"access-review/{scope}.decided.json" not in found:
        gaps.append(f"access review not yet decided for {quarter}")
    return found, gaps


# -- change records from a local git log (C-37) --------------------------------------------------------------------
def _git(repo: Path, *args: str) -> str:
    git = shutil.which("git")
    if git is None:
        raise EvidenceError("git is not installed")
    if not Path(repo).is_dir():
        raise EvidenceError("the git repository folder does not exist")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    done = subprocess.run(  # noqa: S603  fixed argument list, no shell, read-only subcommands
        [git, "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", env=env, check=False
    )
    if done.returncode != 0:
        raise EvidenceError("git log failed (is this a git repository?)")
    return done.stdout


def _clean(text: str) -> str:
    return "".join(ch for ch in text if ch.isprintable())[:TITLE_MAX]


def change_records(repo: Path, period: str) -> list[dict[str, Any]]:
    """Change records for merges dated in `period` on the first-parent history of HEAD, oldest first.

    A change is a merge commit (two or more parents) or a commit whose title ends in ``(#N)`` (squash merge).
    Reviewer, CI result and approval are not in a local git log: they are ``null``, never guessed. Raises
    EvidenceError when git or the repository cannot be read."""
    if not PERIOD.fullmatch(period):
        raise EvidenceError(f"period must be YYYY-MM, got {period!r}")
    out = _git(repo, "log", "--first-parent", f"--format={GIT_FIELDS}")
    records: list[dict[str, Any]] = []
    for chunk in out.split("\x1e"):
        fields = chunk.strip("\n").split("\x1f")
        if len(fields) != 5:
            continue
        commit, parents_raw, committed, author, subject = fields
        parents = parents_raw.split()
        merged = datetime.fromisoformat(committed).astimezone(UTC)
        if merged.strftime("%Y-%m") != period:
            continue
        pr_match = PR_MERGE.match(subject) or PR_SQUASH.search(subject)
        if len(parents) < 2 and pr_match is None:
            continue
        paths = (
            sorted(p for p in _git(repo, "diff", "--name-only", "-z", parents[0], commit).split("\0") if p)
            if parents
            else []
        )
        records.append(
            {
                "record_id": f"CR-{commit[:12]}",
                "kind": "change-record",
                "pr": int(pr_match.group(1)) if pr_match else None,
                "title": _clean(subject),
                "commit": commit,
                "parents": parents,
                "merged_on": merged.date().isoformat(),
                "author": _clean(author),
                "changed_paths": paths,
                "roadmap_ids": sorted(set(ROADMAP_ID.findall(subject))),
                "touches_guardrails": any(p in GUARDRAIL_PATHS or p.startswith(GUARDRAIL_PREFIXES) for p in paths),
                "reviewer": None,
                "ci_result": None,
                "approval": None,
                "evidence": "not in local git",
            }
        )
    return sorted(records, key=lambda r: (r["merged_on"], r["commit"]))


def _change_files(git_repo: Path | None, period: str) -> tuple[dict[str, bytes], list[str]]:
    index: dict[str, Any] = {
        "kind": "merged-prs",
        "period": period,
        "source": "local git log --first-parent",
        "available": False,
        "reason": None,
        "merged": [],
    }
    files: dict[str, bytes] = {}
    gaps: list[str] = []
    try:
        if git_repo is None:
            raise EvidenceError("no git repository was given")
        records = change_records(git_repo, period)
        index["available"] = True
        for record in records:
            files[f"change-records/{record['record_id']}.json"] = canonical_bytes(record)
            index["merged"].append({k: record[k] for k in ("pr", "title", "commit", "merged_on", "record_id")})
    except EvidenceError as exc:
        index["reason"] = str(exc)
        gaps.append("merged PR list unavailable")
    files["merged-prs.json"] = canonical_bytes(index)
    return files, gaps


# -- the bundle ----------------------------------------------------------------------------------------------------
def _collect(
    client: str | None,
    period: str,
    audit: AuditRouter,
    registry_path: Path,
    review_dir: Path,
    git_repo: Path | None,
) -> tuple[dict[str, bytes], dict[str, bool], list[str], dict[str, Any]]:
    chain = audit.path_for(client)
    verify_out = _audit_verify(chain, period)
    files: dict[str, bytes] = {
        "audit-verify.json": canonical_bytes(verify_out),
        "approvals.json": canonical_bytes(_approvals(chain, period)),
        "registry.json": canonical_bytes(_registry_snapshot(registry_path, client)),
    }
    gaps: list[str] = []
    if not verify_out["present"]:
        gaps.append("audit chain missing")
    elif not verify_out["head_pin_present"]:
        gaps.append("audit head pin missing")
    reviews, review_gaps = _review_files(review_dir, period, client or MSP_LOG)
    verified: dict[str, bool] = {}
    for path, (data, ok) in reviews.items():
        files[path] = data
        if ok is not None:
            verified[path] = ok
    gaps += review_gaps
    if client is None:
        change_files, change_gaps = _change_files(git_repo, period)
        files.update(change_files)
        gaps += change_gaps
    return files, verified, sorted(gaps), verify_out


def _manifest(
    client: str | None,
    period: str,
    as_of: str,
    by: str,
    files: dict[str, bytes],
    verified: dict[str, bool],
    gaps: list[str],
    verify_out: dict[str, Any],
) -> dict[str, Any]:
    entries = []
    for path in sorted(files):
        entry: dict[str, Any] = {"path": path, "bytes": len(files[path]), "sha256": _sha(files[path])}
        if path in verified:
            entry["verified"] = verified[path]
        entries.append(entry)
    return {
        "kind": KIND,
        "version": VERSION,
        "scope": "client" if client else "msp",
        "client": client,
        "period": period,
        "as_of": as_of,
        "generated_by": by,
        "data_class": (CLIENT_DATA_CLASS if client else MSP_DATA_CLASS).label,
        "labels": LABELS,
        "note": NOTE,
        "checks": {
            "audit_chain_ok": verify_out["ok"],
            "access_reviews_verified": all(verified.values()) if verified else None,
        },
        "gaps": gaps,
        "management_assertion": {"status": "not made", "asserted_by": None, "note": ASSERTION_NOTE},
        "files": entries,
    }


def _clear_previous(root: Path) -> None:
    """Remove the files a previous bundle in `root` listed, so a rerun leaves no stale file behind."""
    manifest = root / MANIFEST
    if not manifest.is_file():
        return
    try:
        listed = [e["path"] for e in json.loads(manifest.read_bytes())["files"]]
    except (ValueError, KeyError, TypeError):
        listed = []
    for rel in [*listed, MANIFEST, MANIFEST + ".sha256"]:
        target = root / str(rel)
        if root.resolve() in target.resolve().parents and target.is_file():
            target.unlink()


def build_bundle(
    client: str | None,
    *,
    period: str,
    as_of: str,
    by: str,
    write: bool = False,
    out_dir: Path = DEFAULT_OUT_DIR,
    audit_dir: Path = DEFAULT_AUDIT_DIR,
    access_review_dir: Path = DEFAULT_REVIEW_DIR,
    registry_path: Path = DEFAULT_REGISTRY,
    identities_path: Path = DEFAULT_IDENTITIES,
    git_repo: Path | None = REPO_ROOT,
) -> Bundle:
    """Build the bundle for `client` (the MSP when None). A dry run unless `write`; audited either way."""
    _check_inputs(client, period, as_of)
    audit = AuditRouter(audit_dir)
    try:
        identities = IdentityStore.load(identities_path)
    except IdentityConfigError as exc:
        raise EvidenceError(str(exc)) from None
    scope = (client,) if client is not None else tuple(sorted({c for i in identities for c in i.clients}))
    params = {"scope": "client" if client else "msp", "period": period, "as_of": as_of}

    def record(mode: str, result: dict[str, Any]) -> None:
        audit.append(
            agent=by,
            client=client,
            lever=LEVER,
            params=params,
            mode=mode,  # type: ignore[arg-type]
            result=result,
            event="job.run",
            actor_kind=_actor_kind(identities, by),
            lever_version=VERSION,
        )

    refused = _lead_refusal(identities, by, scope)
    files: dict[str, bytes] = {}
    if refused is None:
        try:
            files, verified, gaps, verify_out = _collect(
                client, period, audit, Path(registry_path), Path(access_review_dir), git_repo
            )
        except EvidenceError as exc:
            refused = str(exc)
    if refused is not None:
        record("execute" if write else "dry-run", {"status": "denied", "reason": refused})
        raise EvidenceError(refused)
    manifest = _manifest(client, period, as_of, by, files, verified, gaps, verify_out)
    manifest_bytes = canonical_bytes(manifest)
    digest = _sha(manifest_bytes)
    target = Path(out_dir) / period / (client or MSP_LOG)
    if write:
        target.mkdir(parents=True, exist_ok=True)
        _clear_previous(target)
        for rel, data in {**files, MANIFEST: manifest_bytes}.items():
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        (target / (MANIFEST + ".sha256")).write_text(f"{digest}  {MANIFEST}\n", encoding="ascii", newline="\n")
    record(
        "execute" if write else "dry-run",
        {
            "status": "ok",
            "sha256": audit_digest(digest),
            "files": len(files),
            "gaps": len(gaps),
            "audit_chain_ok": verify_out["ok"],
        },
    )
    return Bundle(manifest, digest, target, target if write else None, write)


# -- verification --------------------------------------------------------------------------------------------------
def verify_bundle(root: Path, audit_dir: Path | None = None) -> str:
    """Re-hash a bundle folder against its manifest and the manifest against its sidecar; return the manifest hash.

    With `audit_dir`, the manifest hash must also be pinned by a successful execute record of this workflow in the
    scope's audit chain, and that chain must verify. Raises VerifyError on any mismatch."""
    root = Path(root)
    manifest_path, side = root / MANIFEST, root / (MANIFEST + ".sha256")
    try:
        data = manifest_path.read_bytes()
        line = side.read_text(encoding="ascii").strip()
    except (OSError, ValueError):
        raise VerifyError(f"{root.name}: manifest or its sidecar cannot be read") from None
    expected, _, name = line.partition("  ")
    actual = _sha(data)
    if name != MANIFEST or actual != expected:
        raise VerifyError(f"{root.name}: manifest SHA-256 {actual} does not match the sidecar ({expected or 'empty'})")
    try:
        manifest = json.loads(data)
    except ValueError:
        raise VerifyError("manifest is not valid JSON") from None
    if not isinstance(manifest, dict) or manifest.get("kind") != KIND or canonical_bytes(manifest) != data:
        raise VerifyError("manifest is not an evidence manifest in canonical form")
    listed = set()
    for entry in manifest.get("files", []):
        rel = str(entry.get("path"))
        pure = Path(rel)
        if pure.is_absolute() or ".." in pure.parts or rel in (MANIFEST, MANIFEST + ".sha256"):
            raise VerifyError(f"manifest lists an unsafe path {rel!r}")
        listed.add(rel)
        try:
            body = (root / rel).read_bytes()
        except OSError:
            raise VerifyError(f"{rel}: listed in the manifest but missing") from None
        if _sha(body) != entry.get("sha256") or len(body) != entry.get("bytes"):
            raise VerifyError(f"{rel}: does not match the manifest")
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel not in listed and rel not in (MANIFEST, MANIFEST + ".sha256"):
            raise VerifyError(f"{rel}: in the folder but not in the manifest")
    if audit_dir is not None:
        _pinned(actual, manifest.get("client"), Path(audit_dir))
    return actual


def _pinned(digest: str, client: str | None, audit_dir: Path) -> None:
    chain = AuditRouter(audit_dir).path_for(client)
    if not chain.is_file():
        raise VerifyError(f"no audit chain at {chain.name}")
    head = head_path_for(chain)
    result = verify_chain(chain, head if head.exists() else None)
    if not result.ok:
        raise VerifyError(f"audit chain {chain.name} does not verify at seq {result.broken_seq}")
    for line in chain.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        res = rec.get("result") or {}
        if (
            rec.get("lever") == LEVER
            and rec.get("mode") == "execute"
            and res.get("status") == "ok"
            and "".join(str(res.get("sha256")).split()) == digest
        ):
            return
    raise VerifyError(f"manifest SHA-256 {digest} is not pinned by any {LEVER} execute record in {chain.name}")
