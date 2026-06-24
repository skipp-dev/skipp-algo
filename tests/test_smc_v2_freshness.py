"""Tests for smc_core.event_freshness (Phase A — uniform freshness state).

Covers:
- ``classify_freshness`` bucket assignment for all five buckets
- ``freshness_decay_multiplier`` return values
- Hard invalidation gate overrides age classification
- Mitigated events always classify as ``mitigated``, not by age
- ``FreshnessState`` is immutable (frozen dataclass)
- Edge cases: age_bars == 0, boundary values for FRESH/AGING/STALE thresholds
"""

from __future__ import annotations

import pytest

from smc_core.event_freshness import (
    AGING_BARS,
    FRESH_BARS,
    STALE_BARS,
    classify_freshness,
    freshness_decay_multiplier,
)

# ---------------------------------------------------------------------------
# classify_freshness — bucket assignment
# ---------------------------------------------------------------------------


class TestBucketAssignment:
    def test_age_zero_is_fresh(self) -> None:
        state = classify_freshness(0, mitigated=False)
        assert state.freshness_bucket == "fresh"

    def test_age_at_fresh_threshold_is_fresh(self) -> None:
        state = classify_freshness(FRESH_BARS, mitigated=False)
        assert state.freshness_bucket == "fresh"

    def test_age_just_above_fresh_threshold_is_aging(self) -> None:
        state = classify_freshness(FRESH_BARS + 1, mitigated=False)
        assert state.freshness_bucket == "aging"

    def test_age_at_aging_threshold_is_aging(self) -> None:
        state = classify_freshness(AGING_BARS, mitigated=False)
        assert state.freshness_bucket == "aging"

    def test_age_just_above_aging_threshold_is_stale(self) -> None:
        state = classify_freshness(AGING_BARS + 1, mitigated=False)
        assert state.freshness_bucket == "stale"

    def test_age_well_above_stale_threshold_is_stale(self) -> None:
        state = classify_freshness(STALE_BARS + 100, mitigated=False)
        assert state.freshness_bucket == "stale"

    def test_mitigated_overrides_age_classification(self) -> None:
        """Even a brand-new event should be 'mitigated' if mitigated=True."""
        state = classify_freshness(0, mitigated=True, mitigated_ts=1_700_000_000.0)
        assert state.freshness_bucket == "mitigated"

    def test_invalidated_overrides_young_event(self) -> None:
        state = classify_freshness(1, mitigated=False, invalidated=True)
        assert state.freshness_bucket == "invalidated"

    def test_invalidated_overrides_mitigated(self) -> None:
        """invalidated takes precedence over mitigated."""
        state = classify_freshness(
            5, mitigated=True, invalidated=True, invalidated_ts=1_700_000_001.0
        )
        assert state.freshness_bucket == "invalidated"


# ---------------------------------------------------------------------------
# classify_freshness — field values
# ---------------------------------------------------------------------------


class TestFieldValues:
    def test_event_age_bars_stored(self) -> None:
        state = classify_freshness(7, mitigated=False)
        assert state.event_age_bars == 7

    def test_event_age_seconds_computed_from_bar_seconds(self) -> None:
        state = classify_freshness(3, mitigated=False, bar_seconds=300.0)
        assert state.event_age_seconds == pytest.approx(900.0)

    def test_default_bar_seconds_is_60(self) -> None:
        state = classify_freshness(5, mitigated=False)
        assert state.event_age_seconds == pytest.approx(300.0)

    def test_mitigated_at_stored(self) -> None:
        ts = 1_700_000_000.0
        state = classify_freshness(10, mitigated=True, mitigated_ts=ts)
        assert state.mitigated_at == pytest.approx(ts)

    def test_invalidated_at_stored(self) -> None:
        ts = 1_700_000_042.0
        state = classify_freshness(3, mitigated=False, invalidated=True, invalidated_ts=ts)
        assert state.invalidated_at == pytest.approx(ts)

    def test_invalidated_at_none_for_fresh(self) -> None:
        state = classify_freshness(2, mitigated=False)
        assert state.invalidated_at is None
        assert state.mitigated_at is None

    def test_negative_age_raises(self) -> None:
        with pytest.raises(ValueError, match="age_bars must be"):
            classify_freshness(-1, mitigated=False)


# ---------------------------------------------------------------------------
# freshness_decay_multiplier
# ---------------------------------------------------------------------------


class TestDecayMultiplier:
    @pytest.mark.parametrize(
        "bucket,expected_penalty",
        [
            ("fresh", 1.00),
            ("aging", 0.85),
            ("stale", 0.60),
            ("mitigated", 0.40),
            ("invalidated", 0.00),
        ],
    )
    def test_multiplier_matches_bucket(self, bucket: str, expected_penalty: float) -> None:
        if bucket == "invalidated":
            state = classify_freshness(1, mitigated=False, invalidated=True)
        elif bucket == "mitigated":
            state = classify_freshness(1, mitigated=True)
        elif bucket == "fresh":
            state = classify_freshness(FRESH_BARS, mitigated=False)
        elif bucket == "aging":
            state = classify_freshness(FRESH_BARS + 1, mitigated=False)
        else:  # stale
            state = classify_freshness(AGING_BARS + 1, mitigated=False)
        assert freshness_decay_multiplier(state) == pytest.approx(expected_penalty)

    def test_multiplier_range_is_0_to_1(self) -> None:
        for age in [0, 5, 20, 50, 500]:
            state = classify_freshness(age, mitigated=False)
            assert 0.0 <= freshness_decay_multiplier(state) <= 1.0


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_freshness_state_is_frozen() -> None:
    state = classify_freshness(3, mitigated=False)
    with pytest.raises((AttributeError, TypeError)):
        state.freshness_bucket = "stale"  # type: ignore[misc]
