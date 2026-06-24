"""Tests for smc_core.smc_confluence (Phase D — OB/FVG/Sweep Confluence).

Covers:
- ``compute_confluence`` returns ``NONE`` tier when all inputs absent / below threshold
- Single active family → ``LOW`` tier
- Two active families → at least ``MEDIUM`` tier
- Three active families → ``HIGH`` tier (with sufficient individual scores)
- ``raw_confluence_score`` is bounded 0.0–1.0
- Geometric-mean logic: lower individual scores → lower interaction
- Anti-double-count: passing same evidence for all three families still
  stays within budget (no scores > 1.0)
- ``ConfluenceScore`` is immutable (frozen dataclass)
- Passing ``None`` for all inputs is safe (returns ``NONE``)
"""

from __future__ import annotations

import pytest

from smc_core.smc_confluence import (
    FVG_ACTIVE_THRESHOLD,
    OB_ACTIVE_THRESHOLD,
    SWEEP_ACTIVE_THRESHOLD,
    ConfluenceScore,
    ConfluenceTier,
    compute_confluence,
)


# ---------------------------------------------------------------------------
# Helpers — build minimal light dicts in the format measurement_evidence uses
# ---------------------------------------------------------------------------


def _ob(score_15: float) -> dict:
    """OB context light dict; score_15 is in 0–15 range (matches MAX_OB)."""
    return {"OB_SUPPORT_SCORE": score_15}


def _fvg(score_15: float) -> dict:
    """FVG lifecycle light dict; score_15 in 0–15 range."""
    return {"FVG_GAP_SCORE": score_15}


def _sweep(score_01: float) -> dict:
    """Liquidity sweeps dict; score_01 already 0.0–1.0."""
    return {"SWEEP_TRAP_QUALITY_SCORE": score_01}


# ---------------------------------------------------------------------------
# Tier assignment
# ---------------------------------------------------------------------------


class TestTierAssignment:
    def test_none_tier_all_absent(self) -> None:
        result = compute_confluence(None, None, None)
        assert result.confluence_tier == "NONE"
        assert result.raw_confluence_score == pytest.approx(0.0)

    def test_none_tier_all_below_threshold(self) -> None:
        # Scores just below their thresholds
        ob_below = _ob(OB_ACTIVE_THRESHOLD * 15 * 0.9)
        fvg_below = _fvg(FVG_ACTIVE_THRESHOLD * 15 * 0.9)
        sweep_below = _sweep(SWEEP_ACTIVE_THRESHOLD * 0.9)
        result = compute_confluence(ob_below, fvg_below, sweep_below)
        assert result.confluence_tier in ("NONE", "LOW")

    def test_single_active_family_gives_low_tier(self) -> None:
        result = compute_confluence(_ob(15.0), None, None)
        assert result.confluence_tier == "LOW"

    def test_two_active_families_gives_at_least_medium(self) -> None:
        result = compute_confluence(_ob(15.0), _fvg(15.0), None)
        assert result.confluence_tier in ("MEDIUM", "HIGH")

    def test_three_active_high_scores_gives_high_tier(self) -> None:
        result = compute_confluence(_ob(15.0), _fvg(15.0), _sweep(1.0))
        assert result.confluence_tier == "HIGH"

    def test_three_active_moderate_scores_gives_medium(self) -> None:
        # OB and FVG at 40% of 15 = 6, sweep at threshold
        result = compute_confluence(
            _ob(6.0), _fvg(6.0), _sweep(SWEEP_ACTIVE_THRESHOLD + 0.05)
        )
        assert result.confluence_tier in ("LOW", "MEDIUM")


# ---------------------------------------------------------------------------
# Score bounds and properties
# ---------------------------------------------------------------------------


class TestScoreBounds:
    def test_raw_score_bounded_0_1(self) -> None:
        for ob_s in [0, 6, 15]:
            for fvg_s in [0, 6, 15]:
                for sw_s in [0.0, 0.5, 1.0]:
                    result = compute_confluence(_ob(ob_s), _fvg(fvg_s), _sweep(sw_s))
                    assert 0.0 <= result.raw_confluence_score <= 1.0

    def test_contributions_bounded_0_1(self) -> None:
        result = compute_confluence(_ob(15.0), _fvg(15.0), _sweep(1.0))
        assert 0.0 <= result.ob_contribution <= 1.0
        assert 0.0 <= result.fvg_contribution <= 1.0
        assert 0.0 <= result.sweep_contribution <= 1.0

    def test_higher_individual_scores_give_higher_confluence(self) -> None:
        low = compute_confluence(_ob(6.0), _fvg(6.0), _sweep(0.4))
        high = compute_confluence(_ob(15.0), _fvg(15.0), _sweep(1.0))
        assert high.raw_confluence_score >= low.raw_confluence_score

    def test_below_threshold_family_excluded_from_interaction(self) -> None:
        """A family below its threshold is excluded from the geometric-mean
        interaction. FVG at 1/10 of threshold should behave like no FVG."""
        fvg_low = compute_confluence(_ob(15.0), _fvg(1.0), _sweep(1.0))
        fvg_none = compute_confluence(_ob(15.0), None, _sweep(1.0))
        assert fvg_low.raw_confluence_score == pytest.approx(
            fvg_none.raw_confluence_score, abs=1e-9
        )

    def test_tri_family_bonus_exceeds_bi_family_at_max_scores(self) -> None:
        """Three active families score higher than two at max individual scores
        due to the 1.2× tri-family bonus."""
        two_family = compute_confluence(_ob(15.0), None, _sweep(1.0))
        three_family = compute_confluence(_ob(15.0), _fvg(15.0), _sweep(1.0))
        assert three_family.raw_confluence_score >= two_family.raw_confluence_score

    def test_sweep_trap_quality_score_preferred_over_sweep_quality(self) -> None:
        """SWEEP_TRAP_QUALITY_SCORE takes priority when present."""
        with_trap = {"SWEEP_TRAP_QUALITY_SCORE": 1.0, "SWEEP_QUALITY_SCORE": 0.1}
        without_trap = {"SWEEP_QUALITY_SCORE": 1.0}
        r_trap = compute_confluence(_ob(15.0), _fvg(15.0), with_trap)
        r_plain = compute_confluence(_ob(15.0), _fvg(15.0), without_trap)
        # Trap quality 1.0 should dominate → similar high scores in both cases
        assert r_trap.sweep_contribution == pytest.approx(1.0)
        assert r_plain.sweep_contribution == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_confluence_score_is_frozen() -> None:
    result = compute_confluence(None, None, None)
    with pytest.raises((AttributeError, TypeError)):
        result.confluence_tier = "HIGH"  # type: ignore[misc]
