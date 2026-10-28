"""Text normalisation for untrusted input: what a model would read, with the hiding tricks taken out.

Three tricks matter here:
- invisible characters (zero-width, bidi controls, soft hyphen, Unicode tag characters) that split or reorder
  words so a keyword scan misses them, while a model still reads the text;
- compatibility look-alikes (fullwidth letters, ligatures, odd spaces) that NFKC folds back to plain text.
"""

from __future__ import annotations

import html
import re
import unicodedata

# Zero-width and joiner characters, bidi embedding/override/isolate controls, word joiner and invisible operators,
# soft hyphen, Mongolian vowel separator, Arabic letter mark, BOM, and the Unicode "tag" block (ASCII smuggling).
_INVISIBLE = re.compile(
    "[\u00ad\u061c\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\U000e0000-\U000e007f]"
)
_TAG_ASCII = re.compile("[\U000e0020-\U000e007e]")


def normalise(text: str) -> str:
    """Strip invisible characters, then apply NFKC so look-alike forms compare equal to plain text."""
    return unicodedata.normalize("NFKC", _INVISIBLE.sub("", text))


def find_invisible(text: str) -> list[str]:
    """Return the invisible characters in ``text`` in order of appearance. A single leading BOM is ignored."""
    body = text[1:] if text.startswith("\ufeff") else text
    return _INVISIBLE.findall(body)


def reveal_tag_text(text: str) -> str:
    """Decode Unicode tag characters (U+E0020..U+E007E) to the ASCII they shadow (invisible, yet read by models)."""
    return "".join(chr(ord(ch) - 0xE0000) for ch in _TAG_ASCII.findall(text))


# Cyrillic and Greek letters that are hard to tell from a Latin letter, written as escapes so a reviewer can see
# them. A deliberately short list: only letters that can stand in for a Latin letter inside an English trigger word.
# Real Cyrillic or Greek text folds to nonsense Latin that matches none of the English rules, so it adds no alarm.
_LOOK_ALIKES = {
    # Cyrillic lower case
    "a": "\u0430", "e": "\u0435", "o": "\u043e", "p": "\u0440", "c": "\u0441", "y": "\u0443", "x": "\u0445",
    "i": "\u0456", "j": "\u0458", "s": "\u0455", "h": "\u04bb", "d": "\u0501",
    # Cyrillic upper case
    "A": "\u0410", "B": "\u0412", "E": "\u0415", "K": "\u041a", "M": "\u041c", "H": "\u041d", "O": "\u041e",
    "P": "\u0420", "C": "\u0421", "T": "\u0422", "X": "\u0425", "I": "\u0406", "J": "\u0408", "S": "\u0405",
}  # fmt: skip
_GREEK = {"o": "\u03bf", "v": "\u03bd", "i": "\u03b9", "O": "\u039f", "A": "\u0391", "B": "\u0392", "E": "\u0395",
          "I": "\u0399", "K": "\u039a", "M": "\u039c", "N": "\u039d", "P": "\u03a1", "T": "\u03a4",
          "Z": "\u0396"}  # fmt: skip
_CONFUSABLES = str.maketrans({ord(fake): latin for table in (_LOOK_ALIKES, _GREEK) for latin, fake in table.items()})


def fold_look_alikes(text: str) -> str:
    """Replace Cyrillic and Greek letters that look like Latin ones with the Latin letter (for scanning only)."""
    return text.translate(_CONFUSABLES)


def decoded_variant(text: str) -> str:
    """The text as a reader would see it after HTML character references and look-alike letters are resolved."""
    return normalise(fold_look_alikes(html.unescape(text)))
