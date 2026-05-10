"""Tests for terminal_finnhub.py — F-05 Finnhub mismatch guards."""
from __future__ import annotations

import time
from unittest import mock

import terminal_finnhub

# ---------------------------------------------------------------------------
# is_equity_symbol guard
# ---------------------------------------------------------------------------


class TestIsEquitySymbol:
    def test_normal_equity(self) -> None:
        assert terminal_finnhub.is_equity_symbol("AAPL") is True
        assert terminal_finnhub.is_equity_symbol("MSFT") is True
        assert terminal_finnhub.is_equity_symbol("TSLA") is True

    def test_multi_class_equity(self) -> None:
        assert terminal_finnhub.is_equity_symbol("BRK.B") is True

    def test_crypto_rejected(self) -> None:
        assert terminal_finnhub.is_equity_symbol("BTC") is False
        assert terminal_finnhub.is_equity_symbol("ETH") is False
        assert terminal_finnhub.is_equity_symbol("SOL") is False
        assert terminal_finnhub.is_equity_symbol("DOGE") is False

    def test_crypto_suffix_rejected(self) -> None:
        assert terminal_finnhub.is_equity_symbol("BTC-USD") is False
        assert terminal_finnhub.is_equity_symbol("ETH-EUR") is False

    def test_crypto_prefix_rejected(self) -> None:
        assert terminal_finnhub.is_equity_symbol("BINANCE:BTCUSDT") is False
        assert terminal_finnhub.is_equity_symbol("CRYPTO:BTC") is False

    def test_forex_rejected(self) -> None:
        assert terminal_finnhub.is_equity_symbol("FX:EURUSD") is False
        assert terminal_finnhub.is_equity_symbol("OANDA:EUR_USD") is False

    def test_index_rejected(self) -> None:
        assert terminal_finnhub.is_equity_symbol("INDEX:SPX") is False

    def test_numeric_rejected(self) -> None:
        assert terminal_finnhub.is_equity_symbol("12345") is False

    def test_empty_rejected(self) -> None:
        assert terminal_finnhub.is_equity_symbol("") is False

    def test_too_long_rejected(self) -> None:
        assert terminal_finnhub.is_equity_symbol("A" * 11) is False


# ---------------------------------------------------------------------------
# social_sentiment_status
# ---------------------------------------------------------------------------


class TestSocialSentimentStatus:
    def test_available_when_key_set(self) -> None:
        with mock.patch.dict("os.environ", {"FINNHUB_API_KEY": "test_key"}):
            terminal_finnhub._social_sentiment_blocked = False
            terminal_finnhub._rate_limit_backoff_until = 0.0
            assert terminal_finnhub.social_sentiment_status() == "available"

    def test_blocked_premium(self) -> None:
        terminal_finnhub._social_sentiment_blocked = True
        assert terminal_finnhub.social_sentiment_status() == "blocked_premium"
        terminal_finnhub._social_sentiment_blocked = False

    def test_rate_limited(self) -> None:
        terminal_finnhub._social_sentiment_blocked = False
        terminal_finnhub._rate_limit_backoff_until = time.time() + 999
        with mock.patch.dict("os.environ", {"FINNHUB_API_KEY": "test_key"}):
            assert terminal_finnhub.social_sentiment_status() == "rate_limited"
        terminal_finnhub._rate_limit_backoff_until = 0.0

    def test_no_api_key(self) -> None:
        terminal_finnhub._social_sentiment_blocked = False
        terminal_finnhub._rate_limit_backoff_until = 0.0
        with mock.patch.dict("os.environ", {}, clear=True):
            assert terminal_finnhub.social_sentiment_status() == "no_api_key"


# ---------------------------------------------------------------------------
# Non-equity guard in fetch_social_sentiment
# ---------------------------------------------------------------------------


class TestFetchSocialSentimentGuard:
    def test_non_equity_returns_none(self) -> None:
        result = terminal_finnhub.fetch_social_sentiment("BTC")
        assert result is None

    def test_empty_returns_none(self) -> None:
        result = terminal_finnhub.fetch_social_sentiment("")
        assert result is None


# ---------------------------------------------------------------------------
# Backoff mechanics
# ---------------------------------------------------------------------------


class TestBackoff:
    def test_backoff_base_and_max_are_sane(self) -> None:
        assert terminal_finnhub._BACKOFF_BASE_SECONDS > 0
        assert terminal_finnhub._BACKOFF_MAX_SECONDS >= terminal_finnhub._BACKOFF_BASE_SECONDS

    def test_consecutive_429_increases_backoff(self) -> None:
        b1 = terminal_finnhub._BACKOFF_BASE_SECONDS * (2 ** 0)
        b2 = terminal_finnhub._BACKOFF_BASE_SECONDS * (2 ** 1)
        assert b2 > b1


# ---------------------------------------------------------------------------
# PR4 (2026-05-09): Finnhub free-tier extensions
# ---------------------------------------------------------------------------

# Audit-fix (2026-05-09): alias the already-imported `mock` rather than
# re-importing as `_mock` (PR2107 review). Keeps existing test body unchanged.
_mock = mock


class TestCompanyNews:
    def setup_method(self) -> None:
        terminal_finnhub._cache.clear()
        terminal_finnhub.clear_blocked_paths()

    def test_non_equity_returns_empty(self) -> None:
        assert terminal_finnhub.fetch_company_news("BTC") == []

    def test_parses_records(self) -> None:
        payload = [
            {
                "id": 7, "datetime": 1700000000, "headline": "AAPL beats",
                "summary": "x", "source": "Reuters", "url": "https://e",
                "category": "company", "related": "AAPL", "image": "",
            },
            {"id": 8, "datetime": 1700000100, "headline": "more", "summary": "",
             "source": "WSJ", "url": "u", "category": "c", "related": "AAPL",
             "image": ""},
        ]
        with _mock.patch.object(terminal_finnhub, "_get", return_value=payload):
            items = terminal_finnhub.fetch_company_news("AAPL", days_back=3)
        assert len(items) == 2
        assert items[0].symbol == "AAPL"
        assert items[0].headline == "AAPL beats"
        assert items[0].item_id == 7

    def test_max_items_cap(self) -> None:
        payload = [{"id": i, "datetime": 1, "headline": f"h{i}", "summary": "",
                    "source": "s", "url": "u", "category": "", "related": "",
                    "image": ""} for i in range(100)]
        with _mock.patch.object(terminal_finnhub, "_get", return_value=payload):
            items = terminal_finnhub.fetch_company_news("MSFT", max_items=5)
        assert len(items) == 5

    def test_empty_payload(self) -> None:
        with _mock.patch.object(terminal_finnhub, "_get", return_value=[]):
            assert terminal_finnhub.fetch_company_news("AAPL") == []

    def test_caches_per_window(self) -> None:
        calls = {"n": 0}
        def fake_get(_p, _q):
            calls["n"] += 1
            return [{"id": 1, "datetime": 1, "headline": "h", "summary": "",
                     "source": "s", "url": "u", "category": "", "related": "",
                     "image": ""}]
        with _mock.patch.object(terminal_finnhub, "_get", side_effect=fake_get):
            terminal_finnhub.fetch_company_news("AAPL", days_back=1)
            terminal_finnhub.fetch_company_news("AAPL", days_back=1)
        assert calls["n"] == 1


class TestNewsSentiment:
    def setup_method(self) -> None:
        terminal_finnhub._cache.clear()
        terminal_finnhub.clear_blocked_paths()

    def test_non_equity_returns_none(self) -> None:
        assert terminal_finnhub.fetch_news_sentiment("BTC") is None

    def test_parses_payload(self) -> None:
        payload = {
            "buzz": {"articlesInLastWeek": 12, "weeklyAverage": 3.4, "buzz": 1.1},
            "companyNewsScore": 0.65, "sectorAverageNewsScore": 0.5,
            "sentiment": {"bearishPercent": 0.2, "bullishPercent": 0.8},
        }
        with _mock.patch.object(terminal_finnhub, "_get", return_value=payload):
            s = terminal_finnhub.fetch_news_sentiment("AAPL")
        assert s is not None
        assert s.symbol == "AAPL"
        assert s.buzz_articles_in_last_week == 12
        assert s.sentiment_bullish_pct == 0.8
        assert s.company_news_score == 0.65

    def test_empty_payload_returns_none(self) -> None:
        with _mock.patch.object(terminal_finnhub, "_get", return_value={}):
            assert terminal_finnhub.fetch_news_sentiment("AAPL") is None


class TestRecommendationTrends:
    def setup_method(self) -> None:
        terminal_finnhub._cache.clear()
        terminal_finnhub.clear_blocked_paths()

    def test_non_equity_returns_empty(self) -> None:
        assert terminal_finnhub.fetch_recommendation_trends("BTC") == []

    def test_parses_records(self) -> None:
        payload = [
            {"period": "2026-04-01", "strongBuy": 10, "buy": 12, "hold": 5,
             "sell": 1, "strongSell": 0, "symbol": "AAPL"},
            {"period": "2026-03-01", "strongBuy": 8, "buy": 11, "hold": 6,
             "sell": 2, "strongSell": 1, "symbol": "AAPL"},
        ]
        with _mock.patch.object(terminal_finnhub, "_get", return_value=payload):
            rows = terminal_finnhub.fetch_recommendation_trends("AAPL")
        assert len(rows) == 2
        assert rows[0].period == "2026-04-01"
        assert rows[0].strong_buy == 10
        assert rows[1].sell == 2

    def test_dict_payload_returns_empty(self) -> None:
        with _mock.patch.object(terminal_finnhub, "_get", return_value={}):
            assert terminal_finnhub.fetch_recommendation_trends("AAPL") == []


class TestInsiderSentiment:
    def setup_method(self) -> None:
        terminal_finnhub._cache.clear()
        terminal_finnhub.clear_blocked_paths()

    def test_non_equity_returns_empty(self) -> None:
        assert terminal_finnhub.fetch_insider_sentiment("BTC") == []

    def test_unwraps_data_field(self) -> None:
        payload = {"symbol": "AAPL", "data": [
            {"symbol": "AAPL", "year": 2026, "month": 4, "change": 5000, "mspr": 12.3},
            {"symbol": "AAPL", "year": 2026, "month": 3, "change": -2000, "mspr": -7.1},
        ]}
        with _mock.patch.object(terminal_finnhub, "_get", return_value=payload):
            rows = terminal_finnhub.fetch_insider_sentiment("AAPL")
        assert len(rows) == 2
        assert rows[0].year == 2026 and rows[0].month == 4
        assert rows[0].change == 5000
        assert rows[1].mspr == -7.1

    def test_missing_data_returns_empty(self) -> None:
        with _mock.patch.object(terminal_finnhub, "_get", return_value={"symbol": "AAPL"}):
            assert terminal_finnhub.fetch_insider_sentiment("AAPL") == []


class TestBlockedPathShortCircuit:
    def setup_method(self) -> None:
        terminal_finnhub._cache.clear()
        terminal_finnhub.clear_blocked_paths()

    def test_clear_blocked_paths_resets_state(self) -> None:
        with terminal_finnhub._state_lock:
            terminal_finnhub._blocked_path_substrings.add("/foo")
            terminal_finnhub._social_sentiment_blocked = True
        terminal_finnhub.clear_blocked_paths()
        assert terminal_finnhub._blocked_path_substrings == set()
        assert terminal_finnhub._social_sentiment_blocked is False


# ---------------------------------------------------------------------------
# Cache miss-sentinel (PR-B, audit 2026-05-10)
# ---------------------------------------------------------------------------


class TestCacheMissSentinel:
    """``_set_cached(key, None)`` must actually cache the miss.

    Pre-fix bug: ``_get_cached`` returned ``None`` for both "no entry" and
    "cached None", so two consecutive empty payloads issued two upstream
    API calls. PR-B switches ``_get_cached`` to ``(found, value)`` and these
    tests pin the new contract.
    """

    def setup_method(self) -> None:
        with terminal_finnhub._cache_lock:
            terminal_finnhub._cache.clear()

    def teardown_method(self) -> None:
        with terminal_finnhub._cache_lock:
            terminal_finnhub._cache.clear()

    def test_get_cached_returns_found_false_for_unknown_key(self) -> None:
        found, value = terminal_finnhub._get_cached("does-not-exist", ttl=60.0)
        assert found is False
        assert value is None

    def test_get_cached_returns_found_true_for_cached_none(self) -> None:
        terminal_finnhub._set_cached("k-none", None)
        found, value = terminal_finnhub._get_cached("k-none", ttl=60.0)
        assert found is True
        assert value is None

    def test_cached_value_returned_within_ttl(self) -> None:
        terminal_finnhub._set_cached("k-val", [1, 2, 3])
        found, value = terminal_finnhub._get_cached("k-val", ttl=60.0)
        assert found is True
        assert value == [1, 2, 3]

    def test_cached_miss_expires_after_ttl(self) -> None:
        # Write the entry with a back-dated timestamp so it is already stale.
        with terminal_finnhub._cache_lock:
            terminal_finnhub._cache["k-stale"] = (time.time() - 120.0, None)
        found, value = terminal_finnhub._get_cached("k-stale", ttl=60.0)
        assert found is False
        assert value is None
        # And the stale entry must have been evicted.
        with terminal_finnhub._cache_lock:
            assert "k-stale" not in terminal_finnhub._cache

    def test_empty_social_response_caches_miss_one_upstream_call(self) -> None:
        """Two consecutive empty-payload calls must issue ONE upstream call."""
        with mock.patch.object(
            terminal_finnhub, "_get", return_value={"reddit": [], "twitter": []}
        ) as m_get:
            r1 = terminal_finnhub.fetch_social_sentiment("AAPL")
            r2 = terminal_finnhub.fetch_social_sentiment("AAPL")
        assert r1 is None
        assert r2 is None
        assert m_get.call_count == 1, (
            f"miss was not cached -- upstream called {m_get.call_count}x"
        )
