"""Ingestion inputs and outputs (B-56): the job, a source document, and the report.

The job decides the namespace. A ``Source`` has no client field on purpose: nothing about a document (its text, its
title, its tags) can send it to a namespace.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from typing import Any

from core.audit.router import valid_client_id
from core.guard.classify import ClientRecord, DataClass
from rag.store.models import MSP_INTERNAL, client_namespace

PIPELINE_VERSION = "b56/1"
DEFAULT_MAX_CHARS = 600
MIN_MAX_CHARS = 20

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class IngestError(ValueError):
    """The job itself is unusable (bad client id, date, record, chunk size or embedder). Nothing is written."""


@dataclass(frozen=True, slots=True)
class IngestJob:
    """One ingestion run for one client, or for the MSP's own documents (``client=None``).

    ``as_of`` is the date stamped into provenance (YYYY-MM-DD); the wall clock is never read. ``record`` is the
    client's record when the caller has it: its industry sets the data-class floor for undeclared text (D6-12).
    """

    job_id: str
    client: str | None
    as_of: str
    record: ClientRecord | None = None

    def __post_init__(self) -> None:
        if not SAFE_ID.fullmatch(self.job_id):
            raise IngestError("job_id is not a safe id")
        if self.client is not None and (not valid_client_id(self.client) or self.client == MSP_INTERNAL):
            raise IngestError("client is not a usable client id")
        if not _DATE.fullmatch(self.as_of):
            raise IngestError("as_of must be a YYYY-MM-DD date")
        try:
            datetime.date.fromisoformat(self.as_of)
        except ValueError as exc:
            raise IngestError("as_of is not a real date") from exc
        if self.record is not None and self.record.id != self.client:
            raise IngestError("the client record is not this job's client")

    @property
    def namespace(self) -> str:
        return MSP_INTERNAL if self.client is None else client_namespace(self.client)


@dataclass(frozen=True, slots=True)
class Source:
    """One document to ingest. ``article_id`` is what an answer will cite; ``origin`` says where it was read from."""

    source_id: str
    article_id: str
    title: str
    text: str
    tags: tuple[str, ...] = ()
    origin: str = ""
    declared_class: DataClass | None = None


@dataclass(frozen=True, slots=True)
class SourceResult:
    """What happened to one source. Names kinds and rule ids only, never a value from the document."""

    source_id: str
    status: str  # "indexed" or "refused"
    reason: str  # "" when indexed
    chunks_indexed: int = 0
    chunks_withheld: int = 0
    data_class: DataClass | None = None
    redacted: tuple[str, ...] = ()
    flag_rules: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "status": self.status,
            "reason": self.reason,
            "chunks_indexed": self.chunks_indexed,
            "chunks_withheld": self.chunks_withheld,
            "data_class": None if self.data_class is None else self.data_class.label,
            "redacted": list(self.redacted),
            "flag_rules": list(self.flag_rules),
        }


@dataclass(frozen=True, slots=True)
class IngestReport:
    job_id: str
    namespace: str
    results: tuple[SourceResult, ...]

    @property
    def indexed(self) -> int:
        return sum(r.status == "indexed" for r in self.results)

    @property
    def refused(self) -> int:
        return sum(r.status == "refused" for r in self.results)

    @property
    def chunks_indexed(self) -> int:
        return sum(r.chunks_indexed for r in self.results)

    @property
    def chunks_withheld(self) -> int:
        return sum(r.chunks_withheld for r in self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "namespace": self.namespace,
            "indexed": self.indexed,
            "refused": self.refused,
            "chunks_indexed": self.chunks_indexed,
            "chunks_withheld": self.chunks_withheld,
            "results": [r.to_dict() for r in self.results],
        }
