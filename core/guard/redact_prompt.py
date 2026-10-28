"""The pre-prompt redaction gate (B-55, B55-2): what a model is allowed to read, decided before any prompt.

``redact_prompt(text, client=..., declared=...)`` normalises the text (invisible characters out, NFKC, so a
zero-width character cannot split an SSN past the scan), classifies it (``core.guard.classify``) and then:

- DC-6 (a secret shape anywhere): ``blocked`` is true and ``text`` is empty. Nothing is sent to any model.
- otherwise every PHI, NPI and PII span is replaced by a typed, numbered placeholder such as ``[PATIENT_NAME_1]``
  or ``[ACCOUNT_NUMBER_2]``. The same value gets the same number within one text, so a model can still tell two
  patients apart. The values are not kept anywhere: there is no mapping to put them back.

The result names kinds and counts only, never a value, so it is safe to log (STD-AU-4).
"""

from __future__ import annotations

from dataclasses import dataclass

from core.guard.classify import Classification, ClientRecord, DataClass, Kind, classify
from core.guard.normalise import normalise

PLACEHOLDER: dict[Kind, str] = {
    "secret": "SECRET",
    "ssn": "SSN",
    "member-id": "MEMBER_ID",
    "account-number": "ACCOUNT_NUMBER",
    "date-of-birth": "DATE_OF_BIRTH",
    "matter-number": "MATTER_NUMBER",
    "phone": "PHONE",
    "patient-name": "PATIENT_NAME",
    "investor-name": "INVESTOR_NAME",
    "client-name": "CLIENT_NAME",
    "person-name": "PERSON_NAME",
}


@dataclass(frozen=True, slots=True)
class RedactedPrompt:
    """The gate's answer for one text: the class, whether it is blocked, and the text a model may read."""

    text: str
    classification: Classification

    @property
    def data_class(self) -> DataClass:
        return self.classification.data_class

    @property
    def blocked(self) -> bool:
        return self.classification.blocked

    @property
    def redacted(self) -> tuple[str, ...]:
        """The kinds replaced, sorted, one entry per kind (no values)."""
        return self.classification.kinds


def redact_prompt(
    text: str, *, client: ClientRecord | None = None, declared: DataClass | None = None
) -> RedactedPrompt:
    """Classify and redact ``text`` for a prompt. A blocked (DC-6) result carries no text at all."""
    clean = normalise(text)
    classification = classify(clean, client=client, declared=declared)
    if classification.blocked:
        return RedactedPrompt(text="", classification=classification)
    numbers: dict[tuple[str, str], int] = {}
    counts: dict[str, int] = {}
    pieces: list[str] = []
    cursor = 0
    for finding in classification.findings:
        value = clean[finding.start : finding.end]
        tag = PLACEHOLDER[finding.kind]
        key = (tag, value)
        if key not in numbers:
            counts[tag] = counts.get(tag, 0) + 1
            numbers[key] = counts[tag]
        pieces.append(clean[cursor : finding.start])
        pieces.append(f"[{tag}_{numbers[key]}]")
        cursor = finding.end
    pieces.append(clean[cursor:])
    return RedactedPrompt(text="".join(pieces), classification=classification)
