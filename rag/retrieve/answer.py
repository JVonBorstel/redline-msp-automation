"""Cited, extractive answers with a refusal (B-57).

An answer is built only from sentences quoted word for word from retrieved passages. Each sentence ends with the
chunk id(s) it was quoted from, so nothing in an answer lacks a source and nothing is paraphrased. If no sentence
scores at least ``threshold`` against the question, the answer is exactly ``no source found`` and cites nothing.

The score is the cosine similarity between the question and a sentence under the caller's embedder. With the offline
``HashEmbedder`` stand-in that is word overlap, not meaning (see ``specs/B-57.md``). ``ANSWER_THRESHOLD`` is the value
the eval in ``evals/rag/`` picked on the synthetic questions; ``check_answer`` re-verifies any answer text.

Defence in depth: each candidate sentence is scanned again with the injection tripwire, so a passage that reached the
index before a rule existed (or by another route) still cannot be quoted as an instruction. A suppressed sentence is
counted in ``Answer.suppressed``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from core.guard.detect import detect_injection
from rag.retrieve.search import DEFAULT_K, Passage, search
from rag.store import Embedder, VectorStore

NO_SOURCE = "no source found"
ANSWER_THRESHOLD = 0.38  # chosen by evals/rag (see evals/rag/threshold.json); a test pins them together
DEFAULT_MAX_SENTENCES = 3
MIN_WORDS = 3

STOPWORDS = frozenset(
    "a an and are as at be been but by can could did do does for from had has have how i if in is it its me my no "
    "not of "
    "on or our out should so than that the their them then there these they this to up us was we were what when where "
    "which who why will with would you your".split()
)
_TOKEN = re.compile(r"[a-z0-9]+")
_SPLIT = re.compile(r"(?<=[.!?])\s+")
_CITED = re.compile(r"^(?P<sentence>.*\S)\s*(?P<ids>(?:\[ch-[0-9a-f]{20}\]\s*)+)$", re.DOTALL)
_ID = re.compile(r"\[(ch-[0-9a-f]{20})\]")


def _squash(text: str) -> str:
    return " ".join(text.split())


def content_words(text: str) -> str:
    """The text with common function words removed: what is embedded for scoring (the quoted sentence is unchanged)."""
    return " ".join(w for w in _TOKEN.findall(text.lower()) if w not in STOPWORDS)


@dataclass(frozen=True, slots=True)
class ScoredSentence:
    text: str
    score: float
    passage: Passage


@dataclass(frozen=True, slots=True)
class AnswerSentence:
    """One quoted sentence and the chunk ids it comes from."""

    text: str
    chunk_ids: tuple[str, ...]
    score: float

    def render(self) -> str:
        return self.text + " " + " ".join(f"[{i}]" for i in self.chunk_ids)


@dataclass(frozen=True, slots=True)
class Citation:
    chunk_id: str
    article_id: str
    title: str


@dataclass(frozen=True, slots=True)
class Answer:
    question: str
    client: str
    threshold: float
    sentences: tuple[AnswerSentence, ...]
    passages: tuple[Passage, ...]
    suppressed: int = 0
    top_score: float = 0.0  # best sentence score seen, whether or not it reached the threshold

    @property
    def refused(self) -> bool:
        return not self.sentences

    @property
    def text(self) -> str:
        return "\n".join(s.render() for s in self.sentences) if self.sentences else NO_SOURCE

    @property
    def citations(self) -> tuple[Citation, ...]:
        by_id = {p.chunk_id: p for p in self.passages}
        seen: dict[str, Citation] = {}
        for sentence in self.sentences:
            for chunk_id in sentence.chunk_ids:
                passage = by_id[chunk_id]
                seen.setdefault(chunk_id, Citation(chunk_id, passage.article_id, passage.title))
        return tuple(seen.values())


def candidates(
    store: VectorStore, embedder: Embedder, client: str, question: str, *, k: int = DEFAULT_K
) -> tuple[tuple[Passage, ...], list[ScoredSentence], int]:
    """Retrieve, split into sentences, score each against the question, drop tripwire hits. Best first."""
    passages = tuple(search(store, embedder, client, question, k=k))
    pieces: list[tuple[str, Passage]] = []
    for passage in passages:
        for line in passage.text.split("\n"):
            for part in _SPLIT.split(line):
                sentence = _squash(part)
                if len(sentence.split()) >= MIN_WORDS:
                    pieces.append((sentence, passage))
    if not pieces:
        return passages, [], 0
    question_vector = embedder.embed([content_words(question)])[0]
    vectors = embedder.embed([content_words(s) for s, _ in pieces])
    scored: list[ScoredSentence] = []
    suppressed = 0
    for (sentence, passage), vector in zip(pieces, vectors, strict=True):
        if detect_injection(sentence).flagged:
            suppressed += 1
            continue
        score = sum(a * b for a, b in zip(vector, question_vector, strict=True))
        scored.append(ScoredSentence(sentence, score, passage))
    scored.sort(key=lambda s: (-s.score, s.passage.chunk_id, s.text))
    return passages, scored, suppressed


def answer(
    store: VectorStore,
    embedder: Embedder,
    client: str,
    question: str,
    *,
    threshold: float = ANSWER_THRESHOLD,
    max_sentences: int = DEFAULT_MAX_SENTENCES,
    k: int = DEFAULT_K,
) -> Answer:
    """A cited answer for ``question`` from the caller's namespaces, or ``no source found``."""
    if threshold < 0:
        raise ValueError("threshold cannot be negative")
    if max_sentences < 1:
        raise ValueError("max_sentences must be at least 1")
    passages, scored, suppressed = candidates(store, embedder, client, question, k=k)
    chosen: list[AnswerSentence] = []
    seen: set[str] = set()
    for item in scored:
        if item.score < threshold or len(chosen) == max_sentences:
            break
        if item.text in seen:
            continue
        seen.add(item.text)
        chosen.append(AnswerSentence(item.text, (item.passage.chunk_id,), item.score))
    top = scored[0].score if scored else 0.0
    return Answer(question, client, threshold, tuple(chosen), passages, suppressed, top)


def check_answer(subject: Answer | str, passages: Sequence[Passage] | None = None) -> list[str]:
    """Problems found in an answer; an empty list means every sentence is cited and quoted from what it cites.

    Takes an ``Answer`` or its rendered text with the passages it was built from. ``no source found`` is valid only
    on its own: a refusal makes no claim and cannot carry a citation.
    """
    if isinstance(subject, Answer):
        text, available = subject.text, subject.passages
    else:
        text, available = subject, tuple(passages or ())
    stripped = text.strip()
    if not stripped:
        return ["the answer is empty"]
    if stripped == NO_SOURCE:
        return []
    if stripped.startswith(NO_SOURCE):
        return ["a refusal must not carry anything else, including a citation"]
    by_id = {p.chunk_id: _squash(p.text) for p in available}
    problems: list[str] = []
    for number, line in enumerate((ln for ln in text.split("\n") if ln.strip()), start=1):
        match = _CITED.match(line.strip())
        if match is None:
            problems.append(f"sentence {number} cites no chunk id")
            continue
        ids = _ID.findall(match.group("ids"))
        unknown = [i for i in ids if i not in by_id]
        if unknown:
            problems.append(f"sentence {number} cites a chunk that was not retrieved: {unknown[0]}")
            continue
        if not any(_squash(match.group("sentence")) in by_id[i] for i in ids):
            problems.append(f"sentence {number} is not quoted from the chunk it cites")
    return problems
