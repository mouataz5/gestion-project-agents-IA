"""The structured CV document: parser output, draft edited by the user, confirmed fact base.

Invariant for parser output: every string value (except ``parser_version``, ``language`` and
``warnings``) is a substring of the document's extracted text — the parser never invents text.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SkillStrength(StrEnum):
    NONE = "NONE"  # declared but not found in the confirmed master CV
    LISTED = "LISTED"  # mentioned (skills section, summary, education, certifications)
    DEMONSTRATED = "DEMONSTRATED"  # used in an experience or a project


class SkillSource(StrEnum):
    MASTER_CV = "MASTER_CV"  # listed in the skills section of the master CV
    PROFILE_DECLARED = "PROFILE_DECLARED"  # declared in the candidate profile (core_skills)


class YearMonth(_Model):
    year: int = Field(ge=1900, le=2100)
    month: int | None = Field(default=None, ge=1, le=12)


class DateRange(_Model):
    text: str = Field(max_length=200, description="The dates as written in the CV")
    start: YearMonth | None = None
    end: YearMonth | None = None
    is_current: bool = False


class ContactInfo(_Model):
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)


class ExperienceEntry(_Model):
    title: str = Field(max_length=300)
    employer: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=200)
    dates: DateRange | None = None
    bullets: list[str] = Field(default_factory=list)
    details: list[str] = Field(default_factory=list)


class EducationEntry(_Model):
    degree: str = Field(max_length=300)
    institution: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=200)
    dates: DateRange | None = None
    bullets: list[str] = Field(default_factory=list)
    details: list[str] = Field(default_factory=list)


class ProjectEntry(_Model):
    name: str = Field(max_length=300)
    dates: DateRange | None = None
    bullets: list[str] = Field(default_factory=list)
    details: list[str] = Field(default_factory=list)


class SkillItem(_Model):
    name: str = Field(max_length=200)
    category: str | None = Field(default=None, max_length=100)


class OtherSection(_Model):
    heading: str = Field(max_length=200)
    lines: list[str] = Field(default_factory=list)


class ParsedCV(_Model):
    parser_version: str
    language: str = Field(default="unknown", max_length=10)
    header_lines: list[str] = Field(default_factory=list)
    contact: ContactInfo = Field(default_factory=ContactInfo)
    summary: str | None = None
    experiences: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    skills: list[SkillItem] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    other_sections: list[OtherSection] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    section: str
    excerpt: str


class SkillEvidence(BaseModel):
    name: str
    normalized_name: str
    category: str | None = None
    strength: SkillStrength
    sources: list[SkillSource]
    evidence: list[EvidenceItem] = Field(default_factory=list)
