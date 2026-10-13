from __future__ import annotations

from open_prep.a0_contract import A0ThresholdContext, build_market_snapshot
from open_prep.pre_a0 import (
    PreA0Machine,
    PreA0Observation,
    PreA0State,
    build_pre_a0_features,
)
from open_prep.pre_a0_outcomes import (
    ConfirmedA0,
    PreA0Outcome,
    evaluate_outcomes,
    summarize_outcomes,
)

THRESHOLDS = A0ThresholdContext(4.0, 2.0, 1.2, 3.0, 1.5, 0.8)


def _observation(second: int, *, progress: float, direction: int = 1) -> PreA0Observation:
    change = direction * 3.0 * progress
    market = build_market_snapshot(
        symbol="XYZ",
        price=100 * (1 + change / 100),
        prev_close=100,
        change_pct=change,
        raw_daily_volume_ratio=0.2 * progress,
        expected_volume_fraction=0.05,
        normalized_volume_pace=4.0 * progress,
        source="databento-live",
        raw_ts_event=1_800_000_000 + second,
        raw_ts_recv=1_800_000_000 + second + 0.05,
        observed_at=1_800_000_000 + second + 0.05,
    )
    return PreA0Observation(market, cumulative_volume=10_000 + second * 1_000)


def test_features_and_eta_are_trailing_deterministic() -> None:
    history = [_observation(second, progress=0.45 + second * 0.02) for second in range(21)]
    features = build_pre_a0_features(history, THRESHOLDS)
    estimate = PreA0Machine().evaluate(features)
    assert features.price_progress == features.volume_progress
    assert features.incremental_volume_rates[-1][1] == 1_000
    assert estimate.state is PreA0State.IMMINENT
    assert estimate.eta_low_s is not None
    assert estimate.eta_high_s is not None
    payload = estimate.to_operator_payload()
    assert payload["kind"] == "PRE_A0"
    assert payload["level"] is None
    assert payload["confirmed"] is False
    assert payload["is_calibrated"] is False
    assert "probability" not in payload


def test_eta_requires_both_axes_and_gap_complete() -> None:
    flat_volume = [_observation(second, progress=0.8) for second in range(20)]
    estimate = PreA0Machine().evaluate(build_pre_a0_features(flat_volume, THRESHOLDS))
    assert estimate.eta_high_s is None
    assert estimate.state is PreA0State.WATCH

    broken = list(flat_volume)
    broken[-1] = PreA0Observation(broken[-1].market, 20_000, gap_complete=False)
    estimate = PreA0Machine().evaluate(build_pre_a0_features(broken, THRESHOLDS))
    assert estimate.state is PreA0State.NONE


def test_reversal_resets_state_and_outcomes_are_horizon_bounded() -> None:
    machine = PreA0Machine()
    first = machine.evaluate(
        build_pre_a0_features(
            [_observation(second, progress=0.5 + second * 0.02) for second in range(20)],
            THRESHOLDS,
        )
    )
    reversed_estimate = machine.evaluate(
        build_pre_a0_features(
            [_observation(second, progress=0.5 + second * 0.02, direction=-1) for second in range(20, 40)],
            THRESHOLDS,
        )
    )
    assert reversed_estimate.state is PreA0State.NONE
    event = ConfirmedA0("XYZ", first.features.observed_at + 45, "up")
    outcomes = evaluate_outcomes([first], [event])
    assert outcomes[0].y_30 is False
    assert outcomes[0].y_60 is True
    assert outcomes[0].y_180 is True
    report = summarize_outcomes(outcomes, session_seconds=3600, eligible_a0_by_horizon={60: 1})
    assert report["precision_60"] == 1.0
    assert report["alerts_per_hour"] == 1.0
    assert report["recall_60"] == 1.0


def test_repeat_alerts_count_ignores_lead_time() -> None:
    # Three (AAA, up) episodes with distinct lead times must collapse to one
    # distinct pair -> two repeats; the pre-fix key included time_to_a0_s, so
    # every row looked unique and repeat_alerts under-counted to zero.
    outcomes = [
        PreA0Outcome("d1", "AAA", "up", True, True, True, 10.0, None),
        PreA0Outcome("d2", "AAA", "up", True, True, True, 20.0, None),
        PreA0Outcome("d3", "AAA", "up", True, True, True, 30.0, None),
        PreA0Outcome("d4", "BBB", "down", False, False, True, 90.0, None),
    ]
    report = summarize_outcomes(outcomes, session_seconds=3600)
    assert report["repeat_alerts"] == 2
