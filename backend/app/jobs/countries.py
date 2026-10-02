"""Country names (English and French), common aliases and major tech cities → ISO 3166-1 alpha-2."""

from __future__ import annotations

import re
import unicodedata

# ISO code → names and aliases (lower-case, accents removed when compared).
_COUNTRIES: dict[str, tuple[str, ...]] = {
    "AE": ("united arab emirates", "uae", "emirats arabes unis", "u.a.e."),
    "AT": ("austria", "autriche", "osterreich"),
    "AU": ("australia", "australie"),
    "BE": ("belgium", "belgique", "belgie"),
    "BH": ("bahrain", "bahrein"),
    "CA": ("canada",),
    "CH": ("switzerland", "suisse", "schweiz"),
    "CN": ("china", "chine"),
    "CZ": ("czech republic", "czechia", "republique tcheque"),
    "DE": ("germany", "allemagne", "deutschland"),
    "DK": ("denmark", "danemark"),
    "DZ": ("algeria", "algerie"),
    "EE": ("estonia", "estonie"),
    "EG": ("egypt", "egypte"),
    "ES": ("spain", "espagne", "espana"),
    "FI": ("finland", "finlande"),
    "FR": ("france",),
    "GB": ("united kingdom", "uk", "u.k.", "great britain", "england", "scotland", "royaume-uni"),
    "GR": ("greece", "grece"),
    "IE": ("ireland", "irlande"),
    "IN": ("india", "inde"),
    "IT": ("italy", "italie", "italia"),
    "JO": ("jordan", "jordanie"),
    "JP": ("japan", "japon"),
    "KW": ("kuwait", "koweit"),
    "LB": ("lebanon", "liban"),
    "LU": ("luxembourg",),
    "LY": ("libya", "libye"),
    "MA": ("morocco", "maroc"),
    "MT": ("malta", "malte"),
    "NL": ("netherlands", "the netherlands", "pays-bas", "pays bas", "holland", "nederland"),
    "NO": ("norway", "norvege", "norge"),
    "NZ": ("new zealand", "nouvelle-zelande"),
    "OM": ("oman",),
    "PL": ("poland", "pologne", "polska"),
    "PT": ("portugal",),
    "QA": ("qatar",),
    "RO": ("romania", "roumanie"),
    "SA": ("saudi arabia", "ksa", "arabie saoudite"),
    "SE": ("sweden", "suede", "sverige"),
    "SG": ("singapore", "singapour"),
    "TN": ("tunisia", "tunisie"),
    "TR": ("turkey", "turkiye", "turquie"),
    "US": (
        "united states",
        "usa",
        "u.s.",
        "u.s.a.",
        "us",
        "etats-unis",
        "united states of america",
    ),
}

_CITIES: dict[str, str] = {
    **dict.fromkeys(
        (
            "paris",
            "lyon",
            "toulouse",
            "marseille",
            "lille",
            "nantes",
            "bordeaux",
            "nice",
            "sophia antipolis",
            "grenoble",
            "rennes",
            "montpellier",
            "strasbourg",
        ),
        "FR",
    ),
    **dict.fromkeys(
        (
            "berlin",
            "munich",
            "munchen",
            "hamburg",
            "frankfurt",
            "cologne",
            "koln",
            "stuttgart",
            "dusseldorf",
            "leipzig",
        ),
        "DE",
    ),
    **dict.fromkeys(
        ("amsterdam", "rotterdam", "eindhoven", "utrecht", "the hague", "den haag", "delft"), "NL"
    ),
    **dict.fromkeys(
        ("brussels", "bruxelles", "antwerp", "anvers", "ghent", "gand", "leuven"), "BE"
    ),
    **dict.fromkeys(("sydney", "melbourne", "brisbane", "perth", "canberra"), "AU"),
    **dict.fromkeys(("riyadh", "jeddah", "dammam", "neom"), "SA"),
    **dict.fromkeys(("dubai", "abu dhabi", "sharjah"), "AE"),
    **dict.fromkeys(("doha",), "QA"),
    **dict.fromkeys(("stockholm", "gothenburg", "malmo"), "SE"),
    **dict.fromkeys(("copenhagen", "aarhus"), "DK"),
    **dict.fromkeys(("dublin", "cork", "galway"), "IE"),
    **dict.fromkeys(("vienna", "wien", "graz"), "AT"),
    **dict.fromkeys(("helsinki", "espoo", "tampere"), "FI"),
    **dict.fromkeys(("oslo", "bergen", "trondheim"), "NO"),
    **dict.fromkeys(("zurich", "geneva", "geneve", "lausanne", "basel", "bern"), "CH"),
    **dict.fromkeys(("london", "cambridge", "oxford", "manchester", "edinburgh", "bristol"), "GB"),
    **dict.fromkeys(
        (
            "new york",
            "san francisco",
            "seattle",
            "boston",
            "austin",
            "chicago",
            "los angeles",
            "mountain view",
            "palo alto",
        ),
        "US",
    ),
    **dict.fromkeys(("tunis", "sfax", "sousse", "ariana"), "TN"),
    **dict.fromkeys(("toronto", "montreal", "vancouver", "ottawa"), "CA"),
    **dict.fromkeys(("madrid", "barcelona", "valencia"), "ES"),
    **dict.fromkeys(("lisbon", "lisboa", "porto"), "PT"),
    **dict.fromkeys(("milan", "milano", "rome", "roma", "turin", "torino"), "IT"),
    **dict.fromkeys(("warsaw", "krakow", "wroclaw"), "PL"),
    **dict.fromkeys(("prague",), "CZ"),
    **dict.fromkeys(("singapore",), "SG"),
    **dict.fromkeys(("bangalore", "bengaluru", "hyderabad", "pune"), "IN"),
    **dict.fromkeys(("luxembourg",), "LU"),
}

COUNTRY_NAMES: dict[str, str] = {code: names[0].title() for code, names in _COUNTRIES.items()}


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).strip()


_BY_NAME: dict[str, str] = {
    _fold(name): code for code, names in _COUNTRIES.items() for name in names
}


def country_code(value: str | None) -> str | None:
    """ISO alpha-2 code for a code, an English/French name or a common alias."""
    if not value or not value.strip():
        return None
    stripped = value.strip()
    if len(stripped) == 2 and stripped.isalpha() and stripped.upper() in _COUNTRIES:
        return stripped.upper()
    return _BY_NAME.get(_fold(stripped))


def country_from_location(location: str | None) -> str | None:
    """Country of a location such as "Paris, France", "Berlin, DE" or "Munich"."""
    if not location or not location.strip():
        return None
    parts = [part.strip() for part in re.split(r"[,|/()]|\s[-–]\s", location) if part.strip()]
    # Full country names first, then known cities, then two-letter codes: "Los Angeles, CA" is
    # in the United States, not in Canada.
    for part in reversed(parts):
        code = _BY_NAME.get(_fold(part)) if len(part) > 2 else None
        if code is not None:
            return code
    for part in parts:
        city = _CITIES.get(_fold(part))
        if city is not None:
            return city
    for part in reversed(parts):
        code = country_code(part)
        if code is not None:
            return code
    return None
