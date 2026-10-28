"""B-80 gateway budgets, circuit breaker and model-call audit (specs/B-80.md).

Offline and synthetic: provider doubles stand in for models, the clock is injected (no sleeps, no wall time), the audit
log lives under tmp_path. Contoso Dental and Fabrikam Capital are invented clients.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from core.audit import AuditLog, verify_chain
from core.audit.router import AuditRouter
from core.gateway import Gateway, GatewayConfig, ProviderError, ProviderName, Task
from core.gateway.budget import BudgetTracker, CircuitBreaker, Reservation, estimate_tokens
from core.gateway.config import LimitsConfig
from core.guard.classify import DataClass

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "fixtures" / "gateway" / "mock_responses.json"

PROMPT_MARKER = "ZEBRA-PROMPT-MARKER"
REPLY_MARKER = "QUOKKA-REPLY-MARKER"


@dataclass(frozen=True)
class Client:
    id: str
    industry: str = "dental"


CONTOSO = Client("contoso-dental")
FABRIKAM = Client("fabrikam-capital", "financial")


class FakeClock:
    """A clock the test moves by hand. Nothing here ever sleeps."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Scripted:
    """A provider double: counts calls, can fail on demand, can spend fake time."""

    def __init__(
        self, name: ProviderName = "mock", reply: str = "fine", clock: FakeClock | None = None, latency_s: float = 0.0
    ) -> None:
        self.name: ProviderName = name
        self.reply = reply
        self.clock = clock
        self.latency_s = latency_s
        self.failing = False
        self.calls = 0
        self.seen: list[str] = []

    def complete(self, *, task: Task, model: str, text: str) -> str:
        self.calls += 1
        self.seen.append(text)
        if self.clock is not None:
            self.clock.advance(self.latency_s)
        if self.failing:
            raise ProviderError("boom: backend said PRIVATE-DETAIL")
        return self.reply


def limits(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "window_s": 3600,
        "chars_per_token": 4,
        "breaker": {"failure_threshold": 3, "open_s": 30},
    }
    return base | overrides


def make_config(limits_section: dict[str, Any] | None = None, *, with_ollama_route: bool = False) -> GatewayConfig:
    routes = {"classify": {"provider": "mock", "model": "small"}, "summarize": {"provider": "mock", "model": "small"}}
    if with_ollama_route:
        routes["reason"] = {"provider": "ollama", "model": "small"}
    data: dict[str, Any] = {
        "providers": {
            "mock": {"fixture": str(FIXTURE), "models": {"small": "mock-small", "strong": "mock-strong"}},
            "ollama": {
                "enabled": True,
                "base_url": "http://127.0.0.1:11434/v1",
                "timeout_s": 2,
                "models": {"small": "local-small"},
            },
        },
        "routes": routes,
        "root": str(ROOT),
    }
    if limits_section is not None:
        data["limits"] = limits_section
    return GatewayConfig.model_validate(data)


def make_gateway(
    limits_section: dict[str, Any] | None = None,
    *,
    clock: FakeClock | None = None,
    provider: Scripted | None = None,
    audit: Any = None,
    with_ollama_route: bool = False,
    ollama: Scripted | None = None,
) -> tuple[Gateway, Scripted, FakeClock]:
    clock = clock or FakeClock()
    provider = provider or Scripted(clock=clock)
    providers: dict[ProviderName, Any] = {"mock": provider}
    if ollama is not None:
        providers["ollama"] = ollama
    gateway = Gateway(
        make_config(limits_section, with_ollama_route=with_ollama_route),
        clock=clock,
        audit=audit,
        providers=providers,
    )
    return gateway, provider, clock


def records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def ungroup(digest: str) -> str:
    return "".join(digest.split())


# --- B80-1: budgets ------------------------------------------------------------------------------------------------


def test_b80_1_no_limits_configured_means_the_gateway_behaves_as_before() -> None:
    gateway, provider, _ = make_gateway(None)
    results = [gateway.complete("classify", f"ticket {n}") for n in range(25)]
    assert all(r.ok for r in results)
    assert provider.calls == 25


def test_b80_1_global_call_budget_returns_budget_exceeded() -> None:
    gateway, provider, _ = make_gateway(limits(**{"global": {"max_calls": 2}}))
    assert gateway.complete("classify", "one").ok
    assert gateway.complete("classify", "two").ok
    third = gateway.complete("classify", "three")
    assert third.ok is False
    assert third.error == "budget exceeded"
    assert third.text == ""
    assert provider.calls == 2


def test_b80_1_a_client_over_budget_does_not_block_another_client() -> None:
    gateway, provider, _ = make_gateway(limits(per_client={"default": {"max_calls": 1}}))
    assert gateway.complete("classify", "a", client=CONTOSO).ok
    blocked = gateway.complete("classify", "b", client=CONTOSO)
    assert (blocked.ok, blocked.error) == (False, "budget exceeded")
    assert gateway.complete("classify", "c", client=FABRIKAM).ok
    assert provider.calls == 2


def test_b80_1_per_client_override_beats_the_default() -> None:
    section = limits(per_client={"default": {"max_calls": 1}, "overrides": {"contoso-dental": {"max_calls": 3}}})
    gateway, _, _ = make_gateway(section)
    assert [gateway.complete("classify", str(n), client=CONTOSO).ok for n in range(4)] == [True, True, True, False]
    assert [gateway.complete("classify", str(n), client=FABRIKAM).ok for n in range(2)] == [True, False]


def test_b80_1_per_agent_budget_is_separate_from_the_client_budget() -> None:
    gateway, _, _ = make_gateway(limits(per_agent={"default": {"max_calls": 2}}))
    assert gateway.complete("classify", "1", client=CONTOSO, agent="triage-bot").ok
    assert gateway.complete("classify", "2", client=CONTOSO, agent="triage-bot").ok
    assert gateway.complete("classify", "3", client=CONTOSO, agent="triage-bot").error == "budget exceeded"
    assert gateway.complete("classify", "4", client=CONTOSO, agent="summary-bot").ok


def test_b80_1_token_budget_uses_the_configured_characters_per_token() -> None:
    assert estimate_tokens(40, 4) == 10
    assert estimate_tokens(41, 4) == 11
    assert estimate_tokens(0, 4) == 0
    # 40-character prompt = 10 estimated tokens in, a 4-character reply = 1 out: 11 per call.
    provider = Scripted(reply="done")
    gateway, _, _ = make_gateway(limits(**{"global": {"max_tokens": 25}}), provider=provider)
    prompt = "x" * 40
    assert gateway.complete("summarize", prompt).ok
    assert gateway.complete("summarize", prompt).ok
    third = gateway.complete("summarize", prompt)
    assert (third.ok, third.error) == (False, "budget exceeded")
    assert provider.calls == 2


def test_b80_1_a_prompt_bigger_than_the_whole_token_budget_is_refused_up_front() -> None:
    gateway, provider, _ = make_gateway(limits(**{"global": {"max_tokens": 5}}))
    assert gateway.complete("summarize", "y" * 100).error == "budget exceeded"
    assert provider.calls == 0


def test_b80_1_a_denied_call_is_not_charged_to_the_other_scopes() -> None:
    gateway, _, _ = make_gateway(limits(**{"global": {"max_calls": 2}}, per_agent={"default": {"max_calls": 1}}))
    assert gateway.complete("classify", "1", agent="a").ok
    assert gateway.complete("classify", "2", agent="a").error == "budget exceeded"  # agent scope, global untouched
    assert gateway.complete("classify", "3", agent="b").ok  # global now at 2
    assert gateway.complete("classify", "4", agent="c").error == "budget exceeded"  # global scope


def test_b80_1_budgets_reset_when_the_window_passes() -> None:
    gateway, _, clock = make_gateway(limits(window_s=60, **{"global": {"max_calls": 1}}))
    assert gateway.complete("classify", "1").ok
    assert gateway.complete("classify", "2").error == "budget exceeded"
    clock.advance(59)
    assert gateway.complete("classify", "3").error == "budget exceeded"
    clock.advance(1)
    assert gateway.complete("classify", "4").ok


def test_b80_1_a_caller_with_no_agent_or_client_still_falls_under_the_default_budgets() -> None:
    section = limits(per_client={"default": {"max_calls": 1}}, per_agent={"default": {"max_calls": 1}})
    gateway, _, _ = make_gateway(section)
    assert gateway.complete("classify", "1").ok
    assert gateway.complete("classify", "2").error == "budget exceeded"


def test_b80_1_a_blocked_or_unrouted_call_costs_no_budget() -> None:
    gateway, provider, _ = make_gateway(limits(**{"global": {"max_calls": 1}}))
    secret_text = "token sk-" + "a1b2c3d4e5f6a7b8c9d0e1f2"
    assert gateway.complete("classify", secret_text).ok is False  # DC-6, never sent
    assert gateway.complete("reason", "no route for this task").ok is False
    assert gateway.complete("classify", "real work").ok
    assert provider.calls == 1


def test_b80_1_exactly_the_budgeted_number_of_threaded_calls_succeed() -> None:
    gateway, provider, _ = make_gateway(limits(**{"global": {"max_calls": 10}}))
    outcomes: list[bool] = []
    guard = threading.Lock()

    def worker(n: int) -> None:
        ok = gateway.complete("classify", f"ticket {n}").ok
        with guard:
            outcomes.append(ok)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count(True) == 10
    assert provider.calls == 10


def test_b80_1_the_tracker_reports_usage_per_scope() -> None:
    clock = FakeClock()
    tracker = BudgetTracker(LimitsConfig.model_validate(limits(**{"global": {"max_calls": 5}})), clock)
    reservation = tracker.reserve(client="contoso-dental", agent="triage-bot", prompt_tokens=7)
    assert isinstance(reservation, Reservation)
    tracker.settle(reservation, completion_tokens=3)
    usage = tracker.usage()
    assert usage[("global", "*")] == (1, 10)
    assert usage[("client", "contoso-dental")] == (1, 10)
    assert usage[("agent", "triage-bot")] == (1, 10)


def test_b80_1_the_committed_limits_file_loads_and_is_attached_to_the_config() -> None:
    config = GatewayConfig.load(ROOT)
    assert config.limits is not None
    assert config.limits.window_s > 0
    assert config.limits.breaker.failure_threshold >= 1


def test_b80_1_a_root_without_a_limits_file_loads_with_no_limits(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    for name in ("models.json", "routing.json"):
        (tmp_path / "config" / name).write_bytes((ROOT / "config" / name).read_bytes())
    assert GatewayConfig.load(tmp_path).limits is None


@pytest.mark.parametrize(
    "bad",
    [
        {"window_s": 0},
        {"chars_per_token": 0},
        {"global": {"max_calls": 0}},
        {"global": {"max_tokens": -1}},
        {"global": {"max_calls": 1, "surprise": 1}},
        {"per_client": {"default": {"max_calls": True}}},
        {"per_agent": {"overrides": {"x": {}}}},
        {"breaker": {"failure_threshold": 0, "open_s": 5}},
        {"breaker": {"failure_threshold": 2, "open_s": 0}},
        {"surprise": 1},
    ],
)
def test_b80_1_invalid_limits_are_refused_at_load(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        LimitsConfig.model_validate(limits() | bad)


def test_b80_1_a_limits_file_with_an_unknown_version_is_refused(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    for name in ("models.json", "routing.json", "limits.json"):
        (tmp_path / "config" / name).write_bytes((ROOT / "config" / name).read_bytes())
    path = tmp_path / "config" / "limits.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["version"] = 2
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported config version"):
        GatewayConfig.load(tmp_path)


# --- B80-2: circuit breaker -----------------------------------------------------------------------------------------


def test_b80_2_a_provider_failing_n_times_opens_the_breaker_and_calls_fail_fast() -> None:
    gateway, provider, _ = make_gateway(limits())
    provider.failing = True
    for n in range(3):
        failed = gateway.complete("classify", f"try {n}")
        assert failed.ok is False
        assert "circuit open" not in (failed.error or "")
    fast = gateway.complete("classify", "after the trip")
    assert fast.ok is False
    assert fast.error is not None
    assert fast.error.startswith("circuit open")
    assert provider.calls == 3  # the fourth never reached the provider


def test_b80_2_the_breaker_recovers_after_t_seconds() -> None:
    gateway, provider, clock = make_gateway(limits())
    provider.failing = True
    for n in range(3):
        gateway.complete("classify", f"try {n}")
    provider.failing = False
    clock.advance(29.9)
    assert (gateway.complete("classify", "too soon").error or "").startswith("circuit open")
    clock.advance(0.1)
    probe = gateway.complete("classify", "probe")
    assert probe.ok
    assert gateway.complete("classify", "normal again").ok
    assert provider.calls == 5


def test_b80_2_a_failed_probe_reopens_for_another_t_seconds() -> None:
    gateway, provider, clock = make_gateway(limits())
    provider.failing = True
    for n in range(3):
        gateway.complete("classify", f"try {n}")
    clock.advance(30)
    assert gateway.complete("classify", "probe").ok is False  # reaches the provider, fails
    assert provider.calls == 4
    clock.advance(29)
    assert (gateway.complete("classify", "still open").error or "").startswith("circuit open")
    assert provider.calls == 4
    clock.advance(1)
    provider.failing = False
    assert gateway.complete("classify", "second probe").ok


def test_b80_2_a_success_resets_the_count_of_consecutive_failures() -> None:
    gateway, provider, _ = make_gateway(limits())
    for failing in (True, True, False, True, True):
        provider.failing = failing
        gateway.complete("classify", "x")
    provider.failing = False
    assert gateway.complete("classify", "still closed").ok


def test_b80_2_one_providers_failures_do_not_open_another_providers_breaker() -> None:
    clock = FakeClock()
    mock, ollama = Scripted(clock=clock), Scripted("ollama", clock=clock)
    gateway, _, _ = make_gateway(limits(), clock=clock, provider=mock, ollama=ollama, with_ollama_route=True)
    ollama.failing = True
    for n in range(3):
        gateway.complete("reason", f"try {n}")
    assert (gateway.complete("reason", "x").error or "").startswith("circuit open")
    assert gateway.complete("classify", "mock is fine").ok


def test_b80_2_a_fast_failed_call_costs_no_budget() -> None:
    gateway, provider, clock = make_gateway(limits(**{"global": {"max_calls": 4}}))
    provider.failing = True
    for n in range(3):
        gateway.complete("classify", f"try {n}")  # 3 attempts, charged
    for n in range(5):
        assert (gateway.complete("classify", f"fast {n}").error or "").startswith("circuit open")
    provider.failing = False
    clock.advance(30)
    assert gateway.complete("classify", "the fourth and last budgeted call").ok
    assert gateway.complete("classify", "fifth").error == "budget exceeded"
    assert provider.calls == 4


def test_b80_2_breaker_unit_states_follow_the_injected_clock() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=2, open_s=10, clock=clock)
    assert breaker.state == "closed"
    assert breaker.allow()
    breaker.record_failure()
    assert breaker.state == "closed"
    assert breaker.allow()
    breaker.record_failure()
    assert breaker.state == "open"
    assert not breaker.allow()
    clock.advance(9.99)
    assert breaker.state == "open"
    clock.advance(0.01)
    assert breaker.state == "half-open"
    assert breaker.allow()  # the one probe
    assert not breaker.allow()  # nobody else while it is in flight
    breaker.record_success()
    assert breaker.state == "closed"
    assert breaker.allow()


def test_b80_2_a_cancelled_probe_frees_the_slot() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=1, open_s=5, clock=clock)
    assert breaker.allow()
    breaker.record_failure()
    clock.advance(5)
    assert breaker.allow()
    assert not breaker.allow()
    breaker.cancel_probe()
    assert breaker.allow()


def test_b80_2_an_unexpected_exception_counts_as_a_failure_and_is_not_swallowed() -> None:
    class Crashing(Scripted):
        def complete(self, *, task: Task, model: str, text: str) -> str:
            raise RuntimeError("bug in the adapter")

    clock = FakeClock()
    gateway, _, _ = make_gateway(limits(), clock=clock, provider=Crashing(clock=clock))
    for _ in range(3):
        with pytest.raises(RuntimeError):
            gateway.complete("classify", "x")
    assert (gateway.complete("classify", "x").error or "").startswith("circuit open")


# --- B80-3: model-call audit ----------------------------------------------------------------------------------------


def audited(tmp_path: Path, **kwargs: Any) -> tuple[Gateway, Scripted, FakeClock, Path]:
    log = AuditLog(tmp_path / "audit" / "model.jsonl")
    gateway, provider, clock = make_gateway(audit=log, **kwargs)
    return gateway, provider, clock, log.path


def test_b80_3_each_call_writes_one_model_complete_v2_record(tmp_path: Path) -> None:
    clock = FakeClock()
    provider = Scripted(reply=REPLY_MARKER, clock=clock, latency_s=0.25)
    gateway, _, _, path = audited(tmp_path, clock=clock, provider=provider)
    prompt = f"{PROMPT_MARKER} customer cannot print"
    completion = gateway.complete("summarize", prompt, client=CONTOSO, agent="summary-bot")
    assert completion.ok
    [record] = records(path)
    assert (record["v"], record["event"], record["lever"]) == (2, "model.complete", "model.complete")
    assert (record["agent"], record["client"], record["mode"]) == ("summary-bot", "contoso-dental", "execute")
    params, result = record["params"], record["result"]
    assert (params["provider"], params["model"], params["task"]) == ("mock", "mock-small", "summarize")
    assert ungroup(params["prompt_sha256"]) == hashlib.sha256(prompt.encode()).hexdigest()
    assert params["input_chars"] == len(prompt)
    assert params["prompt_chars"] == len(prompt)
    assert result["completion_chars"] == len(REPLY_MARKER)
    assert result["latency_ms"] == 250
    assert (result["ok"], result["status"]) == (True, "ok")
    assert completion.ms == 250


def test_b80_3_no_prompt_or_completion_text_is_ever_written(tmp_path: Path) -> None:
    provider = Scripted(reply=REPLY_MARKER)
    gateway, _, _, path = audited(tmp_path, provider=provider)
    gateway.complete("summarize", f"{PROMPT_MARKER} body of the ticket")
    gateway.complete("summarize", f"{PROMPT_MARKER} body", client=CONTOSO)
    raw = path.read_bytes().decode("utf-8")
    assert PROMPT_MARKER not in raw
    assert REPLY_MARKER not in raw
    assert "body of the ticket" not in raw


def test_b80_3_pii_is_hashed_after_redaction_and_never_written(tmp_path: Path) -> None:
    gateway, provider, _, path = audited(tmp_path)
    ssn = "123-45-6789"
    original = f"patient SSN {ssn} needs a callback"
    gateway.complete("summarize", original, client=CONTOSO)
    raw = path.read_text(encoding="utf-8")
    assert ssn not in raw
    [record] = records(path)
    sent = provider.seen[0]
    assert ssn not in sent
    assert ungroup(record["params"]["prompt_sha256"]) == hashlib.sha256(sent.encode()).hexdigest()
    assert record["params"]["input_chars"] == len(original)
    assert record["params"]["prompt_chars"] == len(sent)
    assert record["params"]["redacted_kinds"]


def test_b80_3_a_secret_shaped_prompt_is_denied_and_recorded_with_no_hash(tmp_path: Path) -> None:
    gateway, provider, _, path = audited(tmp_path)
    secret = "sk-" + "a1b2c3d4e5f6a7b8c9d0e1f2"
    completion = gateway.complete("classify", f"use {secret} to log in")
    assert completion.ok is False
    assert provider.calls == 0
    raw = path.read_text(encoding="utf-8")
    assert secret not in raw
    [record] = records(path)
    assert record["result"]["status"] == "denied"
    assert record["result"]["ok"] is False
    assert record["params"]["prompt_sha256"] is None
    assert record["params"]["data_class"] == DataClass.DC6.label


def test_b80_3_denied_calls_are_recorded_too(tmp_path: Path) -> None:
    gateway, _, _, path = audited(tmp_path, limits_section=limits(**{"global": {"max_calls": 1}}))
    gateway.complete("classify", "one", agent="triage-bot")
    gateway.complete("classify", "two", agent="triage-bot")
    gateway.complete("reason", "unrouted", agent="triage-bot")
    first, over_budget, unrouted = records(path)
    assert first["result"]["status"] == "ok"
    assert over_budget["result"]["status"] == "denied"
    assert over_budget["result"]["reason"].startswith("budget")
    assert over_budget["result"]["latency_ms"] == 0
    assert unrouted["result"]["status"] == "denied"
    assert unrouted["params"]["provider"] is None
    assert all(r["event"] == "model.complete" for r in (first, over_budget, unrouted))


def test_b80_3_breaker_fast_failures_and_provider_errors_are_recorded(tmp_path: Path) -> None:
    gateway, provider, _, path = audited(tmp_path, limits_section=limits())
    provider.failing = True
    for n in range(4):
        gateway.complete("classify", f"try {n}")
    statuses = [(r["result"]["status"], r["result"]["reason"]) for r in records(path)]
    assert statuses[:3] == [("error", "provider-error")] * 3
    assert statuses[3] == ("denied", "circuit-open")
    assert "PRIVATE-DETAIL" not in path.read_text(encoding="utf-8")


def test_b80_3_the_audit_chain_verifies_and_never_blanks_a_field(tmp_path: Path) -> None:
    gateway, _, _, path = audited(tmp_path, limits_section=limits(**{"global": {"max_calls": 2}}))
    for n in range(4):
        gateway.complete("classify", f"ticket {n}", client=CONTOSO, agent="triage-bot")
    outcome = verify_chain(path, path.with_name(path.name + ".head"))
    assert outcome.ok, outcome.reason
    assert (outcome.v1_records, outcome.v2_records) == (0, 4)
    assert "[REDACTED]" not in path.read_text(encoding="utf-8")


def test_b80_3_request_id_and_actor_kind_are_carried_and_defaulted(tmp_path: Path) -> None:
    gateway, _, _, path = audited(tmp_path)
    gateway.complete("classify", "a", agent="triage-bot", actor_kind="agent", request_id="req-fixed-1")
    gateway.complete("classify", "b")
    gateway.complete("classify", "c")
    first, second, third = records(path)
    assert (first["request_id"], first["actor_kind"]) == ("req-fixed-1", "agent")
    assert second["actor_kind"] == "unknown"
    assert second["agent"] == "unattributed"
    assert second["request_id"].startswith("req-")
    assert second["request_id"] != third["request_id"]


def test_b80_3_an_audit_router_gives_each_client_its_own_chain(tmp_path: Path) -> None:
    router = AuditRouter(tmp_path / "audit")
    gateway, _, _ = make_gateway(audit=router)
    gateway.complete("classify", "a", client=CONTOSO)
    gateway.complete("classify", "b", client=FABRIKAM)
    gateway.complete("classify", "c")
    assert sorted(router.paths()) == ["_msp", "contoso-dental", "fabrikam-capital"]
    assert all(r.ok for r in router.verify_all().values())


def test_b80_3_if_the_audit_record_cannot_be_written_the_completion_is_withheld(tmp_path: Path) -> None:
    gateway, provider, _, path = audited(tmp_path)
    assert gateway.complete("classify", "first").ok
    head = path.with_name(path.name + ".head")
    head.write_text(json.dumps({"seq": 99, "hash": "0" * 64}) + "\n", encoding="utf-8")  # pin no longer matches
    withheld = gateway.complete("classify", "second")
    assert withheld.ok is False
    assert withheld.text == ""
    assert withheld.error is not None
    assert withheld.error.startswith("audit unavailable")
    assert provider.calls == 2  # it ran; its text was withheld


def test_b80_3_no_audit_sink_means_no_file_and_no_change_in_results(tmp_path: Path) -> None:
    gateway, _, _ = make_gateway(None)
    assert gateway.complete("classify", "x").ok
    assert not any(tmp_path.iterdir())


def test_b80_3_audit_field_names_survive_the_redactor(tmp_path: Path) -> None:
    """The audit redactor blanks any key containing token/key/secret: no field we write may contain those words."""
    gateway, _, _, path = audited(tmp_path)
    gateway.complete("classify", "x", client=CONTOSO, agent="triage-bot")
    [record] = records(path)
    names = set(record["params"]) | set(record["result"])
    assert not {n for n in names if any(w in n.lower() for w in ("token", "key", "secret", "password"))}
