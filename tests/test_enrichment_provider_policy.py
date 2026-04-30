"""Tests for the V4 enrichment provider policy & adapter layer.

Covers:
- Policy declarations (domain → primary + fallbacks)
- Provider success paths
- Provider unavailable / total failure
- Partial provider availability (primary fails, fallback succeeds)
- Malformed payloads
- Deterministic PROVIDER_COUNT / STALE_PROVIDERS output
- Provenance tracking per domain
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from scripts.smc_newsapi_ai import NewsApiAiProviderError
from scripts.smc_provider_policy import (
    ALL_POLICIES,
    POLICY_BASE_SCAN,
    POLICY_CALENDAR,
    POLICY_NEWS,
    POLICY_REGIME,
    POLICY_TECHNICAL,
    DomainPolicy,
    ProviderResult,
    fetch_calendar_fmp,
    fetch_news_fmp,
    fetch_news_newsapi_ai,
    fetch_regime_fmp,
    fetch_technical_fmp,
    fetch_technical_tradingview,
    resolve_domain,
)

# ── Test 1: Policy declarations ──────────────────────────────────


class TestPolicyDeclarations:
    def test_base_scan_is_databento_primary_no_fallback(self):
        assert POLICY_BASE_SCAN.primary == "databento"
        assert POLICY_BASE_SCAN.fallbacks == ()
        assert POLICY_BASE_SCAN.all_providers == ("databento",)

    def test_regime_is_fmp_primary_no_fallback(self):
        assert POLICY_REGIME.primary == "fmp"
        assert POLICY_REGIME.fallbacks == ()

    def test_news_is_fmp_primary_with_explicit_fallback_chain(self):
        assert POLICY_NEWS.primary == "fmp"
        assert POLICY_NEWS.fallbacks == ("benzinga", "newsapi_ai")
        assert POLICY_NEWS.all_providers == ("fmp", "benzinga", "newsapi_ai")

    def test_calendar_is_fmp_primary_benzinga_fallback(self):
        assert POLICY_CALENDAR.primary == "fmp"
        assert POLICY_CALENDAR.fallbacks == ("benzinga",)

    def test_technical_is_fmp_primary_tradingview_fallback(self):
        assert POLICY_TECHNICAL.primary == "fmp"
        assert POLICY_TECHNICAL.fallbacks == ("tradingview",)

    def test_all_policies_registered(self):
        assert set(ALL_POLICIES.keys()) == {
            "base_scan", "regime", "news", "calendar", "technical",
        }

    def test_no_implicit_fallback_chains(self):
        """Every fallback chain is explicitly declared — no hidden cascades."""
        for name, policy in ALL_POLICIES.items():
            assert isinstance(policy.fallbacks, tuple), f"{name} fallbacks is not a tuple"
            for fb in policy.fallbacks:
                assert fb != policy.primary, f"{name}: fallback contains primary"


# ── Test 2: Provider success ────────────────────────────────────


class TestProviderSuccess:
    """All providers return valid data."""

    @patch("scripts.smc_provider_policy.fetch_regime_fmp")
    def test_regime_success_returns_fmp_provider(self, mock_fn):
        mock_fn.return_value = ProviderResult(
            data={"regime": "RISK_ON", "vix_level": 15.0},
            provider="fmp",
        )
        result = resolve_domain("regime", fmp=MagicMock())
        assert result.ok is True
        assert result.provider == "fmp"
        assert result.data["regime"] == "RISK_ON"
        assert result.stale == []

    @patch("scripts.smc_provider_policy.fetch_news_fmp")
    def test_news_success_returns_fmp_provider(self, mock_fn):
        mock_fn.return_value = ProviderResult(
            data={"bullish_tickers": ["AAPL"], "bearish_tickers": []},
            provider="fmp",
        )
        result = resolve_domain("news", fmp=MagicMock(), symbols=["AAPL"])
        assert result.ok is True
        assert result.provider == "fmp"

    @patch("scripts.smc_provider_policy.fetch_calendar_fmp")
    def test_calendar_success_returns_fmp_provider(self, mock_fn):
        mock_fn.return_value = ProviderResult(
            data={"earnings_today_tickers": "AAPL"},
            provider="fmp",
        )
        result = resolve_domain("calendar", fmp=MagicMock(), symbols=["AAPL"])
        assert result.ok is True
        assert result.provider == "fmp"

    @patch("scripts.smc_provider_policy.fetch_technical_fmp")
    def test_technical_success_returns_fmp_provider(self, mock_fn):
        mock_fn.return_value = ProviderResult(
            data={"strength": 0.6, "bias": "BULLISH"},
            provider="fmp",
        )
        result = resolve_domain("technical", fmp=MagicMock())
        assert result.ok is True
        assert result.provider == "fmp"


# ── Test 3: Provider unavailable (total failure) ────────────────


class TestProviderUnavailable:
    """All providers in the chain fail — should return ok=False with defaults."""

    def test_regime_all_fail_returns_safe_default(self):
        # fmp=None → RuntimeError → all_stale=["fmp"]
        result = resolve_domain("regime", fmp=None)
        assert result.ok is False
        assert result.provider == "none"
        assert "fmp" in result.stale

    def test_news_all_fail_returns_safe_default(self):
        result = resolve_domain("news", fmp=None, benzinga_api_key="", symbols=["AAPL"])
        assert result.ok is False
        assert result.provider == "none"
        assert "fmp" in result.stale
        assert "benzinga" in result.stale
        assert "newsapi_ai" in result.stale

    def test_calendar_all_fail_returns_safe_default(self):
        result = resolve_domain("calendar", fmp=None, benzinga_api_key="", symbols=["AAPL"])
        assert result.ok is False
        assert "fmp" in result.stale
        assert "benzinga" in result.stale

    @patch("scripts.smc_provider_policy.fetch_technical_tradingview")
    def test_technical_all_fail_returns_safe_default(self, mock_tradingview):
        mock_tradingview.side_effect = RuntimeError("TradingView fallback unavailable")
        result = resolve_domain("technical", fmp=None)
        assert result.ok is False
        assert result.provider == "none"
        assert "fmp" in result.stale
        assert "tradingview" in result.stale

    def test_unknown_domain_raises(self):
        with pytest.raises(ValueError, match="Unknown enrichment domain"):
            resolve_domain("nonexistent")


# ── Test 4: Partial provider availability ───────────────────────


class TestPartialProviderAvailability:
    """Primary fails, fallback succeeds."""

    @patch("scripts.smc_provider_policy.fetch_news_benzinga")
    @patch("scripts.smc_provider_policy.fetch_news_fmp")
    def test_news_fmp_fails_benzinga_succeeds(self, mock_fmp, mock_bz):
        mock_fmp.side_effect = RuntimeError("FMP timeout")
        mock_bz.return_value = ProviderResult(
            data={"bullish_tickers": ["NVDA"], "bearish_tickers": []},
            provider="benzinga",
        )
        result = resolve_domain(
            "news", fmp=MagicMock(), benzinga_api_key="bz-key", symbols=["NVDA"],
        )
        assert result.ok is True
        assert result.provider == "benzinga"
        assert "fmp" in result.stale
        assert result.data["bullish_tickers"] == ["NVDA"]

    @patch("scripts.smc_provider_policy.fetch_news_newsapi_ai")
    @patch("scripts.smc_provider_policy.fetch_news_benzinga")
    @patch("scripts.smc_provider_policy.fetch_news_fmp")
    def test_news_fmp_and_benzinga_fail_newsapi_succeeds(self, mock_fmp, mock_bz, mock_newsapi):
        mock_fmp.side_effect = RuntimeError("FMP timeout")
        mock_bz.side_effect = RuntimeError("Benzinga timeout")
        mock_newsapi.return_value = ProviderResult(
            data={"bullish_tickers": ["NVDA"], "bearish_tickers": []},
            provider="newsapi_ai",
        )
        result = resolve_domain(
            "news",
            fmp=MagicMock(),
            benzinga_api_key="bz-key",
            newsapi_ai_key="news-key",
            symbols=["NVDA"],
        )
        assert result.ok is True
        assert result.provider == "newsapi_ai"
        assert "fmp" in result.stale
        assert "benzinga" in result.stale

    @patch("scripts.smc_provider_policy.fetch_news_newsapi_ai")
    @patch("scripts.smc_provider_policy.fetch_news_benzinga")
    @patch("scripts.smc_provider_policy.fetch_news_fmp")
    def test_newsapi_fallback_receives_feed_cursor_state(self, mock_fmp, mock_bz, mock_newsapi):
        mock_fmp.side_effect = RuntimeError("FMP timeout")
        mock_bz.side_effect = RuntimeError("Benzinga timeout")
        mock_newsapi.return_value = ProviderResult(
            data={"bullish_tickers": [], "bearish_tickers": []},
            provider="newsapi_ai",
            meta={
                "provider_status": "ok_no_recent_matches",
                "status_detail": "Event Registry reachable, but no new symbol-matching NewsAPI.ai items were newer than the current cursor.",
                "cursor_before_epoch": 123.0,
                "cursor_before_uri": "uri-feed-1",
                "raw_record_count": 0,
                "matched_record_count": 0,
            },
        )

        result = resolve_domain(
            "news",
            fmp=MagicMock(),
            benzinga_api_key="bz-key",
            newsapi_ai_key="news-key",
            symbols=["NVDA"],
            newsapi_ai_feed_after_epoch=123.0,
            newsapi_ai_feed_after_uri="uri-feed-1",
        )

        assert mock_newsapi.call_args.kwargs["article_feed_after_epoch"] == 123.0
        assert mock_newsapi.call_args.kwargs["article_feed_after_uri"] == "uri-feed-1"
        attempts = result.meta["attempts"]
        assert [attempt["provider"] for attempt in attempts] == ["fmp", "benzinga", "newsapi_ai"]
        assert attempts[0]["provider_status"] == "timeout"
        assert attempts[0]["failure_class"] == "runtime"
        assert attempts[-1]["provider_status"] == "ok_no_recent_matches"
        assert attempts[-1]["cursor_before_uri"] == "uri-feed-1"

    @patch("scripts.smc_provider_policy.fetch_calendar_benzinga")
    @patch("scripts.smc_provider_policy.fetch_calendar_fmp")
    def test_calendar_fmp_fails_benzinga_succeeds(self, mock_fmp, mock_bz):
        mock_fmp.side_effect = RuntimeError("FMP down")
        mock_bz.return_value = ProviderResult(
            data={"earnings_today_tickers": "AAPL"},
            provider="benzinga",
        )
        result = resolve_domain(
            "calendar", fmp=MagicMock(), benzinga_api_key="bz-key", symbols=["AAPL"],
        )
        assert result.ok is True
        assert result.provider == "benzinga"
        assert "fmp" in result.stale

    @patch("scripts.smc_provider_policy.fetch_technical_tradingview")
    @patch("scripts.smc_provider_policy.fetch_technical_fmp")
    def test_technical_fmp_fails_tradingview_succeeds(self, mock_fmp, mock_tv):
        mock_fmp.side_effect = RuntimeError("FMP rate limit")
        mock_tv.return_value = ProviderResult(
            data={"strength": 0.7, "bias": "BULLISH"},
            provider="tradingview",
        )
        result = resolve_domain("technical", fmp=MagicMock())
        assert result.ok is True
        assert result.provider == "tradingview"
        assert "fmp" in result.stale

    @patch("scripts.smc_provider_policy.fetch_news_newsapi_ai")
    @patch("scripts.smc_provider_policy.fetch_news_benzinga")
    @patch("scripts.smc_provider_policy.fetch_news_fmp")
    def test_all_news_providers_fail_returns_empty(self, mock_fmp, mock_bz, mock_newsapi):
        mock_fmp.side_effect = RuntimeError("FMP error")
        mock_bz.side_effect = RuntimeError("Benzinga error")
        mock_newsapi.side_effect = RuntimeError("NewsAPI.ai error")
        result = resolve_domain(
            "news",
            fmp=MagicMock(),
            benzinga_api_key="bz-key",
            newsapi_ai_key="news-key",
            symbols=["AAPL"],
        )
        assert result.ok is False
        assert result.provider == "none"
        assert "fmp" in result.stale
        assert "benzinga" in result.stale
        assert "newsapi_ai" in result.stale

    @patch("scripts.smc_provider_policy.fetch_news_newsapi_ai")
    @patch("scripts.smc_provider_policy.fetch_news_benzinga")
    @patch("scripts.smc_provider_policy.fetch_news_fmp")
    def test_newsapi_quota_exhausted_degrades_to_none(self, mock_fmp, mock_bz, mock_newsapi):
        mock_fmp.side_effect = RuntimeError("FMP timeout")
        mock_bz.side_effect = RuntimeError("Benzinga timeout")
        mock_newsapi.side_effect = NewsApiAiProviderError(
            "quota_exhausted",
            "Event Registry token quota exhausted or paid plan required",
            status_code=403,
        )

        result = resolve_domain(
            "news",
            fmp=MagicMock(),
            benzinga_api_key="bz-key",
            newsapi_ai_key="news-key",
            symbols=["NVDA"],
        )

        assert result.ok is False
        assert result.provider == "none"
        assert result.stale == ["fmp", "benzinga", "newsapi_ai"]
        assert result.meta["provider_status"] == "no_data"
        assert result.meta["attempts"][-1]["provider_status"] == "quota_exhausted"
        assert result.meta["attempts"][-1]["failure_class"] == "provider_error"


# ── Test 5: Malformed payloads ──────────────────────────────────


class TestMalformedPayloads:
    """Adapters handle broken data gracefully."""

    def test_regime_fmp_reports_macro_and_sector_diagnostics(self):
        fmp = MagicMock()
        fmp.get_index_quote.return_value = {"price": 19.2}
        fmp.get_sector_performance.return_value = [
            {"sector": "Technology", "changesPercentage": 1.2},
            {"sector": "Financials", "changesPercentage": 0.8},
            {"sector": "Energy", "changesPercentage": -0.6},
        ]
        fmp.get_macro_calendar.return_value = [
            {
                "country": "US",
                "currency": "USD",
                "date": "2026-03-28",
                "event": "Core CPI MoM",
                "actual": 0.3,
                "consensus": 0.2,
                "impact": "High",
            }
        ]

        result = fetch_regime_fmp(fmp)

        assert result.ok is True
        assert result.data["macro_bias"] == pytest.approx(-0.5)
        assert result.data["sector_breadth"] == pytest.approx(0.6667)
        diagnostics = result.meta["diagnostics"]
        assert diagnostics["vix_present"] is True
        assert diagnostics["sector_row_count"] == 3
        assert diagnostics["macro_event_count"] == 1
        assert diagnostics["macro_events_considered"] == 1
        assert diagnostics["macro_inputs_used"] == ["Core CPI MoM"]
        assert diagnostics["macro_score_components"][0]["canonical_event"] == "core_cpi_mom"
        assert diagnostics["sector_fetch"]["status"] == "ok"
        assert diagnostics["macro_input_diagnostics"]["raw_event_count"] == 1
        assert diagnostics["macro_event_audit"][0]["used_for_scoring"] is True

    def test_regime_fmp_reports_rejected_macro_events_and_empty_sector_fetch(self):
        fmp = MagicMock()
        fmp.get_index_quote.return_value = {"price": 19.2}
        fmp.get_sector_performance.return_value = []
        fmp.get_macro_calendar.return_value = [
            {
                "country": "JP",
                "currency": "JPY",
                "date": "2026-04-12 23:50:00",
                "event": "M3 Money Supply (Mar)",
                "actual": None,
                "estimate": None,
                "impact": "Low",
            },
            {
                "country": "US",
                "currency": "USD",
                "date": "2026-04-12 08:30:00",
                "event": "Core CPI MoM",
                "actual": 0.3,
                "consensus": None,
                "impact": "High",
            },
        ]

        result = fetch_regime_fmp(fmp)

        diagnostics = result.meta["diagnostics"]
        assert diagnostics["sector_fetch"]["status"] == "empty"
        assert diagnostics["sector_fetch"]["returned_row_count"] == 0
        assert diagnostics["macro_event_count"] == 2
        assert diagnostics["macro_events_considered"] == 1
        assert diagnostics["macro_bias"] == pytest.approx(0.0)
        assert diagnostics["macro_input_diagnostics"]["raw_event_count"] == 2
        assert diagnostics["macro_input_diagnostics"]["us_scoped_event_count"] == 1
        assert diagnostics["macro_input_diagnostics"]["rejection_reason_counts"] == {
            "non_us_event": 1,
            "missing_consensus": 1,
        }

        audit_by_event = {entry["event"]: entry for entry in diagnostics["macro_event_audit"]}
        assert audit_by_event["M3 Money Supply (Mar)"]["rejection_reasons"] == ["non_us_event"]
        assert audit_by_event["Core CPI MoM"]["passes_us_scope"] is True
        assert "missing_consensus" in audit_by_event["Core CPI MoM"]["rejection_reasons"]

    def test_regime_fmp_frozen_macro_payload_normalizes_scope_consensus_and_dedupe(self):
        fmp = MagicMock()
        fmp.get_index_quote.return_value = {"price": 19.2}
        fmp.get_sector_performance.return_value = []
        fmp.get_macro_calendar.return_value = [
            {
                "country": "",
                "currency": "USD",
                "date": "2026-04-13 08:30:00",
                "event": "GDP Growth Rate QoQ",
                "actual": 3.1,
                "estimate": 2.3,
                "impact": "High",
                "unit": "%",
            },
            {
                "country": "US",
                "currency": "USD",
                "date": "2026-04-13 08:30:00",
                "event": "Gross Domestic Product QoQ",
                "actual": 3.0,
                "consensus": 2.2,
                "impact": "Medium",
                "unit": "%",
            },
            {
                "country": "US",
                "currency": "USD",
                "date": "2026-04-13 08:30:00",
                "event": "Initial Jobless Claims",
                "actual": 221,
                "forecast": 235,
                "impact": "High",
                "unit": "k",
            },
            {
                "country": "SV",
                "currency": "USD",
                "date": "2026-04-13 23:50:00",
                "event": "Inflation Rate YoY (Mar)",
                "actual": 1.8,
                "estimate": 1.9,
                "impact": "Low",
                "unit": "%",
            },
            {
                "country": "United States",
                "currency": "usd",
                "date": "2026-04-13 09:00:00",
                "event": "NFIB Business Optimism Index",
                "actual": 91.0,
                "estimate": 89.0,
                "impact": "Low",
                "unit": "index",
            },
        ]

        result = fetch_regime_fmp(fmp)

        diagnostics = result.meta["diagnostics"]
        assert diagnostics["macro_bias"] == pytest.approx(0.75)
        assert diagnostics["macro_event_count"] == 5
        assert diagnostics["macro_events_considered"] == 3
        assert diagnostics["macro_inputs_used"] == [
            "GDP Growth Rate QoQ",
            "Initial Jobless Claims",
            "NFIB Business Optimism Index",
        ]
        assert diagnostics["macro_input_diagnostics"] == {
            "raw_event_count": 5,
            "us_scoped_event_count": 4,
            "deduped_event_count": 3,
            "scored_event_count": 3,
            "contributing_event_count": 2,
            "rejection_reason_counts": {
                "deduped_duplicate": 1,
                "non_us_event": 1,
                "zero_weight": 1,
            },
            "quality_flag_counts": {},
        }

        audit_by_event = {entry["event"]: entry for entry in diagnostics["macro_event_audit"]}
        assert audit_by_event["GDP Growth Rate QoQ"]["passes_us_scope"] is True
        assert audit_by_event["GDP Growth Rate QoQ"]["country"] == "US"
        assert audit_by_event["GDP Growth Rate QoQ"]["consensus_field"] == "estimate"
        assert audit_by_event["GDP Growth Rate QoQ"]["canonical_event"] == "gdp_qoq"
        assert audit_by_event["GDP Growth Rate QoQ"]["contributed_to_bias"] is True
        assert audit_by_event["Gross Domestic Product QoQ"]["rejection_reasons"] == ["deduped_duplicate"]
        assert audit_by_event["Gross Domestic Product QoQ"]["passes_dedupe"] is False
        assert audit_by_event["Initial Jobless Claims"]["consensus_field"] == "forecast"
        assert audit_by_event["Initial Jobless Claims"]["canonical_event"] == "jobless_claims"
        assert audit_by_event["Initial Jobless Claims"]["contributed_to_bias"] is True
        assert audit_by_event["Inflation Rate YoY (Mar)"]["passes_us_scope"] is False
        assert audit_by_event["Inflation Rate YoY (Mar)"]["rejection_reasons"] == ["non_us_event"]
        assert audit_by_event["NFIB Business Optimism Index"]["passes_us_scope"] is True
        assert audit_by_event["NFIB Business Optimism Index"]["country"] == "US"
        assert audit_by_event["NFIB Business Optimism Index"]["rejection_reasons"] == ["zero_weight"]

        score_components = {
            component["canonical_event"]: component
            for component in diagnostics["macro_score_components"]
        }
        assert score_components["gdp_qoq"]["consensus_field"] == "estimate"
        assert score_components["gdp_qoq"]["contribution"] == pytest.approx(0.5)
        assert score_components["jobless_claims"]["consensus_field"] == "forecast"
        assert score_components["jobless_claims"]["contribution"] == pytest.approx(1.0)
        assert score_components["nfib_business_optimism_index"]["contribution"] == pytest.approx(0.0)

    def test_regime_fmp_reports_market_pe_modifier_diagnostics(self):
        fmp = MagicMock()
        fmp.get_index_quote.return_value = {"price": 14.2}
        fmp.get_sector_performance.return_value = [
            {"sector": "Technology", "changesPercentage": 1.2},
            {"sector": "Financials", "changesPercentage": 0.8},
            {"sector": "Industrials", "changesPercentage": 0.6},
            {"sector": "Energy", "changesPercentage": -0.4},
            {"sector": "Healthcare", "changesPercentage": 0.7},
        ]
        fmp.get_macro_calendar.return_value = [
            {
                "country": "US",
                "currency": "USD",
                "date": "2026-03-28",
                "event": "GDP Growth Rate QoQ",
                "actual": 3.1,
                "consensus": 2.3,
                "impact": "High",
            }
        ]
        fmp.get_market_pe_forward.return_value = 32.0
        fmp._last_market_pe_forward_diagnostics = {
            "status": "ok",
            "symbol": "SPY",
            "source_category": "approximate_ttm",
            "field": "pe",
            "price": 510.0,
            "forward_eps": None,
            "estimate_count": 0,
            "error": "",
        }

        result = fetch_regime_fmp(fmp)

        assert result.data["market_pe_forward"] == pytest.approx(32.0)
        assert result.data["market_pe_regime"] == "EXPENSIVE"
        assert result.data["macro_bias_raw"] > 0.0
        assert result.data["macro_bias_pe_adjustment"] < 0.0
        assert result.data["macro_bias"] < result.data["macro_bias_raw"]
        diagnostics = result.meta["diagnostics"]
        assert diagnostics["market_pe_fetch"]["symbol"] == "SPY"
        assert diagnostics["market_pe_fetch"]["source_category"] == "approximate_ttm"
        assert diagnostics["market_pe_regime"] == "EXPENSIVE"

    def test_news_fmp_reports_payload_diagnostics(self):
        fmp = MagicMock()
        fmp.get_stock_latest_news.return_value = [
            {"title": "AAPL beats earnings, strong growth", "tickers": ["AAPL"]},
            {"title": "TSLA misses estimates, weak outlook", "tickers": ["TSLA"]},
            {"title": "", "tickers": ["AAPL"]},
        ]

        result = fetch_news_fmp(fmp, ["AAPL", "TSLA"])

        diagnostics = result.meta["diagnostics"]
        assert diagnostics["article_count"] == 3
        assert diagnostics["matched_article_count"] == 3
        assert diagnostics["empty_headline_count"] == 1
        assert diagnostics["polarity_distribution"] == {
            "positive": 1,
            "negative": 1,
            "neutral": 1,
        }

    def test_regime_fmp_returns_none_rsi(self):
        fmp = MagicMock()
        fmp.get_index_quote.return_value = {"price": None}
        fmp.get_sector_performance.return_value = []
        fmp.get_macro_calendar.return_value = []
        result = fetch_regime_fmp(fmp)
        # Should still return a valid result with defaults
        assert result.ok is True
        assert result.provider == "fmp"
        assert "regime" in result.data

    def test_regime_fmp_vix_non_numeric(self):
        fmp = MagicMock()
        fmp.get_index_quote.return_value = {"price": "INVALID"}
        fmp.get_sector_performance.return_value = []
        fmp.get_macro_calendar.return_value = []
        # float("INVALID") raises → caught in fetch_regime_fmp
        result = fetch_regime_fmp(fmp)
        assert result.ok is True
        assert "fmp_vix" in result.stale

    def test_news_fmp_empty_articles(self):
        fmp = MagicMock()
        fmp.get_stock_latest_news.return_value = []
        result = fetch_news_fmp(fmp, ["AAPL"])
        assert result.ok is True
        assert result.data["bullish_tickers"] == []

    def test_news_fmp_uses_snippet_text_for_sentiment(self):
        fmp = MagicMock()
        fmp.get_stock_latest_news.return_value = [
            {
                "title": "AAPL corporate update",
                "text": "Shares rally after the company beats earnings and raises guidance.",
                "tickers": ["AAPL"],
            },
        ]

        result = fetch_news_fmp(fmp, ["AAPL"])

        assert result.ok is True
        assert result.data["bullish_tickers"] == ["AAPL"]
        assert result.meta["diagnostics"]["polarity_distribution"] == {
            "positive": 1,
            "negative": 0,
            "neutral": 0,
        }

    @patch("scripts.smc_news_scorer.compute_news_sentiment")
    @patch("scripts.smc_newsapi_ai.fetch_newsapi_records")
    def test_news_newsapi_ai_reports_no_recent_matches_when_cursor_active(self, mock_fetch_records, mock_score):
        mock_fetch_records.return_value = []
        mock_score.return_value = {
            "bullish_tickers": [],
            "bearish_tickers": [],
            "neutral_tickers": [],
            "news_heat_global": 0.0,
            "ticker_heat_map": "",
        }

        result = fetch_news_newsapi_ai(
            "news-key",
            ["AAPL"],
            article_feed_after_epoch=123.0,
            article_feed_after_uri="uri-feed-1",
        )

        assert result.provider == "newsapi_ai"
        assert result.meta["provider_status"] == "ok_no_recent_matches"
        assert "feed window" in result.meta["status_detail"]
        assert result.meta["cursor_before_epoch"] == 123.0
        assert result.meta["cursor_before_uri"] == "uri-feed-1"
        assert result.meta["raw_record_count"] == 0
        assert result.meta["matched_record_count"] == 0

    def test_news_fmp_tickers_is_string(self):
        fmp = MagicMock()
        fmp.get_stock_latest_news.return_value = [
            {"title": "Big move", "tickers": "AAPL,MSFT", "symbol": ""},
        ]
        result = fetch_news_fmp(fmp, ["AAPL", "MSFT"])
        assert result.ok is True

    def test_technical_fmp_no_rsi_raises(self):
        fmp = MagicMock()
        fmp.get_technical_indicator.return_value = {}
        with pytest.raises(ValueError, match="no RSI data"):
            fetch_technical_fmp(fmp)

    @patch("terminal_technicals.fetch_technicals")
    def test_technical_tradingview_uses_real_tradingview_adapter(self, mock_fetch, monkeypatch):
        import terminal_technicals

        monkeypatch.setattr(terminal_technicals, "_TV_AVAILABLE", True)
        mock_fetch.return_value = SimpleNamespace(
            summary_buy=8,
            summary_sell=2,
            summary_neutral=0,
            error="",
        )

        result = fetch_technical_tradingview("AAPL")

        assert result.provider == "tradingview"
        assert result.data == {"strength": 0.6, "bias": "BULLISH"}
        mock_fetch.assert_called_once_with("AAPL", "1D")

    @patch("terminal_technicals.fetch_technicals")
    def test_technical_tradingview_rejects_non_tradingview_fallback_path(self, mock_fetch, monkeypatch):
        import terminal_technicals

        monkeypatch.setattr(terminal_technicals, "_TV_AVAILABLE", False)

        with pytest.raises(ValueError, match="adapter not available"):
            fetch_technical_tradingview("AAPL")

        mock_fetch.assert_not_called()

    @patch("terminal_technicals.fetch_technicals")
    def test_technical_tradingview_raises_on_adapter_error(self, mock_fetch, monkeypatch):
        import terminal_technicals

        monkeypatch.setattr(terminal_technicals, "_TV_AVAILABLE", True)
        mock_fetch.return_value = SimpleNamespace(
            summary_buy=0,
            summary_sell=0,
            summary_neutral=0,
            error="symbol not found",
        )

        with pytest.raises(ValueError, match="returned no data"):
            fetch_technical_tradingview("AAPL")

    def test_calendar_fmp_empty_earnings(self):
        fmp = MagicMock()
        fmp.get_earnings_calendar.return_value = []
        fmp.get_macro_calendar.return_value = []
        result = fetch_calendar_fmp(fmp, ["AAPL"])
        assert result.ok is True
        assert result.data["earnings_today_tickers"] == ""


# ── Test 6: Deterministic PROVIDER_COUNT / STALE_PROVIDERS ──────


class TestProviderCountAndStale:
    """build_enrichment produces deterministic provider provenance."""

    @patch("scripts.smc_v55_lean_normalization.normalize_v55_lean_enrichment", side_effect=lambda enrichment, snapshot=None: enrichment)
    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_build_enrichment_persists_newsapi_feed_state(self, mock_resolve, _mock_normalize, tmp_path):
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        state_path = tmp_path / "newsapi_ai_feed_state.json"
        state_path.write_text(
            json.dumps({
                "last_seen_epoch": 100.0,
                "last_seen_news_uri": "uri-feed-1",
            }),
            encoding="utf-8",
        )

        mock_resolve.return_value = ProviderResult(
            data={
                "bullish_tickers": ["AAPL"],
                "bearish_tickers": [],
                "neutral_tickers": [],
                "news_heat_global": 0.4,
                "ticker_heat_map": "AAPL:0.4",
            },
            provider="newsapi_ai",
            meta={
                "provider_status": "ok",
                "status_detail": "",
                "last_seen_epoch": 140.0,
                "last_seen_news_uri": "uri-feed-2",
                "attempts": [
                    {
                        "provider": "newsapi_ai",
                        "delivered_provider": "newsapi_ai",
                        "outcome": "success",
                        "provider_status": "ok",
                        "status_detail": "",
                    }
                ],
            },
        )

        enrichment = build_enrichment(
            fmp_api_key="",
            newsapi_ai_key="news-key",
            symbols=["AAPL"],
            enrich_news=True,
            newsapi_feed_state_path=state_path,
        )

        assert enrichment is not None
        assert mock_resolve.call_args.kwargs["newsapi_ai_feed_after_epoch"] == 100.0
        assert mock_resolve.call_args.kwargs["newsapi_ai_feed_after_uri"] == "uri-feed-1"
        assert json.loads(state_path.read_text(encoding="utf-8")) == {
            "last_seen_epoch": 140.0,
            "last_seen_news_uri": "uri-feed-2",
        }
        news_diag = enrichment["providers"]["domain_diagnostics"]["news"]
        assert news_diag["provider_status"] == "ok"
        assert news_diag["selected_provider"] == "newsapi_ai"
        assert news_diag["cursor"]["before"] == {
            "last_seen_epoch": 100.0,
            "last_seen_news_uri": "uri-feed-1",
        }
        assert news_diag["cursor"]["after"] == {
            "last_seen_epoch": 140.0,
            "last_seen_news_uri": "uri-feed-2",
        }
        assert news_diag["attempts"][-1]["provider"] == "newsapi_ai"

    @patch("scripts.smc_v55_lean_normalization.normalize_v55_lean_enrichment", side_effect=lambda enrichment, snapshot=None: enrichment)
    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_build_enrichment_merges_live_snapshot_with_provider_chain(self, mock_resolve, _mock_normalize, tmp_path):
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        snapshot_path = tmp_path / "smc_live_news_snapshot.json"
        snapshot_path.write_text(
            json.dumps(
                {
                    "stories": [
                        {
                            "headline": "AAPL misses estimates, weak outlook, loss widens",
                            "tickers": ["AAPL"],
                        },
                        {
                            "headline": "TSLA misses estimates, weak outlook, loss widens",
                            "tickers": ["TSLA"],
                        },
                    ],
                    "summary": {
                        "active_story_count": 2,
                        "new_story_count": 2,
                        "actionable_story_count": 0,
                        "actionable_symbols": [],
                        "symbol_count": 2,
                    },
                    "providers": {
                        "newsapi_ai": {"ok": True, "new_item_count": 2},
                        "benzinga": {"ok": True, "new_item_count": 1},
                    },
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

        mock_resolve.return_value = ProviderResult(
            data={
                "bullish_tickers": ["AAPL"],
                "bearish_tickers": [],
                "neutral_tickers": [],
                "news_heat_global": 0.5,
                "ticker_heat_map": "AAPL:0.50",
            },
            provider="fmp",
            meta={
                "provider_status": "ok",
                "status_detail": "",
                "attempts": [
                    {
                        "provider": "fmp",
                        "delivered_provider": "fmp",
                        "outcome": "success",
                        "provider_status": "ok",
                        "status_detail": "",
                    }
                ],
            },
        )

        enrichment = build_enrichment(
            fmp_api_key="",
            symbols=["AAPL", "TSLA"],
            enrich_news=True,
            live_news_snapshot_path=snapshot_path,
        )

        assert enrichment is not None
        assert enrichment["providers"]["news_provider"] == "fmp"
        assert enrichment["news"]["bullish_tickers"] == []
        assert sorted(enrichment["news"]["bearish_tickers"]) == ["AAPL", "TSLA"]

        news_diag = enrichment["providers"]["domain_diagnostics"]["news"]
        assert news_diag["render_source"] == "provider_chain_plus_live_snapshot"
        assert news_diag["rendered_symbol_count"] == 2
        live_snapshot_diag = news_diag["diagnostics"]["live_snapshot"]
        base_diag = news_diag["diagnostics"]["base_provider_chain"]
        merge_diag = news_diag["diagnostics"]["merge"]
        rendered_diag = news_diag["diagnostics"]["rendered_payload"]
        assert base_diag["provider"] == "fmp"
        assert base_diag["provider_status"] == "ok"
        assert base_diag["rendered_payload"] == {
            "news_heat_global": 0.5,
            "symbol_count": 1,
            "bullish_ticker_count": 1,
            "bearish_ticker_count": 0,
            "neutral_ticker_count": 0,
        }
        assert base_diag["raw_diagnostics"] == {}
        assert live_snapshot_diag["snapshot_story_count"] == 2
        assert live_snapshot_diag["providers_with_new_items"] == ["benzinga", "newsapi_ai"]
        assert merge_diag["live_directional_override_count"] == 1
        assert merge_diag["live_added_count"] == 1
        assert merge_diag["base_news_heat_global"] == pytest.approx(0.5)
        assert rendered_diag["symbol_count"] == 2
        assert rendered_diag["bullish_ticker_count"] == 0
        assert rendered_diag["bearish_ticker_count"] == 2
        assert rendered_diag["neutral_ticker_count"] == 0
        assert rendered_diag["news_heat_global"] < 0  # bearish after live override

    @patch("scripts.smc_v55_lean_normalization.normalize_v55_lean_enrichment", side_effect=lambda enrichment, snapshot=None: enrichment)
    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_build_enrichment_uses_live_snapshot_when_provider_chain_returns_no_data(self, mock_resolve, _mock_normalize, tmp_path):
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        snapshot_path = tmp_path / "smc_live_news_snapshot.json"
        snapshot_path.write_text(
            json.dumps(
                {
                    "stories": [
                        {
                            "headline": "AAPL beats earnings, strong growth outlook",
                            "tickers": ["AAPL"],
                        }
                    ],
                    "summary": {
                        "active_story_count": 1,
                        "new_story_count": 1,
                        "actionable_story_count": 0,
                        "actionable_symbols": [],
                        "symbol_count": 1,
                    },
                    "providers": {
                        "newsapi_ai": {"ok": True, "new_item_count": 1},
                    },
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

        mock_resolve.return_value = ProviderResult(
            data={},
            provider="none",
            ok=False,
            stale=["fmp", "benzinga", "newsapi_ai"],
            meta={
                "provider_status": "no_data",
                "status_detail": "All configured providers in the chain failed.",
                "attempts": [
                    {
                        "provider": "fmp",
                        "delivered_provider": "none",
                        "outcome": "failed",
                        "provider_status": "provider_unavailable",
                        "status_detail": "FMP client not available",
                    }
                ],
            },
        )

        enrichment = build_enrichment(
            fmp_api_key="",
            symbols=["AAPL"],
            enrich_news=True,
            live_news_snapshot_path=snapshot_path,
        )

        assert enrichment is not None
        assert enrichment["providers"]["news_provider"] == "live_snapshot"
        assert enrichment["providers"]["provider_count"] == 2
        assert enrichment["news"]["bullish_tickers"] == ["AAPL"]

        news_diag = enrichment["providers"]["domain_diagnostics"]["news"]
        assert news_diag["selected_provider"] == "live_snapshot"
        assert news_diag["provider_status"] == "ok"
        assert news_diag["status_detail"] == "Provider chain returned no data; using live news snapshot overlay."

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_provider_count_matches_active_providers(self, mock_resolve):
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        def _side_effect(domain, **kw):
            return ProviderResult(data={"regime": "NEUTRAL"}, provider="fmp")

        mock_resolve.side_effect = _side_effect

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"], enrich_regime=True,
        )
        assert enrichment is not None
        # databento (base_scan) + fmp (regime) = 2
        assert enrichment["providers"]["provider_count"] == 2
        assert enrichment["providers"]["regime_provider"] == "fmp"
        assert enrichment["providers"]["base_scan_provider"] == "databento"

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_stale_providers_sorted_and_deduplicated(self, mock_resolve):
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        def _side_effect(domain, **kw):
            if domain == "regime":
                return ProviderResult(data={}, provider="none", ok=False, stale=["fmp"])
            if domain == "news":
                return ProviderResult(data={}, provider="none", ok=False, stale=["fmp", "benzinga"])
            return ProviderResult(data={}, provider="none", ok=False, stale=["fmp"])

        mock_resolve.side_effect = _side_effect

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"],
            enrich_regime=True, enrich_news=True, enrich_calendar=True,
        )
        assert enrichment is not None
        stale = enrichment["providers"]["stale_providers"]
        parts = stale.split(",")
        assert parts == sorted(parts)
        # fmp appears multiple times in stale lists but should be deduplicated
        assert parts == sorted(set(parts))

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_provider_count_zero_when_all_fail(self, mock_resolve):
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        mock_resolve.return_value = ProviderResult(
            data={}, provider="none", ok=False, stale=["fmp"],
        )

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"], enrich_regime=True,
        )
        assert enrichment is not None
        # databento (base_scan) is always counted
        assert enrichment["providers"]["provider_count"] == 1

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_multiple_domains_count_unique_providers(self, mock_resolve):
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        call_count = 0

        def _side_effect(domain, **kw):
            nonlocal call_count
            call_count += 1
            if domain in ("regime", "calendar"):
                return ProviderResult(data={"regime": "NEUTRAL"}, provider="fmp")
            if domain == "news":
                return ProviderResult(
                    data={"bullish_tickers": [], "bearish_tickers": [],
                          "neutral_tickers": [], "news_heat_global": 0.0,
                          "ticker_heat_map": ""},
                    provider="benzinga",
                )
            if domain == "technical":
                return ProviderResult(
                    data={"strength": 0.5, "bias": "NEUTRAL"},
                    provider="fmp",
                )
            return ProviderResult(data={}, provider="none", ok=False, stale=[])

        mock_resolve.side_effect = _side_effect

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"],
            enrich_regime=True, enrich_news=True, enrich_calendar=True,
            enrich_layering=True,
        )
        assert enrichment is not None
        # databento + fmp (regime, calendar, technical) + benzinga (news) = 3 unique
        assert enrichment["providers"]["provider_count"] == 3
        assert enrichment["providers"]["regime_provider"] == "fmp"
        assert enrichment["providers"]["news_provider"] == "benzinga"
        assert enrichment["providers"]["calendar_provider"] == "fmp"
        assert enrichment["providers"]["technical_provider"] == "fmp"

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_output_deterministic_across_calls(self, mock_resolve):
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        mock_resolve.return_value = ProviderResult(
            data={"regime": "NEUTRAL"}, provider="fmp",
        )

        e1 = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"], enrich_regime=True,
        )
        e2 = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"], enrich_regime=True,
        )
        # Same provider state (excluding timestamp which varies)
        assert e1["providers"] == e2["providers"]
        assert e1["regime"] == e2["regime"]


# ── Test 7: Provenance tracking ─────────────────────────────────


class TestProvenanceTracking:
    """Per-domain provider attribution in the enrichment payload."""

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_provenance_records_actual_provider(self, mock_resolve):
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        def _side_effect(domain, **kw):
            providers = {"regime": "fmp", "news": "benzinga"}
            p = providers.get(domain, "fmp")
            return ProviderResult(
                data={"regime": "NEUTRAL", "bullish_tickers": [],
                      "bearish_tickers": [], "neutral_tickers": [],
                      "news_heat_global": 0.0, "ticker_heat_map": ""},
                provider=p,
            )

        mock_resolve.side_effect = _side_effect

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"],
            enrich_regime=True, enrich_news=True,
        )
        assert enrichment is not None
        assert enrichment["providers"]["regime_provider"] == "fmp"
        assert enrichment["providers"]["news_provider"] == "benzinga"

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_provenance_records_none_on_total_failure(self, mock_resolve):
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        mock_resolve.return_value = ProviderResult(
            data={}, provider="none", ok=False, stale=["fmp"],
        )

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"], enrich_regime=True,
        )
        assert enrichment is not None
        assert enrichment["providers"]["regime_provider"] == "none"

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_no_provenance_for_disabled_domains(self, mock_resolve):
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        mock_resolve.return_value = ProviderResult(
            data={"regime": "NEUTRAL"}, provider="fmp",
        )

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"],
            enrich_regime=True, enrich_news=False,
        )
        assert enrichment is not None
        assert "regime_provider" in enrichment["providers"]
        assert "news_provider" not in enrichment["providers"]


# ── Test 8: ProviderResult dataclass ────────────────────────────


class TestProviderResult:
    def test_defaults(self):
        r = ProviderResult(data={"a": 1}, provider="fmp")
        assert r.ok is True
        assert r.stale == []
        assert r.meta == {}

    def test_failure(self):
        r = ProviderResult(data={}, provider="none", ok=False, stale=["fmp"])
        assert r.ok is False
        assert r.stale == ["fmp"]

    def test_stale_is_mutable_list(self):
        r = ProviderResult(data={}, provider="fmp")
        r.stale.append("extra")
        assert "extra" in r.stale


# ── Test 9: DomainPolicy accessors ──────────────────────────────


class TestDomainPolicy:
    def test_all_providers_includes_primary_and_fallbacks(self):
        p = DomainPolicy("test", primary="a", fallbacks=("b", "c"))
        assert p.all_providers == ("a", "b", "c")

    def test_all_providers_no_fallbacks(self):
        p = DomainPolicy("test", primary="a", fallbacks=())
        assert p.all_providers == ("a",)

    def test_frozen(self):
        p = DomainPolicy("test", primary="a", fallbacks=())
        with pytest.raises(AttributeError):
            p.primary = "b"  # type: ignore[misc]


# ── Test 10: Databento base-scan provenance ─────────────────────


class TestBaseScanProvenance:
    """build_enrichment always records Databento as the base-scan provider."""

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_base_scan_provider_always_databento(self, mock_resolve):
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        mock_resolve.return_value = ProviderResult(
            data={"regime": "NEUTRAL"}, provider="fmp",
        )
        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"], enrich_regime=True,
        )
        assert enrichment is not None
        assert enrichment["providers"]["base_scan_provider"] == "databento"

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_provider_count_includes_databento(self, mock_resolve):
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        mock_resolve.return_value = ProviderResult(
            data={"regime": "NEUTRAL"}, provider="fmp",
        )
        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"], enrich_regime=True,
        )
        assert enrichment is not None
        # databento (base_scan) + fmp (regime) = 2
        assert enrichment["providers"]["provider_count"] == 2

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_provider_count_with_all_domains(self, mock_resolve):
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        call_map = {
            "regime": ProviderResult(data={"regime": "NEUTRAL"}, provider="fmp"),
            "news": ProviderResult(
                data={"bullish_tickers": [], "bearish_tickers": [],
                      "neutral_tickers": [], "news_heat_global": 0.0,
                      "ticker_heat_map": ""},
                provider="benzinga",
            ),
            "calendar": ProviderResult(
                data={"earnings_today_tickers": ""}, provider="fmp",
            ),
            "technical": ProviderResult(
                data={"strength": 0.5, "bias": "NEUTRAL"}, provider="tradingview",
            ),
        }
        mock_resolve.side_effect = lambda domain, **kw: call_map[domain]

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"],
            enrich_regime=True, enrich_news=True,
            enrich_calendar=True, enrich_layering=True,
        )
        assert enrichment is not None
        # databento + fmp + benzinga + tradingview = 4 unique
        assert enrichment["providers"]["provider_count"] == 4
        assert enrichment["providers"]["base_scan_provider"] == "databento"


# ── Test 11: End-to-end fallback through build_enrichment ───────


class TestBuildEnrichmentFallbackPaths:
    """Integration tests exercising full domain fallback through build_enrichment."""

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_news_falls_back_to_benzinga_provenance(self, mock_resolve):
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        def _side_effect(domain, **kw):
            if domain == "news":
                return ProviderResult(
                    data={"bullish_tickers": ["NVDA"], "bearish_tickers": [],
                          "neutral_tickers": [], "news_heat_global": 0.3,
                          "ticker_heat_map": "NVDA:0.3"},
                    provider="benzinga",
                    stale=["fmp"],
                )
            return ProviderResult(data={"regime": "NEUTRAL"}, provider="fmp")

        mock_resolve.side_effect = _side_effect

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["NVDA"],
            enrich_regime=True, enrich_news=True,
        )
        assert enrichment is not None
        assert enrichment["providers"]["news_provider"] == "benzinga"
        assert enrichment["providers"]["regime_provider"] == "fmp"
        assert "fmp" in enrichment["providers"]["stale_providers"]
        assert enrichment["news"]["bullish_tickers"] == ["NVDA"]

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_calendar_falls_back_to_benzinga(self, mock_resolve):
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        def _side_effect(domain, **kw):
            if domain == "calendar":
                return ProviderResult(
                    data={"earnings_today_tickers": "AAPL"},
                    provider="benzinga",
                    stale=["fmp"],
                )
            return ProviderResult(data={"regime": "NEUTRAL"}, provider="fmp")

        mock_resolve.side_effect = _side_effect

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"],
            enrich_regime=True, enrich_calendar=True,
        )
        assert enrichment is not None
        assert enrichment["providers"]["calendar_provider"] == "benzinga"
        assert enrichment["calendar"]["earnings_today_tickers"] == "AAPL"

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_technical_falls_back_to_tradingview(self, mock_resolve):
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        def _side_effect(domain, **kw):
            if domain == "technical":
                return ProviderResult(
                    data={"strength": 0.7, "bias": "BULLISH"},
                    provider="tradingview",
                    stale=["fmp"],
                )
            return ProviderResult(data={"regime": "RISK_ON"}, provider="fmp")

        mock_resolve.side_effect = _side_effect

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"],
            enrich_regime=True, enrich_layering=True,
        )
        assert enrichment is not None
        assert enrichment["providers"]["technical_provider"] == "tradingview"
        assert "fmp" in enrichment["providers"]["stale_providers"]

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_all_domains_fail_gives_zero_enrichment_providers(self, mock_resolve):
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        mock_resolve.return_value = ProviderResult(
            data={}, provider="none", ok=False, stale=["fmp"],
        )

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"],
            enrich_regime=True, enrich_news=True,
            enrich_calendar=True, enrich_layering=True,
        )
        assert enrichment is not None
        # Only databento (base_scan) should be active — all domains returned "none"
        assert enrichment["providers"]["provider_count"] == 1
        assert enrichment["providers"]["base_scan_provider"] == "databento"
        stale = enrichment["providers"]["stale_providers"]
        assert "fmp" in stale

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_guaranteed_defaults_on_total_failure(self, mock_resolve):
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        mock_resolve.return_value = ProviderResult(
            data={}, provider="none", ok=False, stale=["fmp", "benzinga"],
        )

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"],
            enrich_regime=True, enrich_news=True,
            enrich_calendar=True, enrich_layering=True,
        )
        assert enrichment is not None
        # Regime falls back to safe default
        assert enrichment["regime"]["regime"] == "NEUTRAL"
        # News defaults
        assert enrichment["news"]["bullish_tickers"] == []
        assert enrichment["news"]["bearish_tickers"] == []
        assert enrichment["news"]["news_heat_global"] == 0.0
        # Calendar defaults
        assert enrichment["calendar"]["earnings_today_tickers"] == ""
        # Layering defaults (computation may succeed with neutral inputs)
        assert "layering" in enrichment

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_volume_regime_emitted_regardless_of_provider_state(self, mock_resolve):
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        mock_resolve.return_value = ProviderResult(
            data={"regime": "NEUTRAL"}, provider="fmp",
        )
        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"], enrich_regime=True,
        )
        assert enrichment is not None
        assert "volume_regime" in enrichment
        assert "low_tickers" in enrichment["volume_regime"]
        assert "holiday_suspect_tickers" in enrichment["volume_regime"]


# ── Test: Event-risk v5 wiring through build_enrichment ─────────


class TestEventRiskWiring:
    """Integration tests for the v5 event-risk layer wired through build_enrichment."""

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_event_risk_populated_when_enabled(self, mock_resolve):
        """Event-risk block is present when enrich_event_risk=True."""
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        mock_resolve.return_value = ProviderResult(
            data={"regime": "NEUTRAL"}, provider="fmp",
        )

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"],
            enrich_regime=True, enrich_event_risk=True,
        )
        assert enrichment is not None
        assert "event_risk" in enrichment
        assert enrichment["event_risk"]["EVENT_WINDOW_STATE"] == "CLEAR"
        assert enrichment["event_risk"]["EVENT_PROVIDER_STATUS"] == "ok"
        assert enrichment["providers"]["event_risk_provider"] == "smc_event_risk_builder"

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_event_risk_absent_when_disabled(self, mock_resolve):
        """No event_risk key when enrich_event_risk is False."""
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        mock_resolve.return_value = ProviderResult(
            data={"regime": "NEUTRAL"}, provider="fmp",
        )

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"], enrich_regime=True,
        )
        assert enrichment is not None
        assert "event_risk" not in enrichment
        assert "event_risk_provider" not in enrichment["providers"]

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_event_risk_derives_from_calendar_and_news(self, mock_resolve):
        """Event-risk builder receives actual calendar + news data from prior stages."""
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        def _side_effect(domain, **kw):
            if domain == "calendar":
                return ProviderResult(
                    data={
                        "earnings_today_tickers": "AAPL",
                        "earnings_tomorrow_tickers": "",
                        "earnings_bmo_tickers": "",
                        "earnings_amc_tickers": "",
                        "high_impact_macro_today": True,
                        "macro_event_name": "FOMC",
                        "macro_event_time": "14:00",
                    },
                    provider="fmp",
                )
            if domain == "news":
                return ProviderResult(
                    data={
                        "bullish_tickers": [], "bearish_tickers": ["AAPL"],
                        "neutral_tickers": [], "news_heat_global": 0.9,
                        "ticker_heat_map": "AAPL:0.9",
                    },
                    provider="fmp",
                )
            return ProviderResult(data={"regime": "NEUTRAL"}, provider="fmp")

        mock_resolve.side_effect = _side_effect

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"],
            enrich_regime=True, enrich_news=True,
            enrich_calendar=True, enrich_event_risk=True,
        )
        assert enrichment is not None
        er = enrichment["event_risk"]
        # FOMC should trigger macro detection
        assert er["NEXT_EVENT_CLASS"] == "MACRO"
        assert er["NEXT_EVENT_NAME"] == "FOMC"
        assert er["NEXT_EVENT_IMPACT"] == "HIGH"
        assert er["EVENT_RISK_LEVEL"] == "HIGH"
        # AAPL has earnings and is bearish — both should appear
        assert "AAPL" in er["EARNINGS_SOON_TICKERS"]
        assert "AAPL" in er["HIGH_RISK_EVENT_TICKERS"]
        assert er["EVENT_PROVIDER_STATUS"] == "ok"

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_event_risk_calendar_missing_status(self, mock_resolve):
        """EVENT_PROVIDER_STATUS='calendar_missing' when calendar provider fails."""
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        def _side_effect(domain, **kw):
            if domain == "calendar":
                return ProviderResult(
                    data={}, provider="none", ok=False, stale=["fmp", "benzinga"],
                )
            if domain == "news":
                return ProviderResult(
                    data={"bullish_tickers": [], "bearish_tickers": [],
                          "neutral_tickers": [], "news_heat_global": 0.0,
                          "ticker_heat_map": ""},
                    provider="fmp",
                )
            return ProviderResult(data={"regime": "NEUTRAL"}, provider="fmp")

        mock_resolve.side_effect = _side_effect

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"],
            enrich_regime=True, enrich_news=True,
            enrich_calendar=True, enrich_event_risk=True,
        )
        assert enrichment is not None
        assert enrichment["event_risk"]["EVENT_PROVIDER_STATUS"] == "calendar_missing"

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_event_risk_news_missing_status(self, mock_resolve):
        """EVENT_PROVIDER_STATUS='news_missing' when news provider fails."""
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        def _side_effect(domain, **kw):
            if domain == "news":
                return ProviderResult(
                    data={}, provider="none", ok=False, stale=["fmp", "benzinga"],
                )
            if domain == "calendar":
                return ProviderResult(
                    data={"earnings_today_tickers": "", "high_impact_macro_today": False},
                    provider="fmp",
                )
            return ProviderResult(data={"regime": "NEUTRAL"}, provider="fmp")

        mock_resolve.side_effect = _side_effect

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"],
            enrich_regime=True, enrich_news=True,
            enrich_calendar=True, enrich_event_risk=True,
        )
        assert enrichment is not None
        assert enrichment["event_risk"]["EVENT_PROVIDER_STATUS"] == "news_missing"

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_event_risk_no_data_when_both_fail(self, mock_resolve):
        """EVENT_PROVIDER_STATUS='no_data' when both calendar and news fail."""
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        def _side_effect(domain, **kw):
            if domain in ("news", "calendar"):
                return ProviderResult(
                    data={}, provider="none", ok=False, stale=["fmp"],
                )
            return ProviderResult(data={"regime": "NEUTRAL"}, provider="fmp")

        mock_resolve.side_effect = _side_effect

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"],
            enrich_regime=True, enrich_news=True,
            enrich_calendar=True, enrich_event_risk=True,
        )
        assert enrichment is not None
        assert enrichment["event_risk"]["EVENT_PROVIDER_STATUS"] == "no_data"

    @patch("databento_reference.get_reference_event_risk_snapshot")
    @patch("databento_reference.maybe_refresh_symbol_reference_cache")
    def test_event_risk_includes_reference_change_signal(
        self,
        mock_refresh_reference,
        mock_reference_snapshot,
    ):
        """Databento reference changes are folded into event_risk even without calendar/news."""
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        mock_reference_snapshot.return_value = {
            "provider_status": "ok",
            "reference_change_tickers": ["META"],
            "by_symbol": {
                "META": {
                    "event_types": ["LCC"],
                    "latest_effective_date": "2026-04-08",
                    "aliases": ["FB"],
                }
            },
        }

        enrichment = build_enrichment(
            fmp_api_key="key",
            symbols=["META"],
            enrich_regime=False,
            enrich_news=False,
            enrich_calendar=False,
            enrich_event_risk=True,
        )
        assert enrichment is not None
        er = enrichment["event_risk"]
        assert er["NEXT_EVENT_CLASS"] == "CORPORATE_ACTION"
        assert er["NEXT_EVENT_NAME"] == "Identifier change (LCC)"
        assert er["SYMBOL_EVENT_BLOCKED"] is True
        assert er["HIGH_RISK_EVENT_TICKERS"] == "META"
        assert er["EVENT_PROVIDER_STATUS"] == "ok"
        mock_refresh_reference.assert_called_once()

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_event_risk_provider_counted_in_active(self, mock_resolve):
        """event_risk_provider is counted in provider_count."""
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        mock_resolve.return_value = ProviderResult(
            data={"regime": "NEUTRAL"}, provider="fmp",
        )

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["AAPL"],
            enrich_regime=True, enrich_event_risk=True,
        )
        assert enrichment is not None
        # databento (base_scan) + fmp (regime) + smc_event_risk_builder = 3
        assert enrichment["providers"]["provider_count"] == 3

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_event_risk_with_benzinga_fallback(self, mock_resolve):
        """Event-risk correctly derives from Benzinga-provided calendar + news."""
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        def _side_effect(domain, **kw):
            if domain == "calendar":
                return ProviderResult(
                    data={
                        "earnings_today_tickers": "TSLA",
                        "earnings_tomorrow_tickers": "",
                        "earnings_bmo_tickers": "",
                        "earnings_amc_tickers": "",
                        "high_impact_macro_today": False,
                        "macro_event_name": "",
                        "macro_event_time": "",
                    },
                    provider="benzinga",
                    stale=["fmp"],
                )
            if domain == "news":
                return ProviderResult(
                    data={"bullish_tickers": ["TSLA"], "bearish_tickers": [],
                          "neutral_tickers": [], "news_heat_global": 0.2,
                          "ticker_heat_map": "TSLA:0.2"},
                    provider="benzinga",
                    stale=["fmp"],
                )
            return ProviderResult(data={"regime": "NEUTRAL"}, provider="fmp")

        mock_resolve.side_effect = _side_effect

        enrichment = build_enrichment(
            fmp_api_key="key", symbols=["TSLA"],
            enrich_regime=True, enrich_news=True,
            enrich_calendar=True, enrich_event_risk=True,
        )
        assert enrichment is not None
        er = enrichment["event_risk"]
        assert "TSLA" in er["EARNINGS_SOON_TICKERS"]
        assert er["SYMBOL_EVENT_BLOCKED"] is True
        assert er["EVENT_PROVIDER_STATUS"] == "ok"
        assert enrichment["providers"]["calendar_provider"] == "benzinga"
        assert enrichment["providers"]["news_provider"] == "benzinga"

    def test_event_risk_alone_triggers_enrichment(self):
        """enrich_event_risk=True alone (no other flags) returns enrichment."""
        from scripts.generate_smc_micro_base_from_databento import build_enrichment

        enrichment = build_enrichment(
            fmp_api_key="", symbols=["AAPL"],
            enrich_event_risk=True,
        )
        assert enrichment is not None
        assert "event_risk" in enrichment
        # With no calendar or news data, safe defaults apply
        assert enrichment["event_risk"]["EVENT_WINDOW_STATE"] == "CLEAR"
        assert enrichment["event_risk"]["EVENT_RISK_LEVEL"] == "NONE"
