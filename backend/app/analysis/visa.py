"""Visa / sponsorship classification (architecture §10).

Deterministic phrase rules (English, French, some German) find the sentences that state
sponsorship, rule it out, make it likely or offer relocation. The model's claim is accepted only
when its quote appears verbatim in the posting and actually talks about work authorisation.

Precedence: an explicit negative statement wins; then a confirmed one; then a likely one;
otherwise UNKNOWN. Relocation support is recorded but never implies sponsorship.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.analysis.schemas import VisaClaim, VisaEvidence, VisaResult
from app.analysis.types import VisaStatus
from app.jobs.hashing import normalize_text


def _patterns(*sources: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(source, re.IGNORECASE) for source in sources)


_NEGATIVE = _patterns(
    r"\bno\s+(visa\s+|work\s+permit\s+)?sponsorship\b",
    r"\b(unable|not\s+able)\s+to\s+(offer|provide|sponsor|support)\b",
    r"\b(cannot|can\s?not|can't|do\s+not|don't|does\s+not|doesn't|will\s+not|won't)\s+"
    r"(offer\s+|provide\s+|support\s+)?(visa\s+|work\s+permit\s+)?sponsor",
    r"\bsponsorship\s+(is\s+)?not\s+(available|offered|provided|possible)\b",
    r"\bmust\s+(already\s+)?(have|hold|possess)\s+(the\s+|a\s+)?(valid\s+)?"
    r"(right|authori[sz]ation|permission|work\s+permit|visa)\b[^.]{0,20}\bto\s+work\b",
    r"\bmust\s+(already\s+)?(have|hold|possess)\s+(the\s+|a\s+)?right\s+to\s+work\b",
    r"\bmust\s+be\s+(legally\s+)?(authori[sz]ed|eligible|entitled|permitted)\s+to\s+work\b",
    r"\b(without|not\s+requiring|no\s+need\s+for)\s+(visa\s+)?sponsorship\b",
    r"\b(EU|EEA|US|U\.S\.|UK)\s+(citizens|nationals|residents)\s+only\b",
    r"\bonly\s+(EU|EEA|US|UK)\s+(citizens|nationals|passport\s+holders)\b",
    r"\b(valid|existing|current)\s+work\s+(permit|authori[sz]ation|visa)\s+(is\s+)?(required|mandatory)\b",
    r"\bne\s+(pouvons|peut|proposons|propose|offrons|offre|parrainons|sponsorisons)\s+pas\b"
    r"[^.]{0,40}\b(visa|parrainage|sponsoring|sponsorisation|permis)",
    r"\b(pas|aucun)\s+(de\s+)?(parrainage|sponsoring|sponsorisation)\b",
    r"\bautorisation\s+de\s+travail\b[^.]{0,30}\b(requise|exigée|obligatoire|nécessaire)\b",
    r"\bkeine\s+(Visa-?)?(Unterstützung|Sponsoring|Sponsorship)\b",
    r"\bArbeitserlaubnis\s+(ist\s+)?(erforderlich|notwendig|vorausgesetzt)\b",
)
_POSITIVE = _patterns(
    r"\b(visa|work\s+permit|blue\s+card)\s+sponsorship\s+(is\s+)?"
    r"(available|offered|provided|possible|included)\b",
    r"\bsponsorship\s+(is\s+)?(available|offered|provided|included)\b",
    r"\bwe\s+(will\s+|can\s+|do\s+|happily\s+|gladly\s+)?sponsor\b",
    r"\b(offer|offers|provide|provides|including|includes)\s+(full\s+|complete\s+)?"
    r"(visa|work\s+permit|blue\s+card)\s+(sponsorship|support|assistance)\b",
    r"\b(visa|work\s+permit)\s+(support|assistance)\s+(is\s+)?(available|provided|offered|included)\b",
    r"\bvisa\s+and\s+relocation\s+(support|assistance|package)\b",
    r"\b(accompagnement|parrainage|sponsoring|prise\s+en\s+charge)\s+(au\s+|du\s+|de\s+|pour\s+le\s+)?"
    r"(visa|titre\s+de\s+séjour|permis\s+de\s+travail)\b",
    r"\bVisa-?(Unterstützung|Sponsoring)\s+(wird\s+)?(angeboten|geboten|möglich)\b",
)
_LIKELY = _patterns(
    r"\binternational\s+(candidates|applicants|talent|profiles)\s+(are\s+)?(welcome|encouraged)\b",
    r"\b(open\s+to|welcom\w*)\s+(international|non-EU|overseas|foreign|global)\s+"
    r"(candidates|applicants|talent)\b",
    r"\b(visa\s+)?sponsorship\s+(may|might|can|could)\s+be\s+"
    r"(available|considered|discussed|possible|offered|provided)\b",
    r"\bcase[- ]by[- ]case\b[^.]{0,40}\bsponsor",
    r"\bcandidatures\s+internationales\s+(bienvenues|acceptées|encouragées)\b",
)
_RELOCATION = _patterns(
    r"\brelocation\s+(support|package|assistance|bonus|allowance|budget|help|costs?)\b",
    r"\brelocation\s+to\s+[\w\s,-]{1,40}?\s(is\s+)?(provided|supported|covered|offered|available)\b",
    r"\b(help|support|assist)\s+(you\s+)?(with\s+)?(your\s+)?relocat",
    r"\b(aide|accompagnement|package|prime)\s+(à|a|de|au)\s+(la\s+)?"
    r"(relocalisation|relocation|mobilité|déménagement)\b",
    r"\bUmzugs(unterstützung|kosten|hilfe)\b",
)

# A claim of sponsorship (or of its absence) must talk about work authorisation.
_AUTHORISATION_WORDS = re.compile(
    r"visa|sponsor|work\s*permit|blue\s*card|employment\s+pass|right\s+to\s+work|authori[sz]|"
    r"eligib|citizen|national|permis|titre\s+de\s+séjour|parrain|autorisation\s+de\s+travail|"
    r"arbeitserlaubnis|aufenthalt",
    re.IGNORECASE,
)
_OPENNESS_WORDS = re.compile(
    r"international|worldwide|anywhere|global|overseas|abroad|foreign|non-eu|nationalit",
    re.IGNORECASE,
)
_RELOCATION_WORDS = re.compile(r"relocat|déménag|mobilité|umzug", re.IGNORECASE)
_QUOTE_EDGES = "\"'“”‘’«»„ .,;:!?()[]"
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")
_SIGNAL_ORDER = {"NEGATIVE": 0, "POSITIVE": 1, "LIKELY": 2, "RELOCATION": 3}


@dataclass(frozen=True)
class VisaSignals:
    positive: tuple[str, ...] = ()
    likely: tuple[str, ...] = ()
    negative: tuple[str, ...] = ()
    relocation: tuple[str, ...] = ()


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text or "") if part.strip()]


def _matches(patterns: tuple[re.Pattern[str], ...], sentence: str) -> bool:
    return any(pattern.search(sentence) for pattern in patterns)


def find_visa_signals(text: str) -> VisaSignals:
    """Sentences of ``text`` stating sponsorship, its absence, openness or relocation."""
    positive: list[str] = []
    likely: list[str] = []
    negative: list[str] = []
    relocation: list[str] = []
    for sentence in split_sentences(text):
        # A negative sentence ("we do not offer visa sponsorship") also contains positive words:
        # it is classified negative only.
        if _matches(_NEGATIVE, sentence):
            negative.append(sentence)
        elif _matches(_POSITIVE, sentence):
            positive.append(sentence)
        elif _matches(_LIKELY, sentence):
            likely.append(sentence)
        if _matches(_RELOCATION, sentence):
            relocation.append(sentence)
    return VisaSignals(tuple(positive), tuple(likely), tuple(negative), tuple(relocation))


def _clean_quote(quote: str | None) -> str:
    return (quote or "").strip().strip(_QUOTE_EDGES)


def quote_in_text(quote: str | None, text: str) -> bool:
    """True when ``quote`` appears in ``text`` (case, spacing and quotation marks ignored)."""
    needle = normalize_text(_clean_quote(quote))
    return bool(needle) and needle in normalize_text(text)


def merge_visa(
    signals: VisaSignals,
    claim: VisaClaim | None,
    *,
    job_text: str,
    sponsorship_needed: bool | None,
    country_code: str | None,
) -> VisaResult:
    evidence: list[VisaEvidence] = []
    seen: set[tuple[str, str]] = set()
    discarded: list[str] = []

    def add(quote: str, signal: str, source: str) -> None:
        key = (normalize_text(_clean_quote(quote)), signal)
        if key not in seen:
            seen.add(key)
            evidence.append(VisaEvidence(quote=quote, signal=signal, source=source))  # type: ignore[arg-type]

    for quote in signals.negative:
        add(quote, "NEGATIVE", "RULE")
    for quote in signals.positive:
        add(quote, "POSITIVE", "RULE")
    for quote in signals.likely:
        add(quote, "LIKELY", "RULE")
    for quote in signals.relocation:
        add(quote, "RELOCATION", "RULE")

    if claim is not None:
        signal = {
            VisaStatus.SPONSORSHIP_NOT_AVAILABLE: "NEGATIVE",
            VisaStatus.SPONSORSHIP_CONFIRMED: "POSITIVE",
            VisaStatus.SPONSORSHIP_LIKELY: "LIKELY",
        }.get(claim.status)
        quote = _clean_quote(claim.quote)
        if signal is not None and quote:
            if not quote_in_text(quote, job_text):
                discarded.append(claim.quote or quote)
            elif _AUTHORISATION_WORDS.search(quote) or (
                signal == "LIKELY" and _OPENNESS_WORDS.search(quote)
            ):
                add(quote, signal, "LLM")
            elif _RELOCATION_WORDS.search(quote):
                add(quote, "RELOCATION", "LLM")  # relocation is never sponsorship
        relocation_quote = _clean_quote(claim.relocation_quote)
        if relocation_quote:
            if not quote_in_text(relocation_quote, job_text):
                discarded.append(claim.relocation_quote or relocation_quote)
            elif _RELOCATION_WORDS.search(relocation_quote):
                add(relocation_quote, "RELOCATION", "LLM")

    evidence.sort(key=lambda item: (_SIGNAL_ORDER[item.signal], item.source != "RULE"))
    signals_found = {item.signal for item in evidence}
    if "NEGATIVE" in signals_found:
        status = VisaStatus.SPONSORSHIP_NOT_AVAILABLE
    elif "POSITIVE" in signals_found:
        status = VisaStatus.SPONSORSHIP_CONFIRMED
    elif "LIKELY" in signals_found:
        status = VisaStatus.SPONSORSHIP_LIKELY
    else:
        status = VisaStatus.SPONSORSHIP_UNKNOWN
    return VisaResult(
        status=status,
        evidence=evidence,
        relocation_available="RELOCATION" in signals_found,
        country_code=country_code,
        sponsorship_needed=sponsorship_needed,
        conflicting="NEGATIVE" in signals_found and bool({"POSITIVE", "LIKELY"} & signals_found),
        discarded_quotes=discarded,
    )
