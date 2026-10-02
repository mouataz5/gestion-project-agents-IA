"""Company watchlist: CRUD and import of the ``crawler/companies.yaml`` seed (audited)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import DbSession, SettingsDep, require_api_token
from app.core.config import Settings
from app.models import Company
from app.schemas.common import ErrorResponse
from app.schemas.companies import CompanyCreate, CompanyImportResult, CompanyRead, CompanyUpdate
from app.services.audit import Actor, AuditAction, AuditService
from app.services.companies import CompanyService
from app.services.job_sources import JobSourceService

router = APIRouter(
    prefix="/companies", tags=["companies"], dependencies=[Depends(require_api_token)]
)


def _job_counts(db: DbSession, settings: Settings) -> dict[uuid.UUID, int]:
    hidden = () if settings.mock_mode else JobSourceService(db).mock_keys()
    return CompanyService(db).job_counts(hidden_sources=hidden)


def _read(company: Company, counts: dict[uuid.UUID, int]) -> CompanyRead:
    return CompanyRead.model_validate(
        {
            **{
                name: getattr(company, name)
                for name in CompanyRead.model_fields
                if name != "job_count"
            },
            "ats_type": company.ats_type.value,
            "job_count": counts.get(company.id, 0),
        }
    )


def _audit(db: DbSession, action: AuditAction, company: Company, **details: object) -> None:
    AuditService(db).record(
        action=action,
        actor=Actor.USER,
        entity_type="company",
        entity_id=str(company.id),
        details={"name": company.name, **details},
    )


@router.get("", response_model=list[CompanyRead], summary="Watchlist companies (by name)")
def list_companies(db: DbSession, settings: SettingsDep) -> list[CompanyRead]:
    counts = _job_counts(db, settings)
    return [_read(company, counts) for company in CompanyService(db).list_companies()]


@router.post(
    "",
    response_model=CompanyRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a company to the watchlist",
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def create_company(payload: CompanyCreate, db: DbSession, settings: SettingsDep) -> CompanyRead:
    company = CompanyService(db).create(payload)
    _audit(db, AuditAction.COMPANY_CREATED, company)
    db.commit()
    return _read(company, _job_counts(db, settings))


@router.post(
    "/import",
    response_model=CompanyImportResult,
    summary="Create or update the companies listed in crawler/companies.yaml",
)
def import_companies(db: DbSession, settings: SettingsDep) -> CompanyImportResult:
    counts = CompanyService(db).import_from_yaml(settings.crawler_dir)
    AuditService(db).record(
        action=AuditAction.COMPANIES_IMPORTED,
        actor=Actor.USER,
        entity_type="company",
        details=counts,
    )
    db.commit()
    return CompanyImportResult(**counts)


@router.get(
    "/{company_id}",
    response_model=CompanyRead,
    summary="One watchlist company",
    responses={404: {"model": ErrorResponse}},
)
def get_company(company_id: uuid.UUID, db: DbSession, settings: SettingsDep) -> CompanyRead:
    return _read(CompanyService(db).get(company_id), _job_counts(db, settings))


@router.patch(
    "/{company_id}",
    response_model=CompanyRead,
    summary="Update a watchlist company (only the fields sent)",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def update_company(
    company_id: uuid.UUID, payload: CompanyUpdate, db: DbSession, settings: SettingsDep
) -> CompanyRead:
    service = CompanyService(db)
    company = service.get(company_id)
    changed = service.update(company, payload)
    if changed:
        _audit(db, AuditAction.COMPANY_UPDATED, company, fields=sorted(changed))
    db.commit()
    return _read(company, _job_counts(db, settings))


@router.delete(
    "/{company_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Remove a company from the watchlist (its jobs are kept)",
    responses={404: {"model": ErrorResponse}},
)
def delete_company(company_id: uuid.UUID, db: DbSession) -> Response:
    service = CompanyService(db)
    company = service.get(company_id)
    _audit(db, AuditAction.COMPANY_DELETED, company)
    service.delete(company)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
