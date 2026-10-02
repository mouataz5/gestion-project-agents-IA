"""The job posting as sent to the model, and as used to verify quotes and requirements."""

from __future__ import annotations

import re
from typing import Any

from app.models import Job

_TAG = re.compile(r"</?\s*job_posting\s*>", re.IGNORECASE)


def _clean(text: str | None) -> str:
    # The posting is untrusted: it must not be able to close the block it is wrapped in.
    return _TAG.sub("[removed tag]", text or "").strip()


def posting_text(job: Job) -> str:
    """Every text of the posting (quotes and extracted requirements must come from here)."""
    parts = [
        job.title,
        job.description,
        job.visa_information,
        job.relocation_information,
        job.experience_requirements,
        job.education_requirements,
        *job.responsibilities,
        ", ".join(job.required_skills),
        ", ".join(job.preferred_skills),
        ", ".join(job.languages),
    ]
    return "\n".join(part for part in parts if part)


def render_job_posting(job: Job) -> str:
    """The user message: the posting wrapped in <job_posting> tags (data, never instructions)."""
    location = job.location or "not stated"
    if job.country_code:
        location += f" (country code {job.country_code})"
    lines = [
        "<job_posting>",
        f"Title: {_clean(job.title) or 'not stated'}",
        f"Company: {_clean(job.company) or 'not stated'}",
        f"Location: {_clean(location)}",
        f"Workplace: {job.remote_status.value}",
        f"Employment type: {job.employment_type.value}",
        f"Seniority suggested by the title: {job.seniority.value}",
    ]
    if job.required_skills:
        lines.append("Required skills (as listed): " + _clean(", ".join(job.required_skills)))
    if job.preferred_skills:
        lines.append("Preferred skills (as listed): " + _clean(", ".join(job.preferred_skills)))
    if job.languages:
        lines.append("Languages (as listed): " + _clean(", ".join(job.languages)))
    for label, value in (
        ("Experience", job.experience_requirements),
        ("Education", job.education_requirements),
        ("Visa information", job.visa_information),
        ("Relocation information", job.relocation_information),
    ):
        if value:
            lines.append(f"{label}: {_clean(value)}")
    if job.responsibilities:
        lines.append("Responsibilities:")
        lines.extend(f"- {_clean(item)}" for item in job.responsibilities)
    lines.append("Description:")
    lines.append(_clean(job.description) or "(no description stored)")
    lines.append("</job_posting>")
    return "\n".join(lines)


def job_context(job: Job) -> dict[str, Any]:
    """Structured job inputs (for the mock provider and for identifying requests in tests)."""
    return {
        "source_job_id": job.source_job_id,
        "title": job.title,
        "company": job.company,
        "country_code": job.country_code,
        "remote_status": job.remote_status.value,
        "employment_type": job.employment_type.value,
        "seniority": job.seniority.value,
        "required_skills": list(job.required_skills),
        "preferred_skills": list(job.preferred_skills),
        "languages": list(job.languages),
        "experience_requirements": job.experience_requirements,
        "posting_text": posting_text(job),
    }
