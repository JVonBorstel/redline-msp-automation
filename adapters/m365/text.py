"""Small text helpers shared by the Microsoft 365 mocks (B-88). Untrusted text becomes one plain, bounded line."""

from __future__ import annotations

import re

from core.guard.detect import detect_injection

WITHHELD = "[withheld: this text looks like an instruction to the assistant]"
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_INVISIBLE_RANGES = ((0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x2064), (0x2066, 0x2069), (0xFEFF, 0xFEFF))
_INVISIBLE = re.compile("[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in _INVISIBLE_RANGES) + "]")
_SPACES = re.compile(r"\s+")
_MARKUP = str.maketrans({"[": "(", "]": ")", "<": "", ">": "", "`": "'", "\\": "/"})


def one_line(value: object, limit: int) -> str:
    """``value`` as one line: control and invisible characters out, markup characters neutralised, cut to ``limit``.

    ``[`` and ``]`` become parentheses so no ``[text](url)`` link can form, ``<`` and ``>`` are removed so no tag can.
    """
    text = _INVISIBLE.sub("", str(value))
    text = _SPACES.sub(" ", _CONTROL.sub(" ", text)).strip().translate(_MARKUP)
    return text if len(text) <= limit else text[: max(limit - 3, 0)].rstrip() + "..."


def screened_line(value: object, limit: int) -> str:
    """``one_line``, or ``WITHHELD`` when the tripwire says the raw text reads like an instruction (C-12)."""
    raw = str(value)
    return WITHHELD if detect_injection(raw).flagged else one_line(raw, limit)
