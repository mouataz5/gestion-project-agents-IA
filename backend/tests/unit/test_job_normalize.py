import pytest

from app.jobs.countries import country_code, country_from_location
from app.jobs.email_links import extract_job_links
from app.jobs.normalize import (
    detect_remote_status,
    html_to_text,
    infer_seniority,
    parse_employment_type,
)
from app.jobs.relevance import title_matches
from app.jobs.types import EmploymentType, RemoteStatus, Seniority

pytestmark = pytest.mark.feature("job-normalization")


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        (("Remote",), RemoteStatus.REMOTE),
        (("Paris, France", "100% remote"), RemoteStatus.REMOTE),
        (("Télétravail complet",), RemoteStatus.REMOTE),
        (("Hybrid - 2 days in office",), RemoteStatus.HYBRID),
        (("Remote-friendly (hybrid)",), RemoteStatus.HYBRID),
        (("Hybride",), RemoteStatus.HYBRID),
        (("On-site",), RemoteStatus.ONSITE),
        (("Sur site",), RemoteStatus.ONSITE),
        (("Paris, France",), RemoteStatus.UNKNOWN),
        ((None,), RemoteStatus.UNKNOWN),
    ],
)
def test_remote_status(texts: tuple[str | None, ...], expected: RemoteStatus) -> None:
    assert detect_remote_status(*texts) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Full-time", EmploymentType.FULL_TIME),
        ("Permanent", EmploymentType.FULL_TIME),
        ("CDI", EmploymentType.FULL_TIME),
        ("Part time", EmploymentType.PART_TIME),
        ("Contract", EmploymentType.CONTRACT),
        ("Freelance", EmploymentType.CONTRACT),
        ("Fixed-term", EmploymentType.TEMPORARY),
        ("CDD", EmploymentType.TEMPORARY),
        ("Internship", EmploymentType.INTERNSHIP),
        ("Stage", EmploymentType.INTERNSHIP),
        ("Alternance", EmploymentType.INTERNSHIP),
        (None, EmploymentType.UNKNOWN),
        ("Whatever", EmploymentType.UNKNOWN),
    ],
)
def test_employment_type(value: str | None, expected: EmploymentType) -> None:
    assert parse_employment_type(value) is expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Senior AI Engineer", Seniority.SENIOR),
        ("Sr. Machine Learning Engineer", Seniority.SENIOR),
        ("Junior Data Scientist", Seniority.JUNIOR),
        ("Graduate ML Engineer", Seniority.JUNIOR),
        ("AI Engineer Intern", Seniority.INTERN),
        ("Stagiaire Data Science", Seniority.INTERN),
        ("Staff AI Engineer", Seniority.LEAD),
        ("Lead MLOps Engineer", Seniority.LEAD),
        ("Principal Applied Scientist", Seniority.PRINCIPAL),
        ("Head of AI", Seniority.PRINCIPAL),
        ("Mid-level NLP Engineer", Seniority.MID),
        ("AI Engineer", Seniority.UNKNOWN),
    ],
)
def test_seniority_from_title(title: str, expected: Seniority) -> None:
    assert infer_seniority(title) is expected


def test_html_descriptions_become_plain_text() -> None:
    html = (
        "<h2>About the role</h2><p>Build <b>RAG</b> systems &amp; agents.</p>"
        "<ul><li>Python</li><li>LangGraph</li></ul>"
        "<script>alert('x')</script><style>p{color:red}</style><p>Apply&nbsp;now</p>"
    )

    assert html_to_text(html) == (
        "About the role\nBuild RAG systems & agents.\n• Python\n• LangGraph\nApply now"
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("FR", "FR"),
        ("fr", "FR"),
        ("France", "FR"),
        ("Allemagne", "DE"),
        ("The Netherlands", "NL"),
        ("Pays-Bas", "NL"),
        ("UK", "GB"),
        ("United Arab Emirates", "AE"),
        ("UAE", "AE"),
        ("USA", "US"),
        ("Tunisie", "TN"),
        ("Atlantis", None),
        (None, None),
    ],
)
def test_country_codes(value: str | None, expected: str | None) -> None:
    assert country_code(value) == expected


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("Paris, France", "FR"),
        ("Berlin, DE", "DE"),
        ("Munich", "DE"),
        ("Amsterdam, Netherlands", "NL"),
        ("Dubai, UAE", "AE"),
        ("San Francisco, CA, USA", "US"),
        ("Remote - Europe", None),
        ("Remote", None),
        ("", None),
    ],
)
def test_country_from_location(location: str, expected: str | None) -> None:
    assert country_from_location(location) == expected


@pytest.mark.parametrize(
    "title",
    [
        "Senior AI Engineer",
        "Machine Learning Engineer",
        "ML Platform Engineer",
        "GenAI Engineer",
        "LLM Engineer (RAG)",
        "Ingénieur IA",
        "Data Scientist, Time Series",
        "Computer Vision Engineer",
        "MLOps Engineer",
        "Applied Scientist, NLP",
        "Agentic AI Engineer",
        "Deep Learning Researcher",
    ],
)
def test_ai_ml_titles_are_relevant(title: str) -> None:
    assert title_matches(title)


@pytest.mark.parametrize(
    "title",
    ["Account Executive", "Frontend Developer", "Email Marketing Manager", "Office Manager"],
)
def test_other_titles_are_not_relevant(title: str) -> None:
    assert not title_matches(title)


def test_candidate_target_roles_extend_the_vocabulary() -> None:
    assert not title_matches("Quantitative Researcher")
    assert title_matches("Quantitative Researcher", roles=["Quantitative Researcher"])


@pytest.mark.feature("job-import")
def test_job_links_are_extracted_from_alert_emails() -> None:
    email = """
    <html><body>
      <a href="https://www.linkedin.com/comm/jobs/view/3912345678/?trackingId=a&amp;refId=b">AI Engineer</a>
      <a href="https://www.linkedin.com/comm/jobs/view/3912345678/?trackingId=other">same job</a>
      <a href="https://www.linkedin.com/comm/jobs/view/3999999999/">LLM Engineer</a>
      <a href="https://www.linkedin.com/comm/jobs/alerts?unsubscribe=1">Unsubscribe</a>
      <a href="https://www.linkedin.com/comm/psettings/email">Settings</a>
      Also: https://fr.indeed.com/rc/clk?jk=abc123&from=ja and https://jobs.lever.co/acme/11-22
    </body></html>
    """

    assert extract_job_links(email) == [
        "https://linkedin.com/jobs/view/3912345678",
        "https://linkedin.com/jobs/view/3999999999",
        "https://fr.indeed.com/viewjob?jk=abc123",
        "https://jobs.lever.co/acme/11-22",
    ]


@pytest.mark.feature("job-import")
def test_link_extraction_is_bounded() -> None:
    text = " ".join(f"https://jobs.lever.co/acme/{i}" for i in range(80))

    assert len(extract_job_links(text, limit=50)) == 50
    assert extract_job_links("no links here") == []
