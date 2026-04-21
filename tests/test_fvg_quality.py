"""Tests for ``smc_core.fvg_quality`` (Plan §2.1 D4 scaffold)."""

from __future__ import annotations

import math

import pytest

from smc_core.fvg_quality import (
    FvgQualityScore,
    rolling_hurst,
    score_events,
    score_fvg,
)


class TestScoreFvg:
    def test_empty_event_lands_in_low_tier_with_bounded_score(self) -> None:
        # With no features set we must still return a valid score in
        # [0, 1] and never explode — the score is only pinned to a
        # *bounded* value, not a specific number, so the weights can
        # be retuned in D4 without breaking the test.
        result = score_fvg({})
        assert 0.0 <= result.score <= 1.0
        assert result.tier in {"LOW", "MEDIUM", "HIGH"}
        assert 0.5 <= result.multiplier <= 1.5

    def test_all_features_maxed_reaches_high_tier(self) -> None:
        result = score_fvg(
            {
                "gap_size_atr": 3.0,
                "htf_aligned": True,
                "distance_to_price_atr": 0.0,
                "is_full_body": True,
                "hurst": 0.9,
            }
        )
        assert result.tier == "HIGH"
        assert result.score >= 0.70
        assert result.multiplier >= 1.0

    def test_worst_case_event_stays_in_low_tier(self) -> None:
        result = score_fvg(
            {
                "gap_size_atr": 0.1,
                "htf_aligned": False,
                "distance_to_price_atr": 10.0,
                "is_full_body": False,
                "hurst": 0.1,
            }
        )
        assert result.tier == "LOW"
        assert result.score < 0.50
        assert result.multiplier < 1.0

    def test_missing_hurst_is_treated_as_neutral_not_zero(self) -> None:
        with_hurst = score_fvg(
            {"gap_size_atr": 1.0, "htf_aligned": True, "distance_to_price_atr": 1.0, "is_full_body": True, "hurst": 0.5}
        )
        without_hurst = score_fvg(
            {"gap_size_atr": 1.0, "htf_aligned": True, "distance_to_price_atr": 1.0, "is_full_body": True}
        )
        # A missing Hurst must produce the same score as a neutral
        # 0.5 Hurst — otherwise absent data would silently penalise
        # the event.
        assert with_hurst.score == without_hurst.score

    def test_components_sum_weighted_to_score(self) -> None:
        event = {
            "gap_size_atr": 1.5,
            "htf_aligned": True,
            "distance_to_price_atr": 0.5,
            "is_full_body": True,
            "hurst": 0.6,
        }
        result = score_fvg(event)
        weighted = (
            0.30 * result.components["gap_size"]
            + 0.25 * result.components["htf_aligned"]
            + 0.15 * result.components["distance"]
            + 0.10 * result.components["full_body"]
            + 0.20 * result.components["hurst"]
        )
        assert math.isclose(result.score, round(weighted, 4), abs_tol=1e-4)

    def test_invalid_hurst_string_is_ignored_not_raised(self) -> None:
        # Upstream data can sometimes ship a string; never crash.
        result = score_fvg({"hurst": "nan"})
        assert 0.0 <= result.score <= 1.0

    def test_score_events_preserves_input_order(self) -> None:
        events = [
            {"gap_size_atr": 0.1},
            {"gap_size_atr": 3.0, "htf_aligned": True, "hurst": 0.8},
            {"gap_size_atr": 1.0, "htf_aligned": True},
        ]
        scored = score_events(events)
        assert len(scored) == 3
        assert all(isinstance(s, FvgQualityScore) for s in scored)
        # The high-quality event must score higher than the low-quality one.
        assert scored[1].score > scored[0].score


class TestRollingHurst:
    def test_short_series_returns_none(self) -> None:
        assert rolling_hurst([1.0] * 5) is None

    def test_flat_series_returns_none(self) -> None:
        assert rolling_hurst([100.0] * 32) is None

    def test_noise_series_is_around_neutral(self) -> None:
        # Alternating up/down → anti-persistent, H should be well
        # below 0.5 but still in [0, 1].
        closes = [100.0 + (0.5 if i % 2 == 0 else -0.5) for i in range(64)]
        h = rolling_hurst(closes)
        assert h is not None
        assert 0.0 <= h <= 1.0
        assert h < 0.5

    def test_strong_trend_raises_hurst_above_noise(self) -> None:
        noise = [100.0 + (0.5 if i % 2 == 0 else -0.5) for i in range(64)]
        trend = [100.0 + i * 0.25 for i in range(64)]
        h_noise = rolling_hurst(noise)
        h_trend = rolling_hurst(trend)
        assert h_noise is not None and h_trend is not None
        assert h_trend > h_noise, "persistent trend must score above anti-persistent noise"
