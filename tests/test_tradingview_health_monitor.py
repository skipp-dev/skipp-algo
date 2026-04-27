"""Pin consecutive-failure -> 'down' status flip (Lane 15)."""
import pytest

import terminal_tradingview_news as tv


@pytest.fixture(autouse=True)
def reset_health():
    state = tv._health
    state.consecutive_failures = 0
    state.total_requests = 0
    state.total_failures = 0
    yield
    state.consecutive_failures = 0
    state.total_requests = 0
    state.total_failures = 0


def test_status_flips_to_down_after_threshold():
    threshold = tv._HEALTH_FAIL_THRESHOLD
    for _ in range(threshold):
        tv._health.record_failure("boom")
    assert tv._health.status == "down"
    assert tv._health.is_healthy is False


def test_status_not_down_below_threshold():
    threshold = tv._HEALTH_FAIL_THRESHOLD
    for _ in range(max(threshold - 1, 0)):
        tv._health.record_failure("boom")
    assert tv._health.status != "down"
    assert tv._health.is_healthy is True


def test_threshold_is_three():
    assert tv._HEALTH_FAIL_THRESHOLD == 3
