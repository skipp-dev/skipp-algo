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


# --- Score Events ---


class TestScoreEvents:
    def test_score_events_basic(self) -> None:
        events = [
            ScoredEvent("s1", "SWEEP", 0.8, True, 1.0),
            ScoredEvent("s2", "SWEEP", 0.2, False, 2.0),
        ]
        result = score_events(events)
        assert result.n_events == 2
        assert math.isfinite(result.brier_score)
        assert math.isfinite(result.log_score)
        assert result.hit_rate == 0.5

    def test_empty_events(self) -> None:
        result = score_events([])
        assert result.n_events == 0


# --- Export Artifact ---


class TestExportArtifact:
    def test_writes_json(self, tmp_path: Path) -> None:
        events = [ScoredEvent("s1", "SWEEP", 0.7, True, 1.0)]
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
        assert data["n_events"] == 1
        assert math.isfinite(data["brier_score"])
