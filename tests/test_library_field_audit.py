"""WP-A5 contract: every Pine mp.* reference maps to a generated library field."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_PINE_DIR = ROOT
_GENERATORS = [
    ROOT / "scripts" / "generate_smc_micro_profiles.py",
    ROOT / "scripts" / "smc_microstructure_base_runtime.py",
]

# Known orphan references that are tolerated until their Pine consumer is cleaned up.
_KNOWN_ORPHANS: set[str] = {
    # ── Deprecated v5-v5.3 fields removed in WP-LF5 ──
    # Still referenced by legacy overlay scripts (SMC_Event_Overlay, SMC_HTF_Confluence,
    # SMC_Imbalance_Context, SMC_Liquidity_Context, SMC_Liquidity_Structure,
    # SMC_Profile_Context, SMC_Session_Context, SMC_Structure_Context).
    "ACTIVE_RESISTANCE",
    "ACTIVE_RESISTANCE_COUNT",
    "ACTIVE_SUPPORT",
    "ACTIVE_SUPPORT_COUNT",
    "ACTIVE_ZONE_COUNT",
    "BEAR_FVG_ACTIVE",
    "BEAR_FVG_BOTTOM",
    "BEAR_FVG_COUNT",
    "BEAR_FVG_FULL_MITIGATION",
    "BEAR_FVG_MITIGATION_PCT",
    "BEAR_FVG_PARTIAL_MITIGATION",
    "BEAR_FVG_TOP",
    "BOS_BEAR",
    "BOS_BULL",
    "BPR_ACTIVE",
    "BPR_BOTTOM",
    "BPR_TOP",
    "BULL_FVG_ACTIVE",
    "BULL_FVG_BOTTOM",
    "BULL_FVG_COUNT",
    "BULL_FVG_FULL_MITIGATION",
    "BULL_FVG_MITIGATION_PCT",
    "BULL_FVG_PARTIAL_MITIGATION",
    "BULL_FVG_TOP",
    "CHOCH_BEAR",
    "CHOCH_BULL",
    "CONFIRM_SCORE",
    "FOLLOW_THROUGH_SCORE",
    "FVG_CONFIRM_OK",
    "HTF_BEARISH_DIVERGENCE",
    "HTF_BEARISH_PATTERN",
    "HTF_BULLISH_DIVERGENCE",
    "HTF_BULLISH_PATTERN",
    "HTF_STRUCTURE_OK",
    "IMBALANCE_STATE",
    "LIQ_VOID_BEAR_ACTIVE",
    "LIQ_VOID_BOTTOM",
    "LIQ_VOID_BULL_ACTIVE",
    "LIQ_VOID_TOP",
    "POOL_IMBALANCE",
    "POOL_MAGNET_DIRECTION",
    "POOL_QUALITY_SCORE",
    "PRIMARY_RESISTANCE_LEVEL",
    "PRIMARY_RESISTANCE_STRENGTH",
    "PRIMARY_SUPPORT_LEVEL",
    "PRIMARY_SUPPORT_STRENGTH",
    "PROFILE_AH_QUALITY",
    "PROFILE_AVG_SPREAD_BPS",
    "PROFILE_CLEAN_SCORE",
    "PROFILE_CONTEXT_SCORE",
    "PROFILE_MIDDAY_EFFICIENCY",
    "PROFILE_PM_QUALITY",
    "PROFILE_RTH_DOMINANCE_PCT",
    "PROFILE_SESSION_BIAS",
    "PROFILE_SPREAD_REGIME",
    "PROFILE_TICKER_GRADE",
    "PROFILE_VWAP_DISTANCE_PCT",
    "PROFILE_VWAP_POSITION",
    "PROFILE_WICKINESS",
    "RECENT_BEAR_SWEEP",
    "RECENT_BULL_SWEEP",
    "RESISTANCE_ACTIVE",
    "RESISTANCE_MITIGATION_PCT",
    "RESISTANCE_SWEEP_COUNT",
    "RETRACE_OK",
    "REVERSAL_CONTEXT_ACTIVE",
    "SESSION_MSS_BEAR",
    "SESSION_MSS_BULL",
    "SETUP_SCORE",
    "STRUCTURE_BEAR_ACTIVE",
    "STRUCTURE_BULL_ACTIVE",
    "STRUCTURE_STATE",
    "SUPPORT_ACTIVE",
    "SUPPORT_MITIGATION_PCT",
    "SUPPORT_SWEEP_COUNT",
    "SWEEP_QUALITY_SCORE",
    "SWEEP_RECLAIM_ACTIVE",
    "SWEEP_TYPE",
    "VWAP_HOLD_OK",
    "ZONE_CONTEXT_BIAS",
    "ZONE_LIQUIDITY_IMBALANCE",
}


def _collect_generated_fields() -> set[str]:
    """Parse all generators for 'export const' field names and render_csv_export calls."""
    from scripts.generate_smc_micro_profiles import LIST_EXPORTS

    fields: set[str] = set()
    for gen in _GENERATORS:
        source = gen.read_text(encoding="utf-8")
        # Direct: export const float FIELD_NAME
        fields.update(re.findall(r"export const (?:float|int|bool|string) (\w+)", source))
        # render_csv_export("FIELD_NAME", ...)
        fields.update(re.findall(r'render_csv_export\(\s*"([A-Z_][A-Z0-9_]+)"', source))
        # f-string: f'export const {type} {FIELD_NAME}' — with literal field name in f-string
        fields.update(re.findall(r"export const (?:float|int|bool|string) ([A-Z_][A-Z0-9_]+)", source))
        # f-string with loop variable, e.g. ZONE_CAL_{fam}: expand known patterns
        for m in re.finditer(r'f"export const (?:float|int|bool|string) ([A-Z_][A-Z0-9_]*?)\{(\w+)\}', source):
            prefix = m.group(1)
            var_name = m.group(2)
            # Resolve known loop variables
            if var_name == "fam":
                for fam in ("OB", "FVG", "BOS", "SWEEP"):
                    fields.add(f"{prefix}{fam}")
        # f-string with two loop variables, e.g. ZONE_CAL_{fam}_{session}: expand cartesian
        for m in re.finditer(
            r'f"export const (?:float|int|bool|string) ([A-Z_][A-Z0-9_]*?)\{(\w+)\}_\{(\w+)\}',
            source,
        ):
            prefix = m.group(1)
            var1 = m.group(2)
            var2 = m.group(3)
            _LOOP_VARS: dict[str, tuple[str, ...]] = {
                "fam": ("OB", "FVG", "BOS", "SWEEP"),
                "session": ("RTH", "ETH"),
                "vol": ("NORMAL", "HIGH_VOL"),
            }
            for v1 in _LOOP_VARS.get(var1, ()):
                for v2 in _LOOP_VARS.get(var2, ()):
                    fields.add(f"{prefix}{v1}_{v2}")
    # Remove partial f-string captures (e.g. 'ZONE_CAL_' without suffix)
    fields = {f for f in fields if not f.endswith("_") or f in _INFRA_ONLY}
    # Dynamic list exports (render_list calls)
    fields.update(LIST_EXPORTS.values())
    return fields


def _collect_pine_mp_refs() -> dict[str, set[str]]:
    """Return {pine_file: {field_names}} for all mp.FIELD references."""
    result: dict[str, set[str]] = {}
    for pine in sorted(_PINE_DIR.glob("*.pine")):
        source = pine.read_text(encoding="utf-8")
        refs = set(re.findall(r"\bmp\.([A-Z_][A-Z0-9_]+)", source))
        if refs:
            result[pine.name] = refs
    return result


def test_all_pine_mp_refs_resolve_to_generated_fields() -> None:
    generated = _collect_generated_fields()
    pine_refs = _collect_pine_mp_refs()

    orphans: list[str] = []
    for fname, refs in sorted(pine_refs.items()):
        for ref in sorted(refs):
            if ref not in generated and ref not in _KNOWN_ORPHANS:
                orphans.append(f"  {fname} -> mp.{ref}")

    assert orphans == [], (
        f"Pine mp.* references to non-existent library fields:\n"
        + "\n".join(orphans)
    )


def test_known_orphans_are_still_orphans() -> None:
    """Prevent _KNOWN_ORPHANS from going stale — remove entries once the field is generated."""
    generated = _collect_generated_fields()
    for orphan in _KNOWN_ORPHANS:
        assert orphan not in generated, (
            f"{orphan} is now generated — remove it from _KNOWN_ORPHANS"
        )


def test_field_count_is_within_audit_bounds() -> None:
    """Total generated fields should be documented in the audit."""
    generated = _collect_generated_fields()
    assert len(generated) >= 120, f"Field count dropped unexpectedly: {len(generated)}"
    assert len(generated) <= 320, f"Field count grew unexpectedly: {len(generated)}"


# ── WP-A6: Compatibility Fields Sunset ──────────────────────────


def test_deprecated_field_policy_has_sunset_date() -> None:
    """DEPRECATED_FIELD_POLICY must include a sunset_date (WP-A6)."""
    from scripts.smc_bus_manifest import DEPRECATED_FIELD_POLICY

    assert "sunset_date" in DEPRECATED_FIELD_POLICY
    sunset = DEPRECATED_FIELD_POLICY["sunset_date"]
    assert isinstance(sunset, str) and len(sunset) == 10, f"Invalid sunset_date: {sunset}"
    from datetime import date as _date
    _date.fromisoformat(sunset)  # must parse


def test_deprecated_field_policy_has_sunset_action() -> None:
    from scripts.smc_bus_manifest import DEPRECATED_FIELD_POLICY

    assert DEPRECATED_FIELD_POLICY.get("sunset_action") == "removed"


def test_generator_sunset_warning_removed() -> None:
    """The sunset warning block was removed after deprecation completed (2026-04-14).

    DEPRECATED_FIELD_POLICY still exists in the manifest for contract verification,
    but the generator no longer logs sunset warnings since all deprecated groups
    have been removed.
    """
    from scripts.smc_bus_manifest import DEPRECATED_FIELD_POLICY

    assert DEPRECATED_FIELD_POLICY.get("sunset_date") == "2026-04-14"
    assert DEPRECATED_FIELD_POLICY.get("deprecatedGroups") == []


# ── OV6: Reverse-direction audit (generated → consumer) ─────────


# Fields intentionally generated without a Pine consumer today.
# Infra/metadata fields are internal; enrichment-reserve fields are exported for
# future Pine consumers or external tooling (Streamlit terminal, notebooks).
_INFRA_ONLY: set[str] = {
    # ── metadata / bookkeeping ──
    "ASOF_TIME",
    "UNIVERSE_SIZE",
    "UNIVERSE_ID",
    "REFRESH_COUNT",
    "LOOKBACK_DAYS",
    # ── enrichment reserve: consumed by Python backend / Streamlit only ──
    "BPR_DIRECTION",
    "BUY_SIDE_POOL_LEVEL",
    "BUY_SIDE_POOL_STRENGTH",
    "EARNINGS_AMC_TICKERS",
    "EARNINGS_BMO_TICKERS",
    "ENSEMBLE_AVAILABLE_COMPONENTS",
    "HIGH_RISK_EVENT_TICKERS",
    "HOLIDAY_SUSPECT_TICKERS",
    "LIQUIDITY_TAKEN_DIRECTION",
    "MACRO_BIAS",
    "NEWS_HEAT_GLOBAL",
    "NEWS_NEUTRAL_TICKERS",
    "NEXT_EVENT_CLASS",
    "VOLATILITY_ATR_RATIO",
    "VOLATILITY_FALLBACK_REASON",
    "VOLATILITY_PROXY_SOURCE",
    "VOLATILITY_PROXY_SYMBOL",
    "VOLATILITY_REGIME_CONFIDENCE",
    # ── zone priority calibration weights (Python-side only) ──
    "ZONE_CAL_OB",
    "ZONE_CAL_FVG",
    "ZONE_CAL_BOS",
    "ZONE_CAL_SWEEP",
    # ── Phase F: contextual calibration weights ──
    "ZONE_CAL_OB_RTH",
    "ZONE_CAL_FVG_RTH",
    "ZONE_CAL_BOS_RTH",
    "ZONE_CAL_SWEEP_RTH",
    "ZONE_CAL_OB_ETH",
    "ZONE_CAL_FVG_ETH",
    "ZONE_CAL_BOS_ETH",
    "ZONE_CAL_SWEEP_ETH",
    "ZONE_CAL_OB_NORMAL",
    "ZONE_CAL_FVG_NORMAL",
    "ZONE_CAL_BOS_NORMAL",
    "ZONE_CAL_SWEEP_NORMAL",
    "ZONE_CAL_OB_HIGH_VOL",
    "ZONE_CAL_FVG_HIGH_VOL",
    "ZONE_CAL_BOS_HIGH_VOL",
    "ZONE_CAL_SWEEP_HIGH_VOL",
    # ── Hero State: Pine consumer arrives in PR 2 (Dashboard Hero Surface) ──
    "HERO_MARKET_MODE",
    "HERO_BIAS",
    "HERO_TRUST",
    "HERO_SETUP_QUALITY",
    "HERO_WHY_NOW",
    "HERO_RISK",
    "HERO_ACTION",
}


def test_every_generated_field_has_pine_consumer() -> None:
    """Every generated field must be consumed by at least one Pine script or be in _INFRA_ONLY."""
    generated = _collect_generated_fields()
    pine_refs = _collect_pine_mp_refs()

    all_consumed: set[str] = set()
    for refs in pine_refs.values():
        all_consumed.update(refs)

    unclaimed = sorted(generated - all_consumed - _INFRA_ONLY)
    assert unclaimed == [], (
        f"Generated fields with no Pine consumer (add mp.* usage or mark _INFRA_ONLY):\n"
        + "\n".join(f"  {f}" for f in unclaimed)
    )


def test_infra_only_fields_are_generated() -> None:
    """Prevent _INFRA_ONLY from going stale — every entry must still be generated."""
    generated = _collect_generated_fields()
    for field in _INFRA_ONLY:
        assert field in generated, (
            f"{field} is in _INFRA_ONLY but no longer generated — remove it"
        )
