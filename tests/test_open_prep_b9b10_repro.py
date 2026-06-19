"""Regression tests for actionable findings in PR #2856 audit."""
import math
from datetime import date
from unittest.mock import MagicMock

import pytest

from open_prep.run_open_prep import (
    _add_pdh_pdl_context,
    _calculate_atr14_from_eod,
    _calendar_date_sort_key,
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

