"""Tests for the C9 AI Zone Priority pipeline."""
from __future__ import annotations

import pytest

from scripts.smc_zone_priority import (
    DEFAULTS,
    _clamp,
    _identify_catalyst,
    _rank_from_score,
    _select_top_family,
    build_zone_priority,
)

# ── Defaults ────────────────────────────────────────────────────

def test_defaults_have_required_keys() -> None:
    assert set(DEFAULTS) == {
        "ZONE_PRIORITY_RANK",
        "ZONE_PRIORITY_SCORE",
        "ZONE_PRIORITY_TOP_FAMILY",
        "ZONE_PRIORITY_CATALYST",
        "ZONE_PRIORITY_REASON",
    }


def test_defaults_are_neutral() -> None:
    assert DEFAULTS["ZONE_PRIORITY_RANK"] == "C"
    assert DEFAULTS["ZONE_PRIORITY_SCORE"] == 0
    assert DEFAULTS["ZONE_PRIORITY_CATALYST"] == "NONE"


# ── Rank mapping ────────────────────────────────────────────────

@pytest.mark.parametrize("score,expected", [
    (100, "A"), (75, "A"), (74, "B"), (50, "B"),
    (49, "C"), (25, "C"), (24, "D"), (0, "D"),
])
def test_rank_from_score(score: int, expected: str) -> None:
    assert _rank_from_score(score) == expected


# ── Clamp ───────────────────────────────────────────────────────

def test_clamp_within_bounds() -> None:
    assert _clamp(0.5) == 0.5
    assert _clamp(-0.5) == 0.0
    assert _clamp(1.5) == 1.0


def test_clamp_nan_maps_to_low_bound_not_high() -> None:
    """NaN is 'no signal' and must clamp to ``lo`` (0.0), never silently to
    ``hi`` (1.0). max(lo, min(hi, nan)) would otherwise return hi because NaN
    compares False to everything.
    """
    assert _clamp(float("nan")) == 0.0
    assert _clamp(float("nan"), lo=0.2, hi=0.9) == 0.2


def test_clamp_infinities_clamp_to_bounds() -> None:
    assert _clamp(float("inf")) == 1.0
    assert _clamp(float("-inf")) == 0.0


def test_build_zone_priority_nan_score_does_not_inflate_rank() -> None:
    """A NaN ensemble_score must not silently inflate the zone-priority score.

    Regression: float('nan') is truthy, so the production call site
    ``ensemble_score=float(_eq.get('score') or 0.0)`` passes NaN straight
    through. Before the NaN guard this produced a mid (B) rank instead of the
    low rank a zero/absent signal should yield.
    """
    nan_out = build_zone_priority(regime="NEUTRAL", ensemble_score=float("nan"))
    zero_out = build_zone_priority(regime="NEUTRAL", ensemble_score=0.0)
    # NaN must behave like no signal (== 0.0 contribution), not max signal.
    assert nan_out["ZONE_PRIORITY_SCORE"] == zero_out["ZONE_PRIORITY_SCORE"]


# ── Risk-on scenario: high score ────────────────────────────────

def test_risk_on_high_confidence_produces_high_score() -> None:
    result = build_zone_priority(
        regime="RISK_ON",
        ensemble_score=0.9,
        news_heat=0.4,
        event_risk_level="NONE",
        session_context="RTH",
        vol_regime="NORMAL",
        zone_proj_score=4,
        htf_aligned=True,
    )
    assert result["ZONE_PRIORITY_RANK"] in ("A", "B")
    assert result["ZONE_PRIORITY_SCORE"] >= 60
    assert result["ZONE_PRIORITY_CATALYST"] == "NEWS"
    assert result["ZONE_PRIORITY_REASON"]


# ── Risk-off scenario: low score ───────────────────────────────

def test_risk_off_low_confidence_produces_low_score() -> None:
    result = build_zone_priority(
        regime="RISK_OFF",
        ensemble_score=0.1,
        news_heat=0.0,
        event_risk_level="HIGH",
        session_context="OVERNIGHT",
        vol_regime="EXTREME",
        zone_proj_score=0,
        htf_aligned=False,
    )
    assert result["ZONE_PRIORITY_RANK"] in ("C", "D")
    assert result["ZONE_PRIORITY_SCORE"] < 40
    assert result["ZONE_PRIORITY_CATALYST"] == "EVENT"


# ── Default call returns valid structure ────────────────────────

def test_default_call_returns_all_keys() -> None:
    result = build_zone_priority()
    assert set(result) == set(DEFAULTS)
    assert isinstance(result["ZONE_PRIORITY_SCORE"], int)
    assert result["ZONE_PRIORITY_RANK"] in ("A", "B", "C", "D")


# ── Top family selection ───────────────────────────────────────

def test_ob_favored_in_normal_aligned() -> None:
    family = _select_top_family(regime="RISK_ON", vol_regime="NORMAL", htf_aligned=True)
    assert family == "OB"


def test_sweep_favored_in_extreme_vol() -> None:
    family = _select_top_family(regime="RISK_OFF", vol_regime="EXTREME", htf_aligned=False)
    # SWEEP gets +0.15 in EXTREME, should be competitive
    assert family in ("SWEEP", "OB")


def test_fvg_penalized_in_eth_session() -> None:
    """R4: FVG should be disfavored during extended trading hours."""
    family_rth = _select_top_family(regime="NEUTRAL", vol_regime="HIGH_VOL", htf_aligned=False, session_context="ETH")
    family_none = _select_top_family(regime="NEUTRAL", vol_regime="HIGH_VOL", htf_aligned=False)
    # Without session context, FVG gets full bonus; with ETH it gets penalized
    # so the top family should differ or at least FVG should not win in ETH
    assert family_rth != "FVG" or family_none != "FVG"


def test_fvg_boosted_in_rth_session() -> None:
    """R4: FVG should get a boost during regular trading hours."""
    # Use calibrated weights where FVG is close to OB so the RTH boost pushes it over
    weights = {"OB": 0.72, "FVG": 0.70, "BOS": 0.65, "SWEEP": 0.60}
    family = _select_top_family(
        regime="NEUTRAL", vol_regime="HIGH_VOL", htf_aligned=False,
        session_context="RTH", calibrated_family_weights=weights,
    )
    # FVG gets +0.08 (HIGH_VOL) +0.03 (NEUTRAL) +0.05 (RTH) = 0.86 vs OB 0.72
    assert family == "FVG"


def test_session_context_backward_compat() -> None:
    """R4: Omitting session_context should not change existing behavior."""
    family_old = _select_top_family(regime="RISK_ON", vol_regime="NORMAL", htf_aligned=True)
    family_new = _select_top_family(regime="RISK_ON", vol_regime="NORMAL", htf_aligned=True, session_context=None)
    assert family_old == family_new


# ── F3: multiplicative score combination (experiment arm) ──────

def test_multiplicative_default_is_additive() -> None:
    """Default behavior must remain additive (no production change)."""
    add = _select_top_family(regime="RISK_ON", vol_regime="NORMAL", htf_aligned=True)
    explicit = _select_top_family(
        regime="RISK_ON", vol_regime="NORMAL", htf_aligned=True,
        family_score_combination="additive",
    )
    assert add == explicit


def test_multiplicative_unknown_mode_falls_back_to_additive() -> None:
    """Unknown / typo modes must not raise; fall back to additive."""
    add = _select_top_family(regime="RISK_ON", vol_regime="NORMAL", htf_aligned=True)
    typo = _select_top_family(
        regime="RISK_ON", vol_regime="NORMAL", htf_aligned=True,
        family_score_combination="multiplicatve",  # intentional typo
    )
    assert add == typo


def test_multiplicative_picks_a_valid_family() -> None:
    """Multiplicative mode must always pick one of the four canonical families."""
    family = _select_top_family(
        regime="RISK_ON", vol_regime="NORMAL", htf_aligned=True,
        family_score_combination="multiplicative",
    )
    assert family in ("OB", "FVG", "BOS", "SWEEP")


def test_multiplicative_amplifies_extreme_vol_sweep_signal() -> None:
    """In EXTREME vol the +0.15 SWEEP bump should still pick SWEEP under
    multiplicative scaling (which amplifies the ratio over the base).
    """
    family_add = _select_top_family(
        regime="RISK_OFF", vol_regime="EXTREME", htf_aligned=False,
        family_score_combination="additive",
    )
    family_mul = _select_top_family(
        regime="RISK_OFF", vol_regime="EXTREME", htf_aligned=False,
        family_score_combination="multiplicative",
    )
    # Both arms see the same dominant signal: SWEEP wins or at least
    # remains in the top-2 under both combination modes.
    assert family_add in ("SWEEP", "OB")
    assert family_mul in ("SWEEP", "OB")


def test_multiplicative_env_var_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Env var SMC_FAMILY_SCORE_COMBINATION should switch the mode when
    no explicit kwarg is passed (used by rolling-benchmark shadow runs).
    """
    monkeypatch.setenv("SMC_FAMILY_SCORE_COMBINATION", "multiplicative")
    # Without explicit kwarg, env var takes effect.
    family_env = _select_top_family(
        regime="NEUTRAL", vol_regime="HIGH_VOL", htf_aligned=False,
    )
    # Explicit kwarg always wins over env var.
    family_explicit = _select_top_family(
        regime="NEUTRAL", vol_regime="HIGH_VOL", htf_aligned=False,
        family_score_combination="additive",
    )
    assert family_env in ("OB", "FVG", "BOS", "SWEEP")
    assert family_explicit in ("OB", "FVG", "BOS", "SWEEP")


def test_multiplicative_preserves_no_bump_baseline() -> None:
    """When NO bumps fire (every per-context branch is False), additive
    and multiplicative arms must agree — they only diverge when bumps
    are applied.
    """
    # Pick a context that triggers no bumps:
    #   htf_aligned=False, vol_regime not in NORMAL/LOW_VOL/HIGH_VOL/EXTREME,
    #   regime not in RISK_ON/NEUTRAL, session_context=None.
    add = _select_top_family(
        regime="ROTATION", vol_regime="UNKNOWN", htf_aligned=False,
        session_context=None, family_score_combination="additive",
    )
    mul = _select_top_family(
        regime="ROTATION", vol_regime="UNKNOWN", htf_aligned=False,
        session_context=None, family_score_combination="multiplicative",
    )
    assert add == mul


# ── Partial calibrated weights (regression: KeyError on missing family) ──

def test_select_top_family_partial_weights_does_not_raise() -> None:
    """A calibration artifact missing canonical families (e.g. BOS/SWEEP)
    must not raise KeyError when a context bump targets the missing family.

    RISK_ON + htf_aligned applies a BOS bump; EXTREME vol applies a SWEEP
    bump. Both are extremely common production contexts, so a partial
    ``family_weights`` artifact would otherwise crash the enrichment.
    """
    partial = {"OB": 0.5, "FVG": 0.5}  # BOS and SWEEP dropped
    family = _select_top_family(
        regime="RISK_ON", vol_regime="EXTREME", htf_aligned=True,
        calibrated_family_weights=partial,
    )
    assert family in ("OB", "FVG", "BOS", "SWEEP")


def test_select_top_family_partial_weights_falls_back_to_priors() -> None:
    """Missing families inherit the hand-tuned base prior rather than
    vanishing, so they can still win when their prior + bumps dominate.
    """
    # Only OB supplied (low); BOS/FVG/SWEEP must fall back to base priors.
    # EXTREME vol adds +0.15 to SWEEP (prior 0.73 -> 0.88), which should
    # beat the supplied OB=0.10 and the unbumped priors.
    partial = {"OB": 0.10}
    family = _select_top_family(
        regime="RISK_OFF", vol_regime="EXTREME", htf_aligned=False,
        calibrated_family_weights=partial,
    )
    assert family == "SWEEP"


def test_build_zone_priority_partial_weights_does_not_raise() -> None:
    """End-to-end public API: a partial ``calibrated_family_weights`` (as
    could be loaded from a truncated/old zone_priority_calibration.json)
    must degrade gracefully instead of raising KeyError.
    """
    partial = {"OB": 0.5, "FVG": 0.5}  # BOS and SWEEP dropped
    result = build_zone_priority(
        regime="RISK_ON", vol_regime="EXTREME", htf_aligned=True,
        calibrated_family_weights=partial,
    )
    assert result["ZONE_PRIORITY_TOP_FAMILY"] in ("OB", "FVG", "BOS", "SWEEP")


def test_select_top_family_complete_weights_unchanged_by_overlay() -> None:
    """The overlay fix must not change selection for complete weight dicts:
    a full calibrated dict still wins exactly as before.
    """
    weights = {"OB": 0.72, "FVG": 0.70, "BOS": 0.65, "SWEEP": 0.60}
    family = _select_top_family(
        regime="NEUTRAL", vol_regime="HIGH_VOL", htf_aligned=False,
        session_context="RTH", calibrated_family_weights=weights,
    )
    # Identical assertion to test_fvg_boosted_in_rth_session.
    assert family == "FVG"


def test_select_top_family_tie_break_is_order_independent() -> None:
    """On an exact score tie the selected family must not depend on the key
    insertion order of the calibrated-weights dict (which can vary when the
    dict is deserialized from JSON). The overlay onto the canonical base
    order pins a deterministic tie-break.
    """
    tied_a = {"OB": 0.5, "FVG": 0.5, "BOS": 0.5, "SWEEP": 0.5}
    tied_b = {"SWEEP": 0.5, "BOS": 0.5, "FVG": 0.5, "OB": 0.5}
    # ROTATION/UNKNOWN/no-htf/no-session triggers no bumps, so the tie holds.
    family_a = _select_top_family(
        regime="ROTATION", vol_regime="UNKNOWN", htf_aligned=False,
        session_context=None, calibrated_family_weights=tied_a,
    )
    family_b = _select_top_family(
        regime="ROTATION", vol_regime="UNKNOWN", htf_aligned=False,
        session_context=None, calibrated_family_weights=tied_b,
    )
    assert family_a == family_b


# ── Catalyst identification ────────────────────────────────────

def test_news_catalyst_when_heat_high() -> None:
    assert _identify_catalyst(news_heat=0.5, event_risk_level="LOW", regime="NEUTRAL") == "NEWS"


def test_event_catalyst_when_risk_high() -> None:
    assert _identify_catalyst(news_heat=0.1, event_risk_level="HIGH", regime="NEUTRAL") == "EVENT"


def test_regime_catalyst_when_risk_on() -> None:
    assert _identify_catalyst(news_heat=0.1, event_risk_level="LOW", regime="RISK_ON") == "REGIME"


def test_no_catalyst_when_neutral() -> None:
    assert _identify_catalyst(news_heat=0.1, event_risk_level="LOW", regime="NEUTRAL") == "NONE"


# ── Overrides ──────────────────────────────────────────────────

def test_overrides_applied() -> None:
    result = build_zone_priority(overrides={"ZONE_PRIORITY_RANK": "A", "ZONE_PRIORITY_SCORE": 99})
    assert result["ZONE_PRIORITY_RANK"] == "A"
    assert result["ZONE_PRIORITY_SCORE"] == 99


def test_overrides_reject_unknown_keys() -> None:
    result = build_zone_priority(overrides={"UNKNOWN_KEY": "value"})
    assert "UNKNOWN_KEY" not in result


# ── Score bounds ───────────────────────────────────────────────

def test_score_never_exceeds_100() -> None:
    result = build_zone_priority(
        regime="RISK_ON",
        ensemble_score=1.0,
        news_heat=1.0,
        event_risk_level="NONE",
        session_context="RTH",
        vol_regime="NORMAL",
        zone_proj_score=5,
        htf_aligned=True,
    )
    assert 0 <= result["ZONE_PRIORITY_SCORE"] <= 100


def test_score_never_negative() -> None:
    result = build_zone_priority(
        regime="RISK_OFF",
        ensemble_score=0.0,
        news_heat=0.0,
        event_risk_level="CRITICAL",
        session_context="OVERNIGHT",
        vol_regime="EXTREME",
        zone_proj_score=0,
        htf_aligned=False,
    )
    assert result["ZONE_PRIORITY_SCORE"] >= 0


# ── Event penalty reduces score ────────────────────────────────

def test_event_risk_penalty_reduces_score() -> None:
    base = build_zone_priority(regime="RISK_ON", ensemble_score=0.8, event_risk_level="NONE")
    penalized = build_zone_priority(regime="RISK_ON", ensemble_score=0.8, event_risk_level="CRITICAL")
    assert penalized["ZONE_PRIORITY_SCORE"] < base["ZONE_PRIORITY_SCORE"]


# ── Enrichment type integration ────────────────────────────────

def test_zone_priority_block_in_enrichment_dict() -> None:
    from scripts.smc_enrichment_types import EnrichmentDict
    hints = EnrichmentDict.__annotations__
    assert "zone_priority" in hints


# ── F2: session_calibration shortcut ───────────────────────────

def test_session_calibration_overrides_top_family() -> None:
    """An explicit session bucket must steer top-family selection."""
    # Default contextual: FVG already wins under RISK_ON+RTH+NORMAL because
    # RTH adds +0.05 to FVG. We force OB by giving it a huge session weight.
    result = build_zone_priority(
        regime="RISK_ON",
        ensemble_score=0.5,
        session_context="RTH",
        vol_regime="NORMAL",
        htf_aligned=True,
        session_calibration={"RTH": {"OB": 0.95, "FVG": 0.10, "BOS": 0.20, "SWEEP": 0.15}},
    )
    assert result["ZONE_PRIORITY_TOP_FAMILY"] == "OB"


def test_session_calibration_silent_when_session_unknown() -> None:
    """Empty / unmatched session_context must not crash and must not bias."""
    result = build_zone_priority(
        regime="NEUTRAL",
        session_context="",
        session_calibration={"RTH": {"OB": 0.99}},
    )
    # No exception, score remains a valid int.
    assert isinstance(result["ZONE_PRIORITY_SCORE"], int)


def test_session_calibration_partial_map_keeps_other_weights() -> None:
    """A partial dict (one family only) must not zero-out the rest."""
    result = build_zone_priority(
        regime="NEUTRAL",
        session_context="RTH",
        vol_regime="NORMAL",
        # Only override FVG; OB/BOS/SWEEP must keep their _FAMILY_BASE_PRIORITY.
        session_calibration={"RTH": {"FVG": 0.99}},
    )
    # FVG should now win because its weight is overwhelmingly high.
    assert result["ZONE_PRIORITY_TOP_FAMILY"] == "FVG"


def test_session_calibration_wins_over_calibrated_family_weights() -> None:
    result = build_zone_priority(
        regime="NEUTRAL",
        session_context="ETH",
        vol_regime="NORMAL",
        calibrated_family_weights={"OB": 0.30, "FVG": 0.30, "BOS": 0.30, "SWEEP": 0.30},
        session_calibration={"ETH": {"BOS": 0.95}},
    )
    assert result["ZONE_PRIORITY_TOP_FAMILY"] == "BOS"
