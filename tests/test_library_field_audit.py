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
    # ENG-WS3-03 / -04 hero-surface block helpers. ENG-WS3-05 now
    # projects through the HERO_ACTION field in generate_smc_micro_profiles.py.
    ROOT / "scripts" / "smc_hero_market_mode.py",
    ROOT / "scripts" / "smc_hero_setup_quality.py",
]

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
    fields.update(_ZH_DEFAULTS.keys())
    return fields


def _collect_pine_mp_refs() -> dict[str, set[str]]:
    """Return {pine_file: {field_names}} for all mp.FIELD references.

    Comment-only references are filtered out: ``// foo mp.BAR baz`` is
    documentation, not a Pine consumer of ``mp.BAR``. Pine has no block
    comments, only ``//`` line comments, so a line-by-line strip-then-
    match is sufficient.

    Found via SMC review v3 phase 11 — without the strip, German-language
    TODO comments in SMC_Hold_Manager.pine (e.g. ``// Quality-Sizing aus
    mp.HERO_QUALITY_TIER + ZONE_HR_*``) caused two false-positive RED
    pins (``test_all_pine_mp_refs_resolve_to_generated_fields`` and
    ``test_reserved_pine_exports_have_no_pine_consumer_yet``).
    """
    result: dict[str, set[str]] = {}
    pattern = re.compile(r"\bmp\.([A-Z_][A-Z0-9_]+)")
    for pine in sorted(_PINE_DIR.glob("*.pine")):
        source = pine.read_text(encoding="utf-8")
        refs: set[str] = set()
        for raw_line in source.splitlines():
            stripped = raw_line.lstrip()
            if stripped.startswith("//"):
                continue
            # Strip trailing inline comments before matching so
            # ``foo = bar  // mp.SOMETHING`` is also filtered.
            code_part = raw_line.split("//", 1)[0]
            refs.update(pattern.findall(code_part))
        if refs:
            result[pine.name] = refs
    return result


def test_all_pine_mp_refs_resolve_to_generated_fields() -> None:
    from scripts.smc_bus_manifest import SURFACE_DEFINITIONS

    generated = _collect_generated_fields()
    pine_refs = _collect_pine_mp_refs()

    observed_missing = {
        (fname, ref)
        for fname, refs in pine_refs.items()
        for ref in refs - generated
    }
    declared_missing = {
        (surface.file, ref)
        for surface in SURFACE_DEFINITIONS
        for ref in surface.known_missing_mp_fields
    }
    undeclared = sorted(observed_missing - declared_missing)
    stale = sorted(declared_missing - observed_missing)

    assert undeclared == [], (
        "Pine mp.* references to non-existent library fields were added "
        "without per-surface debt classification:\n"
        + "\n".join(f"  {fname} -> mp.{ref}" for fname, ref in undeclared)
    )
    assert stale == [], (
        "Declared per-surface mp.* debt is stale; remove resolved entries:\n"
        + "\n".join(f"  {fname} -> mp.{ref}" for fname, ref in stale)
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


def test_missing_mp_field_debt_is_exact_and_replacement_scoped() -> None:
    """Debt is an exact per-file snapshot, never a global field allowlist."""
    from scripts.smc_bus_manifest import SURFACE_DEFINITIONS

    generated = _collect_generated_fields()
    pine_refs = _collect_pine_mp_refs()
    debt_surfaces = [
        surface
        for surface in SURFACE_DEFINITIONS
        if surface.known_missing_mp_fields
    ]

    # 2026-07-30 R5 rebuild removed HTF Confluence (12 fields) and Session
    # Context (2 fields) from the snapshot-debt population: 7/81 -> 5/67.
    assert len(debt_surfaces) == 5
    assert sum(len(surface.known_missing_mp_fields) for surface in debt_surfaces) == 67
    for surface in debt_surfaces:
        observed = pine_refs.get(surface.file, set()) - generated
        assert surface.lifecycle == "replacement_pending"
        assert surface.rollout_state == "not_deployed"
        assert surface.compile_expectation == "known_broken"
        assert set(surface.known_missing_mp_fields) == observed


def test_active_deployed_and_required_surfaces_have_no_mp_field_debt() -> None:
    from scripts.smc_bus_manifest import SURFACE_DEFINITIONS

    offenders = [
        (
            surface.file,
            surface.lifecycle,
            surface.rollout_state,
            surface.compile_expectation,
        )
        for surface in SURFACE_DEFINITIONS
        if surface.known_missing_mp_fields
        and (
            surface.lifecycle == "active"
            or surface.rollout_state == "deployed"
            or surface.compile_expectation == "required"
        )
    ]

    assert offenders == [], (
        "active, deployed, and compile-required surfaces must be mp-debt-free: "
        f"{offenders}"
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
    # ── R5 live-context cutover (2026-07-30) ──
    # These compatibility exports remain generated for Python enrichment and
    # existing published-library readers. The rebuilt Pine roots deliberately
    # compute confirmed chart/session state locally and MUST NOT regress to
    # these frozen snapshot fields.
    "ATR_RATIO",
    "ATR_REGIME",
    "SESSION_DIRECTION_BIAS",
    "SQUEEZE_MOMENTUM_BIAS",
    "SQUEEZE_ON",
    "SQUEEZE_RELEASED",
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
    # the rolled-up TRUST_STATE / TRUST_DEGRADATION_REASON; the cause
    # sub-fields stay Python-side telemetry. NOTE: TRUST_ACTION_IMPACT
    # is intentionally NOT listed here — it is exported as the
    # canonical rolled-up action-impact label but is RESERVED (see the
    # RESERVED_PINE_EXPORTS.add('TRUST_ACTION_IMPACT') call below) until
    # the dashboard re-wire ticket lands. A comment in
    # SMC_Decision_Board.pine:759 documents only the *intent* to wire it up;
    # that comment was previously misclassified as a real consumer by
    # the unfiltered regex scan, hence the v3 phase 11 fix.) ──
    "TRUST_CAUSE_DOMAIN",
    "TRUST_CAUSE_FAILURE_TYPE",
    "TRUST_CAUSE_CODE",
    # ── ENG-WS2-04 action degradation block (consumed by the Hero
    # Action helper at generation time; Pine reads the rolled-up
    # HERO_ACTION field instead) ──
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

# ENG-WS2-02 trust contract — exported as the canonical rolled-up
# action-impact label, but no production *.pine file consumes it yet
# (a comment in SMC_Decision_Board.pine:759 documents the *intent* to
# consume it — that comment was previously misclassified as a real
# consumer by the unfiltered regex scan; see v3 phase 11 fix).
# Re-classified as RESERVED with a backlog reference until the
# dashboard re-wire ticket lands.
RESERVED_PINE_EXPORTS.add("TRUST_ACTION_IMPACT")

# F-3 (Boundary-Contract Plan 2026-04-23, PR-BC-02) — Pine sentinel
# constant for degraded per-family HR exports (e.g. ZONE_HR_FVG).
# Library exports the constant so consumers can write
# ``mp.ZONE_HR_FVG == mp.HR_SENTINEL_DEGRADED`` instead of hardcoding
# -1.0. The 14 Pine consumers are bumped from
# ``import .../smc_micro_profiles_generated/1`` to ``/2`` in a follow-up
# PR after the next TradingView library re-publish (plan §3.7 step 7).
RESERVED_PINE_EXPORTS.add("HR_SENTINEL_DEGRADED")

# Confidence-vocabulary close-window (2026-08-10): the legacy
# ZONE_CAL_CONFIDENCE export is intentionally absent after its four-week
# migration window; ZONE_CAL_RELIABILITY_SCORE is the sole Pine contract.

# Phase H Pine consumer maturity is now complete: ZONE_CAL_TRUST and the
# per-family ZONE_HR_{OB,BOS,SWEEP} were wired into the audit row 12
# composite warning + trust glyph by issue #16 (c). The follow-up tooltip
# patch then wired the remaining two scalars (ZONE_CAL_RELIABILITY_SCORE +
# ZONE_CAL_TREND) into the row 12 hover tooltip via dashboard_row_tt, so
# the entire ZONE_CAL_* scaffolding block from ADR 2026-04-22 has landed
# Pine consumers and no longer needs reservation.

# #3622 (2026-07-14) — enrichment surface that was never really wired.
#
# These 32 fields looked consumed until the engine extraction, but their only
# "consumer" was a dead read in the core suite:
#
#     float  lib_ats_value        = mp.ATS_VALUE          // assigned, never read
#     float  lib_yield_10y        = mp.TREASURY_10Y_YIELD
#     string lib_sector_strongest = mp.SECTOR_STRONGEST
#
# Each lib_* name occurred exactly ONCE in the file — the assignment itself. This
# audit was therefore passing on a *mention*, not a use: none of these fields ever
# reached a rendered Pine surface. #3622 deleted the dead block along with the rest
# of the extracted layer (correctly — no product surface was lost); that is what
# made the gap visible, not what created it.
#
# RESERVED rather than PYTHON_ONLY on purpose: the dead reads are evidence that a
# Pine surface was *intended* for this data, so declaring "Pine MUST NOT depend on
# this" would record a decision nobody made. Reserved keeps the debt visible until
# each field is either wired to a real consumer or demoted deliberately.
#
# Backlog: #3622 removed the dead reads; the wiring decision itself is untriaged.
# Do NOT copy this block as precedent — new entries still need their own ticket.
RESERVED_PINE_EXPORTS.update({
    # Analyst / insider / institutional (FMP enrichment)
    "ANALYST_HIGH_UPSIDE_TICKERS", "ANALYST_STRONG_BUY_TICKERS",
    "ANALYST_UNDERPERFORM_TICKERS", "INSIDER_BUYING_TICKERS",
    "INSIDER_SELLING_HEAVY_TICKERS", "INSTITUTIONAL_DATA_AVAILABLE",
    # Advance/decline + breadth
    "ATS_BEARISH_SEQUENCE", "ATS_BULLISH_SEQUENCE", "ATS_CHANGE_PCT",
    "ATS_VALUE", "ATS_ZSCORE", "GLOBAL_STRENGTH",
    # Short interest
    "HIGH_SHORT_INTEREST_TICKERS", "MARKET_SHORT_INTEREST_AVG",
    "SHORT_INTEREST_EXTREME",
    # News
    "MOST_MENTIONED_TICKER", "NEWS_BEARISH_TICKERS", "NEWS_BULLISH_TICKERS",
    "NEWS_CATEGORY_MAP", "NEWS_COUNT_MAP",
    # Sector rotation
    "SECTOR_LAGGING", "SECTOR_STRONGEST", "SECTOR_WEAKEST",
    # Rates / macro
    "TREASURY_10Y_YIELD", "TREASURY_2Y_YIELD", "YIELD_CURVE_SPREAD",
    # SMC zone geometry — likeliest of this block to earn a real consumer
    "OB_AGE_BARS", "PRIMARY_FVG_DISTANCE", "PRIMARY_OB_DISTANCE", "REL_SIZE",
    # Session / volume context
    "SESSION_VOLATILITY_STATE", "VOLUME_LOW_TICKERS",
})

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
