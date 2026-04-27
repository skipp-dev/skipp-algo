"""Pin BenzingaWsAdapter.is_healthy contract (Lane 15)."""
from newsstack_fmp.ingest_benzinga import BenzingaWsAdapter


def _bare_adapter():
    a = BenzingaWsAdapter.__new__(BenzingaWsAdapter)
    a._consecutive_connect_failures = 0
    return a


def test_threshold_constant_is_five():
    assert BenzingaWsAdapter._WS_HEALTH_THRESHOLD == 5


def test_is_healthy_true_initially():
    a = _bare_adapter()
    assert a.is_healthy is True


def test_is_healthy_false_after_threshold():
    a = _bare_adapter()
    a._consecutive_connect_failures = BenzingaWsAdapter._WS_HEALTH_THRESHOLD
    assert a.is_healthy is False


def test_is_healthy_recovers_on_reset():
    a = _bare_adapter()
    a._consecutive_connect_failures = 99
    a._consecutive_connect_failures = 0
    assert a.is_healthy is True
