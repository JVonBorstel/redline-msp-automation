"""Azure OpenAI adapter (B-90): a mock that fails closed. Nothing here has run against Azure.

What it does: checks that its config names a live, approved register entry for ``azure_openai``, resolves the
endpoint and key from *references* (``env:NAME`` or ``keyvault:NAME``, never values), checks the endpoint is an https
Azure OpenAI host, builds one chat-completions request and hands it to an injected ``transport``. What it does not
do: it contains no HTTP client. With no transport it raises, so the shipped wiring cannot send anything anywhere.

Fail closed: a missing approval, a missing reference, a reference that does not resolve, an endpoint that is not an
https ``*.openai.azure.com`` host, a missing transport, a transport error and a malformed reply are all
``ProviderError``. Error text is fixed wording; it never carries the endpoint, the key, the prompt or a transport's
own message (a transport error can echo a URL or a header).

The approval gate in the gateway decides per call (client, data class, purpose, B90-3). This adapter re-checks the
config-level approval on every call, so it cannot be used to skip the register by calling it directly.

UNVERIFIED: the request path, the ``api-key`` header, the payload and the reply shape follow the publicly documented
Azure OpenAI chat-completions form as remembered; no vendor page was opened and no endpoint was called.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol
from urllib.parse import urlsplit

from core.gateway.base import ProviderDisabled, ProviderError, ProviderName, ProviderNotImplemented, Task
from core.gateway.config import AzureOpenAISettings
from core.gateway.vendor_register import VendorRegister

SecretResolver = Callable[[str], str | None]
"""Maps a reference (``env:NAME``) to its value, or None when it is not set. Values are never logged."""

_HOST_SUFFIX = ".openai.azure.com"
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


@dataclass(frozen=True, slots=True, repr=False)
class AzureRequest:
    """One request for a transport to send. ``repr`` hides the key so a stray print or traceback cannot show it."""

    url: str
    api_key: str
    payload: dict[str, object]

    def __repr__(self) -> str:
        return "AzureRequest(url=<endpoint>, api_key=<hidden>, payload=<prompt>)"


class Transport(Protocol):
    """Sends the request and returns the decoded JSON reply. The real one is not built; tests pass a double."""

    def __call__(self, request: AzureRequest) -> object: ...


def env_resolver(ref: str) -> str | None:
    """Default resolver: ``env:NAME`` reads the process environment; ``keyvault:`` is not built, so it is None."""
    scheme, _, name = ref.partition(":")
    return os.environ.get(name) if scheme == "env" else None


def _today() -> date:
    return datetime.now(UTC).date()


class AzureOpenAIProvider:
    name: ProviderName = "azure_openai"

    def __init__(
        self,
        settings: AzureOpenAISettings | None = None,
        *,
        register: VendorRegister | None = None,
        resolve: SecretResolver | None = None,
        transport: Transport | None = None,
        today: Callable[[], date] | None = None,
    ) -> None:
        self._settings = settings or AzureOpenAISettings()
        self._register = register
        self._resolve: SecretResolver = resolve or env_resolver
        self._transport = transport
        self._today = today or _today

    def complete(self, *, task: Task, model: str, text: str) -> str:
        settings = self._settings
        if not settings.enabled:
            raise ProviderDisabled("provider 'azure_openai' is disabled in config/models.json")
        if self._register is None:
            raise ProviderError("azure_openai: no vendor register loaded; failing closed")
        verdict = self._register.check_provider(
            approval_id=settings.approval_id, provider=self.name, today=self._today()
        )
        if not verdict.allowed:
            raise ProviderError(f"azure_openai: no approved vendor record ({verdict.code}); failing closed")
        if not (settings.endpoint_ref and settings.key_ref and settings.api_version):
            raise ProviderError("azure_openai: not configured (endpoint_ref, key_ref and api_version are required)")
        if not _MODEL.fullmatch(model):
            raise ProviderError("azure_openai: the deployment name is not a plain name")
        endpoint = self._resolve(settings.endpoint_ref)
        api_key = self._resolve(settings.key_ref)
        if not endpoint or not api_key:
            raise ProviderError("azure_openai: a secret reference did not resolve (endpoint_ref or key_ref)")
        base = _checked_endpoint(endpoint)
        if self._transport is None:
            raise ProviderNotImplemented("azure_openai: no HTTP transport is built; the adapter is a mock")
        request = AzureRequest(
            url=f"{base}/openai/deployments/{model}/chat/completions?api-version={settings.api_version}",
            api_key=api_key,
            payload={"messages": [{"role": "user", "content": text}]},
        )
        try:
            reply = self._transport(request)
        except Exception:  # a transport's message can echo the URL, a header or the prompt
            raise ProviderError("azure_openai: the transport failed") from None
        return _content(reply)


def _checked_endpoint(endpoint: str) -> str:
    """The endpoint as ``https://<host>``: https only, no userinfo, port, path, query or fragment, Azure host only."""
    if any(ch.isspace() or ord(ch) < 0x20 for ch in endpoint):
        raise ProviderError("azure_openai: the endpoint is not an https Azure OpenAI host")
    try:
        parts = urlsplit(endpoint)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        raise ProviderError("azure_openai: the endpoint is not an https Azure OpenAI host") from None
    bad = (
        parts.scheme != "https"
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
        or not host.endswith(_HOST_SUFFIX)
        or len(host) <= len(_HOST_SUFFIX)
    )
    if bad:
        raise ProviderError("azure_openai: the endpoint is not an https Azure OpenAI host")
    return f"https://{host}"


def _content(reply: object) -> str:
    """``choices[0].message.content`` as non-empty text, else ProviderError. The reply is data, never a decision."""
    if isinstance(reply, dict):
        choices = reply.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content:
                    return content
    raise ProviderError("azure_openai: the reply was not a chat completion with text")
