import pytest

from app.api.downloads import content_disposition

pytestmark = pytest.mark.feature("cv-upload")


@pytest.mark.parametrize(
    ("filename", "header"),
    [
        ("Alex CV.docx", 'attachment; filename="Alex CV.docx"'),
        (
            "CV Émilie.pdf",
            "attachment; filename=\"CV Emilie.pdf\"; filename*=UTF-8''CV%20%C3%89milie.pdf",
        ),
        (
            "سيرة.pdf",
            "attachment; filename=\".pdf\"; filename*=UTF-8''%D8%B3%D9%8A%D8%B1%D8%A9.pdf",
        ),
    ],
)
def test_content_disposition(filename: str, header: str) -> None:
    assert content_disposition(filename) == header
