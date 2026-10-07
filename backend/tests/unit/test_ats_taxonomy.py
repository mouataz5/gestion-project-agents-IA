"""Skills taxonomy: one source of truth for synonyms, categories and safe free-text scanning."""

import pytest

from app.ats.taxonomy import (
    TECH_CATEGORIES,
    TERMS,
    Category,
    Term,
    _index,
    canonical_key,
    canonical_name,
    category_of,
    find_term,
    is_generic,
    mentions,
    scan_terms,
    vocabulary,
)
from app.cv import evidence

pytestmark = pytest.mark.feature("ats-engine")

# Canonical keys of every spelling known before Phase 5. Stored skill keys (candidate_skills,
# job_skills) depend on them: they must never change.
GOLDEN_KEYS: dict[str, str] = {
    "Kubernetes": "kubernete",
    "k8s": "kubernete",
    "LLMs": "llm",
    "LLM": "llm",
    "large language model": "llm",
    "grand modèle de langage": "llm",
    "grands modèles de langage": "llm",
    "RAG": "rag",
    "retrieval augmented generation": "rag",
    "Machine Learning": "machine learning",
    "ML": "machine learning",
    "apprentissage automatique": "machine learning",
    "Deep Learning": "deep learning",
    "neural network": "deep learning",
    "apprentissage profond": "deep learning",
    "réseaux de neurones": "deep learning",
    "NLP": "nlp",
    "natural language processing": "nlp",
    "traitement automatique du langage": "nlp",
    "TALN": "nlp",
    "Computer Vision": "computer vision",
    "vision par ordinateur": "computer vision",
    "Agentic AI": "agentic ai",
    "agentic": "agentic ai",
    "AI agent": "agentic ai",
    "LLM agent": "agentic ai",
    "autonomous agent": "agentic ai",
    "agents IA": "agentic ai",
    "agent IA": "agentic ai",
    "agents LLM": "agentic ai",
    "agent LLM": "agentic ai",
    "IA agentique": "agentic ai",
    "Multi-agent systems": "multi agent system",
    "multi-agent": "multi agent system",
    "multi agents": "multi agent system",
    "systèmes multi-agents": "multi agent system",
    "MCP": "mcp",
    "Model Context Protocol": "mcp",
    "Vector databases": "vector database",
    "vector database": "vector database",
    "vector DB": "vector database",
    "vector store": "vector database",
    "vector search": "vector database",
    "base de données vectorielle": "vector database",
    "bases de données vectorielles": "vector database",
    "Time-series analysis": "time series analysis",
    "time series": "time series analysis",
    "séries temporelles": "time series analysis",
    "série temporelle": "time series analysis",
    "MLOps": "mlop",
    "ML Ops": "mlop",
    "Generative AI": "generative ai",
    "GenAI": "generative ai",
    "Gen AI": "generative ai",
    "IA générative": "generative ai",
    "GCP": "gcp",
    "Google Cloud": "gcp",
    "Google Cloud Platform": "gcp",
    "AWS": "aws",
    "Amazon Web Services": "aws",
    "Azure": "azure",
    "Microsoft Azure": "azure",
    "Spark": "spark",
    "Apache Spark": "spark",
    "PySpark": "spark",
    "Scikit-learn": "scikit learn",
    "sklearn": "scikit learn",
    "PostgreSQL": "postgresql",
    "Postgres": "postgresql",
    "JavaScript": "javascript",
    "JS": "javascript",
    "TypeScript": "typescript",
    "TS": "typescript",
    "Node.js": "node.j",
    "NodeJS": "node.j",
    "Go": "go",
    "Golang": "go",
    "Hugging Face": "hugging face",
    "HuggingFace": "hugging face",
    "CI/CD": "ci cd",
    "CICD": "ci cd",
    "continuous integration": "ci cd",
}


def test_the_keys_of_earlier_phases_never_change() -> None:
    assert {spelling: canonical_key(spelling) for spelling in GOLDEN_KEYS} == GOLDEN_KEYS


def test_the_first_terms_are_the_earlier_synonym_groups_in_order() -> None:
    names = [term.name for term in TERMS[:26]]
    assert names[0] == "Kubernetes"
    assert names[-1] == "CI/CD"
    assert {spelling for term in TERMS[:26] for spelling in term.spellings} == set(GOLDEN_KEYS)


def test_cv_evidence_reexports_the_taxonomy_matching() -> None:
    assert evidence.canonical_key is canonical_key
    assert evidence.mentions is mentions


@pytest.mark.parametrize(
    ("spelling", "canonical"),
    [
        ("k8s", "Kubernetes"),
        ("Large Language Models", "LLMs"),
        ("Golang", "Go"),
        ("Postgres", "PostgreSQL"),
        ("apprentissage automatique", "Machine Learning"),
        ("Python3", "Python"),
        ("Apache Kafka", "Kafka"),
        ("W&B", "Weights & Biases"),
        ("RESTful", "REST APIs"),
        ("anglais", "English"),
    ],
)
def test_synonyms_share_one_canonical_term(spelling: str, canonical: str) -> None:
    assert canonical_key(spelling) == canonical_key(canonical)
    assert canonical_name(spelling) == canonical


def test_unknown_names_keep_their_own_key_and_display_name() -> None:
    assert find_term("Quantum Basket Weaving") is None
    assert canonical_key("Quantum Basket Weaving") == "quantum basket weaving"
    assert canonical_name("  Quantum Basket Weaving ") == "Quantum Basket Weaving"
    assert category_of("Quantum Basket Weaving") is None


@pytest.mark.parametrize(
    ("name", "category", "technical"),
    [
        ("PyTorch", Category.FRAMEWORK, True),
        ("Kubernetes", Category.DEVOPS, True),
        ("RAG", Category.AI_ML, True),
        ("Python", Category.PROGRAMMING_LANGUAGE, True),
        ("French", Category.SPOKEN_LANGUAGE, False),
        ("Fintech", Category.DOMAIN, False),
    ],
)
def test_terms_have_categories(name: str, category: Category, technical: bool) -> None:
    assert category_of(name) is category
    assert (category in TECH_CATEGORIES) is technical


def test_scanning_free_text_finds_safe_terms_only() -> None:
    text = (
        "Nova AI builds legal assistants with PyTorch and RAG pipelines on k8s. "
        "We go beyond expectations and react to change. A French company. "
        "Suivi du tableau de bord. Swift delivery."
    )

    assert [term.name for term in scan_terms(text)] == ["Kubernetes", "RAG", "PyTorch"]


def test_generic_terms_never_become_keywords() -> None:
    assert is_generic("AI")
    assert is_generic("intelligence artificielle")
    assert not is_generic("Generative AI")
    assert "AI" not in [term.name for term in scan_terms("An AI company building AI products")]


@pytest.mark.parametrize(
    ("text", "skill", "found"),
    [
        ("Built services in Go", "Go", True),
        ("Worked at Google", "Go", False),
        ("Queries in MySQL", "SQL", False),
        ("Repositories on GitHub", "Git", False),
        ("Deployed on k8s", "Kubernetes", True),
        ("Systèmes multi-agents", "Multi-agent systems", True),
        ("Model trained in C++ and C#", "C++", True),
    ],
)
def test_matching_respects_word_boundaries_and_synonyms(text: str, skill: str, found: bool) -> None:
    assert mentions(text, skill) is found


def test_a_spelling_can_belong_to_one_term_only() -> None:
    with pytest.raises(ValueError, match="belongs to both"):
        _index(
            (
                Term("Kubernetes", Category.DEVOPS, ("k8s",)),
                Term("K8s Platform", Category.DEVOPS, ("K8s",)),
            )
        )


def test_the_vocabulary_lists_every_spelling() -> None:
    spellings = vocabulary()
    assert "k8s" in spellings
    assert "PyTorch" in spellings
    assert len(spellings) == sum(len(term.spellings) for term in TERMS)
