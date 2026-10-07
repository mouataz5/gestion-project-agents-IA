"""The evidence ledger of a tailored CV version, and the guard's violations.

Stored with the version (``cv_versions.evidence``)::

    {"format": 1, "base_version_id": "...",
     "items": [{"path": "experiences.0.bullets.0", "origin": "REWRITTEN",
                "sources": ["E1.B1"], "keywords": ["RAG"]}],
     "unused_sources": ["E2.B2"],
     "repairs": [{"path": "...", "rejected_text": "...",
                  "violations": [{"code": "UNSUPPORTED_NUMBER", "detail": "40%"}]}]}

Source ids point into the immutable structure of the base (master) version, never at fact rows.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

LEDGER_FORMAT = 1


class _Result(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class ViolationCode(StrEnum):
    # a generated text (G1-G7)
    SOURCE_INVALID = "SOURCE_INVALID"
    UNSUPPORTED_TECHNOLOGY = "UNSUPPORTED_TECHNOLOGY"
    UNSUPPORTED_NUMBER = "UNSUPPORTED_NUMBER"
    UNSUPPORTED_TERM = "UNSUPPORTED_TERM"
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    NEW_CONTENT = "NEW_CONTENT"
    TEXT_TOO_LONG = "TEXT_TOO_LONG"
    EMPTY_TEXT = "EMPTY_TEXT"
    # the assembled version (the final gate)
    CONTACT_CHANGED = "CONTACT_CHANGED"
    EXPERIENCE_MISSING = "EXPERIENCE_MISSING"
    EXPERIENCE_ADDED = "EXPERIENCE_ADDED"
    EMPLOYER_CHANGED = "EMPLOYER_CHANGED"
    TITLE_CHANGED = "TITLE_CHANGED"
    DATES_CHANGED = "DATES_CHANGED"
    LOCATION_CHANGED = "LOCATION_CHANGED"
    DETAILS_CHANGED = "DETAILS_CHANGED"
    EDUCATION_CHANGED = "EDUCATION_CHANGED"
    CERTIFICATIONS_CHANGED = "CERTIFICATIONS_CHANGED"
    LANGUAGES_CHANGED = "LANGUAGES_CHANGED"
    SECTIONS_CHANGED = "SECTIONS_CHANGED"
    PROJECT_UNKNOWN = "PROJECT_UNKNOWN"
    LEDGER_MISSING = "LEDGER_MISSING"
    UNSUPPORTED_SKILL = "UNSUPPORTED_SKILL"
    CATEGORY_INVALID = "CATEGORY_INVALID"
    UNSUPPORTED_KEYWORD = "UNSUPPORTED_KEYWORD"
    STUFFING = "STUFFING"


class Violation(_Result):
    code: ViolationCode
    detail: str
    path: str | None = None


class Origin(StrEnum):
    VERBATIM = "VERBATIM"  # copied unchanged from the cited source
    REWRITTEN = "REWRITTEN"  # reworded from the cited sources, checked by the guard
    REVERTED = "REVERTED"  # a rejected rewrite, replaced by the source it cited
    COPIED = "COPIED"  # an immutable fact of the master CV
    SELECTED = "SELECTED"  # a skill the master CV backs
    RETITLED = "RETITLED"  # a role title the candidate allows to change


class LedgerItem(_Result):
    path: str  # in the version's structure: "experiences.0.bullets.1"
    origin: Origin
    sources: list[str]  # source ids of the base version: "E1.B2"
    keywords: list[str] = []  # job keywords the text mentions


class Repair(_Result):
    path: str
    rejected_text: str
    violations: list[Violation]


class Ledger(_Result):
    format: int = LEDGER_FORMAT
    base_version_id: str | None = None
    items: list[LedgerItem] = []
    unused_sources: list[str] = []
    repairs: list[Repair] = []

    def item(self, path: str) -> LedgerItem | None:
        return next((item for item in self.items if item.path == path), None)
