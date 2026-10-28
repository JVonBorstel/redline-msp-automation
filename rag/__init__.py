"""RAG ingestion with per-client namespaces and vault exclusion (B-56).

Public interface for retrieval and evals built on top (B-57):

- ``ingest(job, sources, store, embedder)``: put documents into the job's namespace; see ``specs/B-56.md``.
- ``InMemoryStore`` / ``VectorStore``: ``search(vector, namespaces=[...], k=...)`` filters by namespace in the store.
- ``HashEmbedder`` / ``Embedder``: the offline embedder stand-in and the interface real embedders plug into.
- ``client_namespace(client)`` and ``MSP_INTERNAL``: the only two kinds of namespace.
- ``load_kb(path)``: the synthetic corpus in ``fixtures/kb/``.
"""

from __future__ import annotations

from rag.ingest import (
    DEFAULT_MAX_CHARS,
    PIPELINE_VERSION,
    IngestError,
    IngestJob,
    IngestReport,
    KbScope,
    Source,
    SourceResult,
    ingest,
    load_kb,
)
from rag.store import (
    MSP_INTERNAL,
    Chunk,
    Embedder,
    HashEmbedder,
    Hit,
    InMemoryStore,
    Provenance,
    VectorStore,
    client_namespace,
    valid_namespace,
)

__all__ = [
    "DEFAULT_MAX_CHARS",
    "MSP_INTERNAL",
    "PIPELINE_VERSION",
    "Chunk",
    "Embedder",
    "HashEmbedder",
    "Hit",
    "InMemoryStore",
    "IngestError",
    "IngestJob",
    "IngestReport",
    "KbScope",
    "Provenance",
    "Source",
    "SourceResult",
    "VectorStore",
    "client_namespace",
    "ingest",
    "load_kb",
    "valid_namespace",
]
