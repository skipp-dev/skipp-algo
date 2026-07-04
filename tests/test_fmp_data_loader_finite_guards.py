"""Non-finite input guards for ``services.live_overlay_daemon.fmp_data_loader``.

Bug-hunt round 3: FMP payloads with ``null``/NaN/inf values crashed or
silently poisoned downstream consumers (ATR calculation, backtester,
SOFR-IORB spread). Rows with non-finite values are now dropped at ingestion.
"""

from __future__ import annotations

import math

from services.live_overlay_daemon.fmp_data_loader import FMPDataLoader


def _loader() -> FMPDataLoader:
    return FMPDataLoader(api_key="test-key")


def test_historical_price_drops_non_finite_candles(monkeypatch) -> None:
    loader = _loader()
    rows = [
        {"date": "2026-07-01 10:00:00", "open": 100.0, "high": 101.0,
         "low": 99.0, "close": 100.5, "volume": 1000},
        {"date": "2026-07-01 11:00:00", "open": float("nan"), "high": 101.0,
         "low": 99.0, "close": 100.5, "volume": 1000},
        {"date": "2026-07-01 12:00:00", "open": 100.0, "high": float("inf"),
         "low": 99.0, "close": 100.5, "volume": 1000},
        {"date": "2026-07-01 13:00:00", "open": 100.0, "high": 101.0,
         "low": 99.0, "close": None, "volume": 1000},
        {"date": "2026-07-01 14:00:00", "open": 100.5, "high": 102.0,
         "low": 100.0, "close": 101.5, "volume": None},
    ]
    monkeypatch.setattr(
        loader, "_fetch_chart_rows", lambda *args, **kwargs: list(rows)
    )

    candles = loader.get_historical_price("NVDA", period="1hour")

    # NaN open, inf high and None close rows dropped; None volume kept as 0.
    assert [c["timestamp"] for c in candles] == [
        "2026-07-01 10:00:00",
        "2026-07-01 14:00:00",
    ]
    assert [c["bar_index"] for c in candles] == [0, 1]
    assert candles[1]["volume"] == 0
    for c in candles:
        assert all(math.isfinite(c[k]) for k in ("open", "high", "low", "close"))


def test_sofr_iorb_spread_drops_non_finite_values(monkeypatch) -> None:
    loader = _loader()

    def fake_economic_data(name: str, limit: int = 500):
        if name == "sofr":
            return [
                {"date": "2026-07-01", "value": 4.30},
                {"date": "2026-07-02", "value": float("nan")},
                {"date": "2026-07-03", "value": None},
                {"date": "2026-07-06", "value": 4.35},
            ]
        return [
            {"date": "2026-07-01", "value": 4.32},
            {"date": "2026-07-02", "value": 4.31},
            {"date": "2026-07-03", "value": 4.33},
            {"date": "2026-07-06", "value": float("inf")},
        ]

    monkeypatch.setattr(loader, "get_economic_data", fake_economic_data)

    spread_map = loader.get_sofr_iorb_spread()

    # Only dates where BOTH series have finite values survive.
    assert spread_map == {"2026-07-01": (4.30, 4.32)}
