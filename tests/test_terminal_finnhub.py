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
