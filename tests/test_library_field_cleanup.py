"""WP-LF5 contract: deprecated compatibility fields removed, consumed fields preserved."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_GENERATOR = ROOT / "scripts" / "generate_smc_micro_profiles.py"

# Fields that were removed in WP-LF5 (deprecated, no consumer in SMC_Core_Engine.pine).
DELETED_FIELDS: set[str] = {
    # Event Risk (only 2 removed)
    "NEXT_EVENT_CLASS",
    "HIGH_RISK_EVENT_TICKERS",
    # Zone Intelligence (v5.1) — all 13
    "ACTIVE_SUPPORT_COUNT",
    "ACTIVE_RESISTANCE_COUNT",
    "ACTIVE_ZONE_COUNT",
    "PRIMARY_SUPPORT_LEVEL",
    "PRIMARY_RESISTANCE_LEVEL",
    "PRIMARY_SUPPORT_STRENGTH",
    "PRIMARY_RESISTANCE_STRENGTH",
    "SUPPORT_SWEEP_COUNT",
    "RESISTANCE_SWEEP_COUNT",
    "SUPPORT_MITIGATION_PCT",
    "RESISTANCE_MITIGATION_PCT",
    "ZONE_CONTEXT_BIAS",
    "ZONE_LIQUIDITY_IMBALANCE",
    # Reversal Context (v5.1) — all 12
    "REVERSAL_CONTEXT_ACTIVE",
    "SETUP_SCORE",
    "CONFIRM_SCORE",
    "FOLLOW_THROUGH_SCORE",
    "HTF_STRUCTURE_OK",
    "HTF_BULLISH_PATTERN",
    "HTF_BEARISH_PATTERN",
    "HTF_BULLISH_DIVERGENCE",
    "HTF_BEARISH_DIVERGENCE",
    "FVG_CONFIRM_OK",
    "VWAP_HOLD_OK",
    "RETRACE_OK",
    # Session Context (v5.2) — 12 non-consumed
    "SESSION_MSS_BULL",
    "SESSION_MSS_BEAR",
    "SESSION_STRUCTURE_STATE",
    "SESSION_FVG_BULL_ACTIVE",
    "SESSION_FVG_BEAR_ACTIVE",
    "SESSION_BPR_ACTIVE",
    "SESSION_RANGE_TOP",
    "SESSION_RANGE_BOTTOM",
    "SESSION_MEAN",
    "SESSION_VWAP",
    "SESSION_TARGET_BULL",
    "SESSION_TARGET_BEAR",
    # Liquidity Sweeps (v5.2) — all 9
    "RECENT_BULL_SWEEP",
    "RECENT_BEAR_SWEEP",
    "SWEEP_TYPE",
    "SWEEP_DIRECTION",
    "SWEEP_ZONE_TOP",
    "SWEEP_ZONE_BOTTOM",
    "SWEEP_RECLAIM_ACTIVE",
    "LIQUIDITY_TAKEN_DIRECTION",
    "SWEEP_QUALITY_SCORE",
    # Liquidity Pools (v5.2) — all 11
    "BUY_SIDE_POOL_LEVEL",
    "SELL_SIDE_POOL_LEVEL",
    "BUY_SIDE_POOL_STRENGTH",
    "SELL_SIDE_POOL_STRENGTH",
    "POOL_PROXIMITY_PCT",
    "POOL_CLUSTER_DENSITY",
    "UNTESTED_BUY_POOLS",
    "UNTESTED_SELL_POOLS",
    "POOL_IMBALANCE",
    "POOL_MAGNET_DIRECTION",
    "POOL_QUALITY_SCORE",
    # Order Blocks (v5.2) — all 13
    "NEAREST_BULL_OB_LEVEL",
    "NEAREST_BEAR_OB_LEVEL",
    "BULL_OB_FRESHNESS",
    "BEAR_OB_FRESHNESS",
    "BULL_OB_MITIGATED",
    "BEAR_OB_MITIGATED",
    "BULL_OB_FVG_CONFLUENCE",
    "BEAR_OB_FVG_CONFLUENCE",
    "OB_DENSITY",
    "OB_BIAS",
    "OB_NEAREST_DISTANCE_PCT",
    "OB_STRENGTH_SCORE",
    "OB_CONTEXT_SCORE",
    # Zone Projection (v5.2) — all 10
    "ZONE_PROJ_TARGET_BULL",
    "ZONE_PROJ_TARGET_BEAR",
    "ZONE_PROJ_RETEST_EXPECTED",
    "ZONE_PROJ_TRAP_RISK",
    "ZONE_PROJ_SPREAD_QUALITY",
    "ZONE_PROJ_HTF_ALIGNED",
    "ZONE_PROJ_BIAS",
    "ZONE_PROJ_CONFIDENCE",
    "ZONE_PROJ_DECAY_BARS",
    "ZONE_PROJ_SCORE",
    # Profile Context (v5.2) — all 18
    "PROFILE_VOLUME_NODE",
    "PROFILE_VWAP_POSITION",
    "PROFILE_VWAP_DISTANCE_PCT",
    "PROFILE_SPREAD_REGIME",
    "PROFILE_AVG_SPREAD_BPS",
    "PROFILE_SESSION_BIAS",
    "PROFILE_RTH_DOMINANCE_PCT",
    "PROFILE_PM_QUALITY",
    "PROFILE_AH_QUALITY",
    "PROFILE_MIDDAY_EFFICIENCY",
    "PROFILE_DECAY_HALFLIFE",
    "PROFILE_CONSISTENCY",
    "PROFILE_WICKINESS",
    "PROFILE_CLEAN_SCORE",
    "PROFILE_RECLAIM_RATE",
    "PROFILE_STOP_HUNT_RATE",
    "PROFILE_TICKER_GRADE",
    "PROFILE_CONTEXT_SCORE",
    # Structure State (v5.3) — 11 non-consumed
    "STRUCTURE_STATE",
    "STRUCTURE_BULL_ACTIVE",
    "STRUCTURE_BEAR_ACTIVE",
    "CHOCH_BULL",
    "CHOCH_BEAR",
    "BOS_BULL",
    "BOS_BEAR",
    "ACTIVE_SUPPORT",
    "ACTIVE_RESISTANCE",
    "SUPPORT_ACTIVE",
    "RESISTANCE_ACTIVE",
    # Imbalance Lifecycle (v5.3) — all 23
    "BULL_FVG_ACTIVE",
    "BEAR_FVG_ACTIVE",
    "BULL_FVG_TOP",
    "BULL_FVG_BOTTOM",
    "BEAR_FVG_TOP",
    "BEAR_FVG_BOTTOM",
    "BULL_FVG_PARTIAL_MITIGATION",
    "BEAR_FVG_PARTIAL_MITIGATION",
    "BULL_FVG_FULL_MITIGATION",
    "BEAR_FVG_FULL_MITIGATION",
    "BULL_FVG_COUNT",
    "BEAR_FVG_COUNT",
    "BULL_FVG_MITIGATION_PCT",
    "BEAR_FVG_MITIGATION_PCT",
    "BPR_ACTIVE",
    "BPR_DIRECTION",
    "BPR_TOP",
    "BPR_BOTTOM",
    "LIQ_VOID_BULL_ACTIVE",
    "LIQ_VOID_BEAR_ACTIVE",
    "LIQ_VOID_TOP",
    "LIQ_VOID_BOTTOM",
    "IMBALANCE_STATE",
    # Session Structure (v5.3) — all 14
    "SESS_HIGH",
    "SESS_LOW",
    "SESS_OPEN_RANGE_HIGH",
    "SESS_OPEN_RANGE_LOW",
    "SESS_OPEN_RANGE_BREAK",
    "SESS_IMPULSE_DIR",
    "SESS_IMPULSE_STRENGTH",
    "SESS_INTRA_BOS_COUNT",
    "SESS_INTRA_CHOCH",
    "SESS_PDH",
    "SESS_PDL",
    "SESS_PDH_SWEPT",
    "SESS_PDL_SWEPT",
    "SESS_STRUCT_SCORE",
}

# Consumed fields that MUST remain in the library.
CONSUMED_FIELDS: set[str] = {
    # Event Risk (kept)
    "EVENT_WINDOW_STATE",
    "EVENT_RISK_LEVEL",
    "NEXT_EVENT_NAME",
    "NEXT_EVENT_TIME",
    "NEXT_EVENT_IMPACT",
    "EVENT_RESTRICT_BEFORE_MIN",
    "EVENT_RESTRICT_AFTER_MIN",
    "EVENT_COOLDOWN_ACTIVE",
    "MARKET_EVENT_BLOCKED",
    "SYMBOL_EVENT_BLOCKED",
    "EARNINGS_SOON_TICKERS",
    "EVENT_PROVIDER_STATUS",
    # Session Context Light
    "SESSION_CONTEXT",
    "IN_KILLZONE",
    "SESSION_DIRECTION_BIAS",
    "SESSION_CONTEXT_SCORE",
    "SESSION_VOLATILITY_STATE",
    # OB Context Light
    "PRIMARY_OB_SIDE",
    "PRIMARY_OB_DISTANCE",
    "OB_FRESH",
    "OB_AGE_BARS",
    "OB_MITIGATION_STATE",
    # FVG Lifecycle Light
    "PRIMARY_FVG_SIDE",
    "PRIMARY_FVG_DISTANCE",
    "FVG_FILL_PCT",
    "FVG_MATURITY_LEVEL",
    "FVG_FRESH",
    "FVG_INVALIDATED",
    # Structure State Light
    "STRUCTURE_LAST_EVENT",
    "STRUCTURE_EVENT_AGE_BARS",
    "STRUCTURE_FRESH",
    "STRUCTURE_TREND_STRENGTH",
}


def _parse_generator_fields() -> set[str]:
    """Extract field names from export const declarations in the generator source."""
    source = _GENERATOR.read_text(encoding="utf-8")
    return set(re.findall(r"export const (?:float|int|bool|string) ([A-Z_][A-Z0-9_]+)", source))


def test_no_deprecated_compatibility_fields() -> None:
    """None of the deleted deprecated fields appear in the generator."""
    generated = _parse_generator_fields()
    still_present = DELETED_FIELDS & generated
    assert still_present == set(), (
        f"Deprecated fields still in generator: {sorted(still_present)}"
    )


def test_consumed_fields_still_present() -> None:
    """All Pine-consumed fields remain in the generator."""
    generated = _parse_generator_fields()
    missing = CONSUMED_FIELDS - generated
    assert missing == set(), (
        f"Consumed fields missing from generator: {sorted(missing)}"
    )


def test_field_count_reduced() -> None:
    """Library has fewer than 200 export const fields after cleanup."""
    generated = _parse_generator_fields()
    assert len(generated) < 200, (
        f"Expected < 200 fields after cleanup, got {len(generated)}"
    )
