"""FMP re-sourcing of the outlook scorer + power-gap classifier.

2026-07-09: the Benzinga free key is being replaced by Massive (which has no
earnings/economics route), so ``fetch_fmp_earnings`` replaces the retired
Benzinga earnings path in ``_compute_outlook_for_date`` and ``compute_power_gaps``.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import terminal_poller as tp


def _fmp_client(rows: list[dict]) -> MagicMock:
    client = MagicMock()
    client.get_earnings_calendar.return_value = rows
    return client


class TestFetchFmpEarnings:
    def test_maps_fields_and_derives_eps_surprise(self):
        rows = [{
            "symbol": "aapl", "date": "2026-07-09",
            "epsActual": 1.5, "epsEstimated": 1.2,
            "revenueActual": 1e9, "revenueEstimated": 9e8,
        }]
        with patch.object(tp, "_make_fmp_client", return_value=_fmp_client(rows)):
            out = tp.fetch_fmp_earnings("k", "2026-07-09", "2026-07-09")
        assert len(out) == 1
        r = out[0]
        assert r["ticker"] == "AAPL"          # upper-cased
        assert r["date"] == "2026-07-09"
        assert r["earnings_timing"] is None    # FMP /stable has no bmo/amc field
        assert round(r["eps_surprise"], 4) == 0.3            # 1.5 - 1.2
        assert round(r["eps_surprise_percent"], 2) == 25.0   # 0.3 / 1.2 * 100

    def test_null_actual_yields_zero_surprise(self):
        rows = [{"symbol": "NVDA", "date": "2026-07-09", "epsActual": None, "epsEstimated": 0.9}]
        with patch.object(tp, "_make_fmp_client", return_value=_fmp_client(rows)):
            out = tp.fetch_fmp_earnings("k", "2026-07-09", "2026-07-09")
        assert out[0]["eps_surprise"] == 0.0
        assert out[0]["eps_surprise_percent"] == 0.0

    def test_skips_rows_without_symbol_and_non_dicts(self):
        rows = [{"symbol": "", "epsActual": 1.0}, "not-a-dict", {"date": "x"}]
        with patch.object(tp, "_make_fmp_client", return_value=_fmp_client(rows)):
            out = tp.fetch_fmp_earnings("k", "2026-07-09", "2026-07-09")
        assert out == []

    def test_fail_soft_on_client_error(self):
        client = MagicMock()
        client.get_earnings_calendar.side_effect = RuntimeError("boom")
        with patch.object(tp, "_make_fmp_client", return_value=client):
            assert tp.fetch_fmp_earnings("k", "2026-07-09", "2026-07-09") == []


class TestComputePowerGapsUsesFmp:
    @patch("terminal_poller.fetch_fmp_earnings")
    @patch("terminal_poller.fetch_benzinga_market_movers")
    def test_peg_classified_from_fmp_earnings_beat(self, mock_movers, mock_earn):
        mock_movers.return_value = {
            "gainers": [{"symbol": "AAPL", "changePercent": 6.0,
                         "volume": 3_000_000, "averageVolume": 1_000_000}],
            "losers": [],
        }
        mock_earn.return_value = [{"ticker": "AAPL", "eps_surprise": 0.3, "eps_surprise_percent": 25.0}]

        out = tp.compute_power_gaps("bz-or-massive-key", "fmp-key", peg_min_gap=4.0, peg_min_rvol=1.5)

        # earnings came from FMP, using the fmp key (positional arg 0)
        mock_earn.assert_called_once()
        assert mock_earn.call_args.args[0] == "fmp-key"
        aapl = next(r for r in out if r["symbol"] == "AAPL")
        assert aapl["gap_type"] == "PEG"          # gap≥4, beat, rvol≥1.5
        assert aapl["has_earnings"] is True
        assert aapl["eps_surprise"] == 0.3


class TestOutlookUsesFmp:
    @patch("terminal_poller.fetch_sector_performance", return_value=[])
    @patch("terminal_poller.fetch_economic_calendar", return_value=[])
    @patch("terminal_poller.fetch_fmp_earnings")
    def test_outlook_sources_earnings_from_fmp_only(self, mock_earn, _econ, _sector):
        from datetime import date

        mock_earn.return_value = [
            {"ticker": f"S{i}", "date": "2026-07-09", "earnings_timing": None,
             "eps_surprise": 0.0, "eps_surprise_percent": 0.0}
            for i in range(25)
        ]
        # New signature: (target_date, fmp_api_key) — no bz_api_key
        result = tp._compute_outlook_for_date(date(2026, 7, 9), "fmp-key")

        mock_earn.assert_called_once()
        assert mock_earn.call_args.args[0] == "fmp-key"
        assert result["earnings_count"] == 25
        # BMO removed 2026-07-10 (FMP has no bmo/amc timing, no other source has it)
        assert "earnings_bmo_count" not in result
