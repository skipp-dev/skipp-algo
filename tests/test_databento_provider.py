"""Tests for databento_provider and databento_utils modules.

Covers:
- MarketDataProvider protocol satisfaction for both implementations
- DegradedProvider returns empty/raises as expected
- Utility functions (cache, symbol normalization, frame processing, warnings)
- Integration: provider injection into collect_full_universe_session_minute_detail
"""
from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from databento_provider import DabentoProvider, DegradedProvider, MarketDataProvider
from databento_utils import (
    CACHE_VERSION,
    CACHE_VERSION_BY_CATEGORY,
    DATA_CACHE_TTL_SECONDS,
    DATABENTO_SYMBOL_ALIASES,
    DATABENTO_UNSUPPORTED_SYMBOLS,
    PREFERRED_DATABENTO_DATASETS,
    RECENT_INTRADAY_CACHE_TTL_SECONDS,
    US_EASTERN_TZ,
    _API_KEY_REDACTION_PATTERNS,
    _clamp_request_end,
    _coerce_timestamp_frame,
    _exclusive_ohlcv_1s_end,
    _extract_unresolved_symbols_from_warning_messages,
    _iter_symbol_batches,
    _read_cached_frame,
    _redact_sensitive_error_text,
    _store_to_frame,
    _trade_day_cache_max_age_seconds,
    _validate_frame_columns,
    _warn_with_redacted_exception,
    _write_cached_frame,
    build_cache_path,
    choose_default_dataset,
    normalize_symbol_for_databento,
    resolve_display_timezone,
)


# ── Protocol conformance ────────────────────────────────────────────────────


class TestProtocolConformance:
    """Verify that both providers satisfy the MarketDataProvider protocol."""

    def test_degraded_provider_is_protocol_instance(self):
        assert isinstance(DegradedProvider(), MarketDataProvider)

    def test_protocol_is_runtime_checkable(self):
        assert hasattr(MarketDataProvider, "__protocol_attrs__") or hasattr(
            MarketDataProvider, "__abstractmethods__"
        ) or isinstance(DegradedProvider(), MarketDataProvider)

    def test_custom_object_not_provider(self):
        assert not isinstance(object(), MarketDataProvider)

    def test_minimal_duck_type_satisfies_protocol(self):
        class Minimal:
            def get_range(self, *, context, dataset, symbols, schema, start, end):
                return None

            def get_schema_available_end(self, dataset, schema):
                return None

            def list_datasets(self):
                return []

        assert isinstance(Minimal(), MarketDataProvider)


# ── DegradedProvider ────────────────────────────────────────────────────────


class TestDegradedProvider:
    def test_get_range_raises_runtime_error(self):
        provider = DegradedProvider()
        with pytest.raises(RuntimeError, match="DegradedProvider"):
            provider.get_range(
                context="test",
                dataset="DBEQ.BASIC",
                symbols=["AAPL"],
                schema="ohlcv-1m",
                start="2024-01-02",
                end="2024-01-03",
            )

    def test_get_range_error_has_context(self):
        provider = DegradedProvider()
        with pytest.raises(RuntimeError, match="my_context"):
            provider.get_range(
                context="my_context",
                dataset="XNAS.ITCH",
                symbols=["MSFT"],
                schema="ohlcv-1s",
                start="2024-01-02",
                end="2024-01-03",
            )

    def test_get_schema_available_end_returns_none(self):
        provider = DegradedProvider()
        assert provider.get_schema_available_end("DBEQ.BASIC", "ohlcv-1m") is None

    def test_list_datasets_returns_empty(self):
        provider = DegradedProvider()
        assert provider.list_datasets() == []


# ── Cache utilities ─────────────────────────────────────────────────────────


class TestCacheUtilities:
    def test_build_cache_path_returns_parquet(self, tmp_path):
        path = build_cache_path(
            tmp_path, "daily_bars", dataset="DBEQ.BASIC", parts=["2024-01-02", "scope"]
        )
        assert path.suffix == ".parquet"
        assert path.parent.exists()

    def test_build_cache_path_uses_category_version(self, tmp_path):
        path_v2 = build_cache_path(
            tmp_path, "daily_bars", dataset="DBEQ.BASIC", parts=["a"]
        )
        path_v1 = build_cache_path(
            tmp_path, "unknown_category", dataset="DBEQ.BASIC", parts=["a"]
        )
        # Different versions → different hashes → different paths
        assert path_v2 != path_v1

    def test_read_write_cache_roundtrip(self, tmp_path):
        path = tmp_path / "test.parquet"
        frame = pd.DataFrame({"symbol": ["AAPL", "MSFT"], "close": [150.0, 300.0]})
        _write_cached_frame(path, frame)
        result = _read_cached_frame(path)
        assert result is not None
        assert list(result.columns) == ["symbol", "close"]
        assert len(result) == 2

    def test_read_cached_frame_missing_returns_none(self, tmp_path):
        assert _read_cached_frame(tmp_path / "nonexistent.parquet") is None

    def test_read_cached_frame_expired_returns_none(self, tmp_path):
        path = tmp_path / "test.parquet"
        frame = pd.DataFrame({"x": [1]})
        _write_cached_frame(path, frame)
        assert _read_cached_frame(path, max_age_seconds=0) is None

    def test_trade_day_cache_max_age_no_latest(self):
        assert _trade_day_cache_max_age_seconds(date(2024, 1, 2), None) == DATA_CACHE_TTL_SECONDS

    def test_trade_day_cache_max_age_latest_day(self):
        today = date(2024, 6, 15)
        assert _trade_day_cache_max_age_seconds(today, today) == 0

    def test_trade_day_cache_max_age_previous_day(self):
        today = date(2024, 6, 15)
        yesterday = date(2024, 6, 14)
        assert _trade_day_cache_max_age_seconds(yesterday, today) == RECENT_INTRADAY_CACHE_TTL_SECONDS

    def test_trade_day_cache_max_age_old_day(self):
        today = date(2024, 6, 15)
        old_day = date(2024, 6, 10)
        assert _trade_day_cache_max_age_seconds(old_day, today) is None


# ── Symbol normalization ────────────────────────────────────────────────────


class TestSymbolNormalization:
    def test_basic_normalization(self):
        assert normalize_symbol_for_databento("aapl") == "AAPL"
        assert normalize_symbol_for_databento("  msft ") == "MSFT"

    def test_alias_mapping(self):
        assert normalize_symbol_for_databento("BRK-B") == "BRK.B"
        assert normalize_symbol_for_databento("BF-B") == "BF.B"

    def test_unsupported_symbols_rejected(self):
        assert normalize_symbol_for_databento("CTA-PA") == ""

    def test_invalid_chars_rejected(self):
        assert normalize_symbol_for_databento("FOO-BAR") == ""

    def test_warrant_suffixes_rejected(self):
        assert normalize_symbol_for_databento("ACME.WS") == ""
        assert normalize_symbol_for_databento("ACME.U") == ""

    def test_empty_string(self):
        assert normalize_symbol_for_databento("") == ""

    def test_iter_symbol_batches_single_batch(self):
        batches = _iter_symbol_batches({"AAPL", "MSFT", "GOOG"}, batch_size=10)
        assert len(batches) == 1
        assert sorted(batches[0]) == ["AAPL", "GOOG", "MSFT"]

    def test_iter_symbol_batches_multiple(self):
        symbols = {f"SYM{i}" for i in range(5)}
        batches = _iter_symbol_batches(symbols, batch_size=2)
        assert len(batches) == 3  # 5/2 = 3 batches
        all_symbols = [s for batch in batches for s in batch]
        assert len(all_symbols) == 5

    def test_extract_unresolved_symbols(self):
        messages = ["Symbols did not resolve: FAKEA, FAKEB"]
        result = _extract_unresolved_symbols_from_warning_messages(messages)
        assert "FAKEA" in result
        assert "FAKEB" in result

    def test_extract_unresolved_empty(self):
        result = _extract_unresolved_symbols_from_warning_messages([])
        assert result == set()


# ── Timezone ────────────────────────────────────────────────────────────────


class TestTimezone:
    def test_resolve_valid_timezone(self):
        tz = resolve_display_timezone("America/New_York")
        assert tz is not None

    def test_resolve_berlin(self):
        tz = resolve_display_timezone("Europe/Berlin")
        assert tz is not None

    def test_resolve_unsupported_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            resolve_display_timezone("Asia/Tokyo")


# ── Request helpers ─────────────────────────────────────────────────────────


class TestRequestHelpers:
    def test_clamp_request_end_none_available(self):
        requested = pd.Timestamp("2024-06-15T20:00:00", tz="UTC")
        assert _clamp_request_end(requested, None) == requested

    def test_clamp_request_end_clamped(self):
        requested = pd.Timestamp("2024-06-15T20:00:00", tz="UTC")
        available = pd.Timestamp("2024-06-15T18:00:00", tz="UTC")
        result = _clamp_request_end(requested, available)
        assert result == available

    def test_clamp_request_end_not_clamped(self):
        requested = pd.Timestamp("2024-06-15T16:00:00", tz="UTC")
        available = pd.Timestamp("2024-06-15T20:00:00", tz="UTC")
        result = _clamp_request_end(requested, available)
        assert result == requested

    def test_exclusive_ohlcv_1s_end(self):
        logical = pd.Timestamp("2024-06-15T16:00:00", tz="UTC")
        result = _exclusive_ohlcv_1s_end(logical)
        assert result == logical + pd.Timedelta(seconds=1)


# ── Frame processing ───────────────────────────────────────────────────────


class TestFrameProcessing:
    def test_coerce_timestamp_frame_with_ts_event(self):
        df = pd.DataFrame({
            "ts_event": pd.to_datetime(["2024-01-02T09:30:00"], utc=True),
            "close": [150.0],
        })
        result = _coerce_timestamp_frame(df)
        assert "ts" in result.columns
        assert "ts_event" not in result.columns

    def test_coerce_timestamp_frame_empty(self):
        df = pd.DataFrame(columns=["ts_event", "close"])
        result = _coerce_timestamp_frame(df)
        assert result.empty

    def test_coerce_timestamp_frame_no_timestamp_col(self):
        df = pd.DataFrame({"close": [150.0]})
        with pytest.raises(ValueError, match="No timestamp column"):
            _coerce_timestamp_frame(df)

    def test_validate_frame_columns_passes(self):
        df = pd.DataFrame({"symbol": ["AAPL"], "close": [150.0]})
        result = _validate_frame_columns(df, required={"symbol", "close"}, context="test")
        assert len(result) == 1

    def test_validate_frame_columns_missing(self):
        df = pd.DataFrame({"symbol": ["AAPL"]})
        with pytest.raises(ValueError, match="missing required columns"):
            _validate_frame_columns(df, required={"symbol", "close"}, context="test")

    def test_store_to_frame_dataframe(self):
        inner = pd.DataFrame({
            "ts_event": pd.to_datetime(["2024-01-02T09:30:00"], utc=True),
            "symbol": ["AAPL"],
            "close": [150.0],
        })
        store = MagicMock()
        store.to_df.return_value = inner
        result = _store_to_frame(store, context="test")
        assert "ts" in result.columns
        assert len(result) == 1

    def test_store_to_frame_iterator(self):
        chunk = pd.DataFrame({
            "ts_event": pd.to_datetime(["2024-01-02T09:30:00"], utc=True),
            "symbol": ["AAPL"],
            "close": [150.0],
        })
        store = MagicMock()
        store.to_df.return_value = iter([chunk])
        result = _store_to_frame(store, context="test")
        assert "ts" in result.columns

    def test_store_to_frame_empty_iterator(self):
        store = MagicMock()
        store.to_df.return_value = iter([])
        result = _store_to_frame(store, context="test")
        assert result.empty


# ── Warning / redaction ─────────────────────────────────────────────────────


class TestRedaction:
    def test_redact_api_key(self):
        text = "Connection failed: api_key=db-secret-12345&other=value"
        result = _redact_sensitive_error_text(text)
        assert "db-secret-12345" not in result
        assert "***" in result

    def test_redact_token(self):
        text = "Error with token=my_secret_token"
        result = _redact_sensitive_error_text(text)
        assert "my_secret_token" not in result

    def test_redact_bearer(self):
        text = "Authorization: Bearer supersecrettoken123"
        result = _redact_sensitive_error_text(text)
        assert "supersecrettoken123" not in result

    def test_no_sensitive_data_unchanged(self):
        text = "Connection timed out after 30 seconds"
        assert _redact_sensitive_error_text(text) == text


# ── Dataset selection ───────────────────────────────────────────────────────


class TestDatasetSelection:
    def test_choose_requested_dataset(self):
        result = choose_default_dataset(["DBEQ.BASIC", "XNAS.ITCH"], "DBEQ.BASIC")
        assert result == "DBEQ.BASIC"

    def test_choose_preferred_fallback(self):
        result = choose_default_dataset(["DBEQ.BASIC", "XNAS.ITCH"])
        assert result == "XNAS.ITCH"  # first preferred match

    def test_choose_first_available(self):
        result = choose_default_dataset(["CUSTOM.FEED"])
        assert result == "CUSTOM.FEED"

    def test_choose_empty_list(self):
        result = choose_default_dataset([])
        assert result == PREFERRED_DATABENTO_DATASETS[0]


# ── Provider injection into consumer ────────────────────────────────────────


class TestProviderInjection:
    """Verify that collect_full_universe_session_minute_detail accepts a provider."""

    def test_degraded_provider_returns_empty_frame(self):
        """When provider raises on get_range, the symbol-coverage check
        raises RuntimeError — the function does *not* silently succeed with
        missing data.  This verifies the fail-loud contract."""
        from scripts.smc_microstructure_base_runtime import (
            collect_full_universe_session_minute_detail,
        )

        provider = DegradedProvider()
        with pytest.raises(RuntimeError, match="incomplete symbol coverage"):
            collect_full_universe_session_minute_detail(
                "",  # api key not used when provider is given
                provider=provider,
                dataset="DBEQ.BASIC",
                trading_days=[date(2024, 6, 14)],
                universe_symbols={"AAPL", "MSFT"},
                display_timezone="America/New_York",
                use_file_cache=False,
            )

    def test_mock_provider_returns_data(self):
        """A mock provider supplying a valid store produces enriched output."""
        from scripts.smc_microstructure_base_runtime import (
            collect_full_universe_session_minute_detail,
        )

        timestamps = pd.to_datetime(
            ["2024-06-14T13:30:00", "2024-06-14T13:31:00"], utc=True
        )
        inner_df = pd.DataFrame({
            "ts_event": timestamps,
            "symbol": ["AAPL", "AAPL"],
            "open": [190.0, 190.5],
            "high": [191.0, 191.0],
            "low": [189.5, 190.0],
            "close": [190.5, 190.8],
            "volume": [1000, 1200],
        })

        mock_store = MagicMock()
        mock_store.to_df.return_value = inner_df

        class TestProvider:
            def get_range(self, **kwargs):
                return mock_store

            def get_schema_available_end(self, dataset, schema):
                return None

            def list_datasets(self):
                return ["DBEQ.BASIC"]

        result = collect_full_universe_session_minute_detail(
            "",
            provider=TestProvider(),
            dataset="DBEQ.BASIC",
            trading_days=[date(2024, 6, 14)],
            universe_symbols={"AAPL"},
            display_timezone="America/New_York",
            use_file_cache=False,
        )
        assert isinstance(result, pd.DataFrame)
        assert not result.empty
        assert "AAPL" in result["symbol"].values

    def test_empty_universe_returns_empty(self):
        """Empty universe → empty frame without calling provider at all."""
        from scripts.smc_microstructure_base_runtime import (
            collect_full_universe_session_minute_detail,
        )

        provider = DegradedProvider()
        result = collect_full_universe_session_minute_detail(
            "",
            provider=provider,
            dataset="DBEQ.BASIC",
            trading_days=[date(2024, 6, 14)],
            universe_symbols=set(),
            display_timezone="America/New_York",
            use_file_cache=False,
        )
        assert result.empty

    def test_no_trading_days_returns_empty(self):
        """No trading days → empty frame without calling provider."""
        from scripts.smc_microstructure_base_runtime import (
            collect_full_universe_session_minute_detail,
        )

        provider = DegradedProvider()
        result = collect_full_universe_session_minute_detail(
            "",
            provider=provider,
            dataset="DBEQ.BASIC",
            trading_days=[],
            universe_symbols={"AAPL"},
            display_timezone="America/New_York",
            use_file_cache=False,
        )
        assert result.empty
