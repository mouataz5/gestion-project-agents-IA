import time
import uuid
from collections.abc import Iterator

import pytest
import redis

from app.crawlers.compliance import RateLimiter, RateLimitTimeoutError

pytestmark = [pytest.mark.feature("compliance"), pytest.mark.integration]


@pytest.fixture
def limiter(redis_url: str) -> Iterator[RateLimiter]:
    client = redis.Redis.from_url(redis_url)
    yield RateLimiter(client, prefix=f"test-ratelimit-{uuid.uuid4().hex}")
    client.close()


def test_a_burst_is_allowed_then_callers_must_wait(limiter: RateLimiter) -> None:
    assert limiter.try_acquire("jobs.example", rate_per_minute=60, burst=2) == 0
    assert limiter.try_acquire("jobs.example", rate_per_minute=60, burst=2) == 0

    wait = limiter.try_acquire("jobs.example", rate_per_minute=60, burst=2)

    assert 0.5 < wait <= 1.0


def test_limits_are_kept_per_domain(limiter: RateLimiter) -> None:
    assert limiter.try_acquire("a.example", rate_per_minute=60, burst=1) == 0
    assert limiter.try_acquire("a.example", rate_per_minute=60, burst=1) > 0
    assert limiter.try_acquire("b.example", rate_per_minute=60, burst=1) == 0


def test_tokens_refill_at_the_configured_rate(limiter: RateLimiter) -> None:
    assert limiter.try_acquire("jobs.example", rate_per_minute=600, burst=1) == 0
    assert limiter.try_acquire("jobs.example", rate_per_minute=600, burst=1) > 0

    time.sleep(0.15)

    assert limiter.try_acquire("jobs.example", rate_per_minute=600, burst=1) == 0


def test_acquire_waits_for_a_token_or_times_out(limiter: RateLimiter) -> None:
    started = time.monotonic()
    limiter.acquire("jobs.example", rate_per_minute=600, burst=1, timeout=2)
    limiter.acquire("jobs.example", rate_per_minute=600, burst=1, timeout=2)
    assert time.monotonic() - started >= 0.05

    limiter.acquire("slow.example", rate_per_minute=1, burst=1, timeout=1)
    with pytest.raises(RateLimitTimeoutError):
        limiter.acquire("slow.example", rate_per_minute=1, burst=1, timeout=0.2)
