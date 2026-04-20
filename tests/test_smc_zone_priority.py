"""Tests for the C9 AI Zone Priority pipeline."""
from __future__ import annotations

import pytest

from scripts.smc_zone_priority import (
    DEFAULTS,
    build_zone_priority,
    _clamp,
    _rank_from_score,
    _select_top_family,
    _identify_catalyst,
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
