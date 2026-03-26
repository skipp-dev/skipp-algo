"""FastAPI mock for the SMC snapshot endpoint.

Provides fake BOS / OB / FVG / sweep / regime / tech / news data so
the Node bridge can be tested end-to-end without the real SMC runtime.

Start:
    uvicorn smc_mock_api:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, Query

app = FastAPI(title="SMC Mock API")


def _fake_smc(symbol: str, timeframe: str) -> dict[str, Any]:
    now = int(time.time())
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "bos": [
            {"time": now - 3600, "price": 100.0, "dir": "UP"},
            {"time": now - 1800, "price": 98.0, "dir": "DOWN"},
        ],
        "orderblocks": [
            {"low": 95.0, "high": 97.0, "dir": "BULL", "valid": True},
            {"low": 102.0, "high": 104.0, "dir": "BEAR", "valid": True},
        ],
        "fvg": [
            {"low": 97.0, "high": 99.0, "dir": "BULL", "valid": True},
        ],
        "liquidity_sweeps": [
            {"time": now - 900, "price": 96.5, "side": "BUY"},
            {"time": now - 600, "price": 103.2, "side": "SELL"},
        ],
        "regime": {"volume_regime": "NORMAL", "thin_fraction": 0.0},
        "technicalscore": 0.68,
        "technicalsignal": "BULLISH",
        "newsscore": 0.42,
    }


@app.get("/smc_snapshot")
def smc_snapshot(
    symbol: str = Query(...),
    timeframe: str = Query("15m"),
) -> dict[str, Any]:
    return _fake_smc(symbol, timeframe)
