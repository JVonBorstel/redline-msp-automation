"""Deterministic, fixture-driven mock provider: the default backend, fully offline.

For each task the fixture lists keyword rules (first match wins, case-insensitive substring) and a fallback list.
With no rule match, the fallback is picked by a SHA-256 of (task, text), so the same input always gives the same
output across runs and machines. For ``classify`` the output is a JSON object ``{"category": "<label>"}`` whose
label must be one of the fixture's ``labels``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.gateway.base import ProviderName, Task


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Rule(_Strict):
    keywords: list[str] = Field(min_length=1)
    response: str = Field(min_length=1)


class TaskFixture(_Strict):
    rules: list[Rule] = Field(default_factory=list)
    fallback: list[str] = Field(min_length=1)


class ClassifyFixture(TaskFixture):
    labels: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _responses_are_labels(self) -> Self:
        unknown = {r.response for r in self.rules} | set(self.fallback)
        unknown -= set(self.labels)
        if unknown:
            raise ValueError(f"classify responses not in labels: {sorted(unknown)}")
        return self


class MockFixture(_Strict):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    note: str = Field(alias="_note", default="")
    classify: ClassifyFixture
    summarize: TaskFixture
    reason: TaskFixture

    @classmethod
    def load(cls, path: Path) -> Self:
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))


def stable_index(task: str, text: str, size: int) -> int:
    """A platform-independent index in [0, size) derived from SHA-256 (Python's hash() is salted per process)."""
    digest = hashlib.sha256(f"{task}\x00{text}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % size


class MockProvider:
    name: ProviderName = "mock"

    def __init__(self, fixture: MockFixture) -> None:
        self._fixture = fixture

    @classmethod
    def from_file(cls, path: Path) -> Self:
        return cls(MockFixture.load(path))

    def complete(self, *, task: Task, model: str, text: str) -> str:
        spec: TaskFixture = getattr(self._fixture, task)
        folded = text.casefold()
        answer = next(
            (rule.response for rule in spec.rules if any(k.casefold() in folded for k in rule.keywords)),
            spec.fallback[stable_index(task, text, len(spec.fallback))],
        )
        if task == "classify":
            return json.dumps({"category": answer})
        return answer
