"""Automation run lifecycle: creation, progress counters, event timeline, errors, completion."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from types import TracebackType
from typing import Any, Self

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import utcnow
from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.redaction import redact, redact_text
from app.models import (
    RUN_COUNTERS,
    AutomationRun,
    EventLevel,
    RunEvent,
    RunStatus,
    RunTrigger,
    RunType,
)

logger = get_logger(__name__)
MAX_MESSAGE_LENGTH = 2000


class RunService:
    """Operations on runs. Methods flush but never commit: the caller owns the transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_run(
        self,
        *,
        run_type: RunType,
        trigger: RunTrigger,
        parameters: Mapping[str, Any] | None = None,
    ) -> AutomationRun:
        run = AutomationRun(
            run_type=run_type,
            trigger=trigger,
            status=RunStatus.PENDING,
            parameters=redact(dict(parameters or {})),
            errors=[],
            summary={},
        )
        self._session.add(run)
        self._session.flush()
        logger.info("run.created", run_id=str(run.id), run_type=run_type.value)
        return run

    def get_run(self, run_id: uuid.UUID) -> AutomationRun:
        run = self._session.get(AutomationRun, run_id)
        if run is None:
            raise NotFoundError(f"Automation run {run_id} not found")
        return run

    def list_runs(
        self,
        *,
        limit: int,
        offset: int,
        status: RunStatus | None = None,
        run_type: RunType | None = None,
    ) -> tuple[list[AutomationRun], int]:
        query = select(AutomationRun)
        if status is not None:
            query = query.where(AutomationRun.status == status)
        if run_type is not None:
            query = query.where(AutomationRun.run_type == run_type)
        total = self._session.scalar(select(func.count()).select_from(query.subquery())) or 0
        items = self._session.scalars(
            query.order_by(AutomationRun.created_at.desc(), AutomationRun.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return list(items), total

    def mark_running(self, run: AutomationRun, *, task_id: str | None = None) -> None:
        if run.status.is_terminal:
            raise ConflictError(f"Run {run.id} is already {run.status.value}")
        run.status = RunStatus.RUNNING
        run.started_at = run.started_at or utcnow()
        if task_id is not None:
            run.task_id = task_id
        self._session.flush()

    def increment(self, run: AutomationRun, **counters: int) -> None:
        for name, amount in counters.items():
            if name not in RUN_COUNTERS:
                raise ValueError(f"Unknown run counter: {name}")
            if amount < 0:
                raise ValueError(f"Run counters cannot be decremented (got negative {name})")
            setattr(run, name, getattr(run, name) + amount)
        self._session.flush()

    def add_event(
        self,
        run: AutomationRun,
        *,
        stage: str,
        message: str,
        level: EventLevel = EventLevel.INFO,
        data: Mapping[str, Any] | None = None,
    ) -> RunEvent:
        event = RunEvent(
            run=run,
            level=level,
            stage=stage[:100],
            message=redact_text(message)[:MAX_MESSAGE_LENGTH],
            data=redact(dict(data or {})),
        )
        self._session.add(event)
        self._session.flush()
        return event

    def record_error(
        self,
        run: AutomationRun,
        *,
        stage: str,
        error: BaseException | str,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        error_type = type(error).__name__ if isinstance(error, BaseException) else "Error"
        message = redact_text(str(error))[:MAX_MESSAGE_LENGTH]
        entry = {"stage": stage, "type": error_type, "message": message, "at": utcnow().isoformat()}
        # Reassign (not append) so SQLAlchemy detects the JSONB change.
        run.errors = [*run.errors, entry]
        run.error_count += 1
        self.add_event(
            run,
            stage=stage,
            message=f"{error_type}: {message}",
            level=EventLevel.ERROR,
            data=data,
        )
        logger.warning("run.error", run_id=str(run.id), stage=stage, error_type=error_type)

    def finish(
        self,
        run: AutomationRun,
        *,
        status: RunStatus | None = None,
        summary: Mapping[str, Any] | None = None,
    ) -> None:
        if run.status.is_terminal:
            raise ConflictError(f"Run {run.id} is already {run.status.value}")
        if status is None:
            status = RunStatus.SUCCEEDED if run.error_count == 0 else RunStatus.PARTIAL_SUCCESS
        if not status.is_terminal:
            raise ValueError(f"{status.value} is not a final run status")
        now = utcnow()
        run.status = status
        run.started_at = run.started_at or now
        run.finished_at = now
        if summary is not None:
            run.summary = redact(dict(summary))
        self._session.flush()
        logger.info(
            "run.finished",
            run_id=str(run.id),
            status=status.value,
            error_count=run.error_count,
            duration_seconds=run.duration_seconds,
        )

    def mark_failed(self, run: AutomationRun, *, stage: str, error: BaseException | str) -> None:
        self.record_error(run, stage=stage, error=error)
        self.finish(run, status=RunStatus.FAILED)


class RunRecorder:
    """Context manager used by workers to record a run step by step.

    Every call commits immediately so progress is visible in the dashboard while the run is
    executing. If the body raises, the run is marked FAILED and the exception propagates.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        run_id: uuid.UUID,
        *,
        task_id: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._run_id = run_id
        self._task_id = task_id
        self._session: Session | None = None
        self._run: AutomationRun | None = None
        self._finished = False

    @property
    def run(self) -> AutomationRun:
        if self._run is None:
            raise RuntimeError("RunRecorder is not active")
        return self._run

    @property
    def service(self) -> RunService:
        if self._session is None:
            raise RuntimeError("RunRecorder is not active")
        return RunService(self._session)

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        try:
            self._run = self.service.get_run(self._run_id)
            self.service.mark_running(self._run, task_id=self._task_id)
            self._session.commit()
        except BaseException:
            self._session.close()
            self._session = None
            raise
        structlog.contextvars.bind_contextvars(run_id=str(self._run_id))
        return self

    @property
    def _active_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("RunRecorder is not active")
        return self._session

    def _commit(self) -> None:
        self._active_session.commit()

    def event(
        self,
        stage: str,
        message: str,
        *,
        level: EventLevel = EventLevel.INFO,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        self.service.add_event(self.run, stage=stage, message=message, level=level, data=data)
        self._commit()

    def increment(self, **counters: int) -> None:
        self.service.increment(self.run, **counters)
        self._commit()

    def error(
        self, stage: str, error: BaseException | str, *, data: Mapping[str, Any] | None = None
    ) -> None:
        self.service.record_error(self.run, stage=stage, error=error, data=data)
        self._commit()

    def finish(
        self, status: RunStatus | None = None, *, summary: Mapping[str, Any] | None = None
    ) -> None:
        self.service.finish(self.run, status=status, summary=summary)
        self._commit()
        self._finished = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self._active_session
        try:
            if exc is not None:
                session.rollback()
                if not self._finished:
                    self.service.record_error(self.run, stage="run", error=exc)
                    self.service.finish(self.run, status=RunStatus.FAILED)
                    session.commit()
            elif not self._finished:
                self.finish()
        finally:
            session.close()
            self._session = None
            structlog.contextvars.unbind_contextvars("run_id")
