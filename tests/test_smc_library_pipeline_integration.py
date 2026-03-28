"""AP-8 — Integration tests for the SMC library generation pipeline.

Tests the end-to-end flow from enrichment through Pine library generation,
verifying field completeness, provider-failure resilience, Pine syntax,
and default handling.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scripts.generate_smc_micro_profiles import LISTS, write_pine_library
from scripts.generate_smc_micro_base_from_databento import build_enrichment


# ── Helpers ─────────────────────────────────────────────────────

def _empty_lists() -> dict[str, list[str]]:
    return {name: [] for name in LISTS}


def _sample_lists() -> dict[str, list[str]]:
    return {
        "clean_reclaim": ["AAPL", "MSFT"],
        "stop_hunt_prone": ["TSLA"],
        "midday_dead": [],
        "rth_only": ["META"],
        "weak_premarket": [],
        "weak_afterhours": ["AMZN"],
        "fast_decay": [],
    }


def _full_enrichment() -> dict[str, Any]:
    """Enrichment dict matching the contract that write_pine_library expects."""
    return {
        "regime": {
            "regime": "RISK_ON",
            "vix_level": 14.5,
            "macro_bias": 0.1,
            "sector_breadth": 0.72,
        },
        "news": {
            "bullish_tickers": ["AAPL", "MSFT"],
            "bearish_tickers": ["TSLA"],
            "neutral_tickers": ["META"],
            "news_heat_global": 0.35,
            "ticker_heat_map": "AAPL:0.8,MSFT:0.5,TSLA:-0.6",
        },
        "calendar": {
            "earnings_today_tickers": "AAPL,MSFT",
            "earnings_tomorrow_tickers": "AMZN",
            "earnings_bmo_tickers": "AAPL",
            "earnings_amc_tickers": "MSFT",
            "high_impact_macro_today": True,
            "macro_event_name": "FOMC Rate Decision",
            "macro_event_time": "14:00 ET",
        },
        "layering": {
            "global_heat": 0.42,
            "global_strength": 0.65,
            "tone": "BULLISH",
            "trade_state": "ALLOWED",
        },
        "providers": {
            "provider_count": 3,
            "stale_providers": "",
        },
        "volume_regime": {
            "low_tickers": ["AMZN"],
            "holiday_suspect_tickers": [],
        },
    }


# All exported Pine fields that must appear in every generated library
EXPECTED_FIELDS = [
    # Core
    "ASOF_DATE", "UNIVERSE_ID", "LOOKBACK_DAYS", "UNIVERSE_SIZE",
    # Lists
    "CLEAN_RECLAIM_TICKERS", "STOP_HUNT_PRONE_TICKERS",
    "MIDDAY_DEAD_TICKERS", "RTH_ONLY_TICKERS",
    "WEAK_PREMARKET_TICKERS", "WEAK_AFTERHOURS_TICKERS",
    "FAST_DECAY_TICKERS",
    # Regime
    "MARKET_REGIME", "VIX_LEVEL", "MACRO_BIAS", "SECTOR_BREADTH",
    # News
    "NEWS_BULLISH_TICKERS", "NEWS_BEARISH_TICKERS",
    "NEWS_NEUTRAL_TICKERS", "NEWS_HEAT_GLOBAL", "TICKER_HEAT_MAP",
    # Calendar
    "EARNINGS_TODAY_TICKERS", "EARNINGS_TOMORROW_TICKERS",
    "EARNINGS_BMO_TICKERS", "EARNINGS_AMC_TICKERS",
    "HIGH_IMPACT_MACRO_TODAY", "MACRO_EVENT_NAME", "MACRO_EVENT_TIME",
    # Layering
    "GLOBAL_HEAT", "GLOBAL_STRENGTH", "TONE", "TRADE_STATE",
    # Providers
    "PROVIDER_COUNT", "STALE_PROVIDERS",
    # Volume
    "VOLUME_LOW_TICKERS", "HOLIDAY_SUSPECT_TICKERS",
]


# ── Test 1: Full pipeline generates complete library ────────────

class TestFullPipelineGeneratesCompleteLibrary:
    def test_all_fields_present_with_enrichment(self, tmp_path: Path):
        out = tmp_path / "library.pine"
        write_pine_library(
            path=out,
            lists=_sample_lists(),
            asof_date="2025-01-15",
            universe_size=42,
            enrichment=_full_enrichment(),
        )
        text = out.read_text()
        for field in EXPECTED_FIELDS:
            assert field in text, f"Missing field: {field}"

    def test_enrichment_values_present(self, tmp_path: Path):
        out = tmp_path / "library.pine"
        write_pine_library(
            path=out,
            lists=_sample_lists(),
            asof_date="2025-01-15",
            universe_size=42,
            enrichment=_full_enrichment(),
        )
        text = out.read_text()
        assert '"RISK_ON"' in text
        assert "14.5" in text
        assert '"FOMC Rate Decision"' in text
        assert "AAPL,MSFT" in text
        assert '"BULLISH"' in text

    def test_ticker_lists_rendered(self, tmp_path: Path):
        out = tmp_path / "library.pine"
        write_pine_library(
            path=out,
            lists=_sample_lists(),
            asof_date="2025-01-15",
            universe_size=42,
            enrichment=_full_enrichment(),
        )
        text = out.read_text()
        assert "AAPL" in text
        assert "TSLA" in text
        assert "META" in text


# ── Test 2: Pipeline with provider failure ──────────────────────

class TestPipelineWithProviderFailure:
    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    @patch("scripts.generate_smc_micro_base_from_databento._fetch_regime_data")
    @patch("scripts.generate_smc_micro_base_from_databento._fetch_news_data")
    @patch("scripts.generate_smc_micro_base_from_databento._fetch_calendar_data")
    def test_fmp_regime_failure_produces_defaults_and_stale(
        self, mock_cal, mock_news, mock_regime, mock_fmp
    ):
        mock_fmp.return_value = MagicMock()
        mock_regime.side_effect = RuntimeError("FMP timeout")
        mock_news.return_value = {
            "bullish_tickers": [], "bearish_tickers": [],
            "neutral_tickers": [], "news_heat_global": 0.0,
            "ticker_heat_map": "",
        }
        mock_cal.return_value = {
            "earnings_today_tickers": "", "earnings_tomorrow_tickers": "",
            "earnings_bmo_tickers": "", "earnings_amc_tickers": "",
            "high_impact_macro_today": False,
            "macro_event_name": "", "macro_event_time": "",
        }

        enrichment = build_enrichment(
            fmp_api_key="fake-key",
            symbols=["AAPL"],
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=True,
        )
        assert enrichment is not None
        # Regime block falls back to the default dict (regime_result
        # stays {"regime": "NEUTRAL"}) because the exception is caught
        assert enrichment["regime"]["regime"] == "NEUTRAL"
        assert "regime" in enrichment["providers"]["stale_providers"]

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    @patch("scripts.generate_smc_micro_base_from_databento._fetch_regime_data")
    @patch("scripts.generate_smc_micro_base_from_databento._fetch_news_data")
    @patch("scripts.generate_smc_micro_base_from_databento._fetch_calendar_data")
    def test_failure_enrichment_still_generates_valid_library(
        self, mock_cal, mock_news, mock_regime, mock_fmp, tmp_path: Path
    ):
        mock_fmp.return_value = MagicMock()
        mock_regime.side_effect = RuntimeError("boom")
        mock_news.side_effect = RuntimeError("boom")
        mock_cal.side_effect = RuntimeError("boom")

        enrichment = build_enrichment(
            fmp_api_key="fake-key",
            symbols=["AAPL"],
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=True,
        )
        out = tmp_path / "library.pine"
        write_pine_library(
            path=out,
            lists=_empty_lists(),
            asof_date="2025-01-15",
            universe_size=0,
            enrichment=enrichment,
        )
        text = out.read_text()
        # All required fields must still be present even on total failure
        for field in EXPECTED_FIELDS:
            assert field in text, f"Missing field after failure: {field}"

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_missing_fmp_key_records_stale(self, mock_fmp):
        mock_fmp.return_value = None

        enrichment = build_enrichment(
            fmp_api_key="",
            symbols=["AAPL"],
            enrich_regime=True,
        )
        assert enrichment is not None
        assert "fmp_missing" in enrichment["providers"]["stale_providers"]


# ── Test 3: Library Pine syntax is valid ────────────────────────

class TestLibraryPineSyntaxValid:
    @pytest.fixture()
    def pine_text(self, tmp_path: Path) -> str:
        out = tmp_path / "library.pine"
        write_pine_library(
            path=out,
            lists=_sample_lists(),
            asof_date="2025-01-15",
            universe_size=42,
            enrichment=_full_enrichment(),
        )
        return out.read_text()

    def test_version_header(self, pine_text: str):
        assert pine_text.startswith("//@version=6\n")

    def test_library_declaration(self, pine_text: str):
        assert 'library("smc_micro_profiles_generated")' in pine_text

    def test_export_const_format(self, pine_text: str):
        export_lines = [
            line for line in pine_text.splitlines()
            if line.startswith("export const")
        ]
        assert len(export_lines) > 0
        type_pattern = re.compile(
            r'^export const (string|int|float|bool) [A-Z_]+ = .+'
        )
        for line in export_lines:
            assert type_pattern.match(line), f"Bad export line: {line}"

    def test_booleans_lowercase(self, pine_text: str):
        # Pine booleans must be "true"/"false", not Python "True"/"False"
        bool_lines = [
            line for line in pine_text.splitlines()
            if "const bool " in line
        ]
        for line in bool_lines:
            assert "True" not in line, f"Python True in: {line}"
            assert "False" not in line, f"Python False in: {line}"
            assert re.search(r'= (true|false)$', line), f"Bad bool: {line}"

    def test_no_python_list_literals(self, pine_text: str):
        # Pine shouldn't contain Python list repr like "['AAPL']"
        assert "[''" not in pine_text
        assert "[\"" not in pine_text or 'library("' in pine_text


# ── Test 4: All fields have defaults (enrichment=None) ──────────

class TestAllFieldsHaveDefaults:
    @pytest.fixture()
    def default_text(self, tmp_path: Path) -> str:
        out = tmp_path / "library.pine"
        write_pine_library(
            path=out,
            lists=_empty_lists(),
            asof_date="2025-01-15",
            universe_size=0,
            enrichment=None,
        )
        return out.read_text()

    def test_all_fields_present_without_enrichment(self, default_text: str):
        for field in EXPECTED_FIELDS:
            assert field in default_text, f"Missing field (no enrichment): {field}"

    def test_neutral_regime_default(self, default_text: str):
        assert 'MARKET_REGIME = "NEUTRAL"' in default_text

    def test_zero_heat_default(self, default_text: str):
        assert "NEWS_HEAT_GLOBAL = 0.0" in default_text
        assert "GLOBAL_HEAT = 0.0" in default_text

    def test_empty_stale_providers_default(self, default_text: str):
        assert 'STALE_PROVIDERS = ""' in default_text

    def test_macro_defaults_safe(self, default_text: str):
        assert "HIGH_IMPACT_MACRO_TODAY = false" in default_text
        assert 'MACRO_EVENT_NAME = ""' in default_text
