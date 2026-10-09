"""Import smoke tests for root-level Python modules.

These tests verify that each module can be imported without crashing.
No functionality is tested — the goal is to catch broken imports,
missing dependencies, and module-level side effects.
"""
from __future__ import annotations

import importlib

import pytest

# Modules that are pure-logic and should import cleanly without env vars or mocking.
_PURE_MODULES = [
    "databento_client",
    "databento_provider",
    "databento_reference",
    "databento_session",
    "databento_universe",
    "databento_utils",
    "strategy_config",
    "open_prep_boundary",
    "terminal_status_helpers",
    "terminal_feed_state",
    "terminal_attention_state",
    "terminal_posture_state",
    "terminal_catalyst_state",
    "terminal_reaction_state",
    "terminal_resolution_state",
    "terminal_spike_detector",
    "terminal_spike_scanner",
    "terminal_notifications",
    "terminal_export",
    "terminal_forecast",
    "terminal_live_story_state",
    "terminal_technicals",
    "terminal_ai_insights",
    "terminal_bitcoin",
    "terminal_fmp_insights",
    "terminal_fmp_technicals",
    "terminal_finnhub",
    "terminal_newsapi",
    "terminal_tradingview_news",
    "terminal_databento",
    "terminal_ui_helpers",
    "terminal_feed_lifecycle",
    "terminal_background_poller",
    "terminal_poller",
]


@pytest.mark.parametrize("module_name", _PURE_MODULES)
def test_root_module_imports_cleanly(module_name: str) -> None:
    """Each module must import without raising."""
    mod = importlib.import_module(module_name)
    assert mod is not None
