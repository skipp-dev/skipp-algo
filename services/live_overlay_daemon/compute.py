"""
Overlay field computation.

Takes a snapshot of accumulated OHLCV bars from cache.py and produces
the overlay payload for each symbol.

All computations use only standard library + the bars already in cache.
The news snapshot is normally read from a local file, but may instead be
fetched at runtime from NEWS_SNAPSHOT_URL when that env var is set; no other
module here performs network calls.

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
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import cache, config, observability

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# News snapshot helpers
# ---------------------------------------------------------------------------

_news_cache: dict[str, Any] = {}
_news_loaded_at: float = 0.0
_news_checked_at: float = 0.0
_news_lock = threading.Lock()
_NEWS_USER_AGENT = "live-overlay-daemon-news/1"

# ---------------------------------------------------------------------------
# Realtime trading-signals snapshot helpers
# ---------------------------------------------------------------------------
# The realtime engine (open_prep/realtime_signals.py) writes its active A0/A1
# breakout signals to ``artifacts/open_prep/latest/latest_realtime_signals.json``.
# The daemon ingests that snapshot (locally or, when SIGNALS_SNAPSHOT_URL is
# set, over https) purely to surface it as Prometheus metrics for Grafana; it
# never produces or mutates signals.

_signals_cache: dict[str, Any] = {}
_signals_loaded_at: float = 0.0
_signals_checked_at: float = 0.0
_signals_lock = threading.Lock()
_SIGNALS_USER_AGENT = "live-overlay-daemon-signals/1"

# ---------------------------------------------------------------------------
# Daily experiment (Plan 2.8 per-TF family rollup + history) helpers
# ---------------------------------------------------------------------------
# The rolling measurement benchmark (scripts/plan_2_8_tf_family_rollup.py)
# scores SMC setup families (BOS / OB / FVG / SWEEP) per timeframe once per day
# and writes ``plan_2_8_tf_family_rollup.json``; ``plan_2_8_history_archive.py``
# folds each day's rollup into a per-day ``plan_2_8_history.jsonl``. The daemon
# ingests both (locally or, when the *_URL vars are set, over https) purely to
# surface the daily statistics as Prometheus metrics; it never re-scores.

_experiment_cache: dict[str, Any] = {}
_experiment_loaded_at: float = 0.0
_experiment_checked_at: float = 0.0
_experiment_history_cache: list[dict[str, Any]] = []
_experiment_history_loaded_at: float = 0.0
_experiment_history_checked_at: float = 0.0
_experiment_lock = threading.Lock()
_EXPERIMENT_USER_AGENT = "live-overlay-daemon-experiment/1"


def _persist_snapshot(path: Path, text: str) -> None:
    """Atomically write a freshly-fetched snapshot to its local cache ``path``.

    Best-effort write-through: when a runtime ``*_URL`` fetch succeeds we persist
    the payload to the local snapshot path so a Railway volume mounted there
    keeps the last-good copy across restarts. A cold start can then read the
    volume instead of the stale Docker-baked seed when the URL is momentarily
    unreachable. Never raises — a persistence failure must not break the live
    fetch that already succeeded; the temp file is written in the same directory
    and ``os.replace`` swaps it in atomically so readers never see a partial
    file.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / f"{path.name}.tmp"
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        logger.warning("Failed to persist snapshot to %s", path, exc_info=True)


def _fetch_news_url(url: str, token: str, timeout: float = 10.0) -> dict[str, Any] | None:
    """Fetch the news snapshot JSON from ``url``.

    Returns the parsed dict on success or ``None`` on any failure so the caller
    can fall back to the local file (and baked seed). Only https URLs are
    honoured.
    """
    if not url.lower().startswith("https://"):
        logger.warning("NEWS_SNAPSHOT_URL must be an https URL; ignoring %r", url)
        return None
    headers = {"Accept": "application/json", "User-Agent": _NEWS_USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        # Allows pointing NEWS_SNAPSHOT_URL at the GitHub contents API.
        headers["Accept"] = "application/vnd.github.raw+json"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
        raw = json.loads(payload)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        logger.warning("Failed to fetch news snapshot from URL", exc_info=True)
        return None
    return raw if isinstance(raw, dict) else None


def _load_news_snapshot() -> dict[str, Any]:
    global _news_cache, _news_loaded_at, _news_checked_at
    with _news_lock:
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

        # Prefer a runtime URL when configured; fall back to the local file
        # (and baked seed) on any fetch failure so cold-start still works.
        url = config.news_snapshot_url()
        if url:
            fetched = _fetch_news_url(url, config.news_snapshot_url_token())
            if fetched is not None:
                _news_cache = fetched
                _news_loaded_at = now
                _persist_snapshot(
                    config.news_snapshot_path(),
                    json.dumps(fetched, separators=(",", ":")),
                )
                return dict(_news_cache)

        path = config.news_snapshot_path()
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


def _fetch_signals_url(
    url: str, token: str, timeout: float = 10.0
) -> dict[str, Any] | None:
    """Fetch the realtime-signals snapshot JSON from ``url``.

    Returns the parsed dict on success or ``None`` on any failure so the caller
    can fall back to the local file. Only https URLs are honoured.
    """
    if not url.lower().startswith("https://"):
        logger.warning("SIGNALS_SNAPSHOT_URL must be an https URL; ignoring %r", url)
        return None
    headers = {"Accept": "application/json", "User-Agent": _SIGNALS_USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        # Allows pointing SIGNALS_SNAPSHOT_URL at the GitHub contents API.
        headers["Accept"] = "application/vnd.github.raw+json"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
        raw = json.loads(payload)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        logger.warning("Failed to fetch signals snapshot from URL", exc_info=True)
        return None
    return raw if isinstance(raw, dict) else None


def _load_signals_snapshot() -> dict[str, Any]:
    """Return the latest realtime trading-signals snapshot as a dict.

    Mirrors :func:`_load_news_snapshot`: a runtime ``SIGNALS_SNAPSHOT_URL`` (when
    set) takes precedence, otherwise the local ``signals_snapshot_path`` file is
    read. All reads are TTL-rate-limited so a missing/corrupt file cannot cause
    a read/log storm. Returns ``{}`` when no snapshot is available.
    """
    global _signals_cache, _signals_loaded_at, _signals_checked_at
    with _signals_lock:
        now = time.monotonic()
        ttl = config.signals_cache_ttl_secs()

        # Happy path: a successful load within the TTL.
        if _signals_loaded_at > 0.0 and now - _signals_loaded_at < ttl:
            return dict(_signals_cache)

        # Rate-limit every read attempt (success or failure); keep
        # _signals_loaded_at for successful loads only so a snapshot that
        # appears after an earlier miss is still picked up once the window
        # expires instead of being ignored for the full TTL.
        if _signals_checked_at > 0.0 and now - _signals_checked_at < ttl:
            return dict(_signals_cache)

        _signals_checked_at = now

        url = config.signals_snapshot_url()
        if url:
            fetched = _fetch_signals_url(url, config.signals_snapshot_url_token())
            if fetched is not None:
                _signals_cache = fetched
                _signals_loaded_at = now
                _persist_snapshot(
                    config.signals_snapshot_path(),
                    json.dumps(fetched, separators=(",", ":")),
                )
                return dict(_signals_cache)

        path = config.signals_snapshot_path()
        if not path.exists():
            _signals_cache = {}
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            _signals_cache = raw if isinstance(raw, dict) else {}
            _signals_loaded_at = now
        except Exception:
            logger.warning(
                "Failed to load signals snapshot from %s", path, exc_info=True
            )
            _signals_cache = {}
        return dict(_signals_cache)


def _fetch_experiment_url(
    url: str, token: str, timeout: float = 10.0
) -> str | None:
    """Fetch raw text (JSON rollup or JSONL history) from ``url``.

    Returns the decoded body on success or ``None`` on any failure so the caller
    can fall back to the local file. Only https URLs are honoured.
    """
    if not url.lower().startswith("https://"):
        logger.warning("EXPERIMENT_*_URL must be an https URL; ignoring %r", url)
        return None
    headers = {"Accept": "application/json", "User-Agent": _EXPERIMENT_USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        # Allows pointing the URL at the GitHub contents API raw endpoint.
        headers["Accept"] = "application/vnd.github.raw+json"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
        return payload.decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        logger.warning("Failed to fetch experiment data from URL", exc_info=True)
        return None


def _parse_history_lines(text: str, max_days: int) -> list[dict[str, Any]]:
    """Parse a Plan 2.8 history JSONL body into the most recent per-day dicts.

    Malformed lines are skipped. The newest ``max_days`` snapshots are returned
    in chronological order (oldest first) so Grafana renders them left-to-right.
    """
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("captured_at"):
            rows.append(obj)
    # JSONL is append-ordered, but sort defensively on captured_at so a backfill
    # line interleaved out of order still renders chronologically.
    rows.sort(key=lambda r: str(r.get("captured_at", "")))
    if max_days > 0 and len(rows) > max_days:
        rows = rows[-max_days:]
    return rows


def _load_experiment_snapshot() -> dict[str, Any]:
    """Return the latest Plan 2.8 per-TF family rollup as a dict.

    Mirrors :func:`_load_signals_snapshot`: a runtime ``EXPERIMENT_SNAPSHOT_URL``
    takes precedence, otherwise the local rollup file is read. TTL-rate-limited
    so a missing/corrupt file cannot cause a read/log storm. Returns ``{}`` when
    no rollup is available.
    """
    global _experiment_cache, _experiment_loaded_at, _experiment_checked_at
    with _experiment_lock:
        now = time.monotonic()
        ttl = config.experiment_cache_ttl_secs()

        if _experiment_loaded_at > 0.0 and now - _experiment_loaded_at < ttl:
            return dict(_experiment_cache)
        if _experiment_checked_at > 0.0 and now - _experiment_checked_at < ttl:
            return dict(_experiment_cache)

        _experiment_checked_at = now

        url = config.experiment_snapshot_url()
        if url:
            body = _fetch_experiment_url(url, config.experiment_snapshot_url_token())
            if body is not None:
                try:
                    raw = json.loads(body)
                except ValueError:
                    raw = None
                if isinstance(raw, dict):
                    _experiment_cache = raw
                    _experiment_loaded_at = now
                    _persist_snapshot(config.experiment_snapshot_path(), body)
                    return dict(_experiment_cache)

        path = config.experiment_snapshot_path()
        if not path.exists():
            _experiment_cache = {}
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            _experiment_cache = raw if isinstance(raw, dict) else {}
            _experiment_loaded_at = now
        except Exception:
            logger.warning(
                "Failed to load experiment rollup from %s", path, exc_info=True
            )
            _experiment_cache = {}
        return dict(_experiment_cache)


def _load_experiment_history() -> list[dict[str, Any]]:
    """Return the per-day Plan 2.8 history snapshots (oldest first).

    Mirrors the snapshot loader but parses JSONL and caps to
    ``experiment_history_max_days``. Returns ``[]`` when unavailable.
    """
    global _experiment_history_cache, _experiment_history_loaded_at, _experiment_history_checked_at
    with _experiment_lock:
        now = time.monotonic()
        ttl = config.experiment_cache_ttl_secs()
        max_days = config.experiment_history_max_days()

        if (
            _experiment_history_loaded_at > 0.0
            and now - _experiment_history_loaded_at < ttl
        ):
            return [dict(r) for r in _experiment_history_cache]
        if (
            _experiment_history_checked_at > 0.0
            and now - _experiment_history_checked_at < ttl
        ):
            return [dict(r) for r in _experiment_history_cache]

        _experiment_history_checked_at = now

        url = config.experiment_history_url()
        if url:
            body = _fetch_experiment_url(url, config.experiment_history_url_token())
            if body is not None:
                _experiment_history_cache = _parse_history_lines(body, max_days)
                _experiment_history_loaded_at = now
                _persist_snapshot(config.experiment_history_path(), body)
                return [dict(r) for r in _experiment_history_cache]

        path = config.experiment_history_path()
        if not path.exists():
            _experiment_history_cache = []
            return []
        try:
            text = path.read_text(encoding="utf-8")
            _experiment_history_cache = _parse_history_lines(text, max_days)
            _experiment_history_loaded_at = now
        except Exception:
            logger.warning(
                "Failed to load experiment history from %s", path, exc_info=True
            )
            _experiment_history_cache = []
        return [dict(r) for r in _experiment_history_cache]


def _get_news_fields(symbol: str) -> dict[str, Any]:
    """Extract news_strength and news_bias for a symbol from the snapshot."""
    snap = _load_news_snapshot()
    stories = snap.get("stories") or snap.get("items") or []
    sym_upper = symbol.upper()

    def _normalize_tickers(raw: Any) -> list[str]:
        """Normalize story tickers to a safe uppercase ticker list."""
        if isinstance(raw, str):
            raw_items: list[Any] = [raw]
        elif isinstance(raw, (list, tuple, set)):
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

    def _score(story: dict[str, Any]) -> float | None:
        """Prefer sentiment_score when present (including 0.0), else news_score.

        Invalid/non-finite values are treated as missing (None), not as a
        neutral 0.0 sample.
        """
        if "sentiment_score" in story and story.get("sentiment_score") is not None:
            if (score := _coerce_finite_float(story["sentiment_score"])) is not None:
                return score
            # Malformed sentiment_score should not mask a valid news_score.
            if "news_score" in story and story.get("news_score") is not None:
                return _coerce_finite_float(story["news_score"])
            return None
        if "news_score" in story and story.get("news_score") is not None:
            if (score := _coerce_finite_float(story["news_score"])) is not None:
                return score
            return None
        return None

    scores: list[float] = []
    for story in stories:
        if not isinstance(story, dict):
            continue
        tickers = _normalize_tickers(story.get("tickers"))
        if sym_upper not in tickers:
            continue
        if (score := _score(story)) is not None:
            scores.append(score)

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

    def _score(story: dict[str, Any]) -> float | None:
        """Prefer sentiment_score when present (including 0.0), else news_score.

        Invalid/non-finite values are treated as missing (None), not as a
        neutral 0.0 sample.
        """
        if "sentiment_score" in story and story.get("sentiment_score") is not None:
            if (score := _coerce_finite_float(story["sentiment_score"])) is not None:
                return score
            # Malformed sentiment_score should not mask a valid news_score.
            if "news_score" in story and story.get("news_score") is not None:
                return _coerce_finite_float(story["news_score"])
            return None
        if "news_score" in story and story.get("news_score") is not None:
            if (score := _coerce_finite_float(story["news_score"])) is not None:
                return score
            return None
        return None

    scores = [score for s in story_dicts if (score := _score(s)) is not None]
    if not scores:
        return {"tone": "NEUTRAL", "global_heat": None}
    avg = sum(scores) / len(scores)
    # global_heat: directional [-1, 1] per smc-live-overlay/1 schema
    heat = round(max(-1.0, min(1.0, avg)), 4)

    tone = "BULLISH" if avg > 0.05 else ("BEARISH" if avg < -0.05 else "NEUTRAL")
    return {"tone": tone, "global_heat": heat}


def get_global_news_fields() -> dict[str, Any]:
    """Public accessor for market-wide news fields used by API layer."""
    return _get_global_news_fields()


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


def _coerce_finite_float(v: Any) -> float | None:
    """Coerce value to finite float, returning None on invalid/non-finite input."""
    if v is None:
        return None
    # bool is a subclass of int in Python, but True/False in OHLC/volume fields
    # indicates malformed provider data and must not be interpreted as 1.0/0.0.
    if isinstance(v, bool):
        return None
    try:
        coerced = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(coerced):
        return None
    return coerced


def _coerce_volume(v: Any) -> float | None:
    """Coerce a volume field value to float, returning None on failure.

    Accepts int, float, and numeric strings (e.g. '100' from schema drift).
    Returns None for None, empty string, negative values, non-finite values
    (NaN/Inf), or
    any non-numeric value so that
    callers can safely skip the bar instead of crashing.
    """
    coerced = _coerce_finite_float(v)
    if coerced is None:
        return None
    if coerced < 0:
        return None
    return coerced


# ---------------------------------------------------------------------------
# Multi-timeframe aggregation
# ---------------------------------------------------------------------------

_TF_TO_MINUTES: dict[str, int] = {
    "5m": 5,
    "10m": 10,
    "15m": 15,
    "30m": 30,
    "1H": 60,
    "4H": 240,
}


def supported_timeframes() -> tuple[str, ...]:
    """Return supported intraday overlay timeframes in canonical order."""
    return tuple(_TF_TO_MINUTES.keys())


def _bar_minute_bucket(ts_event: int, minutes: int) -> int:
    """Return the bucket-end timestamp (nanoseconds) for a bar.

    Databento ts_event is in nanoseconds since the Unix epoch. We align
    to the end of the N-minute bucket in UTC. Intraday timeframes only.

    For bar-close stamps, events between boundaries are ceiled to the next
    boundary while events already on a boundary remain unchanged.
    """
    ns_per_minute = 60_000_000_000
    minute = ts_event // ns_per_minute
    floored_minute = (minute // minutes) * minutes
    aligned_minute = floored_minute if minute == floored_minute else floored_minute + minutes
    return aligned_minute * ns_per_minute


def _aggregate_bars(bars: list[dict[str, Any]], tf: str) -> list[dict[str, Any]]:
    """Aggregate 1-minute bars into higher intraday timeframes.

    The input cache stores 1-minute bars, so all supported intraday
    timeframes (including 5m) are bucketed and aggregated.
    """
    if tf not in _TF_TO_MINUTES:
        raise ValueError(f"unsupported timeframe: {tf}")

    minutes = _TF_TO_MINUTES[tf]

    ordered_bars = sorted(
        (
            bar
            for bar in bars
            if isinstance((ts := bar.get("ts_event")), int)
            and not isinstance(ts, bool)
            and ts > 0
        ),
        key=lambda bar: int(bar["ts_event"]),
    )

    buckets: dict[int, dict[str, Any]] = {}
    for bar in ordered_bars:
        ts_event = int(bar["ts_event"])
        bucket_ts = _bar_minute_bucket(ts_event, minutes)
        bucket = buckets.get(bucket_ts)
        if bucket is None:
            bucket = {
                "open": None,
                "high": None,
                "low": None,
                "close": None,
                "volume": None,
                "ts_event": bucket_ts,
                "_first_ts": None,
                "_last_ts": None,
            }
            buckets[bucket_ts] = bucket

        open_ = _coerce_finite_float(bar.get("open"))
        high = _coerce_finite_float(bar.get("high"))
        low = _coerce_finite_float(bar.get("low"))
        close = _coerce_finite_float(bar.get("close"))
        volume = _coerce_volume(bar.get("volume"))

        if open_ is not None and (bucket["_first_ts"] is None or ts_event < bucket["_first_ts"]):
            bucket["open"] = open_
            bucket["_first_ts"] = ts_event
        if high is not None:
            bucket["high"] = high if bucket["high"] is None else max(bucket["high"], high)
        if low is not None:
            bucket["low"] = low if bucket["low"] is None else min(bucket["low"], low)
        if close is not None and (bucket["_last_ts"] is None or ts_event >= bucket["_last_ts"]):
            bucket["close"] = close
            bucket["_last_ts"] = ts_event
        if volume is not None:
            bucket["volume"] = volume if bucket["volume"] is None else bucket["volume"] + volume

    # Drop buckets that contain no valid close — they cannot contribute
    # to any indicator and would otherwise create empty aggregated bars.
    out: list[dict[str, Any]] = []
    for _, bucket in sorted(buckets.items()):
        if bucket["close"] is None:
            continue
        bucket.pop("_first_ts", None)
        bucket.pop("_last_ts", None)
        out.append(bucket)
    return out


def _bars_for_timeframe(bars: list[dict[str, Any]], tf: str) -> list[dict[str, Any]]:
    """Return bars for indicator computation at the requested timeframe.

    We aggregate from 1-minute cache bars when possible. If aggregation yields
    no usable bars and the input has no valid ``ts_event`` values (for example
    synthetic/unit-test inputs), fall back to the provided input bars so
    indicator invariants remain stable.
    """
    aggregated = _aggregate_bars(bars, tf)
    if aggregated:
        return aggregated

    has_valid_ts_event = any(
        isinstance((ts := bar.get("ts_event")), int)
        and not isinstance(ts, bool)
        and ts > 0
        for bar in bars
    )
    return [] if has_valid_ts_event else list(bars)


def compute_flow_fields(bars: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute flow_rel_vol, flow_delta_proxy_pct from bar list."""
    if not bars:
        return {"flow_rel_vol": None, "flow_delta_proxy_pct": None}

    # Anchor volume ratio to the CURRENT (last) bar.  If the last bar has no
    # volume we must NOT fall back to bars[-2].volume — that would silently
    # report a one-bar-stale ratio alongside the current bar's price delta.
    # _coerce_volume also guards against string volumes from schema-drift producers.
    last_bar = bars[-1]
    last_vol: float | None = _coerce_volume(last_bar.get("volume"))
    if last_vol is not None:
        prior_volumes = [
            fv
            for b in bars[:-1]
            if (fv := _coerce_volume(b.get("volume"))) is not None
        ]
        avg_vol: float | None = _safe_mean(prior_volumes) if prior_volumes else None
    else:
        avg_vol = None

    flow_rel_vol: float | None = None
    if avg_vol and avg_vol > 0 and last_vol is not None:
        flow_rel_vol = round(last_vol / avg_vol, 4)

    open_ = _coerce_finite_float(last_bar.get("open"))
    close_ = _coerce_finite_float(last_bar.get("close"))
    flow_delta: float | None = None
    if open_ is not None and open_ > 0 and close_ is not None:
        flow_delta = round((close_ - open_) / open_ * 100, 4)

    return {"flow_rel_vol": flow_rel_vol, "flow_delta_proxy_pct": flow_delta}


def compute_squeeze_on(bars: list[dict[str, Any]], period: int = 20) -> bool | None:
    """
    Squeeze = True when Bollinger Band width < Keltner Channel width.
    Approximated here as: BB width < 2 × ATR (simplified single-symbol check).

    Uses aligned filtering: only bars that have ALL of close, high, and low
    are included, so the TR calculation is never computed from misaligned bars
    (which would happen if each field were filtered independently).
    """
    # Build aligned triples so that closes_w[i], highs_w[i], lows_w[i]
    # all refer to the SAME bar. Independent per-field filtering would
    # produce cross-bar ATR when any bar in the window is missing a field.
    triples: list[tuple[float, float, float]] = []
    for b in bars:
        close = _coerce_finite_float(b.get("close"))
        high = _coerce_finite_float(b.get("high"))
        low = _coerce_finite_float(b.get("low"))
        if close is None or high is None or low is None:
            continue
        # Defensive: reject malformed bars where provider data violates OHLC
        # ordering. Keeping such bars would create negative true ranges and
        # can produce false-positive squeeze signals.
        if high < low:
            continue
        # Defensive: close must lie inside [low, high]. Values outside this
        # envelope indicate malformed OHLC bars and can produce false-positive
        # squeeze signals (std close collapses while ATR remains positive).
        if not (low <= close <= high):
            continue
        triples.append((close, high, low))

    if len(triples) < period:
        return None

    window = triples[-period:]
    closes_w = [t[0] for t in window]
    highs_w = [t[1] for t in window]
    lows_w = [t[2] for t in window]

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

    All fields are anchored to bars[-1] to avoid cross-bar misalignment.
    B19: if bars[-1] has no volume, zscore and state are both None.
    B20: if bars[-1] has no close or open, state falls back to "neutral"
         rather than using close/open from a different (prior) bar.
    """
    if not bars:
        return {"ats_state": None, "ats_zscore": None}

    # Anchor to the CURRENT (last) bar — do not fall through to prior bars.
    # _coerce_volume also guards against string volumes from schema-drift producers.
    last_bar = bars[-1]
    last_vol = _coerce_volume(last_bar.get("volume"))
    if last_vol is None:
        # Cannot compute a z-score for a bar with no volume.
        return {"ats_state": None, "ats_zscore": None}

    prior_vols = [
        fv
        for b in bars[:-1]
        if (fv := _coerce_volume(b.get("volume"))) is not None
    ]
    if len(prior_vols) < 4:
        # Need at least 4 prior bars (+ 1 current = 5 total) for a meaningful
        # mean/std — matches the original ≥5-volume guard.
        return {"ats_state": None, "ats_zscore": None}

    mean_v = sum(prior_vols) / len(prior_vols)
    std_v = _safe_std(prior_vols)

    zscore: float | None = None
    if std_v > 0:
        zscore = round((last_vol - mean_v) / std_v, 4)

    last_open = _coerce_finite_float(last_bar.get("open"))
    last_close = _coerce_finite_float(last_bar.get("close"))
    if last_open is None or last_close is None:
        # Cannot determine price direction for this bar; avoid cross-bar delta.
        state = "neutral"
    else:
        # Simple heuristic: price trend × volume z-score
        price_delta = last_close - last_open
        if price_delta > 0 and (zscore or 0) >= 0.5:
            state = "accumulation"
        elif price_delta < 0 and (zscore or 0) >= 0.5:
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
    tf: str = "5m",
) -> dict[str, Any]:
    """Build the full overlay payload for one symbol.

    The supplied ``bars`` are expected to be 1-minute bars. They are
    aggregated to the requested ``tf`` before computing technical
    indicators.
    """
    # asof_ts is Unix-Epoch seconds (int) per smc-live-overlay/1 schema
    asof_ts = int(datetime.datetime.now(datetime.UTC).timestamp())

    aggregated = _bars_for_timeframe(bars, tf)

    news = _get_news_fields(symbol)
    flow = compute_flow_fields(aggregated)
    squeeze_period = len(aggregated) if 5 <= len(aggregated) < 20 else 20
    squeeze = compute_squeeze_on(aggregated, period=squeeze_period)
    ats = compute_ats_fields(aggregated)
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


def run_full_compute_cycle(tf: str = "5m") -> int:
    """
    Compute overlay payloads for ALL symbols currently in the bar cache.
    Returns number of symbols computed.
    Called every OVERLAY_REFRESH_SECS by the refresh thread.
    """
    with observability.trace_span("live_overlay.full_compute_cycle"):
        all_bars = cache.get_all_symbols_snapshot()
        max_stale = config.max_stale_secs()
        global_fields = _get_global_news_fields()

        payloads: dict[str, Any] = {}
        for sym, bars in all_bars.items():
            if not bars:
                continue
            payloads[sym.upper()] = build_payload(sym, bars, global_fields, max_stale, tf=tf)

        # Always replace snapshot (including empty) so stale symbols are removed
        # when bar cache is temporarily empty.
        cache.set_overlay(payloads)

        count = len(payloads)
        observability.metric_gauge("live_overlay.overlay_symbols", count)
        observability.metric_counter("live_overlay.full_compute_cycle.total")
        observability.audit_event(
            "live_overlay_full_compute_cycle",
            "ok",
            symbols=count,
        )
        return count


def run_flow_patch_cycle(tf: str = "5m") -> int:
    """
    Fast refresh: recompute only flow fields for all symbols.
    Does NOT reset the full overlay cache timestamp.
    Called every OVERLAY_FLOW_REFRESH_SECS.
    """
    with observability.trace_span("live_overlay.flow_patch_cycle"):
        all_bars = cache.get_all_symbols_snapshot()
        vix = cache.get_vix()
        count = 0
        for sym, bars in all_bars.items():
            if not bars:
                continue
            aggregated = _bars_for_timeframe(bars, tf)
            updates = compute_flow_fields(aggregated)
            if (vix_value := _coerce_finite_float(vix)) is not None:
                updates["vix_level"] = round(vix_value, 4)
            cache.patch_overlay(
                sym,
                updates,
                allow_none_keys={"flow_rel_vol", "flow_delta_proxy_pct"},
            )
            count += 1
        observability.metric_gauge("live_overlay.flow_patch_symbols", count)
        observability.metric_counter("live_overlay.flow_patch_cycle.total")
        observability.audit_event(
            "live_overlay_flow_patch_cycle",
            "ok",
            symbols=count,
        )
        return count
