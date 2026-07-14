"""Unit tests for the per-key token bucket. Fake clock — no sleeping."""

import pytest

import rate_limit
from rate_limit import RateLimiter


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


def test_burst_is_allowed_then_denied(clock):
    limiter = RateLimiter(per_minute=6, burst=3, clock=clock)
    assert all(limiter.check("ip").allowed for _ in range(3))
    denied = limiter.check("ip")
    assert not denied.allowed
    assert denied.retry_after_seconds == pytest.approx(10.0)  # 6/min = 1 per 10 s


def test_tokens_refill_at_the_sustained_rate(clock):
    limiter = RateLimiter(per_minute=6, burst=1, clock=clock)
    assert limiter.check("ip").allowed
    assert not limiter.check("ip").allowed
    clock.advance(10.0)  # exactly one token refilled
    assert limiter.check("ip").allowed
    assert not limiter.check("ip").allowed


def test_refill_never_exceeds_the_burst_capacity(clock):
    limiter = RateLimiter(per_minute=60, burst=2, clock=clock)
    clock.advance(3600.0)  # an hour idle must not bank 60 tokens
    assert limiter.check("ip").allowed
    assert limiter.check("ip").allowed
    assert not limiter.check("ip").allowed


def test_keys_are_independent(clock):
    limiter = RateLimiter(per_minute=6, burst=1, clock=clock)
    assert limiter.check("alice").allowed
    assert not limiter.check("alice").allowed
    assert limiter.check("bob").allowed, "another IP has its own bucket"


def test_retry_after_shrinks_as_time_passes(clock):
    limiter = RateLimiter(per_minute=6, burst=1, clock=clock)
    limiter.check("ip")
    first = limiter.check("ip").retry_after_seconds
    clock.advance(4.0)
    second = limiter.check("ip").retry_after_seconds
    assert second == pytest.approx(first - 4.0)


def test_memory_stays_bounded(clock, monkeypatch):
    monkeypatch.setattr(rate_limit, "_PRUNE_THRESHOLD", 4)
    limiter = RateLimiter(per_minute=60, burst=2, clock=clock)
    for i in range(10):
        limiter.check(f"ip-{i}")
        clock.advance(10.0)  # each bucket refills fully long before pruning
    assert len(limiter._buckets) <= 5


@pytest.mark.parametrize(
    "kwargs",
    [dict(per_minute=0, burst=3), dict(per_minute=-1, burst=3), dict(per_minute=6, burst=0)],
)
def test_invalid_configuration_raises(kwargs):
    with pytest.raises(ValueError):
        RateLimiter(**kwargs)
