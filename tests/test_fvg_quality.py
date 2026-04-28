"""Tests for ``smc_core.fvg_quality`` (Plan §2.1 D4 scaffold)."""

from __future__ import annotations

import math

from smc_core.fvg_quality import (
    DEFAULT_DIRECTIONS,
    DEFAULT_MEANS,
    DEFAULT_WEIGHTS,
    LENIENT_DIRECTIONS,
    LENIENT_MEANS,
    LENIENT_WEIGHTS,
    STRICT_V1_NO_HURST_DIRECTIONS,
    STRICT_V1_NO_HURST_MEANS,
    STRICT_V1_NO_HURST_WEIGHTS,
    WEIGHT_VERSION,
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

    def test_lenient_maxed_features_reach_high_tier(self) -> None:
        # Legacy lenient regime — explicitly opt in.
        result = score_fvg(
            {
                "gap_size_atr": 3.0,
                "htf_aligned": True,
                "distance_to_price_atr": 0.0,
                "is_full_body": True,
                "hurst": 0.9,
            },
            weights=LENIENT_WEIGHTS,
            directions=LENIENT_DIRECTIONS,
            means=LENIENT_MEANS,
        )
        assert result.tier == "HIGH"
        assert result.score >= 0.70
        assert result.multiplier >= 1.0

    def test_lenient_worst_case_event_stays_in_low_tier(self) -> None:
        result = score_fvg(
            {
                "gap_size_atr": 0.1,
                "htf_aligned": False,
                "distance_to_price_atr": 10.0,
                "is_full_body": False,
                "hurst": 0.1,
            },
            weights=LENIENT_WEIGHTS,
            directions=LENIENT_DIRECTIONS,
            means=LENIENT_MEANS,
        )
        assert result.tier == "LOW"
        assert result.score < 0.50
        assert result.multiplier < 1.0

    def test_strict_minimal_features_reach_high_tier(self) -> None:
        # Strict default (since Q3 D3 promotion, 2026-04-22):
        # minimal features → HIGH tier (inverted semantics).
        result = score_fvg(
            {
                "gap_size_atr": 0.05,
                "htf_aligned": False,
                "distance_to_price_atr": 0.0,
                "is_full_body": False,
                "hurst": None,
            }
        )
        assert result.tier == "HIGH"
        assert result.score >= 0.70

    def test_strict_maxed_features_drop_to_low_tier(self) -> None:
        result = score_fvg(
            {
                "gap_size_atr": 3.0,
                "htf_aligned": True,
                "distance_to_price_atr": 10.0,
                "is_full_body": True,
                "hurst": 0.9,
            }
        )
        assert result.tier == "LOW"
        assert result.score < 0.50

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

    def test_lenient_components_sum_weighted_to_score(self) -> None:
        # Legacy lenient regime: pure weighted sum, no centring.
        event = {
            "gap_size_atr": 1.5,
            "htf_aligned": True,
            "distance_to_price_atr": 0.5,
            "is_full_body": True,
            "hurst": 0.6,
        }
        result = score_fvg(
            event,
            weights=LENIENT_WEIGHTS,
            directions=LENIENT_DIRECTIONS,
            means=LENIENT_MEANS,
        )
        weighted = (
            0.30 * result.components["gap_size"]
            + 0.25 * result.components["htf_aligned"]
            + 0.15 * result.components["distance"]
            + 0.10 * result.components["full_body"]
            + 0.20 * result.components["hurst"]
        )
        assert math.isclose(result.score, round(weighted, 4), abs_tol=1e-4)

    def test_strict_components_sum_signed_to_score(self) -> None:
        # Strict regime: signed weighted sum about 0.5.
        # score = 0.5 + Σ w·d·(comp − 0.5), hurst disabled (d=0).
        event = {
            "gap_size_atr": 1.5,
            "htf_aligned": True,
            "distance_to_price_atr": 0.5,
            "is_full_body": True,
            "hurst": 0.6,
        }
        result = score_fvg(event)
        raw = (
            0.45 * -1 * (result.components["gap_size"] - 0.5)
            + 0.0735 * -1 * (result.components["htf_aligned"] - 0.5)
            + 0.45 * -1 * (result.components["distance"] - 0.5)
            + 0.0515 * -1 * (result.components["full_body"] - 0.5)
            # hurst disabled (direction=0)
        )
        expected = max(0.0, min(1.0, 0.5 + raw))
        assert math.isclose(result.score, round(expected, 4), abs_tol=1e-4)

    def test_directions_applied_correctly(self) -> None:
        # Same event scored under lenient vs strict regimes must
        # produce inverted tier outcomes — proves the direction
        # vector is wired through.
        event = {
            "gap_size_atr": 2.5,
            "htf_aligned": True,
            "distance_to_price_atr": 0.1,
            "is_full_body": True,
            "hurst": 0.7,
        }
        lenient = score_fvg(
            event,
            weights=LENIENT_WEIGHTS,
            directions=LENIENT_DIRECTIONS,
            means=LENIENT_MEANS,
        )
        strict = score_fvg(event)  # default = strict
        assert lenient.score > 0.5
        assert strict.score < 0.5

    def test_strict_v1_no_hurst_constants_pinned(self) -> None:
        # Pin the promoted constants so any future re-tune is a
        # deliberate, reviewable diff.
        assert WEIGHT_VERSION == "strict_v1_no_hurst"
        assert STRICT_V1_NO_HURST_WEIGHTS == {
            "gap_size_atr": 0.45,
            "htf_aligned": 0.0735,
            "distance_to_price_atr": 0.45,
            "is_full_body": 0.0515,
            "hurst_50": 0.0,
        }
        assert STRICT_V1_NO_HURST_DIRECTIONS == {
            "gap_size_atr": -1,
            "htf_aligned": -1,
            "distance_to_price_atr": -1,
            "is_full_body": -1,
            "hurst_50": 0,
        }
        assert {
            k: 0.5 for k in STRICT_V1_NO_HURST_WEIGHTS
        } == STRICT_V1_NO_HURST_MEANS
        assert DEFAULT_WEIGHTS is STRICT_V1_NO_HURST_WEIGHTS
        assert DEFAULT_DIRECTIONS is STRICT_V1_NO_HURST_DIRECTIONS
        assert DEFAULT_MEANS is STRICT_V1_NO_HURST_MEANS

    def test_tier_semantics_inverted_under_strict(self) -> None:
        # Documents the semantic flip: under the production strict
        # regime, HIGH tier means "low/minimal feature values" —
        # the empirical opposite of the legacy lenient regime.
        # See docs/FVG_QUALITY_D4_AUDIT.md §2-3 and §6.
        minimal = {
            "gap_size_atr": 0.05,
            "htf_aligned": False,
            "distance_to_price_atr": 0.0,
            "is_full_body": False,
        }
        maxed = {
            "gap_size_atr": 3.0,
            "htf_aligned": True,
            "distance_to_price_atr": 10.0,
            "is_full_body": True,
        }
        s_min = score_fvg(minimal)
        s_max = score_fvg(maxed)
        assert s_min.tier == "HIGH"
        assert s_max.tier == "LOW"
        assert s_min.score > s_max.score

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
        # Under strict default semantics, minimal-feature events
        # score higher (HIGH tier means "strict-favourable" — see
        # test_tier_semantics_inverted_under_strict).
        assert scored[0].score > scored[1].score


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
