from __future__ import annotations

import pandas as pd

from scripts.explicit_structure_profiles import build_structure_profile


def _bars(symbol: str = "AAPL", n: int = 64) -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    rows: list[dict] = []
    for i, ts in enumerate(timestamps):
        cycle = (i % 10) - 5
        base = 100.0 + i * 0.05 + cycle * 0.15
        close = base + (0.35 if i % 3 == 0 else -0.25 if i % 4 == 0 else 0.05)
        high = max(base, close) + 0.45
        low = min(base, close) - 0.45
        rows.append(
            {
                "symbol": symbol,
                "timestamp": ts,
                "open": base,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1000 + i,
            }
        )
    return pd.DataFrame(rows)


def test_hybrid_profile_emits_auxiliary_and_diagnostics() -> None:
    result = build_structure_profile(_bars(), symbol="AAPL", timeframe="15m", profile="hybrid_default")

    assert isinstance(result.bos, list)
    assert isinstance(result.orderblocks, list)
    assert isinstance(result.fvg, list)
    assert isinstance(result.liquidity_sweeps, list)

    assert set(result.auxiliary.keys()) == {
        "session_ranges",
        "session_pivots",
        "liquidity_lines",
        "ipda_operating_range",
        "htf_fvg_bias",
        "broken_fractal_signals",
    }
    assert result.diagnostics["profile"] == "hybrid_default"


def test_session_liquidity_profile_suppresses_orderblocks() -> None:
    result = build_structure_profile(_bars(), symbol="AAPL", timeframe="15m", profile="session_liquidity")
    assert result.diagnostics["profile"] == "session_liquidity"
    assert result.orderblocks == []


def test_conservative_profile_filters_invalid_zones() -> None:
    result = build_structure_profile(_bars(), symbol="AAPL", timeframe="15m", profile="conservative")
    assert result.diagnostics["profile"] == "conservative"
    assert all(bool(row.get("valid", True)) for row in result.orderblocks)
    assert all(bool(row.get("valid", True)) for row in result.fvg)
