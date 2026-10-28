"""Vector store records, the store interface, and embedders (B-56)."""

from __future__ import annotations

from rag.store.embed import Embedder, HashEmbedder
from rag.store.memory import InMemoryStore, VectorStore
from rag.store.models import (
    CLIENT_PREFIX,
    MSP_INTERNAL,
    Chunk,
    Hit,
    Provenance,
    client_namespace,
    make_chunk_id,
    valid_namespace,
)

__all__ = [
    "CLIENT_PREFIX",
    "MSP_INTERNAL",
    "Chunk",
    "Embedder",
    "HashEmbedder",
    "Hit",
    "InMemoryStore",
    "Provenance",
    "VectorStore",
    "client_namespace",
    "make_chunk_id",
    "valid_namespace",
]
