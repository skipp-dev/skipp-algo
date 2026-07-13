"""Structure detection symmetry + fail-closed direction/side/kind handling.

Covers the mirror-invariance audit findings:

* #1 outside-bar BOS/CHOCH classification is not biased bearish by evaluation order;
* #2 CHOCH events keep their kind in the measurement structure light (not BOS);
* #3 the benchmark evaluators reject unknown/missing direction (no bullish default);
* #4 sweep side normalisation is a shared fail-closed SSOT across consumers;
* #5 layering does not style an unknown OB/FVG direction as bearish/short.
"""
from __future__ import annotations

from typing import Any, cast

import pandas as pd

from scripts.smc_price_action_engine import detect_bos_from_pivots
from smc_core import apply_layering
from smc_core.scoring import label_sweep_reversal, normalize_sweep_side
from smc_core.types import Orderblock, SmcStructure
from smc_integration import measurement_evidence

# reuse the layering meta builder from the heuristics suite
from tests.test_smc_core_layering_heuristics import _meta


# ── #1 outside-bar symmetry ────────────────────────────────────────────────
def _outside_bar_bars() -> pd.DataFrame:
    """Bars with a confirmed pivot-high (12) and pivot-low (5), then an outside
    bar (idx5) whose HIGH (13) breaks the pivot-high AND whose LOW (4) breaks the
    pivot-low in the same bar — the only shape that triggers a simultaneous break."""
    rows = [
        (1, 11.0, 7.0, 9.0),
        (2, 12.0, 9.0, 10.0),   # pivot HIGH = 12 (confirmed at idx2)
        (3, 11.0, 6.0, 8.0),
        (4, 10.0, 5.0, 7.0),    # pivot LOW = 5 (confirmed at idx4)
        (5, 11.0, 8.0, 9.0),    # prev of the outside bar: inside both pivots
        (6, 13.0, 4.0, 8.5),    # OUTSIDE bar: high 13 > 12 and low 4 < 5
    ]
    return pd.DataFrame(
        [
            {"timestamp": ts, "open": (h + low) / 2, "high": h, "low": low, "close": c, "volume": 1000.0}
            for ts, h, low, c in rows
        ]
    )


def _mirror(bars: pd.DataFrame, center: float) -> pd.DataFrame:
    """Reflect prices p -> center - p (high<->low swap) — must swap bull/bear."""
    out = bars.copy()
    out["high"] = center - bars["low"]
    out["low"] = center - bars["high"]
    out["open"] = center - bars["open"]
    out["close"] = center - bars["close"]
    return out


def _wick_bos(bars: pd.DataFrame) -> list[dict[str, Any]]:
    return detect_bos_from_pivots(
        bars, "AAPL", "15m", pivot_lookup=1,
        use_high_low_for_bullish=True, use_high_low_for_bearish=True,
    )


def test_simultaneous_break_is_not_forced_bearish_choch() -> None:
    """The down leg of an outside-bar break must be classified against the state
    BEFORE the bar (here: no prior structure -> BOS), not the UP just set by the
    up leg (which used to force it to CHOCH and the final state to DOWN)."""
    events = _wick_bos(_outside_bar_bars())
    by_dir = {e["dir"]: e for e in events}
    assert {"UP", "DOWN"} <= by_dir.keys(), events
    # Both legs break from a flat (None) prior state -> both are BOS, no bearish bias.
    assert by_dir["UP"]["kind"] == "BOS", events
    assert by_dir["DOWN"]["kind"] == "BOS", events


def test_bos_detection_is_price_mirror_invariant() -> None:
    """Reflecting the price series must swap UP<->DOWN while preserving each
    event's BOS/CHOCH kind — the definition of a mirror-symmetric detector."""
    bars = _outside_bar_bars()
    center = 20.0
    original = _wick_bos(bars)
    mirrored = _wick_bos(_mirror(bars, center))

    def key_set(evts: list[dict[str, Any]], flip: bool) -> set[tuple[str, str]]:
        flipped = {"UP": "DOWN", "DOWN": "UP"}
        return {((flipped[e["dir"]] if flip else e["dir"]), e["kind"]) for e in evts}

    # original with dirs flipped must equal the mirrored run's (dir, kind) set.
    assert key_set(original, flip=True) == key_set(mirrored, flip=False), (original, mirrored)


# ── #2 CHOCH keeps its kind in the structure light ─────────────────────────
def _hist_bars() -> pd.DataFrame:
    """Flat bars → no intrinsic structure, so STRUCTURE_LAST_EVENT baselines to
    ``"NONE"`` and only the event-under-test can set it."""
    return pd.DataFrame(
        [
            {"symbol": "AAPL", "timestamp": f"2024-01-{i:02d}T00:00:00Z", "open": 100.0,
             "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0}
            for i in range(1, 13)
        ]
    )


def _last_event(event: dict[str, Any], expected_direction: str) -> str:
    light = measurement_evidence._structure_state_light_for_event(
        event=event, family="BOS", history_bars=_hist_bars(), expected_direction=expected_direction,
    )
    return str(light["STRUCTURE_LAST_EVENT"])


def test_choch_event_keeps_choch_kind_in_structure_light() -> None:
    # STRUCTURE_LAST_EVENT is the consumer-facing light field; downstream
    # sweep-trap / reaction-zone / confluence branch on BOS_* vs CHOCH_*.
    assert _last_event({"kind": "CHOCH", "dir": "DOWN"}, "BEARISH") == "CHOCH_BEAR"
    assert _last_event({"kind": "CHOCH", "dir": "UP"}, "BULLISH") == "CHOCH_BULL"


def test_bos_event_still_maps_to_bos() -> None:
    assert _last_event({"kind": "BOS", "dir": "UP"}, "BULLISH") == "BOS_BULL"
    assert _last_event({"kind": "BOS", "dir": "DOWN"}, "BEARISH") == "BOS_BEAR"


def test_unknown_kind_is_not_silently_written_as_bos() -> None:
    # Fail-closed: an unknown kind leaves the flat-bars baseline ("NONE"),
    # it is NOT fabricated into a BOS event.
    assert _last_event({"kind": "MYSTERY", "dir": "UP"}, "BULLISH") == "NONE"


# ── #3 benchmark evaluators reject unknown/missing direction ───────────────
def _bench_bars() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"timestamp": float(1_700_000_000 + i * 900), "open": 100.0,
             "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0}
            for i in range(6)
        ]
    )


def test_bos_event_missing_or_unknown_direction_is_rejected() -> None:
    bars = _bench_bars()
    ts = float(bars.iloc[0]["timestamp"])
    assert measurement_evidence._evaluate_bos_event({"price": 100.0, "time": ts}, bars) is None
    assert measurement_evidence._evaluate_bos_event({"price": 100.0, "time": ts, "dir": "SIDEWAYS"}, bars) is None
    # a valid direction still evaluates
    assert measurement_evidence._evaluate_bos_event({"price": 100.0, "time": ts, "dir": "UP"}, bars) is not None


def test_zone_event_missing_or_unknown_direction_is_rejected() -> None:
    bars = _bench_bars()
    ts = float(bars.iloc[0]["timestamp"])
    base = {"low": 99.0, "high": 100.0, "anchor_ts": ts}
    assert measurement_evidence._evaluate_zone_event(base, bars, diagnostics_by_id={}) is None
    assert measurement_evidence._evaluate_zone_event({**base, "dir": "??"}, bars, diagnostics_by_id={}) is None
    assert measurement_evidence._evaluate_zone_event({**base, "dir": "BULL"}, bars, diagnostics_by_id={}) is not None


# ── #4 shared fail-closed sweep-side normalisation ─────────────────────────
def test_normalize_sweep_side_is_fail_closed() -> None:
    assert normalize_sweep_side("SELL_SIDE") == "BULLISH"
    assert normalize_sweep_side("BUY_SIDE") == "BEARISH"
    assert normalize_sweep_side("") == "NEUTRAL"
    assert normalize_sweep_side("GARBAGE") == "NEUTRAL"


def test_label_sweep_reversal_unknown_side_is_false() -> None:
    closes = [100.0, 90.0, 80.0]  # a big down move
    # buy-side => down-reversal labelled True
    assert label_sweep_reversal(100.0, "BUY_SIDE", closes) is True
    # unknown side must NOT borrow the down-reversal branch -> fail-closed False
    assert label_sweep_reversal(100.0, "MYSTERY", closes) is False
    assert label_sweep_reversal(100.0, "", closes) is False


def test_expected_direction_missing_side_is_neutral_not_bullish() -> None:
    assert measurement_evidence._expected_reversal_direction("") == "NEUTRAL"
    assert measurement_evidence._expected_event_direction({}, "SWEEP") == "NEUTRAL"
    assert measurement_evidence._expected_event_direction({"side": "SELL_SIDE"}, "SWEEP") == "BULLISH"


# ── #5 layering does not style an unknown direction as bearish/short ───────
def test_layering_unknown_direction_is_not_styled_short() -> None:
    structure = SmcStructure(
        orderblocks=[Orderblock(id="ob:x", low=100.0, high=101.0, dir=cast(Any, "SIDEWAYS"), valid=True)],
    )
    snapshot = apply_layering(
        structure,
        _meta(tech_strength=0.85, tech_bias="BEARISH", news_strength=0.4, news_bias="BEARISH"),
        generated_at=1709253600.0,
    )
    style = snapshot.layered.zone_styles["ob:x"]
    # Under strong bearish heat an invalid dir used to fall into the SHORT branch.
    assert style.bias == "NEUTRAL"
    assert style.trade_state != "ALLOWED"
