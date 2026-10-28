"""Claim checker for the B-96 pages (B96-2, B96-3).

A factual claim about the system sits in a list item or a table row and ends with a tag:

- ``(proof: `path/to/test_file.py::test_name`)`` for what the system does. It must name at least one test.
- ``(policy: `path/to/file`)`` for a rule for people, or for something that is not built. It must name a file.

The checker fails when a cited path is missing or leaves the repo, when a ``::name`` is not defined in its file, when a
claim line has no tag, when a loose paragraph talks about the system without one, when an over-claim appears, when the
standard labels or the Limits section are missing, and when a one-page page is too long or too hard to read. It proves a
cited test is defined, not that it passes: the test runs prove that. Only lines that start with "Your part:" are
guidance for people and need no tag.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from core.paths import REPO_ROOT
from workflows.assurance.soc2 import _defines, _inside

ONE_PAGE_WORDS = 450
PROTOTYPE_LABEL = "Independently built prototype. Not affiliated with any vendor's or real company's systems."
TAG = re.compile(r"\((proof|policy):([^()]*)\)")
REF = re.compile(r"`([^`]+)`")
FENCE = re.compile(r"(?ms)^```.*?^```[ \t]*$")
LIST_ITEM = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")
STATUS = re.compile(r"^Status: \*\*(built|document-only|mocked)\*\*")
SEPARATOR = re.compile(r"^\|[\s|:-]+\|?$")
NEGATION = re.compile(r"\b(not|no|nothing|never|without|nor|cannot)\b|n't", re.I)
# Words that mark a sentence about what the system does. A loose paragraph with one needs a tag.
CLAIM_WORDS = re.compile(
    r"\b(system|software|tool|tools|model|models|audit|logs?|never|always|cannot|every|only|sends?|refuses?)\b", re.I
)
OVERCLAIMS = (
    re.compile(r"\bin production\b|\bproduction[- ](use|ready|system)\b", re.I),
    re.compile(r"\bcertified\b|\bcertification\b|\bcompliant\b|\battest(ed|ation)\b", re.I),
    re.compile(r"\bguarantee[sd]?\b|\bproven\b", re.I),
    re.compile(r"\bcustomers? (use|trust|rely)\b|\bclients? (use|trust|rely on) (it|this)\b", re.I),
    re.compile(r"\breal[- ]world (results?|savings?|use)\b", re.I),
)


@dataclass(frozen=True)
class Rule:
    """Limits for one page. None means no limit."""

    grade_max: float | None = None
    words_max: int | None = None


DOCS: dict[str, Rule] = {
    "governance/STAFF_TRAINING.md": Rule(grade_max=10.0),
    "governance/CLIENT_CONVERSATION_GUIDE.md": Rule(grade_max=10.0),
    "docs/AI_EXPLAINER.md": Rule(grade_max=8.0, words_max=ONE_PAGE_WORDS),
    "docs/CLIENT_DATA_HANDLING.md": Rule(grade_max=8.0, words_max=ONE_PAGE_WORDS),
}


@dataclass(frozen=True)
class Tag:
    kind: str  # "proof" or "policy"
    refs: tuple[str, ...]
    empty: bool


@dataclass(frozen=True)
class Block:
    kind: str  # "item", "row" or "paragraph"
    line: int
    text: str


def _blank_fences(text: str) -> str:
    """Fenced code replaced by blank lines, so line numbers stay the same."""
    return FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def tags(text: str) -> list[Tag]:
    out: list[Tag] = []
    for kind, body in TAG.findall(_blank_fences(text)):
        out.append(Tag(kind, tuple(REF.findall(body)), not body.strip()))
    return out


def blocks(text: str) -> list[Block]:
    """List items, table body rows and loose paragraphs (headings, quotes, code and the Status line are skipped)."""
    lines = _blank_fences(text).splitlines()
    out: list[Block] = []
    para: list[tuple[int, str]] = []

    def flush() -> None:
        if para:
            out.append(Block("paragraph", para[0][0], " ".join(t for _, t in para)))
            para.clear()

    for n, raw in enumerate(lines, start=1):
        line = raw.rstrip()
        if not line.strip():
            flush()
        elif line.startswith("#") or line.startswith(">") or STATUS.match(line):
            flush()
        elif line.startswith("|"):
            flush()
            nxt = lines[n].strip() if n < len(lines) else ""
            if not SEPARATOR.match(line) and not SEPARATOR.match(nxt):
                out.append(Block("row", n, line))
        elif LIST_ITEM.match(line):
            flush()
            out.append(Block("item", n, LIST_ITEM.sub("", line, count=1)))
        elif raw[:1] in (" ", "\t") and out and out[-1].kind == "item":
            last = out.pop()
            out.append(Block("item", last.line, f"{last.text} {line.strip()}"))
        else:
            para.append((n, line.strip()))
    flush()
    return out


def _snippet(text: str) -> str:
    plain = TAG.sub("", text).strip(" |")
    return plain[:70] + ("..." if len(plain) > 70 else "")


def _check_ref(ref: str, root: Path) -> str | None:
    path, _, name = ref.partition("::")
    target = _inside(root, path)
    if target is None:
        return f"{ref!r} is outside the repo"
    if not target.exists():
        return f"{path} does not exist"
    if name:
        if not path.endswith(".py") or not target.is_file():
            return f"{ref} names a test inside something that is not a Python file"
        if not _defines(target.read_text(encoding="utf-8"), name):
            return f"test {name} is not defined in {path}"
    return None


def _overclaims(text: str) -> list[str]:
    bad: list[str] = []
    for line in text.splitlines():
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            if any(p.search(sentence) for p in OVERCLAIMS) and not NEGATION.search(sentence):
                bad.append(sentence.strip())
    return bad


def reading_text(text: str) -> str:
    """The words a reader reads: no code, tags, headings, link targets or markdown marks."""
    body = TAG.sub("", _blank_fences(text))
    body = re.sub(r"`[^`]*`", " ", body)
    body = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body)
    kept: list[str] = []
    for line in body.splitlines():
        if line.startswith("#") or SEPARATOR.match(line.strip()):
            continue
        line = LIST_ITEM.sub("", line).lstrip("> ").replace("|", " ").replace("*", "")
        if line.strip():
            kept.append(re.sub(r"\s+", " ", line).strip())
    return "\n".join(kept)


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", text)


def word_count(text: str) -> int:
    return len(_words(text))


def _syllables(word: str) -> int:
    """The same heuristic as the notify and incident-response tests."""
    word = word.lower()
    count = len(re.findall(r"[aeiouy]+", word))
    if word.endswith("e") and not word.endswith(("le", "ee")) and count > 1:
        count -= 1
    return max(1, count)


def reading_grade(text: str) -> float:
    """Flesch-Kincaid grade: 0.39 * words/sentences + 11.8 * syllables/words - 15.59. A line ends a sentence."""
    words = _words(text)
    sentences = [s for s in re.split(r"[.!?:]+(?:\s|$)|\n", text) if re.search(r"[A-Za-z0-9]", s)]
    if not words or not sentences:
        return 0.0
    return 0.39 * len(words) / len(sentences) + 11.8 * sum(_syllables(w) for w in words) / len(words) - 15.59


def check_doc(text: str, root: Path = REPO_ROOT, name: str = "page", rule: Rule | None = None) -> list[str]:
    """Problems found in one page, one per line; empty when every claim is tagged and every cited ref exists."""
    rule = rule or Rule()
    problems: list[str] = []
    plain = _blank_fences(text)
    if PROTOTYPE_LABEL not in text:
        problems.append(f"{name}: the prototype label is missing")
    if "Synthetic data only" not in text:
        problems.append(f"{name}: 'Synthetic data only' is missing")
    if not any(STATUS.match(line) for line in text.splitlines()[:8]):
        problems.append(f"{name}: a 'Status: **built|document-only|mocked**' line is missing near the top")
    if not re.search(r"(?m)^## Limits\s*$", text):
        problems.append(f"{name}: a '## Limits' section is missing")
    for found in TAG.finditer(plain):
        kind, body = found.group(1), found.group(2)
        line_no = plain[: found.start()].count("\n") + 1
        refs = REF.findall(body)
        if not body.strip():
            problems.append(f"{name}:{line_no}: the {kind} tag is empty")
            continue
        if kind == "proof" and not any("::" in r for r in refs):
            problems.append(f"{name}:{line_no}: a proof tag names no test (needs `path::test_name`)")
        if kind == "policy" and not refs:
            problems.append(f"{name}:{line_no}: a policy tag names no file")
        for ref in refs:
            why = _check_ref(ref, root)
            if why:
                problems.append(f"{name}:{line_no}: {why}")
    for block in blocks(text):
        has_tag = bool(TAG.search(block.text))
        if block.kind in ("item", "row"):
            if not has_tag and not block.text.startswith("Your part:"):
                problems.append(f"{name}:{block.line}: no proof or policy tag on: {_snippet(block.text)}")
        elif not has_tag and CLAIM_WORDS.search(block.text):
            problems.append(
                f"{name}:{block.line}: a paragraph talks about the system with no tag: {_snippet(block.text)}"
            )
    for sentence in _overclaims(plain):
        problems.append(f"{name}: over-claim: {sentence[:90]}")
    for n, line in enumerate(plain.splitlines(), start=1):
        if re.search(r"\$\s?\d", line):
            problems.append(f"{name}:{n}: a money figure; none is allowed")
        if "%" in line and "fixture-based" not in line:
            problems.append(f"{name}:{n}: a percentage without the words fixture-based on the same line")
    body_text = reading_text(text)
    if rule.words_max is not None and word_count(body_text) > rule.words_max:
        problems.append(f"{name}: {word_count(body_text)} words is more than one page ({rule.words_max})")
    if rule.grade_max is not None and reading_grade(body_text) > rule.grade_max:
        problems.append(f"{name}: reading grade {reading_grade(body_text):.1f} is above {rule.grade_max:g}")
    return problems


def check_all(root: Path = REPO_ROOT) -> list[str]:
    problems: list[str] = []
    for rel, rule in DOCS.items():
        path = root / rel
        if not path.is_file():
            problems.append(f"{rel}: missing")
            continue
        problems += check_doc(path.read_text(encoding="utf-8"), root, rel, rule)
    return problems
