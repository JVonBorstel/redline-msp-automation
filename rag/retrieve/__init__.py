"""Cited retrieval for the knowledge base (B-57).

- ``search(store, embedder, client, query, k=...)``: passages from the caller's client namespace and ``msp-internal``.
- ``answer(store, embedder, client, question)``: quoted sentences, each cited by chunk id, or ``no source found``.
- ``check_answer(answer)``: re-verifies that every sentence is cited and quoted from what it cites.
- ``build_index()``: the synthetic corpus of ``fixtures/kb/`` ingested with the B-56 pipeline.
"""

from __future__ import annotations

from rag.retrieve.answer import (
    ANSWER_THRESHOLD,
    DEFAULT_MAX_SENTENCES,
    NO_SOURCE,
    Answer,
    AnswerSentence,
    Citation,
    ScoredSentence,
    answer,
    candidates,
    check_answer,
)
from rag.retrieve.index import AS_OF, EMBED_DIM, KB_ROOT, Index, build_index
from rag.retrieve.search import DEFAULT_K, MAX_QUERY_CHARS, Passage, caller_namespaces, search

__all__ = [
    "ANSWER_THRESHOLD",
    "AS_OF",
    "EMBED_DIM",
    "DEFAULT_K",
    "DEFAULT_MAX_SENTENCES",
    "KB_ROOT",
    "MAX_QUERY_CHARS",
    "NO_SOURCE",
    "Answer",
    "AnswerSentence",
    "Citation",
    "Index",
    "Passage",
    "ScoredSentence",
    "answer",
    "build_index",
    "caller_namespaces",
    "candidates",
    "check_answer",
    "search",
]
