"""Deterministic chunking by paragraph, then by whitespace (B-56).

A chunk is a slice of the (already redacted) document no longer than ``max_chars``. Paragraphs are packed together
while they fit; a paragraph that does not fit alone is cut at whitespace, and a single word longer than the limit is
cut hard. Offsets are character offsets into the text given.
"""

from __future__ import annotations

import re

_PARAGRAPH = re.compile(r"\S(?:.|\n(?!\s*\n))*")


def _cut(text: str, start: int, end: int, limit: int) -> list[tuple[int, int]]:
    """Cut one paragraph [start, end) into pieces of at most ``limit`` characters, at whitespace where possible."""
    pieces: list[tuple[int, int]] = []
    pos = start
    while pos < end:
        while pos < end and text[pos].isspace():
            pos += 1
        if pos >= end:
            break
        stop = min(end, pos + limit)
        if stop < end:
            space = max(
                text.rfind(" ", pos, stop + 1), text.rfind("\n", pos, stop + 1), text.rfind("\t", pos, stop + 1)
            )
            if space > pos:
                stop = space
        piece_end = stop
        while piece_end > pos and text[piece_end - 1].isspace():
            piece_end -= 1
        pieces.append((pos, piece_end))
        pos = stop
    return pieces


def chunk_spans(text: str, max_chars: int) -> list[tuple[int, int]]:
    """Spans (start, end) of the chunks of ``text``, in order, none longer than ``max_chars``."""
    units: list[tuple[int, int]] = []
    for match in _PARAGRAPH.finditer(text):
        start, end = match.span()
        while end > start and text[end - 1].isspace():
            end -= 1
        if end - start <= max_chars:
            units.append((start, end))
        else:
            units.extend(_cut(text, start, end, max_chars))
    spans: list[tuple[int, int]] = []
    for start, end in units:
        if spans and end - spans[-1][0] <= max_chars:
            spans[-1] = (spans[-1][0], end)
        else:
            spans.append((start, end))
    return spans
