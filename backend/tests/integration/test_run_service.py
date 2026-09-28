import uuid

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import ConflictError, NotFoundError
from app.models import AutomationRun, EventLevel, RunStatus, RunTrigger, RunType
from app.services.runs import RunRecorder, RunService

pytestmark = [pytest.mark.feature("automation-runs"), pytest.mark.integration]


def _new_run(session_factory: sessionmaker[Session]) -> uuid.UUID:
    with session_factory() as session:
        run = RunService(session).create_run(
            run_type=RunType.DIAGNOSTIC, trigger=RunTrigger.MANUAL, parameters={"source": "test"}
        )
        session.commit()
        return run.id


def test_run_lifecycle_counters_and_timing(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        service = RunService(session)
        run = service.create_run(run_type=RunType.DISCOVERY, trigger=RunTrigger.SCHEDULED)
        session.commit()
        assert run.status is RunStatus.PENDING
        assert run.started_at is None

        service.mark_running(run, task_id="task-7")
        service.increment(run, jobs_discovered=5, jobs_processed=2)
        service.increment(run, jobs_discovered=1, cv_generated=1)
        service.add_event(run, stage="discovery", message="found jobs", data={"count": 6})
        service.finish(run, summary={"sources": 1})
        session.commit()

        assert run.status is RunStatus.SUCCEEDED
        assert run.task_id == "task-7"
        assert run.jobs_discovered == 6
        assert run.jobs_processed == 2
        assert run.cv_generated == 1
        assert run.summary == {"sources": 1}
        assert run.started_at is not None
        assert run.finished_at is not None
        assert run.finished_at >= run.started_at
        assert run.duration_seconds is not None
        assert run.duration_seconds >= 0


def test_errors_turn_a_finished_run_into_partial_success(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        service = RunService(session)
        run = service.create_run(run_type=RunType.DISCOVERY, trigger=RunTrigger.API)
        service.mark_running(run)
        service.record_error(run, stage="source.lever", error=TimeoutError("lever timed out"))
        service.finish(run)
        session.commit()

        assert run.status is RunStatus.PARTIAL_SUCCESS
        assert run.error_count == 1
        error = run.errors[0]
        assert error["stage"] == "source.lever"
        assert error["type"] == "TimeoutError"
        assert error["message"] == "lever timed out"
        assert "at" in error
        levels = [event.level for event in run.events]
        assert EventLevel.ERROR in levels


def test_invalid_counter_updates_are_rejected(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        service = RunService(session)
        run = service.create_run(run_type=RunType.DIAGNOSTIC, trigger=RunTrigger.API)

        with pytest.raises(ValueError, match="Unknown run counter"):
            service.increment(run, bogus=1)
        with pytest.raises(ValueError, match="negative"):
            service.increment(run, jobs_discovered=-1)


def test_finishing_twice_is_a_conflict(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        service = RunService(session)
        run = service.create_run(run_type=RunType.DIAGNOSTIC, trigger=RunTrigger.API)
        service.finish(run)

        with pytest.raises(ConflictError):
            service.finish(run)


def test_event_data_and_error_messages_are_redacted(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        service = RunService(session)
        run = service.create_run(run_type=RunType.DIAGNOSTIC, trigger=RunTrigger.API)
        service.add_event(
            run,
            stage="llm",
            message="calling provider with api_key=sk-ant-api03-abcdefghijklmnop",
            data={"api_key": "sk-ant-api03-abcdefghijklmnop", "model": "claude-opus-5"},
        )
        service.record_error(run, stage="db", error=RuntimeError("login failed password=hunter2"))
        session.commit()

        stored = session.get(AutomationRun, run.id)
        assert stored is not None
        dumped = str([(e.message, e.data) for e in stored.events]) + str(stored.errors)
        assert "sk-ant-api03-abcdefghijklmnop" not in dumped
        assert "hunter2" not in dumped
        assert stored.events[0].data["model"] == "claude-opus-5"


def test_events_keep_insertion_order(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        service = RunService(session)
        run = service.create_run(run_type=RunType.DIAGNOSTIC, trigger=RunTrigger.API)
        for index in range(5):
            service.add_event(run, stage="step", message=f"event {index}")
        session.commit()

    with session_factory() as session:
        reloaded = RunService(session).get_run(run.id)
        assert [event.message for event in reloaded.events] == [f"event {i}" for i in range(5)]
        sequences = [event.sequence for event in reloaded.events]
        assert sequences == sorted(sequences)


def test_recorder_completes_a_run(session_factory: sessionmaker[Session]) -> None:
    run_id = _new_run(session_factory)

    with RunRecorder(session_factory, run_id, task_id="task-1") as recorder:
        recorder.event("step", "working", data={"n": 1})
        recorder.increment(jobs_processed=3)

    with session_factory() as session:
        run = RunService(session).get_run(run_id)
        assert run.status is RunStatus.SUCCEEDED
        assert run.task_id == "task-1"
        assert run.jobs_processed == 3
        assert [event.message for event in run.events] == ["working"]


def test_recorder_marks_the_run_failed_when_the_body_raises(
    session_factory: sessionmaker[Session],
) -> None:
    run_id = _new_run(session_factory)

    def failing_body() -> None:
        with RunRecorder(session_factory, run_id) as recorder:
            recorder.event("step", "about to fail")
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        failing_body()

    with session_factory() as session:
        run = RunService(session).get_run(run_id)
        assert run.status is RunStatus.FAILED
        assert run.error_count == 1
        assert run.errors[0]["message"] == "boom"
        assert run.finished_at is not None


def test_recorder_respects_an_explicit_final_status(
    session_factory: sessionmaker[Session],
) -> None:
    run_id = _new_run(session_factory)

    with RunRecorder(session_factory, run_id) as recorder:
        recorder.error("check.redis", ConnectionError("down"))
        recorder.finish(RunStatus.FAILED, summary={"checks_failed": ["redis"]})

    with session_factory() as session:
        run = RunService(session).get_run(run_id)
        assert run.status is RunStatus.FAILED
        assert run.summary == {"checks_failed": ["redis"]}


def test_recorder_rejects_unknown_runs(session_factory: sessionmaker[Session]) -> None:
    with pytest.raises(NotFoundError), RunRecorder(session_factory, uuid.uuid4()):
        pass
