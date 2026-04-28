"""Tests for the Phase H Pine consumer exports."""

from __future__ import annotations

import pytest

from scripts.smc_zone_priority_consumer import (
    DEFAULTS,
    HR_SENTINEL_DEGRADED,
    TRUST_DEGRADED,
    TRUST_FRESH,
    TRUST_STALE,
    TRUST_UNAVAILABLE,
    build_consumer_exports,
    classify_trust_state,
    compute_calibration_confidence,
    compute_calibration_trend,
    compute_per_family_hit_rates,
    degrade_family_hit_rates,
)

# ── Defaults ────────────────────────────────────────────────────


def test_defaults_have_required_keys() -> None:
    assert set(DEFAULTS) == {
        "ZONE_CAL_CONFIDENCE",
        "ZONE_HR_OB",
        "ZONE_HR_FVG",
        "ZONE_HR_BOS",
        "ZONE_HR_SWEEP",
        "ZONE_CAL_TREND",
        "ZONE_CAL_TRUST",
    }


def test_defaults_are_neutral() -> None:
    assert DEFAULTS["ZONE_CAL_CONFIDENCE"] == 0.0
    assert DEFAULTS["ZONE_HR_OB"] == 0.0
    assert DEFAULTS["ZONE_CAL_TREND"] == "STABLE"
    assert DEFAULTS["ZONE_CAL_TRUST"] == TRUST_UNAVAILABLE


# ── H1: Calibration Confidence ─────────────────────────────────


def test_confidence_zero_when_no_events() -> None:
    assert compute_calibration_confidence(0, 0.05) == 0.0
    assert compute_calibration_confidence(None, 0.05) == 0.0


def test_confidence_saturates_at_1000_events_with_clean_ece() -> None:
    # Perfect case — well-calibrated and well-sampled.
    assert compute_calibration_confidence(1000, 0.0) == 1.0
    # Beyond saturation does not exceed 1.0.
    assert compute_calibration_confidence(5000, 0.0) == 1.0


def test_confidence_scales_linearly_below_saturation() -> None:
    # 250 events / 1000 saturation × no ECE penalty = 0.25
    assert compute_calibration_confidence(250, 0.0) == 0.25


def test_confidence_zeroed_by_high_smooth_ece() -> None:
    # smECE 0.20 → penalty multiplier 0.0 → confidence 0 regardless
    # of sample size. This is the "do not trust" boundary.
    assert compute_calibration_confidence(1000, 0.20) == 0.0
    assert compute_calibration_confidence(1000, 0.30) == 0.0


def test_confidence_partial_penalty_smooth_ece() -> None:
    # smECE 0.10 → penalty 1.0 - 5*0.10 = 0.50.
    # 1000 events → events_score 1.0. Confidence = 0.50.
    assert compute_calibration_confidence(1000, 0.10) == 0.50


def test_confidence_handles_invalid_inputs_gracefully() -> None:
    assert compute_calibration_confidence("not-a-number", 0.05) == 0.0
    assert compute_calibration_confidence(500, "bad") == 0.0
    assert compute_calibration_confidence(-50, 0.05) == 0.0


# ── H2: Per-family hit rates ───────────────────────────────────


_REAL_STATS = {
    "OB":    {"weighted_hit_rate": 0.8636, "simple_hit_rate": 0.8636},
    "FVG":   {"weighted_hit_rate": 0.5937, "simple_hit_rate": 0.5938},
    "BOS":   {"weighted_hit_rate": 0.913,  "simple_hit_rate": 0.913},
    "SWEEP": {"weighted_hit_rate": 0.8333, "simple_hit_rate": 0.8333},
}


def test_per_family_hit_rates_passthrough() -> None:
    out = compute_per_family_hit_rates(_REAL_STATS)
    assert out["ZONE_HR_OB"] == 0.8636
    assert out["ZONE_HR_FVG"] == 0.5937
    assert out["ZONE_HR_BOS"] == 0.913
    assert out["ZONE_HR_SWEEP"] == 0.8333


def test_per_family_hit_rates_missing_family_defaults_zero() -> None:
    out = compute_per_family_hit_rates({"OB": _REAL_STATS["OB"]})
    assert out["ZONE_HR_OB"] == 0.8636
    assert out["ZONE_HR_FVG"] == 0.0
    assert out["ZONE_HR_BOS"] == 0.0
    assert out["ZONE_HR_SWEEP"] == 0.0


def test_per_family_hit_rates_falls_back_to_simple() -> None:
    out = compute_per_family_hit_rates(
        {"OB": {"simple_hit_rate": 0.75}}
    )
    assert out["ZONE_HR_OB"] == 0.75


def test_per_family_hit_rates_handles_nan_and_invalid() -> None:
    out = compute_per_family_hit_rates(
        {
            "OB":    {"weighted_hit_rate": float("nan")},
            "FVG":   {"weighted_hit_rate": "bad"},
            "BOS":   {"weighted_hit_rate": 1.5},   # clamped to 1.0
            "SWEEP": {"weighted_hit_rate": -0.2},  # clamped to 0.0
        }
    )
    assert out["ZONE_HR_OB"] == 0.0
    assert out["ZONE_HR_FVG"] == 0.0
    assert out["ZONE_HR_BOS"] == 1.0
    assert out["ZONE_HR_SWEEP"] == 0.0


def test_per_family_hit_rates_none_input() -> None:
    out = compute_per_family_hit_rates(None)
    assert out == {f"ZONE_HR_{f}": 0.0 for f in ("OB", "FVG", "BOS", "SWEEP")}


# ── H3: Calibration trend ──────────────────────────────────────


def test_trend_stable_with_too_few_runs() -> None:
    history = [
        {"weighted_hit_rate": 0.60},
        {"weighted_hit_rate": 0.80},
    ]
    assert compute_calibration_trend(history) == "STABLE"


def test_trend_improving() -> None:
    history = [
        {"weighted_hit_rate": 0.60},
        {"weighted_hit_rate": 0.65},
        {"weighted_hit_rate": 0.70},
    ]
    assert compute_calibration_trend(history) == "IMPROVING"


def test_trend_degrading() -> None:
    history = [
        {"weighted_hit_rate": 0.80},
        {"weighted_hit_rate": 0.75},
        {"weighted_hit_rate": 0.70},
    ]
    assert compute_calibration_trend(history) == "DEGRADING"


def test_trend_stable_within_delta() -> None:
    # Delta < 0.02 across the window → STABLE.
    history = [
        {"weighted_hit_rate": 0.700},
        {"weighted_hit_rate": 0.705},
        {"weighted_hit_rate": 0.715},
    ]
    assert compute_calibration_trend(history) == "STABLE"


def test_trend_derives_avg_from_family_stats_when_top_level_missing() -> None:
    # Three runs, each only carrying family_stats — IMPROVING from 0.6
    # avg → 0.85 avg (mocking what the calibration JSON ships).
    history = [
        {"family_stats": {fam: {"weighted_hit_rate": 0.60} for fam in ("OB", "FVG", "BOS", "SWEEP")}},
        {"family_stats": {fam: {"weighted_hit_rate": 0.72} for fam in ("OB", "FVG", "BOS", "SWEEP")}},
        {"family_stats": {fam: {"weighted_hit_rate": 0.85} for fam in ("OB", "FVG", "BOS", "SWEEP")}},
    ]
    assert compute_calibration_trend(history) == "IMPROVING"


def test_trend_handles_none_and_empty() -> None:
    assert compute_calibration_trend(None) == "STABLE"
    assert compute_calibration_trend([]) == "STABLE"


# ── Aggregator ──────────────────────────────────────────────────


def test_build_consumer_exports_full_payload() -> None:
    # High enough confidence to stay FRESH: 1000 events, clean ECE.
    out = build_consumer_exports(
        family_stats=_REAL_STATS,
        total_events=1000,
        smooth_ece=0.0,
        history=[
            {"weighted_hit_rate": 0.70},
            {"weighted_hit_rate": 0.74},
            {"weighted_hit_rate": 0.78},
        ],
    )
    # Keys complete.
    assert set(out) == set(DEFAULTS)
    # 1000/1000 events, no ECE penalty -> confidence 1.0.
    assert out["ZONE_CAL_CONFIDENCE"] == pytest.approx(1.0, abs=1e-4)
    assert out["ZONE_CAL_TRUST"] == TRUST_FRESH
    # Hit rates pass through unchanged.
    assert out["ZONE_HR_OB"] == 0.8636
    # Trend captured.
    assert out["ZONE_CAL_TREND"] == "IMPROVING"


def test_build_consumer_exports_defaults_on_empty() -> None:
    """Empty input -> trust=UNAVAILABLE. After ADR 2026-04-23
    (D-2 fix) UNAVAILABLE degrades family HRs to the sentinel, so
    the shape no longer equals the static :data:`DEFAULTS` fallback
    (which still carries neutral ``0.0`` for back-compat callers
    that never go through ``build_consumer_exports``).

    Both ``0.0`` and ``-1.0`` satisfy the Pine consumer guard
    ``mp.ZONE_HR_FVG <= 0.0`` so the dashboard renders identically.
    """
    out = build_consumer_exports(
        family_stats=None, total_events=None, smooth_ece=None, history=None
    )
    # Non-HR / non-trust keys still fall back to the static defaults.
    assert out["ZONE_CAL_CONFIDENCE"] == DEFAULTS["ZONE_CAL_CONFIDENCE"]
    assert out["ZONE_CAL_TREND"] == DEFAULTS["ZONE_CAL_TREND"]
    assert out["ZONE_CAL_TRUST"] == TRUST_UNAVAILABLE
    # Family HRs degrade to the sentinel under UNAVAILABLE.
    assert out["ZONE_HR_OB"] == HR_SENTINEL_DEGRADED
    assert out["ZONE_HR_FVG"] == HR_SENTINEL_DEGRADED
    assert out["ZONE_HR_BOS"] == HR_SENTINEL_DEGRADED
    assert out["ZONE_HR_SWEEP"] == HR_SENTINEL_DEGRADED
    # Key set is still complete.
    assert set(out) == set(DEFAULTS)


# ── Trust gating (P0 — ADR 2026-04-22) ───────────────────────────


def test_classify_trust_fresh_above_threshold() -> None:
    assert classify_trust_state(0.35) == TRUST_FRESH
    assert classify_trust_state(1.0) == TRUST_FRESH


def test_classify_trust_degraded_below_threshold() -> None:
    # The exact 258-event / smECE=0.0833 symptom from the H2 smoke.
    assert classify_trust_state(0.1505) == TRUST_DEGRADED
    assert classify_trust_state(0.29) == TRUST_DEGRADED


def test_classify_trust_unavailable_on_zero_or_invalid() -> None:
    assert classify_trust_state(0.0) == TRUST_UNAVAILABLE
    assert classify_trust_state(-0.1) == TRUST_UNAVAILABLE
    assert classify_trust_state(float("nan")) == TRUST_UNAVAILABLE
    assert classify_trust_state("bad") == TRUST_UNAVAILABLE


def test_classify_trust_custom_threshold() -> None:
    assert classify_trust_state(0.20, min_confidence=0.10) == TRUST_FRESH
    assert classify_trust_state(0.20, min_confidence=0.50) == TRUST_DEGRADED


def test_degrade_family_hit_rates_replaces_when_not_fresh() -> None:
    hrs = {
        "ZONE_HR_OB": 0.8636,
        "ZONE_HR_FVG": 0.5937,
        "ZONE_HR_BOS": 0.913,
        "ZONE_HR_SWEEP": 0.8333,
    }
    out = degrade_family_hit_rates(hrs, TRUST_DEGRADED)
    assert all(v == HR_SENTINEL_DEGRADED for v in out.values())
    assert set(out) == set(hrs)


def test_degrade_family_hit_rates_passthrough_when_fresh() -> None:
    hrs = {"ZONE_HR_OB": 0.55}
    assert degrade_family_hit_rates(hrs, TRUST_FRESH) == hrs


def test_aggregator_degrades_ob_hr_on_subsaturation_sample() -> None:
    """Pin the exact 2026-04-22 symptom: 258-event corpus, smECE
    0.0833, OB weighted_hit_rate 0.8636 — must degrade to sentinel.
    """
    out = build_consumer_exports(
        family_stats=_REAL_STATS,
        total_events=258,
        smooth_ece=0.0833,
        history=None,
    )
    assert out["ZONE_CAL_CONFIDENCE"] < 0.30
    assert out["ZONE_CAL_TRUST"] == TRUST_DEGRADED
    # The critical assertion — the user MUST NOT see 0.8636 here.
    assert out["ZONE_HR_OB"] == HR_SENTINEL_DEGRADED
    assert out["ZONE_HR_FVG"] == HR_SENTINEL_DEGRADED
    assert out["ZONE_HR_BOS"] == HR_SENTINEL_DEGRADED
    assert out["ZONE_HR_SWEEP"] == HR_SENTINEL_DEGRADED


def test_aggregator_keeps_hr_when_confidence_is_high() -> None:
    """v3-corpus-shaped input (n=10 004, clean ECE) stays FRESH and
    passes HRs through unchanged."""
    out = build_consumer_exports(
        family_stats=_REAL_STATS,
        total_events=10_004,
        smooth_ece=0.02,
        history=None,
    )
    assert out["ZONE_CAL_TRUST"] == TRUST_FRESH
    assert out["ZONE_HR_OB"] == 0.8636  # passthrough (fixture value)


def test_aggregator_custom_min_confidence_override() -> None:
    """Lower gate via kwarg flips the sub-saturation case to FRESH."""
    out = build_consumer_exports(
        family_stats=_REAL_STATS,
        total_events=258,
        smooth_ece=0.0833,
        history=None,
        min_confidence=0.10,
    )
    assert out["ZONE_CAL_TRUST"] == TRUST_FRESH
    assert out["ZONE_HR_OB"] == 0.8636


def test_aggregator_unavailable_degrades_family_hrs() -> None:
    """Supersedes ``test_aggregator_unavailable_when_confidence_zero``
    (ADR 2026-04-23 — OB-Export-Degradierung).

    When ``total_events=0`` but ``family_stats`` is non-empty, the
    legacy behaviour silently leaked ``OB HR=0.8636`` to Pine because
    trust was UNAVAILABLE and ``degrade_family_hit_rates`` granted
    passthrough. After the fix UNAVAILABLE degrades family HRs just
    like DEGRADED so the under-saturated smoke run cannot leak.
    """
    out = build_consumer_exports(
        family_stats=_REAL_STATS,
        total_events=0,
        smooth_ece=0.0,
        history=None,
    )
    assert out["ZONE_CAL_CONFIDENCE"] == 0.0
    assert out["ZONE_CAL_TRUST"] == TRUST_UNAVAILABLE
    # The critical assertion inversion — must NOT leak 0.8636.
    assert out["ZONE_HR_OB"] == HR_SENTINEL_DEGRADED
    assert out["ZONE_HR_FVG"] == HR_SENTINEL_DEGRADED
    assert out["ZONE_HR_BOS"] == HR_SENTINEL_DEGRADED
    assert out["ZONE_HR_SWEEP"] == HR_SENTINEL_DEGRADED


def test_degrade_family_hit_rates_degrades_unavailable() -> None:
    """UNAVAILABLE is now as strict as DEGRADED — callers that supply
    ``family_stats`` without ``total_events`` get the sentinel, not
    passthrough. Protects against the 2026-04-22 symptom pattern.
    """
    hrs = {
        "ZONE_HR_OB": 0.8636,
        "ZONE_HR_FVG": 0.5937,
        "ZONE_HR_BOS": 0.913,
        "ZONE_HR_SWEEP": 0.8333,
    }
    out = degrade_family_hit_rates(hrs, TRUST_UNAVAILABLE)
    assert all(v == HR_SENTINEL_DEGRADED for v in out.values())
    assert set(out) == set(hrs)


def test_degrade_family_hit_rates_passthrough_on_stale() -> None:
    """STALE is advisory-only (reserved for WS2) — HRs still render
    in the Pine dashboard. No degrade.
    """
    hrs = {"ZONE_HR_OB": 0.55}
    assert degrade_family_hit_rates(hrs, TRUST_STALE) == hrs


# ── Pine-Boundary Vokabular (D-1 Regression, ADR 2026-04-23) ───────────


def test_trust_fresh_constant_matches_pine_glyph_literal() -> None:
    """The TRUST_FRESH string must be the exact literal the Pine
    dashboard's ``zone_cal_trust_glyph()`` branches on. Any drift
    here causes the 🔒 glyph to fall back to '?' silently. The
    hard-coded expected value prevents a future commit from
    re-renaming the constant without reviewing the Pine surface.
    """
    assert TRUST_FRESH == "OK"


def test_trust_vocabulary_is_distinct_and_uppercase() -> None:
    """Pine's string-comparison guard uses literal uppercase tokens
    (see ``SMC_Dashboard.pine::zone_cal_trust_glyph`` and the
    ``ex_trust_ok`` gate). Pin the full surface.
    """
    assert TRUST_FRESH == "OK"
    assert TRUST_DEGRADED == "DEGRADED"
    assert TRUST_STALE == "STALE"
    assert TRUST_UNAVAILABLE == "UNAVAILABLE"
    # Disjoint — no accidental alias.
    assert len({TRUST_FRESH, TRUST_DEGRADED, TRUST_STALE, TRUST_UNAVAILABLE}) == 4


def test_build_consumer_exports_emits_ok_literal_on_healthy_corpus() -> None:
    """End-to-end pin: v3-shaped input (n=10 004, clean ECE) must
    emit the literal Pine token ``"OK"``, not the legacy ``"FRESH"``.
    """
    out = build_consumer_exports(
        family_stats=_REAL_STATS,
        total_events=10_004,
        smooth_ece=0.02,
        history=None,
    )
    assert out["ZONE_CAL_TRUST"] == "OK"
    assert out["ZONE_HR_OB"] == 0.8636  # passthrough unchanged


# ── ZONE_CAL_TREND frozen-vocab (F-11, PR-BC-01) ─────────────────


def test_compute_calibration_trend_returns_value_in_frozen_vocab() -> None:
    """Any trend string reaching Pine MUST belong to ``TREND_VOCAB`` —
    otherwise the Dashboard tooltip (SMC_Dashboard.pine:1440-1444)
    silently concatenates arbitrary text, because there is no literal
    gate on the Pine side.
    """
    from scripts.smc_zone_priority_consumer import (
        TREND_VOCAB,
        compute_calibration_trend,
    )

    # Positive path — enough history to make a call.
    out = compute_calibration_trend([{"weighted_hit_rate": 0.5}] * 20)
    assert out in TREND_VOCAB

    # Edge: empty history → STABLE.
    assert compute_calibration_trend([]) in TREND_VOCAB
    assert compute_calibration_trend(None) in TREND_VOCAB

    # Edge: singleton / below min_runs → STABLE.
    assert compute_calibration_trend([{"weighted_hit_rate": 0.5}]) in TREND_VOCAB

    # Exercise each branch explicitly to pin the full value space.
    rising = [{"weighted_hit_rate": v} for v in (0.30, 0.40, 0.50)]
    falling = [{"weighted_hit_rate": v} for v in (0.60, 0.50, 0.40)]
    flat = [{"weighted_hit_rate": 0.50}] * 3
    assert compute_calibration_trend(rising) in TREND_VOCAB
    assert compute_calibration_trend(falling) in TREND_VOCAB
    assert compute_calibration_trend(flat) in TREND_VOCAB


def test_trend_vocab_constants_pinned() -> None:
    """Pin the three trend literal values; a rename of a constant
    without a Pine-side branch update would regress silently.
    """
    from scripts.smc_zone_priority_consumer import (
        TREND_DEGRADING,
        TREND_IMPROVING,
        TREND_STABLE,
        TREND_VOCAB,
    )

    assert TREND_IMPROVING == "IMPROVING"
    assert TREND_STABLE == "STABLE"
    assert TREND_DEGRADING == "DEGRADING"
    assert frozenset({"IMPROVING", "STABLE", "DEGRADING"}) == TREND_VOCAB
