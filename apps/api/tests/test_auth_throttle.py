"""Throttling of the public auth endpoints (core/ratelimit.py): a per-IP
sliding window on /auth/login and /auth/register, and a failed-login lockout
per (IP, email). Limits are configured per env in tests/conftest.py."""

from app.core.ratelimit import (
    FailureLockout,
    SlidingWindowRateLimiter,
    login_lockout,
    login_rate_limiter,
    register_rate_limiter,
)
from helpers import login, register


def test_register_is_rate_limited_per_ip(client):
    assert register(client).status_code == 201  # consumes the first slot
    remaining = register_rate_limiter.max_events - 1
    for _ in range(remaining):
        # Duplicate emails are 409s but still consume the per-IP budget.
        assert register(client).status_code == 409

    response = register(client, full_name="One Too Many")

    assert response.status_code == 429
    error = response.json()["error"]
    assert error["code"] == "rate_limited"
    assert error["request_id"]


def test_login_is_rate_limited_per_ip(client):
    # Distinct emails per probe: the per-(IP, email) lockout must NOT be what
    # trips here â€” this exercises the per-IP login window alone.
    for i in range(login_rate_limiter.max_events):
        probe = login(client, username=f"probe-{i}@nowhere.example", password="x")
        assert probe.status_code == 401

    response = login(client, username="final@nowhere.example", password="x")

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"


def test_repeated_failures_lock_the_account_for_that_ip(client):
    assert register(client).status_code == 201
    for _ in range(login_lockout.max_failures):
        assert login(client, password="definitely-wrong").status_code == 401

    # Even the CORRECT password is rejected while the lockout is active.
    locked = login(client)
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "rate_limited"


def test_successful_login_resets_failure_history(client):
    assert register(client).status_code == 201
    for _ in range(login_lockout.max_failures - 1):
        assert login(client, password="definitely-wrong").status_code == 401
    # A success clears the failure streak; a fresh streak stays under the
    # threshold, so the account is not locked for the legitimate user.
    assert login(client).status_code == 200
    assert login(client, password="definitely-wrong").status_code == 401
    assert login(client).status_code == 200


def test_lockout_is_per_email(client):
    assert register(client).status_code == 201
    for _ in range(login_lockout.max_failures):
        login(client, password="definitely-wrong")

    # A different email from the same IP is not locked by dana's failures.
    victim = login(client, username="other@nowhere.example", password="x-not-it")
    assert victim.status_code == 401  # plain bad-credentials, not 429


# ---------------------------------------------------------------------------
# Unit tests for the registry primitives (injected clock â€” no sleeping).
# ---------------------------------------------------------------------------

class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_sliding_window_allows_burst_then_refuses_then_recovers():
    clock = _FakeClock()
    limiter = SlidingWindowRateLimiter(max_events=2, window_seconds=60, clock=clock)

    assert limiter.check("k")
    assert limiter.check("k")
    assert not limiter.check("k")

    clock.now = 61.0  # both events aged out of the window
    assert limiter.check("k")


def test_lockout_records_fails_recovers_and_clears():
    clock = _FakeClock()
    lockout = FailureLockout(max_failures=3, window_seconds=900, clock=clock)

    for _ in range(3):
        lockout.record_failure("acct")
    assert lockout.is_locked("acct")
    assert not lockout.is_locked("other")

    clock.now = 901.0  # failures aged out
    assert not lockout.is_locked("acct")

    lockout.record_failure("acct2")
    lockout.clear("acct2")
    assert not lockout.is_locked("acct2")
