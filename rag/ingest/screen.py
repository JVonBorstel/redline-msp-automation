"""The checks that decide what may be indexed (B-56): vault sources, metadata sanity, and the injection tripwire.

Vault exclusion (W-KB-07) is decided from what a source says about itself (tags, origin) BEFORE its text is looked at,
and again from the text (DC-6 shapes, in the pipeline). Both fail closed: a tag or origin that merely looks like a
vault is refused, and a person can re-tag the source if that was wrong.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from core.guard.detect import detect_injection
from rag.ingest.models import SAFE_ID, Source

VAULT_WORDS = frozenset({"vault", "vaults", "keyvault", "credential", "credentials", "secret", "secrets"})
_WORD_BREAK = re.compile(r"[^a-z0-9]+")
_ORIGIN = re.compile(r"^[A-Za-z0-9._:/\\ #~@+=-]{0,300}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
SPAN_FLOOR = 400  # characters: how far apart the pieces of one split-up injection phrase can sit and still be joined


def is_vault_source(source: Source) -> bool:
    """True when a tag or the origin names a credential vault (a vault, credentials or secrets, as a whole word)."""
    for label in (*source.tags, source.origin):
        if VAULT_WORDS & set(_WORD_BREAK.split(label.lower().replace("_", "-"))):
            return True
    return False


def has_valid_metadata(source: Source) -> bool:
    """Ids are safe keys, the origin is a plain path-like string, the title is one short line."""
    title = source.title.strip()
    return (
        bool(SAFE_ID.fullmatch(source.source_id))
        and bool(SAFE_ID.fullmatch(source.article_id))
        and bool(_ORIGIN.fullmatch(source.origin))
        and 0 < len(title) <= 300
        and not _CONTROL.search(title)
        and all(0 < len(t) <= 100 and not _CONTROL.search(t) for t in source.tags)
    )


def flag_chunks(texts: Sequence[str], raw_document: str, max_chars: int) -> list[tuple[str, ...]]:
    """Injection rule ids per chunk (an empty tuple means clean).

    1. Every run of consecutive chunks short enough to hold one phrase is scanned, and the SMALLEST runs that trip a
       rule are flagged, so a phrase cut in two by a chunk boundary is caught and clean neighbours are not.
    2. Anything the raw document trips that no run localised (hidden zero-width characters are removed before
       chunking, for example) flags every chunk, because the offending text cannot be pinned to one.
    """
    n = len(texts)
    limit = max(SPAN_FLOOR, 2 * max_chars)
    cache: dict[tuple[int, int], frozenset[str]] = {}

    def rules(i: int, j: int) -> frozenset[str]:
        if (i, j) not in cache:
            cache[(i, j)] = detect_injection(" ".join(texts[i : j + 1])).rules
        return cache[(i, j)]

    def smallest(i: int) -> int | None:
        total = 0
        for j in range(i, n):
            total += len(texts[j]) + 1
            if j > i and total > limit:
                return None
            if rules(i, j):
                return j
        return None

    found: list[set[str]] = [set() for _ in range(n)]
    ends = [smallest(i) for i in range(n)]
    for i, j in enumerate(ends):
        if j is None:
            continue
        nxt = ends[i + 1] if i + 1 < n else None
        if nxt is not None and nxt <= j:
            continue  # the same phrase is wholly inside the run that starts one chunk later
        for k in range(i, j + 1):
            found[k] |= rules(i, j)
    unplaced = detect_injection(raw_document).rules - set().union(*found) if n else frozenset()
    if unplaced:
        for entry in found:
            entry |= unplaced
    return [tuple(sorted(entry)) for entry in found]
