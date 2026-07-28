from __future__ import annotations

from datetime import UTC, datetime

from open_prep.screen import filter_active_quotes

_RUN_AT = datetime(2026, 7, 28, 14, 30, tzinfo=UTC)


def test_filter_active_quotes_removes_dayforce_months_after_delisting() -> None:
    dayforce = {
        "symbol": "DAY",
        "timestamp": 1_770_152_402,
        "gap_reason": "stale_prior_session_quote",
        "premarket_stale": True,
    }
    active = {
        "symbol": "AAPL",
        "timestamp": _RUN_AT.timestamp() - 5,
        "gap_reason": "ok",
    }

    assert filter_active_quotes([dayforce, active], run_dt_utc=_RUN_AT) == [active]


def test_filter_active_quotes_keeps_transient_prior_session_staleness() -> None:
    quote = {
        "symbol": "AAPL",
        "timestamp": _RUN_AT.timestamp() - 24 * 60 * 60,
        "gap_reason": "stale_prior_session_quote",
        "premarket_stale": True,
    }

    assert filter_active_quotes([quote], run_dt_utc=_RUN_AT) == [quote]


def test_filter_active_quotes_removes_explicitly_inactive_symbol() -> None:
    quote = {
        "symbol": "ZOMB",
        "timestamp": _RUN_AT.timestamp(),
        "isActivelyTrading": False,
    }

    assert filter_active_quotes([quote], run_dt_utc=_RUN_AT) == []
