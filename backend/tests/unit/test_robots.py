from datetime import UTC, datetime, timedelta

import pytest

from app.crawlers.compliance import RobotsPolicy, RobotsResponse

pytestmark = pytest.mark.feature("compliance")

UA = "JobAgent/0.1 (self-hosted personal job search)"
ROBOTS = """
User-agent: *
Disallow: /private
Crawl-delay: 2

User-agent: JobAgent
Disallow: /no-agents
"""


class FakeFetch:
    def __init__(self, response: RobotsResponse | Exception) -> None:
        self.response = response
        self.calls: list[str] = []

    def __call__(self, url: str) -> RobotsResponse:
        self.calls.append(url)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def test_disallowed_paths_are_respected_for_our_user_agent() -> None:
    fetch = FakeFetch(RobotsResponse(status=200, text=ROBOTS))
    policy = RobotsPolicy(fetch, user_agent=UA)

    assert not policy.allowed("https://jobs.example/no-agents/42")
    assert policy.allowed("https://jobs.example/careers/42")
    # The "*" group does not apply when a group names our agent.
    assert policy.allowed("https://jobs.example/private/1")
    assert fetch.calls == ["https://jobs.example/robots.txt"]


def test_generic_rules_apply_to_other_agents() -> None:
    policy = RobotsPolicy(FakeFetch(RobotsResponse(status=200, text=ROBOTS)), user_agent="OtherBot")

    assert not policy.allowed("https://jobs.example/private/1")
    assert policy.crawl_delay("https://jobs.example/") == 2.0


@pytest.mark.parametrize("status", [404, 410, 401, 403])
def test_missing_robots_files_allow_crawling(status: int) -> None:
    policy = RobotsPolicy(FakeFetch(RobotsResponse(status=status, text="")), user_agent=UA)

    assert policy.allowed("https://jobs.example/careers/1")


@pytest.mark.parametrize("status", [429, 500, 503])
def test_unreachable_robots_files_disallow_everything(status: int) -> None:
    policy = RobotsPolicy(FakeFetch(RobotsResponse(status=status, text="")), user_agent=UA)

    assert not policy.allowed("https://jobs.example/careers/1")


def test_network_errors_disallow_everything() -> None:
    policy = RobotsPolicy(FakeFetch(OSError("connection refused")), user_agent=UA)

    assert not policy.allowed("https://jobs.example/careers/1")


def test_robots_files_are_cached_per_origin_until_they_expire() -> None:
    fetch = FakeFetch(RobotsResponse(status=200, text=ROBOTS))
    clock = Clock()
    policy = RobotsPolicy(fetch, user_agent=UA, ttl=timedelta(hours=24), clock=clock)

    policy.allowed("https://jobs.example/a")
    policy.allowed("https://jobs.example/b")
    policy.allowed("https://other.example/a")
    clock.now += timedelta(hours=25)
    policy.allowed("https://jobs.example/c")

    assert fetch.calls == [
        "https://jobs.example/robots.txt",
        "https://other.example/robots.txt",
        "https://jobs.example/robots.txt",
    ]
