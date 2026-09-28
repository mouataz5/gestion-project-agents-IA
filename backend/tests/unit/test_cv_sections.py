import pytest

from app.cv.readers import strip_bullet
from app.cv.sections import SectionKind, match_section

pytestmark = pytest.mark.feature("cv-parsing")


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("EXPERIENCE", SectionKind.EXPERIENCE),
        ("Professional Experience:", SectionKind.EXPERIENCE),
        ("Work History", SectionKind.EXPERIENCE),
        ("Expérience professionnelle", SectionKind.EXPERIENCE),
        ("EXPÉRIENCES PROFESSIONNELLES", SectionKind.EXPERIENCE),
        ("Education", SectionKind.EDUCATION),
        ("Formation", SectionKind.EDUCATION),
        ("Projects", SectionKind.PROJECTS),
        ("Projets personnels", SectionKind.PROJECTS),
        ("Technical Skills", SectionKind.SKILLS),
        ("Compétences techniques", SectionKind.SKILLS),
        ("Summary", SectionKind.SUMMARY),
        ("Profil", SectionKind.SUMMARY),
        ("Certifications", SectionKind.CERTIFICATIONS),
        ("Languages", SectionKind.LANGUAGES),
        ("Langues", SectionKind.LANGUAGES),
        ("Interests", SectionKind.OTHER),
        ("Centres d'intérêt", SectionKind.OTHER),
        ("Publications", SectionKind.OTHER),
    ],
)
def test_known_headings_are_recognised(text: str, kind: SectionKind) -> None:
    assert match_section(text) is kind


@pytest.mark.parametrize(
    "text",
    [
        "Senior AI Engineer — Acme Analytics",
        "I gained a lot of experience building production systems.",
        "Python, SQL",
        "",
    ],
)
def test_ordinary_lines_are_not_headings(text: str) -> None:
    assert match_section(text) is None


@pytest.mark.parametrize(
    ("raw", "is_bullet", "text"),
    [
        ("• Built RAG pipelines", True, "Built RAG pipelines"),
        ("- Built RAG pipelines", True, "Built RAG pipelines"),
        ("– Built RAG pipelines", True, "Built RAG pipelines"),
        ("(cid:127) Built RAG pipelines", True, "Built RAG pipelines"),
        ("▪ Built RAG pipelines", True, "Built RAG pipelines"),
        ("Built RAG pipelines", False, "Built RAG pipelines"),
        ("-2% churn", False, "-2% churn"),
    ],
)
def test_bullet_markers_are_stripped(raw: str, is_bullet: bool, text: str) -> None:
    assert strip_bullet(raw) == (is_bullet, text)
