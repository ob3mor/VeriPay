"""In-memory request throttling for the public auth endpoints.

Phase 1 design, deliberate and documented:

- **Per-process state.** The API deploys as a single instance on the free-tier
  profiles; a multi-instance deployment needs a shared store (Redis/DB) — this
  module is the seam to swap. State is lost on restart, which for throttling
  means an attacker also gets a fresh budget on restart (bounded by the small
  windows below).
- **Sliding window** (deque of monotonic timestamps) instead of fixed buckets:
  exact enough for these limits, and deterministic under fast test execution
  (no window-boundary roll-over flakes).
- **Login lockout is keyed by (client IP, normalized email).** A single source
  cannot brute-force one account; a distributed attacker also cannot mass-lock
  victim accounts by spraying failures from many IPs.
- **The client IP is the socket peer** — deliberately not ``X-Forwarded-For``,
  which is client-controlled unless every proxy in front is trusted. Wiring a
  trusted-proxy list is a deployment concern and must be done together with
  moving this state to a shared store.

A helper performs a synchronous sweep on access, so stale keys do not
accumulate and no background job is needed.
"""

import time
from collections import deque
from collections.abc import Callable
from threading import Lock

from app.core.config import get_settings


def _prune(events: deque[float], window_seconds: float, now: float) -> None:
    """Drop timestamps that fell out of the sliding window."""
    cutoff = now - window_seconds
    while events and events[0] <= cutoff:
        events.popleft()


class _WindowRegistry:
    """Keyed sliding-window counters with an injected clock (test seam)."""

    def __init__(
        self, *, window_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.window_seconds = window_seconds
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = Lock()

    def _prune_key(self, key: str, now: float) -> deque[float] | None:
        events = self._events.get(key)
        if events is None:
            return None
        _prune(events, self.window_seconds, now)
        if not events:
            self._events.pop(key, None)
            return None
        return events

    def reset(self) -> None:
        """Forget all state (test isolation; also usable by admin tooling)."""
        with self._lock:
            self._events.clear()


class SlidingWindowRateLimiter(_WindowRegistry):
    """Allows at most ``max_events`` events per ``window_seconds`` per key."""

    def __init__(
        self,
        *,
        max_events: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(window_seconds=window_seconds, clock=clock)
        self.max_events = max_events

    def check(self, key: str) -> bool:
        """Count one event for ``key``; return True when under the limit."""
        now = self._clock()
        with self._lock:
            events = self._prune_key(key, now)
            if events is None:
                events = self._events.setdefault(key, deque())
            if len(events) >= self.max_events:
                return False
            events.append(now)
            return True


class FailureLockout(_WindowRegistry):
    """Locks a key once ``max_failures`` failures accumulate in the window."""

    def __init__(
        self,
        *,
        max_failures: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(window_seconds=window_seconds, clock=clock)
        self.max_failures = max_failures

    def record_failure(self, key: str) -> None:
        now = self._clock()
        with self._lock:
            events = self._prune_key(key, now)
            if events is None:
                events = self._events.setdefault(key, deque())
            events.append(now)

    def is_locked(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            events = self._prune_key(key, now)
            return events is not None and len(events) >= self.max_failures

    def clear(self, key: str) -> None:
        """Reset one key's failure history (e.g. after a successful login)."""
        with self._lock:
            self._events.pop(key, None)


def _lockout_window_seconds() -> float:
    return float(get_settings().login_lockout_window_seconds)


# Process-wide singletons used by the auth routes (see module docstring for
# the single-instance assumption).
login_rate_limiter = SlidingWindowRateLimiter(
    max_events=get_settings().rate_limit_login_per_minute, window_seconds=60.0
)
register_rate_limiter = SlidingWindowRateLimiter(
    max_events=get_settings().rate_limit_register_per_minute, window_seconds=60.0
)
login_lockout = FailureLockout(
    max_failures=get_settings().login_lockout_max_failures,
    window_seconds=_lockout_window_seconds(),
)


def reset_all() -> None:
    """Clear every throttle/lockout registry (test isolation)."""
    login_rate_limiter.reset()
    register_rate_limiter.reset()
    login_lockout.reset()
