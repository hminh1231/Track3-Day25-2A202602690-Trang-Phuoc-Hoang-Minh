"""Part C — ResilientClient: compose classification, retry, breaker and fallback.

The simulator calls ``start`` for every logical LLM call, then ``on_success``
or ``on_error`` for every attempt. You answer with ``Send`` (try a provider,
maybe after a delay) or ``GiveUp`` (user gets a static degraded answer).

Tests: tests/test_client.py, then `make compare` (6 incident tapes).

Per-call scratch space lives in ``call.state`` (a dict). Suggested keys:
    "ladder": list[str]  providers this call may use, in order
    "idx":    int        position of the provider we are currently on
    "tries":  int        attempts already made on that provider

Decision table for ``on_error`` (implement it!):

| ErrorKind        | breaker              | then                                                    |
|------------------|----------------------|---------------------------------------------------------|
| CLIENT_ERROR     | release (not health) | GiveUp("client_error") — never retry, never fail over   |
| QUOTA_EXHAUSTED  | release              | cooldown provider for quota_cooldown_s; fail over now   |
| RATE_LIMITED     | release              | cooldown provider until now + retry_after; fail over now|
| OVERLOADED /     | on_failure           | retry SAME provider after backoff.delay(tries) if       |
| SERVER_ERROR /   |                      |   tries < max_attempts_per_provider AND budget allows   |
| TIMEOUT          |                      |   AND it fits the deadline; otherwise fail over         |

Cooldowns are per provider and shared by all calls (other calls must avoid a
rate-limited provider too). When every provider in the ladder is unusable,
you may wait for a *short* (<= 5 s) rate-limit cooldown if it fits the deadline.
"""

from __future__ import annotations

import random
from typing import Any

from gameday_lab.breaker import BreakerState, Permit, SlidingWindowBreaker
from gameday_lab.errors import ErrorKind, classify, counts_toward_breaker
from gameday_lab.retry import FullJitterBackoff, RetryBudget
from gameday_lab.sim.contracts import (
    Action,
    Attempt,
    BaseClient,
    CallContext,
    GiveUp,
    ProviderError,
    ProviderInfo,
    Send,
)

RATE_LIMIT_WAIT_MAX_S = 5.0  # only wait for short (rate-limit) cooldowns, never for quota


class ResilientClient(BaseClient):
    name = "resilient"

    def __init__(
        self,
        providers: dict[str, ProviderInfo],
        fallback_order: list[str] | tuple[str, ...],
        settings: dict[str, Any],
        seed: int = 0,
    ) -> None:
        """PROVIDED: reads the `client:` block of configs/gameday.yaml."""
        self.providers = providers
        self.order = list(fallback_order)
        self.timeout_s = float(settings.get("attempt_timeout_s", 8.0))
        self.max_attempts_per_provider = int(settings.get("max_attempts_per_provider", 2))
        self.min_time_left_s = float(settings.get("min_time_left_s", 1.0))
        self.quota_cooldown_s = float(settings.get("quota_cooldown_s", 300.0))
        self.backoff = FullJitterBackoff(
            float(settings.get("backoff_base_s", 0.25)),
            float(settings.get("backoff_cap_s", 4.0)),
            random.Random(seed),
        )
        self.budget = RetryBudget(
            float(settings.get("retry_budget_ratio", 0.1)),
            float(settings.get("retry_budget_min_per_s", 0.5)),
            float(settings.get("retry_budget_max_tokens", 20.0)),
        )
        breaker_cfg = dict(settings.get("breaker", {}))
        self.breakers = {name: SlidingWindowBreaker(name, **breaker_cfg) for name in providers}
        self.cooldown_until: dict[str, float] = {name: 0.0 for name in providers}

    # ------------------------------------------------------------------ provided helper
    def _send(self, call: CallContext, provider: str, now: float, delay: float) -> Action | None:
        """PROVIDED. Build a Send for ``provider`` (after ``delay``), or None if its breaker refuses.

        Takes a breaker permit (carried in ``tag``), and caps the attempt timeout
        so it never runs past the call's deadline. Returns GiveUp("deadline") if
        there is not enough time left for a meaningful attempt.
        """
        permit = self.breakers[provider].allow(now)
        if permit is None:
            return None
        timeout = min(self.timeout_s, call.deadline - (now + delay))
        if timeout < self.min_time_left_s:
            self.breakers[provider].release(permit, now)
            return GiveUp("deadline")
        return Send(provider, timeout_s=timeout, delay_s=delay, tag=permit)

    # ------------------------------------------------------------------ TODO
    def ladder(self, task: str) -> list[str]:
        """TODO(student): ``self.order`` filtered by capability —
        a "tool" call may only use providers with ``supports_tools``."""
        needs_tools = task == "tool"
        return [p for p in self.order if not needs_tools or self.providers[p].supports_tools]

    def _route(self, call: CallContext, now: float, delay: float = 0.0) -> Action:
        """TODO(student): pick the provider for the next attempt.

        Walk the ladder from call.state["idx"]:
          * skip a provider still in cooldown at send time (now + delay)
          * otherwise try self._send(...); a non-None result is your answer
          * when skipping, move idx forward, reset tries, and set delay = 0
            (a failover goes out immediately)
        If the ladder is exhausted: optionally wait for the earliest *short*
        rate-limit cooldown (<= RATE_LIMIT_WAIT_MAX_S, breaker not OPEN, fits the
        deadline), else GiveUp("no_provider_available").
        """
        ladder: list[str] = call.state["ladder"]
        while call.state["idx"] < len(ladder):
            provider = ladder[call.state["idx"]]
            if self.cooldown_until[provider] <= now + delay:
                action = self._send(call, provider, now, delay)
                if action is not None:
                    if isinstance(action, Send):
                        call.state["tries"] += 1
                    return action
            call.state["idx"] += 1
            call.state["tries"] = 0
            delay = 0.0
        return self._wait_for_cooldown(call, now)

    def _wait_for_cooldown(self, call: CallContext, now: float) -> Action:
        """Every provider is unusable: wait for the earliest short rate-limit cooldown, once per call."""
        if call.state.get("waited"):
            return GiveUp("no_provider_available")
        ladder: list[str] = call.state["ladder"]
        best: tuple[float, int] | None = None
        for i, provider in enumerate(ladder):
            wait = self.cooldown_until[provider] - now
            if not 0.0 < wait <= RATE_LIMIT_WAIT_MAX_S:
                continue
            if self.breakers[provider].state is BreakerState.OPEN:
                continue
            if now + wait + self.min_time_left_s > call.deadline:
                continue
            if best is None or wait < best[0]:
                best = (wait, i)
        if best is None:
            return GiveUp("no_provider_available")
        wait, i = best
        call.state["waited"] = True
        call.state["idx"] = i
        call.state["tries"] = 0
        # jitter on top of the cooldown so waiting calls do not all return in the same instant
        delay = wait + self.backoff.rng.uniform(0.0, self.backoff.base_s)
        action = self._send(call, ladder[i], now, delay)
        if action is None:
            return GiveUp("no_provider_available")
        if isinstance(action, Send):
            call.state["tries"] = 1
        return action

    def start(self, call: CallContext, now: float) -> Action:
        """TODO(student): record the request in the retry budget, initialise
        call.state (ladder, idx=0, tries=0) and route."""
        self.budget.record_request(now)
        call.state.update(ladder=self.ladder(call.task), idx=0, tries=0)
        return self._route(call, now)

    def on_success(self, attempt: Attempt, now: float, latency_s: float) -> None:
        """TODO(student): report success + latency to the provider's breaker (attempt.tag is the Permit)."""
        permit = attempt.tag
        if isinstance(permit, Permit):
            self.breakers[attempt.provider].on_success(permit, now, latency_s)

    def on_error(self, attempt: Attempt, err: ProviderError, now: float) -> Action:
        """TODO(student): implement the decision table in the module docstring."""
        call = attempt.call
        provider = attempt.provider
        kind = classify(err)
        breaker = self.breakers[provider]
        permit = attempt.tag
        if isinstance(permit, Permit):
            if counts_toward_breaker(kind):
                breaker.on_failure(permit, now)
            else:
                breaker.release(permit, now)

        if kind is ErrorKind.CLIENT_ERROR:
            return GiveUp("client_error")

        if kind is ErrorKind.QUOTA_EXHAUSTED:
            self.cooldown_until[provider] = max(self.cooldown_until[provider], now + self.quota_cooldown_s)
            return self._fail_over(call, now)

        if kind is ErrorKind.RATE_LIMITED:
            retry_after = err.retry_after if err.retry_after is not None else 1.0
            self.cooldown_until[provider] = max(self.cooldown_until[provider], now + retry_after)
            return self._fail_over(call, now)

        # OVERLOADED / SERVER_ERROR / TIMEOUT: transient — one more go on the same provider?
        tries = call.state["tries"]
        if tries < self.max_attempts_per_provider and breaker.state is not BreakerState.OPEN:
            delay = self.backoff.delay(tries, err.retry_after)
            if now + delay + self.min_time_left_s <= call.deadline and self.budget.try_acquire_retry(now):
                action = self._send(call, provider, now, delay)
                if isinstance(action, Send):
                    call.state["tries"] += 1
                    return action
                if isinstance(action, GiveUp):
                    return action
        return self._fail_over(call, now)

    def _fail_over(self, call: CallContext, now: float) -> Action:
        call.state["idx"] += 1
        call.state["tries"] = 0
        return self._route(call, now)

    def on_cancel(self, call: CallContext, tag: Any, now: float) -> None:
        """TODO(student): a delayed attempt was dropped (deadline) — release its permit."""
        if isinstance(tag, Permit):
            self.breakers[tag.breaker].release(tag, now)
