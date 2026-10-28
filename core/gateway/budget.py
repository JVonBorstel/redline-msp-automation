"""Gateway budgets and circuit breaker (B-80). Pure bookkeeping: no network, no sleeping, no wall clock.

Both classes take a ``Clock`` (a zero-argument callable returning seconds), so a test moves time by hand and the
gateway uses ``time.monotonic``. State is in memory and per process: a restart resets every counter (see specs/B-80.md).

**Budgets.** Three scopes are tracked for every call: ``global``, ``client`` and ``agent``. Each scope has an optional
``Budget`` (calls and estimated tokens per window). A call is admitted only if every scope has room, and then it is
charged to all of them at once under one lock, so a call refused by one scope costs the others nothing. The window opens
at the first call after a reset and closes ``window_s`` seconds later; every counter then returns to zero.

Tokens are estimates: ``ceil(characters / chars_per_token)``. The prompt estimate is checked and charged before the
call; the completion estimate is charged after it, so a single call can overshoot a token budget by one completion and
the next call is then refused.

**Breaker.** One ``CircuitBreaker`` per provider. ``failure_threshold`` consecutive failures open it; while open every
call fails fast without reaching the provider. After ``open_s`` seconds it is half-open and lets exactly one probe call
through: success closes it, failure re-opens it for another ``open_s``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from core.gateway.config import Budget, LimitsConfig

Clock = Callable[[], float]
BreakerState = Literal["closed", "open", "half-open"]

UNATTRIBUTED = "unattributed"
"""The id a call is counted under when the caller names no client or agent, so it still meets the default budgets."""

GLOBAL_ID = "*"


def estimate_tokens(chars: int, chars_per_token: int) -> int:
    """Estimated tokens for ``chars`` characters: ceil(chars / chars_per_token). Not a measurement."""
    return -(-chars // chars_per_token)


@dataclass(frozen=True, slots=True)
class Reservation:
    """What an admitted call has been charged: the scopes it counts against and its prompt estimate."""

    scopes: tuple[tuple[str, str], ...]
    prompt_tokens: int


@dataclass(frozen=True, slots=True)
class Denial:
    """Which scope refused a call and on which dimension. ``reason`` is a fixed code, never text from a caller."""

    scope: Literal["global", "client", "agent"]
    dimension: Literal["calls", "tokens"]

    @property
    def reason(self) -> str:
        return f"budget:{self.scope}:{self.dimension}"


class BudgetTracker:
    def __init__(self, limits: LimitsConfig, clock: Clock) -> None:
        self._limits = limits
        self._clock = clock
        self._lock = threading.Lock()
        self._window_start: float | None = None
        self._used: dict[tuple[str, str], list[int]] = {}

    def reserve(self, *, client: str | None, agent: str | None, prompt_tokens: int) -> Reservation | Denial:
        """Admit and charge one call (one call, ``prompt_tokens`` tokens), or say which scope has no room."""
        client_id, agent_id = client or UNATTRIBUTED, agent or UNATTRIBUTED
        wanted: tuple[tuple[Literal["global", "client", "agent"], str, Budget | None], ...] = (
            ("global", GLOBAL_ID, self._limits.global_),
            ("client", client_id, self._limits.per_client.for_id(client_id)),
            ("agent", agent_id, self._limits.per_agent.for_id(agent_id)),
        )
        with self._lock:
            self._roll()
            for scope, name, budget in wanted:
                calls, tokens = self._used.get((scope, name), [0, 0])
                if budget is None:
                    continue
                if budget.max_calls is not None and calls + 1 > budget.max_calls:
                    return Denial(scope, "calls")
                if budget.max_tokens is not None and tokens + prompt_tokens > budget.max_tokens:
                    return Denial(scope, "tokens")
            keys = tuple((scope, name) for scope, name, _ in wanted)
            for key in keys:
                used = self._used.setdefault(key, [0, 0])
                used[0] += 1
                used[1] += prompt_tokens
            return Reservation(keys, prompt_tokens)

    def settle(self, reservation: Reservation, completion_tokens: int) -> None:
        """Charge the completion estimate to every scope the call was admitted under."""
        with self._lock:
            self._roll()
            for key in reservation.scopes:
                self._used.setdefault(key, [0, 0])[1] += completion_tokens

    def usage(self) -> dict[tuple[str, str], tuple[int, int]]:
        """(calls, estimated tokens) used so far in this window, by (scope, id)."""
        with self._lock:
            self._roll()
            return {key: (used[0], used[1]) for key, used in self._used.items()}

    def _roll(self) -> None:
        now = self._clock()
        if self._window_start is None or now - self._window_start >= self._limits.window_s:
            self._window_start = now
            self._used.clear()


class CircuitBreaker:
    """Closed -> open after ``failure_threshold`` consecutive failures -> half-open after ``open_s`` -> one probe."""

    def __init__(self, *, failure_threshold: int, open_s: float, clock: Clock) -> None:
        self._threshold = failure_threshold
        self._open_s = open_s
        self._clock = clock
        self._lock = threading.Lock()
        self._state: BreakerState = "closed"
        self._failures = 0
        self._opened_at = 0.0
        self._probe_out = False

    @property
    def state(self) -> BreakerState:
        with self._lock:
            self._tick()
            return self._state

    def allow(self) -> bool:
        """True when a call may go to the provider. In half-open state only the first caller gets True (the probe)."""
        with self._lock:
            self._tick()
            if self._state == "closed":
                return True
            if self._state == "half-open" and not self._probe_out:
                self._probe_out = True
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._state, self._failures, self._probe_out = "closed", 0, False

    def record_failure(self) -> None:
        with self._lock:
            self._tick()
            if self._state == "half-open":
                self._trip()
            elif self._state == "closed":
                self._failures += 1
                if self._failures >= self._threshold:
                    self._trip()

    def cancel_probe(self) -> None:
        """Give back the half-open probe slot when the call it was meant for never reached the provider."""
        with self._lock:
            self._probe_out = False

    def _trip(self) -> None:
        self._state, self._opened_at, self._failures, self._probe_out = "open", self._clock(), 0, False

    def _tick(self) -> None:
        if self._state == "open" and self._clock() - self._opened_at >= self._open_s:
            self._state, self._probe_out = "half-open", False
