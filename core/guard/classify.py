"""Data classes DC-0 to DC-6 and the shape rules that raise a text's class (B-55, B55-1; docs/map/05-governance.md 3).

Three rules from the governance map, enforced here in code, never by a model:

1. Unknown is high. Text whose class the caller does not declare takes the client's industry floor from the client
   record (D6-12): dental DC-4; financial, RIA, legal and accounting DC-5. A client with ``industry: other`` and a
   call with no client record at all also get DC-5 (fail closed: the highest class a model may ever see).
2. The class of a text is the highest class of anything in it. One SSN-shaped string in a printer ticket makes
   the whole ticket DC-5; one secret-shaped string makes it DC-6, and DC-6 text never reaches any model.
3. The class comes from the client record and the text's shapes, never from the text's own claims about itself.

Findings carry the kind, the class and the character span, never the matched value, so a ``Finding`` or a
``Classification`` can be logged or shown without leaking what it found (STD-AU-4).

The shape rules are plain regular expressions written for the synthetic Phase 2 set's shapes (B-21) plus common
secret formats. They are a tripwire, not a guarantee: names without a cue word ("patient", "investor", "client")
are not found, which is why the industry floor, not the shape scan, decides what a hosted model may see.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Literal, Protocol


class DataClass(IntEnum):
    """The seven data classes of docs/map/05-governance.md section 3, ordered so ``max`` gives the strictest."""

    DC0 = 0  # public
    DC1 = 1  # MSP internal
    DC2 = 2  # client confidential
    DC3 = 3  # end-user PII
    DC4 = 4  # PHI
    DC5 = 5  # NPI / customer information
    DC6 = 6  # credentials and secrets

    @property
    def label(self) -> str:
        return f"DC-{self.value}"

    @classmethod
    def parse(cls, label: str) -> DataClass:
        """``"DC-4"`` -> ``DataClass.DC4``. Raises ValueError for anything else."""
        match = re.fullmatch(r"DC-([0-6])", label)
        if not match:
            raise ValueError(f"not a data class: {label!r} (expected DC-0 to DC-6)")
        return cls(int(match.group(1)))


INDUSTRY_FLOOR: dict[str, DataClass] = {
    "dental": DataClass.DC4,
    "financial": DataClass.DC5,
    "ria": DataClass.DC5,
    "legal": DataClass.DC5,
    "accounting": DataClass.DC5,
    "other": DataClass.DC5,
}
"""Unknown-text floor per client ``industry`` (D6-12, B55-1). Keys are the client schema's industry enum."""

DEFAULT_FLOOR = DataClass.DC5
"""The floor when no client record is given, or its industry is not in ``INDUSTRY_FLOOR`` (fail closed)."""


class ClientRecord(Protocol):
    """What the gate reads from a client record (``adapters.binding.ClientConfig`` satisfies it)."""

    @property
    def id(self) -> str: ...

    @property
    def industry(self) -> str: ...


def floor_for(client: ClientRecord | None) -> DataClass:
    """The unknown-text floor for ``client``: read from its record's ``industry``, never from any text."""
    if client is None:
        return DEFAULT_FLOOR
    return INDUSTRY_FLOOR.get(client.industry, DEFAULT_FLOOR)


Kind = Literal[
    "secret",
    "ssn",
    "member-id",
    "account-number",
    "date-of-birth",
    "matter-number",
    "phone",
    "patient-name",
    "investor-name",
    "client-name",
    "person-name",
]


@dataclass(frozen=True, slots=True)
class Shape:
    """One shape rule: a pattern whose ``group`` is the sensitive span, and the class it proves."""

    kind: Kind
    data_class: DataClass
    pattern: re.Pattern[str]
    group: int = 0


_WORD = r"[A-Z][a-z]+(?:-[A-Z]?[a-z]+|'[A-Z][a-z]+)?"  # Ana, Smith-Jones, O'Neil; never the possessive 's
_NAME = _WORD + r"(?: " + _WORD + r"){0,2}"
_NUM_LEFT = r"(?<![\w-])"
_NUM_RIGHT = r"(?![\w-])"

# DC-6: any of these blocks the call. Written so this file does not itself match the repo's secret scan.
DC6_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{10,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._~+/=-]{20,}"),
    re.compile(r"(?i)\b(?:AccountKey|SharedAccessKey|SharedAccessSignature|Password|Pwd)=[^;\s]{4,}"),
    re.compile(r"(?i)\bclient[_ ]secret\s*[:=]\s*\S{8,}"),
    re.compile(r"(?i)\b(?:password|passwd|passcode|pwd)\s*(?:is|was|:|=)\s*(?=\S*[\d!@#$%^&*])\S{6,}"),
    re.compile(r"(?i)otpauth://\S+"),
    re.compile(r"\b\d{6}(?:-\d{6}){7}\b"),  # BitLocker recovery key
    re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^@\s/]{3,}@"),  # credentials inside a URL
)

# PHI, NPI and PII shapes, in priority order: an earlier rule claims a span first, a later rule cannot overlap it.
SHAPES: tuple[Shape, ...] = (
    Shape("ssn", DataClass.DC5, re.compile(_NUM_LEFT + r"\d{3}-\d{2}-\d{4}" + _NUM_RIGHT)),
    Shape(
        "member-id",
        DataClass.DC4,
        re.compile(r"(?i:member(?:ship)?(?: id| number| no\.?| #)?)\W{0,3}(\d{2}-\d{4}-\d{4})" + _NUM_RIGHT),
        1,
    ),
    Shape("account-number", DataClass.DC5, re.compile(_NUM_LEFT + r"\d{2}-\d{4}-\d{4}" + _NUM_RIGHT)),
    Shape(
        "account-number",
        DataClass.DC5,
        re.compile(r"(?i:account|acct)(?i: number| no\.?| #)?\s*[:#]?\s*(\d[\d-]{5,}\d)" + _NUM_RIGHT),
        1,
    ),
    Shape(
        "date-of-birth",
        DataClass.DC4,
        re.compile(
            r"(?i:\bDOB\b|date of birth|\bborn(?: on)?)\W{0,3}(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})" + _NUM_RIGHT
        ),
        1,
    ),
    Shape("matter-number", DataClass.DC3, re.compile(r"\b[A-Z]{2,4}-\d{4}-\d{4}\b")),
    Shape(
        "phone",
        DataClass.DC3,
        re.compile(_NUM_LEFT + r"(?:\+?1[ .-]?)?(?:\(\d{3}\) ?|\d{3}[ .-])?\d{3}[ .-]\d{4}" + _NUM_RIGHT),
    ),
    Shape("patient-name", DataClass.DC4, re.compile(r"(?i:\bpatients?)(?:,)? (" + _NAME + r")\b"), 1),
    Shape(
        "investor-name",
        DataClass.DC5,
        re.compile(r"(?i:\binvestors?|\blimited partners?)(?:,)? (" + _NAME + r")\b"),
        1,
    ),
    Shape("investor-name", DataClass.DC5, re.compile(r"\b((?:[A-Z][a-z]+ ){1,3}(?:Family )?Trust)\b"), 1),
    Shape("client-name", DataClass.DC3, re.compile(r"(?i:\bclients?)(?:,)? (" + _NAME + r")\b"), 1),
    Shape("client-name", DataClass.DC3, re.compile(r"(?i:\bthe) ([A-Z][a-z]+) (?i:matter)\b"), 1),
    Shape("person-name", DataClass.DC3, re.compile(r"\b(?:Mrs|Mr|Ms|Mx)\. (" + _NAME + r")\b"), 1),
    Shape("person-name", DataClass.DC3, re.compile(r"(?i:\bnamed|\bthe name|\bname is) (" + _NAME + r")\b"), 1),
)


@dataclass(frozen=True, slots=True)
class Finding:
    """One sensitive span: kind, class and position. Holds no text, so it is safe to log or show."""

    kind: Kind
    data_class: DataClass
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Classification:
    """The class of one text and why: the declared class or the floor, raised by the shapes found."""

    data_class: DataClass
    base: DataClass
    basis: Literal["declared", "client-floor", "default-floor"]
    findings: tuple[Finding, ...]

    @property
    def blocked(self) -> bool:
        """DC-6 text never reaches any model."""
        return self.data_class is DataClass.DC6

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted({f.kind for f in self.findings}))


def find_shapes(text: str) -> tuple[Finding, ...]:
    """Every secret, PHI, NPI and PII span in ``text``, non-overlapping, sorted by position."""
    claimed: list[Finding] = []

    def free(start: int, end: int) -> bool:
        return all(end <= f.start or start >= f.end for f in claimed)

    for pattern in DC6_PATTERNS:
        for match in pattern.finditer(text):
            if free(match.start(), match.end()):
                claimed.append(Finding("secret", DataClass.DC6, match.start(), match.end()))
    for shape in SHAPES:
        for match in shape.pattern.finditer(text):
            start, end = match.span(shape.group)
            if end > start and free(start, end):
                claimed.append(Finding(shape.kind, shape.data_class, start, end))
    return tuple(sorted(claimed, key=lambda f: f.start))


def classify(text: str, *, client: ClientRecord | None = None, declared: DataClass | None = None) -> Classification:
    """Classify ``text``: the declared class (or the client's floor when undeclared), raised by any shape found.

    A shape always raises the class and nothing lowers it: a caller may declare a known class (a public KB
    article is DC-0), but one SSN-shaped string in that text still makes it DC-5.
    """
    basis: Literal["declared", "client-floor", "default-floor"]
    if declared is not None:
        base, basis = DataClass(declared), "declared"
    elif client is not None:
        base, basis = floor_for(client), "client-floor"
    else:
        base, basis = DEFAULT_FLOOR, "default-floor"
    findings = find_shapes(text)
    data_class = max([base, *(f.data_class for f in findings)])
    return Classification(data_class=data_class, base=base, basis=basis, findings=findings)
