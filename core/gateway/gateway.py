"""The model gateway: one ``complete(task, text)`` call, routed by config, that never raises on provider failure.

Every text passes the pre-prompt redaction gate first (B-55, ``core.guard.redact_prompt``):

1. it gets a data class (DC-0 to DC-6): the caller's declared class, else the client record's industry floor,
   else DC-5; any PHI, NPI, PII or secret shape found raises it (B55-1);
2. DC-6 text is blocked: no provider is called, not even the mock (B55-2);
3. PHI, NPI and PII spans are replaced by typed placeholders before any provider sees the text (B55-2);
4. a hosted route (Azure OpenAI, Anthropic) needs a recorded approval (B-90, ``governance/ai-vendor-register.json``):
   an approved, in-date entry named by config that names this provider, this client (whose record must say
   ``model_processing: hosted``), this data class and this purpose. DC-4 and DC-5 text is refused unless the entry
   lists that class (B55-3, B90-3). Every refusal is audited with a fixed code.

The class and the kinds redacted ride on the ``Completion``; the values never do.

An admitted call then meets two more checks (B-80, ``config/limits.json``):

5. the provider's circuit breaker: after N consecutive failures it is open and calls fail fast;
6. the budgets: calls and estimated tokens per window for the whole gateway, the client and the agent. Over budget
   returns ``Completion(ok=False, error="budget exceeded")``; the audit record says which scope.

With an audit sink, every call (allowed, denied or failed) writes one metadata-only ``model.complete`` record
(``core.gateway.call_audit``): never the prompt, the completion or a provider's error text. If that record cannot be
written, a successful completion is withheld (fail closed, STD-ER-4). Time comes from an injectable clock.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.audit.chain import ActorKind, AuditError, new_request_id
from core.gateway.azure_openai import AzureOpenAIProvider, SecretResolver, Transport
from core.gateway.base import Provider, ProviderError, ProviderName, Task
from core.gateway.budget import UNATTRIBUTED, BudgetTracker, CircuitBreaker, Clock, Denial, estimate_tokens
from core.gateway.call_audit import MODEL_LEVER, AuditSink, prompt_digest
from core.gateway.config import GatewayConfig, HostedSettings
from core.gateway.hosted import AnthropicProvider
from core.gateway.mock import MockProvider
from core.gateway.ollama import OllamaProvider
from core.gateway.vendor_register import PURPOSE_PATTERN, REGISTER_FILE, VendorRegister
from core.guard.classify import ClientRecord, DataClass
from core.guard.redact_prompt import redact_prompt
from core.obs import OpsLogger, current_request_id

_ops = OpsLogger("gateway")

HOSTED_PROVIDERS: frozenset[ProviderName] = frozenset({"azure_openai", "anthropic"})
"""Providers that run off this machine. They never receive DC-4 (PHI) or DC-5 (NPI) text (B55-3)."""

HOSTED_REFUSED_FROM = DataClass.DC4


class Completion(BaseModel):
    """The result of one gateway call. ``text`` is plain model output: data to validate, never an instruction.

    ``data_class`` is the class the gate gave the input (None only on completions built outside the gateway, for
    example a test double); ``redacted`` lists the kinds of span replaced before the prompt, never their values.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    model: str
    provider: ProviderName | None
    ms: int = Field(ge=0)
    ok: bool
    error: str | None = None
    data_class: DataClass | None = None
    redacted: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _ok_xor_error(self) -> Self:
        if self.ok and self.error is not None:
            raise ValueError("a successful completion carries no error")
        if not self.ok and (not self.error or self.text):
            raise ValueError("a failed completion carries an error and no text")
        return self


@dataclass(frozen=True, slots=True)
class _Call:
    """What is known about one call before the provider runs; everything in it is safe to audit."""

    agent: str
    client_id: str | None
    task: str
    actor_kind: ActorKind | None
    request_id: str
    input_chars: int
    prompt_chars: int
    digest: str | None
    data_class: DataClass
    redacted: tuple[str, ...]
    prompt_est: int
    approval_id: str | None = None
    purpose: str | None = None
    gate: str | None = None
    """Set only on a hosted route: the register entry config names, the purpose (a short code) and the gate's code."""


def _today() -> date:
    return datetime.now(UTC).date()


@dataclass(frozen=True, slots=True)
class _HostedVerdict:
    """The gate's answer: a fixed code, the class checked, and the audit-safe approval id and purpose."""

    allowed: bool
    code: str
    gate_cls: DataClass
    approval_id: str | None
    purpose: str | None


class Gateway:
    """Routes each task to the provider and model named in config and returns a Completion.

    Model output is returned as text only. The gateway never parses it into tool calls, lever names or permission
    decisions; anything a caller derives from it must go through the lever registry, which validates the lever,
    its parameters, the caller's identity and client scope (core/levers). A fooled model can only return text.

    ``clock`` (seconds, default ``time.monotonic``) drives the budget windows, the breakers and the latency;
    ``audit`` receives one ``model.complete`` record per call; ``providers`` replaces named backends (synthetic
    doubles in tests). Budgets and breakers exist only when the config carries ``limits`` (``config/limits.json``).

    Hosted routes (B-90): ``vendor_register`` is the approval register (default: ``governance/ai-vendor-register.json``
    under the config root; a missing or invalid file means every hosted call is refused); ``today`` dates the
    review check; ``resolve_secret`` and ``azure_transport`` feed the Azure adapter (default: environment variables
    and no transport, so nothing can be sent).
    """

    def __init__(
        self,
        config: GatewayConfig,
        *,
        clock: Clock | None = None,
        audit: AuditSink | None = None,
        providers: Mapping[ProviderName, Provider] | None = None,
        vendor_register: VendorRegister | None = None,
        today: Callable[[], date] | None = None,
        resolve_secret: SecretResolver | None = None,
        azure_transport: Transport | None = None,
    ) -> None:
        self._config = config
        self._clock: Clock = clock or time.monotonic
        self._audit = audit
        self._today = today or _today
        self._register: VendorRegister | None = vendor_register
        if self._register is None:
            try:
                self._register = VendorRegister.load(config.root / REGISTER_FILE)
            except (OSError, ValueError):
                self._register = None  # fail closed: no register, no hosted call
        settings = config.providers
        self._providers: dict[ProviderName, Provider] = {
            "mock": MockProvider.from_file(config.mock_fixture_path),
            "ollama": OllamaProvider(
                settings.ollama.base_url, settings.ollama.timeout_s, settings.ollama.max_response_bytes
            ),
            "azure_openai": AzureOpenAIProvider(
                settings.azure_openai,
                register=self._register,
                resolve=resolve_secret,
                transport=azure_transport,
                today=self._today,
            ),
            "anthropic": AnthropicProvider(enabled=settings.anthropic.enabled),
        }
        self._providers.update(providers or {})
        limits = config.limits
        self._chars_per_token = limits.chars_per_token if limits else 4
        self._budget = BudgetTracker(limits, self._clock) if limits else None
        self._breakers: dict[ProviderName, CircuitBreaker] = (
            {
                name: CircuitBreaker(
                    failure_threshold=limits.breaker.failure_threshold, open_s=limits.breaker.open_s, clock=self._clock
                )
                for name in self._providers
            }
            if limits
            else {}
        )

    def complete(
        self,
        task: Task,
        text: str,
        *,
        client: ClientRecord | None = None,
        data_class: DataClass | None = None,
        agent: str | None = None,
        actor_kind: ActorKind | None = None,
        request_id: str | None = None,
        purpose: str | None = None,
    ) -> Completion:
        """Run one task. Provider failures (disabled, down, timed out, malformed reply) come back as ok=False.

        ``purpose`` is a short code (for example ``ticket-summary``) that a hosted route checks against the approval;
        it is ignored on local routes. It is never read from the text.

        ``client`` is the client record the text belongs to (its industry sets the floor for undeclared text);
        ``data_class`` declares a known class (for example DC-0 for a public KB article). Shapes in the text
        always raise the class; nothing lowers it. ``agent``, ``actor_kind`` and ``request_id`` say who is asking
        and correlate the audit record; a call with no agent or client is counted under ``unattributed`` budgets.
        """
        gated = redact_prompt(text, client=client, declared=data_class)
        cls, kinds = gated.data_class, gated.redacted
        call = _Call(
            agent=agent or UNATTRIBUTED,
            client_id=client.id if client is not None else None,
            task=task,
            actor_kind=actor_kind,
            request_id=request_id or current_request_id() or new_request_id(),
            input_chars=len(text),
            prompt_chars=len(gated.text),
            digest=None if gated.blocked else prompt_digest(gated.text),
            data_class=cls,
            redacted=kinds,
            prompt_est=estimate_tokens(len(gated.text), self._chars_per_token),
        )

        def failed(
            error: str, reason: str, status: str, model: str, provider: ProviderName | None, ms: int
        ) -> Completion:
            completion = Completion(
                text="", model=model, provider=provider, ms=ms, ok=False, error=error, data_class=cls, redacted=kinds
            )
            return self._finish(call, completion, status=status, reason=reason)

        def refused(error: str, reason: str, model: str = "", provider: ProviderName | None = None) -> Completion:
            return failed(error, reason, "denied", model, provider, 0)

        if gated.blocked:
            return refused(
                f"blocked: {cls.label} text (a secret shape) never reaches a model; nothing was sent", "blocked"
            )
        if task not in self._config.routes:
            return refused(f"no route for task {task!r}", "no-route")
        provider_name, model = self._config.resolve(task)
        if not self._config.providers.is_enabled(provider_name):
            return refused(
                f"provider {provider_name!r} is disabled in config/models.json",
                "provider-disabled",
                model,
                provider_name,
            )
        if provider_name in HOSTED_PROVIDERS:
            hosted = self._hosted_gate(provider_name, cls, client, purpose)
            call = replace(call, approval_id=hosted.approval_id, purpose=hosted.purpose, gate=hosted.code)
            if not hosted.allowed:
                if cls >= HOSTED_REFUSED_FROM:
                    return refused(
                        f"refused: {cls.label} text may not go to hosted provider {provider_name!r} (B55-3); "
                        "route it to a local provider",
                        "hosted-refused",
                        model,
                        provider_name,
                    )
                return refused(
                    f"refused: hosted provider {provider_name!r} has no recorded approval for this call "
                    f"({hosted.code}); nothing was sent",
                    "hosted-unapproved",
                    model,
                    provider_name,
                )
        breaker = self._breakers.get(provider_name)
        if breaker is not None and not breaker.allow():
            return refused(
                f"circuit open: provider {provider_name!r} is failing; calls fail fast until it recovers",
                "circuit-open",
                model,
                provider_name,
            )
        reservation = None
        if self._budget is not None:
            admitted = self._budget.reserve(client=call.client_id, agent=agent, prompt_tokens=call.prompt_est)
            if isinstance(admitted, Denial):
                if breaker is not None:
                    breaker.cancel_probe()  # the call never reached the provider: free a half-open probe slot
                return refused("budget exceeded", admitted.reason, model, provider_name)
            reservation = admitted
        started = self._clock()
        try:
            output = self._providers[provider_name].complete(task=task, model=model, text=gated.text)
        except ProviderError as exc:
            if breaker is not None:
                breaker.record_failure()
            return failed(str(exc), "provider-error", "error", model, provider_name, self._elapsed_ms(started))
        except Exception:
            # A bug in an adapter is not a ProviderError. It still counts against the breaker and is audited,
            # and it is not hidden from the caller.
            if breaker is not None:
                breaker.record_failure()
            failed("gateway crashed", "crashed", "error", model, provider_name, self._elapsed_ms(started))
            raise
        if breaker is not None:
            breaker.record_success()
        completion_est = estimate_tokens(len(output), self._chars_per_token)
        if self._budget is not None and reservation is not None:
            self._budget.settle(reservation, completion_est)
        completion = Completion(
            text=output,
            model=model,
            provider=provider_name,
            ms=self._elapsed_ms(started),
            ok=True,
            data_class=cls,
            redacted=kinds,
        )
        return self._finish(call, completion, status="ok", reason="ok", completion_est=completion_est)

    def _hosted_gate(
        self, provider: ProviderName, cls: DataClass, client: ClientRecord | None, purpose: str | None
    ) -> _HostedVerdict:
        """The B-90 approval gate. Reads the register and config, never the text. Anything but a clear yes is a no."""
        settings = self._config.providers.settings(provider)
        approval_id = settings.approval_id if isinstance(settings, HostedSettings) else None
        safe_purpose = purpose if purpose and re.fullmatch(PURPOSE_PATTERN, purpose) else None
        gate_cls = cls

        def verdict(allowed: bool, code: str) -> _HostedVerdict:
            return _HostedVerdict(allowed, code, gate_cls, approval_id, safe_purpose)

        if self._register is None:
            return verdict(False, "register-unavailable")
        decision = self._register.check(
            approval_id=approval_id,
            provider=provider,
            client_id=client.id if client is not None else None,
            data_class=gate_cls,
            purpose=safe_purpose,
            today=self._today(),
        )
        if not decision.allowed:
            return verdict(False, decision.code)
        # The client record, not the caller, says whether this client's text may go to a hosted model (D6-11).
        if getattr(client, "model_processing", None) != "hosted":
            return verdict(False, "client-not-hosted")
        return verdict(True, "ok")

    def _elapsed_ms(self, started: float) -> int:
        return round((self._clock() - started) * 1000)

    def _finish(
        self, call: _Call, completion: Completion, *, status: str, reason: str, completion_est: int = 0
    ) -> Completion:
        """Log the call, write the model-call record (when an audit sink is set), return or withhold the completion."""
        _ops.log(
            "model.complete",
            status,
            client=call.client_id,
            request_id=call.request_id,
            duration_ms=completion.ms,
            provider=completion.provider,
            model=completion.model or None,
            task=call.task,
            status=status,
            reason=reason,
            ok=completion.ok,
            data_class=call.data_class.label,
            actor_kind=call.actor_kind,
            input_chars=call.input_chars,
            prompt_chars=call.prompt_chars,
            completion_chars=len(completion.text),
            prompt_est=call.prompt_est,
            completion_est=completion_est,
        )
        if self._audit is None:
            return completion
        try:
            self._audit.append(
                agent=call.agent,
                client=call.client_id,
                lever=MODEL_LEVER,
                params={
                    "provider": completion.provider,
                    "model": completion.model or None,
                    "task": call.task,
                    "prompt_sha256": call.digest,
                    "input_chars": call.input_chars,
                    "prompt_chars": call.prompt_chars,
                    "data_class": call.data_class.label,
                    "redacted_kinds": list(call.redacted),
                    **({"approval_id": call.approval_id, "purpose": call.purpose} if call.gate else {}),
                },
                mode="execute",
                result={
                    "status": status,
                    "ok": completion.ok,
                    "reason": reason,
                    "latency_ms": completion.ms,
                    "completion_chars": len(completion.text),
                    "prompt_est": call.prompt_est,
                    "completion_est": completion_est,
                    **({"gate": call.gate} if call.gate else {}),
                },
                event="model.complete",
                actor_kind=call.actor_kind,
                request_id=call.request_id,
            )
        except (AuditError, OSError):
            if not completion.ok:
                return completion
            return Completion(
                text="",
                model=completion.model,
                provider=completion.provider,
                ms=completion.ms,
                ok=False,
                error="audit unavailable: the model call ran but its result is withheld; fix the audit log",
                data_class=call.data_class,
                redacted=call.redacted,
            )
        return completion
