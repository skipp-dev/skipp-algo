from __future__ import annotations

import pytest

from open_prep.pre_a0_enrichment import (
    AblationMetrics,
    AuctionSample,
    EnrichmentFamily,
    MicrostructureSample,
    TimedFeature,
    VolumeProfile,
    WarmSet,
    decide_advanced_workstream,
    evaluate_ablation,
    microstructure_features,
)


def test_all_enrichments_are_timestamp_bounded_and_auction_is_isolated() -> None:
    with pytest.raises(ValueError, match="future"):
        TimedFeature(EnrichmentFamily.NEWS, "news", 1, 11, 10, "test").validate_for(10)
    profile = VolumeProfile("p1", "2026-07-01", ((0, 0.02), (30, 0.25)))
    assert profile.expected_fraction(30, session_date="2026-07-02") == 0.25
    with pytest.raises(ValueError, match="historical"):
        profile.expected_fraction(30, session_date="2026-07-01")
    auction = AuctionSample(10, 10, 101, 10_000, 2_000)
    with pytest.raises(ValueError, match="opening"):
        auction.features(prediction_time=10, opening_window=False)


def test_microstructure_is_bounded_to_warm_set_and_prediction_time() -> None:
    warm = WarmSet(max_symbols=2, ttl_s=10)
    warm.touch("AAA", now=1)
    warm.touch("BBB", now=2)
    assert warm.touch("CCC", now=3) == ("AAA",)
    assert warm.contains("AAA") is False
    assert warm.expire(now=20) == ("BBB", "CCC")
    sample = MicrostructureSample("XYZ", 5, 6, 100, 100.1, 60, 40, 10, 4, 20)
    features = microstructure_features(sample, prediction_time=6)
    assert {feature.name for feature in features} == {
        "spread",
        "size_imbalance",
        "microprice",
        "order_flow_imbalance",
        "event_rate",
    }


def test_ablation_promotes_only_incremental_stable_gain() -> None:
    baseline = AblationMetrics(0.40, 0.20, 0.05, 45, 0.01, 0.9)
    candidate = AblationMetrics(0.43, 0.18, 0.04, 47, 0.03, 0.9)
    assert evaluate_ablation(EnrichmentFamily.VOLUME_PROFILE, baseline, candidate).promote is True
    regression = AblationMetrics(0.43, 0.18, 0.08, 47, 0.03, 0.9)
    decision = evaluate_ablation(EnrichmentFamily.NEWS, baseline, regression)
    assert decision.promote is False
    assert "calibration_regression" in decision.reasons
    assert decide_advanced_workstream(
        remaining_error_cluster=False, sufficient_samples=True, justified_cost=True
    )["decision"] == "stop"
