"""Consumer-contract tests: verify Pine consumers only reference fields the library produces.

Three layers:
1. **Field-consumer matrix** — programmatically parse ``mp.FIELD`` references from
   SMC_Core_Engine.pine and assert each one exists in the canonical V4_FIELD_INVENTORY.
2. **BUS channel contract** — ensure Dashboard and Strategy BUS channels are a subset
   of those published by the Engine, and that neither imports the library directly.
3. **Fixture-based output validation** — full/degraded/stale enrichment generates
   correct defaults for every consumer-referenced field.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from scripts.smc_enrichment_types import EnrichmentDict
from scripts.smc_microstructure_base_runtime import generate_pine_library_from_base
from scripts.smc_schema_resolver import resolve_microstructure_schema_path

SCHEMA_PATH = resolve_microstructure_schema_path()
ROOT = Path(__file__).resolve().parent.parent

# ── Canonical field inventory (source of truth) ─────────────────

V4_FIELD_INVENTORY: set[str] = {
    # Core + Meta
    "ASOF_DATE", "ASOF_TIME", "UNIVERSE_ID", "LOOKBACK_DAYS", "UNIVERSE_SIZE",
    "REFRESH_COUNT",
    # Microstructure lists
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
}

# Fields the Engine actually reads via ``mp.FIELD``
ENGINE_CONSUMED_FIELDS: set[str] = {
    "CLEAN_RECLAIM_TICKERS", "STOP_HUNT_PRONE_TICKERS",
    "MIDDAY_DEAD_TICKERS", "RTH_ONLY_TICKERS",
    "WEAK_PREMARKET_TICKERS", "WEAK_AFTERHOURS_TICKERS",
    "FAST_DECAY_TICKERS",
    "ASOF_DATE",
    "MARKET_REGIME", "TRADE_STATE",
    "EARNINGS_TODAY_TICKERS", "HIGH_IMPACT_MACRO_TODAY",
    "NEWS_BEARISH_TICKERS", "NEWS_BULLISH_TICKERS",
    "VOLUME_LOW_TICKERS",
}

# BUS channels published by SMC_Core_Engine.pine
ENGINE_BUS_CHANNELS: set[str] = {
    "ZoneActive", "Armed", "Confirmed", "Ready",
    "EntryBest", "EntryStrict", "Trigger", "Invalidation",
    "QualityScore", "SourceKind", "StateCode",
    "TrendPack", "MetaPack",
    "HardGatesPackA", "HardGatesPackB",
    "QualityPackA", "QualityPackB", "QualityBoundsPack",
    "ModulePackA", "ModulePackB", "ModulePackC", "ModulePackD",
    "EnginePack",
    "StopLevel", "Target1", "Target2",
}

# BUS channels consumed by Dashboard and Strategy
DASHBOARD_BUS_CHANNELS: set[str] = {
    "ZoneActive", "Armed", "Confirmed", "Ready",
    "EntryBest", "EntryStrict", "Trigger", "Invalidation",
    "QualityScore", "SourceKind", "StateCode",
    "TrendPack", "MetaPack",
    "HardGatesPackA", "HardGatesPackB",
    "QualityPackA", "QualityPackB", "QualityBoundsPack",
    "ModulePackA", "ModulePackB", "ModulePackC", "ModulePackD",
    "EnginePack",
    "StopLevel", "Target1", "Target2",
}

STRATEGY_BUS_CHANNELS: set[str] = {
    "Armed", "Confirmed", "Ready",
    "EntryBest", "EntryStrict", "Trigger", "Invalidation",
    "QualityScore",
}

# ── Pine-file parsing helpers ───────────────────────────────────

_MP_FIELD_RE = re.compile(r"\bmp\.([A-Z][A-Z0-9_]+)")
_BUS_PLOT_RE = re.compile(r"'BUS\s+(\w+)'")
_BUS_INPUT_RE = re.compile(r"""input\.source\([^)]*"BUS\s+(\w+)"\)""")
_IMPORT_RE = re.compile(r"^\s*import\b.*smc_micro_profiles", re.MULTILINE)


def _read_pine(name: str) -> str:
    path = ROOT / name
    assert path.exists(), f"Pine file not found: {path}"
    return path.read_text(encoding="utf-8")


def _extract_mp_fields(pine_text: str) -> set[str]:
    return set(_MP_FIELD_RE.findall(pine_text))


def _extract_bus_plots(pine_text: str) -> set[str]:
    return set(_BUS_PLOT_RE.findall(pine_text))


def _extract_bus_inputs(pine_text: str) -> set[str]:
    return set(_BUS_INPUT_RE.findall(pine_text))


# ── Fixtures ────────────────────────────────────────────────────

def _base_row(sym: str) -> dict[str, object]:
    return {
        "asof_date": "2026-03-28",
        "symbol": sym,
        "exchange": "NASDAQ",
        "asset_type": "stock",
        "universe_bucket": "test_bucket",
        "history_coverage_days_20d": 20,
        "adv_dollar_rth_20d": 150_000_000.0,
        "avg_spread_bps_rth_20d": 1.2,
        "rth_active_minutes_share_20d": 0.95,
        "open_30m_dollar_share_20d": 0.20,
        "close_60m_dollar_share_20d": 0.22,
        "clean_intraday_score_20d": 0.92,
        "consistency_score_20d": 0.90,
        "close_hygiene_20d": 0.91,
        "wickiness_20d": 0.10,
        "pm_dollar_share_20d": 0.15,
        "pm_trades_share_20d": 0.14,
        "pm_active_minutes_share_20d": 0.20,
        "pm_spread_bps_20d": 3.0,
        "pm_wickiness_20d": 0.12,
        "midday_dollar_share_20d": 0.24,
        "midday_trades_share_20d": 0.23,
        "midday_active_minutes_share_20d": 0.25,
        "midday_spread_bps_20d": 2.0,
        "midday_efficiency_20d": 0.80,
        "ah_dollar_share_20d": 0.12,
        "ah_trades_share_20d": 0.11,
        "ah_active_minutes_share_20d": 0.14,
        "ah_spread_bps_20d": 3.0,
        "ah_wickiness_20d": 0.10,
        "reclaim_respect_rate_20d": 0.90,
        "reclaim_failure_rate_20d": 0.08,
        "reclaim_followthrough_r_20d": 1.60,
        "ob_sweep_reversal_rate_20d": 0.25,
        "ob_sweep_depth_p75_20d": 0.30,
        "fvg_sweep_reversal_rate_20d": 0.20,
        "fvg_sweep_depth_p75_20d": 0.28,
        "stop_hunt_rate_20d": 0.10,
        "setup_decay_half_life_bars_20d": 30.0,
        "early_vs_late_followthrough_ratio_20d": 0.90,
        "stale_fail_rate_20d": 0.10,
    }


@pytest.fixture()
def base_csv(tmp_path: Path) -> Path:
    df = pd.DataFrame([_base_row("AAPL"), _base_row("MSFT"), _base_row("NVDA")])
    csv_path = tmp_path / "test_base.csv"
    df.to_csv(csv_path, index=False)
    return csv_path


def _full_enrichment() -> EnrichmentDict:
    return EnrichmentDict(
        market_regime="RISK-ON",
        vix_level="LOW",
        macro_bias="BULLISH",
        sector_breadth="WIDE",
        news_bullish_tickers=["AAPL"],
        news_bearish_tickers=["TSLA"],
        news_neutral_tickers=["MSFT"],
        news_heat_global="2",
        ticker_heat_map="AAPL:3,TSLA:-2",
        earnings_today_tickers=["NVDA"],
        earnings_tomorrow_tickers=[],
        earnings_bmo_tickers=["NVDA"],
        earnings_amc_tickers=[],
        high_impact_macro_today="CPI 08:30",
        macro_event_name="CPI",
        macro_event_time="08:30",
        global_heat="3",
        global_strength="5",
        tone="BULLISH",
        trade_state="ACTIVE-LONG",
        provider_count=4,
        stale_providers="",
        volume_low_tickers=["GME"],
        holiday_suspect_tickers=[],
    )


def _stale_enrichment() -> EnrichmentDict:
    """Enrichment dict representing a stale/degraded source."""
    return EnrichmentDict(
        market_regime="UNKNOWN",
        vix_level="n/a",
        macro_bias="n/a",
        sector_breadth="n/a",
        news_bullish_tickers=[],
        news_bearish_tickers=[],
        news_neutral_tickers=[],
        news_heat_global="0",
        ticker_heat_map="",
        earnings_today_tickers=[],
        earnings_tomorrow_tickers=[],
        earnings_bmo_tickers=[],
        earnings_amc_tickers=[],
        high_impact_macro_today="NONE",
        macro_event_name="NONE",
        macro_event_time="",
        global_heat="0",
        global_strength="0",
        tone="NEUTRAL",
        trade_state="WAIT",
        provider_count=0,
        stale_providers="fmp,finnhub",
        volume_low_tickers=[],
        holiday_suspect_tickers=[],
    )


def _run_pipeline(
    base_csv: Path, tmp_path: Path, *, enrichment: EnrichmentDict | None
) -> str:
    result = generate_pine_library_from_base(
        base_csv_path=base_csv,
        schema_path=SCHEMA_PATH,
        output_root=tmp_path,
        enrichment=enrichment,
    )
    pine_path = result["pine_path"]
    return pine_path.read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════
# Layer 1 — Field-consumer matrix
# ═══════════════════════════════════════════════════════════════

class TestFieldConsumerMatrix:
    """Parse mp.FIELD references from SMC_Core_Engine.pine and validate
    them against the canonical V4 field inventory."""

    def test_engine_mp_fields_match_declared_set(self):
        """Fields parsed from the Pine source match ENGINE_CONSUMED_FIELDS."""
        text = _read_pine("SMC_Core_Engine.pine")
        found = _extract_mp_fields(text)
        assert found == ENGINE_CONSUMED_FIELDS, (
            f"Mismatch.\n"
            f"  In Pine but not in declared set: {found - ENGINE_CONSUMED_FIELDS}\n"
            f"  In declared set but not in Pine: {ENGINE_CONSUMED_FIELDS - found}"
        )

    def test_all_consumed_fields_in_inventory(self):
        """Every field the Engine reads must exist in V4_FIELD_INVENTORY."""
        text = _read_pine("SMC_Core_Engine.pine")
        consumed = _extract_mp_fields(text)
        missing = consumed - V4_FIELD_INVENTORY
        assert not missing, (
            f"Engine references fields not in V4 inventory: {missing}"
        )

    def test_consumed_is_subset_of_produced(self, base_csv: Path, tmp_path: Path):
        """Every field the Engine reads must appear as export const in the
        generated Pine library output."""
        pine_text = _run_pipeline(base_csv, tmp_path, enrichment=_full_enrichment())
        export_names = set(re.findall(r"export const \w+ (\w+)", pine_text))
        engine_text = _read_pine("SMC_Core_Engine.pine")
        consumed = _extract_mp_fields(engine_text)
        missing = consumed - export_names
        assert not missing, (
            f"Engine references fields missing from generated library: {missing}"
        )

    def test_no_other_pine_files_import_library(self):
        """Only SMC_Core_Engine.pine should import the micro-profiles library.
        Dashboard and Strategy must use BUS channels instead."""
        for name in ("SMC_Dashboard.pine", "SMC_Long_Strategy.pine",
                     "SMC++.pine", "SMC_Core_Zones.pine"):
            path = ROOT / name
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            assert not _IMPORT_RE.search(text), (
                f"{name} imports smc_micro_profiles directly — "
                f"it should use BUS channels from the Engine"
            )


# ═══════════════════════════════════════════════════════════════
# Layer 2 — BUS channel contract
# ═══════════════════════════════════════════════════════════════

class TestBusChannelContract:
    """Verify BUS channels published by the Engine match those consumed
    by Dashboard and Strategy."""

    def test_engine_publishes_declared_channels(self):
        text = _read_pine("SMC_Core_Engine.pine")
        published = _extract_bus_plots(text)
        assert published == ENGINE_BUS_CHANNELS, (
            f"BUS channel mismatch.\n"
            f"  Published but not declared: {published - ENGINE_BUS_CHANNELS}\n"
            f"  Declared but not published: {ENGINE_BUS_CHANNELS - published}"
        )

    def test_dashboard_channels_subset_of_engine(self):
        engine_text = _read_pine("SMC_Core_Engine.pine")
        published = _extract_bus_plots(engine_text)
        dash_text = _read_pine("SMC_Dashboard.pine")
        consumed = _extract_bus_inputs(dash_text)
        assert consumed == DASHBOARD_BUS_CHANNELS, (
            f"Dashboard BUS input mismatch.\n"
            f"  In Pine but not declared: {consumed - DASHBOARD_BUS_CHANNELS}\n"
            f"  Declared but not in Pine: {DASHBOARD_BUS_CHANNELS - consumed}"
        )
        orphans = consumed - published
        assert not orphans, (
            f"Dashboard reads BUS channels not published by Engine: {orphans}"
        )

    def test_strategy_channels_subset_of_engine(self):
        engine_text = _read_pine("SMC_Core_Engine.pine")
        published = _extract_bus_plots(engine_text)
        strat_text = _read_pine("SMC_Long_Strategy.pine")
        consumed = _extract_bus_inputs(strat_text)
        assert consumed == STRATEGY_BUS_CHANNELS, (
            f"Strategy BUS input mismatch.\n"
            f"  In Pine but not declared: {consumed - STRATEGY_BUS_CHANNELS}\n"
            f"  Declared but not in Pine: {STRATEGY_BUS_CHANNELS - consumed}"
        )
        orphans = consumed - published
        assert not orphans, (
            f"Strategy reads BUS channels not published by Engine: {orphans}"
        )

    def test_strategy_is_subset_of_dashboard(self):
        """Strategy channels should be a strict subset of Dashboard channels."""
        assert STRATEGY_BUS_CHANNELS < DASHBOARD_BUS_CHANNELS


# ═══════════════════════════════════════════════════════════════
# Layer 3 — Fixture-based output validation
# ═══════════════════════════════════════════════════════════════

class TestConsumerFieldDefaults:
    """Verify consumer-referenced fields have safe defaults under
    all enrichment scenarios."""

    def _get_field_value(self, pine_text: str, field: str) -> str | None:
        """Extract the assigned value of ``export const ... FIELD = VALUE``."""
        m = re.search(
            rf"export const \w+ {re.escape(field)}\s*=\s*(.+)", pine_text
        )
        return m.group(1).strip() if m else None

    def test_full_enrichment_consumer_fields(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_full_enrichment())
        for field in ENGINE_CONSUMED_FIELDS:
            val = self._get_field_value(text, field)
            assert val is not None, f"Consumer field {field} missing from output"
            assert val != "", f"Consumer field {field} has empty value"

    def test_no_enrichment_consumer_fields_have_defaults(
        self, base_csv: Path, tmp_path: Path
    ):
        """Without enrichment, every consumer-referenced field must still
        appear with a safe default (not missing or blank)."""
        text = _run_pipeline(base_csv, tmp_path, enrichment=None)
        for field in ENGINE_CONSUMED_FIELDS:
            val = self._get_field_value(text, field)
            assert val is not None, (
                f"Consumer field {field} missing from output (no enrichment)"
            )

    def test_stale_enrichment_consumer_fields(self, base_csv: Path, tmp_path: Path):
        """With stale/degraded enrichment, consumer fields must still have
        valid values (not None or error strings)."""
        text = _run_pipeline(base_csv, tmp_path, enrichment=_stale_enrichment())
        for field in ENGINE_CONSUMED_FIELDS:
            val = self._get_field_value(text, field)
            assert val is not None, (
                f"Consumer field {field} missing (stale enrichment)"
            )

    def test_no_enrichment_list_fields_are_empty_string(
        self, base_csv: Path, tmp_path: Path
    ):
        """Ticker-list fields should be empty-string when no enrichment is
        provided, so the Engine str.contains() calls match nothing."""
        text = _run_pipeline(base_csv, tmp_path, enrichment=None)
        news_and_calendar_lists = {
            "NEWS_BULLISH_TICKERS", "NEWS_BEARISH_TICKERS",
            "EARNINGS_TODAY_TICKERS", "VOLUME_LOW_TICKERS",
        }
        for field in news_and_calendar_lists:
            val = self._get_field_value(text, field)
            assert val is not None, f"{field} missing"
            # should be '""' (empty Pine string)
            assert val == '""', (
                f"{field} should be empty string without enrichment, got {val}"
            )

    def test_regime_defaults_without_enrichment(
        self, base_csv: Path, tmp_path: Path
    ):
        """MARKET_REGIME and TRADE_STATE should fallback to safe defaults
        that don't trigger blocking logic in the Engine."""
        text = _run_pipeline(base_csv, tmp_path, enrichment=None)
        regime = self._get_field_value(text, "MARKET_REGIME")
        trade = self._get_field_value(text, "TRADE_STATE")
        assert regime is not None and '"' in regime
        assert trade is not None and '"' in trade


# ═══════════════════════════════════════════════════════════════
# CI guard — fail on any contract drift
# ═══════════════════════════════════════════════════════════════

class TestCIConsumerFieldGuard:
    """CI-friendly guard: if a developer adds a new ``mp.FIELD`` reference
    to the Engine, these tests force an update to both
    ENGINE_CONSUMED_FIELDS and V4_FIELD_INVENTORY."""

    def test_engine_pine_has_no_unknown_mp_references(self):
        """Fail if Engine references an mp.FIELD not in ENGINE_CONSUMED_FIELDS.
        Forces the developer to explicitly update the contract."""
        text = _read_pine("SMC_Core_Engine.pine")
        found = _extract_mp_fields(text)
        unknown = found - ENGINE_CONSUMED_FIELDS
        assert not unknown, (
            f"SMC_Core_Engine.pine references new mp. fields not in "
            f"ENGINE_CONSUMED_FIELDS — update the contract: {unknown}"
        )

    def test_consumed_fields_all_in_v4_inventory(self):
        """Fail if ENGINE_CONSUMED_FIELDS has a field not in V4_FIELD_INVENTORY.
        Forces the developer to keep the inventory in sync."""
        orphan = ENGINE_CONSUMED_FIELDS - V4_FIELD_INVENTORY
        assert not orphan, (
            f"ENGINE_CONSUMED_FIELDS contains fields not in "
            f"V4_FIELD_INVENTORY: {orphan}"
        )

    def test_inventory_covers_all_consumer_fields(self):
        """Redundant cross-check: parse + compare in one assertion."""
        text = _read_pine("SMC_Core_Engine.pine")
        consumed = _extract_mp_fields(text)
        missing = consumed - V4_FIELD_INVENTORY
        assert not missing, (
            f"CI FAIL: engine reads mp.{{field}} not in V4_FIELD_INVENTORY. "
            f"Either add {missing} to the inventory or remove the reference."
        )
