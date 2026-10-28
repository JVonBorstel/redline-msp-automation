"""Ingestion pipeline (B-56): refuse, redact, chunk, scan, embed, store.

For each source, in this order:

1. metadata must be sane, the text non-empty, the source id new in this job;
2. a source tagged or located as a credential vault is refused (W-KB-07) before its text is read;
3. the redaction gate (B-55) runs on the title and the text: DC-6 shapes anywhere refuse the whole source; every other
   sensitive span becomes a typed placeholder, so nothing downstream (chunker, tripwire, embedder, store) sees it;
4. the redacted text is chunked, and each chunk is scanned with the injection tripwire (B-79 detector) and classified;
5. flagged chunks are stored as records with the flag but no text and no vector; the rest are embedded and stored.

The namespace is ``job.namespace``. Nothing in a source can change it.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from core.guard.classify import DataClass
from core.guard.redact_prompt import redact_prompt
from rag.ingest.chunking import chunk_spans
from rag.ingest.models import (
    DEFAULT_MAX_CHARS,
    MIN_MAX_CHARS,
    PIPELINE_VERSION,
    IngestError,
    IngestJob,
    IngestReport,
    Source,
    SourceResult,
)
from rag.ingest.screen import flag_chunks, has_valid_metadata, is_vault_source
from rag.store.embed import Embedder
from rag.store.memory import VectorStore
from rag.store.models import Chunk, Provenance, make_chunk_id


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _refuse(source_id: str, reason: str) -> SourceResult:
    return SourceResult(source_id=source_id, status="refused", reason=reason)


def _embed(embedder: Embedder, texts: Sequence[str]) -> list[tuple[float, ...]]:
    if not texts:
        return []
    vectors = [tuple(float(x) for x in v) for v in embedder.embed(texts)]
    if len(vectors) != len(texts) or any(len(v) != embedder.dim or not all(map(math.isfinite, v)) for v in vectors):
        raise IngestError("the embedder returned vectors of the wrong number, size or value")
    return vectors


def ingest(
    job: IngestJob,
    sources: Sequence[Source],
    store: VectorStore,
    embedder: Embedder,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> IngestReport:
    """Ingest ``sources`` into the job's namespace. Re-ingesting a source replaces its chunks.

    Refusals are reported per source and never raise. Only an unusable job, chunk size or embedder raises
    ``IngestError``, before that source's chunks are written.
    """
    if max_chars < MIN_MAX_CHARS:
        raise IngestError(f"max_chars must be at least {MIN_MAX_CHARS}")
    namespace = job.namespace
    seen: set[str] = set()
    results: list[SourceResult] = []
    for source in sources:
        if source.source_id in seen:
            results.append(_refuse(source.source_id, "duplicate-source-id"))
            continue
        results.append(_ingest_one(job, source, store, embedder, max_chars, namespace))
        seen.add(source.source_id)
    return IngestReport(job_id=job.job_id, namespace=namespace, results=tuple(results))


def _ingest_one(
    job: IngestJob, source: Source, store: VectorStore, embedder: Embedder, max_chars: int, namespace: str
) -> SourceResult:
    if not has_valid_metadata(source):
        return _refuse(source.source_id, "invalid-source")

    def drop(reason: str) -> SourceResult:
        store.replace_source(namespace, source.source_id, [])  # a source that is now refused must not linger
        return _refuse(source.source_id, reason)

    if is_vault_source(source):
        return drop("vault-source")
    title_gate = redact_prompt(source.title.strip(), client=job.record, declared=DataClass.DC0)
    gate = redact_prompt(source.text, client=job.record, declared=source.declared_class)
    if title_gate.blocked or gate.blocked:
        return drop("secret-shape")
    document = gate.text
    spans = chunk_spans(document, max_chars)
    if not spans:
        return drop("empty-source")

    texts = [document[s:e] for s, e in spans]
    flags = flag_chunks(texts, source.text, max_chars)
    vectors = iter(_embed(embedder, [t for t, f in zip(texts, flags, strict=True) if not f]))
    doc_sha = _sha256(document)
    chunks: list[Chunk] = []
    for index, ((start, end), text, rules) in enumerate(zip(spans, texts, flags, strict=True)):
        text_sha = _sha256(text)
        provenance = Provenance(
            source_id=source.source_id,
            article_id=source.article_id,
            title=title_gate.text,
            origin=source.origin,
            job_id=job.job_id,
            as_of=job.as_of,
            doc_sha256=doc_sha,
            chunk_index=index,
            chunk_count=len(spans),
            char_start=start,
            char_end=end,
            embedder_id=embedder.id,
            pipeline=PIPELINE_VERSION,
        )
        flagged = bool(rules)
        chunks.append(
            Chunk(
                chunk_id=make_chunk_id(namespace, source.source_id, index, text_sha),
                namespace=namespace,
                text="" if flagged else text,
                data_class=gate.data_class,
                flagged=flagged,
                flag_rules=rules,
                text_sha256=text_sha,
                vector=() if flagged else next(vectors),
                provenance=provenance,
            )
        )
    store.replace_source(namespace, source.source_id, chunks)
    withheld = sum(c.flagged for c in chunks)
    return SourceResult(
        source_id=source.source_id,
        status="indexed",
        reason="",
        chunks_indexed=len(chunks) - withheld,
        chunks_withheld=withheld,
        data_class=gate.data_class,
        redacted=gate.redacted,
        flag_rules=tuple(sorted({r for c in chunks for r in c.flag_rules})),
    )
