"""Company watchlist (spec §6): CRUD, YAML seed import and links with discovered jobs."""

from __future__ import annotations

import uuid
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.crawlers.base import CompanyTarget
from app.crawlers.registry import load_companies_file
from app.jobs.countries import COUNTRY_NAMES
from app.jobs.types import AtsType
from app.models import Company, Job
from app.schemas.companies import CompanyCreate, CompanyUpdate

# Fields that may be cleared with an explicit null in a partial update.
_NULLABLE_FIELDS = frozenset({"country_code", "board_token", "notes"})


def normalize_company_name(name: str) -> str:
    """Case- and whitespace-insensitive key (also used to link discovered jobs by name)."""
    return " ".join(name.split()).lower()


class CompanyService:
    """Methods flush but never commit: the caller owns the transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # --- queries -----------------------------------------------------------------------------
    def get(self, company_id: uuid.UUID) -> Company:
        company = self._session.get(Company, company_id)
        if company is None:
            raise NotFoundError(f"Company {company_id} not found")
        return company

    def find_by_name(self, name: str) -> Company | None:
        return self._session.scalar(
            select(Company).where(Company.normalized_name == normalize_company_name(name))
        )

    def list_companies(self) -> list[Company]:
        return list(self._session.scalars(select(Company).order_by(Company.normalized_name)))

    def job_counts(self, *, hidden_sources: Collection[str] = ()) -> dict[uuid.UUID, int]:
        """Primary job records per company (duplicate listings are not counted)."""
        query = (
            select(Job.company_id, func.count())
            .where(Job.company_id.is_not(None), Job.duplicate_of_id.is_(None))
            .group_by(Job.company_id)
        )
        if hidden_sources:
            query = query.where(Job.source.not_in(list(hidden_sources)))
        return {row[0]: row[1] for row in self._session.execute(query) if row[0] is not None}

    def watchlist_targets(self) -> list[CompanyTarget]:
        """Enabled companies, as the sources see them."""
        companies = self._session.scalars(
            select(Company).where(Company.enabled).order_by(Company.normalized_name)
        )
        return [
            CompanyTarget(
                id=company.id,
                name=company.name,
                ats_type=company.ats_type.value,
                board_token=company.board_token,
                career_url=company.career_url,
            )
            for company in companies
        ]

    # --- changes -----------------------------------------------------------------------------
    def create(self, data: CompanyCreate) -> Company:
        if self.find_by_name(data.name) is not None:
            raise ConflictError(f"A company named {data.name!r} is already in the watchlist")
        company = Company(name=data.name, normalized_name=normalize_company_name(data.name))
        self._apply(company, data.model_dump())
        self._session.add(company)
        self._session.flush()
        self._link_jobs(company)
        return company

    def update(self, company: Company, data: CompanyUpdate) -> dict[str, Any]:
        """Apply the fields sent; returns the changed fields ``{name: new value}``."""
        values = {
            name: value
            for name, value in data.model_dump(exclude_unset=True).items()
            if value is not None or name in _NULLABLE_FIELDS
        }
        if "name" in values:
            other = self.find_by_name(values["name"])
            if other is not None and other.id != company.id:
                raise ConflictError(
                    f"A company named {values['name']!r} is already in the watchlist"
                )
        changed = self._apply(company, values)
        self._session.flush()
        if "name" in changed:
            self._link_jobs(company)
        return changed

    def delete(self, company: Company) -> None:
        """Remove a company from the watchlist; its jobs are kept (unlinked)."""
        self._session.delete(company)
        self._session.flush()

    def import_from_yaml(self, crawler_dir: Path) -> dict[str, int]:
        """Create or update the companies listed in ``companies.yaml`` (others are untouched)."""
        counts = {"created": 0, "updated": 0, "unchanged": 0}
        for entry in load_companies_file(crawler_dir).companies:
            company = self.find_by_name(entry.name)
            if company is None:
                self.create(entry)
                counts["created"] += 1
            elif self._apply(company, entry.model_dump()):
                counts["updated"] += 1
            else:
                counts["unchanged"] += 1
        self._session.flush()
        return counts

    def record_check(self, company_id: uuid.UUID, *, at: Any, status: str) -> None:
        company = self._session.get(Company, company_id)
        if company is not None:
            company.last_checked_at = at
            company.last_check_status = status[:300]
            self._session.flush()

    # --- helpers -----------------------------------------------------------------------------
    def _apply(self, company: Company, values: Mapping[str, Any]) -> dict[str, Any]:
        changed: dict[str, Any] = {}
        for name, value in values.items():
            if name == "ats_type":
                value = AtsType(value)
            if name == "target_roles":
                value = list(value)
            if getattr(company, name, None) != value:
                setattr(company, name, value)
                changed[name] = value.value if isinstance(value, AtsType) else value
        if "name" in changed:
            company.normalized_name = normalize_company_name(company.name)
        if "country_code" in changed or company.country is None:
            code = company.country_code
            company.country = COUNTRY_NAMES.get(code) if code else None
        return changed

    def _link_jobs(self, company: Company) -> None:
        """Attach unlinked jobs that carry this company's name."""
        self._session.execute(
            update(Job)
            .where(Job.company_id.is_(None), func.lower(Job.company) == company.normalized_name)
            .values(company_id=company.id)
            .execution_options(synchronize_session=False)
        )
