"""ATS score weights (``ATS_SCORE_WEIGHTS``): no imports, so the settings can validate them."""

from __future__ import annotations

from collections.abc import Mapping

COMPONENTS: tuple[str, ...] = (
    "keywords",
    "skills",
    "experience",
    "responsibilities",
    "title",
    "education",
    "formatting",
)
DEFAULT_WEIGHTS: dict[str, int] = {
    "keywords": 30,
    "skills": 20,
    "experience": 15,
    "responsibilities": 15,
    "title": 10,
    "education": 5,
    "formatting": 5,
}


def validate_weights(weights: Mapping[str, object]) -> dict[str, int]:
    """The 7 component weights: whole numbers >= 0 that sum to 100."""
    missing = [name for name in COMPONENTS if name not in weights]
    unknown = sorted(name for name in weights if name not in COMPONENTS)
    if missing or unknown:
        raise ValueError(
            f"ATS weights must name exactly {', '.join(COMPONENTS)}"
            f" (missing: {', '.join(missing) or 'none'}; unknown: {', '.join(unknown) or 'none'})"
        )
    values: dict[str, int] = {}
    for name in COMPONENTS:
        value = weights[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"ATS weight {name!r} must be a whole number >= 0, got {value!r}")
        values[name] = value
    total = sum(values.values())
    if total != 100:
        raise ValueError(f"ATS weights must sum to 100, got {total}")
    return values
