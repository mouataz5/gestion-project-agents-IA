"""Skills taxonomy: canonical names, synonyms (EN/FR/DE) and categories.

The single source of truth for skill matching in the CV evidence (Phase 2), the job analysis
(Phase 4) and the ATS engine (Phase 5).

* The first spelling of a term is its display name. ``canonical_key`` maps every spelling of a
  term to the key of that name (case, accents, separators and a final plural are ignored).
* Matching (``mentions``) is case-insensitive except for names of one or two characters ("Go",
  "R", "ML"), accent-insensitive, respects word boundaries ("Go" never matches "Google") and
  knows every spelling of a term ("k8s" -> Kubernetes).
* ``scan``: whether the term may be found by scanning free text. Ambiguous names ("Go", "R",
  "Swift", "Helm", "Tableau" in French text) count only where a posting or a CV lists them by
  name, never when they merely appear in prose.
* Generic terms ("AI", "IA") never become ATS keywords: every posting of this project mentions
  them.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache


class Category(StrEnum):
    PROGRAMMING_LANGUAGE = "programming_language"
    FRAMEWORK = "framework"
    AI_ML = "ai_ml"
    DATA = "data"
    DATABASE = "database"
    CLOUD = "cloud"
    DEVOPS = "devops"
    TOOL = "tool"
    METHODOLOGY = "methodology"
    SPOKEN_LANGUAGE = "spoken_language"
    DOMAIN = "domain"
    SOFT_SKILL = "soft_skill"


# Technical skills: the ATS "skills" component scores these (listed and demonstrated).
TECH_CATEGORIES: frozenset[Category] = frozenset(
    {
        Category.PROGRAMMING_LANGUAGE,
        Category.FRAMEWORK,
        Category.AI_ML,
        Category.DATA,
        Category.DATABASE,
        Category.CLOUD,
        Category.DEVOPS,
        Category.TOOL,
        Category.METHODOLOGY,
    }
)

# Skills-section labels a tailored CV may use (besides the labels of the master CV).
CATEGORY_LABELS: dict[Category, str] = {
    Category.PROGRAMMING_LANGUAGE: "Programming languages",
    Category.FRAMEWORK: "Frameworks & libraries",
    Category.AI_ML: "AI & machine learning",
    Category.DATA: "Data",
    Category.DATABASE: "Databases",
    Category.CLOUD: "Cloud",
    Category.DEVOPS: "DevOps & MLOps",
    Category.TOOL: "Tools",
    Category.METHODOLOGY: "Methods",
    Category.SPOKEN_LANGUAGE: "Languages",
    Category.DOMAIN: "Domains",
    Category.SOFT_SKILL: "Soft skills",
}


@dataclass(frozen=True)
class Term:
    name: str
    category: Category
    aliases: tuple[str, ...] = ()
    scan: bool = True

    @property
    def spellings(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


_C = Category

# The first 26 terms are the synonym groups of Phases 2-4: their spellings and order are pinned by
# a test (tests/unit/test_ats_taxonomy.py) because stored skill keys depend on them.
TERMS: tuple[Term, ...] = (
    Term("Kubernetes", _C.DEVOPS, ("k8s",)),
    Term(
        "LLMs",
        _C.AI_ML,
        ("LLM", "large language model", "grand modèle de langage", "grands modèles de langage"),
    ),
    Term("RAG", _C.AI_ML, ("retrieval augmented generation",)),
    Term("Machine Learning", _C.AI_ML, ("ML", "apprentissage automatique")),
    Term(
        "Deep Learning",
        _C.AI_ML,
        ("neural network", "apprentissage profond", "réseaux de neurones"),
    ),
    Term(
        "NLP",
        _C.AI_ML,
        ("natural language processing", "traitement automatique du langage", "TALN"),
    ),
    Term("Computer Vision", _C.AI_ML, ("vision par ordinateur",)),
    Term(
        "Agentic AI",
        _C.AI_ML,
        (
            "agentic",
            "AI agent",
            "LLM agent",
            "autonomous agent",
            "agents IA",
            "agent IA",
            "agents LLM",
            "agent LLM",
            "IA agentique",
        ),
    ),
    Term("Multi-agent systems", _C.AI_ML, ("multi-agent", "multi agents", "systèmes multi-agents")),
    Term("MCP", _C.AI_ML, ("Model Context Protocol",)),
    Term(
        "Vector databases",
        _C.DATABASE,
        (
            "vector database",
            "vector DB",
            "vector store",
            "vector search",
            "base de données vectorielle",
            "bases de données vectorielles",
        ),
    ),
    Term(
        "Time-series analysis",
        _C.DATA,
        ("time series", "séries temporelles", "série temporelle"),
    ),
    Term("MLOps", _C.AI_ML, ("ML Ops",)),
    Term("Generative AI", _C.AI_ML, ("GenAI", "Gen AI", "IA générative")),
    Term("GCP", _C.CLOUD, ("Google Cloud", "Google Cloud Platform")),
    Term("AWS", _C.CLOUD, ("Amazon Web Services",)),
    Term("Azure", _C.CLOUD, ("Microsoft Azure",)),
    Term("Spark", _C.DATA, ("Apache Spark", "PySpark")),
    Term("Scikit-learn", _C.FRAMEWORK, ("sklearn",)),
    Term("PostgreSQL", _C.DATABASE, ("Postgres",)),
    Term("JavaScript", _C.PROGRAMMING_LANGUAGE, ("JS",)),
    Term("TypeScript", _C.PROGRAMMING_LANGUAGE, ("TS",)),
    Term("Node.js", _C.FRAMEWORK, ("NodeJS",)),
    Term("Go", _C.PROGRAMMING_LANGUAGE, ("Golang",), scan=False),
    Term("Hugging Face", _C.FRAMEWORK, ("HuggingFace",)),
    Term("CI/CD", _C.DEVOPS, ("CICD", "continuous integration")),
    # --- programming languages -------------------------------------------------------------
    Term("Python", _C.PROGRAMMING_LANGUAGE, ("Python3",)),
    Term("Java", _C.PROGRAMMING_LANGUAGE),
    Term("Scala", _C.PROGRAMMING_LANGUAGE),
    Term("C++", _C.PROGRAMMING_LANGUAGE, ("cpp",)),
    Term("C#", _C.PROGRAMMING_LANGUAGE, ("C sharp", "csharp")),
    Term("C", _C.PROGRAMMING_LANGUAGE, scan=False),
    Term("R", _C.PROGRAMMING_LANGUAGE, scan=False),
    Term("Rust", _C.PROGRAMMING_LANGUAGE),
    Term("Julia", _C.PROGRAMMING_LANGUAGE, scan=False),
    Term("MATLAB", _C.PROGRAMMING_LANGUAGE),
    Term("SQL", _C.PROGRAMMING_LANGUAGE),
    Term("Bash", _C.PROGRAMMING_LANGUAGE, ("shell scripting",)),
    Term("Kotlin", _C.PROGRAMMING_LANGUAGE),
    Term("Swift", _C.PROGRAMMING_LANGUAGE, scan=False),
    Term("PHP", _C.PROGRAMMING_LANGUAGE),
    Term("Ruby", _C.PROGRAMMING_LANGUAGE, scan=False),
    # --- frameworks and libraries ------------------------------------------------------------
    Term("PyTorch", _C.FRAMEWORK),
    Term("TensorFlow", _C.FRAMEWORK),
    Term("Keras", _C.FRAMEWORK),
    Term("JAX", _C.FRAMEWORK),
    Term("Pandas", _C.FRAMEWORK),
    Term("NumPy", _C.FRAMEWORK),
    Term("SciPy", _C.FRAMEWORK),
    Term("Matplotlib", _C.FRAMEWORK),
    Term("XGBoost", _C.FRAMEWORK),
    Term("LightGBM", _C.FRAMEWORK),
    Term("LangChain", _C.FRAMEWORK),
    Term("LangGraph", _C.FRAMEWORK),
    Term("LlamaIndex", _C.FRAMEWORK, ("Llama Index",)),
    Term("DSPy", _C.FRAMEWORK),
    Term("CrewAI", _C.FRAMEWORK, ("Crew AI",)),
    Term("AutoGen", _C.FRAMEWORK),
    Term("Semantic Kernel", _C.FRAMEWORK),
    Term("Haystack", _C.FRAMEWORK, scan=False),
    Term("OpenCV", _C.FRAMEWORK),
    Term("spaCy", _C.FRAMEWORK),
    Term("NLTK", _C.FRAMEWORK),
    Term("FastAPI", _C.FRAMEWORK),
    Term("Flask", _C.FRAMEWORK),
    Term("Django", _C.FRAMEWORK),
    Term("Streamlit", _C.FRAMEWORK),
    Term("Gradio", _C.FRAMEWORK),
    Term("Pydantic", _C.FRAMEWORK),
    Term("Celery", _C.FRAMEWORK),
    Term("Ray", _C.FRAMEWORK, scan=False),
    Term("Dask", _C.FRAMEWORK),
    Term("Polars", _C.FRAMEWORK),
    Term("ONNX", _C.FRAMEWORK),
    Term("TensorRT", _C.FRAMEWORK),
    Term("vLLM", _C.FRAMEWORK),
    Term("React", _C.FRAMEWORK, ("React.js", "ReactJS"), scan=False),
    Term("Angular", _C.FRAMEWORK, scan=False),
    Term("Vue.js", _C.FRAMEWORK, ("VueJS",)),
    Term("Spring Boot", _C.FRAMEWORK),
    Term(".NET", _C.FRAMEWORK, ("dotnet",)),
    # --- AI and machine learning -----------------------------------------------------------
    Term("Prompt engineering", _C.AI_ML, ("prompt design",)),
    Term("Fine-tuning", _C.AI_ML, ("fine tuning", "finetuning")),
    Term("LoRA", _C.AI_ML),
    Term("PEFT", _C.AI_ML),
    Term("RLHF", _C.AI_ML),
    Term("Reinforcement learning", _C.AI_ML, ("RL", "apprentissage par renforcement")),
    Term("Transformers", _C.AI_ML),
    Term("BERT", _C.AI_ML),
    Term("Embeddings", _C.AI_ML),
    Term("Semantic search", _C.AI_ML, ("recherche sémantique",)),
    Term("Information retrieval", _C.AI_ML),
    Term(
        "Recommender systems",
        _C.AI_ML,
        ("recommendation systems", "recommendation engine", "systèmes de recommandation"),
    ),
    Term("Anomaly detection", _C.AI_ML, ("détection d'anomalies",)),
    Term("Forecasting", _C.AI_ML, ("prévision", "prévisions")),
    Term("Statistics", _C.AI_ML, ("statistiques", "statistical analysis")),
    Term("Feature engineering", _C.AI_ML),
    Term("Speech recognition", _C.AI_ML, ("ASR", "reconnaissance vocale")),
    Term("Object detection", _C.AI_ML, ("détection d'objets",)),
    Term("Image segmentation", _C.AI_ML, ("segmentation d'images",)),
    Term("OCR", _C.AI_ML),
    Term("Sentiment analysis", _C.AI_ML, ("analyse de sentiment",)),
    Term("Named entity recognition", _C.AI_ML, ("NER",)),
    Term("Diffusion models", _C.AI_ML),
    Term("Knowledge graphs", _C.AI_ML, ("knowledge graph", "graphes de connaissances")),
    Term("Graph neural networks", _C.AI_ML, ("GNN",)),
    Term("Explainable AI", _C.AI_ML, ("XAI",)),
    Term("Responsible AI", _C.AI_ML),
    Term("Function calling", _C.AI_ML, ("tool calling",)),
    Term("Quantization", _C.AI_ML, ("quantisation",)),
    Term("Chatbots", _C.AI_ML, ("conversational AI", "agent conversationnel")),
    # --- data --------------------------------------------------------------------------------
    Term("Data science", _C.DATA, ("science des données",)),
    Term("Data engineering", _C.DATA),
    Term("Data pipelines", _C.DATA, ("pipelines de données",)),
    Term("ETL", _C.DATA, ("ELT",)),
    Term("Data visualization", _C.DATA, ("data visualisation", "dataviz")),
    Term("Big Data", _C.DATA),
    Term("Data warehousing", _C.DATA, ("data warehouse",)),
    Term("Data modeling", _C.DATA, ("data modelling",)),
    Term("Airflow", _C.DATA, ("Apache Airflow",)),
    Term("dbt", _C.DATA),
    Term("Kafka", _C.DATA, ("Apache Kafka",)),
    Term("Hadoop", _C.DATA),
    Term("Databricks", _C.DATA),
    Term("Snowflake", _C.DATA),
    Term("BigQuery", _C.DATA),
    Term("Redshift", _C.DATA, ("Amazon Redshift",)),
    Term("Tableau", _C.DATA, scan=False),
    Term("Power BI", _C.DATA, ("PowerBI",)),
    Term("Looker", _C.DATA),
    # --- databases ---------------------------------------------------------------------------
    Term("MySQL", _C.DATABASE),
    Term("MongoDB", _C.DATABASE, ("Mongo",)),
    Term("Redis", _C.DATABASE),
    Term("Elasticsearch", _C.DATABASE, ("Elastic search",)),
    Term("OpenSearch", _C.DATABASE),
    Term("SQLite", _C.DATABASE),
    Term("SQL Server", _C.DATABASE, ("MSSQL",)),
    Term("Oracle", _C.DATABASE, scan=False),
    Term("Cassandra", _C.DATABASE, scan=False),
    Term("Neo4j", _C.DATABASE),
    Term("DynamoDB", _C.DATABASE),
    Term("Pinecone", _C.DATABASE),
    Term("Weaviate", _C.DATABASE),
    Term("Qdrant", _C.DATABASE),
    Term("Milvus", _C.DATABASE),
    Term("ChromaDB", _C.DATABASE, ("Chroma DB",)),
    Term("FAISS", _C.DATABASE),
    Term("pgvector", _C.DATABASE),
    # --- cloud -------------------------------------------------------------------------------
    Term("SageMaker", _C.CLOUD, ("Amazon SageMaker", "AWS SageMaker")),
    Term("Amazon Bedrock", _C.CLOUD, ("AWS Bedrock",)),
    Term("Vertex AI", _C.CLOUD, ("Google Vertex AI",)),
    Term("Azure OpenAI", _C.CLOUD),
    Term("Azure Machine Learning", _C.CLOUD, ("Azure ML",)),
    Term("AWS Lambda", _C.CLOUD),
    Term("Amazon S3", _C.CLOUD, ("S3",)),
    Term("EC2", _C.CLOUD, ("Amazon EC2",)),
    Term("Serverless", _C.CLOUD),
    # --- DevOps and MLOps --------------------------------------------------------------------
    Term("Docker", _C.DEVOPS),
    Term("Terraform", _C.DEVOPS),
    Term("Ansible", _C.DEVOPS),
    Term("Helm", _C.DEVOPS, scan=False),
    Term("GitHub Actions", _C.DEVOPS),
    Term("GitLab CI", _C.DEVOPS, ("GitLab CI/CD",)),
    Term("Jenkins", _C.DEVOPS),
    Term("Linux", _C.DEVOPS),
    Term("Prometheus", _C.DEVOPS),
    Term("Grafana", _C.DEVOPS),
    Term("MLflow", _C.DEVOPS),
    Term("Kubeflow", _C.DEVOPS),
    Term("DVC", _C.DEVOPS),
    Term("Weights & Biases", _C.DEVOPS, ("W&B", "wandb")),
    Term("Microservices", _C.DEVOPS, ("micro-services",)),
    Term("REST APIs", _C.DEVOPS, ("REST API", "RESTful", "API REST", "APIs REST")),
    Term("GraphQL", _C.DEVOPS),
    Term("gRPC", _C.DEVOPS),
    # --- tools -------------------------------------------------------------------------------
    Term("Git", _C.TOOL),
    Term("GitHub", _C.TOOL),
    Term("GitLab", _C.TOOL),
    Term("Jira", _C.TOOL),
    Term("Jupyter", _C.TOOL, ("Jupyter Notebook",)),
    Term("Excel", _C.TOOL, scan=False),
    Term("OpenAI", _C.TOOL, ("OpenAI API",)),
    Term("LangSmith", _C.TOOL),
    Term("Ollama", _C.TOOL),
    Term("CUDA", _C.TOOL),
    # --- methodologies -----------------------------------------------------------------------
    Term("Agile", _C.METHODOLOGY),
    Term("Scrum", _C.METHODOLOGY),
    Term("Kanban", _C.METHODOLOGY),
    Term("DevOps", _C.METHODOLOGY),
    Term("TDD", _C.METHODOLOGY, ("test-driven development",)),
    Term("A/B testing", _C.METHODOLOGY, ("A/B tests", "AB testing")),
    Term("Unit testing", _C.METHODOLOGY, ("unit tests",)),
    Term("Code review", _C.METHODOLOGY),
    Term("System design", _C.METHODOLOGY),
    Term("Software architecture", _C.METHODOLOGY, ("architecture logicielle",)),
    # --- spoken languages (taken from the posting's language list, never scanned) ------------
    Term("English", _C.SPOKEN_LANGUAGE, ("anglais", "Englisch"), scan=False),
    Term(
        "French",
        _C.SPOKEN_LANGUAGE,
        ("français", "francais", "Französisch"),
        scan=False,
    ),
    Term("German", _C.SPOKEN_LANGUAGE, ("allemand", "Deutsch"), scan=False),
    Term("Arabic", _C.SPOKEN_LANGUAGE, ("arabe", "Arabisch"), scan=False),
    Term("Spanish", _C.SPOKEN_LANGUAGE, ("espagnol", "español", "Spanisch"), scan=False),
    Term("Italian", _C.SPOKEN_LANGUAGE, ("italien", "italiano", "Italienisch"), scan=False),
    Term("Dutch", _C.SPOKEN_LANGUAGE, ("néerlandais", "Nederlands", "Niederländisch"), scan=False),
    Term("Portuguese", _C.SPOKEN_LANGUAGE, ("portugais", "português"), scan=False),
    # --- domains and soft skills (only where listed by name) ---------------------------------
    Term("Fintech", _C.DOMAIN, scan=False),
    Term("Healthcare", _C.DOMAIN, ("healthtech",), scan=False),
    Term("E-commerce", _C.DOMAIN, ("ecommerce",), scan=False),
    Term("Cybersecurity", _C.DOMAIN, ("cyber security", "cybersécurité"), scan=False),
    Term("Robotics", _C.DOMAIN, ("robotique",), scan=False),
    Term("Legal tech", _C.DOMAIN, ("legaltech",), scan=False),
    Term("Communication", _C.SOFT_SKILL, scan=False),
    Term("Teamwork", _C.SOFT_SKILL, ("team work", "travail en équipe"), scan=False),
    Term(
        "Problem solving",
        _C.SOFT_SKILL,
        ("problem-solving", "résolution de problèmes"),
        scan=False,
    ),
)

# Mentioned by every posting of this project: never an ATS keyword.
GENERIC_TERMS: tuple[str, ...] = (
    "AI",
    "IA",
    "Artificial Intelligence",
    "Intelligence Artificielle",
)


def fold(text: str) -> str:
    """Accent-insensitive form that keeps the string length stable for ASCII input."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_skill(name: str) -> str:
    """Comparison key: case, accents, hyphens/underscores/slashes and a final plural ignored."""
    text = fold(name).casefold()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[\s\-_/]+", " ", text).strip()
    words = text.split(" ")
    last = words[-1]
    if len(last) > 3 and last.endswith("s") and not last.endswith(("ss", "us", "is")):
        words[-1] = last[:-1]
    return " ".join(words)


def _index(terms: Iterable[Term]) -> dict[str, Term]:
    index: dict[str, Term] = {}
    for term in terms:
        for spelling in term.spellings:
            key = normalize_skill(spelling)
            owner = index.setdefault(key, term)
            if owner is not term:
                raise ValueError(
                    f"Taxonomy spelling {spelling!r} belongs to both {owner.name!r} and "
                    f"{term.name!r}"
                )
    return index


_TERM_BY_KEY: dict[str, Term] = _index(TERMS)
_GENERIC_KEYS: frozenset[str] = frozenset(normalize_skill(name) for name in GENERIC_TERMS)


def find_term(name: str) -> Term | None:
    return _TERM_BY_KEY.get(normalize_skill(name))


def canonical_key(name: str) -> str:
    term = find_term(name)
    return normalize_skill(term.name) if term else normalize_skill(name)


def canonical_name(name: str) -> str:
    """Display name: the taxonomy name for known spellings, the given name otherwise."""
    term = find_term(name)
    return term.name if term else name.strip()


def category_of(name: str) -> Category | None:
    term = find_term(name)
    return term.category if term else None


def is_generic(name: str) -> bool:
    return normalize_skill(name) in _GENERIC_KEYS


def spellings(name: str) -> tuple[str, ...]:
    term = find_term(name)
    return tuple(dict.fromkeys((name, *(term.spellings if term else ()))))


def _spelling_pattern(spelling: str) -> str:
    tokens = [token for token in re.split(r"[\s\-_]+", fold(spelling).strip()) if token]
    last = tokens[-1]
    plural = ""
    if last.isalpha() and len(last) >= 3:
        if (
            len(last) > 3
            and last.lower().endswith("s")
            and not last.lower().endswith(("ss", "us", "is"))
        ):
            tokens[-1] = last[:-1]
        plural = "(?:e?s)?"
    body = r"[\s\-]*".join(re.escape(token) for token in tokens) + plural
    flags = "-i" if len(spelling.strip()) <= 2 else "i"
    return f"(?{flags}:{body})"


@lru_cache(maxsize=4096)
def skill_regex(name: str) -> re.Pattern[str]:
    """Matches any spelling of ``name`` in folded text (see ``fold``), on word boundaries."""
    alternatives = "|".join(_spelling_pattern(spelling) for spelling in spellings(name))
    return re.compile(rf"(?<![\w+#])(?:{alternatives})(?![\w+#])")


def mentions(text: str, skill: str) -> bool:
    return skill_regex(skill).search(fold(text)) is not None


def technologies_in(text: str, skills: Iterable[str]) -> list[str]:
    """The skills (as given, in order) that ``text`` mentions."""
    return [skill for skill in skills if mentions(text, skill)]


def scan_terms(text: str) -> list[Term]:
    """Taxonomy terms safe to detect in free text (``scan``) that ``text`` mentions."""
    folded = fold(text)
    return [term for term in TERMS if term.scan and skill_regex(term.name).search(folded)]


def vocabulary() -> tuple[str, ...]:
    """Every spelling of every term (the truthfulness guard checks generated text against it)."""
    return tuple(spelling for term in TERMS for spelling in term.spellings)
