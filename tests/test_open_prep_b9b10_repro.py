"""Regression tests for actionable findings in PR #2856 audit."""
import json
import math
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from open_prep import run_open_prep
from open_prep.run_open_prep import (
    _add_pdh_pdl_context,
    _calculate_atr14_from_eod,
    _calendar_date_sort_key,
    _compute_gap_for_quote,
    _fetch_symbol_atr,
    _incremental_atr_from_eod_bulk,
    _load_atr_cache,
    _momentum_z_score_from_eod,
    _parse_calendar_date,
)


class TestParseCalendarDateInvariants:
    def test_rejects_slash_delimited_year_first(self):
        # YYYY/MM/DD is a supported legacy format (also accepted by the original
        # parser and used by some providers) — must not return None.
        assert _parse_calendar_date("2024/01/03") == date(2024, 1, 3)

    def test_rejects_iso_week_date(self):
        assert _parse_calendar_date("2024-W01-1") is None

    def test_rejects_trailing_t(self):
        assert _parse_calendar_date("2024-01-01T") is None

    def test_idempotent_iso(self):
        d = date(2024, 1, 15)
        assert _parse_calendar_date(d.isoformat()) == d


class TestChronologicalSortingEverywhere:
    def test_calendar_sort_key_orders_mixed_provider_dates_chronologically(self):
        rows = [
            {"symbol": "A", "date": "2024-01-10"},
            {"symbol": "B", "date": "2024-1-2"},
            {"symbol": "C", "date": "2024-01-03"},
        ]
        rows.sort(key=lambda x: (_calendar_date_sort_key(x.get("date")), x.get("symbol") or ""))
        assert [r["symbol"] for r in rows] == ["B", "C", "A"]

    def test_fetch_symbol_atr_selects_latest_vwap_chronologically(self):
        mock_client = MagicMock()
        mock_client.get_historical_price_eod_full.return_value = [
            {"date": "2024-01-10", "close": 110.0, "high": 111.0, "low": 109.0, "vwap": 110.0, "volume": 1000},
            {"date": "2024-1-2", "close": 102.0, "high": 103.0, "low": 101.0, "vwap": 102.0, "volume": 1000},
            {"date": "2024-01-03", "close": 103.0, "high": 104.0, "low": 102.0, "vwap": 103.0, "volume": 1000},
        ]
        _sym, _atr, _mom, vwap, _avgvol, _err = _fetch_symbol_atr(
            mock_client, "AAPL", date(2024, 1, 1), date(2024, 1, 10), 14
        )
        assert vwap == pytest.approx(110.0), f"expected latest chronological VWAP 110.0, got {vwap}"


class TestAtrDataQuality:
    def test_atr_rejects_negative_ohlc(self):
        candles = [
            {"date": f"2024-02-{i:02d}", "high": -5.0, "low": -6.0, "close": -5.5}
            for i in range(1, 25)
        ]
        atr = _calculate_atr14_from_eod(candles)
        assert atr == 0.0, f"expected 0 for negative OHLC, got {atr}"

    def test_atr_rejects_low_greater_than_high(self):
        candles = [
            {"date": f"2024-02-{i:02d}", "high": 9.0, "low": 10.0, "close": 9.5}
            for i in range(1, 25)
        ]
        atr = _calculate_atr14_from_eod(candles)
        assert atr == 0.0, f"expected 0 for low>high, got {atr}"

    def test_atr_rejects_inf_values(self):
        candles = [
            {"date": f"2024-02-{i:02d}", "high": float("inf"), "low": 9.0, "close": 9.5}
            for i in range(1, 25)
        ]
        atr = _calculate_atr14_from_eod(candles)
        assert atr == 0.0


class TestMomentumAndFetchSanitizing:
    def test_momentum_rejects_inf_close(self):
        candles = [{"date": f"2024-01-{i:02d}", "close": 100.0 + i} for i in range(1, 25)]
        candles[5]["close"] = float("inf")
        z = _momentum_z_score_from_eod(candles)
        assert math.isfinite(z)

    def test_fetch_symbol_atr_sanitizes_non_finite_momentum(self):
        mock_client = MagicMock()
        candles = [
            {
                "date": f"2024-01-{i:02d}",
                "close": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "vwap": 100.0 + i,
                "volume": 1000,
            }
            for i in range(1, 25)
        ]
        candles[5]["close"] = float("inf")
        mock_client.get_historical_price_eod_full.return_value = candles

        _sym, _atr, mom, _vwap, _avgvol, _err = _fetch_symbol_atr(
            mock_client,
            "AAPL",
            date(2024, 1, 1),
            date(2024, 1, 25),
            14,
        )
        assert math.isfinite(mom)


class TestPdhPdlDataQuality:
    def test_pdh_pdl_rejects_inf_values(self):
        q = {
            "price": 150.0,
            "atr": 3.0,
            "previousDayHigh": float("inf"),
            "previousDayLow": float("inf"),
        }
        _add_pdh_pdl_context(q)
        assert q.get("dist_to_pdh_atr") is None
        assert q.get("dist_to_pdl_atr") is None



class TestIncrementalAtrNonFinite:
    """Bug #2 – _incremental_atr_from_eod_bulk must reject inf prev_close."""

    def test_incremental_atr_rejects_non_finite_prev_close(self, tmp_path):
        original_cache_dir = run_open_prep.ATR_CACHE_DIR
        try:
            run_open_prep.ATR_CACHE_DIR = tmp_path
            cache_file = tmp_path / "2024-01-12_p14.json"
            cache_file.write_text(
                json.dumps(
                    {
                        "as_of": "2024-01-12",
                        "atr_period": 14,
                        "atr14_by_symbol": {"AAPL": 2.5},
                        "momentum_z_by_symbol": {"AAPL": 0.5},
                        "prev_close_by_symbol": {"AAPL": float("inf")},
                    },
                    allow_nan=True,
                ),
                encoding="utf-8",
            )
            client = MagicMock()
            client.get_eod_bulk.return_value = [
                {
                    "symbol": "AAPL",
                    "date": "2024-01-15",
                    "high": 105.0,
                    "low": 103.0,
                    "close": 104.0,
                }
            ]
            atr_map, _, _ = _incremental_atr_from_eod_bulk(
                client=client,
                symbols=["AAPL"],
                as_of=date(2024, 1, 15),
                atr_period=14,
            )
            assert "AAPL" not in atr_map, (
                f"Expected AAPL to be skipped (inf prev_close), got atr_map={atr_map}"
            )
        finally:
            run_open_prep.ATR_CACHE_DIR = original_cache_dir

    def test_incremental_atr_rejects_non_finite_prev_atr(self, tmp_path):
        original_cache_dir = run_open_prep.ATR_CACHE_DIR
        try:
            run_open_prep.ATR_CACHE_DIR = tmp_path
            cache_file = tmp_path / "2024-01-12_p14.json"
            cache_file.write_text(
                json.dumps(
                    {
                        "as_of": "2024-01-12",
                        "atr_period": 14,
                        "atr14_by_symbol": {"AAPL": float("inf")},
                        "momentum_z_by_symbol": {"AAPL": 0.5},
                        "prev_close_by_symbol": {"AAPL": 150.0},
                    },
                    allow_nan=True,
                ),
                encoding="utf-8",
            )
            client = MagicMock()
            client.get_eod_bulk.return_value = [
                {
                    "symbol": "AAPL",
                    "date": "2024-01-15",
                    "high": 155.0,
                    "low": 148.0,
                    "close": 152.0,
                }
            ]
            atr_map, _, _ = _incremental_atr_from_eod_bulk(
                client=client,
                symbols=["AAPL"],
                as_of=date(2024, 1, 15),
                atr_period=14,
            )
            assert "AAPL" not in atr_map, (
                f"Expected AAPL skipped (inf prev_atr), got atr_map={atr_map}"
            )
        finally:
            run_open_prep.ATR_CACHE_DIR = original_cache_dir


class TestLoadAtrCacheFiltersNonFinite:
    """Bug #3 – _load_atr_cache must drop inf/negative entries from all maps."""

    def test_load_atr_cache_filters_non_finite_values(self, tmp_path):
        original_cache_dir = run_open_prep.ATR_CACHE_DIR
        try:
            run_open_prep.ATR_CACHE_DIR = tmp_path
            cache_file = tmp_path / "2024-01-15_p14.json"
            cache_file.write_text(
                json.dumps(
                    {
                        "as_of": "2024-01-15",
                        "atr_period": 14,
                        "atr14_by_symbol": {
                            "AAPL": float("inf"),
                            "MSFT": -2.5,
                            "GOOG": 3.0,
                        },
                        "momentum_z_by_symbol": {
                            "AAPL": 0.5,
                            "MSFT": 0.5,
                            "GOOG": float("inf"),
                        },
                        "prev_close_by_symbol": {
                            "AAPL": 100.0,
                            "MSFT": 100.0,
                            "GOOG": 150.0,
                        },
                    },
                    allow_nan=True,
                ),
                encoding="utf-8",
            )
            atr_map, momentum_map, _prev_close_map = _load_atr_cache(date(2024, 1, 15), 14)
            # AAPL and MSFT should be filtered (inf ATR / negative ATR)
            assert "AAPL" not in atr_map, "inf ATR must be filtered"
            assert "MSFT" not in atr_map, "negative ATR must be filtered"
            # GOOG is in atr_map but has inf momentum; momentum entry should be absent
            assert "GOOG" in atr_map
            assert "GOOG" not in momentum_map, "inf momentum_z must be filtered"
        finally:
            run_open_prep.ATR_CACHE_DIR = original_cache_dir

    def test_load_atr_cache_filters_non_finite_prev_close(self, tmp_path):
        original_cache_dir = run_open_prep.ATR_CACHE_DIR
        try:
            run_open_prep.ATR_CACHE_DIR = tmp_path
            cache_file = tmp_path / "2024-01-15_p14.json"
            cache_file.write_text(
                json.dumps(
                    {
                        "as_of": "2024-01-15",
                        "atr_period": 14,
                        "atr14_by_symbol": {"AAPL": 2.5},
                        "momentum_z_by_symbol": {"AAPL": 0.3},
                        "prev_close_by_symbol": {"AAPL": float("inf")},
                    },
                    allow_nan=True,
                ),
                encoding="utf-8",
            )
            _, _, prev_close_map = _load_atr_cache(date(2024, 1, 15), 14)
            assert "AAPL" not in prev_close_map, "inf prev_close must be filtered"
        finally:
            run_open_prep.ATR_CACHE_DIR = original_cache_dir


class TestComputeGapNonFinitePrevClose:
    """Bug #4 – _compute_gap_for_quote must treat inf previousClose as missing."""

    def test_compute_gap_rejects_inf_prev_close(self):
        q = {
            "symbol": "A",
            "price": 100.0,
            "previousClose": float("inf"),
            "open": 105.0,
        }
        run_dt = datetime(2024, 1, 2, 14, 30)
        res = _compute_gap_for_quote(
            q,
            run_dt_utc=run_dt,
            gap_mode="RTH_OPEN",
            gap_scope="DAILY",
        )
        assert res["gap_reason"] == "missing_previous_close", (
            f"Expected missing_previous_close, got {res['gap_reason']!r}"
        )
        assert math.isfinite(res["gap_pct"]), (
            f"gap_pct must be finite, got {res['gap_pct']!r}"
        )
