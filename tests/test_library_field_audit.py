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
    # ENG-WS2-02 / -04 trust + action degradation block helpers.
    ROOT / "scripts" / "smc_trust_state_export.py",
    # ENG-WS3-03 / -04 / -05 hero-surface block helpers.
    ROOT / "scripts" / "smc_hero_market_mode.py",
    ROOT / "scripts" / "smc_hero_setup_quality.py",
    ROOT / "scripts" / "smc_hero_action.py",
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
                # Q3 F1 wiring: session taxonomy is ASIA/LONDON/NY_AM
                # (mirrors scripts/smc_zone_priority_calibration.py).
                "session": ("ASIA", "LONDON", "NY_AM"),
                "vol": ("NORMAL", "HIGH_VOL"),
            }
            for v1 in _LOOP_VARS.get(var1, ()):
                for v2 in _LOOP_VARS.get(var2, ()):
                    fields.add(f"{prefix}{v1}_{v2}")
    # Remove partial f-string captures (e.g. 'ZONE_CAL_' without suffix)
    fields = {f for f in fields if not f.endswith("_") or f in _INFRA_ONLY}
    # Dynamic list exports (render_list calls)
    fields.update(LIST_EXPORTS.values())
    # Explicit Pine field tuples published by the helper modules. The
    # regex-based scan above can miss exports rendered through a loop
    # over an external tuple, so we always trust the tuple as the
    # authoritative field list for that block.
    from scripts.smc_hero_action import PINE_HERO_ACTION_FIELDS
    from scripts.smc_hero_market_mode import PINE_HERO_MARKET_FIELDS
    from scripts.smc_hero_setup_quality import PINE_HERO_QUALITY_FIELDS
    from scripts.smc_trust_state_export import (
        PINE_ACTION_DEGRADATION_FIELDS,
        PINE_TRUST_FIELDS,
    )

    # ZONE_HR_<FAM> per-family hit-rate exports are emitted by
    # generate_smc_micro_profiles.py via a two-stage f-string
    # indirection (``key = f"ZONE_HR_{fam}"``) that the regex above
    # cannot resolve. Pin to the canonical DEFAULTS dict in
    # smc_zone_priority_consumer (see ADR 2026-04-22).
    from scripts.smc_zone_priority_consumer import DEFAULTS as _ZH_DEFAULTS

    fields.update(PINE_TRUST_FIELDS)
    fields.update(PINE_ACTION_DEGRADATION_FIELDS)
    fields.update(PINE_HERO_MARKET_FIELDS)
    fields.update(PINE_HERO_QUALITY_FIELDS)
    fields.update(PINE_HERO_ACTION_FIELDS)
    fields.update(_ZH_DEFAULTS.keys())
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
        "Pine mp.* references to non-existent library fields:\n"
        + "\n".join(orphans)
    )


@pytest.mark.parametrize("family", ["OB", "FVG", "BOS", "SWEEP"])
def test_zone_hr_family_export_is_audit_visible(family: str) -> None:
    """Regression pin (ADR 2026-04-22): every ZONE_HR_<FAM> export must be
    discoverable by the orphan audit, even though the generator emits them
    through a two-stage f-string indirection that the regex scan cannot
    resolve. Wired via the canonical DEFAULTS import in
    :func:`_collect_generated_fields`.
    """
    from scripts.smc_zone_priority_consumer import FAMILIES

    assert family in FAMILIES, (
        f"Test fixture drift: {family!r} not in canonical FAMILIES tuple "
        f"({FAMILIES!r}). Update both together."
    )
    generated = _collect_generated_fields()
    field = f"ZONE_HR_{family}"
    assert field in generated, (
        f"Canonical export {field!r} is invisible to the orphan audit. "
        f"Check scripts/smc_zone_priority_consumer.DEFAULTS and the\n"
        f"DEFAULTS import in tests/test_library_field_audit.py."
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


# Generated fields are categorised by *intended consumer* so the audit
# can distinguish technical infra from a Pine-surface contract that is
# advertised but not yet wired.
#
# Three categories, mutually exclusive:
#
# - PYTHON_ONLY_EXPORTS:   diagnostic / Python-side helpers; Pine MUST
#   NOT depend on these. They show up in the library because the
#   generator emits them (telemetry, calibration weights, ticker
#   lists), but the Pine surface uses a rolled-up sibling instead.
#
# - RESERVED_PINE_EXPORTS: an explicit Pine-surface contract that is
#   already exported by the generator, but no Pine consumer reads it
#   yet. Tracked here on purpose so the debt is visible. New entries
#   MUST point at a backlog ticket so we don't accumulate silent
#   reservations.
#
# - everything else: must be referenced by at least one *.pine file.
PYTHON_ONLY_EXPORTS: set[str] = {
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
    # Session keys mirror the upstream taxonomy from
    # scripts/smc_zone_priority_calibration.py (ASIA/LONDON/NY_AM).
    # Q3 F1 wiring (2026-04-22) replaced the legacy RTH/ETH stubs that
    # never matched any bucket — see docs/STRATEGY_2026_Q3.md §F1 and
    # docs/FVG_LABEL_AUDIT_Q3.md §2.
    "ZONE_CAL_OB_ASIA",
    "ZONE_CAL_FVG_ASIA",
    "ZONE_CAL_BOS_ASIA",
    "ZONE_CAL_SWEEP_ASIA",
    "ZONE_CAL_OB_LONDON",
    "ZONE_CAL_FVG_LONDON",
    "ZONE_CAL_BOS_LONDON",
    "ZONE_CAL_SWEEP_LONDON",
    "ZONE_CAL_OB_NY_AM",
    "ZONE_CAL_FVG_NY_AM",
    "ZONE_CAL_BOS_NY_AM",
    "ZONE_CAL_SWEEP_NY_AM",
    "ZONE_CAL_OB_NORMAL",
    "ZONE_CAL_FVG_NORMAL",
    "ZONE_CAL_BOS_NORMAL",
    "ZONE_CAL_SWEEP_NORMAL",
    "ZONE_CAL_OB_HIGH_VOL",
    "ZONE_CAL_FVG_HIGH_VOL",
    "ZONE_CAL_BOS_HIGH_VOL",
    "ZONE_CAL_SWEEP_HIGH_VOL",
    # ── ENG-WS2-02 trust cause trail (diagnostic; Pine consumes only
    # the rolled-up TRUST_STATE / TRUST_ACTION_IMPACT /
    # TRUST_DEGRADATION_REASON; the cause sub-fields stay Python-side
    # telemetry) ──
    "TRUST_CAUSE_DOMAIN",
    "TRUST_CAUSE_FAILURE_TYPE",
    "TRUST_CAUSE_CODE",
    # ── ENG-WS2-04 action degradation block (consumed by the Hero
    # Action helper at generation time; Pine reads the rolled-up
    # HERO_ACTION_* fields instead) ──
    "ACTION_DEGRADATION_TIER",
    "ACTION_DEGRADATION_REASON",
    "ACTION_DEGRADATION_DERIVED_FROM",
}

# Pine-surface contracts that are exported but not yet consumed by any
# *.pine file. Each entry is a real backlog item, not a hiding place
# for technical debt. Add a # ENG-WS… comment when extending.
RESERVED_PINE_EXPORTS: set[str] = set()

# ENG-WS3-03 — Hero Market Mode head. Generator already emits the
# block; dashboards still re-derive regime/bias/session/trust/freshness
# locally. Wiring lands together with the Mobile + Default surface
# reshape in the upcoming UI ticket.
from scripts.smc_hero_market_mode import (
    PINE_HERO_MARKET_FIELDS,
)

RESERVED_PINE_EXPORTS.update(PINE_HERO_MARKET_FIELDS)

# ENG-WS3-04 — Hero Setup-Quality card. Same situation as above:
# canonical card is exported, dashboards still pick from raw ensemble
# fields. Wired in the same UI ticket as the Market head.
from scripts.smc_hero_setup_quality import (
    PINE_HERO_QUALITY_FIELDS,
)

RESERVED_PINE_EXPORTS.update(PINE_HERO_QUALITY_FIELDS)

# ENG-WS3-05 — Hero Action recommendation. Exported as the canonical
# verb + reason; Pine still derives the action label internally.
from scripts.smc_hero_action import (
    PINE_HERO_ACTION_FIELDS,
)

RESERVED_PINE_EXPORTS.update(PINE_HERO_ACTION_FIELDS)

# F-3 (Boundary-Contract Plan 2026-04-23, PR-BC-02) — Pine sentinel
# constant for degraded per-family HR exports (e.g. ZONE_HR_FVG).
# Library exports the constant so consumers can write
# ``mp.ZONE_HR_FVG == mp.HR_SENTINEL_DEGRADED`` instead of hardcoding
# -1.0. The 14 Pine consumers are bumped from
# ``import .../smc_micro_profiles_generated/1`` to ``/2`` in a follow-up
# PR after the next TradingView library re-publish (plan §3.7 step 7).
RESERVED_PINE_EXPORTS.add("HR_SENTINEL_DEGRADED")

# Phase H Pine consumer maturity is now complete: ZONE_CAL_TRUST and the
# per-family ZONE_HR_{OB,BOS,SWEEP} were wired into the audit row 12
# composite warning + trust glyph by issue #16 (c). The follow-up tooltip
# patch then wired the remaining two scalars (ZONE_CAL_CONFIDENCE +
# ZONE_CAL_TREND) into the row 12 hover tooltip via dashboard_row_tt, so
# the entire ZONE_CAL_* scaffolding block from ADR 2026-04-22 has landed
# Pine consumers and no longer needs reservation.

# Backwards-compatible alias (keeps any external callers happy).
_INFRA_ONLY: set[str] = PYTHON_ONLY_EXPORTS | RESERVED_PINE_EXPORTS


def test_every_generated_field_has_pine_consumer() -> None:
    """Every generated field must be consumed, python-only, or reserved."""
    generated = _collect_generated_fields()
    pine_refs = _collect_pine_mp_refs()

    all_consumed: set[str] = set()
    for refs in pine_refs.values():
        all_consumed.update(refs)

    unclaimed = sorted(generated - all_consumed - _INFRA_ONLY)
    assert unclaimed == [], (
        "Generated fields with no Pine consumer.\n"
        "Decide on ownership: add a mp.* consumer, mark as PYTHON_ONLY_EXPORTS, "
        "or list in RESERVED_PINE_EXPORTS with a backlog reference:\n"
        + "\n".join(f"  {f}" for f in unclaimed)
    )


def test_python_only_and_reserved_categories_are_disjoint() -> None:
    """A field cannot be both Python-only and a reserved Pine contract."""
    overlap = sorted(PYTHON_ONLY_EXPORTS & RESERVED_PINE_EXPORTS)
    assert overlap == [], (
        "Fields appear in both PYTHON_ONLY_EXPORTS and RESERVED_PINE_EXPORTS "
        "— pick exactly one ownership: " + ", ".join(overlap)
    )


def test_reserved_pine_exports_have_no_pine_consumer_yet() -> None:
    """Reserved entries must stay reserved — once Pine consumes them, drop the entry."""
    pine_refs = _collect_pine_mp_refs()
    consumed: set[str] = set()
    for refs in pine_refs.values():
        consumed.update(refs)
    landed = sorted(RESERVED_PINE_EXPORTS & consumed)
    assert landed == [], (
        "These RESERVED_PINE_EXPORTS now have a Pine consumer — "
        "remove them from the reserved set: " + ", ".join(landed)
    )


def test_infra_only_fields_are_generated() -> None:
    """Prevent ownership lists from going stale — every entry must still be generated."""
    generated = _collect_generated_fields()
    for field in PYTHON_ONLY_EXPORTS | RESERVED_PINE_EXPORTS:
        assert field in generated, (
            f"{field} is declared as python-only / reserved "
            "but is no longer generated — remove it."
        )
