"""Databento Historical adapter tests without network access."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from open_prep.a0_stream_state import StreamBar
from services.a0_fast_detector import history

_ET = ZoneInfo("America/New_York")


class Ohlcv1SMsg:
    def __init__(self, ts_event: int) -> None:
        self.close = 102_000_000_000
        self.volume = 100
        self.ts_event = ts_event
        self.ts_recv = ts_event + 100_000_000
        self.sequence = 1


def test_history_provider_requests_open_to_current_exclusive(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(history, "_make_databento_client", lambda _key: object())

    open_et = datetime(2026, 7, 17, 9, 30, tzinfo=_ET)
    current_et = datetime(2026, 7, 17, 11, 0, tzinfo=_ET)
    record = Ohlcv1SMsg(int(open_et.timestamp() * 1_000_000_000))

    def _fetch(_client, **kwargs):
        calls.append(kwargs)
        return [record]

    monkeypatch.setattr(history, "_databento_get_range_with_retry", _fetch)
    provider = history.DatabentoHistoricalBarsProvider("test-key")
    current = StreamBar(
        symbol="NVDA",
        close=103.0,
        volume=50,
        ts_event=current_et.timestamp(),
        ts_recv=current_et.timestamp() + 0.1,
    )
    batch = provider.fetch_before(current)
    assert batch.coverage_complete is True
    assert batch.request_start == open_et.timestamp()
    assert batch.request_end == current_et.timestamp()
    assert len(batch.bars) == 1
    assert calls[0]["schema"] == "ohlcv-1s"
    assert calls[0]["symbols"] == ["NVDA"]
    assert calls[0]["stype_in"] == "raw_symbol"


def test_history_provider_fails_closed_on_out_of_window_bar(monkeypatch) -> None:
    monkeypatch.setattr(history, "_make_databento_client", lambda _key: object())
    current_et = datetime(2026, 7, 17, 11, 0, tzinfo=_ET)
    # A bar stamped at the exclusive end is outside the proven session window,
    # so coverage must not be asserted (recovery then fails closed).
    stray = Ohlcv1SMsg(int(current_et.timestamp() * 1_000_000_000))
    monkeypatch.setattr(
        history, "_databento_get_range_with_retry", lambda _client, **_kwargs: [stray]
    )
    provider = history.DatabentoHistoricalBarsProvider("test-key")
    current = StreamBar(
        symbol="NVDA",
        close=103.0,
        volume=50,
        ts_event=current_et.timestamp(),
        ts_recv=current_et.timestamp() + 0.1,
    )
    batch = provider.fetch_before(current)
    assert batch.coverage_complete is False


def test_history_provider_fails_closed_on_empty_long_window(monkeypatch) -> None:
    monkeypatch.setattr(history, "_make_databento_client", lambda _key: object())
    monkeypatch.setattr(
        history, "_databento_get_range_with_retry", lambda _client, **_kwargs: []
    )
    provider = history.DatabentoHistoricalBarsProvider("test-key")
    # ~90 minutes into the session with zero returned bars is a fetch fault, not
    # a quiet symbol -> must not claim coverage (else volume rebuilds as zero).
    current_et = datetime(2026, 7, 17, 11, 0, tzinfo=_ET)
    current = StreamBar(
        symbol="NVDA",
        close=103.0,
        volume=50,
        ts_event=current_et.timestamp(),
        ts_recv=current_et.timestamp() + 0.1,
    )
    batch = provider.fetch_before(current)
    assert batch.bars == ()
    assert batch.coverage_complete is False


def test_history_provider_covers_empty_short_window_at_quiet_open(monkeypatch) -> None:
    monkeypatch.setattr(history, "_make_databento_client", lambda _key: object())
    monkeypatch.setattr(
        history, "_databento_get_range_with_retry", lambda _client, **_kwargs: []
    )
    provider = history.DatabentoHistoricalBarsProvider("test-key")
    # A minute into the session with no trades yet is a legitimately quiet open,
    # not a fault -> a zero-volume reconstruction is correct, coverage holds.
    current_et = datetime(2026, 7, 17, 9, 31, tzinfo=_ET)
    current = StreamBar(
        symbol="NVDA",
        close=103.0,
        volume=50,
        ts_event=current_et.timestamp(),
        ts_recv=current_et.timestamp() + 0.1,
    )
    batch = provider.fetch_before(current)
    assert batch.bars == ()
    assert batch.coverage_complete is True
