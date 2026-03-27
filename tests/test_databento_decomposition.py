"""Tests for the decomposed Databento modules.

Validates that:
1. ``databento_client`` contains all expected SDK-wrapper functions.
2. ``databento_session`` contains session/window helpers and dataclass.
3. ``databento_universe`` contains universe resolution helpers.
4. All extracted names are still importable from the monolith (backward compat).
5. The extracted modules can be used independently.
"""

from __future__ import annotations

import warnings
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ── 1. databento_client surface ─────────────────────────────────────────────

class TestDabentoClientSurface:
    """All expected names are importable from databento_client."""

    @pytest.mark.parametrize("name", [
        "_import_databento",
        "_make_databento_client",
        "_normalize_tls_certificate_env",
        "_get_schema_available_end",
        "_clamp_request_end",
        "_exclusive_ohlcv_1s_end",
        "_daily_request_end_exclusive",
        "_redact_sensitive_error_text",
        "_warn_with_redacted_exception",
        "_is_retryable_databento_get_range_error",
        "_databento_get_range_with_retry",
        "list_accessible_datasets",
        "DATABENTO_GET_RANGE_MAX_ATTEMPTS",
    ])
    def test_name_exists(self, name: str) -> None:
        import databento_client
        assert hasattr(databento_client, name)


class TestDabentoClientBehavior:
    """Functional tests for extracted client helpers."""

    def test_clamp_request_end_with_available(self) -> None:
        from databento_client import _clamp_request_end
        req = pd.Timestamp("2026-03-10 20:00", tz=UTC)
        avail = pd.Timestamp("2026-03-10 18:00", tz=UTC)
        assert _clamp_request_end(req, avail) == avail

    def test_clamp_request_end_without_available(self) -> None:
        from databento_client import _clamp_request_end
        req = pd.Timestamp("2026-03-10 20:00", tz=UTC)
        assert _clamp_request_end(req, None) == req

    def test_exclusive_ohlcv_1s_end(self) -> None:
        from databento_client import _exclusive_ohlcv_1s_end
        base = pd.Timestamp("2026-03-10 09:31:00", tz=UTC)
        result = _exclusive_ohlcv_1s_end(base)
        assert result == base + pd.Timedelta(seconds=1)

    def test_daily_request_end_exclusive_midnight(self) -> None:
        from databento_client import _daily_request_end_exclusive
        result = _daily_request_end_exclusive(date(2026, 3, 10), None)
        assert result == date(2026, 3, 11)

    def test_daily_request_end_exclusive_clamped_intraday(self) -> None:
        from databento_client import _daily_request_end_exclusive
        avail = pd.Timestamp("2026-03-10 20:00", tz=UTC)
        result = _daily_request_end_exclusive(date(2026, 3, 10), avail)
        assert result == date(2026, 3, 11)  # non-zero time → +1 day

    def test_redact_sensitive_error_text(self) -> None:
        from databento_client import _redact_sensitive_error_text
        assert "***" in _redact_sensitive_error_text("api_key=SECRET123")

    def test_is_retryable_timeout(self) -> None:
        from databento_client import _is_retryable_databento_get_range_error
        assert _is_retryable_databento_get_range_error(Exception("Read timed out"))

    def test_is_not_retryable_auth(self) -> None:
        from databento_client import _is_retryable_databento_get_range_error
        assert not _is_retryable_databento_get_range_error(Exception("Invalid API key"))


# ── 2. databento_session surface ────────────────────────────────────────────

class TestDabentoSessionSurface:
    """All expected names are importable from databento_session."""

    @pytest.mark.parametrize("name", [
        "WindowDefinition",
        "compute_market_relative_window",
        "_resolve_window_for_date",
        "build_window_definition",
        "DEFAULT_INTRADAY_PRE_OPEN_MINUTES",
        "DEFAULT_INTRADAY_POST_OPEN_MINUTES",
        "DEFAULT_OPEN_WINDOW_PRE_OPEN_MINUTES",
        "DEFAULT_OPEN_WINDOW_POST_OPEN_SECONDS",
        "DEFAULT_CLOSE_IMBALANCE_WINDOW_START_ET",
        "DEFAULT_CLOSE_IMBALANCE_AUCTION_TIME_ET",
        "DEFAULT_CLOSE_IMBALANCE_WINDOW_END_ET",
        "DEFAULT_CLOSE_IMBALANCE_AFTERHOURS_END_ET",
        "DEFAULT_CLOSE_IMBALANCE_NEXT_DAY_OUTCOME_TIME_ET",
    ])
    def test_name_exists(self, name: str) -> None:
        import databento_session
        assert hasattr(databento_session, name)


class TestDabentoSessionBehavior:
    """Functional tests for session/window helpers."""

    def test_compute_market_relative_window_defaults(self) -> None:
        from databento_session import compute_market_relative_window
        start, end = compute_market_relative_window(date(2026, 3, 10), "America/New_York")
        assert start == time(9, 20)
        assert end == time(10, 0)

    def test_compute_market_relative_window_post_open_seconds(self) -> None:
        from databento_session import compute_market_relative_window
        start, end = compute_market_relative_window(
            date(2026, 3, 10), "America/New_York",
            pre_open_minutes=1, post_open_seconds=359,
        )
        assert start == time(9, 29)
        assert end == time(9, 35, 59)

    def test_build_window_definition_fields(self) -> None:
        from databento_session import build_window_definition
        wd = build_window_definition(
            date(2026, 3, 10),
            display_timezone="America/New_York",
            window_start=time(9, 20),
            window_end=time(10, 0),
            premarket_anchor_et=time(9, 20),
        )
        assert wd.trade_date == date(2026, 3, 10)
        assert wd.display_timezone == "America/New_York"
        assert wd.fetch_start_utc < wd.fetch_end_utc

    def test_build_window_definition_rejects_inverted(self) -> None:
        from databento_session import build_window_definition
        with pytest.raises(ValueError):
            build_window_definition(
                date(2026, 3, 10),
                display_timezone="America/New_York",
                window_start=time(10, 0),
                window_end=time(9, 20),
                premarket_anchor_et=time(9, 20),
            )

    def test_resolve_window_for_date_explicit(self) -> None:
        from databento_session import _resolve_window_for_date
        s, e = _resolve_window_for_date(date(2026, 3, 10), "America/New_York", time(9, 15), time(10, 30))
        assert s == time(9, 15)
        assert e == time(10, 30)

    def test_resolve_window_for_date_defaults(self) -> None:
        from databento_session import _resolve_window_for_date
        s, e = _resolve_window_for_date(date(2026, 3, 10), "America/New_York", None, None)
        assert s == time(9, 20)
        assert e == time(10, 0)


# ── 3. databento_universe surface ───────────────────────────────────────────

class TestDabentoUniverseSurface:
    """All expected names are importable from databento_universe."""

    @pytest.mark.parametrize("name", [
        "UNIVERSE_COLUMNS",
        "NASDAQ_TRADER_DIRECTORY_SPECS",
        "NASDAQ_TRADER_EXCHANGE_CODE_MAP",
        "NASDAQ_TRADER_EXCHANGE_NAME_MAP",
        "SYMBOL_SUPPORT_CACHE_TTL_SECONDS",
        "SYMBOL_SUPPORT_CHECK_BATCH_SIZE",
        "SYMBOL_SUPPORT_LOOKBACK_DAYS",
        "fetch_us_equity_universe",
        "fetch_us_equity_universe_with_metadata",
        "filter_supported_universe_for_databento",
        "_probe_symbol_support",
        "_download_nasdaq_trader_text",
        "_parse_nasdaq_trader_directory",
        "_fetch_us_equity_universe_via_nasdaq_trader",
        "_fetch_us_equity_universe_via_screener",
        "_empty_universe_frame",
        "_normalize_requested_exchange_codes",
        "_symbols_requiring_support_check",
        "_read_symbol_support_cache",
        "_write_symbol_support_cache",
    ])
    def test_name_exists(self, name: str) -> None:
        import databento_universe
        assert hasattr(databento_universe, name)


class TestDabentoUniverseBehavior:
    """Functional tests for universe helpers."""

    def test_empty_universe_frame(self) -> None:
        from databento_universe import _empty_universe_frame, UNIVERSE_COLUMNS
        frame = _empty_universe_frame()
        assert list(frame.columns) == UNIVERSE_COLUMNS
        assert frame.empty

    def test_normalize_requested_exchange_codes_defaults(self) -> None:
        from databento_universe import _normalize_requested_exchange_codes
        assert _normalize_requested_exchange_codes("") == {"Q", "N", "A"}

    def test_normalize_requested_exchange_codes_custom(self) -> None:
        from databento_universe import _normalize_requested_exchange_codes
        assert _normalize_requested_exchange_codes("NASDAQ,NYSE") == {"Q", "N"}

    def test_symbols_requiring_support_check(self) -> None:
        from databento_universe import _symbols_requiring_support_check
        result = _symbols_requiring_support_check(["AAPL", "msft", "AAPL"])
        assert result == ["AAPL", "MSFT"]

    def test_parse_nasdaq_trader_directory_good(self) -> None:
        from databento_universe import _parse_nasdaq_trader_directory
        text = "Symbol|Security Name|Listing Exchange|ETF|Test Issue\nAAPL|Apple Inc|Q|N|N\n"
        frame = _parse_nasdaq_trader_directory(
            text,
            symbol_column="Symbol",
            security_name_column="Security Name",
            exchange_column="Listing Exchange",
            allowed_exchange_codes={"Q"},
        )
        assert len(frame) == 1
        assert frame.iloc[0]["symbol"] == "AAPL"

    def test_parse_nasdaq_trader_directory_filters_etf(self) -> None:
        from databento_universe import _parse_nasdaq_trader_directory
        text = "Symbol|Security Name|Listing Exchange|ETF|Test Issue\nSPY|SPDR|Q|Y|N\n"
        frame = _parse_nasdaq_trader_directory(
            text,
            symbol_column="Symbol",
            security_name_column="Security Name",
            exchange_column="Listing Exchange",
            allowed_exchange_codes={"Q"},
        )
        assert frame.empty

    def test_read_symbol_support_cache_missing(self, tmp_path: Path) -> None:
        from databento_universe import _read_symbol_support_cache
        assert _read_symbol_support_cache(tmp_path / "nonexistent.json") == {}


# ── 4. Backward-compatibility (monolith still exports all names) ────────────

class TestBackwardCompatibility:
    """Names extracted to new modules must still be importable from the monolith."""

    @pytest.mark.parametrize("name", [
        # from databento_client
        "_make_databento_client",
        "_import_databento",
        "_get_schema_available_end",
        "_clamp_request_end",
        "_exclusive_ohlcv_1s_end",
        "_daily_request_end_exclusive",
        "_databento_get_range_with_retry",
        "_is_retryable_databento_get_range_error",
        "_normalize_tls_certificate_env",
        "_redact_sensitive_error_text",
        "_warn_with_redacted_exception",
        "list_accessible_datasets",
        "DATABENTO_GET_RANGE_MAX_ATTEMPTS",
        # from databento_session
        "WindowDefinition",
        "compute_market_relative_window",
        "_resolve_window_for_date",
        "build_window_definition",
        "DEFAULT_CLOSE_IMBALANCE_WINDOW_START_ET",
        "DEFAULT_CLOSE_IMBALANCE_AUCTION_TIME_ET",
        "DEFAULT_CLOSE_IMBALANCE_WINDOW_END_ET",
        "DEFAULT_CLOSE_IMBALANCE_AFTERHOURS_END_ET",
        "DEFAULT_CLOSE_IMBALANCE_NEXT_DAY_OUTCOME_TIME_ET",
        # from databento_universe
        "UNIVERSE_COLUMNS",
        "NASDAQ_TRADER_DIRECTORY_SPECS",
        "NASDAQ_TRADER_EXCHANGE_CODE_MAP",
        "NASDAQ_TRADER_EXCHANGE_NAME_MAP",
        "SYMBOL_SUPPORT_CACHE_TTL_SECONDS",
        "SYMBOL_SUPPORT_CHECK_BATCH_SIZE",
        "SYMBOL_SUPPORT_LOOKBACK_DAYS",
        "fetch_us_equity_universe",
        "fetch_us_equity_universe_with_metadata",
        "filter_supported_universe_for_databento",
        "_probe_symbol_support",
        "_download_nasdaq_trader_text",
        "_parse_nasdaq_trader_directory",
        "_empty_universe_frame",
        "_normalize_requested_exchange_codes",
        "_symbols_requiring_support_check",
    ])
    def test_monolith_still_exports(self, name: str) -> None:
        import databento_volatility_screener
        assert hasattr(databento_volatility_screener, name), (
            f"databento_volatility_screener.{name} no longer exists — "
            f"backward compatibility broken"
        )
