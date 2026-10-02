"""Visa / sponsorship classification: deterministic phrase rules, quote verification and the merge
with Claude's claim. Relocation never implies sponsorship; explicit negatives always win."""

import pytest

from app.analysis.schemas import VisaClaim
from app.analysis.types import VisaStatus
from app.analysis.visa import find_visa_signals, merge_visa, quote_in_text

pytestmark = pytest.mark.feature("visa-classification")

CONFIRMED = VisaStatus.SPONSORSHIP_CONFIRMED
LIKELY = VisaStatus.SPONSORSHIP_LIKELY
UNKNOWN = VisaStatus.SPONSORSHIP_UNKNOWN
NOT_AVAILABLE = VisaStatus.SPONSORSHIP_NOT_AVAILABLE


def _classify(text: str, claim: VisaClaim | None = None, **kwargs: object):  # type: ignore[no-untyped-def]
    return merge_visa(
        find_visa_signals(text),
        claim,
        job_text=text,
        sponsorship_needed=kwargs.get("sponsorship_needed", True),  # type: ignore[arg-type]
        country_code=kwargs.get("country_code", "FR"),  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("text", "status", "quote"),
    [
        (
            "Build RAG systems. Visa sponsorship is available for non-EU candidates.",
            CONFIRMED,
            "Visa sponsorship is available for non-EU candidates.",
        ),
        ("We sponsor work visas.", CONFIRMED, "We sponsor work visas."),
        ("We offer full visa sponsorship and a relocation package.", CONFIRMED, None),
        ("Accompagnement visa et aide à la relocalisation.", CONFIRMED, None),
        ("We are unable to offer visa sponsorship.", NOT_AVAILABLE, None),
        (
            "Work on ranking models. Candidates must be authorized to work in the United States.",
            NOT_AVAILABLE,
            "Candidates must be authorized to work in the United States.",
        ),
        ("You must already have the right to work in Germany.", NOT_AVAILABLE, None),
        ("Applicants must be eligible to work in the EU without sponsorship.", NOT_AVAILABLE, None),
        ("We do not sponsor visas for this role.", NOT_AVAILABLE, None),
        ("Nous ne proposons pas de parrainage de visa.", NOT_AVAILABLE, None),
        ("Une autorisation de travail valide est requise.", NOT_AVAILABLE, None),
        ("International candidates welcome.", LIKELY, "International candidates welcome."),
        ("Sponsorship may be considered for exceptional candidates.", LIKELY, None),
        ("Build perception models for warehouse robots.", UNKNOWN, None),
    ],
)
def test_explicit_statements_are_classified_with_a_verbatim_quote(
    text: str, status: VisaStatus, quote: str | None
) -> None:
    result = _classify(text)

    assert result.status is status
    if status is UNKNOWN:
        assert result.evidence == []
    else:
        assert result.evidence, "a classification must carry its evidence"
        assert all(item.quote in text for item in result.evidence)  # verbatim
    if quote is not None:
        assert result.evidence[0].quote == quote


@pytest.mark.parametrize(
    "text",
    [
        "Relocation support to Amsterdam is provided.",
        "Relocation package to Paris.",
        "Relocation to Dubai is provided.",
        "Aide à la relocalisation proposée.",
    ],
)
def test_relocation_support_alone_never_implies_sponsorship(text: str) -> None:
    result = _classify(text)

    assert result.status is UNKNOWN
    assert result.relocation_available is True
    assert [item.signal for item in result.evidence] == ["RELOCATION"]


def test_explicit_negatives_win_over_positive_statements() -> None:
    text = (
        "Visa sponsorship is available. "
        "Candidates must already have the right to work in the EU."
    )

    result = _classify(text)

    assert result.status is NOT_AVAILABLE
    assert result.conflicting is True
    assert {item.signal for item in result.evidence} == {"POSITIVE", "NEGATIVE"}


def test_a_verified_claim_from_claude_is_accepted() -> None:
    text = "We are happy to support Blue Card applications for this position."
    claim = VisaClaim(
        status=CONFIRMED,
        quote="We are happy to support Blue Card applications for this position.",
        relocation_quote=None,
    )

    result = _classify(text, claim)

    assert result.status is CONFIRMED
    assert result.evidence[0].source == "LLM"


def test_an_invented_quote_is_discarded() -> None:
    text = "Build RAG systems with LangGraph."
    claim = VisaClaim(
        status=CONFIRMED, quote="Visa sponsorship is available.", relocation_quote=None
    )

    result = _classify(text, claim)

    assert result.status is UNKNOWN
    assert result.evidence == []
    assert result.discarded_quotes == ["Visa sponsorship is available."]


def test_a_relocation_quote_presented_as_sponsorship_is_not_sponsorship() -> None:
    text = "Relocation package to Paris."
    claim = VisaClaim(status=CONFIRMED, quote="Relocation package to Paris.", relocation_quote=None)

    result = _classify(text, claim)

    assert result.status is UNKNOWN
    assert result.relocation_available is True


def test_rules_win_when_claude_misses_a_negative_statement() -> None:
    text = "We are unable to offer visa sponsorship."
    claim = VisaClaim(status=UNKNOWN, quote=None, relocation_quote=None)

    assert _classify(text, claim).status is NOT_AVAILABLE


def test_the_result_records_whether_the_candidate_needs_sponsorship() -> None:
    result = _classify("We sponsor work visas.", sponsorship_needed=False, country_code="TN")

    assert (result.sponsorship_needed, result.country_code) == (False, "TN")


@pytest.mark.parametrize(
    ("quote", "found"),
    [
        ("visa SPONSORSHIP is available", True),
        ("“Visa sponsorship is available.”", True),
        ("Visa   sponsorship\nis available", True),
        ("Visa sponsorship is guaranteed", False),
        ("", False),
    ],
)
def test_quotes_are_verified_against_the_posting(quote: str, found: bool) -> None:
    assert quote_in_text(quote, "Great team. Visa sponsorship is available. Apply now.") is found
