"""The reaction-zone shadow fields are emitted into the event ledger features
with a LEAKAGE-FREE confirmation/outcome split (bars 1-3 vs bars 4-8)."""
from __future__ import annotations

import os
from unittest.mock import patch

import pandas as pd

from smc_integration.measurement_evidence import _evaluate_sweep_event


def _reclaim_then_fade_bars() -> pd.DataFrame:
    """Bullish (SELL_SIDE) sweep of the 100 low: bars 1-3 reclaim above 100
    (confirmation window), then bars 4-8 FADE back below 100 (outcome window).
    Demonstrates the disjoint windows: level_reclaimed=True but the later
    follow-through outcome is False."""
    rows = []
    ts0 = 1_700_000_000
    for i in range(20):
        if i <= 9:
            c = 105.0 if i == 5 else 102.0
            hi, lo = c + 0.5, c - 0.5
        elif i == 10:  # sweep bar: pierces 98, closes 99
            c, hi, lo = 99.0, 100.2, 98.0
        elif i <= 13:  # bars 1-3 after the sweep: reclaim above 100
            c, hi, lo = 101.0, 101.5, 100.2
        else:  # bars 4-8: fade back below 100
            c, hi, lo = 99.5, 99.8, 99.2
        rows.append({"timestamp": ts0 + i * 900, "open": c, "high": hi, "low": lo, "close": c})
    return pd.DataFrame(rows)


def _sweep_event() -> dict:
    return {"id": "sweep-fade", "price": 100.0, "side": "SELL_SIDE",
            "time": float(1_700_000_000 + 10 * 900)}


def test_reaction_fields_emitted_with_disjoint_windows() -> None:
    bars = _reclaim_then_fade_bars()
    with patch.dict(os.environ, {"ENABLE_REACTION_ZONE_STUDY": "1"}):
        result = _evaluate_sweep_event(
            _sweep_event(), bars,
            bias_direction="BULLISH", bias_confidence=0.5, event_context={},
        )
    assert result is not None
    _outcome_dict, scored = result
    feats = scored.features

    assert feats["reaction_schema_version"] == 1
    assert feats["reaction_direction"] == "bull"
    # Confirmation window (bars 1-3) reclaimed above the swept level.
    assert feats["reaction_level_reclaimed"] is True
    assert feats["reaction_bars_to_reclaim"] == 1
    # Outcome window is DISJOINT (bars 4-8) and FADED → no genuine follow-through,
    # even though an early reclaim happened. This is the leakage-free signal.
    assert feats["reaction_outcome_late"] is False
    # All raw study fields present for the follow-up analysis.
    for key in ("reaction_in_rejection_band", "reaction_close_distance_pct",
                "reaction_body_ratio", "reaction_directional_body",
                "reaction_wick_ratio", "reaction_bars_to_rejection_band",
                "reaction_band_width_pct"):
        assert key in feats


def test_reaction_fields_absent_when_flag_off() -> None:
    bars = _reclaim_then_fade_bars()
    with patch.dict(os.environ, {"ENABLE_REACTION_ZONE": "0"}):
        result = _evaluate_sweep_event(
            _sweep_event(), bars,
            bias_direction="BULLISH", bias_confidence=0.5, event_context={},
        )
    assert result is not None
    _outcome_dict, scored = result
    assert "reaction_schema_version" not in scored.features
