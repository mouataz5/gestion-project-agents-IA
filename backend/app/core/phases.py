"""Delivery roadmap. The dashboard uses it to enable navigation for implemented phases only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PhaseStatus = Literal["done", "in_progress", "planned"]


@dataclass(frozen=True)
class Phase:
    number: int
    name: str
    status: PhaseStatus
    summary: str


PHASES: tuple[Phase, ...] = (
    Phase(
        1,
        "Foundation",
        "done",
        "Docker, PostgreSQL, FastAPI, Next.js, configuration, logging, health checks, migrations",
    ),
    Phase(
        2,
        "Candidate profile & master CV",
        "done",
        "Validated profile, master CV upload, deterministic parsing, review, skill evidence",
    ),
    Phase(
        3,
        "Job discovery",
        "done",
        "Jobs, source policy, mock sources, company watchlist, deduplication, posting window, "
        "URL and job-alert email imports",
    ),
    Phase(4, "Job analysis", "planned", "Claude integration, visa classification, matching"),
    Phase(5, "ATS engine", "planned", "Keyword extraction, ATS scoring, truthful tailoring loop"),
    Phase(6, "CV documents", "planned", "ATS-friendly DOCX and PDF generation"),
    Phase(7, "Application answers", "planned", "Question extraction and grounded answers"),
    Phase(8, "Browser automation", "planned", "Playwright, mock ATS sites, ATS adapters"),
    Phase(9, "Human approval", "planned", "Review, edit, skip, approve and guarded submission"),
    Phase(10, "Real sources", "planned", "Public ATS APIs and career pages with compliance"),
    Phase(11, "Automation & dashboard", "planned", "Scheduler, notifications, KPIs, hardening"),
)


def implemented_phases() -> set[int]:
    return {phase.number for phase in PHASES if phase.status == "done"}
