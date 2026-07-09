"""Tests for scripts.calibrate_signal_followthrough — pure maths + fetch join."""
from __future__ import annotations

from typing import Any

from scripts import calibrate_signal_followthrough as cal


def _bars_from_et(rows: list[tuple[str, float, float, float]]) -> list[dict[str, Any]]:
    """Build raw FMP-shaped bars from (ET-time, high, low, close)."""
    return [{"date": t, "high": h, "low": lo, "close": c} for t, h, lo, c in rows]


def test_vol_bucket_edges() -> None:
    assert cal.vol_bucket(0.9) == "<1.0"
    assert cal.vol_bucket(1.0) == "1.0-1.5"
    assert cal.vol_bucket(1.5) == "1.5-2.0"
    assert cal.vol_bucket(2.0) == "2.0-3.0"
    assert cal.vol_bucket(3.0) == ">=3.0"


def test_normalize_bars_sorts_and_drops_bad() -> None:
    raw = [
        {"date": "2026-07-08 09:32:00", "high": 2, "low": 1, "close": 1.5},
        {"date": "2026-07-08 09:31:00", "high": 2, "low": 1, "close": 1.5},
        {"date": "bad", "high": 2, "low": 1, "close": 1.5},          # unparseable date
        {"date": "2026-07-08 09:33:00", "high": "x", "low": 1, "close": 1.5},  # bad number
    ]
    bars = cal.normalize_bars(raw)
    assert len(bars) == 2
    assert bars[0]["epoch"] < bars[1]["epoch"]  # ascending


def test_compute_outcome_bullish() -> None:
    start = cal._bar_epoch("2026-07-08 09:30:00")
    bars = cal.normalize_bars(_bars_from_et([
        ("2026-07-08 09:31:00", 102.0, 99.0, 101.0),  # MFE +2%, MAE -1%
        ("2026-07-08 09:32:00", 101.5, 100.0, 101.0),  # net +1% (last close 101)
    ]))
    ev = {"price": 100.0, "logged_epoch": start, "direction": "LONG", "level": "A1", "volume_ratio": 2.4}
    out = cal.compute_outcome(ev, bars, horizon_min=60, target_pct=0.5)
    assert out["mfe_pct"] == 2.0 and out["mae_pct"] == -1.0 and out["net_pct"] == 1.0
    assert out["hit_target"] is True and out["vol_bucket"] == "2.0-3.0"


def test_compute_outcome_bearish_inverts() -> None:
    start = cal._bar_epoch("2026-07-08 09:30:00")
    bars = cal.normalize_bars(_bars_from_et([
        ("2026-07-08 09:31:00", 100.5, 98.0, 99.0),  # for SHORT: MFE +2% (down), MAE -0.5%
    ]))
    ev = {"price": 100.0, "logged_epoch": start, "direction": "SHORT", "level": "A0", "volume_ratio": 3.2}
    out = cal.compute_outcome(ev, bars, horizon_min=60, target_pct=0.5)
    assert out["mfe_pct"] == 2.0 and out["mae_pct"] == -0.5 and out["net_pct"] == 1.0


def test_compute_outcome_windows_and_empty() -> None:
    start = cal._bar_epoch("2026-07-08 09:30:00")
    # Bar 90 min later is outside a 60-min horizon → no window → None.
    late = cal.normalize_bars(_bars_from_et([("2026-07-08 11:05:00", 110.0, 90.0, 105.0)]))
    ev = {"price": 100.0, "logged_epoch": start, "direction": "LONG", "level": "A1", "volume_ratio": 1.2}
    assert cal.compute_outcome(ev, late, horizon_min=60, target_pct=0.5) is None
    # Zero/absent entry price is unusable.
    assert cal.compute_outcome({"price": 0.0, "logged_epoch": start}, late, horizon_min=60, target_pct=0.5) is None


def test_aggregate_groups_by_level_and_bucket() -> None:
    outcomes = [
        {"level": "A1", "vol_bucket": "2.0-3.0", "mfe_pct": 2.0, "mae_pct": -1.0, "net_pct": 1.0, "hit_target": True},
        {"level": "A1", "vol_bucket": "2.0-3.0", "mfe_pct": 0.2, "mae_pct": -1.5, "net_pct": -0.8, "hit_target": False},
    ]
    table = cal.aggregate(outcomes)
    row = table["A1|2.0-3.0"]
    assert row["n"] == 2 and row["hit_target_rate"] == 0.5
    assert row["mean_net_pct"] == 0.1 and row["median_mfe_pct"] == 1.1


class _FakeClient:
    def __init__(self, bars: list[dict[str, Any]]) -> None:
        self._bars = bars
        self.calls: list[tuple[str, Any]] = []

    def get_intraday_chart(self, symbol: str, interval: str = "1min", day: Any = None, limit: int = 5000) -> list[dict[str, Any]]:
        self.calls.append((symbol, day))
        return self._bars


def test_run_joins_events_to_bars_with_per_symbol_day_cache() -> None:
    start = cal._bar_epoch("2026-07-08 09:30:00")
    client = _FakeClient(_bars_from_et([
        ("2026-07-08 09:31:00", 102.0, 99.5, 101.5),
        ("2026-07-08 09:33:00", 103.0, 100.0, 102.0),  # after both events → both get a window
    ]))
    events = [
        {"symbol": "NVDA", "logged_epoch": start, "price": 100.0, "direction": "LONG", "level": "A1", "volume_ratio": 2.5},
        {"symbol": "NVDA", "logged_epoch": start + 120, "price": 100.0, "direction": "LONG", "level": "A0", "volume_ratio": 3.1},
    ]
    result = cal.run(events, client, horizon_min=60, target_pct=0.5)
    assert result["n_scored"] == 2
    assert len(client.calls) == 1  # same symbol+day fetched once (cached)
    assert set(result["table"]) == {"A1|2.0-3.0", "A0|>=3.0"}
