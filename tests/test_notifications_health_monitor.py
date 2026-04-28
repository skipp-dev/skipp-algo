"""Pin per-channel notification health monitor (Lane 16)."""
import logging

import pytest

import terminal_notifications as tn


@pytest.fixture(autouse=True)
def reset():
    tn._NOTIF_HEALTH.clear()
    yield
    tn._NOTIF_HEALTH.clear()


def test_threshold_constant():
    assert tn._NOTIF_HEALTH_THRESHOLD == 3


def test_failure_increments_counter():
    tn._record_notif_failure("discord", RuntimeError("boom"))
    assert tn.get_notif_health("discord")["consecutive_failures"] == 1


def test_threshold_failures_emit_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="terminal_notifications"):
        for _ in range(tn._NOTIF_HEALTH_THRESHOLD):
            tn._record_notif_failure("pushover", RuntimeError("x"))
    assert any("pushover" in r.message for r in caplog.records)


def test_success_resets():
    for _ in range(2):
        tn._record_notif_failure("traderspost", RuntimeError("e"))
    tn._record_notif_success("traderspost")
    assert tn.get_notif_health("traderspost")["consecutive_failures"] == 0
