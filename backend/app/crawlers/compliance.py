"""Compliance building blocks for sources that access websites (wired into fetchers in Phase 10).

* ``RobotsPolicy`` follows RFC 9309: a parsed robots.txt is obeyed for our user agent; a 4xx
  answer means "no robots.txt" (crawling allowed); 429, 5xx and network errors mean
  "unreachable", so everything is disallowed. Results are cached per origin.
* ``RateLimiter`` is a per-domain token bucket kept in Redis (atomic Lua script, Redis clock),
  shared by every worker process.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import redis

from app.core.clock import utcnow


@dataclass(frozen=True)
class RobotsResponse:
    status: int
    text: str


@dataclass(frozen=True)
class _Rules:
    parser: RobotFileParser | None
    allow_all: bool
    expires_at: datetime


class RobotsPolicy:
    def __init__(
        self,
        fetch: Callable[[str], RobotsResponse],
        *,
        user_agent: str,
        ttl: timedelta = timedelta(hours=24),
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._fetch = fetch
        self._user_agent = user_agent
        self._ttl = ttl
        self._clock = clock
        self._cache: dict[str, _Rules] = {}

    @staticmethod
    def _origin(url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme.lower()}://{parts.netloc.lower()}"

    def _rules(self, url: str) -> _Rules:
        origin = self._origin(url)
        now = self._clock()
        cached = self._cache.get(origin)
        if cached is not None and cached.expires_at > now:
            return cached
        expires_at = now + self._ttl
        try:
            response = self._fetch(f"{origin}/robots.txt")
        except Exception:  # unreachable: assume complete disallow (RFC 9309 §2.3.1.4)
            rules = _Rules(parser=None, allow_all=False, expires_at=expires_at)
        else:
            if 200 <= response.status < 300:
                parser = RobotFileParser()
                parser.parse(response.text.splitlines())
                rules = _Rules(parser=parser, allow_all=False, expires_at=expires_at)
            elif 400 <= response.status < 500 and response.status != 429:
                rules = _Rules(parser=None, allow_all=True, expires_at=expires_at)
            else:
                rules = _Rules(parser=None, allow_all=False, expires_at=expires_at)
        self._cache[origin] = rules
        return rules

    def allowed(self, url: str) -> bool:
        rules = self._rules(url)
        if rules.parser is None:
            return rules.allow_all
        return rules.parser.can_fetch(self._user_agent, url)

    def crawl_delay(self, url: str) -> float | None:
        rules = self._rules(url)
        if rules.parser is None:
            return None
        delay = rules.parser.crawl_delay(self._user_agent)
        return float(delay) if delay is not None else None


class RateLimitTimeoutError(TimeoutError):
    pass


# Token bucket: refill at `rate` tokens/s up to `capacity`; take one token if available,
# otherwise return how long to wait. Uses the Redis clock so every worker agrees.
_BUCKET_SCRIPT = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil then tokens = capacity end
if ts == nil then ts = now end
tokens = math.min(capacity, tokens + math.max(0, now - ts) * rate)
local wait = 0
if tokens >= 1 then
  tokens = tokens - 1
else
  wait = (1 - tokens) / rate
end
redis.call('HSET', key, 'tokens', tostring(tokens), 'ts', tostring(now))
redis.call('EXPIRE', key, math.ceil(capacity / rate) + 60)
return tostring(wait)
"""


class RateLimiter:
    def __init__(self, client: redis.Redis, *, prefix: str = "ratelimit") -> None:
        self._client = client
        self._prefix = prefix
        self._script = client.register_script(_BUCKET_SCRIPT)

    def try_acquire(self, domain: str, *, rate_per_minute: int, burst: int = 1) -> float:
        """Take a token for ``domain``: 0.0 when granted, else the seconds to wait."""
        rate = rate_per_minute / 60.0
        key = f"{self._prefix}:{domain.lower()}"
        wait = float(self._script(keys=[key], args=[rate, max(1, burst)]))
        return 0.0 if wait <= 0 else wait

    def acquire(
        self,
        domain: str,
        *,
        rate_per_minute: int,
        burst: int = 1,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Block until a token is granted, or raise ``RateLimitTimeoutError``."""
        deadline = time.monotonic() + timeout
        while True:
            wait = self.try_acquire(domain, rate_per_minute=rate_per_minute, burst=burst)
            if wait == 0:
                return
            if time.monotonic() + wait > deadline:
                raise RateLimitTimeoutError(
                    f"Rate limit for {domain}: next request allowed in {math.ceil(wait)} s"
                )
            sleep(wait)
