"""Realtime signal engine — FMP-polling breakout detector with A0/A1 alerting.

Monitors top-N ranked candidates from the latest open_prep run, polls FMP
at a configurable interval (default 45 s), and detects breakout signals.

Signal Levels
-------------
  A0 — Immediate action: strong breakout confirmed with volume.
  A1 — Watch closely: early breakout pattern forming, pre-confirmation.

VisiData Integration
--------------------
Use ``--fast`` (5 s poll) or ``--ultra`` (2 s poll) to enable near-realtime
monitoring.  The engine writes a compact JSONL file
(``latest_vd_signals.jsonl``) with one row per symbol that VisiData can
``--filetype jsonl`` watch.  Each row includes Δ-columns so price/volume
changes are visible at a glance::

    vd --filetype jsonl artifacts/open_prep/latest/latest_vd_signals.jsonl

Usage::

    # Standalone polling loop (runs forever, writes signals to JSON)
    python -m open_prep.realtime_signals --interval 45

    # Near-realtime VisiData mode (2 s poll, minimal I/O)
    python -m open_prep.realtime_signals --ultra

    # As a library (for Streamlit integration)
    from open_prep.realtime_signals import RealtimeEngine
    engine = RealtimeEngine(poll_interval=45, top_n=10)
    engine.poll_once()  # single iteration
    signals = engine.get_active_signals()
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .macro import FMPClient
from .signal_decay import adaptive_freshness_decay
from .utils import to_float as _safe_float

logger = logging.getLogger("open_prep.realtime_signals")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_ARTIFACTS_LATEST = Path("artifacts/open_prep/latest")
SIGNALS_PATH = _ARTIFACTS_LATEST / "latest_realtime_signals.json"
VD_SIGNALS_PATH = _ARTIFACTS_LATEST / "latest_vd_signals.jsonl"
LATEST_RUN_PATH = _ARTIFACTS_LATEST / "latest_open_prep_run.json"

# Backward-compat: also check old location in package dir
_LEGACY_RUN_PATH = Path(__file__).resolve().parent / "latest_open_prep_run.json"
DEFAULT_POLL_INTERVAL = 20  # seconds (was 45 — faster detection)
DEFAULT_TOP_N = 15

# Signal level thresholds
A0_VOLUME_RATIO_MIN = 3.0        # 3x avg volume for A0
A1_VOLUME_RATIO_MIN = 1.0        # 1x for A1 (was 1.5 — too late for mid-caps)
A2_VOLUME_RATIO_MIN = 0.6        # 0.6x for A2 early warning
A0_PRICE_CHANGE_PCT_MIN = 1.5    # 1.5% move for A0
A1_PRICE_CHANGE_PCT_MIN = 0.35   # 0.35% for A1 (was 0.5 — missed slow grinders)
A2_PRICE_CHANGE_PCT_MIN = 0.15   # 0.15% for A2 early warning

# Signal expiry & time-based level decay
MAX_SIGNAL_AGE_SECONDS = 480     # 8 min total signal life (was 15 — still too long)
A0_MAX_AGE_SECONDS = 180         # A0 → A1 after 3 min (was 5 — stale A0s)
A1_MAX_AGE_SECONDS = 300         # A1 → A2 after 5 min (was 10)

# Price velocity — detect stale moves where cumulative change is misleading
VELOCITY_LOOKBACK = 5            # polls to look back for price velocity
STALE_VELOCITY_PCT = 0.05        # <0.05% change over lookback = flat/stale

# Multi-rail safety: minimum time between A0 signals per symbol (#7)
A0_COOLDOWN_SECONDS = 600  # 10 minutes between A0 signals per symbol

# Holiday/volume-regime: fraction of thin symbols triggering auto-detection (#9)
THIN_VOLUME_FRACTION_SUSPEND = 0.80  # ≥80% thin → suspend all signals
THIN_VOLUME_FRACTION_RELAX = 0.50    # ≥50% thin → relax thresholds 20%
THIN_VOLUME_RATIO = 0.5             # symbol is "thin" if vol < 50% avg


# ═══════════════════════════════════════════════════════════════════════════
# Quote Delta Tracker — per-symbol Δ columns for VisiData
# ═══════════════════════════════════════════════════════════════════════════

class QuoteDeltaTracker:
    """Track price/volume deltas between consecutive polls.

    Provides per-symbol Δ-price, Δ-volume, tick direction, and streak
    counters that VisiData can display for instant change visibility.
    """

    def __init__(self) -> None:
        # symbol → {price, volume, epoch}
        self._prev: dict[str, dict[str, float]] = {}
        # symbol → streak counter (+N = N consecutive upticks, -N = downticks)
        self._streaks: dict[str, int] = {}

    def update(self, symbol: str, price: float, volume: float) -> dict[str, Any]:
        """Record a new quote and return the delta dict."""
        prev = self._prev.get(symbol)
        now = time.time()

        if prev is None:
            self._prev[symbol] = {"price": price, "volume": volume, "epoch": now}
            self._streaks[symbol] = 0
            return {
                "d_price": 0.0,
                "d_price_pct": 0.0,
                "d_volume": 0,
                "tick": "=",
                "streak": 0,
                "poll_age_s": 0.0,
            }

        d_price = price - prev["price"]
        d_price_pct = (d_price / prev["price"] * 100.0) if prev["price"] > 0 else 0.0
        d_volume = volume - prev["volume"]

        # Tick direction
        if d_price > 0.005:
            tick = "▲"
            streak = max(self._streaks.get(symbol, 0), 0) + 1
        elif d_price < -0.005:
            tick = "▼"
            streak = min(self._streaks.get(symbol, 0), 0) - 1
        else:
            tick = "="
            streak = 0

        self._streaks[symbol] = streak
        poll_age = now - prev["epoch"]
        self._prev[symbol] = {"price": price, "volume": volume, "epoch": now}

        return {
            "d_price": round(d_price, 4),
            "d_price_pct": round(d_price_pct, 4),
            "d_volume": int(d_volume),
            "tick": tick,
            "streak": streak,
            "poll_age_s": round(poll_age, 1),
        }


# ═══════════════════════════════════════════════════════════════════════════
# Async Newsstack Poller — background thread for non-blocking news fetch
# ═══════════════════════════════════════════════════════════════════════════

class AsyncNewsstackPoller:
    """Poll newsstack in a background thread so it never blocks the main loop.

    The result is cached and updated asynchronously.  ``latest()`` always
    returns immediately with the most recent data (or empty dict on first call).
    """

    def __init__(self, poll_interval: float = 15.0) -> None:
        import threading
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._interval = max(poll_interval, 5.0)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        """Start the background polling thread (daemon)."""
        import threading
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="newsstack-bg")
        self._thread.start()
        logger.info("Async newsstack poller started (interval=%.0fs)", self._interval)

    def stop(self) -> None:
        self._stop.set()

    def latest(self) -> dict[str, dict[str, Any]]:
        """Return the latest newsstack data (never blocks)."""
        with self._lock:
            return dict(self._data)

    def _loop(self) -> None:
        _newsstack_poll: Any = None
        _NSConfig: Any = None
        while not self._stop.is_set():
            try:
                if _newsstack_poll is None:
                    from newsstack_fmp.config import Config as _NSConfig
                    from newsstack_fmp.pipeline import poll_once as _newsstack_poll

                ns_candidates = _newsstack_poll(_NSConfig())
                new_data: dict[str, dict[str, Any]] = {}
                for nc in ns_candidates:
                    tk = str(nc.get("ticker", "")).strip().upper()
                    if tk:
                        prev = new_data.get(tk)
                        if prev is None or nc.get("news_score", 0) > prev.get("news_score", 0):
                            new_data[tk] = nc
                with self._lock:
                    self._data = new_data
            except Exception as exc:
                logger.debug("Async newsstack poll error: %s", exc)
            self._stop.wait(self._interval)


# ---------------------------------------------------------------------------
# Market-hours gate
# ---------------------------------------------------------------------------

def _expected_cumulative_volume_fraction() -> float:
    """Expected fraction of daily volume at current time of day.

    Uses a front-loaded intraday model (volume "U-shape"):
      - First 30 min (9:30-10:00): ~25% of daily volume
      - 10:00-11:00: ~15% more (40% cumulative)
      - 11:00-15:30: ~45% spread roughly evenly
      - 15:30-16:00: ~15% closing surge

    Returns a value in [0.02, 1.0].  Used to normalize raw volume_ratio
    so that early-morning breakouts are detectable BEFORE cumulative
    volume reaches the daily average.
    """
    try:
        from zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        try:
            from dateutil.tz import gettz
            now_et = datetime.now(gettz("America/New_York"))
        except Exception:
            return 1.0  # no tz info → no adjustment

    if now_et.weekday() >= 5:
        return 1.0  # weekend — no adjustment

    open_min = 9 * 60 + 30   # 9:30 ET
    close_min = 16 * 60      # 16:00 ET
    now_min = now_et.hour * 60 + now_et.minute

    if now_min < open_min:
        return 0.02  # pre-market: expect very little volume

    elapsed = now_min - open_min
    total = close_min - open_min  # 390 minutes

    if elapsed >= total:
        return 1.0  # after close — raw ratio is fine

    # Front-loaded model:
    if elapsed <= 30:
        frac = 0.25 * (elapsed / 30)           # 0→25% in first 30 min
    elif elapsed <= 90:
        frac = 0.25 + 0.15 * ((elapsed - 30) / 60)  # 25→40% in next 60 min
    else:
        frac = 0.40 + 0.60 * ((elapsed - 90) / 300)  # 40→100% over last 300 min

    return max(frac, 0.02)


def _is_within_market_hours() -> bool:
    """Return ``True`` when the current US-Eastern time is within extended
    trading hours (Mon–Fri, 04:00–20:00 ET).

    Uses ``zoneinfo`` (stdlib ≥ 3.9) with a fallback to ``dateutil.tz``
    and then a UTC-offset estimation so the gate never crashes.
    """
    try:
        from zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        try:
            from dateutil.tz import gettz
            now_et = datetime.now(gettz("America/New_York"))
        except Exception:
            # Last resort: UTC − 4 (EDT) — accepts the full 04:00–20:00
            # ET window during both EST and EDT.  During EST (Nov–Mar) the
            # gate opens/closes ~1 h early, which is acceptable.
            from datetime import timedelta
            now_et = datetime.now(UTC) - timedelta(hours=4)

    # Monday=0, Sunday=6
    if now_et.weekday() >= 5:
        return False

    hour = now_et.hour
    _minute = now_et.minute
    # 04:00–20:00 ET (pre-market 04:00, regular 09:30-16:00, after-hours until 20:00)
    if hour < 4:
        return False
    return hour < 20


# ═══════════════════════════════════════════════════════════════════════════
# Score Telemetry — operational metrics for monitoring / dashboards
# ═══════════════════════════════════════════════════════════════════════════

class ScoreTelemetry:
    """Rolling statistics for scoring and signal generation.

    Accumulates per-poll metrics in bounded deques so memory is constant.
    A JSON snapshot is served via an optional HTTP endpoint.
    """

    def __init__(self, maxlen: int = 500) -> None:
        self._score_diffs: deque[float] = deque(maxlen=maxlen)
        self._volume_ratios: deque[float] = deque(maxlen=maxlen)
        self._change_pcts: deque[float] = deque(maxlen=maxlen)
        self._a0_events: deque[float] = deque(maxlen=maxlen)  # 1.0 if A0, else 0.0
        self._poll_count: int = 0

    def record(
        self,
        signals: list[Any],
        *,
        score_diff: float = 0.0,
        volume_ratio: float = 0.0,
        change_pct: float = 0.0,
    ) -> None:
        """Record metrics from a single poll cycle."""
        self._poll_count += 1
        self._score_diffs.append(score_diff)
        self._volume_ratios.append(volume_ratio)
        self._change_pcts.append(change_pct)
        a0 = 1.0 if any(getattr(s, "level", "") == "A0" for s in signals) else 0.0
        self._a0_events.append(a0)

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary of accumulated metrics."""

        def _stats(d: deque[float]) -> dict[str, float]:
            if not d:
                return {"min": 0.0, "mean": 0.0, "max": 0.0, "count": 0}
            vals = sorted(d)
            n = len(vals)
            return {
                "min": round(vals[0], 4),
                "mean": round(sum(vals) / n, 4),
                "median": round(vals[n // 2], 4),
                "max": round(vals[-1], 4),
                "count": n,
            }

        return {
            "poll_count": self._poll_count,
            "score_diff": _stats(self._score_diffs),
            "volume_ratio": _stats(self._volume_ratios),
            "change_pct": _stats(self._change_pcts),
            "a0_rate": round(sum(self._a0_events) / max(len(self._a0_events), 1), 4),
        }


# ---------------------------------------------------------------------------
# Telemetry HTTP server (runs in a daemon thread)
# ---------------------------------------------------------------------------

def _start_telemetry_server(
    telemetry: ScoreTelemetry,
    port: int = 8099,
) -> Any:
    """Launch a lightweight HTTP server serving ``/telemetry.json`` and ``/healthz``.

    Runs as a daemon thread — will be cleaned up when the main process exits.
    Returns the HTTPServer instance (or None on failure) for graceful shutdown.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/healthz":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"ok\n")
            elif self.path in ("/telemetry.json", "/telemetry"):
                import json as _json
                body = _json.dumps(telemetry.snapshot(), indent=2, allow_nan=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, fmt: str, *args: Any) -> None:
            # Silence standard request logging to avoid log noise
            pass

    try:
        server = HTTPServer(("127.0.0.1", port), _Handler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        logger.info("Telemetry HTTP server listening on http://127.0.0.1:%d", port)
        return server
    except OSError as exc:
        logger.warning("Could not start telemetry server on port %d: %s", port, exc)
        return None


# ═══════════════════════════════════════════════════════════════════════════
# Dynamic Cooldown (Oscillation-Based) — enables high-frequency VisiData
# ═══════════════════════════════════════════════════════════════════════════

class DynamicCooldown:
    """Adaptive cooldown between A0 signals per symbol.

    Ported from IB_MON's oscillation-aware cooldown logic.  Instead of a
    fixed 10-minute gap between A0 signals, the cooldown adjusts based on:

    1. **Volume regime** — thin-volume sessions use longer cooldowns to
       avoid false breakout spam; high-volume sessions shrink it.
    2. **Oscillation detection** — if a symbol flips direction rapidly
       (A0 LONG → A0 SHORT within *window*), cooldown is extended to
       suppress whipsaw alerts.
    3. **News catalyst** — when a fresh news event backs the breakout,
       cooldown is reduced to allow near-realtime re-alerting for
       VisiData monitors.

    Parameters
    ----------
    base_seconds : float
        Default cooldown before any adjustments (default: 120s — down from
        the old fixed 600s to enable faster VisiData refresh).
    min_seconds : float
        Absolute floor for cooldown (default: 5s for near-realtime).
    max_seconds : float
        Absolute ceiling (default: 600s = old fixed value).
    oscillation_window : int
        Number of recent A0 transitions to track per symbol.
    oscillation_threshold : int
        Number of direction changes within *oscillation_window* that
        triggers the oscillation penalty.
    """

    def __init__(
        self,
        base_seconds: float = 120.0,
        min_seconds: float = 5.0,
        max_seconds: float = 600.0,
        oscillation_window: int = 6,
        oscillation_threshold: int = 3,
    ) -> None:
        self.base_seconds = base_seconds
        self.min_seconds = min_seconds
        self.max_seconds = max_seconds
        self._osc_window = oscillation_window
        self._osc_threshold = oscillation_threshold

        # Per-symbol ring buffer of (epoch, direction)
        self._transitions: dict[str, deque[tuple[float, str]]] = {}
        # Last A0 timestamp per symbol
        self._last_a0: dict[str, float] = {}

    def _oscillation_factor(self, symbol: str) -> float:
        """Return a multiplier ≥ 1.0 if the symbol is oscillating."""
        hist = self._transitions.get(symbol)
        if not hist or len(hist) < 3:
            return 1.0
        # Count direction flips
        flips = sum(
            1
            for i in range(1, len(hist))
            if hist[i][1] != hist[i - 1][1]
        )
        if flips >= self._osc_threshold:
            # Strong oscillation: extend cooldown by up to 3×
            return min(3.0, 1.0 + (flips - self._osc_threshold + 1) * 0.5)
        return 1.0

    @staticmethod
    def _regime_factor(volume_regime: str) -> float:
        """Adjust cooldown based on the current volume regime.

        - ``"THIN"``   → 2.0× longer (suppress noise)
        - ``"NORMAL"`` → 1.0 (no change)
        - ``"HIGH"``   → 0.4× shorter (fast markets)
        """
        return {"THIN": 2.0, "NORMAL": 1.0, "HIGH": 0.4}.get(volume_regime, 1.0)

    def compute(
        self,
        symbol: str,
        volume_regime: str = "NORMAL",
        has_news_catalyst: bool = False,
    ) -> float:
        """Compute the current cooldown duration in seconds for *symbol*.

        Returns a value in [min_seconds, max_seconds].
        """
        cd = self.base_seconds
        cd *= self._regime_factor(volume_regime)
        cd *= self._oscillation_factor(symbol)
        if has_news_catalyst:
            cd *= 0.3  # slash cooldown when news backs the move
        return max(self.min_seconds, min(cd, self.max_seconds))

    def record_transition(self, symbol: str, direction: str) -> None:
        """Record an A0 transition (direction flip tracking)."""
        now = time.monotonic()
        if symbol not in self._transitions:
            self._transitions[symbol] = deque(maxlen=self._osc_window)
        self._transitions[symbol].append((now, direction))
        self._last_a0[symbol] = now

    def check_cooldown(
        self,
        symbol: str,
        volume_regime: str = "NORMAL",
        has_news_catalyst: bool = False,
    ) -> tuple[bool, float]:
        """Check if the A0 cooldown is still active for *symbol*.

        Returns
        -------
        (is_active, remaining_seconds)
            ``is_active`` is True when the symbol is still in cooldown.
            ``remaining_seconds`` is > 0 when active, else 0.
        """
        last = self._last_a0.get(symbol, 0.0)
        if last == 0.0:
            return False, 0.0
        cd = self.compute(symbol, volume_regime, has_news_catalyst)
        elapsed = time.monotonic() - last
        if elapsed < cd:
            return True, cd - elapsed
        return False, 0.0


# ═══════════════════════════════════════════════════════════════════════════
# #1  Gate Hysteresis — prevents A0↔A1 flapping near thresholds
# ═══════════════════════════════════════════════════════════════════════════

class GateHysteresis:
    """Anti-flapping filter for signal level transitions.

    Prevents a symbol from rapidly oscillating between A0 and A1 when its
    metrics hover near the threshold.  A transition is allowed only when:
      (a) the new level is *clearly* beyond the threshold (outside the
          margin band), OR
      (b) sufficient time has elapsed since the last transition.
    """

    def __init__(
        self,
        margin_pct: float = 0.02,
        min_hold_seconds: float = 30.0,  # was 90 — faster upgrades
    ):
        self._margin_pct = margin_pct
        self._min_hold = min_hold_seconds
        # {symbol: {"level": "A0"|"A1", "ts": float}}
        self._state: dict[str, dict[str, Any]] = {}

    def evaluate(
        self,
        symbol: str,
        proposed_level: str,
        volume_ratio: float,
        abs_change_pct: float,
    ) -> str:
        """Return the effective signal level after hysteresis filtering.

        If the proposed level differs from the current state and the metrics
        are within the margin band AND not enough time has passed, the level
        is kept unchanged rather than allowed to flip.
        """
        now = time.monotonic()
        prev = self._state.get(symbol)

        if prev is None:
            # First time — accept whatever is proposed
            self._state[symbol] = {"level": proposed_level, "ts": now}
            return proposed_level

        if proposed_level == prev["level"]:
            return proposed_level  # no transition, nothing to gate

        # Transition requested — check if it's clearly beyond threshold
        a0_vol_margin = A0_VOLUME_RATIO_MIN * (1 - self._margin_pct)
        a0_chg_margin = A0_PRICE_CHANGE_PCT_MIN * (1 - self._margin_pct)

        clearly_a0 = (
            volume_ratio >= A0_VOLUME_RATIO_MIN * (1 + self._margin_pct)
            and abs_change_pct >= A0_PRICE_CHANGE_PCT_MIN * (1 + self._margin_pct)
        )
        clearly_a1 = (
            volume_ratio < a0_vol_margin
            or abs_change_pct < a0_chg_margin
        )

        is_clear = clearly_a0 if proposed_level == "A0" else clearly_a1
        elapsed = now - prev["ts"]

        if is_clear or elapsed >= self._min_hold:
            self._state[symbol] = {"level": proposed_level, "ts": now}
            return proposed_level

        # Within margin band and too soon — keep current level
        logger.debug(
            "Hysteresis: %s kept at %s (proposed %s, elapsed=%.0fs)",
            symbol, prev["level"], proposed_level, elapsed,
        )
        return str(prev["level"])

    def record(self, symbol: str, level: str) -> None:
        """Record the level for a symbol without hysteresis evaluation."""
        self._state[symbol] = {"level": level, "ts": time.monotonic()}


# ═══════════════════════════════════════════════════════════════════════════
# #9  Volume-Regime Auto-Detection — detects thin/holiday sessions
# ═══════════════════════════════════════════════════════════════════════════

class VolumeRegimeDetector:
    """Dynamically detects low-volume / holiday sessions.

    On each poll cycle, call ``update()`` with the quote map.  The detector
    computes the fraction of symbols with volume far below their average.
    If ≥80 % are thin → all signals are suspended (holiday mode).
    If ≥50 % are thin → thresholds are relaxed by 20 %.
    """

    def __init__(self) -> None:
        self.regime: str = "NORMAL"  # "NORMAL", "LOW_VOLUME", "HOLIDAY_SUSPECT"
        self.thin_fraction: float = 0.0

    def update(self, quotes: dict[str, dict[str, Any]]) -> str:
        if not quotes:
            self.regime = "NORMAL"
            self.thin_fraction = 0.0
            return self.regime

        thin_count = 0
        total = 0
        for _sym, q in quotes.items():
            vol = _safe_float(q.get("volume"), 0.0)
            avg_vol = _safe_float(q.get("avgVolume"), 0.0)
            if avg_vol <= 0:
                continue   # unknown volume — exclude from both counts
            total += 1
            if vol < avg_vol * THIN_VOLUME_RATIO:
                thin_count += 1

        self.thin_fraction = (thin_count / total) if total > 0 else 0.0

        if self.thin_fraction >= THIN_VOLUME_FRACTION_SUSPEND:
            new_regime = "HOLIDAY_SUSPECT"
        elif self.thin_fraction >= THIN_VOLUME_FRACTION_RELAX:
            new_regime = "LOW_VOLUME"
        else:
            new_regime = "NORMAL"

        if new_regime != self.regime:
            logger.info(
                "Volume regime: %s → %s (%.0f%% thin symbols)",
                self.regime, new_regime, self.thin_fraction * 100,
            )
        self.regime = new_regime
        return self.regime

    def adjusted_thresholds(self) -> dict[str, float]:
        """Return multiplied thresholds based on current regime."""
        if self.regime == "HOLIDAY_SUSPECT":
            return {"vol_mult": 999.0, "chg_mult": 999.0}  # effectively suspend
        if self.regime == "LOW_VOLUME":
            return {"vol_mult": 1.20, "chg_mult": 1.20}  # relax by 20%
        return {"vol_mult": 1.0, "chg_mult": 1.0}


# ═══════════════════════════════════════════════════════════════════════════
# #11  Dirty Flag — skip recompute for unchanged quotes
# ═══════════════════════════════════════════════════════════════════════════

def _quote_hash(q: dict[str, Any]) -> str:
    """Deterministic hash of the price+volume+changesPercentage fields."""
    key = (f"{q.get('price','')},{q.get('lastPrice','')},"
           f"{q.get('volume','')},{q.get('changesPercentage','')}")
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _format_age_hms(seconds: float) -> str:
    """Format elapsed seconds as HH:MM:SS."""
    total = max(int(seconds), 0)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


@dataclass
class RealtimeSignal:
    """A single realtime breakout signal."""
    symbol: str
    level: str                        # "A0" or "A1"
    direction: str                    # "LONG", "SHORT", "B_UP", "B_DOWN"
    pattern: str                      # from detect_breakout
    price: float
    prev_close: float
    change_pct: float
    volume_ratio: float
    score: float                      # from v2 ranking (if available)
    confidence_tier: str              # from v2 ranking
    atr_pct: float
    freshness: float                  # 0..1 (signal strength decay)
    fired_at: str                     # ISO timestamp
    fired_epoch: float                # unix timestamp for sorting/expiry
    level_since_at: str = ""          # ISO timestamp for current A0/A1 level start
    level_since_epoch: float = 0.0    # unix timestamp for current A0/A1 level start
    details: dict[str, Any] = field(default_factory=dict)
    symbol_regime: str = "NEUTRAL"
    # ── News catalyst enrichment (from newsstack_fmp) ──
    news_score: float = 0.0
    news_category: str = ""
    news_headline: str = ""
    news_warn_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def is_expired(self, now_epoch: float | None = None) -> bool:
        now = now_epoch or time.time()
        return (now - self.fired_epoch) > MAX_SIGNAL_AGE_SECONDS


class RealtimeEngine:
    """FMP-polling breakout detection engine."""

    def __init__(
        self,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        top_n: int = DEFAULT_TOP_N,
        fmp_client: FMPClient | None = None,
        *,
        fast_mode: bool = False,
        ultra_mode: bool = False,
    ):
        # ultra_mode: 2s min poll, skips indent in JSON, async newsstack
        # fast_mode:  5s min poll (VisiData near-realtime)
        if ultra_mode:
            min_interval = 2
            fast_mode = True  # ultra implies fast
        elif fast_mode:
            min_interval = 5
        else:
            min_interval = 10
        self.poll_interval = max(min_interval, poll_interval)
        self.top_n = top_n
        self.fast_mode = fast_mode
        self.ultra_mode = ultra_mode
        self._client = fmp_client
        self._client_disabled_reason: str | None = None
        self._active_signals: list[RealtimeSignal] = []
        self._watchlist: list[dict[str, Any]] = []  # top-N from latest run
        self._last_prices: dict[str, float] = {}
        self._price_history: dict[str, deque[float]] = {}  # rolling window for velocity
        self._was_outside_market: bool = False  # session-boundary detection

        # #1 Gate hysteresis — anti-flapping for A0↔A1 transitions
        self._hysteresis = GateHysteresis()

        # #7 Dynamic cooldown (oscillation-based) — replaces fixed 600s
        self._dynamic_cooldown = DynamicCooldown(
            base_seconds=10.0 if ultra_mode else (20.0 if fast_mode else 60.0),
            min_seconds=2.0 if ultra_mode else 5.0,
            max_seconds=180.0 if ultra_mode else 300.0,
        )

        # #9 Volume-regime auto-detection
        self._volume_regime = VolumeRegimeDetector()

        # Score telemetry — operational metrics
        self.telemetry = ScoreTelemetry()

        # Quote delta tracker — Δ-columns for VisiData
        self._delta_tracker = QuoteDeltaTracker()

        # Async newsstack poller (started explicitly via start_async_newsstack)
        self._async_newsstack: AsyncNewsstackPoller | None = None

        # VisiData snapshot: latest per-symbol row data
        self._vd_rows: dict[str, dict[str, Any]] = {}
        self._vd_last_change_epoch: dict[str, float] = {}
        self._poll_seq: int = 0

        # Cached avg_volume & earnings (fetched once per watchlist load)
        self._avg_vol_cache: dict[str, float] = {}
        self._earnings_today_cache: dict[str, dict[str, Any]] = {}
        self._new_entrant_set: set[str] = set()

        # #11 Dirty flag — {symbol: quote_hash}
        self._quote_hashes: dict[str, str] = {}

        # Timing — last poll duration for adaptive sleep
        self.last_poll_duration: float = 0.0

        self._load_watchlist()
        self._restore_signals_from_disk()

    # ------------------------------------------------------------------
    # Restore non-expired signals from previous run (dedup across restarts)
    # ------------------------------------------------------------------
    def _restore_signals_from_disk(self) -> None:
        """Load previously persisted signals to avoid re-firing on restart."""
        try:
            data = self.load_signals_from_disk()
            now_epoch = time.time()
            for raw in data.get("signals", []):
                fired_epoch = _safe_float(raw.get("fired_epoch", 0), 0.0)
                if (now_epoch - fired_epoch) > MAX_SIGNAL_AGE_SECONDS:
                    continue  # already expired
                sig = RealtimeSignal(
                    symbol=str(raw.get("symbol", "")),
                    level=str(raw.get("level", "A1")),
                    direction=str(raw.get("direction", "LONG")),
                    pattern=str(raw.get("pattern", "")),
                    price=_safe_float(raw.get("price", 0), 0.0),
                    prev_close=_safe_float(raw.get("prev_close", 0), 0.0),
                    change_pct=_safe_float(raw.get("change_pct", 0), 0.0),
                    volume_ratio=_safe_float(raw.get("volume_ratio", 0), 0.0),
                    score=_safe_float(raw.get("score", 0), 0.0),
                    confidence_tier=str(raw.get("confidence_tier", "STANDARD")),
                    atr_pct=_safe_float(raw.get("atr_pct", 0), 0.0),
                    freshness=_safe_float(raw.get("freshness", 0), 0.0),
                    fired_at=str(raw.get("fired_at", "")),
                    fired_epoch=fired_epoch,
                    level_since_at=str(raw.get("level_since_at", raw.get("fired_at", ""))),
                    level_since_epoch=_safe_float(raw.get("level_since_epoch", fired_epoch), fired_epoch),
                    details=raw.get("details") or {},
                    symbol_regime=str(raw.get("symbol_regime", "NEUTRAL")),
                    news_score=_safe_float(raw.get("news_score", 0.0), 0.0),
                    news_category=str(raw.get("news_category", "")),
                    news_headline=str(raw.get("news_headline", "")),
                    news_warn_flags=list(raw.get("news_warn_flags") or []),
                )
                self._active_signals.append(sig)
            if self._active_signals:
                logger.info(
                    "Restored %d non-expired signal(s) from disk",
                    len(self._active_signals),
                )
        except Exception as exc:
            logger.debug("Could not restore signals from disk: %s", exc)

    @property
    def client(self) -> FMPClient:
        if self._client is None:
            try:
                self._client = FMPClient.from_env()
            except Exception as exc:
                # Fail-open: disable polling if API key missing or client cannot be built
                self._client_disabled_reason = str(exc)
                raise
        return self._client

    # ------------------------------------------------------------------
    # Load top-N symbols from latest open_prep run
    # ------------------------------------------------------------------
    def _load_watchlist(self) -> None:
        """Load top-N candidates from the latest pipeline result."""
        run_path = LATEST_RUN_PATH if LATEST_RUN_PATH.exists() else _LEGACY_RUN_PATH
        if not run_path.exists():
            logger.warning("No latest_open_prep_run.json found — watchlist empty")
            return
        try:
            with open(run_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            ranked_v2 = data.get("ranked_v2") or []
            # Take top_n by score (already sorted)
            self._watchlist = ranked_v2[:self.top_n]
            # Load new-entrant symbols from diff (for 🆕 column)
            diff = data.get("diff") or {}
            self._new_entrant_set = {
                s.upper() for s in (diff.get("new_entrants") or [])
            }
            logger.info(
                "Loaded %d symbols for realtime monitoring: %s",
                len(self._watchlist),
                [r.get("symbol") for r in self._watchlist],
            )
            self._enrich_watchlist_live()
        except Exception as exc:
            logger.warning("Failed to load watchlist: %s", exc)

    def _enrich_watchlist_live(self) -> None:
        """Fetch avg_volume + earnings from FMP for watchlist symbols.

        The batch-quote endpoint omits avgVolume.  Without it the volume
        ratio is meaningless (everything looks like A0).  We fetch company
        profiles once per watchlist load and cache the value.
        """
        try:
            client = self.client
        except Exception:
            return  # no API key — cannot enrich

        symbols = [
            str(r.get("symbol", "")).strip().upper()
            for r in self._watchlist if r.get("symbol")
        ]
        if not symbols:
            return

        # ── avg_volume from /stable/profile (one call per symbol) ──
        for sym in symbols:
            # Skip if watchlist already has a good value
            wl_avg = 0.0
            for w in self._watchlist:
                if w.get("symbol") == sym:
                    wl_avg = _safe_float(w.get("avg_volume"), 0.0)
                    break
            if wl_avg >= 1000 and sym in self._avg_vol_cache:
                continue  # already enriched
            try:
                profile = client.get_company_profile(sym)
                avg_vol = _safe_float(
                    profile.get("averageVolume") or profile.get("volAvg"), 0.0
                )
                if avg_vol >= 1000:
                    self._avg_vol_cache[sym] = avg_vol
                    # Also update watchlist entry so _detect_signal finds it
                    for w in self._watchlist:
                        if w.get("symbol") == sym and _safe_float(w.get("avg_volume"), 0.0) < 1000:
                            w["avg_volume"] = avg_vol
                            logger.debug("Enriched %s avg_volume=%.0f from profile", sym, avg_vol)
                time.sleep(0.15)  # throttle
            except Exception as exc:
                logger.debug("Profile fetch failed for %s: %s", sym, exc)

        # ── Earnings calendar for today ──
        try:
            from datetime import date as _date
            today = _date.today()
            earnings = client.get_earnings_calendar(today, today)
            for item in earnings:
                sym = str(item.get("symbol") or "").strip().upper()
                if sym in {s for s in symbols}:
                    self._earnings_today_cache[sym] = item
                    # Update watchlist entry
                    for w in self._watchlist:
                        if w.get("symbol") == sym:
                            w["earnings_today"] = True
                            raw_time = str(item.get("time") or item.get("releaseTime") or "").strip().lower()
                            w["earnings_timing"] = raw_time or None
                            logger.info("Earnings today: %s (timing=%s)", sym, raw_time or "unknown")
        except Exception as exc:
            logger.debug("Earnings calendar fetch failed: %s", exc)

    def reload_watchlist(self) -> None:
        """Reload watchlist from latest pipeline run."""
        self._load_watchlist()
        # Prune stale entries from per-symbol tracker dicts so they
        # don't grow unboundedly across daily watchlist rotations.
        wl_syms = {str(r.get("symbol", "")).strip().upper() for r in self._watchlist}
        for d in (
            self._last_prices, self._price_history,
            self._quote_hashes,
            self._delta_tracker._prev, self._delta_tracker._streaks,
            self._hysteresis._state,
            self._dynamic_cooldown._transitions,
            self._dynamic_cooldown._last_a0,
            self._vd_last_change_epoch,
            self._avg_vol_cache,
        ):
            stale = set(d) - wl_syms
            for k in stale:
                del d[k]

    def start_async_newsstack(self, poll_interval: float = 15.0) -> None:
        """Start the background newsstack poller (call once at startup)."""
        self._async_newsstack = AsyncNewsstackPoller(poll_interval=poll_interval)
        self._async_newsstack.start()

    # ------------------------------------------------------------------
    # Fetch current quotes for watched symbols
    # ------------------------------------------------------------------
    def _fetch_realtime_quotes(self) -> dict[str, dict[str, Any]]:
        """Fetch current quotes for all watched symbols via FMP batch quote."""
        if self._client_disabled_reason:
            return {}
        if not self._watchlist:
            return {}
        symbols = [str(r.get("symbol", "")).strip().upper() for r in self._watchlist if r.get("symbol")]
        if not symbols:
            return {}

        quotes: dict[str, dict[str, Any]] = {}
        try:
            # FMP batch quote endpoint
            raw = self.client.get_batch_quotes(symbols)
            for q in raw:
                sym = str(q.get("symbol", "")).strip().upper()
                if sym:
                    quotes[sym] = q
        except Exception as exc:
            logger.warning("Failed to fetch realtime quotes: %s", exc)
            # Fallback — individual quotes (capped to 10 to limit rate-limit pressure)
            for i, sym in enumerate(symbols[:10]):
                try:
                    q_list = self.client.get_batch_quotes([sym])
                    if q_list and isinstance(q_list, list) and q_list:
                        quotes[sym] = q_list[0]
                except Exception:
                    pass
                if i < len(symbols) - 1:
                    time.sleep(0.25)  # throttle fallback calls
        return quotes

    # ------------------------------------------------------------------
    # Signal detection
    # ------------------------------------------------------------------
    def _detect_signal(
        self,
        symbol: str,
        quote: dict[str, Any],
        watchlist_entry: dict[str, Any],
        *,
        regime_thresholds: dict[str, float] | None = None,
    ) -> RealtimeSignal | None:
        """Analyze a single symbol's current quote for breakout signals."""

        # --- Market-hours gate ---
        # Only detect signals during extended US trading hours (Mon–Fri, 4:00–20:00 ET).
        if not _is_within_market_hours():
            return None

        price = _safe_float(quote.get("price") or quote.get("lastPrice"), 0.0)
        prev_close = _safe_float(quote.get("previousClose"), 0.0)
        volume = _safe_float(quote.get("volume"), 0.0)
        avg_volume = _safe_float(
            quote.get("avgVolume") or watchlist_entry.get("avg_volume"), 0.0
        )
        # FMP batch-quote endpoint doesn't return avgVolume.
        # When truly unknown, we cannot compute a meaningful ratio —
        # skip signal detection rather than dividing by 1 and getting
        # an astronomical ratio (e.g. 147M) that forces everything to A0.
        if avg_volume < 1000:
            logger.debug(
                "Skipping %s: avg_volume=%.0f too low/missing for ratio",
                symbol, avg_volume,
            )
            return None

        if price <= 0 or prev_close <= 0:
            return None

        change_pct = ((price / prev_close) - 1) * 100
        raw_volume_ratio = volume / avg_volume

        # ── Time-of-day volume normalization ─────────────────────
        # Raw volume_ratio uses cumulative daily volume vs daily average.
        # At 10:00 AM, even an unusually active stock only shows 0.5x
        # because most of the day hasn't happened yet.  Normalize by
        # expected cumulative fraction so we measure *pace above average*
        # rather than *cumulative total*.
        vol_frac = _expected_cumulative_volume_fraction()
        volume_ratio = raw_volume_ratio / max(vol_frac, 0.02)

        atr_pct = _safe_float(watchlist_entry.get("atr_pct_computed") or watchlist_entry.get("atr_pct"), 0.0)
        confidence_tier = str(watchlist_entry.get("confidence_tier", "STANDARD"))
        v2_score = _safe_float(watchlist_entry.get("score"), 0.0)
        symbol_regime = str(watchlist_entry.get("symbol_regime", "NEUTRAL"))

        # Check for significant price movement
        abs_change = abs(change_pct)

        # Apply volume-regime-adjusted thresholds (#9)
        rt = regime_thresholds or {"vol_mult": 1.0, "chg_mult": 1.0}
        eff_a0_vol = A0_VOLUME_RATIO_MIN * rt["vol_mult"]
        eff_a1_vol = A1_VOLUME_RATIO_MIN * rt["vol_mult"]
        eff_a2_vol = A2_VOLUME_RATIO_MIN * rt["vol_mult"]
        eff_a0_chg = A0_PRICE_CHANGE_PCT_MIN * rt["chg_mult"]
        eff_a1_chg = A1_PRICE_CHANGE_PCT_MIN * rt["chg_mult"]
        eff_a2_chg = A2_PRICE_CHANGE_PCT_MIN * rt["chg_mult"]

        # Determine signal level (A0 > A1 > A2)
        level: str | None = None
        if volume_ratio >= eff_a0_vol and abs_change >= eff_a0_chg:
            level = "A0"
        elif volume_ratio >= eff_a1_vol and abs_change >= eff_a1_chg:
            level = "A1"
        elif abs_change >= eff_a0_chg * 1.2:
            # Large move even without full volume confirmation
            level = "A1"
        elif volume_ratio >= eff_a2_vol and abs_change >= eff_a2_chg:
            # Early warning — building momentum, not confirmed yet
            level = "A2"
        elif abs_change >= eff_a1_chg * 1.5:
            # Moderate move, minimal volume — still worth watching
            level = "A2"

        if level is None:
            return None

        # Determine direction
        direction = "LONG" if change_pct > 0 else "SHORT"
        pattern = "realtime_momentum"

        # Check previous price for reversal pattern
        prev_price = self._last_prices.get(symbol)
        if prev_price is not None:
            if prev_price < prev_close and price > prev_close:
                pattern = "realtime_reversal_up"
                direction = "LONG"
            elif prev_price > prev_close and price < prev_close:
                pattern = "realtime_reversal_down"
                direction = "SHORT"

        # ── #4  Falling knife protection ────────────────────────────
        # Block or downgrade LONG signals when intraday momentum is negative
        # (price falling from previous poll → still accelerating down).
        falling_knife_warned = False
        if direction == "LONG" and prev_price is not None:
            if price < prev_price:
                # Price dropped since last poll — momentum is negative
                if level == "A0":
                    level = "A1"  # downgrade — do not fire A0 into a falling knife
                    logger.debug(
                        "Falling-knife downgrade: %s A0→A1 (price %.2f < prev %.2f)",
                        symbol, price, prev_price,
                    )
                else:
                    # A1 with negative momentum — annotate but allow through
                    logger.debug(
                        "Falling-knife warn: %s A1 (price %.2f < prev %.2f)",
                        symbol, price, prev_price,
                    )
                    falling_knife_warned = True

        # Breakout from key levels — require prev_price to avoid
        # false-fires on first poll after startup / watchlist reload.
        pdh = _safe_float(watchlist_entry.get("pdh"), 0.0)
        pdl = _safe_float(watchlist_entry.get("pdl"), 0.0)
        if pdh > 0 and price > pdh and prev_price is not None and prev_price <= pdh:
            pattern = "pdh_breakout"
            direction = "LONG"
            if level == "A1":
                level = "A0"  # PDH breakout upgrades to A0
        if pdl > 0 and price < pdl and prev_price is not None and prev_price >= pdl:
            pattern = "pdl_breakdown"
            direction = "SHORT"
            if level == "A1":
                level = "A0"

        # ── Stale-move velocity gate ───────────────────────────
        # If price hasn't moved in the last N polls, cumulative change
        # from prev_close is misleading — the breakout already happened.
        hist = self._price_history.get(symbol)
        if hist and len(hist) >= VELOCITY_LOOKBACK:
            lookback_price = hist[-VELOCITY_LOOKBACK]
            if lookback_price > 0:
                velocity_pct = abs((price - lookback_price) / lookback_price) * 100
                if velocity_pct < STALE_VELOCITY_PCT:
                    if level == "A0":
                        level = "A1"
                        logger.debug(
                            "Stale velocity: %s A0→A1 (vel=%.3f%% < %.3f%%)",
                            symbol, velocity_pct, STALE_VELOCITY_PCT,
                        )
                    elif level == "A1":
                        level = "A2"
                        logger.debug(
                            "Stale velocity: %s A1→A2 (vel=%.3f%%)",
                            symbol, velocity_pct,
                        )

        # ── #1  Gate hysteresis — prevent A0↔A1 flapping ───────────
        level = self._hysteresis.evaluate(
            symbol, level, volume_ratio, abs_change,
        )

        # ── #7  Dynamic cooldown (oscillation-based) ────────────────
        if level == "A0":
            # Derive regime label for cooldown: map VolumeRegimeDetector states
            _vol_regime = self._volume_regime.regime if hasattr(self._volume_regime, "regime") else "NORMAL"
            _cd_regime = "THIN" if _vol_regime == "HOLIDAY_SUSPECT" else (
                "HIGH" if volume_ratio > A0_VOLUME_RATIO_MIN else "NORMAL"
            )
            _has_news = bool(_safe_float(watchlist_entry.get("news_catalyst_score"), 0.0) > 0.3)

            is_active, remaining = self._dynamic_cooldown.check_cooldown(
                symbol, volume_regime=_cd_regime, has_news_catalyst=_has_news,
            )
            if is_active:
                level = "A1"  # cooldown active — downgrade to A1
                logger.debug(
                    "Dynamic cooldown active for %s (%.0fs remaining, regime=%s)",
                    symbol, remaining, _cd_regime,
                )
            else:
                # Require momentum confirmation for A0
                if prev_price is not None and direction == "LONG" and price <= prev_price:
                    level = "A1"  # momentum not confirming — keep at A1
                elif prev_price is not None and direction == "SHORT" and price >= prev_price:
                    level = "A1"
                else:
                    self._dynamic_cooldown.record_transition(symbol, direction)

        now = datetime.now(UTC)
        now_iso = now.isoformat()
        now_ts = now.timestamp()
        return RealtimeSignal(
            symbol=symbol,
            level=level,
            direction=direction,
            pattern=pattern,
            price=round(price, 2),
            prev_close=round(prev_close, 2),
            change_pct=round(change_pct, 2),
            volume_ratio=round(raw_volume_ratio, 2),  # display raw, not normalized
            score=round(v2_score, 3),
            confidence_tier=confidence_tier,
            atr_pct=round(atr_pct, 2),
            freshness=1.0,  # brand new signal
            fired_at=now_iso,
            fired_epoch=now_ts,
            level_since_at=now_iso,
            level_since_epoch=now_ts,
            details={
                "pdh": pdh,
                "pdl": pdl,
                "volume": volume,
                "avg_volume": avg_volume,
                "falling_knife": falling_knife_warned,
            },
            symbol_regime=symbol_regime,
        )

    # ------------------------------------------------------------------
    # Poll once — main detection loop
    # ------------------------------------------------------------------
    def poll_once(self) -> list[RealtimeSignal]:
        """Run one poll cycle: fetch quotes → detect signals → persist.

        Also polls the FMP newsstack on each cycle and enriches signals
        with ``news_score``, ``news_category``, and ``news_headline``.

        In fast/ultra mode, newsstack is polled asynchronously via
        :class:`AsyncNewsstackPoller` so it never blocks the main loop.

        Incorporates:
          - #6  Signal re-qualification against current data
          - #9  Volume-regime auto-detection (holiday/thin sessions)
          - #11 Dirty-flag skip for unchanged quotes
          - VisiData delta tracking (Δ-price, Δ-volume, tick, streak)
        """
        poll_start = time.monotonic()

        # ── Session-boundary detection: clear stale _last_prices ──
        # When the engine transitions from outside→inside market hours,
        # yesterday's prices would cause false breakout/falling-knife
        # signals on the first poll cycle of the new session.
        in_market = _is_within_market_hours()
        if not in_market:
            self._was_outside_market = True
        elif self._was_outside_market:
            n_cleared = len(self._last_prices)
            self._last_prices.clear()
            self._price_history.clear()
            self._was_outside_market = False
            logger.info("Session boundary — cleared stale _last_prices (%d symbols)", n_cleared)

        if self._client_disabled_reason:
            # Persist empty signals with disabled reason so UIs stay green
            self._active_signals.clear()
            self._save_signals(disabled_reason=self._client_disabled_reason)
            self.last_poll_duration = time.monotonic() - poll_start
            return []

        # ── Newsstack: prefer async poller, fall back to synchronous ──
        news_by_ticker: dict[str, dict[str, Any]] = {}
        if self._async_newsstack is not None:
            # Non-blocking: read latest cached result
            news_by_ticker = self._async_newsstack.latest()
        else:
            # Legacy synchronous path (non-fast mode)
            try:
                # Lazy-cached imports (same pattern as AsyncNewsstackPoller)
                if not hasattr(self, "_ns_poll_fn"):
                    from newsstack_fmp.config import Config as _NSCfg
                    from newsstack_fmp.pipeline import poll_once as _nsp
                    self._ns_poll_fn = _nsp
                    self._ns_cfg_cls = _NSCfg

                ns_candidates = self._ns_poll_fn(self._ns_cfg_cls())
                for nc in ns_candidates:
                    tk = str(nc.get("ticker", "")).strip().upper()
                    if tk:
                        prev = news_by_ticker.get(tk)
                        if prev is None or nc.get("news_score", 0) > prev.get("news_score", 0):
                            news_by_ticker[tk] = nc
            except Exception as exc:
                logger.debug("Newsstack poll skipped: %s", exc)

        new_signals: list[RealtimeSignal] = []

        quotes = self._fetch_realtime_quotes()
        if not quotes:
            logger.debug("No quotes received in poll cycle")
            self._save_signals()
            self.last_poll_duration = time.monotonic() - poll_start
            return new_signals

        self._poll_seq += 1

        # ── #9  Volume-regime detection ──────────────────────────
        self._volume_regime.update(quotes)
        regime_thresholds = self._volume_regime.adjusted_thresholds()

        if self._volume_regime.regime == "HOLIDAY_SUSPECT":
            logger.info(
                "Volume regime HOLIDAY_SUSPECT — all signals suspended (%.0f%% thin)",
                self._volume_regime.thin_fraction * 100,
            )
            self._active_signals.clear()
            self._save_signals()
            return []

        # Build symbol→watchlist entry map
        wl_map = {
            str(r.get("symbol", "")).strip().upper(): r
            for r in self._watchlist if r.get("symbol")
        }

        # ── H5 fix: prune stale VD rows for symbols no longer in quotes ──
        stale_syms = set(self._vd_rows) - set(quotes)
        for s in stale_syms:
            del self._vd_rows[s]

        vd_now_epoch = time.time()
        for sym, quote in quotes.items():
            # ── #11  Dirty flag — skip if quote unchanged ────────
            qh = _quote_hash(quote)
            if self._quote_hashes.get(sym) == qh:
                # Quote identical to last poll — skip signal detection
                continue
            self._quote_hashes[sym] = qh

            # ── Quote delta tracking for VisiData ────────────────
            q_price = _safe_float(quote.get("price") or quote.get("lastPrice"), 0.0)
            q_volume = _safe_float(quote.get("volume"), 0.0)
            delta = self._delta_tracker.update(sym, q_price, q_volume)

            wl_entry = wl_map.get(sym, {})
            signal = self._detect_signal(
                sym, quote, wl_entry, regime_thresholds=regime_thresholds,
            )
            # Newsstack data (used for signal enrichment & VD row)
            ns_data = news_by_ticker.get(sym)

            if signal:
                # Enrich with newsstack data
                if ns_data:
                    signal.news_score = _safe_float(ns_data.get("news_score", 0))
                    signal.news_category = str(ns_data.get("category", ""))
                    signal.news_headline = str(ns_data.get("headline", ""))[:200]
                    signal.news_warn_flags = list(ns_data.get("warn_flags") or [])
                    # Upgrade A1 → A0 if news catalyst is strong AND
                    # the dynamic cooldown is not active for this symbol.
                    if signal.level in ("A1", "A2") and signal.news_score >= 0.80:
                        cd_active, _ = self._dynamic_cooldown.check_cooldown(sym)
                        if not cd_active:
                            signal.level = "A0"
                            signal.details["a0_upgrade_reason"] = "news_catalyst"

                # Check if we already have an active signal for this symbol
                _level_rank = {"A0": 0, "A1": 1, "A2": 2}
                existing = [s for s in self._active_signals if s.symbol == sym and not s.is_expired()]
                if existing:
                    latest = existing[-1]
                    new_rank = _level_rank.get(signal.level, 3)
                    old_rank = _level_rank.get(latest.level, 3)
                    if new_rank < old_rank:
                        # Upgrade: A2→A1, A1→A0, etc.
                        self._active_signals = [s for s in self._active_signals if s.symbol != sym]
                        new_signals.append(signal)
                    elif signal.direction != latest.direction:
                        # Direction change: replace
                        self._active_signals = [s for s in self._active_signals if s.symbol != sym]
                        new_signals.append(signal)
                    # else: same or lower level, same direction — skip
                else:
                    new_signals.append(signal)

            # Track price for next cycle
            price = _safe_float(quote.get("price") or quote.get("lastPrice"), 0.0)
            if price > 0:
                self._last_prices[sym] = price
                # Rolling price history for velocity gate
                if sym not in self._price_history:
                    self._price_history[sym] = deque(maxlen=20)
                self._price_history[sym].append(price)

            # ── VisiData row: compact per-symbol snapshot with deltas ──
            prev_close = _safe_float(quote.get("previousClose"), 0.0)
            chg_pct = ((price / prev_close) - 1) * 100 if prev_close > 0 else 0.0
            _avg_vol = _safe_float(
                quote.get("avgVolume") or wl_entry.get("avg_volume"), 0.0
            )
            vol_ratio = round(q_volume / _avg_vol, 2) if _avg_vol >= 1000 else 0.0
            # Determine signal status for this symbol
            sym_signals = [
                s for s in (*self._active_signals, *new_signals)
                if s.symbol == sym and not s.is_expired()
            ]
            sig_level = ""
            sig_dir = ""
            if sym_signals:
                best = sym_signals[0]
                sig_level = best.level
                sig_dir = best.direction

            signal_since_at = ""
            signal_age_s = 0
            signal_age_hms = ""
            if sym_signals:
                best = sym_signals[0]
                level_since_epoch = best.level_since_epoch or best.fired_epoch
                signal_since_at = best.level_since_at or best.fired_at
                signal_age_s = max(int(vd_now_epoch - level_since_epoch), 0)
                signal_age_hms = _format_age_hms(signal_age_s)

            current_news_score = round(_safe_float(ns_data.get("news_score", 0.0), 0.0), 2) if ns_data else 0.0
            news_polarity = _safe_float(ns_data.get("polarity", 0.0), 0.0) if ns_data else 0.0
            news_sentiment_label = str(ns_data.get("sentiment_label", "")).lower() if ns_data else ""
            if news_sentiment_label in ("bullish", "positive", "pos"):
                news_sentiment = "+"
            elif news_sentiment_label in ("bearish", "negative", "neg"):
                news_sentiment = "-"
            elif news_sentiment_label in ("neutral", "neu", "n"):
                news_sentiment = "n"
            elif news_polarity > 0.05:
                news_sentiment = "+"
            elif news_polarity < -0.05:
                news_sentiment = "-"
            else:
                news_sentiment = "n"
            # High news_score with neutral sentiment → upgrade to directional
            # A score ≥0.5 means the news is material; neutral emoji is misleading.
            if news_sentiment == "n" and current_news_score >= 0.5:
                news_sentiment = "+" if news_polarity >= 0 else "-"
            news_sentiment_emoji = {"+": "🟢", "n": "🟡", "-": "🔴"}.get(news_sentiment, "🟡")
            news_url = str(ns_data.get("news_url") or ns_data.get("url") or "") if ns_data else ""
            news_headline = str(ns_data.get("headline", "")) if ns_data else ""
            news_with_link = news_headline

            # Breakout status for VisiData view
            _breakout = ""
            if sig_level == "A0":
                _breakout = "CURRENT_A0"
            elif sig_level == "A1":
                _breakout = "CURRENT_A1"
            elif sig_level == "A2":
                _breakout = "EARLY_A2"
            else:
                # Near-threshold early warning (coming breakout)
                eff_a2_vol = A2_VOLUME_RATIO_MIN * regime_thresholds["vol_mult"]
                eff_a2_chg = A2_PRICE_CHANGE_PCT_MIN * regime_thresholds["chg_mult"]
                near = (vol_ratio >= 0.8 * eff_a2_vol and abs(chg_pct) >= 0.8 * eff_a2_chg)
                _breakout = "UPCOMING" if near else ""

            prev_row = self._vd_rows.get(sym, {})
            poll_changed = bool(
                delta["d_price"] != 0.0
                or delta["d_volume"] != 0
                or str(prev_row.get("signal", "")) != sig_level
                or str(prev_row.get("direction", "")) != sig_dir
                or float(prev_row.get("news_score", 0.0) or 0.0) != current_news_score
                or str(prev_row.get("news_s", "")) != news_sentiment_emoji
                or str(prev_row.get("news_url", "")) != news_url
            )
            if poll_changed:
                self._vd_last_change_epoch[sym] = vd_now_epoch
            last_change_epoch = self._vd_last_change_epoch.get(sym, vd_now_epoch)
            last_change_age_s = max(int(vd_now_epoch - last_change_epoch), 0)

            self._vd_rows[sym] = {
                "symbol": sym,
                "N": "🆕" if sym.upper() in self._new_entrant_set else "",
                "signal": sig_level,
                "direction": sig_dir,
                "tick": delta["tick"],
                "score": round(_safe_float(wl_entry.get("score"), 0.0), 2),
                "streak": delta["streak"],
                "earnings": "📊" if wl_entry.get("earnings_today") else "",
                "news": news_with_link,
                "news_url": news_url,
                "news_score": current_news_score,
                "news_s": news_sentiment_emoji,
                "signal_age_hms": signal_age_hms,
                "news_polarity": round(news_polarity, 3),
                "signal_since_at": signal_since_at,
                "price": round(price, 2),
                "chg_pct": round(chg_pct, 2),
                "vol_ratio": round(vol_ratio, 2),
                "d_price_pct": delta["d_price_pct"],
                "tier": str(wl_entry.get("confidence_tier", "")),
                "last_change_age_s": last_change_age_s,
                "poll_seq": self._poll_seq,
                "poll_changed": poll_changed,
            }

        # Add new signals to active list
        self._active_signals.extend(new_signals)

        # ── #6  Signal re-qualification ──────────────────────────
        # Re-validate ALL active signals against current quotes.  If a
        # signal no longer meets even A1 criteria → expire it early.
        requalified: list[RealtimeSignal] = []
        for sig in self._active_signals:
            if sig.is_expired():
                continue
            q = quotes.get(sig.symbol)
            if q is None:
                requalified.append(sig)  # no data this cycle — keep
                continue
            cur_price = _safe_float(q.get("price") or q.get("lastPrice"), 0.0)
            cur_prev_close = _safe_float(q.get("previousClose"), 0.0)
            cur_volume = _safe_float(q.get("volume"), 0.0)
            # Use watchlist fallback for avgVolume (FMP batch quote omits it)
            wl_avg = 0.0
            wl_match = [w for w in self._watchlist if w.get("symbol") == sig.symbol]
            if wl_match:
                wl_avg = _safe_float(wl_match[0].get("avg_volume"), 0.0)
            cur_avg_vol = _safe_float(q.get("avgVolume") or wl_avg, 0.0)
            if cur_avg_vol < 1000:
                requalified.append(sig)  # can't verify — keep
                continue
            if cur_price <= 0 or cur_prev_close <= 0:
                requalified.append(sig)
                continue
            cur_change = abs(((cur_price / cur_prev_close) - 1) * 100)
            raw_cur_vol = cur_volume / cur_avg_vol
            cur_vol_ratio = raw_cur_vol / max(_expected_cumulative_volume_fraction(), 0.02)

            # Apply regime-adjusted thresholds for re-qualification too
            eff_a2_vol = A2_VOLUME_RATIO_MIN * regime_thresholds["vol_mult"]
            eff_a2_chg = A2_PRICE_CHANGE_PCT_MIN * regime_thresholds["chg_mult"]
            eff_a1_vol = A1_VOLUME_RATIO_MIN * regime_thresholds["vol_mult"]
            eff_a1_chg = A1_PRICE_CHANGE_PCT_MIN * regime_thresholds["chg_mult"]

            # Drop signal entirely if it no longer meets even A2 criteria
            still_qualifies_a2 = (
                (cur_vol_ratio >= eff_a2_vol and cur_change >= eff_a2_chg)
                or cur_change >= A1_PRICE_CHANGE_PCT_MIN * 1.5 * regime_thresholds["chg_mult"]
            )

            if not still_qualifies_a2:
                logger.debug(
                    "Re-qualification: expiring %s %s (vol_ratio=%.2f, chg=%.2f%%)",
                    sig.symbol, sig.level, cur_vol_ratio, cur_change,
                )
                continue  # drop the signal

            # ── Momentum-aware time-based level capping ──────────
            # A stale A0 that still meets thresholds is NOT actionable.
            # Cap the maximum level based on signal age, and accelerate
            # decay when price velocity is flat.
            sig_age = time.time() - sig.fired_epoch

            # Check if momentum is stale (flat price over recent polls)
            phist = self._price_history.get(sig.symbol)
            momentum_stale = False
            if phist and len(phist) >= 3 and cur_price > 0:
                lookback_p = phist[-min(3, len(phist))]
                if lookback_p > 0:
                    vel = abs((cur_price - lookback_p) / lookback_p) * 100
                    momentum_stale = vel < STALE_VELOCITY_PCT

            # Stale momentum → halve the allowed time at each level
            eff_a0_max = A0_MAX_AGE_SECONDS // 2 if momentum_stale else A0_MAX_AGE_SECONDS
            eff_a1_max = A1_MAX_AGE_SECONDS // 2 if momentum_stale else A1_MAX_AGE_SECONDS

            if sig.level == "A0" and sig_age > eff_a0_max:
                sig.level = "A1"
                now_iso = datetime.now(UTC).isoformat()
                sig.level_since_at = now_iso
                sig.level_since_epoch = time.time()
                logger.debug(
                    "Time-decay: %s A0→A1 (age %.0fs > %ds, stale=%s)",
                    sig.symbol, sig_age, eff_a0_max, momentum_stale,
                )
            if sig.level == "A1" and sig_age > eff_a1_max:
                sig.level = "A2"
                now_iso = datetime.now(UTC).isoformat()
                sig.level_since_at = now_iso
                sig.level_since_epoch = time.time()
                logger.debug(
                    "Time-decay: %s A1→A2 (age %.0fs > %ds, stale=%s)",
                    sig.symbol, sig_age, eff_a1_max, momentum_stale,
                )

            # Downgrade A0→A1 if no longer meets A0 thresholds
            eff_a0_vol = A0_VOLUME_RATIO_MIN * regime_thresholds["vol_mult"]
            eff_a0_chg = A0_PRICE_CHANGE_PCT_MIN * regime_thresholds["chg_mult"]
            if sig.level == "A0" and not (cur_vol_ratio >= eff_a0_vol and cur_change >= eff_a0_chg):
                sig.level = "A1"
                now_iso = datetime.now(UTC).isoformat()
                sig.level_since_at = now_iso
                sig.level_since_epoch = time.time()
                logger.debug("Re-qualification: downgrade %s A0→A1", sig.symbol)

            # Downgrade A1→A2 if no longer meets A1 thresholds
            if sig.level == "A1" and not (
                (cur_vol_ratio >= eff_a1_vol and cur_change >= eff_a1_chg)
                or cur_change >= A0_PRICE_CHANGE_PCT_MIN * 1.2 * regime_thresholds["chg_mult"]
            ):
                sig.level = "A2"
                now_iso = datetime.now(UTC).isoformat()
                sig.level_since_at = now_iso
                sig.level_since_epoch = time.time()
                logger.debug("Re-qualification: downgrade %s A1→A2", sig.symbol)

            requalified.append(sig)

        self._active_signals = requalified

        # Decay existing signals
        now_epoch = time.time()
        for sig in self._active_signals:
            elapsed = now_epoch - sig.fired_epoch
            sig.freshness = adaptive_freshness_decay(
                elapsed, atr_pct=sig.atr_pct if sig.atr_pct > 0 else None,
            )

        # Prune expired signals
        self._active_signals = [s for s in self._active_signals if not s.is_expired()]

        # Sort: A0 before A1 before A2, then by freshness
        _level_order = {"A0": 0, "A1": 1, "A2": 2}
        self._active_signals.sort(
            key=lambda s: (_level_order.get(s.level, 3), -s.freshness),
        )

        # ── Telemetry recording ─────────────────────────────────
        # Aggregate per-poll stats for the telemetry snapshot
        if new_signals:
            avg_vol_r = sum(s.volume_ratio for s in new_signals) / len(new_signals)
            avg_chg = sum(abs(s.change_pct) for s in new_signals) / len(new_signals)
            avg_score_diff = sum(s.score for s in new_signals) / len(new_signals)
        else:
            avg_vol_r = 0.0
            avg_chg = 0.0
            avg_score_diff = 0.0
        self.telemetry.record(
            new_signals,
            score_diff=avg_score_diff,
            volume_ratio=avg_vol_r,
            change_pct=avg_chg,
        )

        # Persist
        self._save_signals()

        # Track poll duration for adaptive sleep
        self.last_poll_duration = time.monotonic() - poll_start

        if new_signals:
            logger.info(
                "New signals: %s",
                [(s.symbol, s.level, s.direction, s.pattern) for s in new_signals],
            )

        return new_signals

    # ------------------------------------------------------------------
    # Signal access
    # ------------------------------------------------------------------
    def get_active_signals(self) -> list[RealtimeSignal]:
        """Return active (non-expired) signals, sorted by priority."""
        now_epoch = time.time()
        # Update freshness before returning
        for sig in self._active_signals:
            elapsed = now_epoch - sig.fired_epoch
            sig.freshness = adaptive_freshness_decay(
                elapsed, atr_pct=sig.atr_pct if sig.atr_pct > 0 else None,
            )
        self._active_signals = [s for s in self._active_signals if not s.is_expired()]
        return list(self._active_signals)

    def get_a0_signals(self) -> list[RealtimeSignal]:
        """Return only A0 (immediate action) signals."""
        return [s for s in self.get_active_signals() if s.level == "A0"]

    def get_a1_signals(self) -> list[RealtimeSignal]:
        """Return only A1 (watch closely) signals."""
        return [s for s in self.get_active_signals() if s.level == "A1"]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _save_vd_snapshot(self) -> None:
        """Write compact VisiData JSONL — one line per symbol, no fsync.

        Optimised for high-frequency polling: minimal I/O overhead so
        VisiData can ``--reload`` every few seconds without stale data.
        """
        if not self._vd_rows:
            return

        # Compute snapshot-level freshness meta row
        _now = time.time()
        _a0_count = sum(1 for r in self._vd_rows.values() if r.get("signal") == "A0")
        _a1_count = sum(1 for r in self._vd_rows.values() if r.get("signal") == "A1")
        _max_change_age = max(
            (r.get("last_change_age_s", 0) for r in self._vd_rows.values()), default=0,
        )
        _stale_warn = "⚠️ STALE" if _max_change_age > 300 else ""
        _meta_row: dict[str, Any] = {
            "symbol": f"_META {_stale_warn}".strip(),
            "signal": f"A0={_a0_count} A1={_a1_count}",
            "direction": "",
            "tick": "",
            "score": 0,
            "streak": 0,
            "price": 0,
            "chg_pct": 0,
            "vol_ratio": 0,
            "news": f"poll#{self._poll_seq} · {len(self._vd_rows)} syms",
            "news_score": 0,
            "signal_age_hms": "",
            "last_change_age_s": int(_max_change_age),
            "poll_seq": self._poll_seq,
            "poll_changed": True,
        }

        try:
            VD_SIGNALS_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=VD_SIGNALS_PATH.parent, suffix=".tmp", prefix="vd_",
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                    # Meta row first — immediately visible in VisiData
                    fh.write(json.dumps(_meta_row, default=str, allow_nan=False))
                    fh.write("\n")
                    for row in self._vd_rows.values():
                        fh.write(json.dumps(row, default=str, allow_nan=False))
                        fh.write("\n")
                    # NO fsync — speed over durability for VisiData snapshots
                os.replace(tmp_path, VD_SIGNALS_PATH)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as exc:
            logger.debug("VisiData snapshot write failed: %s", exc)

    def _save_signals(self, *, disabled_reason: str | None = None) -> None:
        """Write active signals to JSON for dashboard consumption."""
        # VisiData compact JSONL snapshot (fast, no fsync)
        self._save_vd_snapshot()

        payload = {
            "updated_at": datetime.now(UTC).isoformat(),
            "updated_epoch": time.time(),
            "poll_interval": self.poll_interval,
            "poll_duration": round(self.last_poll_duration, 3),
            "watched_symbols": [str(r.get("symbol", "")) for r in self._watchlist],
            "signals": [s.to_dict() for s in self._active_signals],
            "signal_count": len(self._active_signals),
            "a0_count": sum(1 for s in self._active_signals if s.level == "A0"),
            "a1_count": sum(1 for s in self._active_signals if s.level == "A1"),
            "disabled_reason": disabled_reason,
        }
        try:
            SIGNALS_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=SIGNALS_PATH.parent, suffix=".tmp", prefix="signals_",
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, indent=2, default=str, allow_nan=False)
                    fh.write("\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_path, SIGNALS_PATH)
            except BaseException:
                # Clean up temp file on any failure (including KeyboardInterrupt)
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as exc:
            logger.warning("Failed to save signals: %s", exc)

    @staticmethod
    def load_signals_from_disk(max_age_s: float = 300.0) -> dict[str, Any]:
        """Load latest signals from JSON (for Streamlit/VisiData).

        Parameters
        ----------
        max_age_s : float
            Maximum acceptable file age in seconds (default 5 min).
            If the file is older, a ``stale`` flag is set in the
            returned dict so callers can surface a warning.
        """
        _empty: dict[str, Any] = {"signals": [], "signal_count": 0, "a0_count": 0, "a1_count": 0}
        if not SIGNALS_PATH.exists():
            return _empty
        try:
            file_age_s = time.time() - SIGNALS_PATH.stat().st_mtime
            with open(SIGNALS_PATH, "r", encoding="utf-8") as fh:
                data: dict[str, Any] = json.load(fh)
            if file_age_s > max_age_s:
                data["stale"] = True
                data["stale_age_s"] = round(file_age_s)
            return data
        except Exception:
            return _empty


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the realtime signal engine as a standalone polling loop."""
    import argparse

    # Auto-load .env so FMP_API_KEY is available without manual shell sourcing
    env_path = Path(__file__).resolve().parents[1] / ".env"
    try:
        from dotenv import load_dotenv

        if env_path.is_file():
            load_dotenv(env_path, override=False)
    except ImportError:
        # python-dotenv not installed — minimal stdlib fallback
        if env_path.is_file():
            with open(env_path) as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key, val = key.strip(), val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val

    parser = argparse.ArgumentParser(description="Realtime signal engine")
    parser.add_argument("--interval", type=int, default=DEFAULT_POLL_INTERVAL, help="Poll interval in seconds")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="Number of symbols to monitor")
    parser.add_argument("--reload-interval", type=int, default=300, help="Seconds between watchlist reloads")
    parser.add_argument(
        "--fast", action="store_true",
        help="Enable fast/VisiData mode: 5s min poll interval, 30s base cooldown",
    )
    parser.add_argument(
        "--ultra", action="store_true",
        help="Ultra-fast 2s polling for VisiData near-realtime breakout monitoring",
    )
    parser.add_argument(
        "--telemetry-port", type=int, default=8099,
        help="Port for the telemetry HTTP endpoint (0 to disable)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    )

    engine = RealtimeEngine(
        poll_interval=args.interval,
        top_n=args.top_n,
        fast_mode=args.fast or args.ultra,
        ultra_mode=args.ultra,
    )

    # Start telemetry HTTP server (daemon thread — auto-stops on exit)
    if args.telemetry_port > 0:
        _start_telemetry_server(engine.telemetry, port=args.telemetry_port)

    # Start async newsstack for fast/ultra modes (reduces per-poll latency)
    if args.fast or args.ultra:
        ns_interval = 30 if args.ultra else 60
        engine.start_async_newsstack(poll_interval=ns_interval)
        logger.info("Async newsstack started (interval=%ds)", ns_interval)

    mode_label = "ULTRA" if args.ultra else ("FAST/VisiData" if args.fast else "standard")
    logger.info(
        "Starting realtime signal engine (interval=%ds, top_n=%d, mode=%s, vd=%s)",
        engine.poll_interval, args.top_n, mode_label, VD_SIGNALS_PATH,
    )

    last_reload = time.monotonic()
    while True:
        try:
            cycle_start = time.monotonic()

            # Periodically reload watchlist from latest pipeline run
            if cycle_start - last_reload > args.reload_interval:
                engine.reload_watchlist()
                last_reload = time.monotonic()

            engine.poll_once()

            active = engine.get_active_signals()
            a0 = [s for s in active if s.level == "A0"]
            a1 = [s for s in active if s.level == "A1"]
            logger.info(
                "Poll complete — %d active signals (%d A0, %d A1), took %.1fs",
                len(active), len(a0), len(a1), engine.last_poll_duration,
            )

            if a0:
                for s in a0:
                    logger.info(
                        "🔴 A0 %s %s %s @ $%.2f (vol×%.1f, Δ%+.1f%%, fresh=%.0f%%)",
                        s.symbol, s.direction, s.pattern, s.price,
                        s.volume_ratio, s.change_pct, s.freshness * 100,
                    )

            # Adaptive sleep: subtract poll duration from interval
            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0.5, engine.poll_interval - elapsed)
            time.sleep(sleep_time)

        except KeyboardInterrupt:
            logger.info("Realtime engine stopped by user")
            # Stop async newsstack thread gracefully
            if engine._async_newsstack is not None:
                engine._async_newsstack.stop()
            break
        except Exception as exc:
            logger.error("Poll error: %s", exc, exc_info=True)
            time.sleep(max(10, engine.poll_interval))


if __name__ == "__main__":
    main()
