"""Real FastAPI SMC snapshot + TV-encoded endpoints.

Integrates with the live Python stack:
  - FMPClient for intraday OHLCV candles
  - VolumeRegimeDetector for regime state
  - TechnicalScorer for tech score
  - Lightweight SMC zone detector (BOS / OB / FVG / sweeps from candles)

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
from datetime import date
from pathlib import Path
from typing import Any

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
# Lightweight SMC Zone Detector
# ══════════════════════════════════════════════════════════

def _detect_bos(candles: list[dict[str, Any]], lookback: int = 20) -> list[dict[str, Any]]:
    """Detect Break of Structure from OHLCV candles.

    A BOS-UP occurs when price closes above a recent swing high.
    A BOS-DOWN occurs when price closes below a recent swing low.
    """
    if len(candles) < 5:
        return []

    bos_list: list[dict[str, Any]] = []
    swing_highs: list[tuple[int, float]] = []
    swing_lows: list[tuple[int, float]] = []

    # Find swing points (simple: higher than neighbors)
    for i in range(2, len(candles) - 2):
        h = candles[i]["high"]
        if h > candles[i - 1]["high"] and h > candles[i - 2]["high"] \
           and h > candles[i + 1]["high"] and h > candles[i + 2]["high"]:
            swing_highs.append((i, h))

        lo = candles[i]["low"]
        if lo < candles[i - 1]["low"] and lo < candles[i - 2]["low"] \
           and lo < candles[i + 1]["low"] and lo < candles[i + 2]["low"]:
            swing_lows.append((i, lo))

    # Check for BOS: close breaking recent swing
    recent_highs = swing_highs[-lookback:]
    recent_lows = swing_lows[-lookback:]

    for i in range(max(5, len(candles) - lookback), len(candles)):
        c = candles[i]
        # BOS UP — close above most recent swing high
        for _si, sh in reversed(recent_highs):
            if _si < i and c["close"] > sh:
                bos_list.append({
                    "time": _candle_ts(c),
                    "price": round(sh, 4),
                    "dir": "UP",
                })
                break
        # BOS DOWN — close below most recent swing low
        for _si, sl in reversed(recent_lows):
            if _si < i and c["close"] < sl:
                bos_list.append({
                    "time": _candle_ts(c),
                    "price": round(sl, 4),
                    "dir": "DOWN",
                })
                break

    # Deduplicate: keep last N unique by dir
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for b in reversed(bos_list):
        key = f"{b['dir']}_{b['price']}"
        if key not in seen:
            seen.add(key)
            deduped.append(b)
        if len(deduped) >= 10:
            break
    return list(reversed(deduped))


def _detect_orderblocks(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect order blocks — last candle before a strong impulsive move."""
    if len(candles) < 3:
        return []

    obs: list[dict[str, Any]] = []
    for i in range(1, len(candles) - 1):
        prev = candles[i - 1]
        curr = candles[i]
        nxt = candles[i + 1]

        body_prev = abs(prev["close"] - prev["open"])
        body_next = abs(nxt["close"] - nxt["open"])
        range_next = nxt["high"] - nxt["low"]

        if range_next <= 0:
            continue

        # Bullish OB: bearish candle followed by strong bullish impulse
        if prev["close"] < prev["open"] and nxt["close"] > nxt["open"] \
           and body_next > body_prev * 1.5 and body_next / range_next > 0.6:
            obs.append({
                "low": round(prev["low"], 4),
                "high": round(prev["high"], 4),
                "dir": "BULL",
                "valid": nxt["close"] > prev["high"],  # validated if impulse clears OB
            })

        # Bearish OB: bullish candle followed by strong bearish impulse
        if prev["close"] > prev["open"] and nxt["close"] < nxt["open"] \
           and body_next > body_prev * 1.5 and body_next / range_next > 0.6:
            obs.append({
                "low": round(prev["low"], 4),
                "high": round(prev["high"], 4),
                "dir": "BEAR",
                "valid": nxt["close"] < prev["low"],
            })

    # Keep only recent, valid ones
    valid = [ob for ob in obs if ob["valid"]]
    return valid[-8:]


def _detect_fvg(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect Fair Value Gaps (imbalance zones) from 3-candle patterns."""
    if len(candles) < 3:
        return []

    fvgs: list[dict[str, Any]] = []
    for i in range(2, len(candles)):
        c0 = candles[i - 2]
        c2 = candles[i]

        # Bullish FVG: gap between candle 0 high and candle 2 low
        if c2["low"] > c0["high"]:
            fvgs.append({
                "low": round(c0["high"], 4),
                "high": round(c2["low"], 4),
                "dir": "BULL",
                "valid": True,
            })
        # Bearish FVG: gap between candle 2 high and candle 0 low
        elif c2["high"] < c0["low"]:
            fvgs.append({
                "low": round(c2["high"], 4),
                "high": round(c0["low"], 4),
                "dir": "BEAR",
                "valid": True,
            })

    # Invalidate FVGs that have been filled by later candles
    last_price = candles[-1]["close"] if candles else 0
    for fvg in fvgs:
        if fvg["dir"] == "BULL" and last_price < fvg["low"]:
            fvg["valid"] = False
        elif fvg["dir"] == "BEAR" and last_price > fvg["high"]:
            fvg["valid"] = False

    valid = [f for f in fvgs if f["valid"]]
    return valid[-8:]


def _detect_sweeps(candles: list[dict[str, Any]], lookback: int = 30) -> list[dict[str, Any]]:
    """Detect liquidity sweeps — wick beyond recent S/R then close back inside."""
    if len(candles) < 5:
        return []

    sweeps: list[dict[str, Any]] = []
    start = max(5, len(candles) - lookback)

    for i in range(start, len(candles)):
        c = candles[i]
        # Recent high/low range
        window = candles[max(0, i - 20):i]
        if not window:
            continue
        recent_high = max(w["high"] for w in window)
        recent_low = min(w["low"] for w in window)

        # Buy-side sweep: wick above recent high, close back below
        if c["high"] > recent_high and c["close"] < recent_high:
            sweeps.append({
                "time": _candle_ts(c),
                "price": round(recent_high, 4),
                "side": "SELL",  # sell-side liquidity grabbed
            })
        # Sell-side sweep: wick below recent low, close back above
        if c["low"] < recent_low and c["close"] > recent_low:
            sweeps.append({
                "time": _candle_ts(c),
                "price": round(recent_low, 4),
                "side": "BUY",  # buy-side liquidity grabbed
            })

    return sweeps[-10:]


def _candle_ts(c: dict[str, Any]) -> int:
    """Extract Unix timestamp from a candle dict."""
    # FMP returns 'date' as ISO string, convert if needed
    ts = c.get("timestamp") or c.get("t")
    if ts and isinstance(ts, (int, float)):
        return int(ts)
    d = c.get("date", "")
    if d:
        try:
            import datetime as _dt
            if "T" in d:
                return int(_dt.datetime.fromisoformat(d).timestamp())
            return int(_dt.datetime.strptime(d, "%Y-%m-%d").timestamp())
        except Exception:
            pass
    return int(time.time())


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

    # 1) Fetch candles and detect SMC zones
    candles = _fetch_candles(symbol, timeframe)
    bos = _detect_bos(candles) if candles else []
    orderblocks = _detect_orderblocks(candles) if candles else []
    fvg = _detect_fvg(candles) if candles else []
    sweeps = _detect_sweeps(candles) if candles else []

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
        "bos": bos,
        "orderblocks": orderblocks,
        "fvg": fvg,
        "liquidity_sweeps": sweeps,
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
