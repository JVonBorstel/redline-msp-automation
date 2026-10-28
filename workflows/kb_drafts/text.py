"""Small, deterministic text helpers for B-58: sentence splitting and the contradiction rules.

The rules are lexical on purpose (no model): two sentences are compared only after retrieval says they are about the
same thing, and a rule fires only when they say nearly the same words and differ in exactly one way. They are a
stand-in for a person's judgment and will miss paraphrases (see specs/B-58.md, "Known limits").
"""

from __future__ import annotations

import re

MIN_CORE = 3  # a sentence with fewer content words than this is too short to compare
OVERLAP = 0.8  # share of the shorter sentence's content words the other sentence must also contain

_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_TOKEN = re.compile(r"[a-z0-9']+")
FILLER = frozenset(
    "a an and are as at be been but by can for from has have if in is it its of on or so that the their then there "
    "these this to up was were when where which will with you your do does did should must may also".split()
)
NEGATIONS = frozenset(
    "not never no avoid without cannot don't doesn't didn't shouldn't mustn't can't won't isn't aren't".split()
)
ANTONYMS = {"enable": "disable", "disable": "enable", "allow": "block", "block": "allow"}


def split_sentences(text: str) -> list[str]:
    """Sentences of ``text`` (split after . ! ? and at line breaks), whitespace squashed, blanks dropped."""
    return [" ".join(part.split()) for part in _SPLIT.split(text) if part.strip()]


def _stem(token: str) -> str:
    return token[:-1] if len(token) > 3 and token.endswith("s") and not token.endswith("ss") else token


def _parts(sentence: str) -> tuple[frozenset[str], frozenset[str], bool]:
    """(content words without numbers, numbers, whether the sentence is negated)."""
    tokens = _TOKEN.findall(sentence.lower())
    negated = any(t in NEGATIONS for t in tokens)
    numbers = frozenset(t for t in tokens if t.isdigit())
    core = frozenset(_stem(t) for t in tokens if t not in FILLER and t not in NEGATIONS and not t.isdigit())
    return core, numbers, negated


def _overlap(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def opposition(first: str, second: str) -> str | None:
    """The rule under which two sentences contradict each other, or ``None``.

    - ``opposite-instruction``: nearly the same words, one negated ("restart X" against "do not restart X").
    - ``different-value``: nearly the same words, both with numbers, and the numbers differ ("every 7 days" against
      "every 30 days").
    - ``opposite-action``: nearly the same words except an antonym pair (enable against disable, allow against block).
    """
    core_a, nums_a, neg_a = _parts(first)
    core_b, nums_b, neg_b = _parts(second)
    if min(len(core_a), len(core_b)) < MIN_CORE:
        return None
    similar = _overlap(core_a, core_b) >= OVERLAP
    if similar and neg_a != neg_b:
        return "opposite-instruction"
    if similar and neg_a == neg_b and nums_a and nums_b and nums_a != nums_b:
        return "different-value"
    swapped = any(t in ANTONYMS and ANTONYMS[t] in core_b and t not in core_b for t in core_a)
    mapped = frozenset(ANTONYMS.get(t, t) for t in core_a)
    if neg_a == neg_b and swapped and _overlap(mapped, core_b) >= OVERLAP:
        return "opposite-action"
    return None
