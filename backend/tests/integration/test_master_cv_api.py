import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.session import create_db_engine, create_session_factory
from app.main import create_app
from app.models import CandidateSkill, CvVersion, Experience

pytestmark = [pytest.mark.feature("cv-upload"), pytest.mark.integration]

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
CvLines = list[tuple[str, str]]


@pytest.fixture
def db(candidate_settings: Settings) -> Iterator[sessionmaker[Session]]:
    engine = create_db_engine(candidate_settings)
    yield create_session_factory(engine)
    engine.dispose()


def _upload(
    client: TestClient, content: bytes, filename: str = "Alex CV.docx", mime: str = DOCX
) -> dict[str, Any]:
    response = client.post("/api/v1/candidate/master-cv", files={"file": (filename, content, mime)})
    assert response.status_code == 201, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


@pytest.mark.feature("cv-parsing")
def test_upload_parses_the_cv_and_stores_it_privately(
    candidate_client: TestClient,
    cv_docx: Callable[[CvLines], bytes],
    sample_cv_en: CvLines,
    db: sessionmaker[Session],
) -> None:
    content = cv_docx(sample_cv_en)

    body = _upload(candidate_client, content)

    assert body["status"] == "PARSED"
    assert body["version"] == 1
    assert body["kind"] == "MASTER"
    assert body["original_filename"] == "Alex CV.docx"
    assert body["size_bytes"] == len(content)
    assert [e["title"] for e in body["structure"]["experiences"]] == [
        "Senior AI Engineer",
        "Machine Learning Engineer",
    ]
    with db() as session:
        stored = session.get(CvVersion, uuid.UUID(body["id"]))
        assert stored is not None
        assert stored.storage_key.startswith(f"candidates/{stored.candidate_id}/master_cv/")
        assert stored.storage_key.endswith(".docx")
        assert "Alex" not in stored.storage_key  # generated name, never the user's filename


@pytest.mark.parametrize(
    ("filename", "content", "status", "code"),
    [
        ("cv.doc", b"legacy word", 415, "unsupported_file_type"),
        ("cv.docx", b"%PDF-1.7 spoofed", 415, "file_type_mismatch"),
        ("cv.pdf", b"", 400, "empty_file"),
        ("cv.pdf", b"%PDF-1.7 not really a pdf", 422, "unreadable_file"),
    ],
)
def test_invalid_uploads_are_rejected(
    candidate_client: TestClient, filename: str, content: bytes, status: int, code: str
) -> None:
    response = candidate_client.post(
        "/api/v1/candidate/master-cv", files={"file": (filename, content, "application/pdf")}
    )

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert candidate_client.get("/api/v1/candidate/master-cv").json() == []


def test_oversized_uploads_are_rejected(
    make_settings: Callable[..., Settings],
    postgres_url: str,
    clean_db: None,
    candidate_dir: Any,
    api_token: str,
) -> None:
    settings = make_settings(
        database_url=postgres_url, candidate_dir=candidate_dir, max_upload_mb=1
    )
    with TestClient(create_app(settings), headers={"Authorization": f"Bearer {api_token}"}) as c:
        response = c.post(
            "/api/v1/candidate/master-cv",
            files={"file": ("cv.pdf", b"%PDF-" + b"0" * 1_200_000, "application/pdf")},
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_versions_are_listed_newest_first_and_files_can_be_downloaded(
    candidate_client: TestClient,
    cv_docx: Callable[[CvLines], bytes],
    cv_pdf: Callable[..., bytes],
    sample_cv_en: CvLines,
) -> None:
    docx_bytes = cv_docx(sample_cv_en)
    first = _upload(candidate_client, docx_bytes)
    second = _upload(candidate_client, cv_pdf(sample_cv_en), "cv.pdf", "application/pdf")

    versions = candidate_client.get("/api/v1/candidate/master-cv").json()
    download = candidate_client.get(f"/api/v1/candidate/master-cv/{first['id']}/file")

    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["id"] == second["id"]
    assert versions[0]["content_type"] == "application/pdf"
    assert download.status_code == 200
    assert download.content == docx_bytes
    assert download.headers["content-type"] == DOCX
    assert download.headers["content-disposition"] == 'attachment; filename="Alex CV.docx"'


@pytest.mark.feature("cv-parsing")
def test_drafts_can_be_edited_before_confirmation(
    candidate_client: TestClient, cv_docx: Callable[[CvLines], bytes], sample_cv_en: CvLines
) -> None:
    draft = _upload(candidate_client, cv_docx(sample_cv_en))
    structure = draft["structure"]
    structure["experiences"][0]["title"] = "Lead AI Engineer"
    structure["experiences"][0]["bullets"].append("Mentored two engineers.")

    response = candidate_client.put(
        f"/api/v1/candidate/master-cv/{draft['id']}/structure", json=structure
    )

    assert response.status_code == 200, response.text
    assert response.json()["structure"]["experiences"][0]["title"] == "Lead AI Engineer"
    detail = candidate_client.get(f"/api/v1/candidate/master-cv/{draft['id']}").json()
    assert detail["structure"]["experiences"][0]["bullets"][-1] == "Mentored two engineers."


def test_invalid_structure_edits_are_rejected(
    candidate_client: TestClient, cv_docx: Callable[[CvLines], bytes], sample_cv_en: CvLines
) -> None:
    draft = _upload(candidate_client, cv_docx(sample_cv_en))
    structure = draft["structure"]
    del structure["experiences"][0]["title"]

    response = candidate_client.put(
        f"/api/v1/candidate/master-cv/{draft['id']}/structure", json=structure
    )

    assert response.status_code == 422


@pytest.mark.feature("candidate-skills")
def test_confirmation_builds_the_fact_base_and_skill_evidence(
    candidate_client: TestClient,
    cv_docx: Callable[[CvLines], bytes],
    sample_cv_en: CvLines,
    db: sessionmaker[Session],
) -> None:
    draft = _upload(candidate_client, cv_docx(sample_cv_en))

    response = candidate_client.post(f"/api/v1/candidate/master-cv/{draft['id']}/confirm")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CONFIRMED"
    assert response.json()["confirmed_at"] is not None
    candidate = candidate_client.get("/api/v1/candidate").json()
    assert candidate["active_master_cv"]["id"] == draft["id"]
    skills = {s["name"]: s for s in candidate_client.get("/api/v1/candidate/skills").json()}
    assert skills["LangGraph"]["strength"] == "DEMONSTRATED"
    assert skills["Python"]["strength"] == "LISTED"
    assert skills["Deep Learning"]["strength"] == "NONE"
    assert any("LangGraph" in item["excerpt"] for item in skills["LangGraph"]["evidence"])
    with db() as session:
        experiences = session.scalars(select(Experience).order_by(Experience.position)).all()
        assert [e.title for e in experiences] == ["Senior AI Engineer", "Machine Learning Engineer"]
        assert experiences[0].is_current is True
        assert experiences[0].start_date is not None
        assert experiences[0].start_date.isoformat() == "2022-01-01"
        assert "LangGraph" in experiences[0].technologies
        assert session.scalar(select(func.count()).select_from(CandidateSkill)) == len(skills)


def test_confirmed_versions_are_immutable(
    candidate_client: TestClient, cv_docx: Callable[[CvLines], bytes], sample_cv_en: CvLines
) -> None:
    draft = _upload(candidate_client, cv_docx(sample_cv_en))
    candidate_client.post(f"/api/v1/candidate/master-cv/{draft['id']}/confirm")

    edit = candidate_client.put(
        f"/api/v1/candidate/master-cv/{draft['id']}/structure", json=draft["structure"]
    )
    reconfirm = candidate_client.post(f"/api/v1/candidate/master-cv/{draft['id']}/confirm")

    assert edit.status_code == 409
    assert reconfirm.status_code == 409


def test_a_new_confirmation_supersedes_the_previous_master(
    candidate_client: TestClient,
    cv_docx: Callable[[CvLines], bytes],
    sample_cv_en: CvLines,
    sample_cv_fr: CvLines,
    db: sessionmaker[Session],
) -> None:
    first = _upload(candidate_client, cv_docx(sample_cv_en))
    candidate_client.post(f"/api/v1/candidate/master-cv/{first['id']}/confirm")
    second = _upload(candidate_client, cv_docx(sample_cv_fr))

    candidate_client.post(f"/api/v1/candidate/master-cv/{second['id']}/confirm")

    statuses = {
        v["id"]: v["status"] for v in candidate_client.get("/api/v1/candidate/master-cv").json()
    }
    assert statuses == {first["id"]: "SUPERSEDED", second["id"]: "CONFIRMED"}
    with db() as session:
        titles = session.scalars(select(Experience.title).order_by(Experience.position)).all()
        assert titles == ["Ingénieur IA", "Data Scientist"]  # facts rebuilt from the new master


def test_revise_creates_an_editable_copy(
    candidate_client: TestClient, cv_docx: Callable[[CvLines], bytes], sample_cv_en: CvLines
) -> None:
    original = _upload(candidate_client, cv_docx(sample_cv_en))
    candidate_client.post(f"/api/v1/candidate/master-cv/{original['id']}/confirm")

    response = candidate_client.post(f"/api/v1/candidate/master-cv/{original['id']}/revise")

    assert response.status_code == 201, response.text
    revision = response.json()
    assert revision["status"] == "PARSED"
    assert revision["version"] == 2
    assert revision["revised_from_id"] == original["id"]
    assert revision["structure"] == original["structure"]
    active = candidate_client.get("/api/v1/candidate").json()["active_master_cv"]
    assert active["id"] == original["id"]  # the confirmed version stays active until re-confirmed


def test_identical_uploads_share_storage(
    candidate_client: TestClient,
    cv_docx: Callable[[CvLines], bytes],
    sample_cv_en: CvLines,
    db: sessionmaker[Session],
) -> None:
    content = cv_docx(sample_cv_en)
    first, second = _upload(candidate_client, content), _upload(candidate_client, content)

    with db() as session:
        keys = {
            session.get(CvVersion, uuid.UUID(item["id"])).storage_key  # type: ignore[union-attr]
            for item in (first, second)
        }
    assert len(keys) == 1


def test_cv_actions_are_audited(
    candidate_client: TestClient, cv_docx: Callable[[CvLines], bytes], sample_cv_en: CvLines
) -> None:
    draft = _upload(candidate_client, cv_docx(sample_cv_en))
    candidate_client.post(f"/api/v1/candidate/master-cv/{draft['id']}/confirm")

    entries = candidate_client.get(
        "/api/v1/audit-logs", params={"entity_type": "cv_version", "entity_id": draft["id"]}
    ).json()["items"]

    assert {entry["action"] for entry in entries} == {"cv.uploaded", "cv.confirmed"}


def test_unknown_versions_return_404(candidate_client: TestClient) -> None:
    response = candidate_client.get(f"/api/v1/candidate/master-cv/{uuid.uuid4()}")
    assert response.status_code == 404


def test_incomplete_drafts_cannot_be_confirmed(
    candidate_client: TestClient, cv_docx: Callable[[CvLines], bytes], sample_cv_en: CvLines
) -> None:
    draft = _upload(candidate_client, cv_docx(sample_cv_en))
    structure = draft["structure"]
    structure["experiences"][0]["title"] = ""
    candidate_client.put(f"/api/v1/candidate/master-cv/{draft['id']}/structure", json=structure)

    response = candidate_client.post(f"/api/v1/candidate/master-cv/{draft['id']}/confirm")

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "invalid_cv_structure"
    assert body["details"][0]["loc"] == "experiences.0.title"
    detail = candidate_client.get(f"/api/v1/candidate/master-cv/{draft['id']}").json()
    assert detail["status"] == "PARSED"
    assert any("no job title" in warning for warning in detail["structure"]["warnings"])


def test_drafts_are_not_revised(
    candidate_client: TestClient, cv_docx: Callable[[CvLines], bytes], sample_cv_en: CvLines
) -> None:
    draft = _upload(candidate_client, cv_docx(sample_cv_en))

    response = candidate_client.post(f"/api/v1/candidate/master-cv/{draft['id']}/revise")

    assert response.status_code == 409


def test_uploaded_filenames_are_sanitized(
    candidate_client: TestClient, cv_docx: Callable[[CvLines], bytes], sample_cv_en: CvLines
) -> None:
    body = _upload(candidate_client, cv_docx(sample_cv_en), filename="../../CV <Émilie>.docx")

    assert body["original_filename"] == "CV Émilie.docx"
    download = candidate_client.get(f"/api/v1/candidate/master-cv/{body['id']}/file")
    assert download.headers["content-disposition"] == (
        "attachment; filename=\"CV Emilie.docx\"; filename*=UTF-8''CV%20%C3%89milie.docx"
    )


def test_master_cv_endpoints_require_the_api_token(candidate_settings: Settings) -> None:
    with TestClient(create_app(candidate_settings)) as anonymous:
        assert anonymous.get("/api/v1/candidate/master-cv").status_code == 401
        upload = anonymous.post(
            "/api/v1/candidate/master-cv",
            files={"file": ("cv.pdf", b"%PDF-1.7", "application/pdf")},
        )
        assert upload.status_code == 401
