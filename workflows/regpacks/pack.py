"""Regulatory evidence packs per client (B-52, specs/B-52.md; W-CMP-02/03/06; C-25, C-43, C-45).

One pack per client: a folder of Markdown pages and JSON, plus ``manifest.json`` (every file with its SHA-256) and a
``manifest.json.sha256`` sidecar in ``sha256sum`` format.

- One page per regime in the client record's ``regimes`` list (set by the client's compliance owner, never by this
  code, D6-12): ``hipaa`` (45 CFR 164.308 and 164.312), ``glba-ftc-safeguards`` (16 CFR 314.4) and ``sec-reg-s-p``
  (Regulation S-P as amended in 2024, every line hedged until checked against the rule text).
- Each mapping line ties a rule item to the governance-map row it cites (``BA-n``, ``GLBA-n`` in
  ``docs/map/05-governance.md``), the repo controls, and the client's synthetic findings that share a topic with it.
  An item with no finding says so; it never says the item is met.
- A BAA and vendor due-diligence tracker with a review state worked out from ``as_of``.

Dry run is the default: the manifest is built and returned, nothing is written. Only a lead scoped to the client may
build a pack; each call after the identity file is read is audited (``job.run``), refusals included. Dates come from
``as_of``, never the clock, so the same inputs give the same bytes. Every page carries LABEL at the top and foot.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from core.audit.chain import ActorKind, head_path_for, verify_chain
from core.audit.router import AuditRouter
from core.guard.classify import DataClass
from core.identity import IdentityConfigError, IdentityStore, Role, UnknownIdentity
from core.paths import REPO_ROOT
from workflows.access_review import audit_digest, canonical_bytes

DEFAULT_FIXTURES = REPO_ROOT / "fixtures" / "regpacks"
DEFAULT_GOVERNANCE_DOC = REPO_ROOT / "docs" / "map" / "05-governance.md"
DEFAULT_CONTROLS = REPO_ROOT / "map" / "controls.json"
DEFAULT_IDENTITIES = REPO_ROOT / "config" / "identities.json"
DEFAULT_OUT_DIR = REPO_ROOT / "build" / "regpacks"
DEFAULT_AUDIT_DIR = REPO_ROOT / ".tmp" / "demo" / "audit"
LEVER = "regpack.build"
VERSION = 1
KIND = "regulatory-pack"
MANIFEST = "manifest.json"
CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
GOVERNANCE_ID = re.compile(r"`((?:BA|GLBA)-\d+)`")
LABEL = "mapping for the client's compliance owner; not legal advice"
FIXTURE_LABEL = "fixture-based (synthetic data); not a certification"
LABELS = ["fixture-based", "not a certification", "not legal advice"]
NO_FINDING = "no finding supplied (not evidence that the item is met)"
HEDGE_NOTE = "HEDGED: not checked against the rule text; treat as a pointer, not a statement of the rule."
CLIENT_DATA_CLASS = DataClass.DC2  # client confidential: one client's findings and vendors; no people are named
SOON_DAYS = 60
NOTE = (
    "A mapping of this repo's synthetic findings and controls to the items of each regime the client's compliance "
    "owner has named. It is not legal advice, a gap assessment or a statement that any rule is met."
)
BASE_UNVERIFIED = [
    "Citations are copied from docs/map/05-governance.md, written from memory; none was checked against the eCFR or "
    "the Federal Register.",
    "Whether a regime applies to a client is for the client's compliance owner and counsel; the regimes in "
    "clients.json are synthetic stand-ins.",
    "Findings, vendor, contract and BAA rows are synthetic fixtures, not an assessment or document of any real client.",
    "The 365-day vendor review interval is a fixture setting, not a requirement of any rule.",
]
SP_UNVERIFIED = (
    "Regulation S-P as amended in 2024: the citations, scope and compliance dates are hedged until checked against "
    "the rule text."
)


class RegpackError(ValueError):
    """Bad input, a refused caller, or unusable fixtures; nothing was written except a refusal's audit record."""


class VerifyError(ValueError):
    """A pack does not match its manifest, or its manifest is not pinned in the audit chain."""


@dataclass(frozen=True)
class Pack:
    manifest: dict[str, Any]
    manifest_sha256: str
    target: Path
    root: Path | None  # the folder written; None for a dry run
    written: bool


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RegpackError(f"cannot read {Path(path).name}: {exc}") from None


def _lead_refusal(identities: IdentityStore, who: str, client: str) -> str | None:
    try:
        ident = identities.get(who)
    except UnknownIdentity:
        return f"unknown identity {who!r}"
    if ident.role is not Role.LEAD:
        return f"role {ident.role.value!r} cannot build a regulatory pack (needs lead)"
    if not ident.can_act_for(client):
        return f"{who} is not scoped to {client!r}"
    return None


def _actor_kind(identities: IdentityStore, who: str) -> ActorKind:
    if who not in identities:
        return "unknown"
    return "agent" if identities.get(who).role is Role.AGENT else "human"


# -- inputs --------------------------------------------------------------------------------------------------------
def _table(fixtures: Path, governance_doc: Path, controls: Path, client: str) -> dict[str, Any]:
    """The client's record, regimes, findings and vendors, with every cited id checked to exist."""
    clients = _load(fixtures / "clients.json").get("clients", {})
    record = clients.get(client)
    if not isinstance(record, dict):
        raise RegpackError(f"{client!r} is not in clients.json")
    regimes = record.get("regimes") or []
    if not regimes:
        raise RegpackError(f"{client}: no regimes set by the compliance owner; nothing to map")
    mappings = _load(fixtures / "mappings.json").get("regimes", {})
    unknown = [r for r in regimes if r not in mappings]
    if unknown:
        raise RegpackError(f"{client}: no mapping table for regime {unknown[0]!r}")
    try:
        doc = Path(governance_doc).read_text(encoding="utf-8")
    except OSError as exc:
        raise RegpackError(f"cannot read {Path(governance_doc).name}: {exc}") from None
    known_gov = set(GOVERNANCE_ID.findall(doc))
    known_controls = {c["id"] for c in _load(controls)}
    for regime in regimes:
        for item in mappings[regime]["items"]:
            if item["governance_id"] not in known_gov:
                raise RegpackError(f"{item['id']} cites {item['governance_id']}, which is not in the governance map")
            bad = [c for c in item["controls"] if c not in known_controls]
            if bad:
                raise RegpackError(f"{item['id']} cites {bad[0]}, which is not in map/controls.json")
    findings = [f for f in _load(fixtures / "findings.json")["findings"] if f["client"] == client]
    vendor_doc = _load(fixtures / "vendors.json")
    vendors = [v for v in vendor_doc["vendors"] if v["client"] == client]
    return {
        "name": str(record.get("display_name", client)),
        "regimes": list(regimes),
        "mappings": mappings,
        "findings": findings,
        "vendors": vendors,
        "interval": int(vendor_doc.get("review_interval_days", 365)),
    }


def _mapping(data: dict[str, Any]) -> dict[str, Any]:
    findings = data["findings"]
    used: set[str] = set()
    regimes: dict[str, Any] = {}
    for regime in data["regimes"]:
        table = data["mappings"][regime]
        lines = []
        for item in table["items"]:
            hits = sorted(f["id"] for f in findings if set(f["topics"]) & set(item["topics"]))
            used.update(hits)
            lines.append(
                {
                    "item": item["id"],
                    "cite": item["cite"],
                    "title": item["title"],
                    "governance_id": item["governance_id"],
                    "controls": sorted(item["controls"]),
                    "findings": hits,
                    "status": NO_FINDING if not hits else f"{len(hits)} finding(s) to review",
                    "hedged": bool(table["hedged"]),
                }
            )
        regimes[regime] = {"title": table["title"], "hedged": bool(table["hedged"]), "lines": lines}
    return {
        "findings": [{"id": f["id"], "title": f["title"]} for f in findings],
        "regimes": regimes,
        "unmapped_findings": [{"id": f["id"], "title": f["title"]} for f in findings if f["id"] not in used],
    }


def _vendors(data: dict[str, Any], as_of: date) -> list[dict[str, Any]]:
    rows = []
    hipaa = "hipaa" in data["regimes"]
    for v in sorted(data["vendors"], key=lambda r: r["id"]):
        due = date.fromisoformat(v["review_date"]) + timedelta(days=data["interval"])
        state = "overdue" if due < as_of else "due-soon" if (due - as_of).days <= SOON_DAYS else "current"
        flags = []
        if v["contract_status"] == "expired":
            flags.append("contract-expired")
        if v["contract_status"] == "pending-signature":
            flags.append("contract-unsigned")
        if hipaa and v["baa_status"] in ("pending", "none"):
            flags.append("baa-not-signed")
        rows.append({**v, "next_review_due": due.isoformat(), "review_state": state, "flags": flags})
    return rows


# -- pages ---------------------------------------------------------------------------------------------------------
def _page(title: str, body: list[str]) -> bytes:
    text = [f"# {title}", "", f"> {LABEL.capitalize()}. {FIXTURE_LABEL.capitalize()}.", "", *body, ""]
    text.append(f"_{LABEL.capitalize()}. {FIXTURE_LABEL.capitalize()}._")
    return ("\n".join(text) + "\n").encode("utf-8")


def _regime_page(name: str, regime: dict[str, Any], titles: dict[str, str]) -> bytes:
    body = [f"Client: {name}. Scope: {regime['title']}.", ""]
    if regime["hedged"]:
        body += [f"**{HEDGE_NOTE}** Every line stays hedged until checked against the rule text.", ""]
    body += [
        "| Item | Citation | Requirement | Governance map | Controls | Findings | Status |",
        "|---|---|---|---|---|---|---|",
    ]
    for line in regime["lines"]:
        findings = ", ".join(line["findings"]) or "none"
        status = line["status"] + (" HEDGED" if line["hedged"] else "")
        body.append(
            f"| {line['item']} | {line['cite']} | {line['title']} | {line['governance_id']} | "
            f"{', '.join(line['controls'])} | {findings} | {status} |"
        )
    cited = sorted({f for line in regime["lines"] for f in line["findings"]})
    if cited:
        body += ["", "Findings cited above:", *[f"- {f}: {titles[f]}" for f in cited]]
    return _page(regime["title"], body)


def _vendor_page(name: str, rows: list[dict[str, Any]], regimes: list[str], as_of: str) -> bytes:
    hipaa = "hipaa" in regimes
    cite = "BA-1, BA-3" if hipaa else "GLBA-3"
    what = "business associate agreements" if hipaa else "service-provider oversight"
    body = [
        f"Client: {name}. As of {as_of}. Tracks {what} (governance map {cite}; control C-43).",
        "",
        "| Vendor | Data classes | Contract | BAA | Last review | Next review due | State | Flags |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        body.append(
            f"| {r['id']} {r['name']} | {', '.join(r['data_classes'])} | {r['contract_status']} | {r['baa_status']} | "
            f"{r['review_date']} | {r['next_review_due']} | {r['review_state']} | {', '.join(r['flags']) or 'none'} |"
        )
    if not rows:
        body.append("| (no vendor rows in the fixture) | | | | | | | |")
    return _page("BAA and vendor due-diligence tracker", body)


def _manifest(
    client: str, as_of: str, by: str, regimes: list[str], files: dict[str, bytes], gaps: list[str]
) -> dict[str, Any]:
    unverified = list(BASE_UNVERIFIED)
    if "sec-reg-s-p" in regimes:
        unverified.append(SP_UNVERIFIED)
    return {
        "kind": KIND,
        "version": VERSION,
        "client": client,
        "as_of": as_of,
        "generated_by": by,
        "data_class": CLIENT_DATA_CLASS.label,
        "regimes": sorted(regimes),
        "labels": LABELS,
        "label": LABEL,
        "note": NOTE,
        "files": [{"path": p, "bytes": len(d), "sha256": _sha(d)} for p, d in sorted(files.items())],
        "gaps": gaps,
        "unverified": unverified,
    }


def _clear_previous(root: Path) -> None:
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


def build_pack(
    client: str,
    *,
    as_of: str,
    by: str,
    write: bool = False,
    out_dir: Path = DEFAULT_OUT_DIR,
    audit_dir: Path = DEFAULT_AUDIT_DIR,
    fixtures_dir: Path = DEFAULT_FIXTURES,
    governance_doc: Path = DEFAULT_GOVERNANCE_DOC,
    controls_path: Path = DEFAULT_CONTROLS,
    identities_path: Path = DEFAULT_IDENTITIES,
) -> Pack:
    """Build the pack for `client`. A dry run unless `write`; audited either way."""
    if not isinstance(client, str) or not CLIENT_ID.fullmatch(client):
        raise RegpackError(f"{client!r} is not a client id (not a client)")
    try:
        day = date.fromisoformat(as_of)
    except ValueError:
        raise RegpackError(f"as_of must be an ISO date (YYYY-MM-DD), got {as_of!r}") from None
    try:
        identities = IdentityStore.load(identities_path)
    except IdentityConfigError as exc:
        raise RegpackError(str(exc)) from None
    audit = AuditRouter(audit_dir)
    mode = "execute" if write else "dry-run"

    def record(result: dict[str, Any]) -> None:
        audit.append(
            agent=by,
            client=client,
            lever=LEVER,
            params={"as_of": as_of},
            mode=mode,  # type: ignore[arg-type]
            result=result,
            event="job.run",
            actor_kind=_actor_kind(identities, by),
            lever_version=VERSION,
        )

    refused = _lead_refusal(identities, by, client)
    files: dict[str, bytes] = {}
    regimes: list[str] = []
    gaps: list[str] = []
    if refused is None:
        try:
            data = _table(Path(fixtures_dir), Path(governance_doc), Path(controls_path), client)
            regimes = data["regimes"]
            mapping = _mapping(data)
            vendors = _vendors(data, day)
            titles = {f["id"]: f["title"] for f in mapping["findings"]}
            for regime in regimes:
                files[f"{regime}.md"] = _regime_page(data["name"], mapping["regimes"][regime], titles)
            files["vendors.md"] = _vendor_page(data["name"], vendors, regimes, as_of)
            files["vendors.json"] = canonical_bytes({"client": client, "as_of": as_of, "vendors": vendors})
            files["mapping.json"] = canonical_bytes({"client": client, "as_of": as_of, **mapping})
            if not vendors:
                gaps.append("no vendor rows for this client in the fixture")
            gaps += [f"{u['id']}: finding matches no item of the named regimes" for u in mapping["unmapped_findings"]]
        except RegpackError as exc:
            refused = str(exc)
    if refused is not None:
        record({"status": "denied", "reason": refused})
        raise RegpackError(refused)
    manifest = _manifest(client, as_of, by, regimes, files, gaps)
    manifest_bytes = canonical_bytes(manifest)
    digest = _sha(manifest_bytes)
    target = Path(out_dir) / as_of / client
    if write:
        target.mkdir(parents=True, exist_ok=True)
        _clear_previous(target)
        for rel, body in {**files, MANIFEST: manifest_bytes}.items():
            (target / rel).write_bytes(body)
        (target / (MANIFEST + ".sha256")).write_text(f"{digest}  {MANIFEST}\n", encoding="ascii", newline="\n")
    record({"status": "ok", "sha256": audit_digest(digest), "files": len(files), "gaps": len(gaps)})
    return Pack(manifest, digest, target, target if write else None, write)


# -- verification --------------------------------------------------------------------------------------------------
def verify_pack(root: Path, audit_dir: Path | None = None) -> str:
    """Re-hash a pack folder against its manifest and the manifest against its sidecar; return the manifest hash.

    With `audit_dir`, the manifest hash must also be pinned by a successful execute record of this workflow in the
    client's audit chain, and that chain must verify. Raises VerifyError on any mismatch."""
    root = Path(root)
    try:
        data = (root / MANIFEST).read_bytes()
        line = (root / (MANIFEST + ".sha256")).read_text(encoding="ascii").strip()
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
        raise VerifyError("manifest is not a regulatory-pack manifest in canonical form")
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
        _pinned(actual, str(manifest.get("client")), Path(audit_dir))
    return actual


def _pinned(digest: str, client: str, audit_dir: Path) -> None:
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
