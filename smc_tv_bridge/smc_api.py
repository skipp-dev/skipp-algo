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
import math
import os
import sys
import threading
import time
from datetime import UTC, datetime
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
            return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=UTC).timestamp())
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
# Provider layer — adapter-based (see ADR-001)
# ══════════════════════════════════════════════════════════

from smc_tv_bridge.adapters import CandleProvider, RegimeProvider, TechnicalScoreProvider  # noqa: E402,I001 -- adapter-based Provider layer per ADR-001, imported after upstream type defs

_candle_provider: CandleProvider | None = None
_regime_provider: RegimeProvider | None = None
_tech_provider: TechnicalScoreProvider | None = None


def _get_candle_provider() -> CandleProvider:
    global _candle_provider
    if _candle_provider is None:
        from smc_tv_bridge.adapters_open_prep import FMPCandleProvider
        _candle_provider = FMPCandleProvider()
    return _candle_provider


def _get_regime_provider() -> RegimeProvider:
    global _regime_provider
    if _regime_provider is None:
        from smc_tv_bridge.adapters_open_prep import OpenPrepRegimeProvider
        _regime_provider = OpenPrepRegimeProvider()
    return _regime_provider


def _get_tech_provider() -> TechnicalScoreProvider:
    global _tech_provider
    if _tech_provider is None:
        from smc_tv_bridge.adapters_open_prep import OpenPrepTechnicalScoreProvider
        _tech_provider = OpenPrepTechnicalScoreProvider()
    return _tech_provider


def _fetch_candles(symbol: str, timeframe: str) -> list[dict[str, Any]]:
    """Fetch intraday OHLCV candles via the candle adapter."""
    provider = _get_candle_provider()
    interval = _TF_TO_FMP_INTERVAL.get(timeframe, "15min")
    limit = _TF_CANDLE_LIMIT.get(timeframe, 100)
    candles: list[dict[str, Any]] = provider.fetch_candles(symbol, interval, limit)
    return candles


def _get_news_score(symbol: str) -> float:
    """Best-effort news score for a symbol from the newsstack."""
    try:
        from newsstack_fmp import get_news_score
        return float(get_news_score(symbol))
    except Exception:
        return 0.0


# ── VIX (market-wide volatility) overlay source ─────────────
# VIX is market-wide, so one fetch serves every symbol within the TTL window.
# The value is cached (TTL=300s) and refreshed under a lock so a cold/expired
# cache coalesces concurrent /smc_live calls into a single upstream request,
# capping FMP load. Fail-closed: any miss yields None and the overlay omits
# ``vix_level`` so Pine keeps its baked ``mp.*`` fallback (never loosens).
_VIX_SYMBOL = "^VIX"
_VIX_TTL_SECONDS = 300.0
_VIX_MOCK_LEVEL = 18.5
_vix_lock = threading.Lock()
_vix_cache: dict[str, float | None] = {"value": None, "fetched_at": 0.0}


def _fetch_vix_uncached() -> float | None:
    """Fetch the current VIX level via the shared FMP client. None on miss.

    Network seam for :func:`_get_vix_level`; reuses the candle provider's FMP
    client (same ``getattr(..., "_client")`` access pattern as
    :func:`build_smc_snapshot`). Fail-closed -- any error or a non-positive /
    non-finite price yields None.
    """
    try:
        fmp_client = getattr(_get_candle_provider(), "_client", None)
        if fmp_client is None:
            return None
        quote = fmp_client.get_index_quote(_VIX_SYMBOL)
        if not isinstance(quote, dict):
            return None
        price = quote.get("price")
        if price is None:
            return None
        level = float(price)
    except (ValueError, TypeError, KeyError, AttributeError, RuntimeError, OSError) as exc:
        logger.debug("VIX fetch skipped: %s", exc)
        return None
    if not math.isfinite(level) or level <= 0.0:
        return None
    return level


def _get_vix_level() -> float | None:
    """Cached market-wide VIX level (TTL=300s, thread-safe). None when down.

    The fetch is coalesced under ``_vix_lock`` so a cold or expired cache makes
    exactly one upstream request even under concurrent load; both successes and
    misses are throttled to once per TTL. Holding the lock across the (bounded-
    timeout) FMP fetch is acceptable because VIX is market-wide and refreshed at
    most once per TTL window.
    """
    if USE_MOCK:
        return _VIX_MOCK_LEVEL
    now = time.monotonic()
    with _vix_lock:
        fetched_at = _vix_cache["fetched_at"] or 0.0
        if fetched_at > 0.0 and (now - fetched_at) < _VIX_TTL_SECONDS:
            return _vix_cache["value"]
        _vix_cache["value"] = _fetch_vix_uncached()
        _vix_cache["fetched_at"] = time.monotonic()
        return _vix_cache["value"]


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
    regime = _get_regime_provider()
    try:
        candle_prov = _get_candle_provider()
        # Use the underlying FMP client for quote data when available
        fmp_client = getattr(candle_prov, "_client", None)
        if fmp_client is not None:
            quotes_raw = fmp_client.get_batch_quotes([symbol])
            quotes = {q["symbol"]: q for q in quotes_raw} if quotes_raw else {}
        else:
            quotes = {}
        regime.update(quotes)
    except Exception as exc:
        logger.debug("Regime update skipped: %s", exc)

    # 3) Technical score
    tech_interval = _TF_TO_TECH_INTERVAL.get(timeframe, "15m")
    tech_prov = _get_tech_provider()
    tech_data = tech_prov.get_technical_data(symbol, tech_interval)

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
            "volume_regime": regime.regime,
            "thin_fraction": regime.thin_fraction,
        },
        "technicalscore": tech_data.get("technical_score", 0.5),
        "technicalsignal": tech_data.get("technical_signal", "NEUTRAL"),
        "newsscore": news_score,
    }


# ══════════════════════════════════════════════════════════
# Encoders (pipe-delimited for Pine Script)
# ══════════════════════════════════════════════════════════

def encode_levels(levels: list[dict[str, Any]]) -> str:
    return ";".join(f"{int(ln['time'])}|{ln['price']}|{ln['dir']}" for ln in levels)


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


# Deadband around a neutral news score; |score| <= eps maps to NEUTRAL bias.
_NEWS_BIAS_EPS = 0.05


@app.get("/smc_live")
def smc_live_endpoint(
    symbol: str = Query(..., description="Ticker symbol"),
    tf: str = Query("15m", description="Timeframe: 5m, 15m, 1H, 4H"),
) -> dict[str, Any]:
    """Flat ``smc-live-overlay/1`` payload for the Pine bridge.

    Serves the on-demand news fields (``news_strength``, ``news_bias``) plus the
    canonical overlay ``tone`` (B2), computed through the same layering function
    that bakes ``mp.tone`` so the live tone shares the baseline's weighting and
    thresholds (identical semantics, fresher inputs). The remaining baked-only
    overlay fields (``flow_rel_vol``, ``squeeze_on`` and the rest of the B2 set)
    are omitted so the Pine side keeps its baked ``mp.*`` defaults for them.
    ``exclude_none`` keeps the payload flat and contract-conformant; the overlay
    may only add or tighten, never loosen.

    Off-universe / no-data symbols yield a news score of exactly ``0.0`` (the
    newsstack returns ``0.0`` for unknown tickers and on any lookup error). In
    that case the news fields are omitted entirely so the response degrades to
    the envelope only and Pine falls back to its baked ``mp.*`` news value --
    emitting a fabricated ``0.0`` would instead override (loosen) a real baked
    signal, violating the overlay safety invariant. ``asof_ts`` is the serve
    time: the snapshot is built on demand, so the payload is fresh by
    construction and ``stale`` is ``False``; transport/cache-age staleness is
    enforced Pine-side by comparing ``asof_ts`` against ``i_overlayMaxAge``.
    """
    # Lazy submodule import (mirrors the provider getters above) so the
    # smc_tv_bridge.* import stays after the repo-root sys.path setup.
    from smc_tv_bridge.contracts.live_overlay import LiveOverlayPayload, flatten_overlay

    symbol = symbol.upper()
    if tf not in _TF_TO_FMP_INTERVAL:
        return {"error": f"unsupported timeframe: {tf}"}

    snap = build_smc_snapshot(symbol, tf)
    score = float(snap.get("newsscore", 0.0) or 0.0)

    # Directional news bias from the signed score, with a neutral deadband.
    if score > _NEWS_BIAS_EPS:
        news_bias = "BULLISH"
    elif score < -_NEWS_BIAS_EPS:
        news_bias = "BEARISH"
    else:
        news_bias = "NEUTRAL"

    # Only attach news fields when there is a genuine signal; a 0.0 score means
    # off-universe / no data -> envelope-only -> Pine keeps baked mp.* news.
    news_fields: dict[str, Any] = {}
    if score != 0.0:
        news_fields["news_strength"] = round(min(1.0, abs(score)), 4)
        news_fields["news_bias"] = news_bias

    # Canonical overlay tone: reuse the same layering function that bakes
    # ``mp.tone`` so the live tone shares the baseline's weighting/thresholds
    # (identical semantics, fresher inputs). Omit it on no-data (flat technical
    # score *and* zero news) so Pine keeps its baked ``mp.tone`` instead of
    # receiving a fabricated NEUTRAL override -- mirroring the news-field rule.
    tech_score = float(snap.get("technicalscore", 0.5) or 0.5)
    tech_signal = str(snap.get("technicalsignal", "NEUTRAL") or "NEUTRAL")
    tone_fields: dict[str, Any] = {}
    if tech_score != 0.5 or score != 0.0:
        from scripts.smc_library_layering import compute_library_layering

        regime = snap.get("regime") or {}
        layering = compute_library_layering(
            news=news_bias,
            technical_strength=min(1.0, abs(tech_score - 0.5) * 2.0),
            technical_bias=tech_signal,
            volume_regime=str(regime.get("volume_regime", "NORMAL")),
        )
        tone_fields["tone"] = layering["tone"]

    # Market-wide VIX (B2): cached and symbol-independent. Omitted on a fetch
    # miss so Pine keeps its baked ``mp.vix`` (silent fallback; never loosens).
    vix_fields: dict[str, Any] = {}
    vix_level = _get_vix_level()
    if vix_level is not None:
        vix_fields["vix_level"] = round(vix_level, 2)

    payload = LiveOverlayPayload(
        symbol=symbol,
        tf=tf,
        asof_ts=int(time.time()),
        stale=False,
        **news_fields,
        **tone_fields,
        **vix_fields,
    )
    return flatten_overlay(payload)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "mock": USE_MOCK,
        "fmp_available": not USE_MOCK,
    }
