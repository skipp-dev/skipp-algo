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

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scripts.smc_provider_policy import (
    ALL_POLICIES,
    DomainPolicy,
    POLICY_BASE_SCAN,
    POLICY_CALENDAR,
    POLICY_NEWS,
    POLICY_REGIME,
    POLICY_TECHNICAL,
    ProviderResult,
    fetch_calendar_fmp,
    fetch_news_fmp,
    fetch_regime_fmp,
    fetch_technical_fmp,
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

    def test_news_is_fmp_primary_benzinga_fallback(self):
        assert POLICY_NEWS.primary == "fmp"
        assert POLICY_NEWS.fallbacks == ("benzinga",)
        assert POLICY_NEWS.all_providers == ("fmp", "benzinga")

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

    def test_calendar_all_fail_returns_safe_default(self):
        result = resolve_domain("calendar", fmp=None, benzinga_api_key="", symbols=["AAPL"])
        assert result.ok is False
        assert "fmp" in result.stale
        assert "benzinga" in result.stale

    def test_technical_all_fail_returns_safe_default(self):
        result = resolve_domain("technical", fmp=None)
        assert result.ok is False
        assert "fmp" in result.stale

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

    @patch("scripts.smc_provider_policy.fetch_news_benzinga")
    @patch("scripts.smc_provider_policy.fetch_news_fmp")
    def test_both_news_fail_returns_empty(self, mock_fmp, mock_bz):
        mock_fmp.side_effect = RuntimeError("FMP error")
        mock_bz.side_effect = RuntimeError("Benzinga error")
        result = resolve_domain(
            "news", fmp=MagicMock(), benzinga_api_key="bz-key", symbols=["AAPL"],
        )
        assert result.ok is False
        assert result.provider == "none"
        assert "fmp" in result.stale
        assert "benzinga" in result.stale


# ── Test 5: Malformed payloads ──────────────────────────────────


class TestMalformedPayloads:
    """Adapters handle broken data gracefully."""

    def test_regime_fmp_returns_none_rsi(self):
        fmp = MagicMock()
        fmp.get_index_quote.return_value = {"price": None}
        fmp.get_sector_performance.return_value = []
        result = fetch_regime_fmp(fmp)
        # Should still return a valid result with defaults
        assert result.ok is True
        assert result.provider == "fmp"
        assert "regime" in result.data

    def test_regime_fmp_vix_non_numeric(self):
        fmp = MagicMock()
        fmp.get_index_quote.return_value = {"price": "INVALID"}
        fmp.get_sector_performance.return_value = []
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
