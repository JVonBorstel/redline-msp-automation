"""RAG ingestion: refuse vault material, redact, chunk, scan for injection, embed, store (B-56)."""

from __future__ import annotations

from rag.ingest.corpus import KbScope, load_kb
from rag.ingest.models import (
    DEFAULT_MAX_CHARS,
    PIPELINE_VERSION,
    IngestError,
    IngestJob,
    IngestReport,
    Source,
    SourceResult,
)
from rag.ingest.pipeline import ingest

__all__ = [
    "DEFAULT_MAX_CHARS",
    "PIPELINE_VERSION",
    "IngestError",
    "IngestJob",
    "IngestReport",
    "KbScope",
    "Source",
    "SourceResult",
    "ingest",
    "load_kb",
]
