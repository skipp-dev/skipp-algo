"""Tests for ``scripts/measure_ttf.py`` (Plan §2.1 D3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.measure_ttf import (
    DEFAULT_LOOKAHEAD_SWEEP,
    _load_events,
    distribution_summary,
    lookahead_sensitivity,
    measure,
    time_to_fill,
)


class TestTimeToFill:
    def test_returns_positive_offset(self) -> None:
        assert time_to_fill({"anchor_idx": 10, "mitigation_idx": 18}) == 8

    def test_zero_offset_is_valid(self) -> None:
        assert time_to_fill({"anchor_idx": 5, "mitigation_idx": 5}) == 0

    def test_never_filled_returns_none(self) -> None:
        assert time_to_fill({"anchor_idx": 5, "mitigation_idx": None}) is None

    def test_negative_offset_is_treated_as_corrupted(self) -> None:
        # A mitigation index BEFORE the anchor must not leak into the
        # distribution as a negative sample — it would poison the
        # percentile math silently.
        assert time_to_fill({"anchor_idx": 20, "mitigation_idx": 12}) is None

    def test_non_numeric_indices_return_none(self) -> None:
        assert time_to_fill({"anchor_idx": "x", "mitigation_idx": 3}) is None


class TestDistributionSummary:
    def test_empty_input_returns_nones_not_zeros(self) -> None:
        summary = distribution_summary([])
        assert summary["total_events"] == 0
        assert summary["mitigated_events"] == 0
        assert summary["p25"] is None
        assert summary["median"] is None
        assert summary["p75"] is None
        assert summary["p90"] is None

    def test_basic_percentiles(self) -> None:
        # Anchors at 0, mitigations at 2/4/6/8/10 → TTFs are 2,4,6,8,10.
        events = [
            {"anchor_idx": 0, "mitigation_idx": m} for m in (2, 4, 6, 8, 10)
        ]
        summary = distribution_summary(events)
        assert summary["total_events"] == 5
        assert summary["mitigated_events"] == 5
        assert summary["min"] == 2
        assert summary["max"] == 10
        assert summary["median"] == 6

    def test_never_filled_and_corrupted_are_split(self) -> None:
        events = [
            {"anchor_idx": 0, "mitigation_idx": 3},          # ok, TTF=3
            {"anchor_idx": 0, "mitigation_idx": None},       # never filled
            {"anchor_idx": 0, "mitigation_idx": -1},         # ok, TTF clamped? no — negative → corrupted
            "not-a-dict",                                     # corrupted
        ]
        summary = distribution_summary(events)
        assert summary["mitigated_events"] == 1
        assert summary["never_filled_events"] == 1
        assert summary["corrupted_events"] == 2


class TestLookaheadSensitivity:
    def test_default_sweep_reports_every_candidate(self) -> None:
        events = [
            {"anchor_idx": 0, "mitigation_idx": 3},
            {"anchor_idx": 0, "mitigation_idx": 12},
            {"anchor_idx": 0, "mitigation_idx": 25},
            {"anchor_idx": 0, "mitigation_idx": None},
        ]
        result = lookahead_sensitivity(events)
        lookaheads = [row["lookahead"] for row in result["per_lookahead"]]
        assert lookaheads == sorted(DEFAULT_LOOKAHEAD_SWEEP)
        # lookahead=10 → only the TTF=3 event is a hit.
        default_row = next(
            row for row in result["per_lookahead"] if row["lookahead"] == 10
        )
        assert default_row["hits"] == 1
        assert default_row["hit_rate"] == 0.25
        # lookahead=40 catches 3, 12 and 25 → 3 hits.
        row40 = next(
            row for row in result["per_lookahead"] if row["lookahead"] == 40
        )
        assert row40["hits"] == 3
        # Top-level default_hit_rate is the 10-bar rate.
        assert result["default_hit_rate"] == 0.25

    def test_custom_sweep_is_deduplicated_and_sorted(self) -> None:
        result = lookahead_sensitivity([], lookaheads=(20, 5, 5, 20))
        lookaheads = [row["lookahead"] for row in result["per_lookahead"]]
        assert lookaheads == [5, 20]


class TestMeasure:
    def test_measure_combines_both_reports(self) -> None:
        events = [
            {"anchor_idx": 0, "mitigation_idx": 2},
            {"anchor_idx": 0, "mitigation_idx": 15},
        ]
        out = measure(events)
        assert "distribution" in out
        assert "lookahead_sensitivity" in out
        assert out["distribution"]["mitigated_events"] == 2
        assert out["lookahead_sensitivity"]["total_events"] == 2

    def test_output_is_json_serialisable(self) -> None:
        events = [{"anchor_idx": 0, "mitigation_idx": 4}]
        json.dumps(measure(events))


class TestCliLoader:
    def test_accepts_bare_list(self, tmp_path: Path) -> None:
        path = tmp_path / "events.json"
        path.write_text(json.dumps([{"anchor_idx": 0, "mitigation_idx": 5}]))
        assert _load_events(path) == [{"anchor_idx": 0, "mitigation_idx": 5}]

    def test_accepts_events_wrapper(self, tmp_path: Path) -> None:
        path = tmp_path / "events.json"
        path.write_text(json.dumps({"events": [{"anchor_idx": 0, "mitigation_idx": 7}]}))
        assert _load_events(path) == [{"anchor_idx": 0, "mitigation_idx": 7}]

    def test_rejects_unsupported_shape(self, tmp_path: Path) -> None:
        path = tmp_path / "events.json"
        path.write_text(json.dumps(42))
        with pytest.raises(ValueError):
            _load_events(path)
