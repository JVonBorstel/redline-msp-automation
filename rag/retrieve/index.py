"""A ready-to-search index of the synthetic corpus in ``fixtures/kb/`` (B-57)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.paths import REPO_ROOT
from rag.ingest import IngestJob, IngestReport, ingest, load_kb
from rag.store import Embedder, HashEmbedder, InMemoryStore, VectorStore

KB_ROOT = REPO_ROOT / "fixtures" / "kb"
AS_OF = "2026-10-27"  # stamped into provenance; the clock is never read
EMBED_DIM = 1024  # the stand-in at 1024 dimensions: fewer hash collisions than the 64 default, still word overlap


@dataclass(frozen=True, slots=True)
class Index:
    """A store with its embedder and the ingestion reports that built it."""

    store: VectorStore
    embedder: Embedder
    reports: tuple[IngestReport, ...] = ()


def build_index(
    kb_root: Path = KB_ROOT, *, store: VectorStore | None = None, embedder: Embedder | None = None
) -> Index:
    """Ingest every scope under ``kb_root`` (one job per scope, so each lands in its own namespace)."""
    store = InMemoryStore() if store is None else store
    embedder = HashEmbedder(EMBED_DIM) if embedder is None else embedder
    reports = tuple(
        ingest(IngestJob(f"kb-{scope.name}", scope.client, AS_OF), scope.sources, store, embedder)
        for scope in load_kb(kb_root)
    )
    return Index(store, embedder, reports)
