"""Real FastAPI SMC snapshot + TV-encoded endpoints.

Integrates with the live Python stack:
  - FMPClient for intraday OHLCV candles
  - VolumeRegimeDetector for regime state
  - TechnicalScorer for tech score
  - Canonical structure producer (scripts/explicit_structure_from_bars)

Start (production):
    uvicorn smc_tv_bridge.smc_api:app --host 0.0.0.0 --port 8000

Start (mock — no FMP key needed):
    SMC_USE_MOCK=1 uvicorn smc_tv_bridge.smc_api:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

# ── Ensure repo root is importable ──────────────────────
_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

logger = logging.getLogger("smc_api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="SMC TV API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

USE_MOCK = os.environ.get("SMC_USE_MOCK", "0") == "1"

# ── Timeframe mapping ──────────────────────────────────
_TF_TO_FMP_INTERVAL: dict[str, str] = {
    "5m": "5min",
    "15m": "15min",
    "1H": "1hour",
    "4H": "4hour",
}

_TF_TO_TECH_INTERVAL: dict[str, str] = {
    "5m": "5m",
    "15m": "15m",
    "1H": "1h",
    "4H": "4h",
}

_TF_CANDLE_LIMIT: dict[str, int] = {
    "5m": 200,
    "15m": 100,
    "1H": 50,
    "4H": 30,
}


# ══════════════════════════════════════════════════════════
# Candle timestamp extraction
# ══════════════════════════════════════════════════════════

def _candle_ts(c: dict[str, Any]) -> int:
    """Extract Unix timestamp from a candle dict."""
    ts = c.get("timestamp") or c.get("t")
    if ts and isinstance(ts, (int, float)):
        return int(ts)
    d = c.get("date", "")
    if d:
        try:
            if "T" in d:
                return int(datetime.fromisoformat(d).timestamp())
            return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        except Exception:
            pass
    return int(time.time())


# ══════════════════════════════════════════════════════════
# Candle → DataFrame adapter
# ══════════════════════════════════════════════════════════

def candles_to_dataframe(candles: list[dict[str, Any]], symbol: str) -> pd.DataFrame:
    """Convert FMP-style candle dicts to the DataFrame shape expected by
    the canonical structure producer (symbol, timestamp, OHLCV)."""
    if not candles:
        return pd.DataFrame(columns=["symbol", "timestamp", "open", "high", "low", "close", "volume"])

    rows: list[dict[str, Any]] = []
    sym = symbol.strip().upper()
    for c in candles:
        ts = _candle_ts(c)
        rows.append({
            "symbol": sym,
            "timestamp": ts,
            "open": float(c.get("open", 0)),
            "high": float(c.get("high", 0)),
            "low": float(c.get("low", 0)),
            "close": float(c.get("close", 0)),
            "volume": float(c.get("volume", 0)),
        })
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════
# Canonical structure → bridge response adapter
# ══════════════════════════════════════════════════════════

_SWEEP_SIDE_MAP = {"BUY_SIDE": "BUY", "SELL_SIDE": "SELL"}


def _adapt_bos(canonical_bos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip canonical extras, keep only {time, price, dir}."""
    return [
        {"time": int(b.get("time", b.get("anchor_ts", 0))), "price": b["price"], "dir": b["dir"]}
        for b in canonical_bos
    ]


def _adapt_zones(canonical_zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip canonical extras, keep only {low, high, dir, valid}."""
    return [
        {"low": z["low"], "high": z["high"], "dir": z["dir"], "valid": z.get("valid", True)}
        for z in canonical_zones
    ]


def _adapt_sweeps(canonical_sweeps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip canonical extras, map SELL_SIDE→SELL / BUY_SIDE→BUY."""
    return [
        {
            "time": int(s.get("time", s.get("anchor_ts", 0))),
            "price": s["price"],
            "side": _SWEEP_SIDE_MAP.get(s["side"], s["side"]),
        }
        for s in canonical_sweeps
    ]


def _detect_structure_canonical(candles: list[dict[str, Any]], symbol: str, timeframe: str) -> dict[str, list[dict[str, Any]]]:
    """Run the canonical structure producer and adapt its output to bridge shape."""
    df = candles_to_dataframe(candles, symbol)
    if df.empty:
        return {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}

    from scripts.explicit_structure_from_bars import build_full_structure_from_bars

    try:
        raw = build_full_structure_from_bars(df, symbol=symbol, timeframe=timeframe)
    except (ValueError, KeyError) as exc:
        logger.warning("Canonical structure failed for %s/%s: %s", symbol, timeframe, exc)
        return {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}

    return {
        "bos": _adapt_bos(raw.get("bos", [])),
        "orderblocks": _adapt_zones(raw.get("orderblocks", [])),
        "fvg": _adapt_zones(raw.get("fvg", [])),
        "liquidity_sweeps": _adapt_sweeps(raw.get("liquidity_sweeps", [])),
    }

# ══════════════════════════════════════════════════════════
# Provider layer — either real FMP or mock
# ══════════════════════════════════════════════════════════

_fmp_client = None
_volume_regime = None
_tech_scorer = None


def _get_fmp_client():
    global _fmp_client
    if _fmp_client is None:
        from open_prep.macro import FMPClient
        _fmp_client = FMPClient.from_env()
        logger.info("FMPClient initialized")
    return _fmp_client


def _get_volume_regime():
    global _volume_regime
    if _volume_regime is None:
        from open_prep.realtime_signals import VolumeRegimeDetector
        _volume_regime = VolumeRegimeDetector()
        logger.info("VolumeRegimeDetector initialized")
    return _volume_regime


def _get_tech_scorer():
    global _tech_scorer
    if _tech_scorer is None:
        from open_prep.realtime_signals import TechnicalScorer
        _tech_scorer = TechnicalScorer()
        logger.info("TechnicalScorer initialized")
    return _tech_scorer


def _fetch_candles(symbol: str, timeframe: str) -> list[dict[str, Any]]:
    """Fetch intraday OHLCV candles from FMP."""
    client = _get_fmp_client()
    interval = _TF_TO_FMP_INTERVAL.get(timeframe, "15min")
    limit = _TF_CANDLE_LIMIT.get(timeframe, 100)
    try:
        candles = client.get_intraday_chart(symbol, interval=interval, limit=limit)
        # FMP returns newest-first; reverse to oldest-first for detection
        if candles and isinstance(candles, list):
            candles.sort(key=lambda c: c.get("date", ""))
        return candles or []
    except Exception as exc:
        logger.warning("Failed to fetch candles for %s/%s: %s", symbol, timeframe, exc)
        return []


def _get_news_score(symbol: str) -> float:
    """Best-effort news score for a symbol from the newsstack."""
    try:
        from newsstack_fmp import get_news_score
        return get_news_score(symbol)
    except Exception:
        return 0.0


# ══════════════════════════════════════════════════════════
# Mock provider
# ══════════════════════════════════════════════════════════

def _mock_snapshot(symbol: str, timeframe: str) -> dict[str, Any]:
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


# ══════════════════════════════════════════════════════════
# Core snapshot builder
# ══════════════════════════════════════════════════════════

def build_smc_snapshot(symbol: str, timeframe: str) -> dict[str, Any]:
    """Build full SMC snapshot for a symbol + timeframe."""
    if USE_MOCK:
        return _mock_snapshot(symbol, timeframe)

    # 1) Fetch candles and detect SMC zones via canonical producer
    candles = _fetch_candles(symbol, timeframe)
    structure = _detect_structure_canonical(candles, symbol, timeframe)

    # 2) Volume regime (needs a recent quote to update)
    regime_det = _get_volume_regime()
    try:
        client = _get_fmp_client()
        quotes_raw = client.get_batch_quotes([symbol])
        quotes = {q["symbol"]: q for q in quotes_raw} if quotes_raw else {}
        regime_det.update(quotes)
    except Exception as exc:
        logger.debug("Regime update skipped: %s", exc)

    # 3) Technical score
    tech_interval = _TF_TO_TECH_INTERVAL.get(timeframe, "15m")
    scorer = _get_tech_scorer()
    tech_data = scorer.get_technical_data(symbol, tech_interval)

    # 4) News score
    news_score = _get_news_score(symbol)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "bos": structure["bos"],
        "orderblocks": structure["orderblocks"],
        "fvg": structure["fvg"],
        "liquidity_sweeps": structure["liquidity_sweeps"],
        "regime": {
            "volume_regime": regime_det.regime,
            "thin_fraction": regime_det.thin_fraction,
        },
        "technicalscore": tech_data.get("technical_score", 0.5),
        "technicalsignal": tech_data.get("technical_signal", "NEUTRAL"),
        "newsscore": news_score,
    }


# ══════════════════════════════════════════════════════════
# Encoders (pipe-delimited for Pine Script)
# ══════════════════════════════════════════════════════════

def encode_levels(levels: list[dict[str, Any]]) -> str:
    return ";".join(f"{int(l['time'])}|{l['price']}|{l['dir']}" for l in levels)


def encode_zones(zones: list[dict[str, Any]]) -> str:
    return ";".join(
        f"{z['low']}|{z['high']}|{z['dir']}|{int(z.get('valid', True))}"
        for z in zones
    )


def encode_sweeps(sweeps: list[dict[str, Any]]) -> str:
    return ";".join(f"{int(s['time'])}|{s['price']}|{s['side']}" for s in sweeps)


# ══════════════════════════════════════════════════════════
# Endpoints
# ══════════════════════════════════════════════════════════

@app.get("/smc_snapshot")
def smc_snapshot_endpoint(
    symbol: str = Query(..., description="Ticker symbol, e.g. AAPL"),
    timeframe: str = Query("15m", description="Timeframe: 5m, 15m, 1H, 4H"),
) -> dict[str, Any]:
    """Full SMC snapshot (nested JSON)."""
    symbol = symbol.upper()
    if timeframe not in _TF_TO_FMP_INTERVAL:
        return {"error": f"unsupported timeframe: {timeframe}"}
    return build_smc_snapshot(symbol, timeframe)


@app.get("/smc_tv")
def smc_tv_endpoint(
    symbol: str = Query(..., description="Ticker symbol"),
    tf: str = Query("15m", description="Timeframe: 5m, 15m, 1H, 4H"),
) -> dict[str, Any]:
    """Pine-friendly pipe-encoded SMC snapshot."""
    symbol = symbol.upper()
    if tf not in _TF_TO_FMP_INTERVAL:
        return {"error": f"unsupported timeframe: {tf}"}

    snap = build_smc_snapshot(symbol, tf)
    return {
        "bos": encode_levels(snap["bos"]),
        "ob": encode_zones(snap["orderblocks"]),
        "fvg": encode_zones(snap["fvg"]),
        "sweeps": encode_sweeps(snap["liquidity_sweeps"]),
        "regime": snap["regime"]["volume_regime"],
        "tech": snap["technicalscore"],
        "news": snap["newsscore"],
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "mock": USE_MOCK,
        "fmp_available": not USE_MOCK,
    }
