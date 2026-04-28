"""Bucket H — coverage uplift for `open_prep.run_open_prep` helpers.

Targets pure helpers and externally-mockable fetchers:

  * `_int_env`, `_normalize_tradingview_article_date`,
    `_tradingview_headline_to_article`, `_benzinga_news_item_to_article`
  * `_calculate_atr14_from_eod`, `_load_atr_cache`, `_save_atr_cache`,
    `_evict_stale_cache_files`, `_incremental_atr_from_eod_bulk`,
    `_atr14_by_symbol`
  * `compute_premarket_high_low`, `_pm_cache_save` / `_pm_cache_load`,
    `_fetch_premarket_high_low_bulk`
  * `_fetch_analyst_catalyst`, `_fetch_earnings_distance_features`,
    `_fetch_fmp_us_mid_large_universe`,
    `_fetch_benzinga_core_news_articles` (env / early-return paths only)
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from open_prep import run_open_prep as rop

# ---------------------------------------------------------------------------
# _int_env
# ---------------------------------------------------------------------------


def test_int_env_returns_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPEN_PREP_TEST_INT", raising=False)
    assert rop._int_env("OPEN_PREP_TEST_INT", 7) == 7


def test_int_env_returns_default_on_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPEN_PREP_TEST_INT", "not-an-int")
    assert rop._int_env("OPEN_PREP_TEST_INT", 9) == 9


def test_int_env_returns_value_when_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPEN_PREP_TEST_INT", "42")
    assert rop._int_env("OPEN_PREP_TEST_INT", 7) == 42


# ---------------------------------------------------------------------------
# _normalize_tradingview_article_date
# ---------------------------------------------------------------------------


def test_normalize_tradingview_article_date_invalid_input() -> None:
    assert rop._normalize_tradingview_article_date(None) == ""
    assert rop._normalize_tradingview_article_date("not-a-number") == ""
    assert rop._normalize_tradingview_article_date(0) == ""
    assert rop._normalize_tradingview_article_date(-100) == ""


def test_normalize_tradingview_article_date_valid_epoch() -> None:
    out = rop._normalize_tradingview_article_date(1_700_000_000)
    assert out.startswith("2023-")
    assert out.endswith("+00:00")


# ---------------------------------------------------------------------------
# _tradingview_headline_to_article
# ---------------------------------------------------------------------------


def test_tradingview_headline_to_article_missing_title_returns_none() -> None:
    headline = SimpleNamespace(title="", tickers=["AAPL"], published=1_700_000_000)
    assert rop._tradingview_headline_to_article(headline) is None


def test_tradingview_headline_to_article_no_tickers_returns_none() -> None:
    headline = SimpleNamespace(title="Big move", tickers=[], published=1_700_000_000)
    assert rop._tradingview_headline_to_article(headline) is None


def test_tradingview_headline_to_article_full_payload() -> None:
    headline = SimpleNamespace(
        title="Apple beats earnings",
        tickers=["aapl", "msft"],
        published=1_700_000_000,
        source="TradingView",
        story_url="https://tv/x",
        provider="custom_provider",
    )
    out = rop._tradingview_headline_to_article(headline)
    assert out is not None
    assert out["tickers"] == "AAPL,MSFT"
    assert out["title"] == "Apple beats earnings"
    assert out["url"] == "https://tv/x"
    assert out["provider"] == "custom_provider"


# ---------------------------------------------------------------------------
# _benzinga_news_item_to_article
# ---------------------------------------------------------------------------


def test_benzinga_news_item_to_article_missing_title() -> None:
    item = SimpleNamespace(headline="", tickers=["AAPL"])
    assert rop._benzinga_news_item_to_article(item) is None


def test_benzinga_news_item_to_article_no_tickers() -> None:
    item = SimpleNamespace(headline="Big news", tickers=[])
    assert rop._benzinga_news_item_to_article(item) is None


def test_benzinga_news_item_to_article_full_payload() -> None:
    item = SimpleNamespace(
        headline="Apple update",
        tickers=["AAPL"],
        published_ts=1_700_000_000,
        snippet="Snippet",
        source="Benzinga",
        url="https://bz/x",
        provider="benzinga_rest",
    )
    out = rop._benzinga_news_item_to_article(item)
    assert out is not None
    assert out["title"] == "Apple update"
    assert out["tickers"] == "AAPL"
    assert out["date"].startswith("2023-")


def test_benzinga_news_item_to_article_invalid_published_ts() -> None:
    item = SimpleNamespace(
        headline="Foo",
        tickers=["AAPL"],
        published_ts="garbage",
    )
    out = rop._benzinga_news_item_to_article(item)
    assert out is not None
    assert out["date"] == ""


# ---------------------------------------------------------------------------
# _calculate_atr14_from_eod (Wilder's RMA)
# ---------------------------------------------------------------------------


def test_calculate_atr14_returns_zero_when_insufficient_bars() -> None:
    candles = [
        {"date": "2026-04-01", "high": 10, "low": 9, "close": 9.5},
        {"date": "2026-04-02", "high": 11, "low": 10, "close": 10.5},
    ]
    assert rop._calculate_atr14_from_eod(candles, period=14) == 0.0


def test_calculate_atr14_constant_range_yields_constant_atr() -> None:
    # 20 bars, identical H/L/C → TR=1 each → ATR converges to 1.0
    candles = [
        {"date": f"2026-04-{i+1:02d}", "high": 11.0, "low": 10.0, "close": 10.5}
        for i in range(20)
    ]
    assert rop._calculate_atr14_from_eod(candles, period=14) == pytest.approx(1.0)


def test_calculate_atr14_skips_invalid_rows() -> None:
    candles = [{"date": "", "high": 1, "low": 1, "close": 1}]
    assert rop._calculate_atr14_from_eod(candles, period=14) == 0.0
    candles2 = [{"date": "2026-04-01", "high": "bad", "low": 1, "close": 1}]
    assert rop._calculate_atr14_from_eod(candles2, period=14) == 0.0


# ---------------------------------------------------------------------------
# ATR cache I/O
# ---------------------------------------------------------------------------


def test_load_atr_cache_returns_empty_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rop, "ATR_CACHE_DIR", tmp_path)
    out = rop._load_atr_cache(date(2026, 4, 23), period=14)
    assert out == ({}, {}, {})


def test_save_then_load_atr_cache_roundtrip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rop, "ATR_CACHE_DIR", tmp_path)
    rop._save_atr_cache(
        as_of=date(2026, 4, 23),
        period=14,
        atr_map={"AAPL": 1.5, "msft": 2.5, "ZERO": 0.0},  # ZERO filtered out
        momentum_map={"AAPL": 0.1, "MSFT": -0.2},
        prev_close_map={"AAPL": 100.0, "MSFT": 200.0},
    )
    atr, mom, prev = rop._load_atr_cache(date(2026, 4, 23), period=14)
    assert set(atr) == {"AAPL", "MSFT"}
    assert atr["AAPL"] == 1.5
    assert mom["AAPL"] == 0.1
    assert prev["MSFT"] == 200.0


def test_load_atr_cache_handles_corrupt_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rop, "ATR_CACHE_DIR", tmp_path)
    cache_file = rop._atr_cache_file(date(2026, 4, 23), 14)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text("{not valid json")
    assert rop._load_atr_cache(date(2026, 4, 23), period=14) == ({}, {}, {})


# ---------------------------------------------------------------------------
# _evict_stale_cache_files
# ---------------------------------------------------------------------------


def test_evict_stale_cache_files_removes_old(tmp_path: Path) -> None:
    import os as _os
    import time as _time

    fresh = tmp_path / "new.json"
    fresh.write_text("{}")
    stale = tmp_path / "old.json"
    stale.write_text("{}")
    old_ts = _time.time() - 30 * 86400
    _os.utime(stale, (old_ts, old_ts))
    rop._evict_stale_cache_files(tmp_path, max_age_days=7)
    assert fresh.exists()
    assert not stale.exists()


def test_evict_stale_cache_files_missing_dir_is_silent(tmp_path: Path) -> None:
    rop._evict_stale_cache_files(tmp_path / "nope", max_age_days=7)


# ---------------------------------------------------------------------------
# _incremental_atr_from_eod_bulk
# ---------------------------------------------------------------------------


def _make_atr_cache_for_prev_day(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, as_of: date
) -> None:
    monkeypatch.setattr(rop, "ATR_CACHE_DIR", tmp_path)
    prev_day = rop._prev_trading_day(as_of)
    rop._save_atr_cache(
        as_of=prev_day,
        period=14,
        atr_map={"AAPL": 1.0, "MSFT": 2.0},
        momentum_map={"AAPL": 0.5, "MSFT": -0.5},
        prev_close_map={"AAPL": 100.0, "MSFT": 200.0},
    )


def test_incremental_atr_returns_empty_when_no_prev_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rop, "ATR_CACHE_DIR", tmp_path)

    class _Client:
        def get_eod_bulk(self, _d: date) -> list[dict[str, Any]]:
            return []

    out = rop._incremental_atr_from_eod_bulk(
        client=_Client(), symbols=["AAPL"], as_of=date(2026, 4, 23), atr_period=14,
    )
    assert out == ({}, {}, {})


def test_incremental_atr_updates_with_eod_bulk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    as_of = date(2026, 4, 23)
    _make_atr_cache_for_prev_day(monkeypatch, tmp_path, as_of=as_of)

    class _Client:
        def get_eod_bulk(self, _d: date) -> list[dict[str, Any]]:
            return [
                {"symbol": "AAPL", "high": 102, "low": 99, "close": 101},
                {"symbol": "MSFT", "high": 205, "low": 198, "close": 203},
                {"symbol": "ZZZ", "high": 1, "low": 1, "close": 1},  # not in cache → skipped
            ]

    atr, mom, close = rop._incremental_atr_from_eod_bulk(
        client=_Client(), symbols=["AAPL", "MSFT", "ZZZ"], as_of=as_of, atr_period=14,
    )
    assert set(atr) == {"AAPL", "MSFT"}
    assert atr["AAPL"] > 0
    assert mom["AAPL"] == 0.5  # carries over from cache
    assert close["AAPL"] == 101


# ---------------------------------------------------------------------------
# _atr14_by_symbol — cache-hit short-circuit
# ---------------------------------------------------------------------------


def test_atr14_by_symbol_returns_from_cache_when_complete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rop, "ATR_CACHE_DIR", tmp_path)
    as_of = date(2026, 4, 23)
    rop._save_atr_cache(
        as_of=as_of,
        period=14,
        atr_map={"AAPL": 1.5, "MSFT": 2.5},
        momentum_map={"AAPL": 0.0, "MSFT": 0.0},
        prev_close_map={"AAPL": 100.0, "MSFT": 200.0},
    )

    class _Client:
        def get_historical_price_eod_full(self, *_a: Any, **_k: Any) -> Any:
            raise AssertionError("should not be called when cache is complete")

        def get_eod_bulk(self, _d: date) -> list[dict[str, Any]]:
            raise AssertionError("should not be called when cache is complete")

        def get_batch_quotes(self, _syms: list[str]) -> list[dict[str, Any]]:
            return []

    atr, _mom, vwap, _avg_vol_fb, errors = rop._atr14_by_symbol(
        client=_Client(),
        symbols=["AAPL", "MSFT"],
        as_of=as_of,
        atr_period=14,
        parallel_workers=2,
    )
    assert atr == {"AAPL": 1.5, "MSFT": 2.5}
    assert vwap == {"AAPL": None, "MSFT": None}
    assert errors == {}


# ---------------------------------------------------------------------------
# compute_premarket_high_low
# ---------------------------------------------------------------------------


def test_compute_premarket_high_low_aggregates_window() -> None:
    session_day = date(2026, 4, 23)
    bars = [
        # 04:30 ET → in window
        {"date": "2026-04-23 04:30", "high": 101.0, "low": 100.0},
        # 09:00 ET → in window (max high)
        {"date": "2026-04-23 09:00", "high": 105.0, "low": 99.0},
        # 09:30 ET → outside (>=)
        {"date": "2026-04-23 09:30", "high": 200.0, "low": 50.0},
        # 03:30 ET → before window
        {"date": "2026-04-23 03:30", "high": 999.0, "low": 1.0},
    ]
    pm_high, pm_low = rop.compute_premarket_high_low(bars, session_day_ny=session_day)
    assert pm_high == 105.0
    assert pm_low == 99.0


def test_compute_premarket_high_low_skips_invalid_and_zero() -> None:
    bars = [
        {"date": "bogus", "high": 100, "low": 99},  # unparseable
        {"date": "2026-04-23 05:00", "high": 0, "low": 0},  # zero
    ]
    pm_high, pm_low = rop.compute_premarket_high_low(bars, session_day_ny=date(2026, 4, 23))
    assert pm_high is None
    assert pm_low is None


# ---------------------------------------------------------------------------
# _pm_cache_load / _pm_cache_save
# ---------------------------------------------------------------------------


def test_pm_cache_save_then_load_roundtrip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rop, "PM_CACHE_DIR", tmp_path)
    day = date(2026, 4, 23)
    rop._pm_cache_save("AAPL", day, "5min", 105.0, 99.0)
    out = rop._pm_cache_load("AAPL", day, "5min")
    assert out == (105.0, 99.0)


def test_pm_cache_load_missing_file_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rop, "PM_CACHE_DIR", tmp_path)
    assert rop._pm_cache_load("MSFT", date(2026, 4, 23), "5min") is None


def test_pm_cache_load_corrupt_json_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rop, "PM_CACHE_DIR", tmp_path)
    target = rop._pm_cache_file("AAPL", date(2026, 4, 23), "5min")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{not json")
    assert rop._pm_cache_load("AAPL", date(2026, 4, 23), "5min") is None


def test_pm_cache_load_expired_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rop, "PM_CACHE_DIR", tmp_path)
    monkeypatch.setattr(rop, "PM_CACHE_TTL_SECONDS", 1)
    day = date(2026, 4, 23)
    rop._pm_cache_save("AAPL", day, "5min", 1.0, 1.0)
    # Rewrite cached_at to an old timestamp
    target = rop._pm_cache_file("AAPL", day, "5min")
    payload = json.loads(target.read_text())
    payload["cached_at_utc"] = "2020-01-01T00:00:00+00:00"
    target.write_text(json.dumps(payload))
    assert rop._pm_cache_load("AAPL", day, "5min") is None


# ---------------------------------------------------------------------------
# _fetch_premarket_high_low_bulk
# ---------------------------------------------------------------------------


def test_fetch_premarket_high_low_bulk_uses_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rop, "PM_CACHE_DIR", tmp_path)
    day = date(2026, 4, 23)
    rop._pm_cache_save("AAPL", day, "5min", 105.0, 99.0)

    class _Client:
        def get_intraday_chart(self, *_a: Any, **_k: Any) -> list[dict[str, Any]]:
            raise AssertionError("should not fetch when cached")

    run_dt = datetime(2026, 4, 23, 13, 0, tzinfo=UTC)
    out, timeout_msg = rop._fetch_premarket_high_low_bulk(
        client=_Client(), symbols=["AAPL"], run_dt_utc=run_dt,
    )
    assert out["AAPL"] == {"premarket_high": 105.0, "premarket_low": 99.0}
    assert timeout_msg is None


def test_fetch_premarket_high_low_bulk_fetches_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rop, "PM_CACHE_DIR", tmp_path)

    class _Client:
        def get_intraday_chart(self, *_a: Any, **_k: Any) -> list[dict[str, Any]]:
            return [
                {"date": "2026-04-23 05:00", "high": 110.0, "low": 100.0},
            ]

    run_dt = datetime(2026, 4, 23, 13, 0, tzinfo=UTC)
    out, timeout_msg = rop._fetch_premarket_high_low_bulk(
        client=_Client(), symbols=["AAPL"], run_dt_utc=run_dt, parallel_workers=1,
    )
    assert out["AAPL"]["premarket_high"] == 110.0
    assert timeout_msg is None


def test_fetch_premarket_high_low_bulk_swallows_per_symbol_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rop, "PM_CACHE_DIR", tmp_path)

    class _Client:
        def get_intraday_chart(self, *_a: Any, **_k: Any) -> list[dict[str, Any]]:
            raise RuntimeError("api fail")

    run_dt = datetime(2026, 4, 23, 13, 0, tzinfo=UTC)
    out, _ = rop._fetch_premarket_high_low_bulk(
        client=_Client(), symbols=["AAPL"], run_dt_utc=run_dt, parallel_workers=1,
    )
    assert out["AAPL"] == {"premarket_high": None, "premarket_low": None}


# ---------------------------------------------------------------------------
# _fetch_analyst_catalyst
# ---------------------------------------------------------------------------


def test_fetch_analyst_catalyst_returns_empty_when_limit_zero() -> None:
    class _Client:
        def get_price_target_summary(self, *_a: Any) -> dict[str, Any]:
            raise AssertionError("should not be called")

    assert rop._fetch_analyst_catalyst(client=_Client(), symbols=["AAPL"], limit=0) == {}


def test_fetch_analyst_catalyst_aggregates_targets() -> None:
    class _Client:
        def get_price_target_summary(self, sym: str) -> dict[str, Any]:
            if sym == "AAPL":
                return {"lastQuarterAvgPriceTarget": 200.0, "lastQuarterCount": 10}
            if sym == "MSFT":
                return {}  # falsy → None
            raise RuntimeError("bad")

    out = rop._fetch_analyst_catalyst(
        client=_Client(), symbols=["AAPL", "MSFT", "ERR"], limit=3,
    )
    assert "AAPL" in out
    assert out["AAPL"]["analyst_price_target"] == 200.0
    assert out["AAPL"]["analyst_coverage_count"] == 10
    assert "MSFT" not in out
    assert "ERR" not in out  # exception swallowed


# ---------------------------------------------------------------------------
# _fetch_earnings_distance_features
# ---------------------------------------------------------------------------


def test_fetch_earnings_distance_features_returns_empty_when_max_zero() -> None:
    class _Client:
        def get_earnings_report(self, *_a: Any, **_k: Any) -> list[dict[str, Any]]:
            raise AssertionError("should not be called")

    out = rop._fetch_earnings_distance_features(
        client=_Client(), symbols=["AAPL"], today=date(2026, 4, 23), max_symbols=0,
    )
    assert out == {}


def test_fetch_earnings_distance_features_computes_distances() -> None:
    today = date(2026, 4, 23)

    class _Client:
        def get_earnings_report(self, sym: str, *, limit: int) -> list[dict[str, Any]]:
            if sym == "AAPL":
                return [
                    {"date": "2026-04-22"},  # 1 day ago → risk window
                    {"date": "2026-07-22"},  # future
                ]
            if sym == "MSFT":
                return []  # no dates
            return [{"date": "garbage"}]  # parse error → no dates

    out = rop._fetch_earnings_distance_features(
        client=_Client(), symbols=["AAPL", "MSFT", "BAD"], today=today, max_symbols=10,
    )
    assert out["AAPL"]["days_since_last_earnings"] == 1
    assert out["AAPL"]["days_to_next_earnings"] == 90
    assert out["AAPL"]["earnings_risk_window"] is True
    assert "MSFT" not in out
    assert "BAD" not in out


# ---------------------------------------------------------------------------
# _fetch_fmp_us_mid_large_universe
# ---------------------------------------------------------------------------


def test_fetch_fmp_us_mid_large_universe_paginates_and_filters() -> None:
    # Page 0 returns exactly `remaining` rows so paging continues to page 1
    pages: dict[int, list[dict[str, Any]]] = {
        0: [
            {"symbol": "AAPL", "marketCap": 3_000_000_000_000, "sector": "Technology"},
            {"symbol": "tiny", "marketCap": 100, "sector": "Misc"},  # below cap
            {"symbol": "AAPL", "marketCap": 1, "sector": "dup"},  # dup
        ],
        1: [
            {"symbol": "MSFT", "marketCap": 2_000_000_000_000, "sector": "Technology"},
        ],
    }

    class _Client:
        def __init__(self) -> None:
            self.calls = 0

        def get_company_screener(self, **kwargs: Any) -> list[dict[str, Any]]:
            page = kwargs["page"]
            self.calls += 1
            return pages.get(page, [])

    client = _Client()
    # max_symbols=3 → page 0 returns 3 rows == remaining, paging continues
    syms, sector_map = rop._fetch_fmp_us_mid_large_universe(
        client=client, min_market_cap=1_000_000_000, max_symbols=3,
    )
    assert syms == ["AAPL", "MSFT"]
    assert sector_map == {"AAPL": "Technology", "MSFT": "Technology"}


def test_fetch_fmp_us_mid_large_universe_stops_when_empty_batch() -> None:
    class _Client:
        def get_company_screener(self, **_k: Any) -> list[dict[str, Any]]:
            return []

    syms, sector_map = rop._fetch_fmp_us_mid_large_universe(
        client=_Client(), min_market_cap=1, max_symbols=10,
    )
    assert syms == []
    assert sector_map == {}


# ---------------------------------------------------------------------------
# _fetch_benzinga_core_news_articles — early-return paths
# ---------------------------------------------------------------------------


def test_fetch_benzinga_core_news_articles_missing_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BENZINGA_API_KEY", raising=False)
    articles, err = rop._fetch_benzinga_core_news_articles(symbols=["AAPL"])
    assert articles == []
    assert err == "missing BENZINGA_API_KEY"


def test_fetch_benzinga_core_news_articles_zero_max_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BENZINGA_API_KEY", "test_key")
    monkeypatch.setenv("OPEN_PREP_BENZINGA_CORE_NEWS_MAX_SYMBOLS", "0")
    articles, err = rop._fetch_benzinga_core_news_articles(symbols=["AAPL"])
    assert articles == []
    assert err is None


def test_fetch_benzinga_core_news_articles_no_normalized_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BENZINGA_API_KEY", "test_key")
    monkeypatch.setenv("OPEN_PREP_BENZINGA_CORE_NEWS_MAX_SYMBOLS", "10")
    articles, err = rop._fetch_benzinga_core_news_articles(symbols=["", "  "])
    assert articles == []
    assert err is None
