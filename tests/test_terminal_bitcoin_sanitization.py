from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_fetch_btc_ohlcv_10min_sanitizes_cached_and_logged_errors() -> None:
    import terminal_bitcoin as tb

    secret = "https://example.test/feed?apikey=TOPSECRET"
    ticker = MagicMock()
    ticker.history.side_effect = RuntimeError(secret)

    with patch.object(tb, "_YF", True), \
         patch.object(tb, "_PD", True), \
         patch.object(tb, "_get_cached", return_value=None), \
         patch.object(tb, "_set_cached") as mock_set_cached, \
         patch.object(tb.yf, "Ticker", return_value=ticker), \
         patch.object(tb, "log") as mock_log:
        rows = tb.fetch_btc_ohlcv_10min(hours=4)

    assert rows == []
    mock_set_cached.assert_called_once()
    cached_error = mock_set_cached.call_args.args[1]
    assert "TOPSECRET" not in cached_error
    assert "apikey=***" in cached_error

    mock_log.warning.assert_called_once()
    logged_error = mock_log.warning.call_args.args[1]
    assert "TOPSECRET" not in logged_error
    assert "apikey=***" in logged_error


def test_fetch_btc_ohlcv_10min_returns_stale_fallback_on_failure() -> None:
    import terminal_bitcoin as tb

    ticker = MagicMock()
    ticker.history.side_effect = RuntimeError("temporary backend failure")
    stale_rows = [{"date": "2026-03-08T10:00:00+00:00", "close": 100000.0, "open": 99900.0, "high": 100100.0, "low": 99800.0, "volume": 42.0}]

    def _cached_side_effect(key: str, ttl: float):
        if key.endswith(":error"):
            return None
        if key.endswith(":last_good"):
            return stale_rows
        return None

    with patch.object(tb, "_YF", True), \
         patch.object(tb, "_PD", True), \
         patch.object(tb, "_get_cached", side_effect=_cached_side_effect), \
         patch.object(tb, "_set_cached") as mock_set_cached, \
         patch.object(tb.yf, "Ticker", return_value=ticker):
        rows = tb.fetch_btc_ohlcv_10min(hours=4)

    assert rows == stale_rows
    # Error throttle entry should still be written
    assert mock_set_cached.called