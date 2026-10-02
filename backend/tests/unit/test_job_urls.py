import pytest

from app.jobs.urls import UnsafeUrlError, ats_type_from_url, canonical_url, validate_public_url

pytestmark = pytest.mark.feature("job-normalization")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # tracking parameters, fragment, host case, default port, www
        (
            "HTTPS://Nova-AI.example/careers/jobs/1001?gh_src=abc&utm_source=linkedin#apply",
            "https://nova-ai.example/careers/jobs/1001",
        ),
        (
            "http://www.example.com:80/careers/job/42/?b=2&a=1&utm_campaign=x&fbclid=y",
            "https://example.com/careers/job/42?a=1&b=2",
        ),
        ("https://example.com:443//jobs//7/", "https://example.com/jobs/7"),
        ("https://example.com/", "https://example.com/"),
        # job identifiers in the query string are kept
        (
            "https://acme.example/careers?gh_jid=4567&gh_src=x",
            "https://acme.example/careers?gh_jid=4567",
        ),
        # ATS apply pages are the same job as the posting
        (
            "https://jobs.lever.co/acme/1111-2222/apply?lever-source=LinkedIn&lever-origin=x",
            "https://jobs.lever.co/acme/1111-2222",
        ),
        (
            "https://boards.greenhouse.io/acme/jobs/123?gh_src=abc",
            "https://boards.greenhouse.io/acme/jobs/123",
        ),
        ("https://jobs.ashbyhq.com/acme/9f8e/application", "https://jobs.ashbyhq.com/acme/9f8e"),
        # LinkedIn job views: e-mail (comm) links, slugs, country subdomains, tracking
        (
            "https://www.linkedin.com/comm/jobs/view/3912345678/?refId=abc&trackingId=def",
            "https://linkedin.com/jobs/view/3912345678",
        ),
        (
            "https://fr.linkedin.com/jobs/view/senior-ai-engineer-at-nova-ai-3912345678?trk=public",
            "https://linkedin.com/jobs/view/3912345678",
        ),
        # Indeed: only the job key matters
        (
            "https://fr.indeed.com/rc/clk?jk=abc123&from=vj&tk=1",
            "https://fr.indeed.com/viewjob?jk=abc123",
        ),
        ("https://www.indeed.com/viewjob?jk=abc123&vjs=3", "https://indeed.com/viewjob?jk=abc123"),
    ],
)
def test_canonical_url(raw: str, expected: str) -> None:
    assert canonical_url(raw) == expected


def test_canonical_url_is_idempotent() -> None:
    url = "http://WWW.Example.com/jobs/1/?utm_source=x&id=5#top"
    assert canonical_url(canonical_url(url)) == canonical_url(url)


@pytest.mark.parametrize(
    ("url", "ats_type"),
    [
        ("https://boards.greenhouse.io/acme/jobs/1", "GREENHOUSE"),
        ("https://job-boards.greenhouse.io/acme/jobs/1", "GREENHOUSE"),
        ("https://acme.example/careers?gh_jid=1", "GREENHOUSE"),
        ("https://jobs.lever.co/acme/1", "LEVER"),
        ("https://jobs.ashbyhq.com/acme/1", "ASHBY"),
        ("https://jobs.smartrecruiters.com/Acme/1", "SMARTRECRUITERS"),
        ("https://acme.wd3.myworkdayjobs.com/en-US/careers/job/x", "WORKDAY"),
        ("https://www.linkedin.com/jobs/view/1", "LINKEDIN"),
        ("https://fr.indeed.com/viewjob?jk=1", "INDEED"),
        ("https://acme.example/careers/1", "GENERIC"),
    ],
)
def test_ats_type_is_detected_from_the_url(url: str, ats_type: str) -> None:
    assert ats_type_from_url(url) == ats_type


@pytest.mark.parametrize(
    "url",
    [
        "https://boards.greenhouse.io/acme/jobs/123",
        "http://example.com/job?id=1",
        "https://www.linkedin.com/jobs/view/3912345678",
        "https://8.8.8.8/careers",
    ],
)
def test_public_urls_are_accepted(url: str) -> None:
    assert validate_public_url(url) == url


@pytest.mark.feature("job-import")
@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a url",
        "ftp://example.com/job",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://user:secret@example.com/job",
        "http://localhost:8000/admin",
        "http://api.localhost/x",
        "http://127.0.0.1/x",
        "http://127.1/x",
        "http://2130706433/x",
        "http://0x7f000001/x",
        "http://[::1]/x",
        "http://10.0.0.5/x",
        "http://172.16.0.1/x",
        "http://192.168.1.1/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0/x",
        "http://100.64.0.1/x",
        "http://[fd00::1]/x",
        "http://intranet/x",
        "http://printer.local/x",
        "http://db.internal/x",
        "https://example.com:22/x",
        "https://example.com/" + "a" * 2100,
    ],
)
def test_private_and_unsafe_urls_are_rejected(url: str) -> None:
    with pytest.raises(UnsafeUrlError) as excinfo:
        validate_public_url(url)
    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "unsafe_url"
