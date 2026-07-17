"""Metrics contract for A0 latency, async news, and the near-A0 fast lane."""

from __future__ import annotations

from types import SimpleNamespace

from open_prep.realtime_signals import _collect_a0_latency_metrics


class _MetricsSource:
    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def metrics(self) -> dict[str, object]:
        return dict(self._values)


def test_latency_metrics_expose_unknown_quote_age_when_no_data() -> None:
    engine = SimpleNamespace(
        _last_data_epoch=0.0,
        last_poll_interval_actual_seconds=12.5,
        _poll_phase_seconds={"quote_fetch": 0.25},
        _async_newsstack=None,
        _near_a0_repoller=None,
    )
    body = "\n".join(_collect_a0_latency_metrics(engine, 100.0, "signals"))
    assert "signals_a0_quote_data_age_seconds 999999.000" in body
    assert "signals_a0_poll_interval_actual_seconds 12.500" in body
    assert 'signals_a0_poll_phase_seconds{phase="quote_fetch"} 0.250000' in body
    assert "signals_a0_news_async_enabled 0" in body
    assert "signals_a0_near_repoll_enabled 0" in body


def test_latency_metrics_expose_async_news_and_near_repoll_health() -> None:
    news = _MetricsSource({
        "last_success_at": 95.0,
        "last_poll_duration": 0.4,
        "poll_count": 7,
        "poll_errors": 2,
        "cached_tickers_count": 11,
    })
    near = _MetricsSource({
        "last_warm_set_size": 4,
        "poll_count": 9,
        "poll_errors": 1,
        "a0_pushed": 3,
    })
    near._interval = 5.0
    engine = SimpleNamespace(
        _last_data_epoch=98.0,
        last_poll_interval_actual_seconds=10.0,
        _poll_phase_seconds={"news_context": 0.001},
        _async_newsstack=news,
        _near_a0_repoller=near,
    )
    body = "\n".join(_collect_a0_latency_metrics(engine, 100.0, "signals"))
    assert "signals_a0_quote_data_age_seconds 2.000" in body
    assert "signals_a0_news_async_enabled 1" in body
    assert "signals_a0_news_snapshot_age_seconds 5.000" in body
    assert "signals_a0_news_poll_errors_total 2" in body
    assert "signals_a0_near_repoll_enabled 1" in body
    assert "signals_a0_near_repoll_interval_seconds 5.000" in body
    assert "signals_a0_near_repoll_warm_set_size 4" in body
    assert "signals_a0_near_repoll_a0_pushed_total 3" in body
