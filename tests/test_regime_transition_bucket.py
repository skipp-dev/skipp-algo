"""Sprint C5.1 tests for regime-transition bucket + degraded helpers."""
from __future__ import annotations

import pytest

from scripts.regime_stratification import compute_regime_conditional_metrics
from scripts.regime_transition import (
    TRANSITION_LABEL,
    assign_transition_bucket,
    degraded_regimes,
    is_degraded,
    transition_share,
)


def _trade(bar: int, regime: str, pnl: float = 0.0) -> dict:
    return {"bar_index": bar, "regime_at_entry": regime, "pnl": pnl}


def test_assign_transition_tags_bars_within_window() -> None:
    trades = [
        _trade(0, "A"), _trade(1, "A"), _trade(2, "A"),
        _trade(3, "B"),  # regime flip at bar 3
        _trade(4, "B"), _trade(5, "B"),
        _trade(6, "C"),  # second flip at bar 6
        _trade(7, "C"), _trade(8, "C"),
    ]
    out = assign_transition_bucket(trades, bars_around=1)
    labels = [t["regime_at_entry"] for t in out]
    # Flips at bar 3 (A→B) and bar 6 (B→C). bars_around=1 means every
    # trade whose nearest flip is within 1 bar gets re-tagged — with two
    # flips that's bars 2..7 inclusive.
    expected = ["A", "A"] + [TRANSITION_LABEL] * 6 + ["C"]
    assert labels == expected


def test_assign_transition_preserves_original_label() -> None:
    trades = [_trade(0, "A"), _trade(1, "B")]
    out = assign_transition_bucket(trades, bars_around=2)
    assert all(t["regime_at_entry"] == TRANSITION_LABEL for t in out)
    assert out[0]["regime_original"] == "A"
    assert out[1]["regime_original"] == "B"


def test_assign_transition_zero_window_is_noop() -> None:
    trades = [_trade(0, "A"), _trade(1, "B"), _trade(2, "B")]
    out = assign_transition_bucket(trades, bars_around=0)
    assert [t["regime_at_entry"] for t in out] == ["A", "B", "B"]
    assert all("regime_original" not in t for t in out)


def test_assign_transition_no_changes_is_noop() -> None:
    trades = [_trade(0, "A"), _trade(1, "A"), _trade(2, "A")]
    out = assign_transition_bucket(trades, bars_around=5)
    assert all(t["regime_at_entry"] == "A" for t in out)
    assert all("regime_original" not in t for t in out)


def test_assign_transition_does_not_mutate_input() -> None:
    trades = [_trade(0, "A"), _trade(1, "B")]
    snapshot = [dict(t) for t in trades]
    assign_transition_bucket(trades, bars_around=1)
    assert trades == snapshot


def test_assign_transition_validates_bars_around() -> None:
    with pytest.raises(ValueError, match="bars_around"):
        assign_transition_bucket([], bars_around=-1)


def test_transition_share_reports_correct_fraction() -> None:
    trades = [
        _trade(0, "A"), _trade(1, "A"), _trade(2, "A"),
        _trade(3, "B"), _trade(4, "B"),
    ]
    out = assign_transition_bucket(trades, bars_around=1)
    share = transition_share(trades, out)
    # Flip at bar 3, bars_around=1 → bars 2,3,4 transition → 3/5.
    assert share == pytest.approx(0.6)


def test_transition_share_empty_input() -> None:
    assert transition_share([], []) == 0.0


def test_is_degraded_detects_skipped_reason() -> None:
    assert is_degraded({"skipped_reason": "insufficient_n", "n": 5})
    assert is_degraded({"skipped_reason": "insufficient_finite_n", "n": 50})
    assert not is_degraded({"sharpe": 1.2, "n": 100})


def test_is_degraded_detects_explicit_flag() -> None:
    assert is_degraded({"degraded": True, "n": 100, "sharpe": 1.0})
    assert not is_degraded({"degraded": False, "n": 100, "sharpe": 1.0})


def test_degraded_regimes_filter() -> None:
    per_regime = {
        "RTH": {"sharpe": 1.5, "n": 200},
        "OPEN": {"skipped_reason": "insufficient_n", "n": 5},
        "CLOSE": {"skipped_reason": "insufficient_finite_n", "n": 50, "n_finite": 10},
        "OVN": {"sharpe": 0.4, "n": 80},
    }
    assert degraded_regimes(per_regime) == ["OPEN", "CLOSE"]


def test_transition_pipeline_end_to_end() -> None:
    """Assign transition bucket → stratify → metrics include TRANSITION."""
    trades = [_trade(i, "A", pnl=1.0) for i in range(40)]
    trades += [_trade(i, "B", pnl=-0.5) for i in range(40, 80)]
    rewritten = assign_transition_bucket(trades, bars_around=2)
    # Group by regime label.
    groups: dict[str, list] = {}
    for t in rewritten:
        groups.setdefault(t["regime_at_entry"], []).append(t)
    metrics = compute_regime_conditional_metrics(groups, min_n_per_regime=3)
    assert TRANSITION_LABEL in metrics
    transition_record = metrics[TRANSITION_LABEL]
    assert "skipped_reason" not in transition_record
    # Flip at bar 40, bars_around=2 → bars 38..42 transition → 5 trades.
    assert transition_record["n"] == 5
