"""Tests for trend-state features (observe-only, no scorer weight).

Covers:
  - ``compute_trend_state_features`` math + fail-closed guards
  - ``prepare_outcome_snapshot`` pass-through of the three feature keys
  - ``FEATURE_KEYS`` / ``PASS_THROUGH_FEATURE_KEYS`` / ``FEATURE_TO_WEIGHT_KEY``
    consistency
  - ``FeatureImportanceCollector`` ingestion of the new keys
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from open_prep.technical_analysis import _ema, compute_trend_state_features

TREND_STATE_KEYS = ("trend_alignment", "dist_to_ema20_pct", "ema50_slope_pct")


def _bars(closes: list[float]) -> list[dict[str, Any]]:
    return [{"close": c} for c in closes]


# ── compute_trend_state_features: math ──────────────────────────────────────


class TestComputeTrendStateFeatures:
    def test_uptrend_alignment_positive(self) -> None:
        closes = [100.0 + i * 0.5 for i in range(250)]
        out = compute_trend_state_features(_bars(closes))
        assert out["trend_alignment"] == 1
        assert out["ema50_slope_pct"] is not None and out["ema50_slope_pct"] > 0
        # Last close sits above the lagging EMA20 in a steady uptrend
        assert out["dist_to_ema20_pct"] is not None and out["dist_to_ema20_pct"] > 0

    def test_downtrend_alignment_negative(self) -> None:
        closes = [225.0 - i * 0.5 for i in range(250)]
        out = compute_trend_state_features(_bars(closes))
        assert out["trend_alignment"] == -1
        assert out["ema50_slope_pct"] is not None and out["ema50_slope_pct"] < 0
        assert out["dist_to_ema20_pct"] is not None and out["dist_to_ema20_pct"] < 0

    def test_alignment_matches_ema_ordering(self) -> None:
        """V-shape series: ordinal must reflect the actual EMA ordering."""
        closes = [300.0 - i for i in range(200)] + [100.0 + 2.0 * i for i in range(50)]
        out = compute_trend_state_features(_bars(closes))
        e20, e50, e200 = _ema(closes, 20), _ema(closes, 50), _ema(closes, 200)
        if e20 > e50 > e200:
            expected = 1
        elif e20 < e50 < e200:
            expected = -1
        else:
            expected = 0
        assert out["trend_alignment"] == expected

    def test_dist_uses_current_price_when_given(self) -> None:
        closes = [100.0] * 30
        out = compute_trend_state_features(_bars(closes), current_price=110.0)
        # EMA20 of a flat series is exactly 100 → +10%
        assert out["dist_to_ema20_pct"] == 10.0

    def test_dist_falls_back_to_last_close(self) -> None:
        closes = [100.0] * 30
        out = compute_trend_state_features(_bars(closes))
        assert out["dist_to_ema20_pct"] == 0.0

    def test_non_positive_current_price_falls_back(self) -> None:
        closes = [100.0] * 30
        out = compute_trend_state_features(_bars(closes), current_price=0.0)
        assert out["dist_to_ema20_pct"] == 0.0

    def test_slope_window_respected(self) -> None:
        closes = [100.0 + i for i in range(60)]
        out = compute_trend_state_features(_bars(closes), slope_window=5)
        e_now = _ema(closes, 50)
        e_prev = _ema(closes[:-5], 50)
        expected = round((e_now - e_prev) / e_prev * 100.0, 4)
        assert out["ema50_slope_pct"] == expected


# ── compute_trend_state_features: fail-closed guards ────────────────────────


class TestTrendStateFailClosed:
    def test_empty_bars_all_none(self) -> None:
        out = compute_trend_state_features([])
        assert all(out[k] is None for k in TREND_STATE_KEYS)

    def test_non_positive_closes_all_none(self) -> None:
        out = compute_trend_state_features(_bars([0.0, -5.0] * 120))
        assert all(out[k] is None for k in TREND_STATE_KEYS)

    def test_missing_close_keys_skipped(self) -> None:
        out = compute_trend_state_features([{"open": 1.0}] * 250)
        assert all(out[k] is None for k in TREND_STATE_KEYS)

    def test_under_20_bars_all_none(self) -> None:
        out = compute_trend_state_features(_bars([100.0] * 19))
        assert all(out[k] is None for k in TREND_STATE_KEYS)

    def test_under_55_bars_no_slope(self) -> None:
        out = compute_trend_state_features(_bars([100.0] * 54), slope_window=5)
        assert out["dist_to_ema20_pct"] is not None
        assert out["ema50_slope_pct"] is None
        assert out["trend_alignment"] is None

    def test_under_200_bars_no_alignment(self) -> None:
        out = compute_trend_state_features(_bars([100.0 + i for i in range(199)]))
        assert out["trend_alignment"] is None
        assert out["dist_to_ema20_pct"] is not None
        assert out["ema50_slope_pct"] is not None

    def test_zero_slope_window_no_slope(self) -> None:
        out = compute_trend_state_features(_bars([100.0] * 250), slope_window=0)
        assert out["ema50_slope_pct"] is None
        assert out["trend_alignment"] == 0  # flat: EMAs equal → mixed


# ── prepare_outcome_snapshot pass-through ────────────────────────────────────


class TestOutcomeSnapshotTrendState:
    def test_snapshot_includes_trend_state_fields(self) -> None:
        from open_prep.outcomes import prepare_outcome_snapshot

        ranked = [{
            "symbol": "AAPL",
            "gap_pct": 2.0,
            "volume": 1_000_000,
            "avg_volume": 500_000,
            "score": 3.2,
            "trend_alignment": 1,
            "dist_to_ema20_pct": 1.25,
            "ema50_slope_pct": 0.4,
        }]
        records = prepare_outcome_snapshot(ranked, date(2026, 6, 11))
        assert records[0]["trend_alignment"] == 1
        assert records[0]["dist_to_ema20_pct"] == 1.25
        assert records[0]["ema50_slope_pct"] == 0.4

    def test_snapshot_trend_state_none_when_absent(self) -> None:
        from open_prep.outcomes import prepare_outcome_snapshot

        records = prepare_outcome_snapshot(
            [{"symbol": "MSFT", "gap_pct": 1.0, "volume": 1, "avg_volume": 1, "score": 0.5}],
            date(2026, 6, 11),
        )
        for key in TREND_STATE_KEYS:
            assert records[0][key] is None


# ── FEATURE_KEYS / pass-through consistency ──────────────────────────────────


class TestFeatureKeyConsistency:
    def test_feature_keys_include_trend_state(self) -> None:
        from open_prep.outcomes import FEATURE_KEYS

        for key in TREND_STATE_KEYS:
            assert key in FEATURE_KEYS

    def test_trend_state_are_pass_through(self) -> None:
        from open_prep.outcomes import FEATURE_TO_WEIGHT_KEY, PASS_THROUGH_FEATURE_KEYS

        for key in TREND_STATE_KEYS:
            assert key in PASS_THROUGH_FEATURE_KEYS
            assert key not in FEATURE_TO_WEIGHT_KEY

    def test_pass_through_keys_subset_of_feature_keys(self) -> None:
        from open_prep.outcomes import FEATURE_KEYS, PASS_THROUGH_FEATURE_KEYS

        assert PASS_THROUGH_FEATURE_KEYS.issubset(FEATURE_KEYS)

    def test_scorer_has_no_trend_state_weight(self) -> None:
        """Observe-only contract: scorer DEFAULT_WEIGHTS must not weight these."""
        from open_prep.scorer import DEFAULT_WEIGHTS

        for key in TREND_STATE_KEYS:
            assert key not in DEFAULT_WEIGHTS


# ── FeatureImportanceCollector ingestion ─────────────────────────────────────


class TestFICollectorTrendState:
    def test_record_and_flush_includes_trend_state(self, monkeypatch, tmp_path) -> None:
        import open_prep.outcomes as outcomes

        monkeypatch.setattr(outcomes, "FEATURE_IMPORTANCE_DIR", tmp_path)
        collector = outcomes.FeatureImportanceCollector()
        breakdown = {key: 0.0 for key in outcomes.FEATURE_KEYS}
        breakdown.update({
            "trend_alignment": -1.0,
            "dist_to_ema20_pct": 2.5,
            "ema50_slope_pct": -0.75,
        })
        collector.record(
            "TSLA",
            breakdown,
            total_score=1.0,
            profitable_30m=True,
            run_date="2026-06-11",
        )
        path = collector.flush_to_disk(date(2026, 6, 11))
        assert path is not None
        sample = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert sample["trend_alignment"] == -1.0
        assert sample["dist_to_ema20_pct"] == 2.5
        assert sample["ema50_slope_pct"] == -0.75
