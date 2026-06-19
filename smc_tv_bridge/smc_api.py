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
from datetime import UTC, datetime, timedelta
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
    "10m": "10min",
    "15m": "15min",
    "30m": "30min",
    "1H": "1hour",
    "4H": "4hour",
}

_TF_TO_TECH_INTERVAL: dict[str, str] = {
    "5m": "5m",
    "10m": "10m",
    "15m": "15m",
    "30m": "30m",
    "1H": "1h",
    "4H": "4h",
}

_TF_CANDLE_LIMIT: dict[str, int] = {
    "5m": 200,
    "10m": 150,
    "15m": 100,
    "30m": 80,
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


# ── Flow-delta + ATS overlay source (per-symbol microstructure) ──────────────
#
# The slow baseline bakes safe ``mp.*`` flow/ATS constants into Pine. This
# overlay re-derives today's flow-delta proxy and ATS z-score/state from *live*
# trade microstructure (Databento), qualified against the cached 20-day ATS
# baseline, so the bridge can tighten field-by-field. Per-symbol values are
# cached (TTL=300s) and coalesced under a per-symbol lock so concurrent
# /smc_live calls for the same symbol make a single upstream request while
# different symbols still refresh in parallel. Fail-closed: any miss (no trades,
# missing baseline row, fetch error) yields None for all three fields and the
# bridge omits them so Pine keeps its baked ``mp.*`` fallback (never loosens).
_FLOW_DATASET = "XNAS.ITCH"
_FLOW_TTL_SECONDS = 300.0
_FLOW_MOCK_FIELDS: dict[str, Any] = {
    "flow_delta_proxy_pct": 12.0,
    "ats_zscore": 0.75,
    "ats_state": "ELEVATED",
}
_ATS_BASELINE_PATH = Path(__file__).resolve().parents[1] / "reports" / "ats_baseline_20d.json"
_ATS_MEAN_KEY = "avg_trade_size_20d_mean"
_ATS_STD_KEY = "avg_trade_size_20d_std"
_flow_cache_lock = threading.Lock()
_flow_cache: dict[str, dict[str, Any]] = {}
_flow_symbol_locks: dict[str, threading.Lock] = {}


# Per-symbol event-risk-light (lean v5.5) served on the overlay. Mirrors the
# flow/ATS cache: a short ``_event_cache_lock`` guards the module cache while the
# resolve runs under a per-symbol lock so concurrent /smc_live calls for the same
# symbol coalesce. Fail-closed + tighten-only: no data / resolve error yields an
# empty dict and the endpoint omits every event field so Pine keeps its baked
# ``mp.*`` event posture; the two block booleans are emitted only when True so the
# overlay can assert a block but never lift the baked one.
_EVENT_TTL_SECONDS = 300.0
_EVENT_MOCK_FIELDS: dict[str, Any] = {
    "event_window_state": "PRE_EVENT",
    "event_risk_level": "HIGH",
    "next_event_name": "AAPL Q3 Earnings",
    "next_event_time": "20:00",
    "symbol_event_blocked": True,
    "event_provider_status": "ok",
}
_event_cache_lock = threading.Lock()
_event_cache: dict[str, dict[str, Any]] = {}
_event_symbol_locks: dict[str, threading.Lock] = {}


def _event_lock_for(symbol: str) -> threading.Lock:
    with _event_cache_lock:
        lock = _event_symbol_locks.get(symbol)
        if lock is None:
            lock = threading.Lock()
            _event_symbol_locks[symbol] = lock
        return lock


def _event_light_to_overlay_fields(light: dict[str, Any]) -> dict[str, Any]:
    """Map the 7 UPPERCASE event-risk-light fields to flat overlay keys.

    Fail-closed + tighten-only: when the provider reports ``no_data`` every field
    is omitted so Pine keeps its baked posture. ``market_event_blocked`` and
    ``symbol_event_blocked`` are emitted only when True so the overlay can assert
    a block but never lift the baked one.
    """
    status = str(light.get("EVENT_PROVIDER_STATUS", "no_data") or "no_data").strip()
    if status == "no_data":
        return {}
    fields: dict[str, Any] = {}
    for src, dst in (
        ("EVENT_WINDOW_STATE", "event_window_state"),
        ("EVENT_RISK_LEVEL", "event_risk_level"),
        ("NEXT_EVENT_NAME", "next_event_name"),
        ("NEXT_EVENT_TIME", "next_event_time"),
    ):
        value = str(light.get(src, "") or "").strip()
        if value:
            fields[dst] = value
    if bool(light.get("MARKET_EVENT_BLOCKED")):
        fields["market_event_blocked"] = True
    if bool(light.get("SYMBOL_EVENT_BLOCKED")):
        fields["symbol_event_blocked"] = True
    fields["event_provider_status"] = status
    return fields


def _fetch_event_risk_uncached(symbol: str) -> dict[str, Any]:
    """Resolve the live event-risk-light for ``symbol`` (fail-closed -> {})."""
    from scripts.smc_event_risk_light import build_event_risk_light

    try:
        from databento_reference import get_reference_event_risk_snapshot
        from scripts.smc_event_risk_builder import build_event_risk

        snapshot = get_reference_event_risk_snapshot([symbol])
        if isinstance(snapshot, dict):
            light = build_event_risk_light(event_risk=build_event_risk(reference=snapshot))
        else:
            light = build_event_risk_light(event_risk={"EVENT_PROVIDER_STATUS": "no_data"})
    except (OSError, ValueError, KeyError, RuntimeError, TypeError) as exc:
        logger.debug("Event-risk resolve skipped for %s: %s", symbol, exc)
        return {}
    return _event_light_to_overlay_fields(light)


def _get_event_risk(symbol: str) -> dict[str, Any]:
    """Cached per-symbol event-risk overlay fields (TTL=300s, thread-safe)."""
    if USE_MOCK:
        return dict(_EVENT_MOCK_FIELDS)
    now = time.monotonic()
    with _event_cache_lock:
        entry = _event_cache.get(symbol)
        if entry is not None and (now - entry["fetched_at"]) < _EVENT_TTL_SECONDS:
            return entry["value"]
    with _event_lock_for(symbol):
        now = time.monotonic()
        with _event_cache_lock:
            entry = _event_cache.get(symbol)
            if entry is not None and (now - entry["fetched_at"]) < _EVENT_TTL_SECONDS:
                return entry["value"]
        value = _fetch_event_risk_uncached(symbol)
        with _event_cache_lock:
            _event_cache[symbol] = {"value": value, "fetched_at": time.monotonic()}
        return value


def _load_ats_baseline_symbols() -> dict[str, Any]:
    """Return the per-symbol 20-day ATS baseline mapping (fail-soft -> {})."""
    import json

    try:
        with _ATS_BASELINE_PATH.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.debug("ATS baseline load skipped: %s", exc)
        return {}
    symbols = data.get("symbols") if isinstance(data, dict) else None
    return symbols if isinstance(symbols, dict) else {}


def _fetch_flow_ats_uncached(symbol: str) -> dict[str, Any] | None:
    """Derive live flow-delta + ATS fields for ``symbol``. None on any miss.

    Network seam for :func:`_get_flow_ats_fields`. Pulls today's trade
    microstructure (Databento) and qualifies it against the cached 20-day ATS
    baseline via the same :func:`build_flow_qualifier` that feeds the slow
    baseline, so the live fields share the baseline's semantics. Fail-closed --
    a missing baseline row, an empty trade window or any error yields None.
    """
    baseline = _load_ats_baseline_symbols().get(symbol.upper())
    if not isinstance(baseline, dict):
        return None
    mean = baseline.get(_ATS_MEAN_KEY)
    std = baseline.get(_ATS_STD_KEY)
    if mean is None or std is None:
        return None
    try:
        from scripts.smc_flow_qualifier import build_flow_qualifier
        from scripts.smc_trades_microstructure import fetch_symbol_microstructure

        today = datetime.now(UTC).date()
        micro = fetch_symbol_microstructure(
            symbol,
            _FLOW_DATASET,
            today.isoformat(),
            (today + timedelta(days=1)).isoformat(),
        )
        avg_trade_size = (micro or {}).get("avg_trade_size")
        buy_volume_pct = (micro or {}).get("buy_volume_pct")
        n_trades = (micro or {}).get("n_trades")
        # Fail closed on an empty trade window: fetch_symbol_microstructure
        # returns neutral defaults (avg_trade_size=0.0, buy_volume_pct=50.0)
        # when n_trades == 0 (e.g. outside market hours). Emitting those would
        # fabricate a flow/ATS overlay that overrides the baked mp.* baseline
        # with non-data, so bail and let Pine keep its baked fallback.
        if avg_trade_size is None or buy_volume_pct is None or not n_trades:
            return None
        row = pd.DataFrame(
            [
                {
                    "symbol": symbol.upper(),
                    "avg_trade_size": float(avg_trade_size),
                    "buy_volume_pct": float(buy_volume_pct),
                    _ATS_MEAN_KEY: float(mean),
                    _ATS_STD_KEY: float(std),
                }
            ]
        )
        qualifier = build_flow_qualifier(snapshot=row, symbol=symbol.upper())
    except (OSError, ValueError, KeyError, RuntimeError, TypeError) as exc:
        logger.debug("Flow/ATS fetch skipped for %s: %s", symbol, exc)
        return None
    delta = qualifier.get("DELTA_PROXY_PCT")
    zscore = qualifier.get("ATS_ZSCORE")
    state = qualifier.get("ATS_STATE")
    if delta is None or zscore is None or state is None:
        return None
    return {
        "flow_delta_proxy_pct": float(delta),
        "ats_zscore": float(zscore),
        "ats_state": str(state),
    }


def _flow_lock_for(symbol: str) -> threading.Lock:
    """Return the per-symbol fetch lock, created under the shared cache lock."""
    with _flow_cache_lock:
        lock = _flow_symbol_locks.get(symbol)
        if lock is None:
            lock = threading.Lock()
            _flow_symbol_locks[symbol] = lock
        return lock


def _get_flow_ats_fields(symbol: str) -> dict[str, Any] | None:
    """Cached per-symbol flow-delta + ATS fields (TTL=300s, thread-safe).

    Double-checked locking: the short ``_flow_cache_lock`` guards the
    module-level cache while the actual fetch runs under a per-symbol lock, so
    concurrent /smc_live calls for the *same* symbol coalesce into a single
    upstream request while different symbols still refresh in parallel. Both
    hits and misses are throttled to once per TTL window.
    """
    if USE_MOCK:
        return dict(_FLOW_MOCK_FIELDS)
    now = time.monotonic()
    with _flow_cache_lock:
        entry = _flow_cache.get(symbol)
        if entry is not None and (now - entry["fetched_at"]) < _FLOW_TTL_SECONDS:
            return entry["value"]
    with _flow_lock_for(symbol):
        now = time.monotonic()
        with _flow_cache_lock:
            entry = _flow_cache.get(symbol)
            if entry is not None and (now - entry["fetched_at"]) < _FLOW_TTL_SECONDS:
                return entry["value"]
        value = _fetch_flow_ats_uncached(symbol)
        with _flow_cache_lock:
            _flow_cache[symbol] = {"value": value, "fetched_at": time.monotonic()}
        return value


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
    timeframe: str = Query("15m", description="Timeframe: 5m, 10m, 15m, 30m, 1H, 4H"),
) -> dict[str, Any]:
    """Full SMC snapshot (nested JSON)."""
    symbol = symbol.upper()
    if timeframe not in _TF_TO_FMP_INTERVAL:
        return {"error": f"unsupported timeframe: {timeframe}"}
    return build_smc_snapshot(symbol, timeframe)


@app.get("/smc_tv")
def smc_tv_endpoint(
    symbol: str = Query(..., description="Ticker symbol"),
    tf: str = Query("15m", description="Timeframe: 5m, 10m, 15m, 30m, 1H, 4H"),
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
    tf: str = Query("15m", description="Timeframe: 5m, 10m, 15m, 30m, 1H, 4H"),
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

    # Canonical overlay tone + global_heat (B2/C): reuse the same layering that
    # bakes ``mp.tone`` / ``mp.GLOBAL_HEAT`` so the live values share the
    # baseline's weighting/thresholds (fresher inputs). Omit on no-data (flat
    # technical score *and* zero news) so Pine keeps its baked values instead
    # of a fabricated NEUTRAL/zero override -- mirroring the news-field rule.
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
        tone_fields["global_heat"] = layering["global_heat"]

    # Market-wide VIX (B2): cached and symbol-independent. Omitted on a fetch
    # miss so Pine keeps its baked ``mp.vix`` (silent fallback; never loosens).
    vix_fields: dict[str, Any] = {}
    vix_level = _get_vix_level()
    if vix_level is not None:
        vix_fields["vix_level"] = round(vix_level, 2)

    # Per-symbol flow-delta + ATS (B2): cached live microstructure qualified
    # against the 20-day ATS baseline. Omitted field-by-field on a miss so Pine
    # keeps its baked ``mp.*`` flow/ATS fallback (silent fallback; never loosens).
    flow_fields: dict[str, Any] = {}
    flow_ats = _get_flow_ats_fields(symbol)
    if flow_ats:
        flow_fields = {k: v for k, v in flow_ats.items() if v is not None}

    # Per-symbol event-risk-light (lean v5.5): built from the cached Databento
    # reference snapshot (corporate actions; no earnings/calendar/news feed yet) —
    # window state, risk level, next-event name/time, block flags, provider health.
    # Fail-closed + tighten-only: omitted on no-data so Pine keeps its baked posture.
    event_fields = _get_event_risk(symbol)

    payload = LiveOverlayPayload(
        symbol=symbol,
        tf=tf,
        asof_ts=int(time.time()),
        stale=False,
        **news_fields,
        **tone_fields,
        **vix_fields,
        **flow_fields,
        **event_fields,
    )
    return flatten_overlay(payload)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "mock": USE_MOCK,
        "fmp_available": not USE_MOCK,
    }
