"""Mock routing backends: deterministic keyword deciders that return a category and a declared confidence.

These are stand-ins for a rules-first tier, a small model and a strong model (``mock_backends.json``). They make no
network call and import no model client. A real or local model would plug in behind the same ``Decision`` shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from workflows.triage.tickets import Category

Tier = Literal["rules", "small", "strong"]
TIERS: tuple[Tier, ...] = ("rules", "small", "strong")
DEFAULT_BACKENDS_PATH = Path(__file__).with_name("mock_backends.json")


class BackendError(ValueError):
    """The backend fixture is missing or malformed."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Rule(_Strict):
    keywords: list[str] = Field(min_length=1)
    category: Category
    confidence: float = Field(gt=0, le=1)


class Fallback(_Strict):
    category: Category
    confidence: float = Field(gt=0, le=1)


class Decision(_Strict):
    category: Category
    confidence: float


class Backend(_Strict):
    relative_cost: float = Field(ge=0)
    fallback: Fallback
    rules: list[Rule]

    def decide(self, text: str) -> Decision:
        folded = text.casefold()
        for rule in self.rules:
            if any(k.casefold() in folded for k in rule.keywords):
                return Decision(category=rule.category, confidence=rule.confidence)
        return Decision(category=self.fallback.category, confidence=self.fallback.confidence)


class Backends(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    note: str = Field(alias="_note", default="")
    tiers: dict[Tier, Backend]

    @classmethod
    def load(cls, path: Path = DEFAULT_BACKENDS_PATH) -> Self:
        try:
            parsed = cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise BackendError(f"cannot load routing backends from {path}: {exc}") from exc
        missing = [t for t in TIERS if t not in parsed.tiers]
        if missing:
            raise BackendError(f"routing backends lack tier(s): {', '.join(missing)}")
        return parsed
