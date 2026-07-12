"""Wiring: _build_context_payloads guards forming bars before vol-regime.

The databento context export can capture a still-forming trailing bar; feeding
it to ``compute_vol_regime`` would contaminate the current-bar ATR / variance.
``_build_context_payloads`` passes the frame through
``guard_closed_bars(interval=timeframe.lower(), now=time.time())`` first. These
tests pin (a) that every canonical timeframe resolves to a guard interval token
and (b) that a forming trailing bar is dropped before vol-regime, while a fully
closed frame is passed through untouched.
"""
from __future__ import annotations

import types

import pandas as pd
import pytest

import smc_integration.service as svc
from smc_core.bar_close_guard import guard_closed_bars
from smc_integration.timeframes import CANONICAL_TIMEFRAMES


def _frame(timestamps: list[float]) -> pd.DataFrame:
    n = len(timestamps)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [1.0] * n,
            "high": [2.0] * n,
            "low": [0.5] * n,
            "close": [1.5] * n,
            "volume": [100.0] * n,
            "symbol": ["X"] * n,
        }
    )


@pytest.mark.parametrize("timeframe", CANONICAL_TIMEFRAMES)
def test_every_canonical_timeframe_resolves_to_a_guard_interval(timeframe: str) -> None:
    # timeframe.lower() must be a known guard interval — otherwise the live
    # wiring would raise ValueError for that timeframe in production.
    guard_closed_bars(_frame([1_700_000_000.0]), interval=timeframe.lower(), now=None)


def _drive_context_payloads(monkeypatch: pytest.MonkeyPatch, frame: pd.DataFrame) -> dict:
    captured: dict = {}
    real_vol = svc.compute_vol_regime

    def spy(df: pd.DataFrame):
        captured["n"] = len(df)
        captured["max_ts"] = float(df["timestamp"].max())
        return real_vol(df)

    monkeypatch.setattr(svc, "_load_symbol_bars_for_context", lambda _s, _tf: frame)
    monkeypatch.setattr(svc, "build_structure_qualifiers", lambda *a, **k: {})
    monkeypatch.setattr(svc, "build_session_liquidity_context", lambda *a, **k: {})
    monkeypatch.setattr(svc, "build_htf_bias_context", lambda *a, **k: {})
    monkeypatch.setattr(svc, "normalize_meta", lambda _m: {})
    monkeypatch.setattr(svc, "derive_base_signals", lambda _m: {"global_strength": 0.5})
    monkeypatch.setattr(svc, "build_ensemble_quality", lambda **k: object())
    monkeypatch.setattr(svc, "serialize_ensemble_quality", lambda _q: {})
    monkeypatch.setattr(svc, "compute_vol_regime", spy)

    snapshot = types.SimpleNamespace(meta={}, generated_at=1_700_000_000.0)
    svc._build_context_payloads("X", "15m", snapshot)
    return captured


def test_forming_trailing_bar_dropped_before_vol_regime(monkeypatch: pytest.MonkeyPatch) -> None:
    now = svc.time.time()
    step = 15 * 60
    # three closed 15m bars + one forming bar that opened mid-interval (its
    # close-time step-seconds later is still in the future).
    closed = [now - 4 * step, now - 3 * step, now - 2 * step]
    forming_open = now - step // 2
    captured = _drive_context_payloads(monkeypatch, _frame([*closed, forming_open]))

    assert captured["n"] == 3, "forming trailing bar must be dropped before vol-regime"
    assert captured["max_ts"] <= now


def test_all_closed_bars_pass_through_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    now = svc.time.time()
    step = 15 * 60
    closed = [now - 4 * step, now - 3 * step, now - 2 * step]  # all closed
    captured = _drive_context_payloads(monkeypatch, _frame(closed))

    assert captured["n"] == 3, "no bar may be dropped when every bar is closed"


def test_resample_intraday_buckets_per_second_rows_to_timeframe() -> None:
    # 900 one-second rows (15 min) → three 5m bars (300s each). base is bucket-aligned.
    base = 1_700_000_100  # divisible by 300
    closes = [float(i) for i in range(900)]
    df = pd.DataFrame(
        {
            "timestamp": [base + i for i in range(900)],
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1.0] * 900,
        }
    )
    out = svc._resample_intraday_to_timeframe(df, "5m")
    assert list(out["timestamp"]) == [base, base + 300, base + 600]
    first = out.iloc[0]
    assert first["open"] == 0.0  # first of the bucket
    assert first["close"] == 299.0  # last of the bucket
    assert first["high"] == 300.0  # max high
    assert first["low"] == -1.0  # min low
    assert first["volume"] == 300.0  # summed


def test_resample_unknown_timeframe_fails_open_unchanged() -> None:
    df = _frame([1.0, 2.0, 3.0])
    out = svc._resample_intraday_to_timeframe(df, "bogus")
    assert len(out) == 3  # unknown token → rows returned unchanged, not dropped
