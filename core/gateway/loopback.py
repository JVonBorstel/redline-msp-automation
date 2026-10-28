"""Loopback-only URL guard for local model endpoints (Ollama, vLLM).

The check is an allow-list on the parsed host, never a prefix or substring match, so
``http://127.0.0.1.evil.com``, ``http://127.0.0.1@evil.com`` and similar tricks are refused.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from core.gateway.base import UnsafeBaseURL

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_ALLOWED_SCHEMES = frozenset({"http", "https"})


def require_loopback_url(url: str) -> str:
    """Return ``url`` unchanged if it is a plain http(s) URL whose host is loopback; raise UnsafeBaseURL otherwise."""
    # urlsplit silently strips whitespace and some control characters, so refuse them before parsing.
    if not url or any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in url):
        raise UnsafeBaseURL("base URL is empty or contains whitespace/control characters")
    if "\\" in url or "%" in url:
        raise UnsafeBaseURL("base URL must not contain backslashes or percent-encoding")

    parts = urlsplit(url)
    if parts.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeBaseURL(f"base URL scheme must be http or https, got {parts.scheme!r}")
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        raise UnsafeBaseURL("base URL must not contain userinfo (user@host)")
    if parts.query or parts.fragment or url.endswith(("?", "#")):
        raise UnsafeBaseURL("base URL must not contain a query or fragment")
    if parts.hostname not in LOOPBACK_HOSTS:
        raise UnsafeBaseURL(f"base URL host must be one of {sorted(LOOPBACK_HOSTS)}, got {parts.hostname!r}")
    try:
        port = parts.port
    except ValueError as exc:
        raise UnsafeBaseURL(f"base URL port is invalid: {exc}") from exc
    if port == 0:
        raise UnsafeBaseURL("base URL port must not be 0")
    return url
