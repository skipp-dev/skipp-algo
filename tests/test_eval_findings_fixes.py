"""Tests for the eval-findings remediation bundle (2026-06-11).

Covers:
  B1 — direction-aware labeling (``infer_trade_direction``, signed PnL)
  B2 — triple-barrier label in ``compute_pnl_from_bars``
  B3 — FI hardening: pooled-std separation, Welch p-values, BH-FDR gate
  B7 — SMA-seeded EMA
  B8 — macro surprise scale fix (no 1.0 floor)
  D3 — gap×playbook bucket report
  D7 — real ADX / BB-width from daily bars
  C4 — gap_range_pos observe-only feature
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import pytest

from open_prep.outcome_backfill import compute_pnl_from_bars
from open_prep.outcomes import (
    FEATURE_KEYS,
    PASS_THROUGH_FEATURE_KEYS,
    _benjamini_hochberg,
    _compute_feature_statistics_cpu,
    compute_gap_playbook_report,
    infer_trade_direction,
    prepare_outcome_snapshot,
)
from open_prep.technical_analysis import (
    _ema,
    compute_adx_from_bars,
    compute_bb_width_pct_from_bars,
    compute_gap_range_position,
)

# ── B7: SMA-seeded EMA ──────────────────────────────────────────────────────

class TestEmaSeed:
    def test_constant_series_returns_constant(self) -> None:
        assert _ema([5.0] * 50, 20) == pytest.approx(5.0)

    def test_single_value_returns_that_value(self) -> None:
        assert _ema([42.0], 10) == 42.0

    def test_empty_returns_nan(self) -> None:
        assert math.isnan(_ema([], 5))

    def test_short_series_is_sma(self) -> None:
        # Fewer values than span → plain mean (SMA seed over what exists).
        assert _ema([1.0, 2.0, 3.0], 10) == pytest.approx(2.0)

    def test_seed_reduces_first_bar_bias(self) -> None:
        # 220 bars: first bar is an outlier (1000), rest are 100.
        # Old values[0]-seed left ~11% weight on the outlier for span=200;
        # the SMA seed dilutes it to ~1/200 within the seed window.
        values = [1000.0] + [100.0] * 219
        result = _ema(values, 200)
        assert result < 110.0  # old seed gave ~ 200

    def test_matches_known_progression(self) -> None:
        # span=3, k=0.5; seed = mean(1,2,3)=2; then 4: 4*.5+2*.5=3; 5: 4.
        assert _ema([1.0, 2.0, 3.0, 4.0, 5.0], 3) == pytest.approx(4.0)


# ── D7: real ADX / BB-width ─────────────────────────────────────────────────

def _make_bars(closes: list[float], spread: float = 0.5) -> list[dict[str, Any]]:
    return [
        {"open": c, "high": c + spread, "low": c - spread, "close": c, "volume": 1000}
        for c in closes
    ]


class TestAdxFromBars:
    def test_insufficient_bars_returns_none(self) -> None:
        assert compute_adx_from_bars(_make_bars([100.0] * 20)) is None

    def test_strong_trend_high_adx(self) -> None:
        closes = [100.0 + 2.0 * i for i in range(60)]
        adx = compute_adx_from_bars(_make_bars(closes))
        assert adx is not None and adx > 25.0

    def test_flat_series_low_adx(self) -> None:
        # Alternating chop: no sustained directional movement.
        closes = [100.0 + (0.3 if i % 2 else -0.3) for i in range(60)]
        adx = compute_adx_from_bars(_make_bars(closes))
        assert adx is not None and adx < 25.0

    def test_bounded_zero_to_hundred(self) -> None:
        closes = [100.0 + 5.0 * i for i in range(80)]
        adx = compute_adx_from_bars(_make_bars(closes))
        assert adx is not None and 0.0 <= adx <= 100.0


class TestBbWidthFromBars:
    def test_insufficient_bars_returns_none(self) -> None:
        assert compute_bb_width_pct_from_bars(_make_bars([100.0] * 10)) is None

    def test_constant_closes_zero_width(self) -> None:
        assert compute_bb_width_pct_from_bars(_make_bars([100.0] * 25)) == pytest.approx(0.0)

    def test_volatile_closes_positive_width(self) -> None:
        closes = [100.0 + (5.0 if i % 2 else -5.0) for i in range(25)]
        width = compute_bb_width_pct_from_bars(_make_bars(closes))
        assert width is not None and width > 10.0

    def test_non_positive_middle_returns_none(self) -> None:
        assert compute_bb_width_pct_from_bars(_make_bars([0.0] * 25)) is None


# ── C4: gap_range_pos ───────────────────────────────────────────────────────

class TestGapRangePosition:
    def test_above_prior_high_gt_one(self) -> None:
        bars = _make_bars([100.0])  # prior H=100.5, L=99.5
        assert compute_gap_range_position(bars, 102.0) > 1.0

    def test_below_prior_low_lt_zero(self) -> None:
        bars = _make_bars([100.0])
        assert compute_gap_range_position(bars, 98.0) < 0.0

    def test_inside_range(self) -> None:
        bars = _make_bars([100.0])
        pos = compute_gap_range_position(bars, 100.0)
        assert pos == pytest.approx(0.5)

    def test_no_bars_returns_none(self) -> None:
        assert compute_gap_range_position([], 100.0) is None

    def test_zero_price_returns_none(self) -> None:
        assert compute_gap_range_position(_make_bars([100.0]), 0.0) is None

    def test_degenerate_range_returns_none(self) -> None:
        bars = [{"open": 100, "high": 100.0, "low": 100.0, "close": 100, "volume": 1}]
        assert compute_gap_range_position(bars, 101.0) is None


# ── B1: direction inference ─────────────────────────────────────────────────

class TestInferTradeDirection:
    def test_gap_fade_gap_up_is_short(self) -> None:
        row = {"gap_pct": 12.0, "playbook": {"playbook": "GAP_FADE"}}
        assert infer_trade_direction(row) == "short"

    def test_gap_fade_gap_down_is_long(self) -> None:
        row = {"gap_pct": -8.0, "playbook": {"playbook": "GAP_FADE"}}
        assert infer_trade_direction(row) == "long"

    def test_gap_and_go_gap_up_is_long(self) -> None:
        row = {"gap_pct": 4.0, "playbook": {"playbook": "GAP_AND_GO"}}
        assert infer_trade_direction(row) == "long"

    def test_continuation_gap_down_is_short(self) -> None:
        row = {"gap_pct": -4.0, "playbook": {"playbook": "POST_NEWS_DRIFT"}}
        assert infer_trade_direction(row) == "short"

    def test_missing_everything_defaults_long(self) -> None:
        assert infer_trade_direction({}) == "long"


# ── B1/B2: signed PnL + triple barrier ──────────────────────────────────────

def _bars_df(symbol: str, run_date: date, closes: list[float],
             highs: list[float] | None = None,
             lows: list[float] | None = None) -> pd.DataFrame:
    """1-min bars starting 09:30 ET on run_date."""
    n = len(closes)
    ts = pd.date_range(
        start=pd.Timestamp(f"{run_date} 09:30", tz="America/New_York"),
        periods=n, freq="1min",
    ).tz_convert("UTC")
    return pd.DataFrame({
        "symbol": [symbol] * n,
        "ts_event": ts,
        "open": closes,
        "high": highs or [c + 0.01 for c in closes],
        "low": lows or [c - 0.01 for c in closes],
        "close": closes,
    })


_D = date(2026, 6, 10)


class TestComputePnlDirectional:
    def test_short_fade_winner_signed_positive(self) -> None:
        # Price falls 100 → 95: long PnL −5%, short fade is the winner.
        closes = [100.0 - i * 0.2 for i in range(26)]
        df = _bars_df("XYZ", _D, closes)
        result = compute_pnl_from_bars(df, "XYZ", _D, direction="short")
        assert result is not None
        assert result["pnl_30m_pct"] < 0          # legacy long-only view
        assert result["profitable_30m"] is False  # unchanged legacy label
        assert result["pnl_30m_pct_signed"] > 0   # directional truth
        assert result["profitable_30m_directional"] is True

    def test_long_direction_matches_legacy(self) -> None:
        closes = [100.0 + i * 0.1 for i in range(26)]
        df = _bars_df("XYZ", _D, closes)
        result = compute_pnl_from_bars(df, "XYZ", _D, direction="long")
        assert result is not None
        assert result["pnl_30m_pct_signed"] == result["pnl_30m_pct"]
        assert result["profitable_30m_directional"] == result["profitable_30m"]

    def test_tb_target_hit_long(self) -> None:
        # ATR 2% → target +2%, stop −1%. Spike to +3% in bar 5.
        closes = [100.0] * 26
        highs = [100.01] * 26
        highs[5] = 103.0
        df = _bars_df("XYZ", _D, closes, highs=highs)
        result = compute_pnl_from_bars(df, "XYZ", _D, direction="long", atr_pct=2.0)
        assert result is not None
        assert result["label_tb"] == "target"
        assert result["profitable_tb"] is True
        assert result["tb_barrier_source"] == "atr"

    def test_tb_stop_hit_long(self) -> None:
        closes = [100.0] * 26
        lows = [99.99] * 26
        lows[3] = 98.0  # −2% < stop at −1%
        df = _bars_df("XYZ", _D, closes, lows=lows)
        result = compute_pnl_from_bars(df, "XYZ", _D, direction="long", atr_pct=2.0)
        assert result is not None
        assert result["label_tb"] == "stop"
        assert result["profitable_tb"] is False

    def test_tb_stop_wins_tie_in_same_bar(self) -> None:
        # Bar 2 touches BOTH barriers → conservative: stop.
        closes = [100.0] * 26
        highs = [100.01] * 26
        lows = [99.99] * 26
        highs[2], lows[2] = 103.0, 98.0
        df = _bars_df("XYZ", _D, closes, highs=highs, lows=lows)
        result = compute_pnl_from_bars(df, "XYZ", _D, direction="long", atr_pct=2.0)
        assert result is not None
        assert result["label_tb"] == "stop"

    def test_tb_timeout_labels(self) -> None:
        closes = [100.0 + i * 0.01 for i in range(26)]  # tiny drift up
        df = _bars_df("XYZ", _D, closes)
        result = compute_pnl_from_bars(df, "XYZ", _D, direction="long", atr_pct=5.0)
        assert result is not None
        assert result["label_tb"] == "timeout_win"
        assert result["profitable_tb"] is True

    def test_tb_default_barriers_when_atr_missing(self) -> None:
        closes = [100.0] * 26
        df = _bars_df("XYZ", _D, closes)
        result = compute_pnl_from_bars(df, "XYZ", _D, direction="long", atr_pct=None)
        assert result is not None
        assert result["tb_barrier_source"] == "default"

    def test_tb_short_target_is_downside(self) -> None:
        closes = [100.0] * 26
        lows = [99.99] * 26
        lows[4] = 97.0  # −3% crosses the short target (−2%)
        df = _bars_df("XYZ", _D, closes, lows=lows)
        result = compute_pnl_from_bars(df, "XYZ", _D, direction="short", atr_pct=2.0)
        assert result is not None
        assert result["label_tb"] == "target"
        assert result["profitable_tb"] is True


# ── B3: pooled std, p-values, BH-FDR ────────────────────────────────────────

class TestFiHardening:
    def test_stats_include_p_value(self) -> None:
        rng = np.random.default_rng(42)
        matrix = rng.normal(size=(100, len(FEATURE_KEYS)))
        outcomes = (rng.random(100) > 0.5).astype(np.float64)
        stats = _compute_feature_statistics_cpu(matrix, outcomes)
        for key in FEATURE_KEYS:
            assert "p_value" in stats[key]
            assert 0.0 <= stats[key]["p_value"] <= 1.0

    def test_separation_uses_pooled_std(self) -> None:
        # Winners tightly clustered at 1.0 (σ_win→0), losers spread at 0.
        # σ_win-only would explode separation; pooled std keeps it sane.
        n = 100
        matrix = np.zeros((n, len(FEATURE_KEYS)))
        outcomes = np.zeros(n)
        outcomes[:50] = 1.0
        matrix[:50, 0] = 1.0 + np.random.default_rng(0).normal(0, 0.001, 50)
        matrix[50:, 0] = np.random.default_rng(1).normal(0, 1.0, 50)
        stats = _compute_feature_statistics_cpu(matrix, outcomes)
        # Pooled std ≈ 0.71 → separation ≈ 1.4; σ_win-only gave ≈ 1000.
        assert stats[FEATURE_KEYS[0]]["mean_separation"] < 10.0

    def test_real_signal_significant(self) -> None:
        rng = np.random.default_rng(7)
        n = 400
        matrix = rng.normal(size=(n, len(FEATURE_KEYS)))
        outcomes = (rng.random(n) > 0.5).astype(np.float64)
        # Inject a real effect into feature 0.
        matrix[:, 0] += outcomes * 2.0
        stats = _compute_feature_statistics_cpu(matrix, outcomes)
        assert stats[FEATURE_KEYS[0]]["p_value"] < 0.01

    def test_bh_all_noise_rejects_all(self) -> None:
        flags = _benjamini_hochberg({f"f{i}": 0.5 + i * 0.02 for i in range(10)})
        assert not any(flags.values())

    def test_bh_strong_signal_passes(self) -> None:
        p_values = {"signal": 1e-6, **{f"noise{i}": 0.8 for i in range(10)}}
        flags = _benjamini_hochberg(p_values)
        assert flags["signal"] is True
        assert not any(v for k, v in flags.items() if k != "signal")

    def test_bh_empty(self) -> None:
        assert _benjamini_hochberg({}) == {}

    def test_min_tuning_samples_raised(self) -> None:
        from open_prep.outcomes import _MIN_TUNING_SAMPLES
        assert _MIN_TUNING_SAMPLES >= 200


# ── D3: gap × playbook report ───────────────────────────────────────────────

class TestGapPlaybookReport:
    def test_aggregates_by_bucket_and_playbook(self) -> None:
        records = [
            {"gap_bucket_label": "5-10%", "playbook_name": "GAP_AND_GO",
             "profitable_30m_directional": True, "pnl_30m_pct_signed": 2.0},
            {"gap_bucket_label": "5-10%", "playbook_name": "GAP_AND_GO",
             "profitable_30m_directional": False, "pnl_30m_pct_signed": -1.0},
            {"gap_bucket_label": ">10%", "playbook_name": "GAP_FADE",
             "profitable_30m_directional": True, "pnl_30m_pct_signed": 3.0},
        ]
        report = compute_gap_playbook_report(records)
        assert report["5-10%:GAP_AND_GO"]["total"] == 2
        assert report["5-10%:GAP_AND_GO"]["hit_rate"] == pytest.approx(0.5)
        assert report[">10%:GAP_FADE"]["hit_rate"] == pytest.approx(1.0)

    def test_falls_back_to_legacy_label(self) -> None:
        records = [
            {"gap_bucket_label": "2-5%", "playbook_name": "GAP_AND_GO",
             "profitable_30m": True, "pnl_30m_pct": 1.5},
        ]
        report = compute_gap_playbook_report(records)
        assert report["2-5%:GAP_AND_GO"]["total"] == 1

    def test_skips_unresolved(self) -> None:
        assert compute_gap_playbook_report([{"gap_bucket_label": "2-5%"}]) == {}


# ── Snapshot schema ─────────────────────────────────────────────────────────

class TestSnapshotSchema:
    def test_new_fields_present(self) -> None:
        rows = [{
            "symbol": "NVDA", "gap_pct": 5.0, "volume": 2_000_000,
            "avg_volume": 1_000_000, "score": 9.0,
            "playbook": {"playbook": "GAP_AND_GO"},
            "atr_pct": 3.2, "gap_range_pos": 1.15, "eps_surprise_pct": 12.5,
        }]
        rec = prepare_outcome_snapshot(rows, date(2026, 6, 10))[0]
        assert rec["direction"] == "long"
        assert rec["atr_pct"] == 3.2
        assert rec["playbook_name"] == "GAP_AND_GO"
        assert rec["gap_range_pos"] == 1.15
        assert rec["eps_surprise_pct"] == 12.5
        for key in ("pnl_30m_pct_signed", "profitable_30m_directional",
                    "label_tb", "profitable_tb"):
            assert rec[key] is None

    def test_new_features_are_pass_through(self) -> None:
        assert "gap_range_pos" in PASS_THROUGH_FEATURE_KEYS
        assert "eps_surprise_pct" in PASS_THROUGH_FEATURE_KEYS
        assert PASS_THROUGH_FEATURE_KEYS.issubset(set(FEATURE_KEYS))


# ── B8: macro surprise scale ────────────────────────────────────────────────

class TestMacroSurpriseScale:
    def test_low_consensus_not_crushed(self) -> None:
        from open_prep.macro import macro_bias_with_components
        events = [{
            "event": "CPI MoM", "actual": 0.4, "consensus": 0.2,
            "impact": "High", "unit": "%", "country": "US",
        }]
        result = macro_bias_with_components(events)
        comps = [c for c in result["score_components"] if c.get("weight", 0) > 0]
        assert comps, "expected a weighted CPI component"
        # (0.4−0.2)/0.2 = 1.0 — the old max(|consensus|, 1.0) floor reported 0.2.
        assert comps[0]["surprise"] == pytest.approx(1.0, abs=0.01)

    def test_surprise_capped(self) -> None:
        from open_prep.macro import macro_bias_with_components
        events = [{
            "event": "Initial Jobless Claims", "actual": 500.0, "consensus": 0.001,
            "impact": "High", "unit": "K", "country": "US",
        }]
        result = macro_bias_with_components(events)
        for c in result["score_components"]:
            assert abs(c.get("surprise", 0.0)) <= 10.0
