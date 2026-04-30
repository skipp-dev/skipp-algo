"""Tests for scripts/smc_enrichment_value_analysis.py (WP-OV7)."""

from __future__ import annotations

from scripts.smc_enrichment_value_analysis import (
    TradeEntry,
    analyze_enrichment_value,
    format_analysis_markdown,
)


def _sample_trades() -> list[TradeEntry]:
    return [
        TradeEntry(pnl=1.5, regime="trending", trust_tier="high", news_bias="bullish"),
        TradeEntry(pnl=-0.3, regime="ranging", trust_tier="low", news_bias="neutral"),
        TradeEntry(pnl=0.8, regime="trending", trust_tier="good", news_bias="bullish"),
        TradeEntry(pnl=-1.0, regime="ranging", trust_tier="low", news_bias="bearish"),
        TradeEntry(pnl=2.0, regime="trending", trust_tier="high", news_bias="neutral"),
        TradeEntry(pnl=0.1, regime="ranging", trust_tier="ok", news_bias="neutral"),
    ]


class TestEnrichmentValueAnalysis:
    def test_mock_trades_produce_buckets(self) -> None:
        results = analyze_enrichment_value(_sample_trades())
        assert "regime" in results
        assert "trust_tier" in results
        assert "news_bias" in results

        regime = results["regime"]
        assert "trending" in regime.buckets
        assert "ranging" in regime.buckets
        assert regime.buckets["trending"].count == 3
        assert regime.buckets["ranging"].count == 3
        assert regime.total_trades == 6

    def test_regime_gate_value(self) -> None:
        results = analyze_enrichment_value(_sample_trades())
        regime = results["regime"]
        # Trending trades have positive mean PnL → positive lift
        assert regime.buckets["trending"].mean_pnl > regime.baseline_mean_pnl
        assert regime.lift("trending") > 0
        # Ranging trades have negative mean PnL → negative lift
        assert regime.buckets["ranging"].mean_pnl < regime.baseline_mean_pnl
        assert regime.lift("ranging") < 0

    def test_trust_tier_correlation(self) -> None:
        results = analyze_enrichment_value(_sample_trades())
        trust = results["trust_tier"]
        # High trust tier has best PnL
        assert trust.buckets["high"].mean_pnl > trust.buckets["low"].mean_pnl

    def test_empty_log_returns_empty(self) -> None:
        results = analyze_enrichment_value([])
        for dim in ("regime", "trust_tier", "news_bias"):
            assert results[dim].total_trades == 0
            assert results[dim].buckets == {}
            assert results[dim].baseline_mean_pnl == 0.0


class TestFormatMarkdown:
    def test_markdown_contains_headings(self) -> None:
        results = analyze_enrichment_value(_sample_trades())
        md = format_analysis_markdown(results)
        assert "## Enrichment Value A/B Analysis" in md
        assert "### Regime" in md
        assert "### Trust Tier" in md
        assert "### News Bias" in md
        assert "Lift" in md
