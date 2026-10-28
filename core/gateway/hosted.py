"""Hosted provider adapters: off by default, last-resort escalation only (D-018, D6-11, B-90).

Azure OpenAI has its own module (``core.gateway.azure_openai``, a mock that fails closed) and is re-exported here.
The Anthropic adapter is still a stub with no endpoint, no key and no client: disabled, it raises ProviderDisabled;
enabled, ProviderNotImplemented. Either way the gateway returns ok=False.
"""

from __future__ import annotations

from core.gateway.azure_openai import AzureOpenAIProvider
from core.gateway.base import ProviderDisabled, ProviderName, ProviderNotImplemented, Task

__all__ = ["AnthropicProvider", "AzureOpenAIProvider"]


class AnthropicProvider:
    name: ProviderName = "anthropic"

    def __init__(self, *, enabled: bool = False) -> None:
        self._enabled = enabled

    def complete(self, *, task: Task, model: str, text: str) -> str:
        if not self._enabled:
            raise ProviderDisabled(f"provider {self.name!r} is disabled in config/models.json")
        raise ProviderNotImplemented(f"provider {self.name!r} is a stub adapter; no hosted client is built")
