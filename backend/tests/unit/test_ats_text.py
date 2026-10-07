"""Text primitives of the truthfulness guard: numbers, stems, content terms and proper nouns."""

from decimal import Decimal

import pytest

from app.ats.text import (
    content_terms,
    proper_noun_tokens,
    quantities,
    quantity_supported,
    stem,
    token_in,
)

pytestmark = pytest.mark.feature("cv-tailoring")


def _values(text: str) -> list[tuple[str, str | None]]:
    return [(str(quantity.value), quantity.unit) for quantity in quantities(text)]


@pytest.mark.parametrize(
    "text",
    ["serving 2,000 users", "for 2000 users", "2K users", "2 000 users", "2,000+ users"],
)
def test_thousands_are_one_value_whatever_the_notation(text: str) -> None:
    (quantity,) = quantities(text)
    assert quantity.value == Decimal(2000)
    assert quantity.unit is None
    assert quantity.noun == "user"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("35%", [("35", "%")]),
        ("35 percent", [("35", "%")]),
        ("35 per cent", [("35", "%")]),
        ("35 %", [("35", "%")]),
        ("35", [("35", None)]),
        ("1,5 ans", [("1.5", None)]),
        ("2.000 utilisateurs", [("2000", None)]),
        ("Python 3.11", [("3.11", None)]),
        ("20-30% faster", [("20", "%"), ("30", "%")]),
        ("$2M budget", [("2000000", "$")]),
        ("2M€ budget", [("2000000", "€")]),
        ("3x faster", [("3", "x")]),
        ("3\u00d7 faster", [("3", "x")]),
        ("two thousand users", [("2000", None)]),
        ("twenty-five engineers", [("25", None)]),
        ("ranked 1st", [("1", "ordinal")]),
        ("Sept 2019", [("2019", None)]),
        ("one model and un projet", []),
    ],
)
def test_numbers_are_normalised(text: str, expected: list[tuple[str, str | None]]) -> None:
    assert _values(text) == expected


SOURCE = "Designed a RAG platform with LangGraph and a vector database serving 2,000 users."


@pytest.mark.parametrize(
    ("text", "supported"),
    [
        ("A RAG platform for 2K users", True),
        ("Serving 2,000+ users", True),
        ("Serving 2,000+ active users", False),  # a qualifier the source does not state
        ("Serving 2,000 teams", False),
        ("Serving 3,000 users", False),
    ],
)
def test_a_number_needs_the_same_value_unit_and_noun_in_a_source(
    text: str, supported: bool
) -> None:
    (quantity,) = quantities(text)
    assert quantity_supported(quantity, [SOURCE]) is supported


def test_percentages_are_not_plain_numbers() -> None:
    sources = ["Reduced inference latency by 35%."]
    (percent,) = quantities("Cut latency by 35 percent")
    (plain,) = quantities("Cut latency by 35")
    (other,) = quantities("Cut latency by 40%")

    assert quantity_supported(percent, sources)
    assert not quantity_supported(plain, sources)
    assert not quantity_supported(other, sources)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("designed", "design"),
        ("pipelines", "pipeline"),
        ("mentored", "mentor"),
        ("evaluate", "evaluation"),
        ("Deploying", "deployed"),
    ],
)
def test_word_forms_share_a_stem(first: str, second: str) -> None:
    assert stem(first) == stem(second)


def test_content_terms_ignore_stopwords_and_know_synonyms() -> None:
    assert content_terms("Design RAG pipelines") == content_terms(
        "Designed a retrieval augmented generation pipeline"
    )
    assert content_terms("Design RAG pipelines") == {"design", "pipelin", "term:rag"}
    assert "the" not in content_terms("Ship the product to the users")


def test_proper_nouns_are_found_by_their_shape() -> None:
    text = (
        "Built pipelines on Snowflake with PyTorch, S3, C++ and .NET. "
        "Deployed with Node.js for 2K users, 3x faster, ranked 1st."
    )

    assert proper_noun_tokens(text) == ["C++", ".NET", "PyTorch", "S3", "Snowflake", "Node.js"]


def test_the_first_word_of_a_sentence_is_not_a_name_by_shape() -> None:
    assert proper_noun_tokens("Designed a platform. Reduced latency.") == []
    assert proper_noun_tokens("Designed a platform for Acme.") == ["Acme"]


@pytest.mark.parametrize(
    ("token", "text", "found"),
    [
        ("PyTorch", "Trained models in pytorch", True),
        (".NET", "Worked with .NET services", True),
        ("Java", "Wrote JavaScript", False),
        ("Acme", "Acme Analytics", True),
    ],
)
def test_tokens_are_matched_as_whole_words(token: str, text: str, found: bool) -> None:
    assert token_in(token, [text]) is found
