"""Tests for the EV-07 structure -> FamilyEvent wiring adapter."""

from __future__ import annotations

from governance.family_event_adapter import (
    _BOS_LOOKAHEAD_BARS,
    family_events_from_structure,
)
from governance.family_returns import realized_return, to_build_spec
from scripts.build_family_metrics import build_bundle

_T0 = 1_700_000_000.0
_STEP = 86_400.0  # daily bars


def _bars(closes: list[float], *, highs: list[float] | None = None, lows: list[float] | None = None) -> list[dict]:
    highs = highs if highs is not None else [c + 1.0 for c in closes]
    lows = lows if lows is not None else [c - 1.0 for c in closes]
    return [
        {"timestamp": _T0 + i * _STEP, "high": highs[i], "low": lows[i], "close": closes[i]}
        for i in range(len(closes))
    ]


def test_bos_maps_to_immediate_long_positive_return() -> None:
    closes = [100.0 + i for i in range(20)]
    bars = _bars(closes)
    structure = {"bos": [{"id": "b1", "time": _T0 + 5 * _STEP, "price": 105.0, "dir": "UP"}]}

    events = family_events_from_structure(structure, bars)

    assert len(events) == 1
    event = events[0]
    assert event["family"] == "BOS"
    assert event["entry_mode"] == "immediate"
    assert event["entry_price"] == 105.0
    assert event["anchor_ts"] == _T0 + 5 * _STEP
    # Forward bars are strictly after the anchor index (bar 5 -> bars 6..13).
    assert len(event["forward_closes"]) == _BOS_LOOKAHEAD_BARS
    assert event["forward_closes"][0] == 106.0
    assert all(ts > event["anchor_ts"] for ts in event["forward_timestamps"])

    ret = realized_return(event)
    assert ret is not None and ret > 0.0


def test_sweep_sell_side_maps_to_long_reversal() -> None:
    closes = [100.0 + i for i in range(20)]
    bars = _bars(closes)
    structure = {"liquidity_sweeps": [{"id": "s1", "time": _T0 + 4 * _STEP, "price": 104.0, "side": "SELL_SIDE"}]}

    events = family_events_from_structure(structure, bars)

    assert len(events) == 1
    assert events[0]["family"] == "SWEEP"
    assert events[0]["entry_mode"] == "immediate"
    assert events[0]["direction"] == "LONG"
    assert realized_return(events[0]) is not None


def test_ob_zone_maps_to_retest_touch() -> None:
    # Dip into the zone at bar 7, then rally.
    closes = [110.0, 109.0, 108.0, 107.0, 106.0, 105.0, 102.0, 100.0, 103.0, 106.0, 109.0, 112.0, 115.0, 118.0]
    bars = _bars(closes)
    structure = {"orderblocks": [{"id": "ob1", "time": _T0 + 5 * _STEP, "low": 99.0, "high": 101.0, "dir": "BULL"}]}

    events = family_events_from_structure(structure, bars)

    assert len(events) == 1
    event = events[0]
    assert event["family"] == "OB"
    assert event["entry_mode"] == "retest_touch"
    assert event["zone_low"] == 99.0
    assert event["zone_high"] == 101.0
    assert realized_return(event) is not None


def test_unanchored_event_is_dropped() -> None:
    bars = _bars([100.0 + i for i in range(20)])
    # Anchor far beyond the last bar timestamp -> no anchor index.
    structure = {"bos": [{"id": "b1", "time": _T0 + 999 * _STEP, "price": 105.0, "dir": "UP"}]}

    assert family_events_from_structure(structure, bars) == []


def test_degenerate_event_is_dropped() -> None:
    bars = _bars([100.0 + i for i in range(20)])
    structure = {
        "bos": [{"id": "b1", "time": _T0 + 5 * _STEP, "price": 0.0, "dir": "UP"}],
        "orderblocks": [{"id": "ob1", "time": _T0 + 5 * _STEP, "low": 101.0, "high": 99.0, "dir": "BULL"}],
    }

    assert family_events_from_structure(structure, bars) == []


def test_anchor_on_last_bar_is_dropped() -> None:
    closes = [100.0 + i for i in range(10)]
    bars = _bars(closes)
    # Anchor at the final bar -> no forward bar available.
    structure = {"bos": [{"id": "b1", "time": _T0 + 9 * _STEP, "price": 109.0, "dir": "UP"}]}

    assert family_events_from_structure(structure, bars) == []


def test_buy_side_sweep_maps_to_short() -> None:
    closes = [100.0 - i for i in range(20)]
    bars = _bars(closes)
    structure = {"liquidity_sweeps": [{"id": "s1", "time": _T0 + 4 * _STEP, "price": 96.0, "side": "BUY_SIDE"}]}

    events = family_events_from_structure(structure, bars)

    assert len(events) == 1
    assert events[0]["family"] == "SWEEP"
    assert events[0]["direction"] == "SHORT"


def test_unknown_sweep_side_is_dropped() -> None:
    bars = _bars([100.0 + i for i in range(20)])
    # A malformed side must not coerce into a spurious short.
    structure = {"liquidity_sweeps": [{"id": "s1", "time": _T0 + 4 * _STEP, "price": 104.0, "side": "MIDDLE"}]}

    assert family_events_from_structure(structure, bars) == []


def test_pine_style_zone_without_anchor_is_dropped() -> None:
    # Raw Pine OB/FVG payloads carry no time/anchor_ts (smc_core.types.Orderblock
    # / Fvg have no formation timestamp). Such zones cannot be anchored without
    # fabricating a position in time, so the adapter drops them rather than
    # anchoring to bar 0. Zone returns require the explicit-recompute path,
    # which emits anchor_ts. This guards the documented honest limitation.
    bars = _bars([100.0 + i for i in range(20)])
    structure = {
        "orderblocks": [{"id": "ob1", "low": 99.0, "high": 101.0, "dir": "BULL"}],
        "fvg": [{"id": "f1", "low": 99.0, "high": 101.0, "dir": "BULL"}],
    }

    assert family_events_from_structure(structure, bars) == []



def test_round_trip_through_build_family_metrics() -> None:
    bos_events = []
    for i in range(40):
        anchor = _T0 + (10 + i) * 60.0
        # Vary the entry level so realized returns are not constant.
        bos_events.append({"id": f"b{i}", "time": anchor, "price": 100.0 + (i % 5) * 0.1, "dir": "UP"})
    # One long, rising series of bars covering every anchor + forward window.
    closes = [50.0 + 0.25 * i for i in range(400)]
    bars = [
        {"timestamp": _T0 + i * 60.0, "high": closes[i] + 0.2, "low": closes[i] - 0.2, "close": closes[i]}
        for i in range(len(closes))
    ]
    structure = {"bos": bos_events}

    events = family_events_from_structure(structure, bars)
    assert len(events) == 40

    spec = to_build_spec(events, as_of=_T0 + 10_000 * 60.0)
    bundle = build_bundle(spec)

    bos_metrics = next(m for m in bundle if m["family"] == "BOS")
    assert bos_metrics["psr"] is not None


def _volume_bars(closes: list[float], volumes: list[float]) -> list[dict]:
    return [
        {
            "timestamp": _T0 + i * _STEP,
            "open": closes[i],
            "high": closes[i] + 1.0,
            "low": closes[i] - 1.0,
            "close": closes[i],
            "volume": volumes[i],
        }
        for i in range(len(closes))
    ]


def test_vrvp_shadow_scalars_attached_recorded_only() -> None:
    # 30 volume-bearing bars; a BOS anchored deep enough (idx 20) that the
    # trailing ATR_PERIOD window is fully populated, so the VRVP profile builds.
    closes = [100.0 + (i % 3) for i in range(30)]
    volumes = [1000.0 for _ in range(30)]
    bars = _volume_bars(closes, volumes)
    anchor_idx = 20
    structure = {
        "bos": [
            {
                "id": "b1",
                "time": _T0 + anchor_idx * _STEP,
                "price": closes[anchor_idx],
                "dir": "UP",
            }
        ]
    }

    events = family_events_from_structure(structure, bars)

    assert len(events) == 1
    event = events[0]
    # Both VRVP shadow scalars ride alongside the event, recorded-only.
    assert "vrvp_vpoc_dist" in event
    assert "vrvp_va_pos" in event
    assert isinstance(event["vrvp_vpoc_dist"], float)
    assert event["vrvp_va_pos"] in (-1.0, 0.0, 1.0)


def test_vrvp_shadow_scalars_absent_without_volume() -> None:
    # OHLCV-less run (no volume key) -> the profile cannot be built -> the VRVP
    # scalars are honestly absent, never invented.
    closes = [100.0 + (i % 3) for i in range(30)]
    bars = _bars(closes)
    anchor_idx = 20
    structure = {
        "bos": [
            {
                "id": "b1",
                "time": _T0 + anchor_idx * _STEP,
                "price": closes[anchor_idx],
                "dir": "UP",
            }
        ]
    }

    events = family_events_from_structure(structure, bars)

    assert len(events) == 1
    assert "vrvp_vpoc_dist" not in events[0]
    assert "vrvp_va_pos" not in events[0]


def _bos_structure(anchor_idx: int, closes: list[float]) -> dict:
    return {
        "bos": [
            {
                "id": "b1",
                "time": _T0 + anchor_idx * _STEP,
                "price": closes[anchor_idx],
                "dir": "UP",
            }
        ]
    }


def test_cross_lead_lag_absent_without_benchmark() -> None:
    # No benchmark supplied -> the cross-asset lead-lag feature is honestly
    # absent and behaviour is identical to every existing caller (back-compat).
    closes = [100.0 + i + (i % 5) * 0.7 for i in range(30)]
    bars = _bars(closes)
    anchor_idx = 20
    structure = _bos_structure(anchor_idx, closes)

    events = family_events_from_structure(structure, bars)

    assert len(events) == 1
    assert "cross_lead_lag" not in events[0]


def test_cross_lead_lag_attached_with_aligned_benchmark() -> None:
    # Index- and timestamp-aligned benchmark with its own curved returns ->
    # the lead-lag ratio rides alongside the event, recorded-only.
    closes = [100.0 + i + (i % 5) * 0.7 for i in range(30)]
    bars = _bars(closes)
    bench_closes = [200.0 + i * 0.5 + (i % 4) * 1.3 for i in range(30)]
    benchmark = _bars(bench_closes)
    anchor_idx = 20
    structure = _bos_structure(anchor_idx, closes)

    events = family_events_from_structure(structure, bars, benchmark_bars=benchmark)

    assert len(events) == 1
    assert "cross_lead_lag" in events[0]
    assert isinstance(events[0]["cross_lead_lag"], float)


def test_cross_lead_lag_degrades_when_benchmark_misaligned() -> None:
    # Benchmark timestamps shifted by a second -> strict alignment fails -> the
    # benchmark is dropped and the feature is absent (never paired misaligned).
    closes = [100.0 + i + (i % 5) * 0.7 for i in range(30)]
    bars = _bars(closes)
    bench_closes = [200.0 + i * 0.5 + (i % 4) * 1.3 for i in range(30)]
    benchmark = [
        {**b, "timestamp": b["timestamp"] + 1.0} for b in _bars(bench_closes)
    ]
    anchor_idx = 20
    structure = _bos_structure(anchor_idx, closes)

    events = family_events_from_structure(structure, bars, benchmark_bars=benchmark)

    assert len(events) == 1
    assert "cross_lead_lag" not in events[0]
