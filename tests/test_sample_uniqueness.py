"""Tests for the Lopez de Prado ch.4 sample-uniqueness / ESS primitives."""

from __future__ import annotations

import pytest

from governance.sample_uniqueness import (
    WEIGHTS_TAG,
    average_uniqueness,
    effective_sample_size,
    sample_weights,
    time_decay,
)


# --------------------------------------------------------------------------- #
# average_uniqueness                                                          #
# --------------------------------------------------------------------------- #
def test_isolated_spans_are_fully_unique() -> None:
    # No overlap anywhere -> every label scores exactly 1.0.
    starts = [0.0, 10.0, 20.0]
    ends = [1.0, 11.0, 21.0]
    assert average_uniqueness(starts, ends) == [1.0, 1.0, 1.0]


def test_two_identical_spans_split_uniqueness() -> None:
    u = average_uniqueness([0.0, 0.0], [2.0, 2.0])
    assert u == [0.5, 0.5]


def test_three_identical_spans_split_uniqueness() -> None:
    u = average_uniqueness([5.0, 5.0, 5.0], [9.0, 9.0, 9.0])
    assert u == pytest.approx([1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0])


def test_partial_overlap_exact_value() -> None:
    # A=[0,2], B=[1,3]: concurrency is 1 on [0,1), 2 on [1,2), 1 on [2,3).
    # A integral = 1*1 + 1*0.5 = 1.5 over length 2 -> 0.75; B symmetric.
    u = average_uniqueness([0.0, 1.0], [2.0, 3.0])
    assert u == pytest.approx([0.75, 0.75])


def test_nested_span_is_more_unique_than_the_pair_inside() -> None:
    # Outer [0,4] overlaps two short inner spans [1,2] and [2,3].
    # Outer: [0,1) c1, [1,2) c2, [2,3) c2, [3,4) c1 -> (1+.5+.5+1)/4 = 0.75.
    # Each inner is fully covered while c=2 -> 0.5.
    u = average_uniqueness([0.0, 1.0, 2.0], [4.0, 2.0, 3.0])
    assert u == pytest.approx([0.75, 0.5, 0.5])


def test_empty_input_returns_empty() -> None:
    assert average_uniqueness([], []) == []


def test_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        average_uniqueness([0.0, 1.0], [1.0])


def test_non_positive_lifespan_raises() -> None:
    with pytest.raises(ValueError, match="non-positive label lifespan"):
        average_uniqueness([0.0, 5.0], [1.0, 5.0])  # second span has end == start


# --------------------------------------------------------------------------- #
# time_decay                                                                  #
# --------------------------------------------------------------------------- #
def test_time_decay_disabled_when_last_weight_one() -> None:
    factors = time_decay([0.0, 1.0, 2.0], [1.0, 1.0, 1.0], last_weight=1.0)
    assert factors == [1.0, 1.0, 1.0]


def test_time_decay_newest_is_one_oldest_is_floor() -> None:
    # Equal uniqueness -> cumulative [1,2,3], total 3, last_weight 0:
    # factors map to [1/3, 2/3, 1.0] in chronological order.
    factors = time_decay([0.0, 1.0, 2.0], [1.0, 1.0, 1.0], last_weight=0.0)
    assert factors == pytest.approx([1.0 / 3.0, 2.0 / 3.0, 1.0])


def test_time_decay_respects_unsorted_anchor_order() -> None:
    # Newest anchor (2.0) is at index 0 -> it must receive factor 1.0.
    factors = time_decay([2.0, 0.0, 1.0], [1.0, 1.0, 1.0], last_weight=0.0)
    assert factors[0] == pytest.approx(1.0)
    assert factors[1] == pytest.approx(1.0 / 3.0)
    assert factors[2] == pytest.approx(2.0 / 3.0)


def test_time_decay_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        time_decay([0.0, 1.0], [1.0])


def test_time_decay_rejects_out_of_range_last_weight() -> None:
    with pytest.raises(ValueError, match="last_weight"):
        time_decay([0.0], [1.0], last_weight=1.5)


# --------------------------------------------------------------------------- #
# effective_sample_size                                                       #
# --------------------------------------------------------------------------- #
def test_ess_equals_n_for_equal_weights() -> None:
    assert effective_sample_size([1.0, 1.0, 1.0, 1.0]) == pytest.approx(4.0)


def test_ess_collapses_when_weight_is_concentrated() -> None:
    # All mass on one observation -> the sample is worth one point.
    assert effective_sample_size([2.0, 0.0, 0.0, 0.0]) == pytest.approx(1.0)


def test_ess_empty_and_all_zero_are_zero() -> None:
    assert effective_sample_size([]) == 0.0
    assert effective_sample_size([0.0, 0.0]) == 0.0


def test_ess_rejects_negative_weight() -> None:
    with pytest.raises(ValueError, match="negative weight"):
        effective_sample_size([1.0, -0.5])


def test_overlapping_sample_has_ess_below_raw_count() -> None:
    # Two isolated + two fully-overlapping spans: raw n = 4 but the redundant
    # pair must drag the effective sample size strictly below 4.
    starts = [0.0, 10.0, 20.0, 20.0]
    ends = [1.0, 11.0, 21.0, 21.0]
    weights = average_uniqueness(starts, ends)
    ess = effective_sample_size(weights)
    assert ess < 4.0
    assert ess == pytest.approx((sum(weights) ** 2) / sum(w * w for w in weights))


# --------------------------------------------------------------------------- #
# sample_weights                                                              #
# --------------------------------------------------------------------------- #
def test_sample_weights_normalise_to_mean_one() -> None:
    starts = [0.0, 1.0, 20.0]
    ends = [2.0, 3.0, 21.0]
    anchor = [0.0, 1.0, 20.0]
    weights = sample_weights(starts, ends, anchor)
    assert sum(weights) == pytest.approx(len(weights))


def test_sample_weights_unnormalised_equals_uniqueness_without_decay() -> None:
    starts = [0.0, 1.0]
    ends = [2.0, 3.0]
    anchor = [0.0, 1.0]
    weights = sample_weights(starts, ends, anchor, normalise=False)
    assert weights == pytest.approx(average_uniqueness(starts, ends))


def test_sample_weights_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        sample_weights([0.0, 1.0], [1.0, 2.0], [0.0])


# --------------------------------------------------------------------------- #
# provenance                                                                  #
# --------------------------------------------------------------------------- #
def test_weights_tag_is_versioned_string() -> None:
    assert isinstance(WEIGHTS_TAG, str)
    assert WEIGHTS_TAG.endswith("_v1")
