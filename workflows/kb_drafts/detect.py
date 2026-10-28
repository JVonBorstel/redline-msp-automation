"""Stale and conflicting article detection (B-58), read-only.

For one client's knowledge base:

* **stale**: an article last reviewed more than ``max_age_days`` before ``as_of`` (review dates come from the B-59
  documentation fixture shape), or one the B-59 documentation upkeep report calls stale because it documents
  something observed state no longer shows. The B-59 finding ids are listed with it;
* **conflicting**: two articles of the same client that say opposite things about the same topic. Candidates come from
  B-57 retrieval (``rag.retrieve.search``, which reads the client's namespace and ``msp-internal`` only): each sentence
  of an article is the query, and a sentence of another article of the same client in the results that a lexical rule
  (``workflows.kb_drafts.text.opposition``) finds contradictory is a conflict. A draft can be checked the same way
  against the existing articles.

Safety: article text is untrusted and is screened with the injection tripwire (an article with instruction-like text
is listed in ``flagged_articles`` and neither compared nor quoted); vault entries are counted and never read; only
sentences that passed the redaction gate are quoted; passages from ``msp-internal`` are never compared (a client
article is checked against the same client's articles only). Nothing is written to the knowledge base.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from core.audit.router import valid_client_id
from core.guard.detect import detect_injection
from core.guard.redact_prompt import redact_prompt
from core.paths import REPO_ROOT
from rag.ingest import IngestError, load_kb
from rag.retrieve import MAX_QUERY_CHARS, build_index, search
from rag.store import MSP_INTERNAL
from workflows.doc_upkeep import DocUpkeepError, build_report
from workflows.doc_upkeep.upkeep import DEFAULT_DATA_DIR as UPKEEP_DATA_DIR
from workflows.kb_drafts.drafts import Draft
from workflows.kb_drafts.text import MIN_CORE, opposition, split_sentences

DEFAULT_KB_DIR = REPO_ROOT / "fixtures" / "kb"
DEFAULT_REVIEWS_DIR = UPKEEP_DATA_DIR
DEFAULT_OUT_DIR = REPO_ROOT / "build" / "kb-detect"
DEFAULT_MAX_AGE_DAYS = 365
RELATED_MIN = 0.15  # retrieval score a passage needs before its sentences are compared (stand-in embedder)
RETRIEVE_K = 6


class DetectError(ValueError):
    """The request or an input is unusable. Nothing is reported."""


@dataclass(frozen=True, slots=True)
class StaleFinding:
    article_id: str
    age_days: int | None
    reasons: tuple[str, ...]  # "older-than-limit" and/or "doc-upkeep"
    doc_upkeep: tuple[str, ...]  # B-59 finding ids on this article

    def to_dict(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "age_days": self.age_days,
            "reasons": list(self.reasons),
            "doc_upkeep": list(self.doc_upkeep),
        }


@dataclass(frozen=True, slots=True)
class ConflictFinding:
    id: str
    articles: tuple[str, str]
    rule: str
    sentences: tuple[str, str]  # in the order of ``articles``; redacted
    score: float  # B-57 retrieval score of the passage that surfaced the second sentence
    doc_upkeep: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "articles": list(self.articles),
            "rule": self.rule,
            "sentences": list(self.sentences),
            "score": round(self.score, 4),
            "doc_upkeep": list(self.doc_upkeep),
            "proposal": {
                "action": "reconcile-articles",
                "status": "draft",
                "draft": f"Decide which of {self.articles[0]} and {self.articles[1]} is right and fix the other.",
            },
        }


@dataclass(frozen=True, slots=True)
class DetectReport:
    client: str
    as_of: str
    max_age_days: int
    articles_checked: int
    vault_skipped: int
    flagged_articles: tuple[str, ...]
    msp_passages_ignored: int
    stale: tuple[StaleFinding, ...]
    conflicts: tuple[ConflictFinding, ...]
    draft_conflicts: tuple[ConflictFinding, ...]
    read_only: bool = True
    note: str = "Fixture-based: synthetic KB and review dates, word-overlap retrieval stand-in. Proposals are drafts."

    def to_dict(self) -> dict[str, Any]:
        return {
            "client": self.client,
            "as_of": self.as_of,
            "read_only": self.read_only,
            "note": self.note,
            "max_age_days": self.max_age_days,
            "articles_checked": self.articles_checked,
            "vault_skipped": self.vault_skipped,
            "flagged_articles": list(self.flagged_articles),
            "msp_passages_ignored": self.msp_passages_ignored,
            "stale": [s.to_dict() for s in self.stale],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "draft_conflicts": [c.to_dict() for c in self.draft_conflicts],
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()


def _canonical(body: Mapping[str, Any]) -> bytes:
    return (json.dumps(body, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def _date(value: object, what: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise DetectError(f"{what} is not a YYYY-MM-DD date") from exc


def _reviews(client: str, reviews_dir: Path) -> dict[str, Any]:
    try:
        body = json.loads((Path(reviews_dir) / f"{client}.json").read_text(encoding="utf-8"))
        if body["client"] != client or not isinstance(body["pages"], list):
            raise DetectError("the review fixture does not belong to this client")
        _date(body["as_of"], "the review fixture as_of")
        return dict(body)
    except DetectError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DetectError(f"no usable review fixture for {client} ({type(exc).__name__})") from exc


def _clean_sentence(sentence: str) -> str | None:
    """The sentence after the redaction gate, or ``None`` when it is too short, blocked or instruction-like."""
    if detect_injection(sentence).flagged:
        return None
    gate = redact_prompt(sentence)
    if gate.blocked or len(gate.text.split()) < MIN_CORE:
        return None
    return gate.text


def detect_report(
    client: str,
    *,
    kb_dir: Path = DEFAULT_KB_DIR,
    reviews_dir: Path = DEFAULT_REVIEWS_DIR,
    as_of: str | None = None,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    drafts: Sequence[Draft] = (),
) -> DetectReport:
    """Stale and conflicting articles for ``client``; read-only and deterministic for one ``as_of``."""
    if not isinstance(client, str) or not valid_client_id(client) or client == MSP_INTERNAL:
        raise DetectError("not a usable client id")
    if max_age_days < 1:
        raise DetectError("max_age_days must be at least 1")
    for draft in drafts:
        if draft.client != client:
            raise DetectError("a draft belongs to another client")
    reviews = _reviews(client, reviews_dir)
    today = _date(as_of if as_of is not None else reviews["as_of"], "as_of")
    try:
        scopes = load_kb(kb_dir)
    except (IngestError, OSError) as exc:
        raise DetectError("the KB fixtures are not readable") from exc
    scope = next((s for s in scopes if s.name == client), None)
    if scope is None:
        raise DetectError(f"no KB scope for {client}")
    try:
        upkeep = build_report(client, as_of=today.isoformat(), kb_dir=kb_dir, data_dir=reviews_dir)
    except DocUpkeepError as exc:
        raise DetectError(f"the B-59 documentation report is unavailable: {exc}") from exc

    vault = 0
    flagged: list[str] = []
    live: dict[str, list[str]] = {}  # article id -> redacted, screened sentences
    listed: list[str] = []  # every non-vault article (flagged ones too: a review date is not article text)
    for source in scope.sources:
        if source.origin.startswith("vault/") or "credential-vault" in source.tags:
            vault += 1
            continue
        listed.append(source.article_id)
        if detect_injection(f"{source.title}\n{source.text}").flagged:
            flagged.append(source.article_id)
            continue
        live[source.article_id] = [
            s for s in (_clean_sentence(x) for x in split_sentences(source.text)) if s is not None
        ]

    # --- stale ------------------------------------------------------------------------------------------------
    reviewed = {str(p["article_id"]): p.get("last_reviewed") for p in reviews["pages"]}
    upkeep_ids: dict[str, list[str]] = {}
    upkeep_claim_stale: set[str] = set()
    for finding in upkeep.findings:
        if finding.page is None:
            continue
        if finding.kind == "stale":
            upkeep_ids.setdefault(finding.page, []).append(finding.id)
            if finding.subject != "review date":  # B-59's own age limit is not this report's N
                upkeep_claim_stale.add(finding.page)
    stale: list[StaleFinding] = []
    for article in sorted(listed):
        stamp = reviewed.get(article)
        age = None if stamp is None else (today - _date(stamp, f"{article} last_reviewed")).days
        reasons = []
        if age is not None and age > max_age_days:
            reasons.append("older-than-limit")
        if article in upkeep_claim_stale:
            reasons.append("doc-upkeep")
        if reasons:
            stale.append(StaleFinding(article, age, tuple(reasons), tuple(sorted(upkeep_ids.get(article, [])))))

    # --- conflicts via B-57 retrieval -------------------------------------------------------------------------
    index = build_index(Path(kb_dir))
    msp_ignored = 0

    def scan(owner: str, sentences: Sequence[str]) -> dict[tuple[str, str, str], tuple[float, str, str]]:
        nonlocal msp_ignored
        found: dict[tuple[str, str, str], tuple[float, str, str]] = {}
        for sentence in sentences:
            for passage in search(index.store, index.embedder, client, sentence[:MAX_QUERY_CHARS], k=RETRIEVE_K):
                if passage.scope != "client":
                    msp_ignored += 1
                    continue
                if passage.article_id == owner or passage.article_id not in live or passage.score < RELATED_MIN:
                    continue
                for other in split_sentences(passage.text):
                    if (cleaned := _clean_sentence(other)) is None or (rule := opposition(sentence, cleaned)) is None:
                        continue
                    key = (owner, passage.article_id, rule)
                    if key not in found or passage.score > found[key][0]:
                        found[key] = (passage.score, sentence, cleaned)
        return found

    def related_upkeep(*articles: str) -> tuple[str, ...]:
        wanted = set(articles)
        return tuple(sorted(f.id for f in upkeep.findings if f.kind == "contradictory" and f.page in wanted))

    pairs: dict[tuple[str, str, str], tuple[float, str, str]] = {}
    for article in sorted(live):
        for (owner, other, rule), (score, mine, theirs) in scan(article, live[article]).items():
            first, second = sorted((owner, other))
            ordered = (mine, theirs) if owner == first else (theirs, mine)
            if (first, second, rule) not in pairs or score > pairs[(first, second, rule)][0]:
                pairs[(first, second, rule)] = (score, ordered[0], ordered[1])
    conflicts = tuple(
        ConflictFinding(f"{client}:conflict:{n:02d}", (a, b), rule, (s1, s2), score, related_upkeep(a, b))
        for n, ((a, b, rule), (score, s1, s2)) in enumerate(sorted(pairs.items()), start=1)
    )

    draft_found: dict[tuple[str, str, str], tuple[float, str, str]] = {}
    for draft in sorted(drafts, key=lambda d: d.draft_id):
        steps = [s for s in (_clean_sentence(x) for x in draft.steps) if s is not None]
        draft_found.update(scan(draft.draft_id, steps))
    draft_conflicts = tuple(
        ConflictFinding(f"{client}:draft-conflict:{n:02d}", (a, b), rule, (mine, theirs), score, related_upkeep(b))
        for n, ((a, b, rule), (score, mine, theirs)) in enumerate(sorted(draft_found.items()), start=1)
    )

    return DetectReport(
        client=client,
        as_of=today.isoformat(),
        max_age_days=max_age_days,
        articles_checked=len(live),
        vault_skipped=vault,
        flagged_articles=tuple(sorted(flagged)),
        msp_passages_ignored=msp_ignored,
        stale=tuple(stale),
        conflicts=conflicts,
        draft_conflicts=draft_conflicts,
    )


def render_markdown(report: DetectReport) -> str:
    out = [
        f"# Stale and conflicting articles: {report.client}",
        "",
        f"As of {report.as_of}. Read-only: these are DRAFT proposals for a person; nothing was changed or published. "
        f"{report.note}",
        "",
        f"Articles compared {report.articles_checked}; vault entries skipped unread {report.vault_skipped}; "
        f"articles with instruction-like text (flagged, not compared): {', '.join(report.flagged_articles) or 'none'}.",
        "",
        f"## Stale (older than {report.max_age_days} days, or flagged by the B-59 upkeep report) ({len(report.stale)})",
        "",
    ]
    for s in report.stale:
        age = "no review date" if s.age_days is None else f"{s.age_days} days since review"
        used = f" B-59: {', '.join(s.doc_upkeep)}." if s.doc_upkeep else ""
        out.append(f"- `{s.article_id}`: {age} ({', '.join(s.reasons)}).{used}")
    for title, rows in (("Conflicting articles", report.conflicts), ("Drafts that conflict", report.draft_conflicts)):
        out += ["", f"## {title} ({len(rows)})", ""]
        for c in rows:
            out.append(f"- `{c.id}` {c.articles[0]} and {c.articles[1]} ({c.rule}, retrieval score {c.score:.2f}).")
            out.append(f"  - {c.articles[0]}: {c.sentences[0]}")
            out.append(f"  - {c.articles[1]}: {c.sentences[1]}")
    out += ["", f"Report SHA-256: `{report.sha256}`", ""]
    return "\n".join(out)


def write_detect_report(report: DetectReport, out_dir: Path = DEFAULT_OUT_DIR) -> list[Path]:
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
