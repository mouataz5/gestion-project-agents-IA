"""Deterministic analysis rules: sponsorship need, skill-match verification, languages and the
qualification table (APPLY / REVIEW / SKIP)."""

import pytest

from app.analysis.languages import CandidateLanguage, candidate_languages, check_languages
from app.analysis.qualification import QualificationInput, qualify
from app.analysis.schemas import LanguageRequirementOutput, SkillAssessment
from app.analysis.skills import CandidateSkillEvidence, verify_skills
from app.analysis.sponsorship import sponsorship_needed
from app.analysis.types import Recommendation, VisaStatus
from app.schemas.candidate import (
    AuthorizationStatus,
    SpokenLanguage,
    WorkAuthorization,
    WorkAuthorizationEntry,
)

TUNISIAN = WorkAuthorization(
    visa_sponsorship_required=True,
    sponsorship_required_when="work_permit_needed",
    current_work_authorizations=[
        WorkAuthorizationEntry(country_code="TN", status=AuthorizationStatus.CITIZEN)
    ],
)


# --- sponsorship need ---------------------------------------------------------------------------


@pytest.mark.feature("visa-classification")
@pytest.mark.parametrize(
    ("authorization", "country", "needed"),
    [
        (TUNISIAN, "FR", True),
        (TUNISIAN, "AE", True),
        (TUNISIAN, "TN", False),
        (TUNISIAN, None, None),
        (WorkAuthorization(sponsorship_required_when="never"), "FR", False),
        (WorkAuthorization(visa_sponsorship_required=False), "DE", False),
        (WorkAuthorization(sponsorship_required_when="always"), "FR", True),
        (
            WorkAuthorization(
                sponsorship_required_when="work_permit_needed",
                current_work_authorizations=[
                    WorkAuthorizationEntry(country_code="FR", status=AuthorizationStatus.CITIZEN)
                ],
            ),
            "DE",
            False,  # EU citizens work anywhere in the EEA without a permit
        ),
        (WorkAuthorization(), "FR", None),  # nothing declared: unknown, never guessed
    ],
)
def test_sponsorship_need_comes_from_the_profile(
    authorization: WorkAuthorization, country: str | None, needed: bool | None
) -> None:
    assert sponsorship_needed(authorization, country) is needed


# --- skills -------------------------------------------------------------------------------------

EVIDENCE = [
    CandidateSkillEvidence("Python", "LISTED"),
    CandidateSkillEvidence("LLMs", "DEMONSTRATED"),
    CandidateSkillEvidence("RAG", "DEMONSTRATED"),
    CandidateSkillEvidence("LangGraph", "DEMONSTRATED"),
    CandidateSkillEvidence("Kubernetes", "DEMONSTRATED"),
    CandidateSkillEvidence("Deep Learning", "NONE"),
]


@pytest.mark.feature("job-relevance")
def test_skill_matches_must_be_backed_by_cv_evidence() -> None:
    result = verify_skills(
        required=["Python", "LLMs", "RAG", "LangGraph"],
        preferred=["Kubernetes", "MCP"],
        assessments=[
            SkillAssessment(
                job_skill="MCP", importance="PREFERRED", candidate_skill="Model Context Protocol"
            ),
        ],
        evidence=EVIDENCE,
        job_text="",
    )

    assert [m.job_skill for m in result.required_matches] == ["Python", "LLMs", "RAG", "LangGraph"]
    assert result.required_matches[1].strength == "DEMONSTRATED"
    assert [m.job_skill for m in result.preferred_matches] == ["Kubernetes"]
    assert result.gaps == ["MCP"]
    assert result.unsupported_claims == ["MCP → Model Context Protocol"]
    assert (result.required_count, result.required_coverage) == (4, 1.0)


@pytest.mark.feature("job-relevance")
def test_semantic_matches_count_only_with_evidence() -> None:
    result = verify_skills(
        required=["Large Language Models", "Deep Learning"],
        preferred=[],
        assessments=[
            SkillAssessment(
                job_skill="Large Language Models", importance="REQUIRED", candidate_skill="LLMs"
            ),
            SkillAssessment(
                job_skill="Deep Learning", importance="REQUIRED", candidate_skill="Deep Learning"
            ),
        ],
        evidence=EVIDENCE,
        job_text="",
    )

    assert [(m.job_skill, m.candidate_skill) for m in result.required_matches] == [
        ("Large Language Models", "LLMs")
    ]
    assert result.gaps == ["Deep Learning"]  # declared in the profile, no evidence in the CV
    assert result.unsupported_claims == ["Deep Learning → Deep Learning"]
    assert result.required_coverage == 0.5


@pytest.mark.feature("job-relevance")
def test_skills_extracted_by_claude_must_appear_in_the_posting() -> None:
    result = verify_skills(
        required=[],
        preferred=[],
        assessments=[
            SkillAssessment(job_skill="Python", importance="REQUIRED", candidate_skill="Python"),
            SkillAssessment(job_skill="Rust", importance="REQUIRED", candidate_skill=None),
            SkillAssessment(
                job_skill="Kubernetes", importance="PREFERRED", candidate_skill="Kubernetes"
            ),
        ],
        evidence=EVIDENCE,
        job_text="You will write Python services and deploy them on Kubernetes.",
    )

    assert [m.job_skill for m in result.required_matches] == ["Python"]
    assert [m.job_skill for m in result.preferred_matches] == ["Kubernetes"]
    assert result.gaps == []  # "Rust" is not in the posting: an invented requirement is dropped
    assert result.required_count == 1


@pytest.mark.feature("job-relevance")
def test_no_listed_requirements_means_unknown_coverage() -> None:
    result = verify_skills(
        required=[], preferred=[], assessments=[], evidence=EVIDENCE, job_text=""
    )

    assert (result.required_count, result.required_coverage) == (0, None)


# --- languages ----------------------------------------------------------------------------------


@pytest.mark.feature("job-relevance")
def test_candidate_languages_come_from_the_profile_then_the_cv() -> None:
    from_profile = candidate_languages(
        [SpokenLanguage(language="English", level="professional")],
        ["Arabic (native)"],
    )
    from_cv = candidate_languages(
        None, ["Arabic (native), French (fluent), English (professional)"]
    )

    assert from_profile == [CandidateLanguage("English", 3)]
    assert from_cv == [
        CandidateLanguage("Arabic", 5),
        CandidateLanguage("French", 4),
        CandidateLanguage("English", 3),
    ]
    assert candidate_languages(None, []) is None  # unknown, never guessed


@pytest.mark.feature("job-relevance")
@pytest.mark.parametrize(
    ("job_languages", "requirements", "candidate", "met"),
    [
        (
            ["English", "French"],
            [],
            [CandidateLanguage("English", 3), CandidateLanguage("French", 4)],
            True,
        ),
        (["English", "German"], [], [CandidateLanguage("English", 3)], False),
        ([], [], [CandidateLanguage("English", 3)], True),
        (["English"], [], None, None),
        (
            [],
            [LanguageRequirementOutput(language="Allemand", required=True, level="C1")],
            [CandidateLanguage("German", 2)],
            False,
        ),
        (
            [],
            [LanguageRequirementOutput(language="German", required=False, level=None)],
            [CandidateLanguage("English", 3)],
            True,  # nice-to-have languages never block
        ),
    ],
)
def test_language_requirements(
    job_languages: list[str],
    requirements: list[LanguageRequirementOutput],
    candidate: list[CandidateLanguage] | None,
    met: bool | None,
) -> None:
    text = "Fluent German (C1) is required. Allemand. German."
    checks, all_met = check_languages(job_languages, requirements, candidate, job_text=text)

    assert all_met is met
    assert all(check.language for check in checks)


# --- qualification ------------------------------------------------------------------------------

APPLY_CASE = {
    "role_relevance": "HIGH",
    "seniority_fit": "MATCH",
    "required_count": 4,
    "required_coverage": 1.0,
    "languages_met": True,
    "visa_status": VisaStatus.SPONSORSHIP_CONFIRMED,
    "sponsorship_needed": True,
}


@pytest.mark.feature("job-relevance")
@pytest.mark.parametrize(
    ("changes", "recommendation", "reason"),
    [
        ({}, Recommendation.APPLY, "Visa sponsorship is confirmed"),
        ({"seniority_fit": "UNKNOWN"}, Recommendation.APPLY, "seniority is not stated"),
        ({"visa_status": VisaStatus.SPONSORSHIP_LIKELY}, Recommendation.APPLY, "likely"),
        (
            {"sponsorship_needed": False, "visa_status": VisaStatus.SPONSORSHIP_UNKNOWN},
            Recommendation.APPLY,
            "do not need sponsorship",
        ),
        (
            {"visa_status": VisaStatus.SPONSORSHIP_NOT_AVAILABLE},
            Recommendation.SKIP,
            "rules out visa sponsorship",
        ),
        (
            {"visa_status": VisaStatus.SPONSORSHIP_NOT_AVAILABLE, "sponsorship_needed": False},
            Recommendation.APPLY,
            "do not need sponsorship",
        ),
        ({"role_relevance": "LOW"}, Recommendation.SKIP, "not a match for your target roles"),
        ({"languages_met": False}, Recommendation.SKIP, "required language"),
        (
            {"visa_status": VisaStatus.SPONSORSHIP_UNKNOWN},
            Recommendation.REVIEW,
            "sponsorship is not mentioned",
        ),
        (
            {"sponsorship_needed": None, "visa_status": VisaStatus.SPONSORSHIP_UNKNOWN},
            Recommendation.REVIEW,
            "work authorization",
        ),
        ({"role_relevance": "MEDIUM"}, Recommendation.REVIEW, "partly matches"),
        ({"seniority_fit": "UNDER_QUALIFIED"}, Recommendation.REVIEW, "more senior"),
        ({"seniority_fit": "OVER_QUALIFIED"}, Recommendation.REVIEW, "more junior"),
        ({"required_coverage": 0.5}, Recommendation.REVIEW, "2 of 4 required skills"),
        (
            {"required_count": 0, "required_coverage": None},
            Recommendation.REVIEW,
            "no required skills",
        ),
        ({"languages_met": None}, Recommendation.REVIEW, "languages"),
    ],
)
def test_qualification_rules(
    changes: dict[str, object], recommendation: Recommendation, reason: str
) -> None:
    result = qualify(QualificationInput(**{**APPLY_CASE, **changes}))  # type: ignore[arg-type]

    assert result.recommendation is recommendation
    assert any(reason.lower() in text.lower() for text in result.reasons), result.reasons
