"""Tests for Benzinga VisiData enrichment and calendar export.

Covers:
- build_vd_snapshot() with bz_dividends, bz_guidance, bz_options enrichment
- build_vd_bz_calendar() for unified calendar JSONL
- save_vd_bz_calendar() atomic JSONL write
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

# Ensure project root is on the path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from terminal_export import (
    build_vd_bz_calendar,
    build_vd_snapshot,
    save_vd_bz_calendar,
)


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _make_feed_item(
    ticker: str = "AAPL",
    score: float = 0.8,
    headline: str = "Test headline",
    age_seconds: float = 60.0,
) -> dict[str, Any]:
    """Create a minimal feed item for build_vd_snapshot."""
    return {
        "ticker": ticker,
        "news_score": score,
        "published_ts": time.time() - age_seconds,
        "headline": headline,
        "url": f"https://example.com/{ticker}",
        "provider": "BZ",
        "sentiment_label": "bullish",
        "relevance": 0.9,
        "category": "earnings",
        "event_label": "beat",
        "materiality": "high",
        "impact": 3,
        "clarity": 4,
        "sentiment_score": 0.75,
        "polarity": 0.6,
        "age_minutes": age_seconds / 60.0,
        "recency_bucket": "fresh",
        "is_actionable": True,
    }


# ═══════════════════════════════════════════════════════════════
# build_vd_snapshot enrichment
# ═══════════════════════════════════════════════════════════════


class TestBuildVdSnapshotEnrichment:
    """Test Benzinga enrichment columns in build_vd_snapshot."""

    def test_enrichment_columns_present_without_data(self):
        """Enrichment columns should exist even when no BZ data provided."""
        feed = [_make_feed_item("AAPL")]
        rows = build_vd_snapshot(feed)
        assert len(rows) == 1
        row = rows[0]
        assert "div_exdate" in row
        assert "div_yield" in row
        assert "guid_eps" in row
        assert "options_flow" in row
        # Should be empty when no data
        assert row["div_exdate"] == ""
        assert row["div_yield"] == ""
        assert row["guid_eps"] == ""
        assert row["options_flow"] == ""

    def test_dividend_enrichment(self):
        """Dividend data should populate div_exdate and div_yield."""
        feed = [_make_feed_item("AAPL")]
        divs = [{"ticker": "AAPL", "ex_date": "2025-02-07", "dividend_yield": "0.55%"}]
        rows = build_vd_snapshot(feed, bz_dividends=divs)
        assert len(rows) == 1
        assert rows[0]["div_exdate"] == "2025-02-07"
        assert rows[0]["div_yield"] == "0.55%"

    def test_guidance_enrichment(self):
        """Guidance data should populate guid_eps."""
        feed = [_make_feed_item("NVDA")]
        guidance = [{"ticker": "NVDA", "eps_guidance_est": "1.50"}]
        rows = build_vd_snapshot(feed, bz_guidance=guidance)
        assert len(rows) == 1
        assert rows[0]["guid_eps"] == "1.50"

    def test_options_enrichment(self):
        """Options data should show 🎰 marker."""
        feed = [_make_feed_item("TSLA")]
        opts = [{"ticker": "TSLA", "type": "CALL", "strike": 200}]
        rows = build_vd_snapshot(feed, bz_options=opts)
        assert len(rows) == 1
        assert rows[0]["options_flow"] == "🎰"

    def test_no_options_match(self):
        """Options data for different ticker should not enrich."""
        feed = [_make_feed_item("AAPL")]
        opts = [{"ticker": "TSLA", "type": "CALL"}]
        rows = build_vd_snapshot(feed, bz_options=opts)
        assert rows[0]["options_flow"] == ""

    def test_all_enrichment_combined(self):
        """All enrichment sources combined."""
        feed = [_make_feed_item("AAPL")]
        divs = [{"ticker": "AAPL", "ex_date": "2025-03-01", "dividend_yield": "0.6%"}]
        guidance = [{"ticker": "AAPL", "eps_guidance_est": "2.10"}]
        opts = [{"ticker": "AAPL", "type": "CALL", "volume": 5000}]
        rows = build_vd_snapshot(
            feed, bz_dividends=divs, bz_guidance=guidance, bz_options=opts,
        )
        assert len(rows) == 1
        r = rows[0]
        assert r["div_exdate"] == "2025-03-01"
        assert r["div_yield"] == "0.6%"
        assert r["guid_eps"] == "2.10"
        assert r["options_flow"] == "🎰"

    def test_case_insensitive_ticker_match(self):
        """Ticker matching should be case-insensitive."""
        feed = [_make_feed_item("AAPL")]
        divs = [{"ticker": "aapl", "ex_date": "2025-02-07", "dividend_yield": "0.5%"}]
        rows = build_vd_snapshot(feed, bz_dividends=divs)
        assert rows[0]["div_exdate"] == "2025-02-07"

    def test_multiple_tickers_enrichment(self):
        """Different tickers get different enrichment data."""
        feed = [_make_feed_item("AAPL"), _make_feed_item("NVDA", score=0.9)]
        divs = [{"ticker": "AAPL", "ex_date": "2025-02-07", "dividend_yield": "0.5%"}]
        guidance = [{"ticker": "NVDA", "eps_guidance_est": "3.00"}]
        rows = build_vd_snapshot(feed, bz_dividends=divs, bz_guidance=guidance)
        assert len(rows) == 2
        aapl = next(r for r in rows if r["symbol"] == "AAPL")
        nvda = next(r for r in rows if r["symbol"] == "NVDA")
        assert aapl["div_exdate"] == "2025-02-07"
        assert aapl["guid_eps"] == ""
        assert nvda["div_exdate"] == ""
        assert nvda["guid_eps"] == "3.00"

    def test_backward_compat_no_enrichment_params(self):
        """Calling without enrichment params should work (backward compat)."""
        feed = [_make_feed_item("AAPL")]
        rows = build_vd_snapshot(feed, rt_quotes=None, bz_quotes=None, max_age_s=14400.0)
        assert len(rows) == 1
        assert "rank_score" in rows[0]
        assert "div_exdate" in rows[0]

    def test_enrichment_with_empty_lists(self):
        """Empty enrichment lists should not crash."""
        feed = [_make_feed_item("AAPL")]
        rows = build_vd_snapshot(feed, bz_dividends=[], bz_guidance=[], bz_options=[])
        assert len(rows) == 1
        assert rows[0]["div_exdate"] == ""


# ═══════════════════════════════════════════════════════════════
# build_vd_bz_calendar
# ═══════════════════════════════════════════════════════════════


class TestBuildVdBzCalendar:
    """Test unified BZ calendar builder."""

    def test_empty_inputs(self):
        """No data → empty list."""
        assert build_vd_bz_calendar() == []

    def test_none_inputs(self):
        """Explicit None → empty list."""
        assert build_vd_bz_calendar(
            bz_dividends=None, bz_splits=None, bz_ipos=None,
            bz_guidance=None, bz_retail=None,
        ) == []

    def test_dividends(self):
        divs = [{"ticker": "AAPL", "name": "Apple", "ex_date": "2025-02-07",
                 "dividend": "0.25", "dividend_yield": "0.55%"}]
        rows = build_vd_bz_calendar(bz_dividends=divs)
        assert len(rows) == 1
        assert rows[0]["type"] == "dividend"
        assert rows[0]["ticker"] == "AAPL"
        assert "0.25" in rows[0]["detail"]

    def test_splits(self):
        splits = [{"ticker": "NVDA", "name": "NVIDIA", "date_ex": "2024-06-10",
                   "ratio": "10:1"}]
        rows = build_vd_bz_calendar(bz_splits=splits)
        assert len(rows) == 1
        assert rows[0]["type"] == "split"
        assert "10:1" in rows[0]["detail"]

    def test_ipos(self):
        ipos = [{"ticker": "RDDT", "name": "Reddit", "pricing_date": "2024-03-21",
                 "price_min": 31, "price_max": 34, "deal_status": "Priced"}]
        rows = build_vd_bz_calendar(bz_ipos=ipos)
        assert len(rows) == 1
        assert rows[0]["type"] == "ipo"
        assert "31" in rows[0]["detail"]

    def test_guidance(self):
        guidance = [{"ticker": "AAPL", "name": "Apple", "date": "2025-01-30",
                     "period": "Q1", "period_year": "2025",
                     "eps_guidance_est": "1.50", "revenue_guidance_est": "120B"}]
        rows = build_vd_bz_calendar(bz_guidance=guidance)
        assert len(rows) == 1
        assert rows[0]["type"] == "guidance"
        assert "1.50" in rows[0]["detail"]
        assert "Q1 2025" in rows[0]["frequency"]

    def test_retail(self):
        retail = [{"ticker": "WMT", "name": "Walmart", "date": "2025-02-20",
                   "period": "Q4", "period_year": "2024",
                   "sss": "3.2%", "sss_est": "2.5%", "retail_surprise": "0.7%"}]
        rows = build_vd_bz_calendar(bz_retail=retail)
        assert len(rows) == 1
        assert rows[0]["type"] == "retail"
        assert "3.2%" in rows[0]["detail"]

    def test_combined_sorted_by_date(self):
        """All types combined, sorted by date descending."""
        divs = [{"ticker": "AAPL", "ex_date": "2025-02-07", "dividend": "0.25",
                 "dividend_yield": "0.5%"}]
        ipos = [{"ticker": "RDDT", "pricing_date": "2025-03-01",
                 "price_min": 31, "price_max": 34, "deal_status": "Filed"}]
        guidance = [{"ticker": "NVDA", "date": "2025-01-30",
                     "eps_guidance_est": "1.5", "revenue_guidance_est": "25B"}]
        rows = build_vd_bz_calendar(
            bz_dividends=divs, bz_ipos=ipos, bz_guidance=guidance,
        )
        assert len(rows) == 3
        # Sorted by date descending
        dates = [r["date"] for r in rows]
        assert dates == sorted(dates, reverse=True)

    def test_missing_fields_handled(self):
        """Missing fields should show '?' in detail, not crash."""
        divs = [{"ticker": "TEST"}]  # minimal dict
        rows = build_vd_bz_calendar(bz_dividends=divs)
        assert len(rows) == 1
        assert rows[0]["type"] == "dividend"
        assert "?" in rows[0]["detail"]  # should have fallback '?'


# ═══════════════════════════════════════════════════════════════
# save_vd_bz_calendar
# ═══════════════════════════════════════════════════════════════


class TestSaveVdBzCalendar:
    """Test atomic BZ calendar JSONL write."""

    def test_writes_jsonl_file(self, tmp_path: Path):
        path = str(tmp_path / "bz_cal.jsonl")
        divs = [{"ticker": "AAPL", "ex_date": "2025-02-07",
                 "dividend": "0.25", "dividend_yield": "0.5%"}]
        save_vd_bz_calendar(bz_dividends=divs, path=path)

        assert os.path.exists(path)
        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["type"] == "dividend"
        assert row["ticker"] == "AAPL"

    def test_empty_data_no_file(self, tmp_path: Path):
        """No data → no file created."""
        path = str(tmp_path / "bz_cal_empty.jsonl")
        save_vd_bz_calendar(path=path)
        assert not os.path.exists(path)

    def test_multiple_types(self, tmp_path: Path):
        path = str(tmp_path / "bz_cal_multi.jsonl")
        divs = [{"ticker": "AAPL", "ex_date": "2025-02-07",
                 "dividend": "0.25", "dividend_yield": "0.5%"}]
        ipos = [{"ticker": "RDDT", "pricing_date": "2025-03-01",
                 "price_min": 31, "price_max": 34, "deal_status": "Filed"}]
        save_vd_bz_calendar(bz_dividends=divs, bz_ipos=ipos, path=path)

        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 2
        types = {json.loads(l)["type"] for l in lines}
        assert types == {"dividend", "ipo"}

    def test_atomic_write_no_tmp_left(self, tmp_path: Path):
        """After successful write, no .tmp file should remain."""
        path = str(tmp_path / "bz_cal_atomic.jsonl")
        divs = [{"ticker": "AAPL", "ex_date": "2025-02-07",
                 "dividend": "0.25", "dividend_yield": "0.5%"}]
        save_vd_bz_calendar(bz_dividends=divs, path=path)

        assert not os.path.exists(path + ".tmp")
        assert os.path.exists(path)

    def test_overwrite_existing(self, tmp_path: Path):
        """Second write should overwrite the first."""
        path = str(tmp_path / "bz_cal_overwrite.jsonl")

        divs1 = [{"ticker": "AAPL", "ex_date": "2025-01-01",
                  "dividend": "0.20", "dividend_yield": "0.4%"}]
        save_vd_bz_calendar(bz_dividends=divs1, path=path)

        divs2 = [{"ticker": "MSFT", "ex_date": "2025-02-01",
                  "dividend": "0.75", "dividend_yield": "0.8%"},
                 {"ticker": "NVDA", "ex_date": "2025-02-15",
                  "dividend": "0.04", "dividend_yield": "0.02%"}]
        save_vd_bz_calendar(bz_dividends=divs2, path=path)

        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 2
        tickers = {json.loads(l)["ticker"] for l in lines}
        assert "AAPL" not in tickers
        assert tickers == {"MSFT", "NVDA"}
