"""Deterministic title pre-filter: keep AI/ML roles before any (paid) LLM analysis.

This is not the relevance judgement (Phase 4 does that with Claude); it only stops obviously
unrelated postings (sales, frontend, office roles) from entering the pipeline. Matching reuses
the skill matcher: word boundaries, synonyms, case-sensitive for two-letter terms ("AI", "ML").
"""

from __future__ import annotations

from collections.abc import Iterable

from app.cv.evidence import mentions

AI_ML_TERMS: tuple[str, ...] = (
    "AI",
    "IA",
    "Artificial Intelligence",
    "Intelligence Artificielle",
    "Machine Learning",
    "MLOps",
    "Deep Learning",
    "LLMs",
    "Generative AI",
    "NLP",
    "Computer Vision",
    "Data Scientist",
    "Data Science",
    "Science des données",
    "Applied Scientist",
    "Research Scientist",
    "RAG",
    "Agentic",
    "AI agent",
    "Prompt Engineer",
    "Reinforcement Learning",
    "Neural",
)


def title_matches(title: str, roles: Iterable[str] = ()) -> bool:
    """True when the title names an AI/ML role or one of the candidate's target roles."""
    return any(mentions(title, term) for term in (*roles, *AI_ML_TERMS))
