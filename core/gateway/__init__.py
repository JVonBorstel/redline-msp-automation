"""Model gateway: one internal interface over swappable model backends (Phase 1, deliverable 4).

``Gateway(config).complete(task, text) -> Completion(text, model, provider, ms, ok, error)``

- ``mock`` (default): deterministic, driven by ``fixtures/gateway/mock_responses.json``; fully offline.
- ``ollama``: a local OpenAI-compatible endpoint on 127.0.0.1/localhost/::1 only; models from ``config/models.json``.
- ``azure_openai`` / ``anthropic``: stubs, disabled in config.

Routing (``config/routing.json``) maps ``classify`` / ``summarize`` / ``reason`` to a provider and model alias.

Budgets, the circuit breaker and the model-call audit record (B-80) are driven by ``config/limits.json``, an injectable
clock and an optional audit sink; see ``specs/B-80.md``.

Security note: the gateway never turns model output into tool calls. ``Completion.text`` is untrusted text; the
lever registry alone decides whether any lever runs, with which parameters, for whom and for which client.
"""

from __future__ import annotations

from core.gateway.base import (
    Provider,
    ProviderDisabled,
    ProviderError,
    ProviderName,
    ProviderNotImplemented,
    Task,
    UnsafeBaseURL,
)
from core.gateway.budget import BudgetTracker, CircuitBreaker
from core.gateway.call_audit import AuditSink
from core.gateway.config import GatewayConfig, LimitsConfig
from core.gateway.gateway import Completion, Gateway
from core.gateway.loopback import require_loopback_url

__all__ = [
    "AuditSink",
    "BudgetTracker",
    "CircuitBreaker",
    "Completion",
    "Gateway",
    "GatewayConfig",
    "LimitsConfig",
    "Provider",
    "ProviderDisabled",
    "ProviderError",
    "ProviderName",
    "ProviderNotImplemented",
    "Task",
    "UnsafeBaseURL",
    "require_loopback_url",
]
