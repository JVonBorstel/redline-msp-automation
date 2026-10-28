"""Client documentation upkeep (B-59): compare a client's documentation with observed state, propose draft fixes.

Inputs, all read-only: the client's KB scope (``fixtures/kb/<client>/manifest.json``, B-56), the documentation fixture
(``workflows/doc_upkeep/data/<client>.json``: review dates and structured claims per page) and observed state through
the RMM, PSA and Graph mock adapters (devices, contacts, licence SKUs). Output: findings of three kinds, each with a
draft proposal for a person. Nothing is written to a documentation system and no lever is invoked.

* stale: the page was last reviewed too long ago, or it claims something observed state no longer shows;
* missing: observed state or a required topic that no page covers, or a page with no review record;
* contradictory: a page disagrees with observed state, with another page, or with its own client (it names another
  client), or the observed state disagrees with itself (two RMM records for one hostname).

Page text is untrusted: it is searched for client names and screened for instruction-like text (flagged, never
followed) but never copied into a finding. Vault entries are skipped by origin and tag without reading their text.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from adapters.base import AdapterError, AdapterResult
from adapters.binding import BoundBinding
from adapters.graph.mock import GraphMock
from adapters.psa.mock import DEFAULT_PSA_DIR, PsaMock
from adapters.rmm.mock import DEFAULT_RMM_DIR, RmmMock
from core.audit.router import valid_client_id
from core.guard.detect import detect_injection
from core.levers.tenant import DEFAULT_TENANT_DIR
from core.paths import REPO_ROOT
from rag.ingest.corpus import KbScope, load_kb
from rag.ingest.models import IngestError

DEFAULT_KB_DIR = REPO_ROOT / "fixtures" / "kb"
DEFAULT_DATA_DIR = REPO_ROOT / "workflows" / "doc_upkeep" / "data"
DEFAULT_OUT_DIR = REPO_ROOT / "build" / "doc-upkeep"

DORMANT_DAYS = 60  # an offline device unseen this long counts as out of service
REVIEW_DAY_UNIT = 30  # review_months * 30 days
KINDS = ("stale", "missing", "contradictory")
_SAFE = re.compile(r"[A-Za-z0-9 ._'@:/-]{1,80}")
_ATTR_LABEL = {"category": "device category", "title": "job title", "seats": "licensed seats"}


class DocUpkeepError(ValueError):
    """The request or an input is unusable. Nothing is reported."""


@dataclass(frozen=True, slots=True)
class Proposal:
    """A draft change for a person to review. ``status`` is always ``draft``; nothing applies it."""

    action: str
    page: str | None
    draft: str
    status: str = "draft"


@dataclass(frozen=True, slots=True)
class Finding:
    id: str
    client: str
    kind: str
    page: str | None
    subject: str
    detail: str
    sources: tuple[str, ...]
    proposal: Proposal

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "page": self.page,
            "subject": self.subject,
            "detail": self.detail,
            "sources": list(self.sources),
            "proposal": {
                "action": self.proposal.action,
                "page": self.proposal.page,
                "draft": self.proposal.draft,
                "status": self.proposal.status,
            },
        }


@dataclass(frozen=True, slots=True)
class Report:
    client: str
    as_of: str
    pages_checked: int
    vault_skipped: int
    flagged_pages: tuple[str, ...]
    findings: tuple[Finding, ...]
    read_only: bool = True
    note: str = "Fixture-based: synthetic KB, documentation fixture and mock adapter state. Proposals are drafts."

    @property
    def summary(self) -> dict[str, int]:
        return {kind: sum(f.kind == kind for f in self.findings) for kind in KINDS}

    def to_dict(self) -> dict[str, Any]:
        return {
            "client": self.client,
            "as_of": self.as_of,
            "read_only": self.read_only,
            "note": self.note,
            "pages_checked": self.pages_checked,
            "vault_skipped": self.vault_skipped,
            "flagged_pages": list(self.flagged_pages),
            "summary": self.summary,
            "findings": [f.to_dict() for f in self.findings],
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()


def _canonical(body: Mapping[str, Any]) -> bytes:
    return (json.dumps(body, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def _safe(value: object) -> str:
    text = str(value)
    return text if _SAFE.fullmatch(text) else "[value withheld]"


def _date(value: object, what: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise DocUpkeepError(f"{what} is not a YYYY-MM-DD date") from exc


def _result[T](result: AdapterResult[T], what: str) -> T:
    if not result.ok or result.data is None:
        raise DocUpkeepError(f"{what} unavailable: {result.reason}")
    return result.data


# ---------------------------------------------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------------------------------------------


@dataclass
class _Observed:
    devices: dict[str, dict[str, Any]] = field(default_factory=dict)  # casefolded hostname -> latest record
    duplicates: dict[str, int] = field(default_factory=dict)  # hostname -> records
    contacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    skus: dict[str, int] = field(default_factory=dict)


def _observe(client: str, rmm_dir: Path, psa_dir: Path, tenant_dir: Path) -> _Observed:
    seen = _Observed()
    try:
        rmm = RmmMock.for_fixture(client, rmm_dir)
        psa_file = json.loads((Path(psa_dir) / f"{client}.json").read_text(encoding="utf-8"))
        psa = PsaMock(client, BoundBinding(client, "psa", "mock", str(psa_file["company"]["id"])), psa_dir)
        graph = GraphMock(
            client, BoundBinding(client, "m365", "mock", "doc-upkeep-read-only", f"client-{client}-m365"), tenant_dir
        )
    except (AdapterError, OSError, ValueError, KeyError, TypeError) as exc:
        raise DocUpkeepError(f"observed state for {client} is not available ({type(exc).__name__})") from exc

    groups: dict[str, list[dict[str, Any]]] = {}
    for device in _result(rmm.list_devices(), "RMM devices"):
        if not device.get("deleted") and device.get("hostname"):
            groups.setdefault(str(device["hostname"]), []).append(device)
    for host, rows in groups.items():
        seen.devices[host.casefold()] = max(rows, key=lambda r: str(r.get("lastSeen", "")))
        if len(rows) > 1:
            seen.duplicates[host] = len(rows)
    for contact in _result(psa.list_contacts(), "PSA contacts"):
        if contact.get("isActive"):
            seen.contacts[f"{contact.get('firstName', '')} {contact.get('lastName', '')}".strip().casefold()] = contact
    licenses = _result(graph.family_state("licenses"), "licence state")
    for sku in licenses.get("skus", []):
        seen.skus[str(sku["skuPartNumber"]).casefold()] = int(sku["prepaidUnits"]["enabled"])
    return seen


def _documentation(client: str, data_dir: Path) -> dict[str, Any]:
    try:
        body = json.loads((Path(data_dir) / f"{client}.json").read_text(encoding="utf-8"))
        if body["client"] != client or not isinstance(body["pages"], list):
            raise DocUpkeepError("documentation fixture does not belong to this client")
        _date(body["as_of"], "documentation fixture as_of")
        int(body["review_months"])
        return dict(body)
    except DocUpkeepError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DocUpkeepError(f"no usable documentation fixture for {client} ({type(exc).__name__})") from exc


def _scope(client: str, kb_dir: Path) -> KbScope:
    try:
        scopes = load_kb(kb_dir)
    except (IngestError, OSError) as exc:
        raise DocUpkeepError("the KB fixtures are not readable") from exc
    for scope in scopes:
        if scope.name == client:
            return scope
    raise DocUpkeepError(f"no KB scope for {client}")


# ---------------------------------------------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------------------------------------------


def _observed_attr(kind: str, key: str, attr: str, seen: _Observed) -> Any:
    if kind == "device":
        return seen.devices[key].get("deviceType", {}).get("category")
    if kind == "contact":
        return seen.contacts[key].get("title")
    return seen.skus[key] if attr == "seats" else None


def _exists(kind: str, key: str, seen: _Observed) -> bool:
    known: dict[str, Mapping[str, Any]] = {"device": seen.devices, "contact": seen.contacts, "license": seen.skus}
    return key in known[kind]


def _dormant(record: Mapping[str, Any], today: date) -> bool:
    if record.get("online"):
        return False
    try:
        return (today - date.fromisoformat(str(record.get("lastSeen", ""))[:10])).days >= DORMANT_DAYS
    except ValueError:
        return False


def build_report(
    client: str,
    *,
    as_of: str | None = None,
    kb_dir: Path = DEFAULT_KB_DIR,
    data_dir: Path = DEFAULT_DATA_DIR,
    rmm_dir: Path = DEFAULT_RMM_DIR,
    psa_dir: Path = DEFAULT_PSA_DIR,
    tenant_dir: Path = DEFAULT_TENANT_DIR,
) -> Report:
    """Compare the client's documentation with observed state. Read-only; deterministic for one ``as_of``."""
    if not valid_client_id(client):
        raise DocUpkeepError("not a usable client id")
    docs = _documentation(client, data_dir)
    today = _date(as_of if as_of is not None else docs["as_of"], "as_of")
    scope = _scope(client, kb_dir)
    seen = _observe(client, rmm_dir, psa_dir, tenant_dir)
    limit_days = int(docs["review_months"]) * REVIEW_DAY_UNIT
    metas = {str(p["article_id"]): p for p in docs["pages"]}
    rows: list[tuple[str, str | None, str, str, tuple[str, ...], Proposal]] = []

    def add(
        kind: str, page: str | None, subject: str, detail: str, sources: tuple[str, ...], proposal: Proposal
    ) -> None:
        rows.append((kind, page, subject, detail, sources, proposal))

    others = [s.name for s in scope_list(kb_dir) if s.client is not None and s.name != client]
    vault = 0
    flagged: list[str] = []
    topics: set[str] = set()
    pages: list[str] = []
    claims: dict[tuple[str, str], list[tuple[str, dict[str, Any], str]]] = {}

    for source in scope.sources:
        if source.origin.startswith("vault/") or "credential-vault" in source.tags:
            vault += 1
            continue
        page = source.article_id
        pages.append(page)
        topics.update(source.tags)
        text = f"{source.title}\n{source.text}"
        if detect_injection(text).flagged:
            flagged.append(page)
        for other in others:
            if re.search(rf"\b{re.escape(other)}\b|\b{re.escape(other.replace('-', ' '))}\b", text, re.IGNORECASE):
                add(
                    "contradictory",
                    page,
                    "ownership",
                    f"{page} is filed under {client} but names another client",
                    (f"doc:{page}", "kb:fixtures"),
                    Proposal(
                        "fix-ownership",
                        page,
                        f"Check whether {page} belongs to another client; move it or drop the cross-client reference.",
                    ),
                )
                break
        meta = metas.get(page)
        reviewed = None if meta is None else meta.get("last_reviewed")
        if reviewed is None:
            add(
                "missing",
                page,
                "review date",
                f"{page} has no review date on record",
                (f"doc:{page}",),
                Proposal("re-review", page, f"Review {page} against current state and record the date."),
            )
        else:
            age = (today - _date(reviewed, f"{page} last_reviewed")).days
            if age < 0:
                raise DocUpkeepError(f"{page} last_reviewed is after as_of")
            if age > limit_days:
                add(
                    "stale",
                    page,
                    "review date",
                    f"{page} was last reviewed {age} days before {today} (limit {limit_days})",
                    (f"doc:{page}",),
                    Proposal("re-review", page, f"Re-review {page} (last reviewed {reviewed}) and update the date."),
                )
        for claim in [] if meta is None else meta.get("claims", []):
            kind, name = str(claim["kind"]), str(claim["key"])
            key = name.casefold()
            claims.setdefault((kind, key), []).append((page, dict(claim.get("attrs", {})), name))
            src = (
                f"doc:{page}",
                {"device": "rmm:devices", "contact": "psa:contacts", "license": "graph:licenses"}[kind],
            )
            if not _exists(kind, key, seen):
                add(
                    "stale",
                    page,
                    name,
                    f"{page} documents {kind} {_safe(name)}, which observed state no longer shows",
                    src,
                    Proposal(
                        "remove-claim",
                        page,
                        f"Remove or update the {kind} entry for {_safe(name)} on {page}; it is not in observed state.",
                    ),
                )
                continue
            if kind == "device" and _dormant(seen.devices[key], today):
                since = str(seen.devices[key].get("lastSeen"))[:10]
                add(
                    "stale",
                    page,
                    name,
                    f"{page} documents device {_safe(name)} as in service; offline since {since}",
                    src,
                    Proposal(
                        "remove-claim",
                        page,
                        f"Mark {_safe(name)} retired or remove it from {page}; unseen for {DORMANT_DAYS}+ days.",
                    ),
                )
            for attr, said in dict(claim.get("attrs", {})).items():
                actual = _observed_attr(kind, key, attr, seen)
                if actual is not None and actual != said:
                    label = _ATTR_LABEL.get(attr, attr)
                    add(
                        "contradictory",
                        page,
                        name,
                        f"{page} gives {label} of {_safe(name)} as {_safe(said)}; observed state says {_safe(actual)}",
                        src,
                        Proposal(
                            "revise-claim",
                            page,
                            f"On {page}, change {label} of {_safe(name)} from {_safe(said)} to {_safe(actual)}.",
                        ),
                    )

    for (_kind, _key), entries in sorted(claims.items()):
        for attr in sorted({a for _, attrs, _ in entries for a in attrs}):
            values = {str(attrs[attr]): page for page, attrs, _ in entries if attr in attrs}
            if len(values) > 1:
                first, second = entries[0], entries[1]
                add(
                    "contradictory",
                    first[0],
                    first[2],
                    f"{first[0]} and {second[0]} give different {_ATTR_LABEL.get(attr, attr)} for {_safe(first[2])}",
                    (f"doc:{first[0]}", f"doc:{second[0]}"),
                    Proposal(
                        "revise-claim",
                        first[0],
                        f"Make {first[0]} and {second[0]} agree on {_ATTR_LABEL.get(attr, attr)} of {_safe(first[2])}.",
                    ),
                )

    for host, count in sorted(seen.duplicates.items()):
        add(
            "contradictory",
            None,
            host,
            f"the RMM holds {count} records for {_safe(host)}",
            ("rmm:devices",),
            Proposal("re-review", None, f"Reconcile the {count} RMM records for {_safe(host)} before documenting it."),
        )
    for page in sorted(set(metas) - {s.article_id for s in scope.sources}):
        add(
            "missing",
            None,
            page,
            "the documentation record names a page the KB does not hold",
            (f"doc:{page}", "kb:fixtures"),
            Proposal("add-page", None, f"Restore or write the page {_safe(page)}, or drop its record."),
        )
    for tag in sorted(set(docs.get("required_tags", [])) - topics):
        add(
            "missing",
            None,
            f"topic: {tag}",
            f"no page covers the required topic {_safe(tag)}",
            ("doc:required_tags", "kb:fixtures"),
            Proposal("add-page", None, f"Draft a {_safe(tag)} page for {client}."),
        )
    claimed = {k for k in claims}
    for key, device in sorted(seen.devices.items()):
        if ("device", key) not in claimed and not _dormant(device, today):
            category = _safe(device.get("deviceType", {}).get("category", "unknown"))
            add(
                "missing",
                None,
                str(device["hostname"]),
                f"observed device {_safe(device['hostname'])} is not in any page",
                ("rmm:devices",),
                Proposal("add-claim", None, f"Add {_safe(device['hostname'])} ({category}) to the asset list."),
            )
    for key, contact in sorted(seen.contacts.items()):
        if ("contact", key) not in claimed:
            name = f"{contact.get('firstName', '')} {contact.get('lastName', '')}".strip()
            add(
                "missing",
                None,
                _safe(name),
                f"observed contact {_safe(name)} is not in any page",
                ("psa:contacts",),
                Proposal(
                    "add-claim",
                    None,
                    f"Add {_safe(name)} ({_safe(contact.get('title', 'role unknown'))}) to the contact list.",
                ),
            )
    for key, seats in sorted(seen.skus.items()):
        if ("license", key) not in claimed:
            sku = key.upper()
            add(
                "missing",
                None,
                sku,
                f"observed licence {sku} ({seats} seats) is not in any page",
                ("graph:licenses",),
                Proposal("add-claim", None, f"Add licence {sku} ({seats} seats) to the licence list."),
            )

    order = {kind: i for i, kind in enumerate(KINDS)}
    rows.sort(key=lambda r: (order[r[0]], r[1] or "", r[2], r[3]))
    findings = tuple(
        Finding(f"{client}:{kind}:{n:02d}", client, kind, page, subject, detail, sources, proposal)
        for n, (kind, page, subject, detail, sources, proposal) in enumerate(rows, start=1)
    )
    return Report(client, today.isoformat(), len(pages), vault, tuple(flagged), findings)


def scope_list(kb_dir: Path) -> tuple[KbScope, ...]:
    try:
        return load_kb(kb_dir)
    except (IngestError, OSError) as exc:
        raise DocUpkeepError("the KB fixtures are not readable") from exc


# ---------------------------------------------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------------------------------------------


def render_markdown(report: Report) -> str:
    out = [
        f"# Documentation upkeep: {report.client}",
        "",
        f"As of {report.as_of}. Read-only: these are DRAFT proposals for a person; nothing was changed. {report.note}",
        "",
        f"Pages checked {report.pages_checked}; vault entries skipped unread {report.vault_skipped}; "
        f"pages with instruction-like text (flagged, not followed): {', '.join(report.flagged_pages) or 'none'}.",
        "",
        "Summary: " + ", ".join(f"{kind} {count}" for kind, count in report.summary.items()),
    ]
    for kind in KINDS:
        rows = [f for f in report.findings if f.kind == kind]
        out += ["", f"## {kind.capitalize()} ({len(rows)})", ""]
        for f in rows:
            where = f.page or "no page"
            out.append(f"- `{f.id}` ({where}) {f.detail}. Used: {', '.join(f.sources)}.")
            out.append(f"  - Draft proposal ({f.proposal.action}): {f.proposal.draft}")
    out += ["", f"Report SHA-256: `{report.sha256}`", ""]
    return "\n".join(out)


def write_report(report: Report, out_dir: Path = DEFAULT_OUT_DIR) -> list[Path]:
    """Write ``<client>.json`` (with ``report_sha256``) and ``<client>.md`` under ``out_dir``; nothing else."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    body = report.to_dict()
    body["report_sha256"] = report.sha256
    json_path = out / f"{report.client}.json"
    md_path = out / f"{report.client}.md"
    json_path.write_bytes(_canonical(body))
    md_path.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    return [json_path, md_path]
