"""Namespaces, chunks and provenance: the records the vector store holds (B-56).

A namespace is the unit of isolation. ``client:<id>`` holds one client's documents and nothing else; ``msp-internal``
holds the MSP's own documents (runbooks, templates) and no client's. The namespace is always chosen by the ingestion
job's client (``rag.ingest``), never by a document's text, and a store only ever searches the namespaces the caller
names (B-57 passes the caller's client and ``msp-internal``).

A chunk's id is derived from its namespace, so a chunk copied into another namespace no longer matches its id and the
store refuses it.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

from core.audit.router import valid_client_id
from core.guard.classify import DataClass

MSP_INTERNAL = "msp-internal"
CLIENT_PREFIX = "client:"


def client_namespace(client: str) -> str:
    """The namespace of one client. Raises ValueError when ``client`` is not a safe client id."""
    if not valid_client_id(client) or client == MSP_INTERNAL:
        raise ValueError("not a usable client id")
    return CLIENT_PREFIX + client


def valid_namespace(namespace: object) -> bool:
    """True for ``msp-internal`` and for ``client:<safe client id>``; nothing else (no wildcards, no blanks)."""
    if namespace == MSP_INTERNAL:
        return True
    if not isinstance(namespace, str) or not namespace.startswith(CLIENT_PREFIX):
        return False
    client = namespace[len(CLIENT_PREFIX) :]
    return valid_client_id(client) and client != MSP_INTERNAL


def make_chunk_id(namespace: str, source_id: str, index: int, text_sha256: str) -> str:
    """Deterministic chunk id (``ch-`` and 20 hex digits) bound to the namespace, source, position and text."""
    digest = hashlib.sha256("\x1f".join((namespace, source_id, str(index), text_sha256)).encode("utf-8"))
    return "ch-" + digest.hexdigest()[:20]


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a chunk came from. Offsets are character offsets into the redacted document, not the original."""

    source_id: str
    article_id: str
    title: str  # redacted
    origin: str
    job_id: str
    as_of: str  # the job's date, never the wall clock
    doc_sha256: str  # SHA-256 of the redacted document
    chunk_index: int
    chunk_count: int
    char_start: int
    char_end: int
    embedder_id: str
    pipeline: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Chunk:
    """One indexed passage, or a withheld one.

    A withheld chunk (``flagged``) was recognised as injection-like. It is kept as a record with its flag, rule ids,
    provenance and the hash of its text, but ``text`` is empty and it has no vector, so it is never retrievable.
    """

    chunk_id: str
    namespace: str
    text: str  # redacted; empty when withheld
    data_class: DataClass
    flagged: bool
    flag_rules: tuple[str, ...]
    text_sha256: str
    vector: tuple[float, ...]
    provenance: Provenance

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "namespace": self.namespace,
            "text": self.text,
            "data_class": self.data_class.label,
            "flagged": self.flagged,
            "flag_rules": list(self.flag_rules),
            "text_sha256": self.text_sha256,
            "vector": list(self.vector),
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class Hit:
    """One search result: the chunk (with its provenance) and its cosine score."""

    chunk: Chunk
    score: float
