"""Loader for the synthetic knowledge-base corpus in ``fixtures/kb/`` (B-56).

Layout: one folder per ingestion scope, ``fixtures/kb/<client-id>/manifest.json`` for a client and
``fixtures/kb/msp-internal/manifest.json`` for the MSP's own documents. The FOLDER NAME is the operator's choice of
scope and becomes the job's client; a manifest entry that names a client (or any other unknown key) is refused.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.audit.router import valid_client_id
from core.guard.classify import DataClass
from rag.ingest.models import IngestError, Source
from rag.store.models import MSP_INTERNAL

_KEYS = {"source_id", "article_id", "title", "tags", "origin", "declared_class", "paragraphs"}


@dataclass(frozen=True, slots=True)
class KbScope:
    """One folder of the corpus: its name, the job client it implies (None for the MSP), and its sources."""

    name: str
    client: str | None
    sources: tuple[Source, ...]


def _source(entry: Any, where: str) -> Source:
    if not isinstance(entry, dict) or set(entry) - _KEYS:
        raise IngestError(f"{where}: unknown or malformed source entry")
    try:
        declared = entry.get("declared_class")
        return Source(
            source_id=str(entry["source_id"]),
            article_id=str(entry["article_id"]),
            title=str(entry["title"]),
            text="\n\n".join(str(p) for p in entry["paragraphs"]),
            tags=tuple(str(t) for t in entry.get("tags", [])),
            origin=str(entry.get("origin", "")),
            declared_class=None if declared is None else DataClass.parse(str(declared)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise IngestError(f"{where}: source entry is incomplete or invalid") from exc


def load_kb(root: Path) -> tuple[KbScope, ...]:
    """Every scope folder under ``root`` with a ``manifest.json``, sorted by name."""
    scopes: list[KbScope] = []
    for folder in sorted(p for p in Path(root).iterdir() if (p / "manifest.json").is_file()):
        name = folder.name
        client = None if name == MSP_INTERNAL else name
        if client is not None and not valid_client_id(client):
            raise IngestError(f"{name}: folder name is not a usable client id")
        try:
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            entries = manifest["sources"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise IngestError(f"{name}: manifest.json is unreadable or has no sources") from exc
        scopes.append(KbScope(name, client, tuple(_source(e, f"{name}/manifest.json") for e in entries)))
    return tuple(scopes)
