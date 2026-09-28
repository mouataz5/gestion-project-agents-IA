from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import REPO_ROOT, Settings
from app.core.errors import NotFoundError
from app.core.storage import LocalStorageProvider
from app.db.session import create_db_engine, create_session_factory
from app.services.candidate_profile import CandidateService, load_profile
from app.services.master_cv import MasterCvService
from app.services.skills import SkillService

pytestmark = [pytest.mark.feature("multi-candidate"), pytest.mark.integration]


@pytest.fixture
def session_factory(candidate_settings: Settings) -> Iterator[sessionmaker[Session]]:
    engine = create_db_engine(candidate_settings)
    yield create_session_factory(engine)
    engine.dispose()


def test_candidate_data_is_isolated(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
    cv_docx: Callable[[list[tuple[str, str]]], bytes],
    sample_cv_en: list[tuple[str, str]],
    sample_cv_fr: list[tuple[str, str]],
) -> None:
    storage = LocalStorageProvider(tmp_path / "storage")
    profile = load_profile(REPO_ROOT / "candidate")

    with session_factory() as session:
        candidates = CandidateService(session, candidate_dir=REPO_ROOT / "candidate")
        cvs = MasterCvService(session, storage)
        alice = candidates.create("alice", profile)
        bob = candidates.create("bob", profile)
        alice_cv = cvs.upload(alice, filename="alice.docx", data=cv_docx(sample_cv_en))
        bob_cv = cvs.upload(bob, filename="bob.docx", data=cv_docx(sample_cv_fr))
        cvs.confirm(alice, alice_cv.id)
        cvs.confirm(bob, bob_cv.id)
        session.commit()

        assert [v.id for v in cvs.list_versions(alice)] == [alice_cv.id]
        assert [v.id for v in cvs.list_versions(bob)] == [bob_cv.id]
        with pytest.raises(NotFoundError):
            cvs.get(alice, bob_cv.id)
        assert [e.title for e in cvs.experiences(alice)] == [
            "Senior AI Engineer",
            "Machine Learning Engineer",
        ]
        assert [e.title for e in cvs.experiences(bob)] == ["Ingénieur IA", "Data Scientist"]
        skills = SkillService(session)
        alice_skills = {s.name for s in skills.list(alice)}
        bob_skills = {s.name for s in skills.list(bob)}
        assert "SQL" in alice_skills
        assert "SQL" not in bob_skills
        assert candidates.get_by_slug("alice").id == alice.id
