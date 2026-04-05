"""Tests for smc_core.scoring — probabilistic quality scoring."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from smc_core.scoring import (
    ScoredEvent,
    ScoringResult,
    brier_score,
    export_scoring_artifact,
    label_bos_follow_through,
    label_fvg_mitigation,
    label_orderblock_mitigation,
    label_sweep_reversal,
    log_score,
    score_events,
)


# --- Brier Score ---


class TestBrierScore:
    def test_perfect_predictions(self) -> None:
        # All predictions perfectly calibrated
        assert brier_score([(1.0, True), (0.0, False)]) == 0.0

    def test_worst_predictions(self) -> None:
        assert brier_score([(0.0, True), (1.0, False)]) == 1.0

    def test_mid_range(self) -> None:
        result = brier_score([(0.5, True), (0.5, False)])
        assert abs(result - 0.25) < 1e-9

    def test_empty(self) -> None:
        assert math.isnan(brier_score([]))


# --- Log Score ---


class TestLogScore:
    def test_perfect_high_prob(self) -> None:
        # Near-perfect predictions → low log score
        result = log_score([(0.99, True), (0.01, False)])
        assert result < 0.1

    def test_bad_predictions(self) -> None:
        # Bad predictions → high log score
        result = log_score([(0.01, True), (0.99, False)])
        assert result > 2.0

    def test_empty(self) -> None:
        assert math.isnan(log_score([]))

    def test_no_inf(self) -> None:
        # Even p=0 and p=1 should not produce inf
        result = log_score([(0.0, True), (1.0, False)])
        assert math.isfinite(result)


# --- Sweep Reversal Label ---


class TestLabelSweepReversal:
    def test_sell_side_reversal_up(self) -> None:
        assert label_sweep_reversal(100.0, "SELL_SIDE", [100.6, 101.0]) is True

    def test_sell_side_no_reversal(self) -> None:
        assert label_sweep_reversal(100.0, "SELL_SIDE", [99.5, 99.0]) is False

    def test_buy_side_reversal_down(self) -> None:
        assert label_sweep_reversal(100.0, "BUY_SIDE", [99.4, 99.0]) is True

    def test_buy_side_no_reversal(self) -> None:
        assert label_sweep_reversal(100.0, "BUY_SIDE", [100.5, 101.0]) is False

    def test_empty_closes(self) -> None:
        assert label_sweep_reversal(100.0, "SELL_SIDE", []) is False


class TestLabelBosFollowThrough:
    def test_bullish_follow_through(self) -> None:
        assert label_bos_follow_through(100.0, "UP", [100.4, 100.7], [99.9, 100.1]) is True

    def test_bearish_follow_through(self) -> None:
        assert label_bos_follow_through(100.0, "DOWN", [100.1, 99.8], [99.5, 99.2]) is True

    def test_empty_paths(self) -> None:
        assert label_bos_follow_through(100.0, "UP", [], []) is False


class TestZoneMitigationLabels:
    def test_orderblock_mitigation_before_invalidation(self) -> None:
        assert label_orderblock_mitigation(99.0, 100.0, "BULL", [101.0, 100.5], [100.4, 99.6], [100.8, 99.9]) is True

    def test_orderblock_invalidation_before_touch(self) -> None:
        assert label_orderblock_mitigation(99.0, 100.0, "BULL", [101.0, 101.2], [100.5, 100.4], [98.7, 99.4]) is False

    def test_fvg_bearish_mitigation(self) -> None:
        assert label_fvg_mitigation(100.0, 101.0, "BEAR", [100.6, 100.8], [99.7, 99.9], [100.4, 100.7]) is True


# --- Score Events ---


class TestScoreEvents:
    def test_score_events_basic(self) -> None:
        events = [
            ScoredEvent("b1", "BOS", 0.8, True, 1.0),
            ScoredEvent("b2", "BOS", 0.3, False, 2.0),
            ScoredEvent("s1", "SWEEP", 0.7, True, 3.0),
        ]
        result = score_events(events)
        assert result.n_events == 3
        assert math.isfinite(result.brier_score)
        assert math.isfinite(result.log_score)
        assert result.hit_rate == 0.6667
        assert set(result.family_metrics) == {"BOS", "SWEEP"}
        assert result.family_metrics["BOS"].n_events == 2
        assert result.family_metrics["SWEEP"].n_events == 1
        assert math.isfinite(result.family_metrics["BOS"].brier_score)
        assert result.calibration.n_events == 3
        assert result.calibration.method in {"platt_scaling", "beta_bin", "identity"}
        assert result.stratified_calibration == {}
        assert result.contextual_calibration == {}

    def test_empty_events(self) -> None:
        result = score_events([])
        assert result.n_events == 0
        assert result.family_metrics == {}
        assert result.calibration.n_events == 0

    def test_score_events_builds_platt_calibration_when_history_is_sufficient(self) -> None:
        events = []
        for idx in range(12):
            events.append(ScoredEvent(f"low-{idx}", "BOS", 0.18 + (idx % 4) * 0.04, False, float(idx + 1)))
        for idx in range(12):
            events.append(ScoredEvent(f"high-{idx}", "SWEEP", 0.62 + (idx % 4) * 0.06, True, float(idx + 21)))

        result = score_events(events)

        assert result.calibration.method == "platt_scaling"
        assert result.calibration.applied is True
        assert result.calibration.n_events == 24
        assert math.isfinite(result.calibration.raw_brier_score)
        assert math.isfinite(result.calibration.calibrated_brier_score)
        assert math.isfinite(result.calibration.raw_ece)
        assert math.isfinite(result.calibration.calibrated_ece)
        assert result.calibration.parameters["slope"] is not None

    def test_score_events_builds_stratified_calibration_from_event_context(self) -> None:
        events = [
            ScoredEvent("ny-1", "BOS", 0.72, True, 1.0, context={"session": "NY_AM", "htf_bias": "BULLISH", "vol_regime": "NORMAL"}),
            ScoredEvent("ny-2", "BOS", 0.35, False, 2.0, context={"session": "NY_AM", "htf_bias": "BULLISH", "vol_regime": "NORMAL"}),
            ScoredEvent("ldn-1", "SWEEP", 0.64, True, 3.0, context={"session": "LONDON", "htf_bias": "BEARISH", "vol_regime": "HIGH_VOL"}),
            ScoredEvent("ldn-2", "SWEEP", 0.28, False, 4.0, context={"session": "LONDON", "htf_bias": "BEARISH", "vol_regime": "HIGH_VOL"}),
        ]

        result = score_events(events)

        assert set(result.stratified_calibration) == {"session", "htf_bias", "vol_regime"}
        assert result.stratified_calibration["session"].groups["NY_AM"].n_events == 2
        assert result.stratified_calibration["session"].groups["LONDON"].n_events == 2
        assert result.stratified_calibration["htf_bias"].groups["BULLISH"].n_events == 2
        assert result.stratified_calibration["vol_regime"].groups["HIGH_VOL"].n_events == 2
        assert set(result.contextual_calibration) == {"session", "htf_bias", "vol_regime"}
        assert result.contextual_calibration["session"].covered_events == 4
        assert result.contextual_calibration["session"].coverage_ratio == 1.0
        assert result.contextual_calibration["session"].group_method_counts

    def test_score_events_prefers_raw_signal_quality_score_when_present(self) -> None:
        events = [
            ScoredEvent("sq-1", "BOS", 0.15, False, 1.0, raw_score=22.0, raw_score_name="SIGNAL_QUALITY_SCORE"),
            ScoredEvent("sq-2", "BOS", 0.20, False, 2.0, raw_score=28.0, raw_score_name="SIGNAL_QUALITY_SCORE"),
            ScoredEvent("sq-3", "SWEEP", 0.85, True, 3.0, raw_score=74.0, raw_score_name="SIGNAL_QUALITY_SCORE"),
            ScoredEvent("sq-4", "SWEEP", 0.90, True, 4.0, raw_score=81.0, raw_score_name="SIGNAL_QUALITY_SCORE"),
        ]

        result = score_events(events)

        assert result.calibration.input_kind == "raw_score_0_100"
        assert result.calibration.source_name == "SIGNAL_QUALITY_SCORE"
        assert result.calibration.n_events == 4
        assert result.contextual_calibration == {}


# --- Export Artifact ---


class TestExportArtifact:
    def test_writes_json(self, tmp_path: Path) -> None:
        events = [
            ScoredEvent("s1", "SWEEP", 0.7, True, 1.0),
            ScoredEvent("b1", "BOS", 0.6, False, 2.0),
        ]
        result = score_events(events)
        path = export_scoring_artifact(
            result,
            symbol="AAPL",
            timeframe="15m",
            output_dir=tmp_path,
            schema_version="2.0.0",
        )
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["symbol"] == "AAPL"
        assert data["schema_version"] == "2.0.0"
        assert isinstance(data["generated_at"], float)
        assert data["n_events"] == 2
        assert math.isfinite(data["brier_score"])
        assert data["aggregate"]["n_events"] == 2
        assert set(data["family_metrics"]) == {"BOS", "SWEEP"}
        assert data["family_metrics"]["BOS"]["n_events"] == 1
        assert data["calibration"]["n_events"] == 2
        assert "method" in data["calibration"]
        assert data["stratified_calibration"] == {}
        assert data["contextual_calibration"] == {}
