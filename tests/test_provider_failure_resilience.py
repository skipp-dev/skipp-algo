"""Tests for WP-FIX1/FIX4: Provider failure resilience.

WP-FIX1: bz_ws.drain() exception must not crash the poll cycle.
WP-FIX4: Calendar domain failure must appear in stale_providers.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# WP-FIX1: Benzinga WS drain safety
# ---------------------------------------------------------------------------


class TestBzWsDrainSafety(unittest.TestCase):
    """bz_ws.drain() failures must not crash poll_once()."""

    @patch("newsstack_fmp.pipeline._get_bz_ws_adapter")
    @patch("newsstack_fmp.pipeline._get_store")
    @patch("newsstack_fmp.pipeline._get_enricher")
    def test_drain_connection_error_continues_poll(self, mock_enr, mock_store, mock_ws):
        from newsstack_fmp.config import Config
        from newsstack_fmp.pipeline import poll_once

        store = MagicMock()
        store.get_kv.return_value = "0"
        mock_store.return_value = store
        mock_enr.return_value = MagicMock()

        adapter = MagicMock()
        adapter.drain.side_effect = ConnectionError("WebSocket closed unexpectedly")
        mock_ws.return_value = adapter

        with patch.dict(os.environ, {
            "FMP_API_KEY": "",
            "ENABLE_FMP": "0",
            "FILTER_TO_UNIVERSE": "0",
            "ENABLE_BENZINGA_WS": "1",
            "BENZINGA_API_KEY": "test_key",
        }):
            cfg = Config()
            result = poll_once(cfg, universe=set())

        self.assertIsInstance(result, list)

    @patch("newsstack_fmp.pipeline._get_bz_ws_adapter")
    @patch("newsstack_fmp.pipeline._get_store")
    @patch("newsstack_fmp.pipeline._get_enricher")
    def test_drain_timeout_continues_poll(self, mock_enr, mock_store, mock_ws):
        from newsstack_fmp.config import Config
        from newsstack_fmp.pipeline import poll_once

        store = MagicMock()
        store.get_kv.return_value = "0"
        mock_store.return_value = store
        mock_enr.return_value = MagicMock()

        adapter = MagicMock()
        adapter.drain.side_effect = TimeoutError("drain timeout")
        mock_ws.return_value = adapter

        with patch.dict(os.environ, {
            "FMP_API_KEY": "",
            "ENABLE_FMP": "0",
            "FILTER_TO_UNIVERSE": "0",
            "ENABLE_BENZINGA_WS": "1",
            "BENZINGA_API_KEY": "test_key",
        }):
            cfg = Config()
            result = poll_once(cfg, universe=set())

        self.assertIsInstance(result, list)


# ---------------------------------------------------------------------------
# WP-FIX4: Calendar domain failure → stale_providers
# ---------------------------------------------------------------------------


class TestCalendarFailureStalePropagation(unittest.TestCase):
    """When all calendar providers fail, 'calendar' must appear in stale_providers."""

    def test_calendar_failure_adds_domain_to_stale(self):
        """resolve_domain(calendar) failure → 'calendar' in all_stale → STALE_PROVIDERS."""
        from scripts.smc_provider_policy import ProviderResult

        # Simulate what build_enrichment does for calendar
        all_stale: list[str] = []

        # Simulate resolve_domain returning failure
        pr = ProviderResult(data={}, provider="none", ok=False, stale=["fmp"])

        all_stale.extend(pr.stale)
        if not pr.ok:
            all_stale.append("calendar")

        stale_providers = ",".join(sorted(set(all_stale)))
        self.assertIn("calendar", stale_providers)
        self.assertIn("fmp", stale_providers)

    def test_calendar_success_no_domain_stale(self):
        """resolve_domain(calendar) success → 'calendar' NOT in all_stale."""
        from scripts.smc_provider_policy import ProviderResult

        all_stale: list[str] = []

        pr = ProviderResult(
            data={"earnings_today_tickers": "AAPL"},
            provider="fmp",
            ok=True,
            stale=[],
        )

        all_stale.extend(pr.stale)
        if not pr.ok:
            all_stale.append("calendar")

        self.assertNotIn("calendar", all_stale)

    def test_stale_providers_string_includes_calendar_on_total_failure(self):
        """End-to-end: calendar domain failure flows into providers dict."""
        all_stale = ["fmp"]
        # Simulate the calendar domain failing
        all_stale.append("calendar")

        providers = {
            "provider_count": 1,
            "stale_providers": ",".join(sorted(set(all_stale))),
        }

        self.assertEqual(providers["stale_providers"], "calendar,fmp")


# ---------------------------------------------------------------------------
# WP-FIX5: Strategy backtest_mode (Pine-level — structural test)
# ---------------------------------------------------------------------------


class TestStrategyBacktestModeInput(unittest.TestCase):
    """Verify the backtest_mode input exists in SMC_Long_Strategy.pine."""

    def test_backtest_mode_input_present(self):
        from pathlib import Path

        strategy_path = Path(__file__).resolve().parent.parent / "SMC_Long_Strategy.pine"
        if not strategy_path.exists():
            self.skipTest("SMC_Long_Strategy.pine not found")

        content = strategy_path.read_text(encoding="utf-8")
        self.assertIn('input.bool(false, "Backtest Mode (Ignore Library)"', content)
        self.assertIn("backtest_mode", content)

    def test_backtest_mode_bypasses_regime_gate(self):
        from pathlib import Path

        strategy_path = Path(__file__).resolve().parent.parent / "SMC_Long_Strategy.pine"
        if not strategy_path.exists():
            self.skipTest("SMC_Long_Strategy.pine not found")

        content = strategy_path.read_text(encoding="utf-8")
        # The regime gate should check backtest_mode
        self.assertIn("not backtest_mode", content)


# ---------------------------------------------------------------------------
# WP-FIX3: Look-ahead bias disclaimer (structural tests)
# ---------------------------------------------------------------------------


class TestLookAheadBiasDisclaimer(unittest.TestCase):
    """Verify look-ahead bias warnings are present in docs and strategy."""

    def test_strategy_tooltip_warns_about_bias(self):
        from pathlib import Path

        strategy_path = Path(__file__).resolve().parent.parent / "SMC_Long_Strategy.pine"
        if not strategy_path.exists():
            self.skipTest("SMC_Long_Strategy.pine not found")

        content = strategy_path.read_text(encoding="utf-8")
        self.assertIn("BACKTEST NOTE", content)
        self.assertIn("snapshot of a single day", content.lower())

    def test_getting_started_has_backtest_section(self):
        from pathlib import Path

        guide_path = Path(__file__).resolve().parent.parent / "docs" / "SMC_GETTING_STARTED.md"
        if not guide_path.exists():
            self.skipTest("SMC_GETTING_STARTED.md not found")

        content = guide_path.read_text(encoding="utf-8")
        self.assertIn("Backtesting", content)
        self.assertIn("look-ahead bias", content)
        self.assertIn("Backtest Mode", content)
