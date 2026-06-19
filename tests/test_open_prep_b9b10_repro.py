"""Regression tests for B9/B10 open-prep findings."""
import math
from datetime import date
from unittest.mock import MagicMock
import pytest
from open_prep.run_open_prep import (
    _add_pdh_pdl_context,
    _calculate_atr14_from_eod,
    _fetch_symbol_atr,
    _momentum_z_score_from_eod,
    _parse_calendar_date,
)

class TestParseCalendarDateInvariants:
    def test_rejects_slash_delimited_year_first(self):
        assert _parse_calendar_date("2024/01/03") is None
    def test_rejects_iso_week_date(self):
        assert _parse_calendar_date("2024-W01-1") is None
    def test_rejects_trailing_t(self):
        assert _parse_calendar_date("2024-01-01T") is None
    def test_idempotent_iso(self):
        d = date(2024, 1, 15)
        assert _parse_calendar_date(d.isoformat()) == d

class TestChronologicalSortingEverywhere:
    def test_fetch_symbol_atr_selects_latest_vwap_chronologically(self):
        mock_client = MagicMock()
        mock_client.get_historical_price_eod_full.return_value = [
            {"date": "2024-01-10", "close": 110.0, "high": 111.0, "low": 109.0, "vwap": 110.0, "volume": 1000},
            {"date": "2024-1-2",  "close": 102.0, "high": 103.0, "low": 101.0, "vwap": 102.0, "volume": 1000},
            {"date": "2024-01-03", "close": 103.0, "high": 104.0, "low": 102.0, "vwap": 103.0, "volume": 1000},
        ]
        sym, atr, mom, vwap, avgvol, err = _fetch_symbol_atr(
            mock_client, "AAPL", date(2024, 1, 1), date(2024, 1, 10), 14
        )
        assert vwap == pytest.approx(110.0), f"expected latest chronological VWAP 110.0, got {vwap}"

    def test_momentum_z_score_duplicate_dates_are_deduplicated(self):
        candles = [
            {"date": "2024-01-01", "close": 100.0},
            {"date": "2024-01-02", "close": 101.0},
            {"date": "2024-01-03", "close": 102.0},
            {"date": "2024-01-04", "close": 103.0},
            {"date": "2024-01-05", "close": 104.0},
            {"date": "2024-01-06", "close": 105.0},
            {"date": "2024-01-07", "close": 106.0},
            {"date": "2024-01-07", "close": 106.0},
            {"date": "2024-01-08", "close": 107.0},
        ]
        z = _momentum_z_score_from_eod(candles)
        assert isinstance(z, float)
        assert not math.isnan(z)

class TestAtrDataQuality:
    def test_atr_rejects_negative_ohlc(self):
        candles = [
            {"date": f"2024-02-{i:02d}", "high": -5.0 + i, "low": -6.0 + i, "close": -5.5 + i}
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
        assert not math.isinf(atr)
        assert not math.isnan(atr)

class TestPdhPdlDataQuality:
    def test_pdh_pdl_rejects_inf_values(self):
        q = {"price": 150.0, "atr": 3.0, "previousDayHigh": float("inf"), "previousDayLow": float("inf")}
        _add_pdh_pdl_context(q)
        dist_pdh = q.get("dist_to_pdh_atr")
        dist_pdl = q.get("dist_to_pdl_atr")
        assert dist_pdh is None or not math.isinf(dist_pdh)
        assert dist_pdl is None or not math.isinf(dist_pdl)

    def test_momentum_rejects_inf_close(self):
        candles = [{"date": f"2024-01-{i:02d}", "close": 100.0 + i} for i in range(1, 25)]
        candles[5]["close"] = float("inf")
        z = _momentum_z_score_from_eod(candles)
        assert not math.isnan(z)
