"""Alert rules as versioned data (B-83): the file format, its validation and the loader.

A rule file is JSON: ``{"version": 1, "rules": [...]}``. Every rule has an ``id`` (a lowercase identifier, unique in the
file), a ``kind`` that fixes which other fields it carries, a ``severity`` and a one-line ``summary`` written by the
rule author. Unknown kinds, unknown fields, a version other than 1 and duplicate ids are refused, so a typo cannot
silently disable an alert. Thresholds are data: tuning one is a change to ``rules.json``, reviewed like code, with no
code change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

DEFAULT_RULES = Path(__file__).resolve().parent / "rules.json"
SCHEMA_VERSION = 1

Severity = Literal["critical", "warning", "info"]
SEVERITY_ORDER: tuple[str, ...] = ("critical", "warning", "info")
RuleId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")]
Summary = Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=r"^[^\r\n]*$")]
Seconds = Annotated[int, Field(strict=True, ge=1, le=30 * 24 * 3600)]
Count = Annotated[int, Field(strict=True, ge=1, le=1_000_000)]


class RulesError(ValueError):
    """The rule file is missing, is not JSON or does not match the format."""


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: RuleId
    severity: Severity
    summary: Summary


class AuditChainFailure(_Base):
    """Fires once per audit chain whose verification failed. No thresholds: one broken chain is enough."""

    kind: Literal["audit-chain-failure"]


class BreakerOpen(_Base):
    """Fires per provider at ``min_events`` model calls refused with ``circuit-open`` in the last ``window_s``."""

    kind: Literal["breaker-open"]
    window_s: Seconds
    min_events: Count


class BudgetExhaustion(_Base):
    """Fires per budget scope (and per client for the client scope) at ``min_events`` ``budget:*`` denials."""

    kind: Literal["budget-exhaustion"]
    window_s: Seconds
    min_events: Count


class ApprovalBacklogAge(_Base):
    """Fires per client when its oldest pending proposal is more than ``max_age_s`` old."""

    kind: Literal["approval-backlog-age"]
    max_age_s: Seconds


class DeadLetterGrowth(_Base):
    """Fires per client when the dead-letter count rose by at least ``min_growth`` within ``window_s``."""

    kind: Literal["dead-letter-growth"]
    window_s: Seconds
    min_growth: Count


Rule = Annotated[
    AuditChainFailure | BreakerOpen | BudgetExhaustion | ApprovalBacklogAge | DeadLetterGrowth,
    Field(discriminator="kind"),
]


class RuleSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1]
    rules: list[Rule] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        ids = [rule.id for rule in self.rules]
        if len(set(ids)) != len(ids):
            raise ValueError("rule ids must be unique")
        return self


def load_rules(path: Path | None = None) -> RuleSet:
    """Read and validate a rule file (default: the committed ``rules.json``). Raises ``RulesError``."""
    target = path or DEFAULT_RULES
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RulesError(f"cannot read rules from {target.name}: {exc.__class__.__name__}") from exc
    if isinstance(raw, dict):
        raw = {key: value for key, value in raw.items() if key != "_note"}
    try:
        return RuleSet.model_validate(raw)
    except ValidationError as exc:
        raise RulesError(f"{target.name} is not a valid rule file: {exc.error_count()} problem(s)") from exc
