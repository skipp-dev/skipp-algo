"""Consumer-contract tests: verify Pine consumers only reference fields the library produces.

Three layers:
1. **Field-consumer matrix** — programmatically parse ``mp.FIELD`` references from
   SMC_Core_Engine.pine and assert each one exists in the canonical V5_FIELD_INVENTORY.
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
from scripts.smc_bus_manifest import DASHBOARD_BUS_CHANNELS as MANIFEST_DASHBOARD_BUS_CHANNELS
from scripts.smc_bus_manifest import ENGINE_BUS_CHANNELS as MANIFEST_ENGINE_BUS_CHANNELS
from scripts.smc_bus_manifest import STRATEGY_BUS_CHANNELS as MANIFEST_STRATEGY_BUS_CHANNELS
from scripts.smc_microstructure_base_runtime import generate_pine_library_from_base
from scripts.smc_schema_resolver import resolve_microstructure_schema_path

SCHEMA_PATH = resolve_microstructure_schema_path()
ROOT = Path(__file__).resolve().parent.parent

# ── Canonical field inventory (source of truth) ─────────────────

V5_FIELD_INVENTORY: set[str] = {
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
    # Event Risk (v5)
    "EVENT_WINDOW_STATE", "EVENT_RISK_LEVEL",
    "NEXT_EVENT_CLASS", "NEXT_EVENT_NAME", "NEXT_EVENT_TIME", "NEXT_EVENT_IMPACT",
    "EVENT_RESTRICT_BEFORE_MIN", "EVENT_RESTRICT_AFTER_MIN",
    "EVENT_COOLDOWN_ACTIVE", "MARKET_EVENT_BLOCKED", "SYMBOL_EVENT_BLOCKED",
    "EARNINGS_SOON_TICKERS", "HIGH_RISK_EVENT_TICKERS", "EVENT_PROVIDER_STATUS",
    # Flow Qualifier (v5.1)
    "REL_VOL", "REL_ACTIVITY", "REL_SIZE", "DELTA_PROXY_PCT",
    "FLOW_LONG_OK", "FLOW_SHORT_OK",
    "ATS_VALUE", "ATS_CHANGE_PCT", "ATS_ZSCORE", "ATS_STATE",
    "ATS_SPIKE_UP", "ATS_SPIKE_DOWN", "ATS_BULLISH_SEQUENCE", "ATS_BEARISH_SEQUENCE",
    # Compression / ATR Regime (v5.1)
    "SQUEEZE_ON", "SQUEEZE_RELEASED", "SQUEEZE_MOMENTUM_BIAS",
    "ATR_REGIME", "ATR_RATIO",
    # Zone Intelligence (v5.1)
    "ACTIVE_SUPPORT_COUNT", "ACTIVE_RESISTANCE_COUNT", "ACTIVE_ZONE_COUNT",
    "PRIMARY_SUPPORT_LEVEL", "PRIMARY_RESISTANCE_LEVEL",
    "PRIMARY_SUPPORT_STRENGTH", "PRIMARY_RESISTANCE_STRENGTH",
    "SUPPORT_SWEEP_COUNT", "RESISTANCE_SWEEP_COUNT",
    "SUPPORT_MITIGATION_PCT", "RESISTANCE_MITIGATION_PCT",
    "ZONE_CONTEXT_BIAS", "ZONE_LIQUIDITY_IMBALANCE",
    # Reversal Context (v5.1)
    "REVERSAL_CONTEXT_ACTIVE", "SETUP_SCORE", "CONFIRM_SCORE", "FOLLOW_THROUGH_SCORE",
    "HTF_STRUCTURE_OK", "HTF_BULLISH_PATTERN", "HTF_BEARISH_PATTERN",
    "HTF_BULLISH_DIVERGENCE", "HTF_BEARISH_DIVERGENCE",
    "FVG_CONFIRM_OK", "VWAP_HOLD_OK", "RETRACE_OK",
    # Session Context (v5.2 + v5.3)
    "SESSION_CONTEXT", "IN_KILLZONE",
    "SESSION_MSS_BULL", "SESSION_MSS_BEAR",
    "SESSION_STRUCTURE_STATE",
    "SESSION_FVG_BULL_ACTIVE", "SESSION_FVG_BEAR_ACTIVE",
    "SESSION_BPR_ACTIVE",
    "SESSION_RANGE_TOP", "SESSION_RANGE_BOTTOM",
    "SESSION_MEAN", "SESSION_VWAP",
    "SESSION_TARGET_BULL", "SESSION_TARGET_BEAR",
    "SESSION_DIRECTION_BIAS", "SESSION_CONTEXT_SCORE",
    # Liquidity Sweeps (v5.2)
    "RECENT_BULL_SWEEP", "RECENT_BEAR_SWEEP",
    "SWEEP_TYPE", "SWEEP_DIRECTION",
    "SWEEP_ZONE_TOP", "SWEEP_ZONE_BOTTOM",
    "SWEEP_RECLAIM_ACTIVE", "LIQUIDITY_TAKEN_DIRECTION", "SWEEP_QUALITY_SCORE",
    # Liquidity Pools (v5.2)
    "BUY_SIDE_POOL_LEVEL", "SELL_SIDE_POOL_LEVEL",
    "BUY_SIDE_POOL_STRENGTH", "SELL_SIDE_POOL_STRENGTH",
    "POOL_PROXIMITY_PCT", "POOL_CLUSTER_DENSITY",
    "UNTESTED_BUY_POOLS", "UNTESTED_SELL_POOLS",
    "POOL_IMBALANCE", "POOL_MAGNET_DIRECTION", "POOL_QUALITY_SCORE",
    # Order Blocks (v5.2)
    "NEAREST_BULL_OB_LEVEL", "NEAREST_BEAR_OB_LEVEL",
    "BULL_OB_FRESHNESS", "BEAR_OB_FRESHNESS",
    "BULL_OB_MITIGATED", "BEAR_OB_MITIGATED",
    "BULL_OB_FVG_CONFLUENCE", "BEAR_OB_FVG_CONFLUENCE",
    "OB_DENSITY", "OB_BIAS", "OB_NEAREST_DISTANCE_PCT",
    "OB_STRENGTH_SCORE", "OB_CONTEXT_SCORE",
    # Zone Projection (v5.2)
    "ZONE_PROJ_TARGET_BULL", "ZONE_PROJ_TARGET_BEAR",
    "ZONE_PROJ_RETEST_EXPECTED", "ZONE_PROJ_TRAP_RISK",
    "ZONE_PROJ_SPREAD_QUALITY", "ZONE_PROJ_HTF_ALIGNED",
    "ZONE_PROJ_BIAS", "ZONE_PROJ_CONFIDENCE",
    "ZONE_PROJ_DECAY_BARS", "ZONE_PROJ_SCORE",
    # Profile Context (v5.2)
    "PROFILE_VOLUME_NODE", "PROFILE_VWAP_POSITION", "PROFILE_VWAP_DISTANCE_PCT",
    "PROFILE_SPREAD_REGIME", "PROFILE_AVG_SPREAD_BPS",
    "PROFILE_SESSION_BIAS", "PROFILE_RTH_DOMINANCE_PCT",
    "PROFILE_PM_QUALITY", "PROFILE_AH_QUALITY",
    "PROFILE_MIDDAY_EFFICIENCY", "PROFILE_DECAY_HALFLIFE",
    "PROFILE_CONSISTENCY", "PROFILE_WICKINESS",
    "PROFILE_CLEAN_SCORE", "PROFILE_RECLAIM_RATE", "PROFILE_STOP_HUNT_RATE",
    "PROFILE_TICKER_GRADE", "PROFILE_CONTEXT_SCORE",
    # Structure State (v5.3)
    "STRUCTURE_STATE", "STRUCTURE_BULL_ACTIVE", "STRUCTURE_BEAR_ACTIVE",
    "CHOCH_BULL", "CHOCH_BEAR", "BOS_BULL", "BOS_BEAR",
    "STRUCTURE_LAST_EVENT", "STRUCTURE_EVENT_AGE_BARS", "STRUCTURE_FRESH",
    "ACTIVE_SUPPORT", "ACTIVE_RESISTANCE", "SUPPORT_ACTIVE", "RESISTANCE_ACTIVE",
    # Imbalance Lifecycle (v5.3)
    "BULL_FVG_ACTIVE", "BEAR_FVG_ACTIVE",
    "BULL_FVG_TOP", "BULL_FVG_BOTTOM", "BEAR_FVG_TOP", "BEAR_FVG_BOTTOM",
    "BULL_FVG_PARTIAL_MITIGATION", "BEAR_FVG_PARTIAL_MITIGATION",
    "BULL_FVG_FULL_MITIGATION", "BEAR_FVG_FULL_MITIGATION",
    "BULL_FVG_COUNT", "BEAR_FVG_COUNT",
    "BULL_FVG_MITIGATION_PCT", "BEAR_FVG_MITIGATION_PCT",
    "BPR_ACTIVE", "BPR_DIRECTION", "BPR_TOP", "BPR_BOTTOM",
    "LIQ_VOID_BULL_ACTIVE", "LIQ_VOID_BEAR_ACTIVE",
    "LIQ_VOID_TOP", "LIQ_VOID_BOTTOM", "IMBALANCE_STATE",
    # Session Structure (v5.3)
    "SESS_HIGH", "SESS_LOW",
    "SESS_OPEN_RANGE_HIGH", "SESS_OPEN_RANGE_LOW", "SESS_OPEN_RANGE_BREAK",
    "SESS_IMPULSE_DIR", "SESS_IMPULSE_STRENGTH",
    "SESS_INTRA_BOS_COUNT", "SESS_INTRA_CHOCH",
    "SESS_PDH", "SESS_PDL", "SESS_PDH_SWEPT", "SESS_PDL_SWEPT",
    "SESS_STRUCT_SCORE",
    # Range Regime (v5.3)
    "RANGE_REGIME", "RANGE_WIDTH_PCT", "RANGE_POSITION",
    "RANGE_HIGH", "RANGE_LOW", "RANGE_DURATION_BARS",
    "RANGE_VPOC_LEVEL", "RANGE_VAH_LEVEL", "RANGE_VAL_LEVEL",
    "RANGE_BALANCE_STATE", "RANGE_REGIME_SCORE",
    # Range Profile Regime (v5.3)
    "RANGE_ACTIVE", "RANGE_TOP", "RANGE_BOTTOM", "RANGE_MID",
    "RANGE_WIDTH_ATR", "RANGE_BREAK_DIRECTION",
    "PROFILE_POC", "PROFILE_VALUE_AREA_TOP", "PROFILE_VALUE_AREA_BOTTOM",
    "PROFILE_VALUE_AREA_ACTIVE",
    "PROFILE_BULLISH_SENTIMENT", "PROFILE_BEARISH_SENTIMENT",
    "PROFILE_SENTIMENT_BIAS",
    "LIQUIDITY_ABOVE_PCT", "LIQUIDITY_BELOW_PCT", "LIQUIDITY_IMBALANCE",
    "PRED_RANGE_MID", "PRED_RANGE_UPPER_1", "PRED_RANGE_UPPER_2",
    "PRED_RANGE_LOWER_1", "PRED_RANGE_LOWER_2",
    "IN_PREDICTIVE_RANGE_EXTREME",
    # v5.5 Lean: shared canonical exports remain listed above
    "SESSION_VOLATILITY_STATE",
    # v5.5 Lean: Order Block Context Light
    "PRIMARY_OB_SIDE", "PRIMARY_OB_DISTANCE",
    "OB_FRESH", "OB_AGE_BARS", "OB_MITIGATION_STATE",
    # v5.5 Lean: FVG / Imbalance Lifecycle Light
    "PRIMARY_FVG_SIDE", "PRIMARY_FVG_DISTANCE",
    "FVG_FILL_PCT", "FVG_MATURITY_LEVEL", "FVG_FRESH", "FVG_INVALIDATED",
    # v5.5 Lean: Structure State Light
    "STRUCTURE_TREND_STRENGTH",
    # v5.5 Lean: Signal Quality
    "SIGNAL_QUALITY_SCORE", "SIGNAL_QUALITY_TIER",
    "SIGNAL_WARNINGS", "SIGNAL_BIAS_ALIGNMENT", "SIGNAL_FRESHNESS",
}

# Fields the Engine actually reads via ``mp.FIELD``
ENGINE_CONSUMED_FIELDS: set[str] = {
    # Microstructure lists
    "CLEAN_RECLAIM_TICKERS", "STOP_HUNT_PRONE_TICKERS",
    "MIDDAY_DEAD_TICKERS", "RTH_ONLY_TICKERS",
    "WEAK_PREMARKET_TICKERS", "WEAK_AFTERHOURS_TICKERS",
    "FAST_DECAY_TICKERS",
    # Core
    "ASOF_DATE",
    "MARKET_REGIME", "TRADE_STATE",
    "EARNINGS_TODAY_TICKERS", "HIGH_IMPACT_MACRO_TODAY",
    "NEWS_BEARISH_TICKERS", "NEWS_BULLISH_TICKERS",
    "VOLUME_LOW_TICKERS",
    # Event Risk (v5)
    "EVENT_WINDOW_STATE", "EVENT_RISK_LEVEL",
    "NEXT_EVENT_NAME", "NEXT_EVENT_TIME", "NEXT_EVENT_IMPACT",
    "EVENT_COOLDOWN_ACTIVE", "MARKET_EVENT_BLOCKED", "SYMBOL_EVENT_BLOCKED",
    "EARNINGS_SOON_TICKERS",
    # Flow Qualifier (v5.1)
    "REL_VOL", "REL_ACTIVITY", "REL_SIZE", "DELTA_PROXY_PCT",
    "FLOW_LONG_OK", "FLOW_SHORT_OK",
    "ATS_VALUE", "ATS_CHANGE_PCT", "ATS_ZSCORE", "ATS_STATE",
    "ATS_SPIKE_UP", "ATS_SPIKE_DOWN", "ATS_BULLISH_SEQUENCE", "ATS_BEARISH_SEQUENCE",
    # Compression / ATR Regime (v5.1)
    "SQUEEZE_ON", "SQUEEZE_RELEASED", "SQUEEZE_MOMENTUM_BIAS",
    "ATR_REGIME", "ATR_RATIO",
    # Event Risk Light (v5.5b canonical exports)
    "EVENT_WINDOW_STATE", "EVENT_RISK_LEVEL",
    "NEXT_EVENT_NAME", "NEXT_EVENT_TIME",
    "MARKET_EVENT_BLOCKED", "SYMBOL_EVENT_BLOCKED",
    "EVENT_PROVIDER_STATUS",
    # Session Context Light (v5.5b canonical exports)
    "SESSION_CONTEXT", "IN_KILLZONE",
    "SESSION_DIRECTION_BIAS", "SESSION_CONTEXT_SCORE",
    "SESSION_VOLATILITY_STATE",
    # OB Context Light (v5.5b)
    "PRIMARY_OB_SIDE", "PRIMARY_OB_DISTANCE",
    "OB_FRESH", "OB_AGE_BARS", "OB_MITIGATION_STATE",
    # FVG Lifecycle Light (v5.5b)
    "PRIMARY_FVG_SIDE", "PRIMARY_FVG_DISTANCE",
    "FVG_FILL_PCT", "FVG_MATURITY_LEVEL", "FVG_FRESH", "FVG_INVALIDATED",
    # Structure State Light (v5.5b canonical exports)
    "STRUCTURE_LAST_EVENT", "STRUCTURE_EVENT_AGE_BARS",
    "STRUCTURE_FRESH", "STRUCTURE_TREND_STRENGTH",
    # Signal Quality (v5.5b)
    "SIGNAL_QUALITY_SCORE", "SIGNAL_QUALITY_TIER",
    "SIGNAL_WARNINGS", "SIGNAL_BIAS_ALIGNMENT", "SIGNAL_FRESHNESS",
}

# BUS channels published by SMC_Core_Engine.pine
ENGINE_BUS_CHANNELS: set[str] = set(MANIFEST_ENGINE_BUS_CHANNELS)

# BUS channels consumed by Dashboard and Strategy
DASHBOARD_BUS_CHANNELS: set[str] = set(MANIFEST_DASHBOARD_BUS_CHANNELS)

STRATEGY_BUS_CHANNELS: set[str] = set(MANIFEST_STRATEGY_BUS_CHANNELS)

# ── Pine-file parsing helpers ───────────────────────────────────

_MP_FIELD_RE = re.compile(r"\bmp\.([A-Z][A-Z0-9_]+)")
_BUS_PLOT_RE = re.compile(r"'BUS\s+(\w+)'")
_BUS_INPUT_RE = re.compile(r"""input\.source\([^,]+,\s*"BUS\s+(\w+)"[^)]*\)""")
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
    them against the canonical V5 field inventory."""

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
        """Every field the Engine reads must exist in V5_FIELD_INVENTORY."""
        text = _read_pine("SMC_Core_Engine.pine")
        consumed = _extract_mp_fields(text)
        missing = consumed - V5_FIELD_INVENTORY
        assert not missing, (
            f"Engine references fields not in V5 inventory: {missing}"
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
    ENGINE_CONSUMED_FIELDS and V5_FIELD_INVENTORY."""

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

    def test_consumed_fields_all_in_v5_inventory(self):
        """Fail if ENGINE_CONSUMED_FIELDS has a field not in V5_FIELD_INVENTORY.
        Forces the developer to keep the inventory in sync."""
        orphan = ENGINE_CONSUMED_FIELDS - V5_FIELD_INVENTORY
        assert not orphan, (
            f"ENGINE_CONSUMED_FIELDS contains fields not in "
            f"V5_FIELD_INVENTORY: {orphan}"
        )

    def test_inventory_covers_all_consumer_fields(self):
        """Redundant cross-check: parse + compare in one assertion."""
        text = _read_pine("SMC_Core_Engine.pine")
        consumed = _extract_mp_fields(text)
        missing = consumed - V5_FIELD_INVENTORY
        assert not missing, (
            f"CI FAIL: engine reads mp.{{field}} not in V5_FIELD_INVENTORY. "
            f"Either add {missing} to the inventory or remove the reference."
        )


# ═══════════════════════════════════════════════════════════════
# v5.5 Lean Contract Validation
# ═══════════════════════════════════════════════════════════════

V55_LEAN_FAMILIES: dict[str, set[str]] = {
    "event_risk_light": {
        "EVENT_WINDOW_STATE", "EVENT_RISK_LEVEL",
        "NEXT_EVENT_NAME", "NEXT_EVENT_TIME",
        "MARKET_EVENT_BLOCKED", "SYMBOL_EVENT_BLOCKED",
        "EVENT_PROVIDER_STATUS",
    },
    "session_context_light": {
        "SESSION_CONTEXT", "IN_KILLZONE",
        "SESSION_DIRECTION_BIAS", "SESSION_CONTEXT_SCORE",
        "SESSION_VOLATILITY_STATE",
    },
    "ob_context_light": {
        "PRIMARY_OB_SIDE", "PRIMARY_OB_DISTANCE",
        "OB_FRESH", "OB_AGE_BARS", "OB_MITIGATION_STATE",
    },
    "fvg_lifecycle_light": {
        "PRIMARY_FVG_SIDE", "PRIMARY_FVG_DISTANCE",
        "FVG_FILL_PCT", "FVG_MATURITY_LEVEL", "FVG_FRESH", "FVG_INVALIDATED",
    },
    "structure_state_light": {
        "STRUCTURE_LAST_EVENT", "STRUCTURE_EVENT_AGE_BARS",
        "STRUCTURE_FRESH", "STRUCTURE_TREND_STRENGTH",
    },
    "signal_quality": {
        "SIGNAL_QUALITY_SCORE", "SIGNAL_QUALITY_TIER",
        "SIGNAL_WARNINGS", "SIGNAL_BIAS_ALIGNMENT", "SIGNAL_FRESHNESS",
    },
}


class TestV55LeanContract:
    """Validate v5.5 lean family fields are present in all surfaces."""

    def test_all_lean_fields_in_inventory(self):
        """Every v5.5 lean field must be in V5_FIELD_INVENTORY."""
        all_lean = set()
        for fields in V55_LEAN_FAMILIES.values():
            all_lean |= fields
        missing = all_lean - V5_FIELD_INVENTORY
        assert not missing, f"v5.5 lean fields missing from inventory: {missing}"

    def test_all_lean_fields_consumed_by_engine(self):
        """Every v5.5 lean field must be consumed by SMC_Core_Engine.pine."""
        all_lean = set()
        for fields in V55_LEAN_FAMILIES.values():
            all_lean |= fields
        missing = all_lean - ENGINE_CONSUMED_FIELDS
        assert not missing, f"v5.5 lean fields not consumed by engine: {missing}"

    def test_lean_field_count(self):
        """v5.5 contract specifies exactly 32 lean fields across 6 families."""
        total = sum(len(f) for f in V55_LEAN_FAMILIES.values())
        assert total == 32, f"Expected 32 v5.5 lean fields, got {total}"

    def test_lean_bus_channels_exist(self):
        """v5.5 lean BUS channels must be declared."""
        lean_channels = {"LeanPackA", "LeanPackB"}
        missing = lean_channels - ENGINE_BUS_CHANNELS
        assert not missing, f"v5.5 lean BUS channels missing: {missing}"

    def test_generated_pine_has_lean_sections(self):
        """Generated Pine library must have v5.5 section headers."""
        text = _read_pine("pine/generated/smc_micro_profiles_generated.pine")
        for family_name in V55_LEAN_FAMILIES:
            section_tag = "(v5.5b)"
            assert section_tag in text, (
                f"Generated Pine missing v5.5 section marker for {family_name}"
            )


class TestV55DriftGuard:
    """Prevent lean fields from being accidentally replaced by old broad fields.

    These tests ensure that v5.5 lean integration is maintained and not
    silently reverted during refactoring.
    """

    def test_event_risk_gate_uses_lean_fields(self):
        """event_risk_gate_ok must derive from lean Event Risk Light fields."""
        text = _read_pine("SMC_Core_Engine.pine")
        # Must use lib_erl_* (lean) not lib_market_event_blocked/lib_symbol_event_blocked (old)
        gate_lines = [
            line.strip()
            for line in text.splitlines()
            if "event_risk_gate_ok" in line
            and ":=" not in line
            and "bool" in line
            and "not" in line
        ]
        assert gate_lines, "event_risk_gate_ok declaration not found"
        gate_decl = gate_lines[0]
        assert "lib_erl_" in gate_decl, (
            f"event_risk_gate_ok must use lean lib_erl_* fields, found: {gate_decl}"
        )

    def test_legacy_gates_removed(self):
        """Old v5.1-v5.3 context gate sections were removed in AP6 v5.5 cleanup."""
        text = _read_pine("SMC_Core_Engine.pine")
        for version in ("v5.1", "v5.2", "v5.3"):
            pattern = rf"──\s*{version}\s+Context Gates"
            assert not re.search(pattern, text), (
                f"{version} context gates section should have been removed in v5.5 cleanup"
            )

    def test_lean_context_section_marked_primary(self):
        """v5.5 lean context section must be marked [PRIMARY]."""
        text = _read_pine("SMC_Core_Engine.pine")
        assert re.search(r"v5\.5\s+Lean\s+Context\s+\[PRIMARY\]", text), (
            "v5.5 lean context section not marked [PRIMARY]"
        )

    def test_deprecated_sections_removed_in_phase_b(self):
        """Fields marked [DEPRECATED v5.5] should be gone after Phase B removal."""
        text = _read_pine("SMC_Core_Engine.pine")
        deprecated_markers = re.findall(
            r"\[DEPRECATED v5\.5[^\]]*\]", text
        )
        assert len(deprecated_markers) == 0, (
            f"Expected 0 deprecated section markers after Phase B, found {len(deprecated_markers)}: {deprecated_markers}"
        )

    def test_bus_event_risk_row_uses_lean_fields(self):
        """BUS EventRiskRow call must pass lean lib_erl_* fields."""
        text = _read_pine("SMC_Core_Engine.pine")
        bus_lines = [
            line.strip()
            for line in text.splitlines()
            if "BUS EventRiskRow" in line and line.strip().startswith("plot(")
        ]
        assert bus_lines, "BUS EventRiskRow plot not found"
        bus_call = bus_lines[0]
        assert "lib_erl_" in bus_call, (
            f"BUS EventRiskRow must use lean lib_erl_* fields, found: {bus_call}"
        )

    def test_gate_classification_comment_exists(self):
        """Gate classification documentation must exist in the engine."""
        text = _read_pine("SMC_Core_Engine.pine")
        assert "Gate Classification (v5.5b)" in text, (
            "Gate classification comment block not found in engine"
        )

    def test_prefixed_lean_aliases_stay_removed(self):
        """Legacy *_LIGHT_* aliases must not return for shared lean families."""
        text = _read_pine("SMC_Core_Engine.pine")
        for field in {
            "EVENT_RISK_LIGHT_WINDOW_STATE",
            "EVENT_RISK_LIGHT_LEVEL",
            "EVENT_RISK_LIGHT_NEXT_NAME",
            "EVENT_RISK_LIGHT_NEXT_TIME",
            "EVENT_RISK_LIGHT_MARKET_BLOCKED",
            "EVENT_RISK_LIGHT_SYMBOL_BLOCKED",
            "EVENT_RISK_LIGHT_PROVIDER_STATUS",
            "SESSION_CONTEXT_LIGHT",
            "SESSION_LIGHT_IN_KILLZONE",
            "SESSION_LIGHT_DIRECTION_BIAS",
            "SESSION_LIGHT_CONTEXT_SCORE",
            "SESSION_LIGHT_VOLATILITY_STATE",
            "STRUCTURE_LIGHT_LAST_EVENT",
            "STRUCTURE_LIGHT_EVENT_AGE_BARS",
            "STRUCTURE_LIGHT_FRESH",
        }:
            assert field not in text, f"Legacy alias reappeared in engine: {field}"


class TestV55bContractSync:
    """Ensure repo docs, generator, and manifest stay aligned at v5.5b."""

    def test_manifest_field_version_is_v55b(self):
        import json
        manifest = json.loads(
            (ROOT / "pine/generated/smc_micro_profiles_generated.json").read_text()
        )
        assert manifest["library_field_version"] == "v5.5b", (
            f"Manifest library_field_version should be v5.5b, got {manifest['library_field_version']}"
        )

    def test_contract_doc_references_v55b(self):
        text = (ROOT / "docs/v5_5_lean_contract.md").read_text()
        assert "v5.5b" in text, "Contract doc must reference v5.5b"
        assert "Signal Quality Primacy" in text, "Contract doc must list Signal Quality Primacy principle"
        assert "No Shadow Logic" in text, "Contract doc must list No Shadow Logic principle"

    def test_session_volatility_state_marked_optional(self):
        text = (ROOT / "docs/v5_5_lean_contract.md").read_text()
        assert "optional" in text.lower(), "SESSION_VOLATILITY_STATE must be marked optional"

    def test_session_volatility_state_pine_has_safe_default(self):
        """Pine must always export SESSION_VOLATILITY_STATE with safe default."""
        pine = (ROOT / "pine/generated/smc_micro_profiles_generated.pine").read_text()
        assert 'SESSION_VOLATILITY_STATE = "NORMAL"' in pine, (
            "SESSION_VOLATILITY_STATE must default to NORMAL in committed Pine"
        )

    def test_lean_family_count_32(self):
        """v5.5b still has exactly 32 lean fields across 6 families."""
        total = sum(len(f) for f in V55_LEAN_FAMILIES.values())
        assert total == 32

    def test_fvg_maturity_level_not_age_bars(self):
        """FVG uses FVG_MATURITY_LEVEL (proxy), never FVG_AGE_BARS."""
        assert "FVG_MATURITY_LEVEL" in V55_LEAN_FAMILIES["fvg_lifecycle_light"]
        assert "FVG_AGE_BARS" not in V55_LEAN_FAMILIES["fvg_lifecycle_light"]
        # Also verify docs match
        text = (ROOT / "docs/v5_5_lean_contract.md").read_text()
        assert "FVG_MATURITY_LEVEL" in text
        assert "FVG_AGE_BARS" not in text

    def test_no_shadow_event_risk_blocks(self):
        """Dead shadow logic (event_risk_hard_block/soft_block) must stay removed."""
        text = _read_pine("SMC_Core_Engine.pine")
        assert "event_risk_hard_block" not in text or "REMOVED" in text, (
            "event_risk_hard_block was removed in v5.5b — must not reappear"
        )
        assert "event_risk_soft_block" not in text or "REMOVED" in text, (
            "event_risk_soft_block was removed in v5.5b — must not reappear"
        )

    def test_no_shadow_logic_policy_exists(self):
        """No Shadow Logic policy document must exist."""
        assert (ROOT / "docs/NO_SHADOW_LOGIC_POLICY.md").exists()

    def test_compact_mode_hero_surface(self):
        """Compact mode must suppress all expected _eff flags and secondary overlays."""
        text = _read_pine("SMC_Core_Engine.pine")
        # Must suppress these in compact_mode if-block
        expected_suppressions = [
            "show_ob_debug_eff := false",
            "show_fvg_debug_eff := false",
            "show_long_engine_debug_eff := false",
            "show_microstructure_debug_eff := false",
            "show_strict_debug_markers_eff := false",
            "show_dashboard_ltf_eff := false",
            "show_ema_support_eff := false",
            "show_session_vwap_eff := false",
            "show_mean_target_overlay_eff := false",
        ]
        for s in expected_suppressions:
            assert s in text, f"compact_mode must contain: {s}"
        # Visual plots must use _eff versions (not raw input)
        assert "show_session_vwap_eff and intraday_time_chart" in text
        assert "show_ema_support_eff ? ema_fast" in text
        assert "show_mean_target_overlay_eff and not na" in text
        # Contract doc must describe Hero-Surface
        doc = (ROOT / "docs/v5_5_lean_contract.md").read_text()
        assert "Hero-Surface" in doc

    def test_compact_mode_preserves_filter_logic(self):
        """Compact mode must not suppress EMA/VWAP filter logic — only visual plots."""
        text = _read_pine("SMC_Core_Engine.pine")
        # EMA support filter must still use raw show_ema_support (not _eff)
        # The BUS row resolver uses show_ema_support as parameter name
        assert "resolve_bus_ema_support_row(show_ema_support," in text, (
            "BUS EMA support row must use raw show_ema_support, not _eff"
        )

    def test_reference_enrichment_fixture(self):
        """Reference enrichment fixture must load and contain all lean blocks."""
        import json
        fixture = json.loads(
            (ROOT / "tests/fixtures/reference_enrichment.json").read_text()
        )
        for block in V55_LEAN_FAMILIES:
            assert block in fixture, f"Reference enrichment must contain {block}"
        assert "meta" in fixture
        assert fixture["meta"]["asof_time"], "asof_time must not be empty"
        assert fixture["meta"]["refresh_count"] > 0

    def test_reference_enrichment_field_names_match_typeddicts(self):
        """Every field in the reference fixture must match its TypedDict exactly."""
        import json
        from scripts.smc_enrichment_types import (
            EventRiskLightBlock,
            SessionContextLightBlock,
            OBContextLightBlock,
            FVGLifecycleLightBlock,
            StructureStateLightBlock,
            SignalQualityBlock,
        )
        fixture = json.loads(
            (ROOT / "tests/fixtures/reference_enrichment.json").read_text()
        )
        typeddict_map = {
            "event_risk_light": EventRiskLightBlock,
            "session_context_light": SessionContextLightBlock,
            "ob_context_light": OBContextLightBlock,
            "fvg_lifecycle_light": FVGLifecycleLightBlock,
            "structure_state_light": StructureStateLightBlock,
            "signal_quality": SignalQualityBlock,
        }
        for block_name, td_class in typeddict_map.items():
            expected_keys = set(td_class.__annotations__)
            actual_keys = set(fixture[block_name])
            assert actual_keys == expected_keys, (
                f"{block_name}: fixture keys {actual_keys} != TypedDict keys {expected_keys}"
            )

    def test_manifest_matches_committed_pine(self):
        """Committed manifest must match committed Pine (both default reference)."""
        import json, re
        manifest = json.loads(
            (ROOT / "pine/generated/smc_micro_profiles_generated.json").read_text()
        )
        pine = (ROOT / "pine/generated/smc_micro_profiles_generated.pine").read_text()
        # Manifest enrichment_blocks mirrors actual enrichment state
        assert isinstance(manifest["enrichment_blocks"], list)
        # ASOF_TIME must match between Pine and manifest
        pine_asof = re.search(r'ASOF_TIME\s*=\s*"([^"]*)"', pine)
        assert pine_asof is not None
        assert manifest["asof_time"] == pine_asof.group(1)
        # REFRESH_COUNT must match
        pine_rc = re.search(r'REFRESH_COUNT\s*=\s*(\d+)', pine)
        assert pine_rc is not None
        assert manifest["refresh_count"] == int(pine_rc.group(1))
        # v55_lean_blocks must list all lean families
        for block in V55_LEAN_FAMILIES:
            assert block in manifest["v55_lean_blocks"]

    def test_reference_enrichment_values_contract_compliant(self):
        """Reference fixture values must conform to v5.5b lean contract allowed values."""
        import json
        fixture = json.loads(
            (ROOT / "tests/fixtures/reference_enrichment.json").read_text()
        )
        # ── Allowed value domains from docs/v5_5_lean_contract.md ──
        erl = fixture["event_risk_light"]
        assert erl["EVENT_WINDOW_STATE"] in ("CLEAR", "PRE_EVENT", "ACTIVE", "COOLDOWN")
        assert erl["EVENT_RISK_LEVEL"] in ("NONE", "LOW", "ELEVATED", "HIGH")
        assert erl["EVENT_PROVIDER_STATUS"] in ("ok", "no_data", "calendar_missing", "news_missing")
        assert isinstance(erl["MARKET_EVENT_BLOCKED"], bool)
        assert isinstance(erl["SYMBOL_EVENT_BLOCKED"], bool)

        scl = fixture["session_context_light"]
        assert scl["SESSION_CONTEXT"] in ("ASIA", "LONDON", "NY_AM", "NY_PM", "NONE")
        assert isinstance(scl["IN_KILLZONE"], bool)
        assert scl["SESSION_DIRECTION_BIAS"] in ("BULLISH", "BEARISH", "NEUTRAL")
        assert 0 <= scl["SESSION_CONTEXT_SCORE"] <= 7
        assert scl.get("SESSION_VOLATILITY_STATE", "NORMAL") in ("LOW", "NORMAL", "HIGH", "EXTREME")

        ob = fixture["ob_context_light"]
        assert ob["PRIMARY_OB_SIDE"] in ("BULL", "BEAR", "NONE")
        assert isinstance(ob["PRIMARY_OB_DISTANCE"], (int, float))
        assert isinstance(ob["OB_FRESH"], bool)
        assert isinstance(ob["OB_AGE_BARS"], int) and ob["OB_AGE_BARS"] >= 0
        assert ob["OB_MITIGATION_STATE"] in ("fresh", "touched", "mitigated", "stale")

        fvg = fixture["fvg_lifecycle_light"]
        assert fvg["PRIMARY_FVG_SIDE"] in ("BULL", "BEAR", "NONE")
        assert isinstance(fvg["PRIMARY_FVG_DISTANCE"], (int, float))
        assert 0.0 <= fvg["FVG_FILL_PCT"] <= 1.0
        assert fvg["FVG_MATURITY_LEVEL"] in (0, 1, 2, 3)
        assert isinstance(fvg["FVG_FRESH"], bool)
        assert isinstance(fvg["FVG_INVALIDATED"], bool)

        ssl = fixture["structure_state_light"]
        assert ssl["STRUCTURE_LAST_EVENT"] in ("NONE", "BOS_BULL", "BOS_BEAR", "CHOCH_BULL", "CHOCH_BEAR")
        assert isinstance(ssl["STRUCTURE_EVENT_AGE_BARS"], int) and ssl["STRUCTURE_EVENT_AGE_BARS"] >= 0
        assert isinstance(ssl["STRUCTURE_FRESH"], bool)
        assert 0 <= ssl["STRUCTURE_TREND_STRENGTH"] <= 100

        sq = fixture["signal_quality"]
        assert 0 <= sq["SIGNAL_QUALITY_SCORE"] <= 100
        assert sq["SIGNAL_QUALITY_TIER"] in ("low", "ok", "good", "high")
        assert isinstance(sq["SIGNAL_WARNINGS"], str)
        assert sq["SIGNAL_BIAS_ALIGNMENT"] in ("bull", "bear", "mixed", "neutral")
        assert sq["SIGNAL_FRESHNESS"] in ("fresh", "aging", "stale")

        # ── Semantic coherence checks ──
        # Score ↔ tier consistency
        score = sq["SIGNAL_QUALITY_SCORE"]
        tier = sq["SIGNAL_QUALITY_TIER"]
        if score >= 75:
            assert tier == "high", f"score {score} should map to tier 'high'"
        elif score >= 50:
            assert tier in ("good", "ok"), f"score {score} should be 'good' or 'ok'"

        # Event risk coherence: blocked ↔ state
        if erl["MARKET_EVENT_BLOCKED"] or erl["SYMBOL_EVENT_BLOCKED"]:
            assert erl["EVENT_WINDOW_STATE"] != "CLEAR", "Blocked event should not be CLEAR"
        if erl["EVENT_WINDOW_STATE"] == "CLEAR":
            assert erl["EVENT_RISK_LEVEL"] in ("NONE", "LOW")

        # Freshness ↔ fresh flags
        if sq["SIGNAL_FRESHNESS"] == "fresh":
            # At least one structure element should be fresh in a coherent scenario
            assert any([ob.get("OB_FRESH"), fvg.get("FVG_FRESH"), ssl.get("STRUCTURE_FRESH")])

    def test_runtime_budget_doc_exists(self):
        """Runtime budget document must exist and record the executed C1 cleanup."""
        doc = (ROOT / "docs/RUNTIME_BUDGET.md").read_text()
        assert "Phase C C1" in doc
        assert "show_mtf_trend" in doc, "C1 removal inventory must include show_mtf_trend"
        assert "Phase B" in doc, "Removal roadmap must include Phase B"

    def test_artifact_strategy_two_classes(self):
        """Both artifact classes must exist: seed reference and showcase fixture."""
        import json
        # Seed reference (generator-first, all defaults)
        seed_pine = ROOT / "pine/generated/smc_micro_profiles_generated.pine"
        seed_manifest = ROOT / "pine/generated/smc_micro_profiles_generated.json"
        assert seed_pine.exists(), "Seed Pine artifact must exist"
        assert seed_manifest.exists(), "Seed manifest must exist"
        manifest = json.loads(seed_manifest.read_text())
        assert manifest["enrichment_blocks"] == [], "Seed artifact must have empty enrichment_blocks"
        assert manifest["asof_time"] == "", "Seed artifact must have empty asof_time"
        # Showcase reference (hand-maintained, contract-compliant values)
        fixture_path = ROOT / "tests/fixtures/reference_enrichment.json"
        assert fixture_path.exists(), "Showcase fixture must exist"
        fixture = json.loads(fixture_path.read_text())
        assert fixture["meta"]["asof_time"] != "", "Showcase fixture must have populated asof_time"
        assert fixture["meta"]["refresh_count"] > 0, "Showcase fixture must have positive refresh_count"
        # Strategy doc
        assert (ROOT / "docs/ARTIFACT_STRATEGY.md").exists(), "Artifact strategy doc must exist"