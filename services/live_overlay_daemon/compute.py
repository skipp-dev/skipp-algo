"""
Overlay field computation.

Takes a snapshot of accumulated OHLCV bars from cache.py and produces
the 16-field overlay payload for each symbol.

All computations use only standard library + the bars already in cache —
no additional network calls from this module.

Field definitions (matching spec/smc_live_overlay.schema.json):
  news_strength        — [0.0, 1.0] composite news sentiment magnitude for symbol
  news_bias            — "BULLISH" | "BEARISH" | "NEUTRAL"
  flow_rel_vol         — volume(last N bars) / avg_volume(rolling window)
  flow_delta_proxy_pct — (close - open) / open × 100 for most recent bar
  squeeze_on           — True if Bollinger-band width < ATR threshold
  ats_state            — "accumulation" | "distribution" | "neutral"
  ats_zscore           — z-score of last-bar volume vs rolling mean
  vix_level            — latest VIX level (from VIX symbol bars)
  tone                 — "BULLISH" | "BEARISH" | "NEUTRAL" (market-wide)
  global_heat          — [-1.0, 1.0] directional news heat (positive = bullish)
  event_window_state   — "pre-event" | "in-event" | "post-event" | "normal"
  event_risk_level     — "high" | "medium" | "low"
  next_event_name      — str or null
  next_event_time      — ISO-8601 str or null
  market_event_blocked — bool
  symbol_event_blocked — bool
  event_provider_status — "ok" | "stale" | "unavailable"
  asof_ts              — Unix-Epoch seconds (int) of computation
  stale                — True if overlay_age > max_stale_secs
"""
from __future__ import annotations

import datetime
import json
import logging
import math
import threading
import time
from typing import Any

from . import cache, config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# News snapshot helpers
# ---------------------------------------------------------------------------

_news_cache: dict[str, Any] = {}
_news_loaded_at: float = 0.0
_news_checked_at: float = 0.0
_news_lock = threading.Lock()

def _load_news_snapshot() -> dict[str, Any]:
    global _news_cache, _news_loaded_at, _news_checked_at
    with _news_lock:
        path = config.news_snapshot_path()
        now = time.monotonic()
        ttl = config.news_cache_ttl_secs()

        # Happy path: we already have a successful load within the TTL.
        if _news_loaded_at > 0.0 and now - _news_loaded_at < ttl:
            return dict(_news_cache)

        # Rate-limit all read attempts (success or failure) so a missing file
        # or corrupted JSON does not generate a read/log storm.  We keep
        # _news_loaded_at for *successful* loads only; that way a snapshot that
        # appears after an earlier "file not found" is picked up as soon as the
        # rate-limit window expires instead of being ignored for the full TTL.
        if _news_checked_at > 0.0 and now - _news_checked_at < ttl:
            return dict(_news_cache)

        _news_checked_at = now

        if not path.exists():
            _news_cache = {}
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            _news_cache = raw if isinstance(raw, dict) else {}
            _news_loaded_at = now
        except Exception:
            logger.warning("Failed to load news snapshot from %s", path, exc_info=True)
            _news_cache = {}
        return dict(_news_cache)


def _get_news_fields(symbol: str) -> dict[str, Any]:
    """Extract news_strength and news_bias for a symbol from the snapshot."""
    snap = _load_news_snapshot()
    stories = snap.get("stories") or snap.get("items") or []
    sym_upper = symbol.upper()

    def _normalize_tickers(raw: Any) -> list[str]:
        """Normalize story tickers to a safe uppercase ticker list."""
        if isinstance(raw, str):
            raw_items: list[Any] = [raw]
        elif isinstance(raw, list):
            raw_items = raw
        else:
            return []

        out: list[str] = []
        for item in raw_items:
            if not isinstance(item, str):
                continue
            ticker = item.strip().upper()
            if ticker:
                out.append(ticker)
        return out

    def _score(story: dict[str, Any]) -> float:
        """Prefer sentiment_score when present (including 0.0), else news_score."""
        try:
            if "sentiment_score" in story and story.get("sentiment_score") is not None:
                return float(story["sentiment_score"])
            if "news_score" in story and story.get("news_score") is not None:
                return float(story["news_score"])
        except (TypeError, ValueError):
            return 0.0
        return 0.0

    scores: list[float] = []
    for story in stories:
        if not isinstance(story, dict):
            continue
        tickers = _normalize_tickers(story.get("tickers"))
        if sym_upper not in tickers:
            continue
        scores.append(_score(story))

    if not scores:
        return {"news_strength": None, "news_bias": None}

    avg = sum(scores) / len(scores)
    bias = "BULLISH" if avg > 0.1 else ("BEARISH" if avg < -0.1 else "NEUTRAL")
    return {
        "news_strength": round(max(0.0, min(1.0, abs(avg))), 4),
        "news_bias": bias,
    }


def _get_global_news_fields() -> dict[str, Any]:
    """Compute market-wide tone and global_heat from the full news snapshot."""
    snap = _load_news_snapshot()
    stories = snap.get("stories") or snap.get("items") or []
    story_dicts = [s for s in stories if isinstance(s, dict)]
    if not story_dicts:
        return {"tone": "NEUTRAL", "global_heat": None}

    def _score(story: dict[str, Any]) -> float:
        """Prefer sentiment_score when present (including 0.0), else news_score."""
        try:
            if "sentiment_score" in story and story.get("sentiment_score") is not None:
                return float(story["sentiment_score"])
            if "news_score" in story and story.get("news_score") is not None:
                return float(story["news_score"])
        except (TypeError, ValueError):
            return 0.0
        return 0.0

    scores = [_score(s) for s in story_dicts]
    avg = sum(scores) / len(scores)
    # global_heat: directional [-1, 1] per smc-live-overlay/1 schema
    heat = round(max(-1.0, min(1.0, avg)), 4)

    tone = "BULLISH" if avg > 0.05 else ("BEARISH" if avg < -0.05 else "NEUTRAL")
    return {"tone": tone, "global_heat": heat}


# ---------------------------------------------------------------------------
# OHLCV bar computations
# ---------------------------------------------------------------------------

def _safe_mean(vals: list[float]) -> float | None:
    if not vals:
        return None
    return sum(vals) / len(vals)


def _safe_std(vals: list[float]) -> float:
    n = len(vals)
    if n < 2:
        return 0.0
    mean = sum(vals) / n
    return math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1))


def compute_flow_fields(bars: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute flow_rel_vol, flow_delta_proxy_pct from bar list."""
    if not bars:
        return {"flow_rel_vol": None, "flow_delta_proxy_pct": None}

    # Anchor volume ratio to the CURRENT (last) bar.  If the last bar has no
    # volume we must NOT fall back to bars[-2].volume — that would silently
    # report a one-bar-stale ratio alongside the current bar's price delta.
    last_bar = bars[-1]
    last_vol: float | None = last_bar.get("volume")
    if last_vol is not None:
        prior_volumes = [
            b["volume"] for b in bars[:-1] if b.get("volume") is not None
        ]
        avg_vol: float | None = _safe_mean(prior_volumes) if prior_volumes else None
    else:
        avg_vol = None

    flow_rel_vol: float | None = None
    if avg_vol and avg_vol > 0 and last_vol is not None:
        flow_rel_vol = round(last_vol / avg_vol, 4)

    open_ = last_bar.get("open")
    close_ = last_bar.get("close")
    flow_delta: float | None = None
    if open_ and open_ > 0 and close_ is not None:
        flow_delta = round((close_ - open_) / open_ * 100, 4)

    return {"flow_rel_vol": flow_rel_vol, "flow_delta_proxy_pct": flow_delta}


def compute_squeeze_on(bars: list[dict[str, Any]], period: int = 20) -> bool | None:
    """
    Squeeze = True when Bollinger Band width < Keltner Channel width.
    Approximated here as: BB width < 1.5 × ATR (simplified single-symbol check).
    """
    closes = [b["close"] for b in bars if b.get("close") is not None]
    highs = [b["high"] for b in bars if b.get("high") is not None]
    lows = [b["low"] for b in bars if b.get("low") is not None]

    if len(closes) < period or len(highs) < period or len(lows) < period:
        return None

    closes_w = closes[-period:]
    highs_w = highs[-period:]
    lows_w = lows[-period:]

    std_c = _safe_std(closes_w)

    # Approximate ATR (True Range without prior-close continuity)
    trs = [h - lo for h, lo in zip(highs_w, lows_w)]
    atr = sum(trs) / len(trs)

    bb_width = 4 * std_c  # upper - lower (2σ each side)
    kc_width = 2 * atr     # Keltner ±1 ATR approximation

    return bool(bb_width < kc_width)


def compute_ats_fields(bars: list[dict[str, Any]]) -> dict[str, Any]:
    """
    ATS (Automatic Trading System) state:
      ats_state  — "accumulation" | "distribution" | "neutral"
      ats_zscore — z-score of most recent bar's volume vs rolling avg
    """
    volumes = [b["volume"] for b in bars if b.get("volume") is not None]
    if len(volumes) < 5:
        return {"ats_state": None, "ats_zscore": None}

    mean_v = sum(volumes[:-1]) / len(volumes[:-1])
    std_v = _safe_std(volumes[:-1])
    last_v = volumes[-1]

    zscore: float | None = None
    if std_v > 0:
        zscore = round((last_v - mean_v) / std_v, 4)

    closes = [b["close"] for b in bars if b.get("close") is not None]
    opens = [b["open"] for b in bars if b.get("open") is not None]
    if len(closes) < 2 or len(opens) < 2:
        state = "neutral"
    else:
        # Simple heuristic: price trend × volume
        price_delta = closes[-1] - opens[-1]
        if price_delta > 0 and (zscore or 0) > 0.5:
            state = "accumulation"
        elif price_delta < 0 and (zscore or 0) > 0.5:
            state = "distribution"
        else:
            state = "neutral"

    return {"ats_state": state, "ats_zscore": zscore}


# ---------------------------------------------------------------------------
# Event calendar (placeholder — extend with real calendar source)
# ---------------------------------------------------------------------------

def _event_fields_for(_symbol: str) -> dict[str, Any]:
    """
    Placeholder: returns neutral event state.
    In Phase 2, connect to earnings calendar API (FMP or similar).
    """
    return {
        "event_window_state": "normal",
        "event_risk_level": "low",
        "next_event_name": None,
        "next_event_time": None,
        "market_event_blocked": False,
        "symbol_event_blocked": False,
        "event_provider_status": "unavailable",
    }


# ---------------------------------------------------------------------------
# Full payload builder
# ---------------------------------------------------------------------------

def build_payload(
    symbol: str,
    bars: list[dict[str, Any]],
    global_fields: dict[str, Any],
    max_stale_secs: int,
) -> dict[str, Any]:
    """Build the full 16-field overlay payload for one symbol."""
    # asof_ts is Unix-Epoch seconds (int) per smc-live-overlay/1 schema
    asof_ts = int(datetime.datetime.now(datetime.UTC).timestamp())

    news = _get_news_fields(symbol)
    flow = compute_flow_fields(bars)
    squeeze = compute_squeeze_on(bars)
    ats = compute_ats_fields(bars)
    vix = cache.get_vix()
    events = _event_fields_for(symbol)

    age = cache.overlay_age_secs()
    stale = (age > max_stale_secs) if age != float("inf") else True

    return {
        "schema": "smc-live-overlay/1",
        "symbol": symbol.upper(),
        "asof_ts": asof_ts,
        "stale": stale,
        # News
        "news_strength": news.get("news_strength"),
        "news_bias": news.get("news_bias"),
        # Flow
        "flow_rel_vol": flow.get("flow_rel_vol"),
        "flow_delta_proxy_pct": flow.get("flow_delta_proxy_pct"),
        # Technicals
        "squeeze_on": int(squeeze) if squeeze is not None else None,
        "ats_state": ats.get("ats_state"),
        "ats_zscore": ats.get("ats_zscore"),
        # Market-wide
        "vix_level": round(vix, 4) if vix is not None else None,
        "tone": global_fields.get("tone"),
        "global_heat": global_fields.get("global_heat"),
        # Events
        **events,
    }


def run_full_compute_cycle() -> int:
    """
    Compute overlay payloads for ALL symbols currently in the bar cache.
    Returns number of symbols computed.
    Called every OVERLAY_REFRESH_SECS by the refresh thread.
    """
    all_bars = cache.get_all_symbols_snapshot()
    max_stale = config.max_stale_secs()
    global_fields = _get_global_news_fields()

    payloads: dict[str, Any] = {}
    for sym, bars in all_bars.items():
        if not bars:
            continue
        payloads[sym.upper()] = build_payload(sym, bars, global_fields, max_stale)

    # Always replace snapshot (including empty) so stale symbols are removed
    # when bar cache is temporarily empty.
    cache.set_overlay(payloads)

    return len(payloads)


def run_flow_patch_cycle() -> int:
    """
    Fast refresh: recompute only flow fields for all symbols.
    Does NOT reset the full overlay cache timestamp.
    Called every OVERLAY_FLOW_REFRESH_SECS.
    """
    all_bars = cache.get_all_symbols_snapshot()
    vix = cache.get_vix()
    count = 0
    for sym, bars in all_bars.items():
        if not bars:
            continue
        updates = compute_flow_fields(bars)
        if vix is not None:
            updates["vix_level"] = round(vix, 4)
        cache.patch_overlay(sym, updates)
        count += 1
    return count
