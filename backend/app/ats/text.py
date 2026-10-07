"""Text primitives for the ATS engine and the truthfulness guard.

* ``quantities``: every number in a text as (value, unit, following noun), so "2K users",
  "2,000+ users" and "2 000 users" are the same claim, while "35" is not "35%".
* ``content_terms``: the meaningful words of a text, as Snowball (English) stems, with every
  taxonomy term counted as one synonym-aware token ("RAG" == "retrieval augmented generation").
* ``proper_noun_tokens``: names a generated text may only contain if its sources do (CamelCase,
  ACRONYMS, letter-digit mixes, C++/.NET/*.js, capitalised words inside a sentence).

Stemming is English-only but applied identically to both sides of every comparison.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

import snowballstemmer

from app.ats.taxonomy import TERMS, canonical_name, fold, normalize_skill, skill_regex

_STEMMER = snowballstemmer.stemmer("english")

STOPWORDS: frozenset[str] = frozenset(
    (
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "for",
        "from",
        "had",
        "has",
        "have",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "him",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "itself",
        "just",
        "me",
        "more",
        "most",
        "my",
        "no",
        "nor",
        "not",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "our",
        "ours",
        "out",
        "over",
        "own",
        "same",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "yours",
        "also",
        "across",
        "via",
        "per",
        "within",
        "without",
        "upon",
        "using",
        "etc",
        "e",
        "g",
        "ie",
        "eg",
        "le",
        "la",
        "les",
        "un",
        "une",
        "des",
        "du",
        "de",
        "d",
        "l",
        "et",
        "ou",
        "en",
        "dans",
        "sur",
        "pour",
        "par",
        "avec",
        "au",
        "aux",
        "ce",
        "cet",
        "cette",
        "ces",
        "qui",
        "que",
        "quoi",
        "dont",
        "est",
        "sont",
        "etre",
        "ete",
        "nous",
        "vous",
        "notre",
        "nos",
        "votre",
        "vos",
        "leur",
        "leurs",
        "il",
        "elle",
        "ils",
        "elles",
        "je",
        "j",
        "mon",
        "ma",
        "mes",
        "ton",
        "ta",
        "tes",
        "son",
        "sa",
        "ses",
        "se",
        "s",
        "n",
        "ne",
        "pas",
        "plus",
        "moins",
        "tres",
        "a",
        "y",
        "sans",
        "sous",
        "chez",
        "entre",
        "vers",
        "der",
        "die",
        "das",
        "und",
        "oder",
        "mit",
        "fur",
        "von",
        "zu",
        "im",
        "ein",
        "eine",
        "einen",
        "einem",
    )
)

# Generic verbs and nouns a rewording may introduce without making a claim ("design" is
# deliberately absent: "Designed" is a claim). Stems.
NEUTRAL_TERMS: frozenset[str] = frozenset(
    _STEMMER.stemWord(word)
    for word in (
        "build",
        "built",
        "develop",
        "create",
        "implement",
        "use",
        "work",
        "experience",
        "project",
        "system",
        "solution",
        "application",
        "deliver",
        "support",
        "help",
        "provide",
        "include",
        "enable",
        "handle",
        "make",
        "made",
        "set",
        "write",
        "wrote",
        "written",
        "run",
        "apply",
        "prepare",
        "team",
        "product",
        "feature",
        "tool",
        "process",
        "service",
        "platform",
        "task",
        "code",
        "environment",
        "various",
        "several",
        "key",
        "core",
        "new",
        "end",
        "user",
        "users",
        "production",
        "based",
        "construire",
        "developper",
        "creer",
        "mettre",
        "utiliser",
        "travailler",
        "projet",
        "systeme",
        "solution",
        "application",
        "livrer",
        "outil",
        "service",
        "plateforme",
        "equipe",
        "produit",
    )
)

_WORD = re.compile(r"[a-z][a-z0-9+#]*")


@lru_cache(maxsize=16384)
def stem(word: str) -> str:
    stemmed: str = _STEMMER.stemWord(fold(word).casefold())
    return stemmed


def words(text: str) -> list[str]:
    """Lower-case, accent-free word tokens (numbers excluded)."""
    return _WORD.findall(fold(text).casefold())


@lru_cache(maxsize=4096)
def content_terms(text: str) -> frozenset[str]:
    """Stems of the meaningful words of ``text``; taxonomy terms count as ``term:<key>``."""
    remaining = fold(text)
    found: set[str] = set()
    for term in TERMS:
        if not term.scan:
            continue
        regex = skill_regex(term.name)
        if regex.search(remaining):
            found.add("term:" + normalize_skill(term.name))
            remaining = regex.sub(" ", remaining)
    for word in words(remaining):
        if word in STOPWORDS or len(word) < 2:
            continue
        found.add(stem(word))
    return frozenset(found)


_TOKEN = re.compile(r"[^\W\d_][\w+#]*")


def term_words(text: str, terms: Iterable[str]) -> list[str]:
    """How ``text`` writes each of ``terms`` (content terms of ``text``), in order of appearance:
    "pipelin" -> "pipelines", "term:llm" -> "LLM". Terms ``text`` lacks are kept as they are."""
    wanted = set(terms)
    positions: dict[str, tuple[int, str]] = {}
    folded = fold(text)
    same_length = len(folded) == len(text)  # then a span of ``folded`` is a span of ``text``
    for term in wanted:
        if term.startswith("term:"):
            name = canonical_name(term.removeprefix("term:"))
            match = skill_regex(name).search(folded)
            if match:
                written = text[match.start() : match.end()] if same_length else name
                positions[term] = (match.start(), written)
    for match in _TOKEN.finditer(text):
        key = stem(match.group(0))
        if key in wanted and key not in positions:
            positions[key] = (match.start(), match.group(0))
    found = sorted(positions.values())
    return [word for _, word in found] + sorted(wanted - positions.keys())


# ---------------------------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Quantity:
    value: Decimal
    unit: str | None  # "%", "x", a currency symbol, "ordinal", or None
    noun: str | None  # stem of the word that follows, if any
    start: int  # position in the (folded) text
    end: int


_SEP = "[,.\u00a0\u202f' ]"
_NUMBER = re.compile(
    rf"""
    (?<![\w.,])
    (?P<cur>[$€£])?\s?
    (?P<num>\d{{1,3}}(?:{_SEP}\d{{3}})+(?![\d])(?:[.,]\d+)?|\d+(?:[.,]\d+)?)
    (?:\s?(?P<mult>k|K|M|bn|B)(?![A-Za-z]))?
    (?P<ord>st|nd|rd|th|er|ere|eme|e)?(?![A-Za-wyz0-9])
    (?P<plus>\+)?
    (?:\s?(?P<unit>%|percent(?![a-z])|per\s+cent(?![a-z])|pour\s?cent(?![a-z])|[x\u00d7](?![a-z])|[€£$]))?
    """,
    re.VERBOSE,
)
_MULTIPLIERS = {
    "k": Decimal(1_000),
    "K": Decimal(1_000),
    "M": Decimal(1_000_000),
    "bn": Decimal(1_000_000_000),
    "B": Decimal(1_000_000_000),
}
_RANGE = re.compile(r"\s*(?:[-–—]|to|a|à)\s*$")

_SMALL_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    # French "sept", "neuf" and "seize" are left out: also "Sept" (September), "new", "seize".
    "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "huit": 8, "dix": 10, "onze": 11,
    "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "vingt": 20, "vingts": 20,
    "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60,
}  # fmt: skip
_SCALE_WORDS = {"hundred": 100, "cent": 100, "cents": 100}
_BIG_WORDS = {
    "thousand": 1_000,
    "mille": 1_000,
    "million": 1_000_000,
    "millions": 1_000_000,
    "billion": 1_000_000_000,
    "milliard": 1_000_000_000,
    "milliards": 1_000_000_000,
}
_NUMBER_WORD = re.compile(
    r"(?<![a-z])(?:(?:"
    + "|".join(sorted({*_SMALL_WORDS, *_SCALE_WORDS, *_BIG_WORDS}, key=len, reverse=True))
    + r")(?:[\s-]+(?:and|et)?[\s-]*)?)+(?![a-z])"
)
_UNIT_WORDS = {"percent", "per", "cent", "pour", "x"}


def _decimal(raw: str) -> Decimal:
    digits = re.sub(rf"{_SEP}(?=\d{{3}}(?!\d))", "", raw)  # thousands separators
    return Decimal(digits.replace(",", "."))


def _canonical(value: Decimal) -> Decimal:
    """2000 rather than 2E+3, 1.5 rather than 1.50."""
    if value == value.to_integral_value():
        return value.quantize(Decimal(1))
    return value.normalize()


def _words_value(phrase: str) -> int | None:
    total = current = 0
    seen = False
    for token in re.split(r"[\s-]+", phrase):
        if token in ("and", "et", ""):
            continue
        if token in _SMALL_WORDS:
            current += _SMALL_WORDS[token]
        elif token in _SCALE_WORDS:
            current = max(current, 1) * _SCALE_WORDS[token]
        elif token in _BIG_WORDS:
            total += max(current, 1) * _BIG_WORDS[token]
            current = 0
        else:
            continue
        seen = True
    return total + current if seen else None


def _noun_after(text: str, end: int) -> str | None:
    for word in _WORD.findall(text[end : end + 60].casefold()):
        if word in STOPWORDS or word in _UNIT_WORDS:
            continue
        return stem(word)
    return None


def _unit(match: re.Match[str]) -> str | None:
    unit = match.group("unit")
    if unit:
        unit = unit.strip()
        if unit in ("x", "\u00d7"):
            return "x"
        if unit in ("€", "£", "$"):
            return unit
        return "%"
    if match.group("cur"):
        return match.group("cur")
    if match.group("ord"):
        return "ordinal"
    return None


def quantities(text: str) -> list[Quantity]:
    """Every number of ``text``: digits (thousands separators, decimals, k/M/bn, %, x, currency,
    ordinals, ranges) and EN/FR number words from two upwards."""
    folded = fold(text)
    found: list[Quantity] = []
    for match in _NUMBER.finditer(folded):
        value = _decimal(match.group("num"))
        mult = match.group("mult")
        if mult:
            value *= _MULTIPLIERS[mult]
        found.append(
            Quantity(
                value=_canonical(value),
                unit=_unit(match),
                noun=_noun_after(folded, match.end()),
                start=match.start(),
                end=match.end(),
            )
        )
    lowered = folded.casefold()
    digit_spans = [(quantity.start, quantity.end) for quantity in found]
    for match in _NUMBER_WORD.finditer(lowered):
        number = _words_value(match.group(0))
        if number is None or any(
            start < match.end() and match.start() < end for start, end in digit_spans
        ):
            continue  # "35 per cent": "cent" is the unit, not a hundred
        found.append(
            Quantity(
                value=Decimal(number),
                unit=None,
                noun=_noun_after(lowered, match.end()),
                start=match.start(),
                end=match.end(),
            )
        )
    found.sort(key=lambda quantity: quantity.start)
    # "20-30%": the unit of the second number applies to the first.
    for index in range(len(found) - 1):
        first, second = found[index], found[index + 1]
        between = folded[first.end : second.start]
        if first.unit is None and second.unit is not None and _RANGE.fullmatch(between):
            found[index] = Quantity(first.value, second.unit, second.noun, first.start, first.end)
    return found


_SENTENCE = re.compile(r"(?<=[.!?;])\s+|\n+")


def sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE.split(text) if part.strip()]


def quantity_supported(quantity: Quantity, sources: list[str]) -> bool:
    """A sentence of the sources states the same value and unit, and mentions the noun."""
    for source in sources:
        for sentence in sentences(source):
            for candidate in quantities(sentence):
                if candidate.value != quantity.value or candidate.unit != quantity.unit:
                    continue
                if quantity.noun is None or quantity.noun in content_terms(sentence):
                    return True
                if quantity.noun in {stem(word) for word in words(sentence)}:
                    return True
    return False


# ---------------------------------------------------------------------------------------------
# Proper nouns
# ---------------------------------------------------------------------------------------------

_SPECIAL = re.compile(r"C\+\+|C#|F#|\.NET\b|\b\w+\.js\b")
_CAMEL = re.compile(r"\b[A-Z]?[a-z]+(?:[A-Z][a-z0-9]*)+\b")
_ACRONYM = re.compile(r"\b[A-Z]{2,}s?\b")
_ALNUM = re.compile(r"\b(?=[A-Za-z]*\d)(?=\d*[A-Za-z])[A-Za-z0-9]{2,}\b")
_NUMERIC_TOKEN = re.compile(
    r"\d+(?:[.,]\d+)?(?:k|m|bn|b|x|st|nd|rd|th|er|ere|eme|e)", re.IGNORECASE
)
_CAPITALISED = re.compile(r"\b[A-Z][a-z]+\b")


def _inside(position: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in spans)


def proper_noun_tokens(text: str) -> list[str]:
    """Name-shaped tokens of ``text``. The first word of each sentence is not a name by shape."""
    tokens: list[str] = []
    for sentence in sentences(text):
        special = [(match.start(), match.end()) for match in _SPECIAL.finditer(sentence)]
        tokens.extend(sentence[start:end] for start, end in special)
        first = re.match(r"\W*(\w+)", sentence)
        for regex in (_CAMEL, _ACRONYM, _ALNUM, _CAPITALISED):
            for match in regex.finditer(sentence):
                token = match.group(0)
                if _inside(match.start(), special):
                    continue
                if regex is _ALNUM and _NUMERIC_TOKEN.fullmatch(token):
                    continue
                if regex is _CAPITALISED and first and match.start() == first.start(1):
                    continue
                tokens.append(token)
    return list(dict.fromkeys(tokens))


def token_in(token: str, texts: Sequence[str]) -> bool:
    """``token`` appears as a whole word (case- and accent-insensitive) in one of ``texts``."""
    pattern = re.compile(rf"(?<![\w+#.]){re.escape(fold(token))}(?![\w+#])", re.IGNORECASE)
    return any(pattern.search(fold(text)) for text in texts)
