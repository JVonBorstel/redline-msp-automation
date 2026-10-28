"""Gateway configuration: ``config/models.json`` (providers and model names) and ``config/routing.json`` (task routes).

Model names live only in config. Routes name a provider and a model *alias* (for example ``small``), and the alias
is resolved through that provider's ``models`` map, so swapping a model or a provider is a config change.

Both files are read from ``core.paths.REPO_ROOT`` by default (DR-08, STD-CF-9), never from the current directory.
Each file may carry ``"version": 1`` (STD-CF-4, DR-07); any other value is refused. A file with no version is still
accepted until the owner adds the field to both committed files; then the absent case is removed (tracked in B-12).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.gateway.base import ProviderName, Task
from core.gateway.loopback import require_loopback_url
from core.paths import REPO_ROOT

MODELS_FILE = Path("config/models.json")
ROUTING_FILE = Path("config/routing.json")
LIMITS_FILE = Path("config/limits.json")
CONFIG_VERSION = 1
"""The only config version this reader knows (STD-CF-4)."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MockSettings(_Strict):
    enabled: bool = True
    fixture: Path
    models: dict[str, str] = Field(min_length=1)


class OllamaSettings(_Strict):
    enabled: bool = False
    base_url: str
    timeout_s: float = Field(gt=0, le=600)
    max_response_bytes: int = Field(default=1_048_576, gt=0)
    models: dict[str, str] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def _loopback_only(cls, value: str) -> str:
        return require_loopback_url(value)


REF_PATTERN = r"^(env|keyvault):[A-Za-z][A-Za-z0-9_.-]{0,126}$"
"""A reference names where a secret lives (an environment variable or a Key Vault secret name), never its value."""


class HostedSettings(_Strict):
    """Azure OpenAI and Anthropic: off by default. No endpoints or keys are ever stored here.

    ``approval_id`` names the entry in ``governance/ai-vendor-register.json`` that approves this provider (B90-1).
    Without one that is approved and in date, nothing hosted runs, whatever ``enabled`` says.
    """

    enabled: bool = False
    approval_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{2,63}$")
    models: dict[str, str] = Field(default_factory=dict)


class AzureOpenAISettings(HostedSettings):
    """Azure OpenAI: where to find the endpoint and key (references only) and the API version to ask for."""

    endpoint_ref: str | None = Field(default=None, pattern=REF_PATTERN)
    key_ref: str | None = Field(default=None, pattern=REF_PATTERN)
    api_version: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}(-preview)?$")


class ProvidersConfig(_Strict):
    mock: MockSettings
    ollama: OllamaSettings
    azure_openai: AzureOpenAISettings = AzureOpenAISettings()
    anthropic: HostedSettings = HostedSettings()

    def settings(self, provider: ProviderName) -> MockSettings | OllamaSettings | HostedSettings:
        settings: MockSettings | OllamaSettings | HostedSettings = getattr(self, provider)
        return settings

    def models_for(self, provider: ProviderName) -> dict[str, str]:
        return self.settings(provider).models

    def is_enabled(self, provider: ProviderName) -> bool:
        return self.settings(provider).enabled


class Route(_Strict):
    provider: ProviderName
    model: str = Field(min_length=1, description="Alias into the provider's models map in config/models.json.")


class Budget(_Strict):
    """Limits for one scope inside one window. An absent dimension is not limited."""

    max_calls: int | None = Field(default=None, gt=0, strict=True)
    max_tokens: int | None = Field(default=None, gt=0, strict=True)


class ScopedBudgets(_Strict):
    """A default budget for every id in a scope (every client, every agent) and per-id overrides."""

    default: Budget | None = None
    overrides: dict[str, Budget] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _overrides_limit_something(self) -> Self:
        empty = sorted(name for name, budget in self.overrides.items() if budget == Budget())
        if empty:
            raise ValueError(f"overrides {empty} set no limit; remove them or give max_calls or max_tokens")
        return self

    def for_id(self, name: str) -> Budget | None:
        return self.overrides.get(name, self.default)


class BreakerSettings(_Strict):
    failure_threshold: int = Field(gt=0, strict=True, description="Consecutive provider failures that open it.")
    open_s: float = Field(gt=0, le=86_400, description="Seconds it stays open before one probe call is allowed.")


class LimitsConfig(BaseModel):
    """``config/limits.json``: budgets (calls, estimated tokens) per window, and the circuit breaker (B-80).

    Tokens are estimated as ``ceil(characters / chars_per_token)``; no provider here reports real usage.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    window_s: int = Field(gt=0, strict=True, description="Budgets reset this many seconds after the window opens.")
    chars_per_token: int = Field(default=4, gt=0, strict=True)
    global_: Budget | None = Field(default=None, alias="global")
    per_client: ScopedBudgets = ScopedBudgets()
    per_agent: ScopedBudgets = ScopedBudgets()
    breaker: BreakerSettings


class GatewayConfig(_Strict):
    providers: ProvidersConfig
    routes: dict[Task, Route]
    root: Path = REPO_ROOT
    # B-80: None (no config/limits.json) means no budgets and no circuit breaker; the committed file is present.
    limits: LimitsConfig | None = None
    # DR-07: ``None`` (absent) is accepted only until config/models.json and config/routing.json carry the field.
    version: Literal[1] | None = None

    @field_validator("version", mode="before")
    @classmethod
    def _version_is_an_integer(cls, value: object) -> object:
        # Refuse look-alikes such as true or 1.0 that lax validation would read as 1 (STD-CF-4).
        if value is not None and type(value) is not int:
            raise ValueError(f"version must be the integer {CONFIG_VERSION}, not {value!r}")
        return value

    @model_validator(mode="after")
    def _routes_resolve(self) -> Self:
        for task, route in self.routes.items():
            if route.model not in self.providers.models_for(route.provider):
                raise ValueError(
                    f"route {task!r}: model alias {route.model!r} is not defined for provider {route.provider!r}"
                )
        return self

    def resolve(self, task: Task) -> tuple[ProviderName, str]:
        """Return (provider, concrete model name) for a task. Raises KeyError for an unrouted task."""
        route = self.routes[task]
        return route.provider, self.providers.models_for(route.provider)[route.model]

    @property
    def mock_fixture_path(self) -> Path:
        fixture = self.providers.mock.fixture
        return fixture if fixture.is_absolute() else self.root / fixture

    @classmethod
    def load(cls, root: Path = REPO_ROOT) -> Self:
        """Load and validate both config files under ``root`` (default: the repo root). Raises on any invalid value.

        A ``version`` other than 1 in either file raises ValueError; an absent version is accepted for now (DR-07).
        ``config/limits.json`` (B-80) is optional at load so older roots and test trees still load: without it the
        gateway runs with no budgets and no breaker. A file that is present must be valid; nothing loads partially.
        """
        models = json.loads((root / MODELS_FILE).read_text(encoding="utf-8"))
        routing = json.loads((root / ROUTING_FILE).read_text(encoding="utf-8"))
        versions = {_file_version(models, MODELS_FILE), _file_version(routing, ROUTING_FILE)} - {None}
        data: dict[str, Any] = {"providers": models["providers"], "routes": routing["routes"], "root": root}
        limits_path = root / LIMITS_FILE
        if limits_path.is_file():
            limits = json.loads(limits_path.read_text(encoding="utf-8"))
            _file_version(limits, LIMITS_FILE)
            data["limits"] = {k: v for k, v in limits.items() if k not in ("version", "_note")}
        if versions:
            data["version"] = versions.pop()
        return cls.model_validate(data)


def _file_version(document: dict[str, Any], name: Path) -> int | None:
    """The file's ``version``, or None when absent. Any value other than the integer 1 is refused (STD-CF-4)."""
    if "version" not in document:
        return None
    version = document["version"]
    if type(version) is not int or version != CONFIG_VERSION:
        raise ValueError(f"{name.as_posix()}: unsupported config version {version!r} (known: {CONFIG_VERSION})")
    return version
