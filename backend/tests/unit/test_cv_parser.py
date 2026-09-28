import re
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from app.cv.errors import NoTextFoundError, TooManyPagesError, UnreadableFileError
from app.cv.files import CvFileKind
from app.cv.models import ParsedCV
from app.cv.parser import parse_cv

pytestmark = pytest.mark.feature("cv-parsing")

CvLines = list[tuple[str, str]]


def _ym(value: Any) -> tuple[int, int | None] | None:
    return None if value is None else (value.year, value.month)


def _strings(value: Any, *, skip: frozenset[str]) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in skip:
                yield from _strings(item, skip=skip)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item, skip=skip)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def assert_nothing_invented(parsed: ParsedCV, extracted_text: str) -> None:
    """Every value in the parsed structure must appear verbatim in the source text."""
    source = _normalize(extracted_text)
    skip = frozenset({"parser_version", "language", "warnings", "kind"})
    for value in _strings(parsed.model_dump(mode="json"), skip=skip):
        assert _normalize(value) in source, f"not in source: {value!r}"


def test_english_docx_is_parsed_into_a_structured_draft(
    cv_docx: Callable[[CvLines], bytes], sample_cv_en: CvLines
) -> None:
    parsed, text = parse_cv(cv_docx(sample_cv_en), CvFileKind.DOCX)

    assert parsed.language == "en"
    assert parsed.header_lines[0] == "Alex Example"
    assert parsed.contact.emails == ["alex.example@example.com"]
    assert parsed.contact.phones == ["+33 6 12 34 56 78"]
    assert parsed.contact.links == ["linkedin.com/in/alex-example"]
    assert parsed.summary == "AI engineer building LLM and RAG systems in production."

    first, second = parsed.experiences
    assert first.title == "Senior AI Engineer"
    assert first.employer == "Acme Analytics"
    assert first.location == "Paris, France"
    assert first.dates is not None
    assert _ym(first.dates.start) == (2022, 1)
    assert first.dates.end is None
    assert first.dates.is_current is True
    assert len(first.bullets) == 2
    assert second.title == "Machine Learning Engineer"
    assert second.employer == "Beta Labs"
    assert second.dates is not None
    assert _ym(second.dates.end) == (2021, 12)
    assert second.bullets[1] == "Reduced inference latency by 35%."

    (education,) = parsed.education
    assert education.degree == "MSc in Computer Science"
    assert education.institution == "Université de Tunis"
    assert education.dates is not None
    assert _ym(education.dates.start) == (2017, None)

    (project,) = parsed.projects
    assert project.name == "Job Agent"
    assert project.bullets == ["Multi-agent system orchestrating LLMs with MCP."]

    skills = {(skill.category, skill.name) for skill in parsed.skills}
    assert ("Languages", "Python") in skills
    assert ("ML", "LLMs") in skills
    assert ("Cloud", "GCP") in skills
    assert len(parsed.skills) == 8

    assert parsed.certifications == ["Azure AI Engineer Associate (2023)"]
    assert parsed.languages == ["Arabic (native)", "French (fluent)", "English (professional)"]
    assert [section.heading for section in parsed.other_sections] == ["Interests"]
    assert_nothing_invented(parsed, text)


def test_french_docx_is_parsed(cv_docx: Callable[[CvLines], bytes], sample_cv_fr: CvLines) -> None:
    parsed, text = parse_cv(cv_docx(sample_cv_fr), CvFileKind.DOCX)

    assert parsed.language == "fr"
    assert parsed.summary == "Ingénieur IA spécialisé en IA générative."
    first, second = parsed.experiences
    assert first.title == "Ingénieur IA"
    assert first.employer == "Société Démo"
    assert first.dates is not None
    assert first.dates.is_current is True
    assert _ym(first.dates.start) == (2021, 1)
    assert second.dates is not None
    assert (_ym(second.dates.start), _ym(second.dates.end)) == ((2019, 3), (2020, 12))
    assert parsed.education[0].institution == "ENSI"
    assert [skill.name for skill in parsed.skills] == ["Python", "PyTorch", "Docker"]
    assert parsed.languages == ["Arabe", "Français", "Anglais"]
    assert_nothing_invented(parsed, text)


def test_pdf_is_parsed(cv_pdf: Callable[..., bytes], sample_cv_en: CvLines) -> None:
    parsed, text = parse_cv(cv_pdf(sample_cv_en), CvFileKind.PDF)

    assert [e.title for e in parsed.experiences] == [
        "Senior AI Engineer",
        "Machine Learning Engineer",
    ]
    assert parsed.experiences[0].employer == "Acme Analytics"
    assert parsed.experiences[0].dates is not None
    assert parsed.experiences[0].dates.is_current is True
    assert len(parsed.experiences[0].bullets) == 2
    assert parsed.education[0].degree == "MSc in Computer Science"
    assert len(parsed.skills) == 8
    assert_nothing_invented(parsed, text)


def test_entries_without_dates_produce_warnings(cv_docx: Callable[[CvLines], bytes]) -> None:
    parsed, _ = parse_cv(
        cv_docx(
            [
                ("heading", "Experience"),
                ("bold", "Freelance Consultant — Self-employed"),
                ("bullet", "Delivered chatbot prototypes."),
            ]
        ),
        CvFileKind.DOCX,
    )

    assert parsed.experiences[0].dates is None
    assert any("Freelance Consultant" in warning for warning in parsed.warnings)


def test_documents_without_known_sections_are_flagged(
    cv_docx: Callable[[CvLines], bytes],
) -> None:
    parsed, _ = parse_cv(
        cv_docx([("text", "Just some text"), ("text", "More text")]), CvFileKind.DOCX
    )

    assert parsed.experiences == []
    assert parsed.header_lines == ["Just some text", "More text"]
    assert any("No known CV sections" in warning for warning in parsed.warnings)


def test_pdfs_with_too_many_pages_are_rejected(cv_pdf: Callable[..., bytes]) -> None:
    with pytest.raises(TooManyPagesError):
        parse_cv(cv_pdf([("text", "Alex Example")], pages=11), CvFileKind.PDF)


def test_pdfs_without_text_are_rejected(cv_pdf: Callable[..., bytes]) -> None:
    with pytest.raises(NoTextFoundError):
        parse_cv(cv_pdf([]), CvFileKind.PDF)


def test_corrupt_documents_are_rejected() -> None:
    with pytest.raises(UnreadableFileError):
        parse_cv(b"PK\x03\x04 definitely not a valid archive", CvFileKind.DOCX)


def test_common_entry_layouts_are_segmented(cv_docx: Callable[[CvLines], bytes]) -> None:
    parsed, text = parse_cv(
        cv_docx(
            [
                ("title", "Sam Sample"),
                ("caps", "WORK EXPERIENCE"),
                # title / company + location / dates on separate lines
                ("bold", "Data Scientist"),
                ("text", "Gamma Corp, Berlin, Germany"),
                ("text", "03/2021 – 12/2023"),
                ("bullet", "Built churn models."),
                # company first, then title
                ("bold", "Delta Inc."),
                ("text", "Research Intern"),
                ("text", "Jun 2020 - Aug 2020"),
                ("bullet", "Prototyped NLP pipelines."),
                # dates first
                ("text", "2018 – 2019"),
                ("bold", "Teaching Assistant"),
                ("text", "University of Tunis"),
                ("bullet", "Taught Python."),
                # everything on one line, description paragraph instead of bullets
                ("bold", "Freelance ML Engineer, Remote | 2017 – 2018"),
                ("text", "Delivered forecasting dashboards for small retailers using Python."),
                ("caps", "EDUCATION"),
                ("bold", "MSc Data Science, Université Paris-Saclay"),
                ("text", "2016 – 2018"),
                ("bold", "BSc Mathematics, Université de Sfax"),
                ("text", "2013 – 2016"),
            ]
        ),
        CvFileKind.DOCX,
    )

    summary = [
        (e.title, e.employer, e.location, e.dates.text if e.dates else None)
        for e in parsed.experiences
    ]
    assert summary == [
        ("Data Scientist", "Gamma Corp", "Berlin, Germany", "03/2021 – 12/2023"),
        ("Research Intern", "Delta Inc.", None, "Jun 2020 - Aug 2020"),
        ("Teaching Assistant", "University of Tunis", None, "2018 – 2019"),
        ("Freelance ML Engineer", None, "Remote", "2017 – 2018"),
    ]
    assert parsed.experiences[3].details == [
        "Delivered forecasting dashboards for small retailers using Python."
    ]
    assert [(e.degree, e.institution) for e in parsed.education] == [
        ("MSc Data Science", "Université Paris-Saclay"),
        ("BSc Mathematics", "Université de Sfax"),
    ]
    assert parsed.warnings == []
    assert_nothing_invented(parsed, text)


def test_skill_sub_labels_and_contact_sections(cv_docx: Callable[[CvLines], bytes]) -> None:
    parsed, text = parse_cv(
        cv_docx(
            [
                ("title", "Sam Sample"),
                ("caps", "SKILLS"),
                ("bold", "Programming Languages"),  # a label inside Skills, not a section
                ("text", "Python, R, SQL"),
                ("bold", "Tools"),
                ("text", "Docker / Kubernetes / Airflow"),
                ("caps", "CONTACT"),
                ("text", "sam@example.org"),
                ("text", "+49 151 2345 6789"),
                ("text", "github.com/samsample"),
            ]
        ),
        CvFileKind.DOCX,
    )

    assert [(s.category, s.name) for s in parsed.skills] == [
        ("Programming Languages", "Python"),
        ("Programming Languages", "R"),
        ("Programming Languages", "SQL"),
        ("Tools", "Docker"),
        ("Tools", "Kubernetes"),
        ("Tools", "Airflow"),
    ]
    assert parsed.contact.emails == ["sam@example.org"]
    assert parsed.contact.phones == ["+49 151 2345 6789"]
    assert parsed.contact.links == ["github.com/samsample"]
    assert_nothing_invented(parsed, text)


def test_inline_dates_and_bullet_lists(cv_docx: Callable[[CvLines], bytes]) -> None:
    parsed, text = parse_cv(
        cv_docx(
            [
                ("heading", "Education"),
                ("text", "Engineering degree in Computer Science, ENSI, 2014 – 2017"),
                ("text", "Preparatory classes, IPEIT, 2012 – 2014"),
                ("heading", "Projects"),
                ("bullet", "Chatbot: RAG assistant for internal docs using LangChain."),
                ("bullet", "Vision: defect detection with YOLO."),
                ("heading", "Experience"),
                ("text", "Acme, Paris — Jan 2021 – Present"),
                ("bold", "ML Engineer"),
                ("bullet", "Shipped models."),
            ]
        ),
        CvFileKind.DOCX,
    )

    assert [
        (e.degree, e.institution, e.dates.text if e.dates else None) for e in parsed.education
    ] == [
        ("Engineering degree in Computer Science", "ENSI", "2014 – 2017"),
        ("Preparatory classes", "IPEIT", "2012 – 2014"),
    ]
    assert [(p.name, p.bullets) for p in parsed.projects] == [
        ("Chatbot", ["RAG assistant for internal docs using LangChain."]),
        ("Vision", ["defect detection with YOLO."]),
    ]
    (experience,) = parsed.experiences
    assert (experience.title, experience.employer, experience.location) == (
        "ML Engineer",
        "Acme",
        "Paris",
    )
    assert experience.dates is not None
    assert experience.dates.is_current is True
    assert_nothing_invented(parsed, text)


def test_wrapped_pdf_bullets_are_joined() -> None:
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    rows = [
        (72, "Helvetica-Bold", 12, "EXPERIENCE"),
        (72, "Helvetica-Bold", 10, "AI Engineer — Omega | Tunis, Tunisia"),
        (72, "Helvetica", 10, "Jan 2022 – Present"),
        (72, "Helvetica", 10, "• Built a retrieval-augmented generation service that answers"),
        (82, "Helvetica", 10, "questions over 10k internal documents with LangGraph."),
        (72, "Helvetica", 10, "• Reduced costs by 20%."),
    ]
    for index, (x, font, size, content) in enumerate(rows):
        pdf.setFont(font, size)
        pdf.drawString(x, 800 - index * 14, content)
    pdf.showPage()
    pdf.save()

    parsed, text = parse_cv(buffer.getvalue(), CvFileKind.PDF)

    (experience,) = parsed.experiences
    assert experience.location == "Tunis, Tunisia"
    assert experience.bullets == [
        "Built a retrieval-augmented generation service that answers questions over 10k "
        "internal documents with LangGraph.",
        "Reduced costs by 20%.",
    ]
    assert_nothing_invented(parsed, text)


def test_confirmation_requires_complete_entries() -> None:
    from app.cv.models import DateRange, ExperienceEntry, YearMonth
    from app.cv.parser import PARSER_VERSION, confirmation_errors

    cv = ParsedCV(
        parser_version=PARSER_VERSION,
        experiences=[
            ExperienceEntry(title=""),
            ExperienceEntry(
                title="Engineer",
                dates=DateRange(
                    text="2022 - 2020", start=YearMonth(year=2022), end=YearMonth(year=2020)
                ),
            ),
        ],
    )

    assert [error["loc"] for error in confirmation_errors(cv)] == [
        "experiences.0.title",
        "experiences.1.dates",
    ]


@pytest.mark.parametrize(
    ("line", "phones"),
    [
        ("Tunis | +216 20 123 456", ["+216 20 123 456"]),
        ("(+33) 6 12 34 56 78", ["(+33) 6 12 34 56 78"]),
        ("Available 2019 - 2021", []),  # a date range is not a phone number
        ("Order 12345", []),  # too short
    ],
)
def test_phone_numbers_are_extracted_conservatively(line: str, phones: list[str]) -> None:
    from app.cv.parser import extract_contact

    assert extract_contact([line]).phones == phones
