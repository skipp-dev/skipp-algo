from __future__ import annotations

from smc_core.ensemble_quality import build_ensemble_quality, serialize_ensemble_quality
from smc_core.scoring import ScoredEvent, score_events


def _scoring_result():
    return score_events(
        [
            ScoredEvent("bos-1", "BOS", 0.72, True, 1.0),
            ScoredEvent("ob-1", "OB", 0.66, True, 2.0),
            ScoredEvent("sw-1", "SWEEP", 0.35, False, 3.0),
        ]
    )


def test_build_ensemble_quality_is_bounded_and_explainable() -> None:
    result = build_ensemble_quality(
        heuristic_quality=0.82,
        bias_direction="BULLISH",
        bias_confidence=0.9,
        vol_regime_label="NORMAL",
        vol_regime_confidence=0.8,
        scoring_result=_scoring_result(),
    )

    assert 0.0 <= result.score <= 1.0
    assert result.tier in {"low", "ok", "good", "high"}
    assert result.available_components == ["bias", "heuristic", "scoring", "vol_regime"]
    assert set(result.contributions) == {"heuristic", "bias", "vol_regime", "scoring"}


def test_build_ensemble_quality_is_stable_for_identical_inputs() -> None:
    first = build_ensemble_quality(
        heuristic_quality=0.64,
        bias_direction="BEARISH",
        bias_confidence=0.7,
        vol_regime_label="HIGH_VOL",
        vol_regime_confidence=0.6,
        scoring_result=_scoring_result(),
    )
    second = build_ensemble_quality(
        heuristic_quality=0.64,
        bias_direction="BEARISH",
        bias_confidence=0.7,
        vol_regime_label="HIGH_VOL",
        vol_regime_confidence=0.6,
        scoring_result=_scoring_result(),
    )

    first_payload = serialize_ensemble_quality(first)
    second_payload = serialize_ensemble_quality(second)
    first_payload.pop("generated_at", None)
    second_payload.pop("generated_at", None)

    assert first_payload == second_payload


def test_build_ensemble_quality_uses_history_rows_when_available() -> None:
    result = build_ensemble_quality(
        bias_direction="BULLISH",
        bias_confidence=0.85,
        vol_regime_label="NORMAL",
        vol_regime_confidence=0.75,
        scoring_result=_scoring_result(),
        history_rows=[
            {"brier_score": 0.18, "log_score": 0.42, "n_events": 3},
            {"brier_score": 0.22, "log_score": 0.48, "n_events": 4},
        ],
    )

    assert "history" in result.available_components
    assert result.contributions["history"]["detail"]["history_runs"] == 2
    assert result.contributions["history"]["detail"]["baseline_n_events"] == 3.5