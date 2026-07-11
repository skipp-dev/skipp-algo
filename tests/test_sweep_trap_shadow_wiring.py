"""WS1 + WS4a: sweep-trap shadow wiring in measurement_evidence.

WS1 derives ``swept_level`` / ``sweep_extreme`` / ``origin_level`` at the single
choke point (sweep event + bars both available) so ``classify_sweep_trap``
executes on real sweeps when ``ENABLE_SWEEP_TRAP=1``.

WS4a logs the trap quality into the SWEEP ScoredEvent ``features`` observe-only.
These MUST NOT change the event outcome / raw_score (confluence reads the coarse
SWEEP_QUALITY_SCORE, not SWEEP_TRAP_QUALITY_SCORE) — they exist so WS4b can
measure a Brier/hit-rate delta before any budget weight.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pandas as pd

from smc_integration.measurement_evidence import (
    _derive_sweep_trap_geometry,
    _evaluate_sweep_event,
)


def _bull_sweep_bars() -> pd.DataFrame:
    """A bullish (SELL_SIDE) sweep of the 100 low: leg up to 105, dip to 98 at
    bar 10, then reclaim back above 100."""
    rows = []
    ts0 = 1_700_000_000
    for i in range(20):
        if i <= 9:
            # pre-sweep leg: drifts around 102-105 (origin high = 105 at bar 5)
            c = 105.0 if i == 5 else 102.0
            hi, lo = c + 0.5, c - 0.5
        elif i == 10:
            # the sweep bar: low pierces 98 (below swept_level 100), closes 99
            c, hi, lo = 99.0, 100.2, 98.0
        else:
            # reclaim: closes back above 100
            c, hi, lo = 101.0, 101.5, 100.2
        rows.append({"timestamp": ts0 + i * 900, "open": c, "high": hi, "low": lo, "close": c})
    return pd.DataFrame(rows)


_SWEEP_TS = 1_700_000_000 + 10 * 900  # timestamp of the sweep bar (index 10)


def _event() -> dict:
    return {"id": "sweep-x", "price": 100.0, "side": "SELL_SIDE", "time": float(_SWEEP_TS)}


class TestDeriveGeometry:
    def test_bullish_geometry(self) -> None:
        bars = _bull_sweep_bars()
        swept, extreme, origin = _derive_sweep_trap_geometry(
            _event(), bars, 10, is_bullish_sweep=True
        )
        assert swept == 100.0
        assert extreme == 98.0          # sweep bar low
        assert origin == 105.5          # max high (wick) in the pre-sweep leg
        assert origin > swept > extreme  # bullish: origin above, extreme below

    def test_producer_value_overrides_derivation(self) -> None:
        bars = _bull_sweep_bars()
        cand = {**_event(), "origin_level": 110.0}
        _, _, origin = _derive_sweep_trap_geometry(cand, bars, 10, is_bullish_sweep=True)
        assert origin == 110.0

    def test_missing_bar_index_falls_back(self) -> None:
        bars = _bull_sweep_bars()
        swept, extreme, origin = _derive_sweep_trap_geometry(_event(), bars, None, is_bullish_sweep=True)
        assert swept == 100.0
        assert extreme == 0.0   # no bar → candidate fallback
        assert origin == 100.0  # falls back to swept_level


def _evaluate(bars: pd.DataFrame, *, flag: str) -> tuple:
    with patch.dict(os.environ, {"ENABLE_SWEEP_TRAP": flag}):
        return _evaluate_sweep_event(
            _event(), bars,
            bias_direction="BULLISH", bias_confidence=0.6,
            event_context={"session": "NY_AM"},
        )


class TestShadowObserve:
    def test_features_populated_when_flag_on(self) -> None:
        result = _evaluate(_bull_sweep_bars(), flag="1")
        assert result is not None
        _, scored = result
        f = scored.features
        assert f["sweep_trap_type"] != "failed"          # corrected classifier → valid trap
        assert f["sweep_trap_reclaim_strength"] > 0.0
        assert f["sweep_trap_fib_retrace"] > 0.0
        assert f["sweep_trap_quality_score"] > 0.0

    def test_features_empty_when_flag_off(self) -> None:
        result = _evaluate(_bull_sweep_bars(), flag="0")
        assert result is not None
        _, scored = result
        assert scored.features == {}

    def test_outcome_and_score_unchanged_by_flag(self) -> None:
        bars = _bull_sweep_bars()
        _, on = _evaluate(bars, flag="1")
        _, off = _evaluate(bars, flag="0")
        # The observe fields must not perturb the label or the probability.
        assert on.outcome == off.outcome
        assert on.predicted_prob == off.predicted_prob
        assert on.raw_score == off.raw_score
