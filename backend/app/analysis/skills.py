"""Skill matches must be backed by the confirmed CV.

A job skill is matched when the candidate has the same skill (synonym-aware ``canonical_key``)
with ``DEMONSTRATED`` or ``LISTED`` evidence, or when the model maps it to such a skill. Claimed
matches citing a skill without evidence are removed and reported. Skills the model extracts from
free text must appear in the posting (no invented requirements).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.analysis.schemas import Importance, SkillAssessment, SkillMatch
from app.cv.evidence import canonical_key, mentions

BACKED = ("DEMONSTRATED", "LISTED")


@dataclass(frozen=True)
class CandidateSkillEvidence:
    name: str
    strength: str  # DEMONSTRATED | LISTED | NONE


@dataclass(frozen=True)
class SkillVerification:
    required_matches: list[SkillMatch] = field(default_factory=list)
    preferred_matches: list[SkillMatch] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    required_count: int = 0
    required_coverage: float | None = None


def verify_skills(
    *,
    required: Sequence[str],
    preferred: Sequence[str],
    assessments: Sequence[SkillAssessment],
    evidence: Sequence[CandidateSkillEvidence],
    job_text: str,
) -> SkillVerification:
    backed = {canonical_key(item.name): item for item in evidence if item.strength in BACKED}
    claims = {canonical_key(item.job_skill): item for item in assessments}

    items: list[tuple[str, Importance]] = []
    keys: set[str] = set()

    def add(skill: str, importance: Importance) -> None:
        key = canonical_key(skill)
        if key and key not in keys:
            keys.add(key)
            items.append((skill, importance))

    for skill in required:
        add(skill, "REQUIRED")
    for skill in preferred:
        add(skill, "PREFERRED")
    for assessment in assessments:  # requirements the model read in the free text
        if mentions(job_text, assessment.job_skill):
            add(assessment.job_skill, assessment.importance)

    result = SkillVerification()
    for job_skill, importance in items:
        key = canonical_key(job_skill)
        match: SkillMatch | None = None
        if key in backed:
            found = backed[key]
            match = SkillMatch(
                job_skill=job_skill,
                candidate_skill=found.name,
                strength=found.strength,  # type: ignore[arg-type]
                source="EXACT",
            )
        else:
            claim = claims.get(key)
            if claim is not None and claim.candidate_skill:
                cited = backed.get(canonical_key(claim.candidate_skill))
                if cited is not None:
                    match = SkillMatch(
                        job_skill=job_skill,
                        candidate_skill=cited.name,
                        strength=cited.strength,  # type: ignore[arg-type]
                        source="LLM",
                    )
                else:
                    result.unsupported_claims.append(f"{job_skill} → {claim.candidate_skill}")
        if match is None:
            result.gaps.append(job_skill)
        elif importance == "REQUIRED":
            result.required_matches.append(match)
        else:
            result.preferred_matches.append(match)

    required_count = sum(1 for _, importance in items if importance == "REQUIRED")
    coverage = round(len(result.required_matches) / required_count, 4) if required_count else None
    return SkillVerification(
        required_matches=result.required_matches,
        preferred_matches=result.preferred_matches,
        gaps=result.gaps,
        unsupported_claims=result.unsupported_claims,
        required_count=required_count,
        required_coverage=coverage,
    )
