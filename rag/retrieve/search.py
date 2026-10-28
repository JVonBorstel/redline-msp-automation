"""``search``: passages for one caller, from the caller's client namespace and ``msp-internal`` only (B-57).

The namespace list is built here from the caller's client id and handed to the store, which applies it; nothing is
filtered afterwards. As a second check the result is verified and the call fails closed if a store returned a chunk
from any other namespace (a broken store must be loud, never quietly leak).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rag.store import MSP_INTERNAL, Embedder, VectorStore, client_namespace

DEFAULT_K = 5
MAX_QUERY_CHARS = 300


@dataclass(frozen=True, slots=True)
class Passage:
    """One retrieved passage: what to show, what to cite (``chunk_id``, ``article_id``) and how well it matched."""

    chunk_id: str
    article_id: str
    title: str
    text: str
    score: float
    source_id: str
    scope: str  # "client" or "msp-internal"; never the client's name
    char_start: int
    char_end: int
    namespace: str

    def to_dict(self) -> dict[str, Any]:
        """The shape the ``rag.search`` lever returns. The namespace stays out: ``scope`` says enough."""
        return {
            "chunk_id": self.chunk_id,
            "article_id": self.article_id,
            "title": self.title,
            "text": self.text,
            "score": round(self.score, 4),
            "source_id": self.source_id,
            "scope": self.scope,
            "char_start": self.char_start,
            "char_end": self.char_end,
        }


def caller_namespaces(client: str) -> list[str]:
    """The only two namespaces a caller may read. Raises ValueError for anything that is not a usable client id."""
    return [client_namespace(client), MSP_INTERNAL]


def search(store: VectorStore, embedder: Embedder, client: str, query: str, *, k: int = DEFAULT_K) -> list[Passage]:
    """The ``k`` best passages for ``query`` from ``client``'s namespace and ``msp-internal``, best first."""
    namespaces = caller_namespaces(client)
    if not isinstance(query, str) or not query.strip():
        raise ValueError("the query is empty")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"the query is longer than {MAX_QUERY_CHARS} characters")
    if k < 1:
        raise ValueError("k must be at least 1")
    vector = embedder.embed([query])[0]
    passages: list[Passage] = []
    for hit in store.search(vector, namespaces=namespaces, k=k):
        chunk = hit.chunk
        if chunk.namespace not in namespaces:
            raise RuntimeError("the store returned a passage from a namespace the caller may not read")
        if chunk.flagged:
            raise RuntimeError("the store returned a withheld passage")
        prov = chunk.provenance
        passages.append(
            Passage(
                chunk_id=chunk.chunk_id,
                article_id=prov.article_id,
                title=prov.title,
                text=chunk.text,
                score=hit.score,
                source_id=prov.source_id,
                scope=MSP_INTERNAL if chunk.namespace == MSP_INTERNAL else "client",
                char_start=prov.char_start,
                char_end=prov.char_end,
                namespace=chunk.namespace,
            )
        )
    return passages
