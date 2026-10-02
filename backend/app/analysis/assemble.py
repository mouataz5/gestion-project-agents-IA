"""Turn the model's answer into a verified analysis and a decision.

The model proposes; this module verifies (visa quotes, skill evidence, languages) and the
qualification rules decide. The model's own recommendation is kept for transparency only.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.analysis.facts import CandidateFacts
from app.analysis.job_text import posting_text
from app.analysis.languages import check_languages
from app.analysis.qualification import QualificationInput, qualify
from app.analysis.schemas import JobAnalysisOutput, RelevanceResult, VisaResult
from app.analysis.skills import verify_skills
from app.analysis.sponsorship import sponsorship_needed
from app.analysis.types import Recommendation
from app.analysis.visa import find_visa_signals, merge_visa
from app.models import Job


@dataclass(frozen=True)
class AssembledAnalysis:
    visa: VisaResult
    relevance: RelevanceResult
    recommendation: Recommendation
    llm_recommendation: Recommendation
    reasons: list[str]


def assemble_analysis(
    output: JobAnalysisOutput, *, job: Job, facts: CandidateFacts
) -> AssembledAnalysis:
    text = posting_text(job)
    needed = sponsorship_needed(facts.work_authorization, job.country_code)
    visa = merge_visa(
        find_visa_signals(text),
        output.visa,
        job_text=text,
        sponsorship_needed=needed,
        country_code=job.country_code,
    )
    skills = verify_skills(
        required=job.required_skills,
        preferred=job.preferred_skills,
        assessments=output.skills,
        evidence=facts.skills,
        job_text=text,
    )
    checks, languages_met = check_languages(
        job.languages, output.language_requirements, facts.languages, job_text=text
    )
    decision = qualify(
        QualificationInput(
            role_relevance=output.role_relevance,
            seniority_fit=output.seniority_fit,
            required_count=skills.required_count,
            required_coverage=skills.required_coverage,
            languages_met=languages_met,
            visa_status=visa.status,
            sponsorship_needed=needed,
        )
    )
    relevance = RelevanceResult(
        role_relevance=output.role_relevance,
        role_relevance_reason=output.role_relevance_reason,
        seniority_fit=output.seniority_fit,
        seniority_reason=output.seniority_reason,
        required_skill_matches=skills.required_matches,
        preferred_skill_matches=skills.preferred_matches,
        skill_gaps=skills.gaps,
        unsupported_claims=skills.unsupported_claims,
        required_count=skills.required_count,
        required_coverage=skills.required_coverage,
        language_requirements=checks,
        languages_met=languages_met,
        concerns=list(output.concerns),
        reasoning=output.explanation,
    )
    return AssembledAnalysis(
        visa=visa,
        relevance=relevance,
        recommendation=decision.recommendation,
        llm_recommendation=Recommendation(output.recommendation),
        reasons=decision.reasons,
    )
