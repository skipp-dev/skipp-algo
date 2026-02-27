"""Tests for terminal_spike_scanner.py.

Covers all pure functions: spike classification, volume detection,
formatting, asset type heuristics, row building, and filtering.
"""

from __future__ import annotations

from typing import Any

from terminal_spike_scanner import (
    _safe_float,
    asset_type_label,
    build_spike_rows,
    classify_spike,
    classify_volume_spike,
    filter_spike_rows,
    format_change_pct,
    format_market_cap,
    market_session,
    overlay_extended_hours_quotes,
    spike_icon,
    volume_icon,
)

# ── Helpers ─────────────────────────────────────────────────────


def _raw(
    symbol: str = "AAPL",
    changesPercentage: float = 2.5,
    change: float = 4.0,
    price: float = 175.0,
    volume: float = 50_000_000,
    avgVolume: float = 25_000_000,
    marketCap: float = 2.8e12,
    name: str = "Apple Inc.",
) -> dict[str, Any]:
    """Factory for a raw FMP quote dict."""
    return {
        "symbol": symbol,
        "changesPercentage": changesPercentage,
        "change": change,
        "price": price,
        "volume": volume,
        "avgVolume": avgVolume,
        "marketCap": marketCap,
        "name": name,
    }


# ═══════════════════════════════════════════════════════════════
# classify_spike
# ═══════════════════════════════════════════════════════════════


class TestClassifySpike:
    def test_up_spike(self):
        assert classify_spike(2.5) == "UP"

    def test_down_spike(self):
        assert classify_spike(-3.0) == "DOWN"

    def test_below_threshold_no_spike(self):
        assert classify_spike(0.5) == ""

    def test_boundary_exactly_threshold(self):
        assert classify_spike(1.0) == "UP"

    def test_negative_boundary(self):
        assert classify_spike(-1.0) == "DOWN"

    def test_zero_no_spike(self):
        assert classify_spike(0.0) == ""

    def test_custom_threshold(self):
        assert classify_spike(1.5, price_spike_threshold=2.0) == ""
        assert classify_spike(2.5, price_spike_threshold=2.0) == "UP"

    def test_large_spike(self):
        assert classify_spike(15.0) == "UP"
        assert classify_spike(-20.0) == "DOWN"


# ═══════════════════════════════════════════════════════════════
# classify_volume_spike
# ═══════════════════════════════════════════════════════════════


class TestClassifyVolumeSpike:
    def test_spike(self):
        assert classify_volume_spike(100, 40) is True

    def test_no_spike(self):
        assert classify_volume_spike(50, 40) is False

    def test_boundary(self):
        assert classify_volume_spike(80, 40) is True  # 2.0x exact

    def test_zero_avg_volume(self):
        assert classify_volume_spike(100, 0) is False

    def test_negative_avg_volume(self):
        assert classify_volume_spike(100, -10) is False

    def test_custom_ratio(self):
        assert classify_volume_spike(100, 40, volume_spike_ratio=3.0) is False
        assert classify_volume_spike(130, 40, volume_spike_ratio=3.0) is True


# ═══════════════════════════════════════════════════════════════
# Icons
# ═══════════════════════════════════════════════════════════════


class TestIcons:
    def test_spike_up(self):
        assert spike_icon("UP") == "🟢"

    def test_spike_down(self):
        assert spike_icon("DOWN") == "🔴"

    def test_spike_none(self):
        assert spike_icon("") == "⚪"

    def test_volume_spike(self):
        assert volume_icon(True) == "📊"

    def test_volume_no_spike(self):
        assert volume_icon(False) == ""


# ═══════════════════════════════════════════════════════════════
# Formatting
# ═══════════════════════════════════════════════════════════════


class TestFormatChangePct:
    def test_positive(self):
        result = format_change_pct(2.5)
        assert ":green[" in result
        assert "+2.50%" in result

    def test_negative(self):
        result = format_change_pct(-3.14)
        assert ":red[" in result
        assert "-3.14%" in result

    def test_zero(self):
        assert format_change_pct(0.0) == "0.00%"


class TestFormatMarketCap:
    def test_trillion(self):
        assert format_market_cap(2.8e12) == "2.8T"

    def test_billion(self):
        assert format_market_cap(1.5e9) == "1.5B"

    def test_million(self):
        assert format_market_cap(450e6) == "450M"

    def test_small(self):
        assert format_market_cap(50000) == "50,000"

    def test_none(self):
        assert format_market_cap(None) == "—"

    def test_zero(self):
        assert format_market_cap(0) == "—"

    def test_negative(self):
        assert format_market_cap(-100) == "—"


class TestAssetTypeLabel:
    def test_stock(self):
        assert asset_type_label("AAPL", "Apple Inc.") == "STOCK"

    def test_etf_by_name(self):
        assert asset_type_label("SPY", "SPDR S&P 500 ETF Trust") == "ETF"

    def test_etf_fund(self):
        assert asset_type_label("VTI", "Vanguard Total Stock Market Index Fund") == "ETF"

    def test_no_name(self):
        assert asset_type_label("AAPL") == "STOCK"


# ═══════════════════════════════════════════════════════════════
# _safe_float
# ═══════════════════════════════════════════════════════════════


class TestSafeFloat:
    def test_float(self):
        assert _safe_float(3.14) == 3.14

    def test_int(self):
        assert _safe_float(42) == 42.0

    def test_string(self):
        assert _safe_float("2.5") == 2.5

    def test_none(self):
        assert _safe_float(None) == 0.0

    def test_invalid_string(self):
        assert _safe_float("abc") == 0.0

    def test_custom_default(self):
        assert _safe_float(None, default=-1.0) == -1.0


# ═══════════════════════════════════════════════════════════════
# build_spike_rows
# ═══════════════════════════════════════════════════════════════


class TestBuildSpikeRows:
    def test_basic_gainer(self):
        rows = build_spike_rows(
            [_raw(symbol="AAPL", changesPercentage=5.0)], [], [],
        )
        assert len(rows) == 1
        assert rows[0]["symbol"] == "AAPL"
        assert rows[0]["spike_dir"] == "UP"
        assert rows[0]["source"] == "gainer"

    def test_basic_loser(self):
        rows = build_spike_rows(
            [], [_raw(symbol="TSLA", changesPercentage=-4.0)], [],
        )
        assert len(rows) == 1
        assert rows[0]["spike_dir"] == "DOWN"
        assert rows[0]["source"] == "loser"

    def test_most_active(self):
        rows = build_spike_rows(
            [], [], [_raw(symbol="GME", changesPercentage=0.5)],
        )
        assert len(rows) == 1
        assert rows[0]["source"] == "active"
        assert rows[0]["spike_dir"] == ""  # below threshold

    def test_dedup_across_sources(self):
        rows = build_spike_rows(
            [_raw(symbol="AAPL", changesPercentage=3.0)],
            [],
            [_raw(symbol="AAPL", changesPercentage=3.0)],
        )
        assert len(rows) == 1  # deduped

    def test_sorted_by_abs_change(self):
        rows = build_spike_rows(
            [_raw(symbol="A", changesPercentage=2.0)],
            [_raw(symbol="B", changesPercentage=-5.0)],
            [_raw(symbol="C", changesPercentage=3.0)],
        )
        assert rows[0]["symbol"] == "B"  # 5% > 3% > 2%
        assert rows[1]["symbol"] == "C"

    def test_limit(self):
        gainers = [_raw(symbol=f"T{i}", changesPercentage=float(i))
                   for i in range(60)]
        rows = build_spike_rows(gainers, [], [], limit=10)
        assert len(rows) == 10

    def test_volume_spike_detection(self):
        rows = build_spike_rows(
            [_raw(volume=100000, avgVolume=20000)], [], [],
        )
        assert rows[0]["vol_spike"] is True
        assert rows[0]["volume_ratio"] == 5.0

    def test_no_volume_spike(self):
        rows = build_spike_rows(
            [_raw(volume=30000, avgVolume=25000)], [], [],
        )
        assert rows[0]["vol_spike"] is False

    def test_market_cap_formatting(self):
        rows = build_spike_rows(
            [_raw(marketCap=2.8e12)], [], [],
        )
        assert rows[0]["mktcap_display"] == "2.8T"

    def test_empty_inputs(self):
        rows = build_spike_rows([], [], [])
        assert rows == []

    def test_missing_fields_safe(self):
        rows = build_spike_rows([{"symbol": "X"}], [], [])
        assert len(rows) == 1
        assert rows[0]["price"] == 0.0
        assert rows[0]["change_pct"] == 0.0

    def test_change_display_formatting(self):
        rows = build_spike_rows(
            [_raw(changesPercentage=2.5)], [], [],
        )
        assert ":green[" in rows[0]["change_display"]

    def test_asset_type_detected(self):
        rows = build_spike_rows(
            [_raw(name="SPDR S&P 500 ETF Trust")], [], [],
        )
        assert rows[0]["asset_type"] == "ETF"

    def test_custom_thresholds(self):
        rows = build_spike_rows(
            [_raw(changesPercentage=1.5)], [], [],
            price_spike_threshold=2.0,
        )
        assert rows[0]["spike_dir"] == ""


# ═══════════════════════════════════════════════════════════════
# filter_spike_rows
# ═══════════════════════════════════════════════════════════════


class TestFilterSpikeRows:
    def _rows(self) -> list[dict[str, Any]]:
        return build_spike_rows(
            [
                _raw(symbol="AAPL", changesPercentage=5.0, volume=100000, avgVolume=20000),
                _raw(symbol="MSFT", changesPercentage=1.5, volume=30000, avgVolume=25000),
            ],
            [
                _raw(symbol="TSLA", changesPercentage=-4.0, volume=80000, avgVolume=30000),
            ],
            [
                _raw(symbol="SPY", changesPercentage=0.3, volume=50000, avgVolume=40000,
                     name="SPDR S&P 500 ETF Trust"),
            ],
        )

    def test_no_filter(self):
        rows = self._rows()
        assert len(filter_spike_rows(rows)) == 4

    def test_direction_up(self):
        result = filter_spike_rows(self._rows(), direction="UP")
        assert all(r["spike_dir"] == "UP" for r in result)

    def test_direction_down(self):
        result = filter_spike_rows(self._rows(), direction="DOWN")
        assert all(r["spike_dir"] == "DOWN" for r in result)

    def test_min_change(self):
        result = filter_spike_rows(self._rows(), min_change_pct=3.0)
        assert all(abs(r["change_pct"]) >= 3.0 for r in result)

    def test_asset_type_stock(self):
        result = filter_spike_rows(self._rows(), asset_type="STOCK")
        assert all(r["asset_type"] == "STOCK" for r in result)

    def test_asset_type_etf(self):
        result = filter_spike_rows(self._rows(), asset_type="ETF")
        assert all(r["asset_type"] == "ETF" for r in result)

    def test_vol_spike_only(self):
        result = filter_spike_rows(self._rows(), vol_spike_only=True)
        assert all(r["vol_spike"] for r in result)

    def test_combined_filters(self):
        result = filter_spike_rows(
            self._rows(),
            direction="UP",
            min_change_pct=2.0,
            asset_type="STOCK",
        )
        assert len(result) == 1
        assert result[0]["symbol"] == "AAPL"

    def test_no_match(self):
        result = filter_spike_rows(self._rows(), min_change_pct=50.0)
        assert result == []

    def test_empty_input(self):
        assert filter_spike_rows([]) == []


# ── Market session tests ────────────────────────────────────────


class TestMarketSession:
    def test_returns_valid_session(self):
        result = market_session()
        assert result in ("pre-market", "regular", "after-hours", "closed")

    def test_weekend_is_closed(self):
        from unittest.mock import patch
        from datetime import datetime
        from zoneinfo import ZoneInfo

        # Saturday 10:00 ET
        fake_sat = datetime(2026, 2, 28, 10, 0, tzinfo=ZoneInfo("America/New_York"))
        with patch("terminal_spike_scanner.datetime") as mock_dt:
            mock_dt.now.return_value = fake_sat
            assert market_session() == "closed"

    def test_premarket(self):
        from unittest.mock import patch
        from datetime import datetime
        from zoneinfo import ZoneInfo

        # Monday 7:00 ET
        fake_mon = datetime(2026, 3, 2, 7, 0, tzinfo=ZoneInfo("America/New_York"))
        with patch("terminal_spike_scanner.datetime") as mock_dt:
            mock_dt.now.return_value = fake_mon
            assert market_session() == "pre-market"

    def test_regular(self):
        from unittest.mock import patch
        from datetime import datetime
        from zoneinfo import ZoneInfo

        # Monday 12:00 ET
        fake_mon = datetime(2026, 3, 2, 12, 0, tzinfo=ZoneInfo("America/New_York"))
        with patch("terminal_spike_scanner.datetime") as mock_dt:
            mock_dt.now.return_value = fake_mon
            assert market_session() == "regular"

    def test_afterhours(self):
        from unittest.mock import patch
        from datetime import datetime
        from zoneinfo import ZoneInfo

        # Monday 17:00 ET
        fake_mon = datetime(2026, 3, 2, 17, 0, tzinfo=ZoneInfo("America/New_York"))
        with patch("terminal_spike_scanner.datetime") as mock_dt:
            mock_dt.now.return_value = fake_mon
            assert market_session() == "after-hours"

    def test_late_night_closed(self):
        from unittest.mock import patch
        from datetime import datetime
        from zoneinfo import ZoneInfo

        # Monday 22:00 ET
        fake_mon = datetime(2026, 3, 2, 22, 0, tzinfo=ZoneInfo("America/New_York"))
        with patch("terminal_spike_scanner.datetime") as mock_dt:
            mock_dt.now.return_value = fake_mon
            assert market_session() == "closed"


# ── Overlay extended-hours quotes tests ─────────────────────────


class TestOverlayExtendedHoursQuotes:
    @staticmethod
    def _make_rows() -> list[dict[str, Any]]:
        gainers = [
            _raw("ALBT", changesPercentage=114.48, change=0.58, price=1.09, volume=300000),
            _raw("TSLA", changesPercentage=3.5, change=8.0, price=236.0, volume=50000000),
        ]
        return build_spike_rows(gainers, [], [])

    def test_overlay_replaces_price_and_change(self):
        rows = self._make_rows()
        quotes = [
            {"symbol": "ALBT", "last": 0.75, "change": -0.34,
             "changePercent": -31.19, "volume": 2000000},
        ]
        overlay_extended_hours_quotes(rows, quotes)
        albt = next(r for r in rows if r["symbol"] == "ALBT")
        assert albt["price"] == 0.75
        assert albt["change"] == -0.34
        assert albt["change_pct"] == -31.19
        assert albt["spike_dir"] == "DOWN"

    def test_overlay_preserves_unmatched_rows(self):
        rows = self._make_rows()
        quotes = [
            {"symbol": "ALBT", "last": 0.75, "change": -0.34,
             "changePercent": -31.19, "volume": 2000000},
        ]
        overlay_extended_hours_quotes(rows, quotes)
        tsla = next(r for r in rows if r["symbol"] == "TSLA")
        assert tsla["change_pct"] == 3.5  # Unchanged

    def test_overlay_empty_quotes_is_noop(self):
        rows = self._make_rows()
        original_prices = {r["symbol"]: r["price"] for r in rows}
        overlay_extended_hours_quotes(rows, [])
        for r in rows:
            assert r["price"] == original_prices[r["symbol"]]

    def test_overlay_skips_zero_price_quotes(self):
        rows = self._make_rows()
        quotes = [{"symbol": "ALBT", "last": 0, "change": 0, "changePercent": 0}]
        overlay_extended_hours_quotes(rows, quotes)
        albt = next(r for r in rows if r["symbol"] == "ALBT")
        assert albt["price"] == 1.09  # Unchanged

    def test_overlay_resorts_by_abs_change(self):
        rows = self._make_rows()
        # ALBT was #1 with +114%, now becomes -31% (abs 31 < TSLA's 3.5? No, 31 > 3.5)
        # Actually ALBT at -31% is still bigger than TSLA at 3.5%
        quotes = [
            {"symbol": "ALBT", "last": 0.75, "change": -0.34,
             "changePercent": -31.19, "volume": 2000000},
        ]
        overlay_extended_hours_quotes(rows, quotes)
        assert rows[0]["symbol"] == "ALBT"  # Still first (31% > 3.5%)

    def test_overlay_marks_source_with_bz_suffix(self):
        rows = self._make_rows()
        quotes = [
            {"symbol": "ALBT", "last": 0.75, "change": -0.34,
             "changePercent": -31.19, "volume": 2000000},
        ]
        overlay_extended_hours_quotes(rows, quotes)
        albt = next(r for r in rows if r["symbol"] == "ALBT")
        assert "+bz" in albt["source"]

    def test_overlay_updates_volume_ratio(self):
        rows = self._make_rows()
        quotes = [
            {"symbol": "ALBT", "last": 0.75, "change": -0.34,
             "changePercent": -31.19, "volume": 5000000},
        ]
        overlay_extended_hours_quotes(rows, quotes)
        albt = next(r for r in rows if r["symbol"] == "ALBT")
        assert albt["volume"] == 5000000
