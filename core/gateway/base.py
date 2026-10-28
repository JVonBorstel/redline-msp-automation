"""Shared types for the gateway: task names, provider names, the provider protocol and its errors."""

from __future__ import annotations

from typing import Literal, Protocol, get_args

Task = Literal["classify", "summarize", "reason"]
ProviderName = Literal["mock", "ollama", "azure_openai", "anthropic"]

TASKS: tuple[str, ...] = get_args(Task)


class ProviderError(Exception):
    """A provider could not produce a completion. The gateway turns it into Completion(ok=False)."""


class ProviderDisabled(ProviderError):
    """The provider is switched off in config/models.json."""


class ProviderNotImplemented(ProviderError):
    """The provider is a stub adapter with no real client behind it."""


class UnsafeBaseURL(ValueError):
    """A provider base URL points somewhere other than this machine's loopback interface."""


class Provider(Protocol):
    """One model backend. Returns the model's text, or raises ProviderError. Never returns anything but text."""

    name: ProviderName

    def complete(self, *, task: Task, model: str, text: str) -> str: ...
