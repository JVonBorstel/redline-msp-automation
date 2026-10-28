"""The vector store interface and an in-memory implementation (B-56).

Isolation is enforced here, in the store: ``search`` takes the namespaces the caller may read and looks at nothing
else, so a caller cannot filter after the fact by mistake. An empty namespace list returns nothing; a malformed
namespace (blank, wildcard, wrong shape) raises instead of being guessed at.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from typing import Any, Protocol, runtime_checkable

from rag.store.models import Chunk, Hit, make_chunk_id, valid_namespace


@runtime_checkable
class VectorStore(Protocol):
    """What ingestion writes to and retrieval reads from. Real vector databases are adapters behind this."""

    def add(self, chunks: Iterable[Chunk]) -> None: ...

    def replace_source(self, namespace: str, source_id: str, chunks: Sequence[Chunk]) -> None: ...

    def search(self, vector: Sequence[float], *, namespaces: Collection[str], k: int = 5) -> list[Hit]: ...

    def chunks(self, namespace: str) -> list[Chunk]: ...

    def namespaces(self) -> list[str]: ...

    def count(self, namespace: str) -> int: ...

    def dump(self) -> list[dict[str, Any]]: ...


class InMemoryStore:
    """Namespaced in-memory store. Chunks are validated before any of them is written (all or nothing)."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Chunk]] = {}
        self._dim = 0

    # ---- writes ----

    def _validate(self, chunk: Chunk, dim: int) -> int:
        if not valid_namespace(chunk.namespace):
            raise ValueError("chunk has a malformed namespace")
        expected = make_chunk_id(
            chunk.namespace, chunk.provenance.source_id, chunk.provenance.chunk_index, chunk.text_sha256
        )
        if chunk.chunk_id != expected:
            raise ValueError("chunk id does not match its namespace, source and text")
        if chunk.flagged and (chunk.text or chunk.vector):
            raise ValueError("a withheld chunk must carry no text and no vector")
        if not chunk.flagged:
            if not chunk.vector:
                raise ValueError("an indexed chunk needs a vector")
            if dim and len(chunk.vector) != dim:
                raise ValueError("vector size differs from the store's")
            dim = len(chunk.vector)
        return dim

    def _check(self, chunks: Sequence[Chunk]) -> int:
        dim = self._dim
        for chunk in chunks:
            dim = self._validate(chunk, dim)
        return dim

    def add(self, chunks: Iterable[Chunk]) -> None:
        batch = list(chunks)
        dim = self._check(batch)
        for chunk in batch:
            self._data.setdefault(chunk.namespace, {})[chunk.chunk_id] = chunk
        self._dim = dim

    def replace_source(self, namespace: str, source_id: str, chunks: Sequence[Chunk]) -> None:
        """Atomically replace every chunk of one source in one namespace (an empty list removes the source)."""
        if not valid_namespace(namespace):
            raise ValueError("malformed namespace")
        if any(c.namespace != namespace or c.provenance.source_id != source_id for c in chunks):
            raise ValueError("chunks do not belong to that namespace and source")
        dim = self._check(chunks)
        space = self._data.get(namespace, {})
        for chunk_id in [i for i, c in space.items() if c.provenance.source_id == source_id]:
            del space[chunk_id]
        for chunk in chunks:
            space[chunk.chunk_id] = chunk
        if space:
            self._data[namespace] = space
        else:
            self._data.pop(namespace, None)
        self._dim = dim

    # ---- reads ----

    def search(self, vector: Sequence[float], *, namespaces: Collection[str], k: int = 5) -> list[Hit]:
        """The ``k`` best indexed chunks, from the named namespaces only. Withheld chunks are never returned."""
        wanted = list(dict.fromkeys(namespaces))
        for namespace in wanted:
            if not valid_namespace(namespace):
                raise ValueError("malformed namespace")
        if k < 1:
            raise ValueError("k must be at least 1")
        hits: list[Hit] = []
        for namespace in wanted:
            for chunk in self._data.get(namespace, {}).values():
                if chunk.flagged:
                    continue
                if len(chunk.vector) != len(vector):
                    raise ValueError("query vector size differs from the store's")
                hits.append(Hit(chunk, sum(a * b for a, b in zip(chunk.vector, vector, strict=True))))
        hits.sort(key=lambda h: (-h.score, h.chunk.chunk_id))
        return hits[:k]

    def chunks(self, namespace: str) -> list[Chunk]:
        """Every chunk record in one namespace, withheld ones included, in document order."""
        if not valid_namespace(namespace):
            raise ValueError("malformed namespace")
        found = self._data.get(namespace, {}).values()
        return sorted(found, key=lambda c: (c.provenance.source_id, c.provenance.chunk_index))

    def namespaces(self) -> list[str]:
        return sorted(ns for ns, space in self._data.items() if space)

    def count(self, namespace: str) -> int:
        return len(self.chunks(namespace))

    def dump(self) -> list[dict[str, Any]]:
        return [c.to_dict() for ns in self.namespaces() for c in self.chunks(ns)]
