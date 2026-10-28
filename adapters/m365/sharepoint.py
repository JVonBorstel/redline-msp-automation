"""SharePoint document source for RAG ingestion (B-88, B88-2). MOCK; reads a synthetic fixture, calls nothing.

UNVERIFIED: the library and item shape (``siteId``, ``siteName``, ``driveName``, items with ``id``, ``name``, ``path``,
``mimeType``, ``lastModifiedDateTime``, ``eTag``) is modelled loosely on Graph ``driveItem`` from memory; the ``text``
field is a mock convenience (a real source would download and extract content). No Microsoft page was opened.

One adapter is one client: it is built from that client's binding, the fixture's ``client`` and ``tenantId`` must match
it, and ``ingest_sharepoint`` refuses a job for any other client (or for the MSP) before anything is written. The
namespace is the job's (B-56); nothing in an item, its name or its text can change it, and ``Source`` has no
client field.

The adapter only decides WHICH items become sources. Everything that decides what may be stored stays in the B-56
pipeline: vault sources are refused (the library, site and path names go into the source's tags and origin, so a
credentials library is refused there), DC-6 secret shapes refuse the document, other personal data is redacted,
and injection-like chunks are stored withheld. Items the adapter cannot take are skipped with a reason code and
counted, never guessed at.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters.base import Adapter, AdapterError, AdapterResult
from adapters.binding import CLIENT_ID, BoundBinding
from adapters.m365.text import one_line
from core.paths import REPO_ROOT
from rag import DEFAULT_MAX_CHARS, Embedder, IngestError, IngestJob, IngestReport, Source, VectorStore, ingest

DEFAULT_SHAREPOINT_DIR = REPO_ROOT / "adapters" / "m365" / "fixtures"
TEXT_TYPES = frozenset({"text/plain", "text/markdown"})
MAX_TEXT_CHARS = 200_000
MAX_NAME_CHARS = 200
_ITEM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,150}")
_ORIGIN_UNSAFE = re.compile(r"[^A-Za-z0-9._:/ #~@+=-]")


def _origin(site: str, drive: str, path: str) -> str:
    """A path-like origin that carries every name the item sits under, so a vault word anywhere in it is seen."""
    joined = "sharepoint:/" + "/".join((one_line(site, 60), one_line(drive, 60), one_line(path, 150)))
    return _ORIGIN_UNSAFE.sub("_", joined)


class SharePointMock(Adapter):
    """One client's document libraries, read once at construction from ``<root>/<client>.json``."""

    system = "m365"

    def __init__(self, client: str, binding: BoundBinding, root: Path = DEFAULT_SHAREPOINT_DIR) -> None:
        super().__init__(client, binding)
        if binding.implementation != "mock":
            raise AdapterError("SharePointMock serves the 'mock' implementation only")
        if not CLIENT_ID.fullmatch(client):
            raise AdapterError("invalid client id; adapter not built")
        try:
            data = json.loads((Path(root) / f"{client}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AdapterError(f"no readable SharePoint fixture for this client ({type(exc).__name__})") from exc
        if (
            not isinstance(data, dict)
            or data.get("client") != client
            or str(data.get("tenantId")) != binding.external_id
            or not isinstance(data.get("libraries"), list)
        ):
            raise AdapterError("SharePoint fixture does not belong to this client's tenant binding; adapter not built")
        self._sources: tuple[Source, ...]
        self._skipped: tuple[tuple[str, str], ...]
        self._sources, self._skipped = self._read(data["libraries"])

    @classmethod
    def for_fixture(cls, client: str, root: Path = DEFAULT_SHAREPOINT_DIR) -> SharePointMock:
        """Build from the fixture's own tenant id (tests and the CLI; a real run uses the client's binding)."""
        if not CLIENT_ID.fullmatch(client):
            raise AdapterError("invalid client id; adapter not built")
        try:
            data = json.loads((Path(root) / f"{client}.json").read_text(encoding="utf-8"))
            tenant = str(data["tenantId"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise AdapterError(f"no readable SharePoint fixture for this client ({type(exc).__name__})") from exc
        return cls(client, BoundBinding(client, "m365", "mock", tenant), root)

    @property
    def skipped(self) -> tuple[tuple[str, str], ...]:
        """``(position, reason code)`` per item not taken. Positions are ``library/item`` indexes, never text."""
        return self._skipped

    def sources(self) -> AdapterResult[list[Source]]:
        """Every item that can be ingested, as a ``Source`` (no client field), in fixture order."""
        return self._guard(lambda: AdapterResult.success(list(self._sources)))

    # -- internals ------------------------------------------------------------------------

    def _read(self, libraries: Sequence[Any]) -> tuple[tuple[Source, ...], tuple[tuple[str, str], ...]]:
        sources: list[Source] = []
        skipped: list[tuple[str, str]] = []
        seen: set[str] = set()
        for li, lib in enumerate(libraries):
            items = lib.get("items") if isinstance(lib, dict) else None
            if not isinstance(items, list):
                skipped.append((f"{li}", "malformed"))
                continue
            site, drive = str(lib.get("siteName", "")), str(lib.get("driveName", ""))
            for ii, item in enumerate(items):
                where = f"{li}/{ii}"
                source, reason = self._source(item, site, drive, seen)
                if source is None:
                    skipped.append((where, reason))
                else:
                    sources.append(source)
        return tuple(sources), tuple(skipped)

    @staticmethod
    def _source(item: Any, site: str, drive: str, seen: set[str]) -> tuple[Source | None, str]:
        if not isinstance(item, dict):
            return None, "malformed"
        item_id = item.get("id")
        if not isinstance(item_id, str) or not _ITEM_ID.fullmatch(item_id):
            return None, "unsafe-id"
        if item_id in seen:
            return None, "duplicate-id"
        seen.add(item_id)
        if item.get("mimeType") not in TEXT_TYPES:
            return None, "unsupported-type"
        raw_name = item.get("name")
        if not isinstance(raw_name, str) or len(raw_name) > MAX_NAME_CHARS:
            return None, "bad-name"
        title = one_line(raw_name, MAX_NAME_CHARS)
        if not title:
            return None, "bad-name"
        text = item.get("text")
        if not isinstance(text, str):
            return None, "no-text"
        if not text.strip():
            return None, "empty"
        if len(text) > MAX_TEXT_CHARS:
            return None, "too-large"
        path = item.get("path")
        tags = ["sharepoint"]
        drive_tag = one_line(drive, 100)
        if drive_tag:
            tags.append(drive_tag)
        return (
            Source(
                source_id="sp-" + item_id,
                article_id="SP-" + item_id,
                title=title,
                text=text,
                tags=tuple(tags),
                origin=_origin(site, drive, path if isinstance(path, str) else raw_name),
            ),
            "",
        )


@dataclass(frozen=True, slots=True)
class SharePointIngestReport:
    """The B-56 report for the job plus the items the adapter skipped (reason codes only)."""

    ingest: IngestReport
    skipped: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {**self.ingest.to_dict(), "skipped": [{"item": i, "reason": r} for i, r in self.skipped]}


def ingest_sharepoint(
    adapter: SharePointMock,
    job: IngestJob,
    store: VectorStore,
    embedder: Embedder,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> SharePointIngestReport:
    """Ingest the adapter's items into the job's namespace; the job's client must be the adapter's (``IngestError``)."""
    if job.client != adapter.client:
        raise IngestError("the job is not for this adapter's client; nothing was read or written")
    result = adapter.sources()
    if not result.ok or result.data is None:
        raise IngestError("the SharePoint source could not be read")
    return SharePointIngestReport(ingest(job, result.data, store, embedder, max_chars=max_chars), adapter.skipped)
