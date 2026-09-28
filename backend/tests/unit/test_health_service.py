import pytest

from app.schemas.health import ComponentHealth, ComponentStatus
from app.services.health import aggregate_status, run_check

pytestmark = pytest.mark.feature("health-checks")


def _component(status: ComponentStatus, *, critical: bool) -> ComponentHealth:
    return ComponentHealth(name="x", status=status, critical=critical)


def test_aggregate_is_down_when_a_critical_component_is_down() -> None:
    components = [
        _component(ComponentStatus.DOWN, critical=True),
        _component(ComponentStatus.OK, critical=False),
    ]
    assert aggregate_status(components) is ComponentStatus.DOWN


def test_aggregate_is_degraded_when_only_optional_components_fail() -> None:
    components = [
        _component(ComponentStatus.OK, critical=True),
        _component(ComponentStatus.DOWN, critical=False),
    ]
    assert aggregate_status(components) is ComponentStatus.DEGRADED


def test_aggregate_is_ok_when_everything_is_ok() -> None:
    components = [
        _component(ComponentStatus.OK, critical=True),
        _component(ComponentStatus.OK, critical=False),
    ]
    assert aggregate_status(components) is ComponentStatus.OK


def test_run_check_reports_success_with_latency() -> None:
    result = run_check("storage", critical=True, check=lambda: "writable")

    assert result.status is ComponentStatus.OK
    assert result.detail == "writable"
    assert result.latency_ms is not None
    assert result.latency_ms >= 0


def test_run_check_turns_exceptions_into_redacted_down_status() -> None:
    def failing() -> str:
        raise ConnectionError("cannot reach redis://default:hunter2@cache:6379/0")

    result = run_check("redis", critical=True, check=failing)

    assert result.status is ComponentStatus.DOWN
    assert result.detail is not None
    assert result.detail.startswith("ConnectionError")
    assert "hunter2" not in result.detail


def test_run_check_honours_explicit_degraded_status() -> None:
    result = run_check(
        "worker", critical=False, check=lambda: (ComponentStatus.DEGRADED, "no workers")
    )
    assert result.status is ComponentStatus.DEGRADED
    assert result.detail == "no workers"
