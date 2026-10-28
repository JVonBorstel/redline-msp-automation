"""Answer drafts for security questionnaires, cyber-insurance questions and proposal sections (B-60).

Nothing here calls a model. A draft answer is assembled from three kinds of evidence and nothing else:

- a sentence quoted word for word from a retrieved passage (B-57 ``candidates``), cited by chunk id;
- a repo control from ``map/controls.json`` that is built or partial and has at least one test that exists, cited by
  control id and test id (B-95 mapping);
- a range of actual hours over similar past synthetic projects, cited by project id.

Every claim is the same fixed lead plus the evidence itself, so an answer cannot say more than its evidence: the lead
names what kind of statement it is ("MSP policy ... states", "is described as", "logged actual hours"), never "does",
"is enforced" or "is certified". ``check_draft`` re-derives each claim from its citations and reports any difference;
``inflation_problems`` is the independent word check (strong words and numbers must appear in the evidence).

A question is refused ("needs a person") when it asks for certification or framework status, for a result or count from
real operation, or whether something is enforced or running in production, because this repo can never support those;
when no source qualifies; and when its text trips the injection tripwire (the text is withheld, not echoed).
Every draft carries DRAFT and the named person who must review it. Nothing is approved or sent here.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.audit.router import valid_client_id
from core.guard.detect import detect_injection
from core.paths import REPO_ROOT
from rag.retrieve import ANSWER_THRESHOLD, Index, build_index, candidates
from rag.retrieve.search import caller_namespaces
from rag.store import MSP_INTERNAL
from rag.store.models import Chunk
from workflows.assurance.soc2 import control_status, load_controls, load_mapping

FIXTURES = REPO_ROOT / "fixtures" / "questionnaires"
AS_OF = "2026-10-27"
NEEDS_PERSON = "needs a person"
STATUS_DRAFT = "DRAFT"
KINDS = ("security", "insurance", "proposal")
SCOPES = ("msp", "client", "scoping")
MAX_ITEMS = 200
MAX_QUESTION_CHARS = 300
MAX_SENTENCES = 3
MAX_CONTROLS = 2
MIN_PROJECTS = 3
RETRIEVE_K = 12
WITHHELD_QUESTION = "[question text withheld: it was flagged as an instruction attempt]"

LIMIT_BASE = (
    "This is a draft built from written policy, client records and repo tests on synthetic fixtures. "
    "It is not evidence that anything operates, is enforced, or has been tested in a real environment."
)
LIMIT_RANGE = "A range from history, not an estimate, quote or promise for this project."

_PLACEHOLDER_OWNERS = frozenset(
    "tbd todo owner none n/a na anyone anybody unknown me admin team someone nobody name reviewer".split()
)
_TOKEN = re.compile(r"[a-z0-9]+")
_NUMBER = re.compile(r"\d+")
_TEST_ID = re.compile(r"^[\w./-]+\.py::\w+$")

# Words that raise the strength of a claim. A claim body may contain one only if its evidence already does.
STRONG_WORDS = frozenset(
    "always never all every enforced verified production continuously fully ensure ensures ensured prevent prevents "
    "certified certification compliant compliance audited attested guarantee guarantees guaranteed soc hipaa iso "
    "hitrust pci".split()
)

_CERT = re.compile(
    r"\b(soc ?2?|iso|hitrust|pci|hipaa|certified|certification|certify|compliant|compliance|attest\w*|type ii|"
    r"audit report|accredit\w*)\b",
    re.IGNORECASE,
)
_RESULTS = re.compile(
    r"\b(how many|percent(age)?|results?|uptime|average|have you (had|experienced|suffered)|did you (have|experience)|"
    r"(last|past|previous) (\w+ )?(years?|months?|quarters?)|in the past)\b",
    re.IGNORECASE,
)
_OPERATING = re.compile(
    r"\b(enforced|deployed|currently|fully|continuously|running|right now|in production|100%|at all times)\b",
    re.IGNORECASE,
)
REASON_CERT = (
    "the question asks for certification, attestation or framework status; only a named person holding the report "
    "can state it, and nothing in this repo is a certification"
)
REASON_RESULTS = "the question asks for a result or a count from real operation; this repo has fixture results only"
REASON_OPERATING = (
    "the question asks whether something is enforced, deployed or running in production; the evidence here is written "
    "policy and synthetic tests, which cannot show that"
)
REASON_NO_SOURCE = "no source found above the retrieval threshold in the MSP policy passages or a usable repo control"
REASON_NO_CLIENT_SOURCE = (
    "no source found in this client's own records; client facts are never taken from MSP policy or another client"
)


class QuestionnaireError(ValueError):
    """Bad questionnaire file, bad owner, bad client id: refused before anything is drafted."""


@dataclass(frozen=True, slots=True)
class Item:
    id: str
    scope: str  # msp: answer from MSP policy; client: from this client's records; scoping: from past projects
    text: str
    project_kind: str | None = None


@dataclass(frozen=True, slots=True)
class Questionnaire:
    title: str
    client: str
    kind: str
    items: tuple[Item, ...]


@dataclass(frozen=True, slots=True)
class Cite:
    kind: str  # passage | control | test | project
    ref: str  # chunk id, control id, "path::test_name" or project id
    label: str
    scope: str  # msp-internal or client


@dataclass(frozen=True, slots=True)
class Claim:
    level: str  # policy | client-record | repo-control | project-history
    lead: str  # fixed wording that says what kind of statement follows
    body: str  # the evidence itself: a quote, a control objective, or a range
    cites: tuple[Cite, ...]

    @property
    def text(self) -> str:
        return self.lead + self.body


@dataclass(frozen=True, slots=True)
class Draft:
    item_id: str
    scope: str
    question: str
    owner: str
    claims: tuple[Claim, ...]
    limits: tuple[str, ...]
    reason: str = ""
    withheld_question: bool = False
    withheld_sources: int = 0

    @property
    def refused(self) -> bool:
        return not self.claims

    @property
    def status(self) -> str:
        """Every draft, answered or refused, is a DRAFT until its named owner reviews it."""
        return STATUS_DRAFT

    @property
    def state(self) -> str:
        return NEEDS_PERSON if self.refused else STATUS_DRAFT


@dataclass(frozen=True)
class Context:
    """Everything a draft may draw on, loaded once: the cited index, the controls, the projects, the crosswalk."""

    index: Index
    controls: dict[str, dict[str, Any]]
    mapping: dict[str, Any]
    projects: tuple[dict[str, Any], ...]
    crosswalk: tuple[tuple[frozenset[str], tuple[str, ...]], ...]
    root: Path = REPO_ROOT

    def chunks_for(self, client: str) -> dict[str, Chunk]:
        """The retrievable chunks a caller may cite: its own namespace and msp-internal, never a withheld chunk."""
        out: dict[str, Chunk] = {}
        for ns in caller_namespaces(client):
            for chunk in self.index.store.chunks(ns):
                if not chunk.flagged:
                    out[chunk.chunk_id] = chunk
        return out

    def passages_for(self, cite: Cite) -> list[Chunk]:
        """Test helper: the chunk a passage citation points at, whatever its namespace."""
        if cite.kind != "passage":
            return []
        return [
            c for ns in self.index.store.namespaces() for c in self.index.store.chunks(ns) if c.chunk_id == cite.ref
        ]

    def control_objective(self, control_id: str) -> str | None:
        control = self.controls.get(control_id)
        return None if control is None else str(control.get("objective", ""))


def build_context(root: Path = REPO_ROOT, fixtures: Path = FIXTURES) -> Context:
    index = build_index(fixtures / "kb")
    controls = {str(c["id"]): c for c in load_controls(root)}
    mapping = load_mapping(root)
    projects_doc = json.loads((fixtures / "projects.json").read_text(encoding="utf-8"))
    crosswalk_doc = json.loads((fixtures / "crosswalk.json").read_text(encoding="utf-8"))
    crosswalk = tuple(
        (frozenset(str(k).lower() for k in row["keywords"]), tuple(str(c) for c in row["controls"]))
        for row in crosswalk_doc["rows"]
    )
    return Context(index, controls, mapping, tuple(projects_doc["projects"]), crosswalk, root)


# -- inputs ------------------------------------------------------------------------------------------------------------


def validate_owner(owner: str) -> str:
    """The named person who must review the draft. Placeholders and empty names are refused."""
    name = " ".join(str(owner).split())
    if len(name) < 3 or not re.search(r"[A-Za-z]", name) or name.lower() in _PLACEHOLDER_OWNERS:
        raise QuestionnaireError("a draft needs a named owner who will review it (not blank or a placeholder)")
    return name


def _item(raw: Any, seen: set[str]) -> Item:
    if not isinstance(raw, dict) or set(raw) - {"id", "scope", "text", "project_kind"}:
        raise QuestionnaireError("an item is malformed or has an unknown key")
    item_id, scope, text = raw.get("id"), raw.get("scope"), raw.get("text")
    if not isinstance(item_id, str) or not item_id.strip() or item_id in seen:
        raise QuestionnaireError("an item id is missing or repeated")
    if scope not in SCOPES:
        raise QuestionnaireError(f"{item_id}: scope must be one of {', '.join(SCOPES)}")
    if not isinstance(text, str) or len(text.split()) < 2 or len(text) > MAX_QUESTION_CHARS:
        raise QuestionnaireError(f"{item_id}: the question text is missing or too long")
    kind = raw.get("project_kind")
    if scope == "scoping" and not isinstance(kind, str):
        raise QuestionnaireError(f"{item_id}: a scoping item needs a project_kind")
    seen.add(item_id)
    return Item(item_id, scope, text, kind if isinstance(kind, str) else None)


def load_questionnaire(path: Path) -> Questionnaire:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise QuestionnaireError(f"cannot read {Path(path).name}") from exc
    if not isinstance(doc, dict) or doc.get("synthetic") is not True:
        raise QuestionnaireError('only questionnaires marked synthetic are accepted ("synthetic": true)')
    client, kind = doc.get("client"), doc.get("kind")
    if not valid_client_id(client):
        raise QuestionnaireError("the client id is not usable")
    if kind not in KINDS:
        raise QuestionnaireError(f"kind must be one of {', '.join(KINDS)}")
    raw_items = doc.get("items")
    if not isinstance(raw_items, list) or len(raw_items) > MAX_ITEMS:
        raise QuestionnaireError(f"items must be a list of at most {MAX_ITEMS}")
    seen: set[str] = set()
    items = tuple(_item(r, seen) for r in raw_items)
    return Questionnaire(str(doc.get("title", "Synthetic questionnaire")), str(client), str(kind), items)


# -- the evidence checks -----------------------------------------------------------------------------------------------


def _squash(text: str) -> str:
    return " ".join(text.split())


def inflation_problems(claim: str, evidence: Iterable[str]) -> list[str]:
    """Words or numbers in ``claim`` that make it stronger than ``evidence``. Empty means it says no more."""
    evidence_text = " ".join(evidence).lower()
    have_words = set(_TOKEN.findall(evidence_text))
    have_numbers = set(_NUMBER.findall(evidence_text))
    problems: list[str] = []
    for word in sorted(set(_TOKEN.findall(claim.lower())) & STRONG_WORDS):
        if word not in have_words:
            problems.append(f"says '{word}', which the evidence does not")
    for number in sorted(set(_NUMBER.findall(claim))):
        if number not in have_numbers:
            problems.append(f"states the number {number}, which the evidence does not contain")
    return problems


def _passage_lead(chunk: Chunk) -> str:
    prov = chunk.provenance
    kind = "MSP policy" if chunk.namespace == MSP_INTERNAL else "Client record"
    return f'{kind} {prov.article_id} "{prov.title}" states: '


def _control_lead(control: dict[str, Any]) -> str:
    return f"Repo control {control['id']} ({control['name']}), status {control_status(control)}, is described as: "


def _resolved_tests(ctx: Context, control_id: str) -> list[str]:
    entry = ctx.mapping["controls"].get(control_id, {})
    found: list[str] = []
    for test in entry.get("tests", []):
        if not isinstance(test, str) or not _TEST_ID.match(test):
            continue
        rel, name = test.split("::")
        path = (ctx.root / rel).resolve()
        if ctx.root.resolve() not in path.parents or not path.is_file():
            continue
        if re.search(rf"^\s*def {re.escape(name)}\b", path.read_text(encoding="utf-8"), re.MULTILINE):
            found.append(test)
    return found


def _range_body(hours: Sequence[int]) -> str:
    return f"between {min(hours)} and {max(hours)} hours across {len(hours)} projects."


def _range_lead(kind: str, ids: Sequence[str]) -> str:
    return f"Past synthetic projects of kind {kind} ({', '.join(ids)}) logged actual hours "


def _visible_projects(ctx: Context, client: str, kind: str) -> tuple[list[dict[str, Any]], int]:
    """Projects of this kind the client may see (its own and msp-internal), minus injection-flagged ones."""
    usable: list[dict[str, Any]] = []
    withheld = 0
    for project in ctx.projects:
        if project.get("kind") != kind or project.get("namespace") not in (client, MSP_INTERNAL):
            continue
        free_text = " ".join(str(project.get(k, "")) for k in ("title", "note"))
        if detect_injection(free_text).flagged:
            withheld += 1
            continue
        hours = project.get("hours_actual")
        if isinstance(hours, int) and not isinstance(hours, bool) and hours >= 0:
            usable.append(project)
    usable.sort(key=lambda p: str(p["project_id"]))
    return usable, withheld


def check_draft(ctx: Context, client: str, draft: Draft) -> list[str]:
    """Problems found in a draft; empty means each claim is exactly what its own citations support."""
    problems: list[str] = []
    try:
        validate_owner(draft.owner)
    except QuestionnaireError as exc:
        problems.append(str(exc))
    if draft.refused:
        if not draft.reason:
            problems.append("a refusal must give its reason")
        return problems
    if draft.reason:
        problems.append("an answered draft must not carry a refusal reason")
    if not draft.limits:
        problems.append("an answered draft must state its limits")
    chunks = ctx.chunks_for(client)
    for number, claim in enumerate(draft.claims, start=1):
        problems.extend(f"claim {number} {p}" for p in _check_claim(ctx, client, draft, claim, chunks))
    return problems


def _check_claim(ctx: Context, client: str, draft: Draft, claim: Claim, chunks: dict[str, Chunk]) -> list[str]:
    if not claim.cites:
        return ["cites nothing"]
    if claim.level in {"policy", "client-record"}:
        return _check_passage_claim(draft, claim, chunks)
    if claim.level == "repo-control":
        return _check_control_claim(ctx, claim)
    if claim.level == "project-history":
        return _check_project_claim(ctx, client, claim)
    return [f"has an unknown level '{claim.level}'"]


def _check_passage_claim(draft: Draft, claim: Claim, chunks: dict[str, Chunk]) -> list[str]:
    if len(claim.cites) != 1 or claim.cites[0].kind != "passage":
        return ["must cite exactly one passage"]
    chunk = chunks.get(claim.cites[0].ref)
    if chunk is None:
        return ["cites a passage this caller may not read or that does not exist"]
    problems: list[str] = []
    is_msp = chunk.namespace == MSP_INTERNAL
    if draft.scope == "scoping" or (draft.scope == "msp") != is_msp:
        problems.append("cites a passage from the wrong scope for this question")
    if claim.lead != _passage_lead(chunk) or claim.level != ("policy" if is_msp else "client-record"):
        problems.append("lead differs from what its citation supports")
    if _squash(claim.body) not in _squash(chunk.text):
        problems.append("body is not quoted from the passage it cites")
    problems.extend(inflation_problems(claim.body, [chunk.text]))
    return problems


def _check_control_claim(ctx: Context, claim: Claim) -> list[str]:
    first = claim.cites[0]
    control = ctx.controls.get(first.ref) if first.kind == "control" else None
    if control is None:
        return ["cites a control that is not in the control map"]
    problems: list[str] = []
    if control_status(control) == "planned":
        problems.append("cites a control the map lists as planned")
    if claim.lead != _control_lead(control) or claim.body != str(control.get("objective", "")):
        problems.append("text differs from what the control map supports")
    allowed = set(_resolved_tests(ctx, first.ref))
    tests = [c.ref for c in claim.cites[1:] if c.kind == "test"]
    if not tests or len(tests) != len(claim.cites) - 1 or not set(tests) <= allowed:
        problems.append("must cite one or more tests that exist for this control, and nothing else")
    problems.extend(inflation_problems(claim.body, [str(control.get("objective", ""))]))
    return problems


def _check_project_claim(ctx: Context, client: str, claim: Claim) -> list[str]:
    ids = [c.ref for c in claim.cites if c.kind == "project"]
    if len(ids) != len(claim.cites) or len(ids) < MIN_PROJECTS:
        return [f"must cite at least {MIN_PROJECTS} projects and nothing else"]
    by_id = {str(p["project_id"]): p for p in ctx.projects}
    chosen = [by_id.get(i) for i in ids]
    if any(p is None or p.get("namespace") not in (client, MSP_INTERNAL) for p in chosen):
        return ["cites a project this caller may not see"]
    rows = [p for p in chosen if p is not None]
    hours = [int(p["hours_actual"]) for p in rows]
    kinds = {str(p["kind"]) for p in rows}
    problems: list[str] = []
    if len(kinds) != 1 or claim.lead != _range_lead(kinds.pop(), sorted(ids)) or claim.body != _range_body(hours):
        problems.append("text differs from the range its projects support")
    problems.extend(inflation_problems(claim.body, [str(h) for h in hours] + [str(len(hours))]))
    return problems


# -- drafting ----------------------------------------------------------------------------------------------------------


def _classify(text: str) -> str | None:
    for pattern, reason in ((_CERT, REASON_CERT), (_RESULTS, REASON_RESULTS), (_OPERATING, REASON_OPERATING)):
        if pattern.search(text):
            return reason
    return None


def _control_claims(ctx: Context, text: str) -> list[Claim]:
    words = set(_TOKEN.findall(text.lower()))
    wanted: list[str] = []
    for keywords, controls in ctx.crosswalk:
        if words & keywords:
            wanted.extend(c for c in controls if c not in wanted)
    claims: list[Claim] = []
    for control_id in wanted:
        control = ctx.controls.get(control_id)
        if control is None or control_status(control) == "planned":
            continue
        tests = _resolved_tests(ctx, control_id)
        if not tests:
            continue
        cites = (Cite("control", control_id, str(control["name"]), MSP_INTERNAL),) + tuple(
            Cite("test", t, t.split("::")[1], MSP_INTERNAL) for t in tests
        )
        claims.append(Claim("repo-control", _control_lead(control), str(control["objective"]), cites))
        if len(claims) == MAX_CONTROLS:
            break
    return claims


def _control_limits(ctx: Context, claims: Sequence[Claim]) -> list[str]:
    limits: list[str] = []
    for claim in claims:
        entry = ctx.mapping["controls"].get(claim.cites[0].ref, {})
        for gap in entry.get("not_demonstrated", []):
            limits.append(f"{claim.cites[0].ref} not demonstrated: {gap}")
    return limits


def _passage_claims(ctx: Context, client: str, item: Item) -> tuple[list[Claim], int]:
    _, scored, suppressed = candidates(ctx.index.store, ctx.index.embedder, client, item.text, k=RETRIEVE_K)
    want = MSP_INTERNAL if item.scope == "msp" else "client"
    claims: list[Claim] = []
    seen: set[str] = set()
    allowed = ctx.chunks_for(client)
    for sentence in scored:
        if sentence.score < ANSWER_THRESHOLD or len(claims) == MAX_SENTENCES:
            break
        if sentence.passage.scope != want or sentence.text in seen:
            continue
        seen.add(sentence.text)
        chunk = allowed[sentence.passage.chunk_id]
        prov = chunk.provenance
        level = "policy" if want == MSP_INTERNAL else "client-record"
        cite = Cite("passage", chunk.chunk_id, f"{prov.article_id} {prov.title}", want)
        claims.append(Claim(level, _passage_lead(chunk), sentence.text, (cite,)))
    return claims, suppressed


def _scoping(ctx: Context, client: str, item: Item) -> tuple[list[Claim], int, str]:
    kind = item.project_kind or ""
    rows, withheld = _visible_projects(ctx, client, kind)
    if len(rows) < MIN_PROJECTS:
        reason = f"fewer than {MIN_PROJECTS} similar past projects are visible to this client, so no range is given"
        return [], withheld, reason
    hours = [int(p["hours_actual"]) for p in rows]
    ids = [str(p["project_id"]) for p in rows]
    cites = tuple(
        Cite(
            "project",
            str(p["project_id"]),
            str(p["title"]),
            MSP_INTERNAL if p["namespace"] == MSP_INTERNAL else "client",
        )
        for p in rows
    )
    return [Claim("project-history", _range_lead(kind, ids), _range_body(hours), cites)], withheld, ""


def _refuse(item: Item, owner: str, reason: str, **extra: Any) -> Draft:
    return Draft(item.id, item.scope, item.text, owner, (), (), reason, **extra)


def draft_item(ctx: Context, client: str, item: Item, owner: str) -> Draft:
    """One DRAFT answer with citations, or a refusal marked ``needs a person``."""
    owner = validate_owner(owner)
    if not valid_client_id(client):
        raise QuestionnaireError("the client id is not usable")
    if item.scope not in SCOPES:
        raise QuestionnaireError(f"{item.id}: unknown scope")
    if len(item.text) > MAX_QUESTION_CHARS:
        raise QuestionnaireError(f"{item.id}: the question text is too long")
    if detect_injection(item.text).flagged:
        why = "the question text was withheld: it matched the injection tripwire"
        return Draft(item.id, item.scope, WITHHELD_QUESTION, owner, (), (), why, withheld_question=True)
    reason = _classify(item.text)
    if reason is not None:
        return _refuse(item, owner, reason)
    if item.scope == "scoping":
        claims, withheld, why = _scoping(ctx, client, item)
        if not claims:
            return _refuse(item, owner, why, withheld_sources=withheld)
        return Draft(
            item.id, item.scope, item.text, owner, tuple(claims), (LIMIT_BASE, LIMIT_RANGE), "", False, withheld
        )
    claims, withheld = _passage_claims(ctx, client, item)
    limits: list[str] = []
    if item.scope == "msp":
        controls = _control_claims(ctx, item.text)
        claims.extend(controls)
        limits.extend(_control_limits(ctx, controls))
    if not claims:
        why = REASON_NO_CLIENT_SOURCE if item.scope == "client" else REASON_NO_SOURCE
        return _refuse(item, owner, why, withheld_sources=withheld)
    return Draft(item.id, item.scope, item.text, owner, tuple(claims), (LIMIT_BASE, *limits), "", False, withheld)


def draft_questionnaire(ctx: Context, q: Questionnaire, owner: str) -> list[Draft]:
    owner = validate_owner(owner)
    return [draft_item(ctx, q.client, item, owner) for item in q.items]


# -- rendering ---------------------------------------------------------------------------------------------------------


def banner(owner: str) -> str:
    return f"DRAFT - requires review by {owner}. Not reviewed, not approved, not sent."


def render_draft(draft: Draft) -> str:
    lines = [banner(draft.owner), f"[{draft.item_id}] {draft.question}"]
    if draft.refused:
        lines.append(f"NEEDS A PERSON (needs a human answer): {draft.reason}")
    for claim in draft.claims:
        refs = " ".join(f"[{c.ref}]" for c in claim.cites if c.kind in {"passage", "control", "project"})
        lines.append(f"{claim.text} {refs}")
        tests = [c.ref for c in claim.cites if c.kind == "test"]
        if tests:
            lines.append("Backed by tests: " + "; ".join(tests))
    lines.extend(f"Limits: {limit}" for limit in draft.limits)
    if draft.withheld_sources:
        lines.append(f"{draft.withheld_sources} source text(s) withheld by the injection tripwire and not used.")
    return "\n".join(lines)


def render_questionnaire(q: Questionnaire, drafts: Sequence[Draft], owner: str) -> str:
    answered = sum(not d.refused for d in drafts)
    head = [
        f"# DRAFT - {q.title}",
        "",
        banner(owner),
        "",
        f"Synthetic questionnaire for {q.client} ({q.kind}), drafted {AS_OF} without any model call. "
        f"{answered} of {len(drafts)} items have a cited draft; {len(drafts) - answered} {NEEDS_PERSON}.",
        "",
    ]
    for draft in drafts:
        head.extend([f"## {draft.item_id}", "", "```text", render_draft(draft), "```", ""])
    return "\n".join(head)


def questionnaire_json(q: Questionnaire, drafts: Sequence[Draft], owner: str) -> dict[str, Any]:
    return {
        "status": STATUS_DRAFT,
        "requires_review_by": owner,
        "owner": owner,
        "synthetic": True,
        "client": q.client,
        "kind": q.kind,
        "title": q.title,
        "as_of": AS_OF,
        "items": [
            {
                "id": d.item_id,
                "status": d.state,
                "question": d.question,
                "reason": d.reason,
                "withheld_sources": d.withheld_sources,
                "limits": list(d.limits),
                "claims": [
                    {
                        "level": c.level,
                        "text": c.text,
                        "cites": [{"kind": x.kind, "ref": x.ref, "label": x.label} for x in c.cites],
                    }
                    for c in d.claims
                ],
            }
            for d in drafts
        ],
    }
