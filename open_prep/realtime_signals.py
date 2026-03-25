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
    engine = RealtimeEngine(poll_interval=45)
    engine.poll_once()  # single iteration
    signals = engine.get_active_signals()
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import sys
import tempfile
import threading
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
DEFAULT_TOP_N = 0  # 0 = monitor ALL symbols from pipeline (900+)

# FMP batch-quote chunking: max symbols per request to avoid URL length limits
_BATCH_QUOTE_CHUNK_SIZE = 500

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

# PID file for the background engine process
_RT_ENGINE_PID_FILE = _ARTIFACTS_LATEST / "realtime_engine.pid"
_RT_ENGINE_LOCK_FILE = _ARTIFACTS_LATEST / "realtime_engine.lock"
_RT_ENGINE_LOG_FILE = _ARTIFACTS_LATEST / "realtime_signals.log"
_RT_ENGINE_STATUS_FILE = _ARTIFACTS_LATEST / "realtime_engine_status.json"
_RT_ENGINE_TELEMETRY_FILE = _ARTIFACTS_LATEST / "realtime_telemetry.json"


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception:
        logger.debug("Failed to read JSON file: %s", path, exc_info=True)
        return None


def _update_rt_engine_status(*, running: bool, pid: int | None, error: str | None = None) -> None:
    _write_json_atomically(
        _RT_ENGINE_STATUS_FILE,
        {
            "running": bool(running),
            "pid": int(pid) if pid is not None else None,
            "error": str(error) if error else "",
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "log_path": str(_RT_ENGINE_LOG_FILE),
        },
    )


def _update_telemetry_status(
    *,
    enabled: bool,
    requested_port: int,
    active_port: int | None,
    error: str | None = None,
) -> None:
    _write_json_atomically(
        _RT_ENGINE_TELEMETRY_FILE,
        {
            "enabled": bool(enabled),
            "requested_port": int(requested_port),
            "active_port": int(active_port) if active_port is not None else None,
            "url": f"http://127.0.0.1:{active_port}" if active_port is not None else "",
            "error": str(error) if error else "",
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    )


def _detect_rt_engine_pid() -> int | None:
    import subprocess

    if _RT_ENGINE_PID_FILE.exists():
        try:
            pid = int(_RT_ENGINE_PID_FILE.read_text().strip())
            os.kill(pid, 0)
            return pid
        except (ValueError, OSError):
            try:
                _RT_ENGINE_PID_FILE.unlink(missing_ok=True)
            except OSError:
                pass

    try:
        result = subprocess.run(
            ["pgrep", "-f", "python.*-m open_prep.realtime_signals"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    for raw_pid in result.stdout.splitlines():
        try:
            pid = int(raw_pid.strip())
        except ValueError:
            continue
        try:
            os.kill(pid, 0)
        except OSError:
            continue
        try:
            _RT_ENGINE_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
            _RT_ENGINE_PID_FILE.write_text(str(pid))
        except OSError:
            pass
        return pid
    return None


def get_rt_engine_status() -> dict[str, Any]:
    payload = _read_json_file(_RT_ENGINE_STATUS_FILE) or {}
    if "running" not in payload:
        pid = _detect_rt_engine_pid()
        payload = {
            "running": pid is not None,
            "pid": pid,
            "error": "",
            "log_path": str(_RT_ENGINE_LOG_FILE),
        }
    return payload


def get_rt_engine_telemetry_status() -> dict[str, Any]:
    return _read_json_file(_RT_ENGINE_TELEMETRY_FILE) or {}


def ensure_rt_engine_running(
    *,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    project_root: Path | str | None = None,
) -> bool:
    """Ensure the realtime signal engine is running as a background process.

    Call this from Streamlit apps, VisiData launchers, or any other entry
    point that needs RT signal data.  If the engine is already running
    (detected via PID file + process check) this is a no-op.

    Returns ``True`` if the engine was started (or is already running),
    ``False`` on failure.
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parents[1]
    project_root = Path(project_root)

    pid = _detect_rt_engine_pid()
    if pid is not None:
        _update_rt_engine_status(running=True, pid=pid, error=None)
        return True

    # Use a file lock to prevent TOCTOU race between concurrent callers
    _RT_ENGINE_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(_RT_ENGINE_LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # Another process holds the lock — wait briefly and verify that a
        # running engine actually becomes visible before claiming success.
        lock_fd.close()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            pid = _detect_rt_engine_pid()
            if pid is not None:
                _update_rt_engine_status(running=True, pid=pid, error=None)
                return True
            time.sleep(0.2)
        _update_rt_engine_status(
            running=False,
            pid=None,
            error="RT engine startup lock held, but no running process became visible.",
        )
        logger.warning("RT engine lock held but no running process became visible within the wait window")
        return False

    try:
        return _ensure_rt_engine_running_locked(
            poll_interval=poll_interval,
            project_root=project_root,
        )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def _ensure_rt_engine_running_locked(
    *,
    poll_interval: int,
    project_root: Path,
) -> bool:
    """Inner helper — called while holding the engine lock file."""
    import subprocess

    pid = _detect_rt_engine_pid()
    if pid is not None:
        logger.debug("RT engine already running (PID %d)", pid)
        _update_rt_engine_status(running=True, pid=pid, error=None)
        return True

    # Not running — start it
    logger.info("Starting RT engine as background process (interval=%ds)…", poll_interval)
    try:
        _RT_ENGINE_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RT_ENGINE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["PYTHONPATH"] = str(project_root)

        # Load .env for API keys
        env_file = project_root / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                if "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip("'\"")
                if k and k not in env:
                    env[k] = v

        log_fh = open(_RT_ENGINE_LOG_FILE, "a", encoding="utf-8")
        try:
            proc = subprocess.Popen(
                [
                    sys.executable, "-m", "open_prep.realtime_signals",
                    "--interval", str(poll_interval),
                ],
                cwd=str(project_root),
                env=env,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # detach from parent — survives parent exit
            )
        finally:
            log_fh.close()  # parent doesn't need the fd — child inherited it
        time.sleep(0.5)
        if proc.poll() is not None:
            _RT_ENGINE_PID_FILE.unlink(missing_ok=True)
            _update_rt_engine_status(
                running=False,
                pid=None,
                error=f"RT engine exited immediately with code {proc.returncode}.",
            )
            logger.warning("RT engine exited immediately after launch (code=%s)", proc.returncode)
            return False
        _RT_ENGINE_PID_FILE.write_text(str(proc.pid))
        _update_rt_engine_status(running=True, pid=proc.pid, error=None)
        logger.info("RT engine started (PID %d, log: %s)", proc.pid, _RT_ENGINE_LOG_FILE)
        return True
    except Exception as exc:
        _update_rt_engine_status(running=False, pid=None, error=f"Failed to start RT engine: {type(exc).__name__}")
        logger.warning("Failed to start RT engine: %s", exc, exc_info=True)
        return False


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
            logger.debug("tz fallback in _expected_volume_fraction — no adjustment", exc_info=True)
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
            # Last resort: UTC − 5 (EST) is more conservative than UTC − 4 (EDT).
            # During EDT (Mar–Nov) the gate opens at 05:00 ET / closes at 21:00 ET
            # (1 h late), which is safe.  During EST (Nov–Mar) it is exact.
            logger.debug("zoneinfo + dateutil unavailable, using UTC-5 fallback", exc_info=True)
            from datetime import timedelta
            now_et = datetime.now(UTC) - timedelta(hours=5)

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
        _update_telemetry_status(enabled=True, requested_port=port, active_port=int(server.server_port), error=None)
        logger.info("Telemetry HTTP server listening on http://127.0.0.1:%d", port)
        return server
    except OSError as exc:
        logger.warning("Could not start telemetry server on port %d: %s", port, type(exc).__name__, exc_info=True)
        try:
            fallback_server = HTTPServer(("127.0.0.1", 0), _Handler)
            t = threading.Thread(target=fallback_server.serve_forever, daemon=True)
            t.start()
            fallback_port = int(fallback_server.server_port)
            error = f"Requested port {port} unavailable ({type(exc).__name__}); using fallback port {fallback_port}."
            _update_telemetry_status(
                enabled=True,
                requested_port=port,
                active_port=fallback_port,
                error=error,
            )
            logger.warning("Telemetry server fell back to port %d after port %d failed", fallback_port, port)
            return fallback_server
        except OSError as fallback_exc:
            error = (
                f"Requested port {port} unavailable ({type(exc).__name__}); "
                f"fallback bind failed ({type(fallback_exc).__name__})."
            )
            _update_telemetry_status(enabled=False, requested_port=port, active_port=None, error=error)
            logger.warning("Could not start telemetry server fallback after port %d failed", port, exc_info=True)
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

        # Prune stale symbols to prevent unbounded dict growth
        stale_cutoff = now - self.max_seconds * 5
        stale_syms = [s for s, ts in self._last_a0.items() if ts < stale_cutoff]
        for s in stale_syms:
            self._last_a0.pop(s, None)
            self._transitions.pop(s, None)

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

    def is_cooling(self, symbol: str) -> bool:
        """Return True if *symbol* is still in cooldown (convenience wrapper)."""
        active, _ = self.check_cooldown(symbol)
        return active


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
        self._wl_avg_volumes: dict[str, float] = {}
        self._last_missing_avg_warn_ts: float = 0.0

    def update(self, quotes: dict[str, dict[str, Any]]) -> str:
        if not quotes:
            self.regime = "NORMAL"
            self.thin_fraction = 0.0
            return self.regime

        thin_count = 0
        total = 0
        for _sym, q in quotes.items():
            vol = _safe_float(q.get("volume"), 0.0)
            # FMP batch-quote omits avgVolume — try watchlist_avg_volumes
            # fallback dict (populated from bulk profile enrichment).
            avg_vol = _safe_float(q.get("avgVolume"), 0.0)
            if avg_vol <= 0 and hasattr(self, "_wl_avg_volumes"):
                avg_vol = self._wl_avg_volumes.get(_sym, 0.0)
            if avg_vol <= 0:
                continue   # unknown volume — exclude from both counts
            total += 1
            if vol < avg_vol * THIN_VOLUME_RATIO:
                thin_count += 1

        self.thin_fraction = (thin_count / total) if total > 0 else 0.0
        if total == 0 and quotes:
            now = time.monotonic()
            if (now - self._last_missing_avg_warn_ts) >= 300.0:
                logger.warning(
                    "Volume regime fallback: avgVolume unavailable for %d/%d symbols; treating regime as NORMAL",
                    len(quotes),
                    len(quotes),
                )
                self._last_missing_avg_warn_ts = now

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
            return {"vol_mult": 0.80, "chg_mult": 0.80}  # relax by 20% (lower thresholds)
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


# ═══════════════════════════════════════════════════════════════════════════
# Technical Indicator Scoring Layer
# ═══════════════════════════════════════════════════════════════════════════

class TechnicalScorer:
    """Cached technical indicator scoring layer.

    Wraps ``fetch_technicals()`` (TradingView primary, FMP stable fallback)
    with per-symbol caching and rate-limit awareness.  Computes a weighted
    ``technical_score`` (0.0–1.0) from RSI, MACD, EMA/SMA alignment, and ADX.

    Weight allocation (inspired by IB_monitoring EWMA engine):

        RSI oversold/overbought :  40%
        MA alignment            :  25%
        MACD cross              :  15%
        ADX trend strength      :  10%
        Summary signal          :  10%

    The scorer degrades gracefully: if indicators are unavailable (rate
    limit, missing data), a neutral 0.5 score is returned so existing
    price+volume logic is unaffected.
    """

    _CACHE_TTL = 90.0         # seconds — balance freshness vs rate limits
    _MIN_CALL_SPACING = 13.0  # seconds — TV enforces ~12s spacing; 13s avoids 429
    _CACHE_MAX = 200          # max entries before eviction

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._last_call_ts: float = 0.0
        self._fetch_fn: Any = None  # lazy import

    def _get_fetch_fn(self) -> Any:
        if self._fetch_fn is None:
            try:
                import sys
                parent = str(Path(__file__).resolve().parents[1])
                if parent not in sys.path:
                    sys.path.insert(0, parent)
                from terminal_technicals import fetch_technicals
                self._fetch_fn = fetch_technicals
                logger.info("TechnicalScorer: loaded fetch_technicals OK")
            except ImportError as exc:
                logger.warning("TechnicalScorer: fetch_technicals unavailable: %s", exc)
                self._fetch_fn = _noop_fetch
        return self._fetch_fn

    def get_technical_data(self, symbol: str, interval: str = "1D") -> dict[str, Any]:
        """Get cached technical data for *symbol*.

        Returns a dict with keys: ``rsi``, ``macd_signal``, ``adx``,
        ``williams``, ``summary_signal``, ``summary_buy``, ``summary_sell``,
        ``summary_neutral``, ``ma_buy``, ``ma_sell``, ``technical_score``,
        ``technical_signal``, ``osc_detail``, ``ma_detail``, ``error``.
        """
        now = time.time()
        key = f"{symbol}:{interval}"
        cached_data: dict[str, Any] | None = None

        # Fast path — return cached if fresh
        with self._lock:
            cached = self._cache.get(key)
            if cached:
                cached_data = cached[1]
            if cached and (now - cached[0]) < self._CACHE_TTL:
                return cached[1]

        # Rate limit guard
        with self._lock:
            if (now - self._last_call_ts) < self._MIN_CALL_SPACING:
                if cached_data is not None:
                    return cached_data
                return self._empty_result(symbol, error="rate limited and no cached technicals")
            self._last_call_ts = now

        # Fetch
        fetch = self._get_fetch_fn()
        try:
            result = fetch(symbol, interval)
            if result is None:
                data = self._empty_result(symbol, error="fetch returned None")
            elif hasattr(result, "error") and result.error:
                data = self._empty_result(symbol, error=result.error)
            else:
                data = self._extract_and_score(result)
        except Exception as exc:
            logger.debug("TechnicalScorer fetch error for %s: %s", symbol, exc)
            data = self._empty_result(symbol, error=str(exc))

        with self._lock:
            self._cache[key] = (now, data)
            if len(self._cache) > self._CACHE_MAX:
                cutoff = now - self._CACHE_TTL * 3
                self._cache = {k: v for k, v in self._cache.items() if v[0] > cutoff}
                # If TTL-based eviction didn't shrink enough, drop oldest entries
                if len(self._cache) > self._CACHE_MAX:
                    sorted_items = sorted(self._cache.items(), key=lambda x: x[1][0])
                    keep = sorted_items[len(sorted_items) - self._CACHE_MAX:]
                    self._cache = dict(keep)

        return data

    def clear(self) -> None:
        """Clear the cache (e.g. on watchlist reload)."""
        with self._lock:
            self._cache.clear()

    # ── Indicator extraction & scoring ──────────────────────────

    def _extract_and_score(self, result: Any) -> dict[str, Any]:
        """Extract individual indicators from a TechnicalResult and score."""
        rsi: float | None = None
        macd_signal: str | None = None
        adx: float | None = None
        williams: float | None = None

        for osc in (result.osc_detail or []):
            name = str(osc.get("name", "")).upper()
            val = osc.get("value")
            if val is None:
                continue
            if name.startswith("RSI") and "14" in name:
                rsi = float(val)
            elif "MACD" in name and "STOCHASTIC" not in name:
                macd_signal = str(osc.get("action", "NEUTRAL")).upper()
            elif name.startswith("ADX"):
                adx = float(val)
            elif "WILLIAMS" in name or name.startswith("WILL"):
                williams = float(val)

        # MA vote counts
        ma_buy = int(result.ma_buy or 0)
        ma_sell = int(result.ma_sell or 0)
        ma_neutral = int(result.ma_neutral or 0)
        ma_total = ma_buy + ma_sell + ma_neutral

        # ── Weighted score (0.0 – 1.0) ──────────────────────────
        score = 0.5  # neutral baseline

        # 1) RSI component — 40 % weight
        if rsi is not None:
            if rsi < 20:
                rsi_score = 0.95
            elif rsi < 30:
                rsi_score = 0.85
            elif rsi < 40:
                rsi_score = 0.65
            elif rsi > 80:
                rsi_score = 0.05
            elif rsi > 70:
                rsi_score = 0.15
            elif rsi > 60:
                rsi_score = 0.35
            else:
                rsi_score = 0.5
            score += (rsi_score - 0.5) * 0.40

        # 2) MA alignment — 25 % weight
        if ma_total > 0:
            ma_score = ma_buy / ma_total  # 0.0 (all sell) → 1.0 (all buy)
            score += (ma_score - 0.5) * 0.25

        # 3) MACD cross — 15 % weight
        if macd_signal and macd_signal not in ("NEUTRAL", ""):
            macd_val = 0.80 if macd_signal == "BUY" else 0.20
            score += (macd_val - 0.5) * 0.15

        # 4) ADX trend strength — 10 % weight (direction-neutral: higher = stronger trend)
        #    ADX itself doesn't indicate direction; it measures trend strength.
        #    We add its value only as a magnitude modifier (0 = no trend → 50+ = strong).
        if adx is not None:
            adx_norm = min(adx / 50.0, 1.0)
            # Keep ADX direction-neutral: scale its contribution by the
            # existing directional bias so it amplifies, not creates, bias.
            directional_bias = score - 0.5  # current bias before ADX
            if abs(directional_bias) < 0.01:
                pass  # No existing bias → ADX contributes nothing
            else:
                # Amplify existing directional bias by ADX strength
                score += directional_bias * adx_norm * 0.20  # 10% effective weight at adx_norm=0.5

        # 5) Summary signal — 10 % weight
        ss = (result.summary_signal or "").upper()
        ss_map = {"STRONG_BUY": 0.9, "BUY": 0.7, "NEUTRAL": 0.5, "SELL": 0.3, "STRONG_SELL": 0.1}
        ss_val = ss_map.get(ss, 0.5)
        score += (ss_val - 0.5) * 0.10

        score = max(0.0, min(1.0, score))

        # Derive human-readable signal from score
        if score >= 0.75:
            tech_signal = "STRONG_BUY"
        elif score >= 0.60:
            tech_signal = "BUY"
        elif score <= 0.25:
            tech_signal = "STRONG_SELL"
        elif score <= 0.40:
            tech_signal = "SELL"
        else:
            tech_signal = "NEUTRAL"

        return {
            "rsi": round(rsi, 2) if rsi is not None else None,
            "macd_signal": macd_signal,
            "adx": round(adx, 2) if adx is not None else None,
            "williams": round(williams, 2) if williams is not None else None,
            "summary_signal": result.summary_signal or "",
            "summary_buy": int(result.summary_buy or 0),
            "summary_sell": int(result.summary_sell or 0),
            "summary_neutral": int(result.summary_neutral or 0),
            "ma_buy": ma_buy,
            "ma_sell": ma_sell,
            "technical_score": round(score, 3),
            "technical_signal": tech_signal,
            "osc_detail": result.osc_detail or [],
            "ma_detail": result.ma_detail or [],
            "error": "",
        }

    @staticmethod
    def _empty_result(symbol: str, error: str = "") -> dict[str, Any]:
        return {
            "rsi": None, "macd_signal": None, "adx": None, "williams": None,
            "summary_signal": "", "summary_buy": 0, "summary_sell": 0,
            "summary_neutral": 0, "ma_buy": 0, "ma_sell": 0,
            "technical_score": 0.5, "technical_signal": "NEUTRAL",
            "osc_detail": [], "ma_detail": [],
            "error": error,
        }


def _noop_fetch(symbol: str, interval: str = "1D") -> None:
    """Stub when terminal_technicals is not importable."""
    return None


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
    # ── Technical indicator enrichment (TradingView / FMP) ──
    technical_score: float = 0.5      # 0.0–1.0 weighted indicator score
    technical_signal: str = "NEUTRAL" # STRONG_BUY / BUY / NEUTRAL / SELL / STRONG_SELL
    rsi: float | None = None          # RSI-14 value (None if unavailable)
    macd_signal: str = ""             # MACD action: BUY / SELL / NEUTRAL

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
        self.top_n = top_n  # 0 = all symbols (default)
        self.fast_mode = fast_mode
        self.ultra_mode = ultra_mode
        self._client = fmp_client
        self._client_disabled_reason: str | None = None
        self._active_signals: list[RealtimeSignal] = []
        self._watchlist: list[dict[str, Any]] = []  # all scored symbols from pipeline
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

        # #12 Technical indicator scorer (TradingView + FMP)
        self._technical_scorer = TechnicalScorer()

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
                    technical_score=_safe_float(raw.get("technical_score", 0.5), 0.5),
                    technical_signal=str(raw.get("technical_signal", "NEUTRAL")),
                    rsi=_safe_float(raw.get("rsi"), None) if raw.get("rsi") is not None else None,
                    macd_signal=str(raw.get("macd_signal", "")),
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
                self._client_disabled_reason = type(exc).__name__
                raise
        return self._client

    # ------------------------------------------------------------------
    # Load ALL symbols from latest open_prep run
    # ------------------------------------------------------------------
    def _load_watchlist(self) -> None:
        """Load all scored candidates from the latest pipeline result.

        Merges ``ranked_v2`` (top scored) with overflow entries from
        ``filtered_out_v2`` (scored but below display cutoff) to build
        the full monitoring universe (typically 900+ symbols).

        If ``self.top_n > 0`` the list is sliced for backward compat;
        the default (0) means *all* symbols are monitored.
        """
        run_path = LATEST_RUN_PATH if LATEST_RUN_PATH.exists() else _LEGACY_RUN_PATH
        if not run_path.exists():
            logger.warning("No latest_open_prep_run.json found — watchlist empty")
            return
        try:
            with open(run_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)

            # -- Build full universe: ranked + overflow -------------------
            ranked_v2 = data.get("ranked_v2") or []
            seen: set[str] = set()
            full: list[dict[str, Any]] = []
            for r in ranked_v2:
                sym = str(r.get("symbol", "")).strip().upper()
                if sym and sym not in seen:
                    seen.add(sym)
                    full.append(r)

            # Recover scored-but-below-cutoff entries from filtered_out_v2
            for r in (data.get("filtered_out_v2") or []):
                reasons = r.get("filter_reasons") or []
                if "below_top_n_cutoff" not in reasons:
                    continue  # truly filtered out — skip
                sym = str(r.get("symbol", "")).strip().upper()
                if sym and sym not in seen:
                    seen.add(sym)
                    full.append(r)

            # Also include any symbols from enriched_quotes not yet covered
            for q in (data.get("enriched_quotes") or []):
                sym = str(q.get("symbol", "")).strip().upper()
                if sym and sym not in seen:
                    seen.add(sym)
                    # Build a minimal watchlist entry from the quote
                    full.append({
                        "symbol": sym,
                        "avg_volume": _safe_float(
                            q.get("avgVolume") or q.get("volAvg"), 0.0
                        ),
                        "price": _safe_float(q.get("price"), 0.0),
                    })

            # Optional backward-compat slice (top_n > 0)
            if self.top_n > 0:
                full = full[:self.top_n]

            self._watchlist = full

            # Load new-entrant symbols from diff (for 🆕 column)
            diff = data.get("diff") or {}
            self._new_entrant_set = {
                s.upper() for s in (diff.get("new_entrants") or [])
            }
            logger.info(
                "Loaded %d symbols for realtime monitoring (top_n=%s)",
                len(self._watchlist),
                self.top_n if self.top_n > 0 else "ALL",
            )
            self._enrich_watchlist_live()
        except Exception as exc:
            logger.warning("Failed to load watchlist: %s", exc, exc_info=True)

    def _enrich_watchlist_live(self) -> None:
        """Fetch avg_volume + earnings from FMP for watchlist symbols.

        Uses bulk profile endpoint (single call) for efficient avg_volume
        enrichment across 900+ symbols.  Falls back to per-symbol profile
        calls (capped to 50) if bulk is unavailable.

        The batch-quote endpoint omits avgVolume.  Without it the volume
        ratio is meaningless (everything looks like A0).  We fetch company
        profiles once per watchlist load and cache the value.
        """
        try:
            client = self.client
        except (AttributeError, ValueError, RuntimeError):
            return  # no API key — cannot enrich

        symbols = [
            str(r.get("symbol", "")).strip().upper()
            for r in self._watchlist if r.get("symbol")
        ]
        if not symbols:
            return
        sym_set = set(symbols)

        # Identify symbols that still need avgVolume enrichment
        need_avg_vol: set[str] = set()
        for sym in symbols:
            if sym in self._avg_vol_cache:
                continue  # already have it from a previous cycle
            wl_avg = 0.0
            for w in self._watchlist:
                if str(w.get("symbol", "")).strip().upper() == sym:
                    wl_avg = _safe_float(w.get("avg_volume"), 0.0)
                    break
            if wl_avg < 1000:
                need_avg_vol.add(sym)

        if need_avg_vol:
            enriched_count = 0
            # Strategy 1: Bulk profile (single call, all symbols)
            try:
                bulk = client.get_profile_bulk()
                for item in bulk:
                    sym = str(item.get("symbol") or "").strip().upper()
                    if sym not in need_avg_vol:
                        continue
                    avg_vol = _safe_float(
                        item.get("averageVolume") or item.get("volAvg"), 0.0
                    )
                    if avg_vol >= 1000:
                        self._avg_vol_cache[sym] = avg_vol
                        for w in self._watchlist:
                            if str(w.get("symbol", "")).strip().upper() == sym:
                                if _safe_float(w.get("avg_volume"), 0.0) < 1000:
                                    w["avg_volume"] = avg_vol
                                break
                        enriched_count += 1
                logger.info(
                    "Bulk profile enriched %d/%d symbols with avgVolume",
                    enriched_count, len(need_avg_vol),
                )
            except Exception as exc:
                logger.debug("Bulk profile unavailable (%s) — falling back to per-symbol", exc)
                # Strategy 2: Per-symbol fallback (capped to 50 to limit latency)
                remaining = need_avg_vol - set(self._avg_vol_cache)
                for i, sym in enumerate(sorted(remaining)[:50]):
                    try:
                        profile = client.get_company_profile(sym)
                        avg_vol = _safe_float(
                            profile.get("averageVolume") or profile.get("volAvg"), 0.0
                        )
                        if avg_vol >= 1000:
                            self._avg_vol_cache[sym] = avg_vol
                            for w in self._watchlist:
                                if str(w.get("symbol", "")).strip().upper() == sym:
                                    if _safe_float(w.get("avg_volume"), 0.0) < 1000:
                                        w["avg_volume"] = avg_vol
                                    break
                        time.sleep(0.15)  # throttle
                    except Exception as exc2:
                        logger.debug("Profile fetch failed for %s: %s", sym, exc2)

        # Apply cached avg_volume to any watchlist entries still missing it
        for w in self._watchlist:
            sym = str(w.get("symbol", "")).strip().upper()
            if _safe_float(w.get("avg_volume"), 0.0) < 1000 and sym in self._avg_vol_cache:
                w["avg_volume"] = self._avg_vol_cache[sym]

        # ── Earnings calendar for today ──
        try:
            from datetime import datetime as _datetime
            from zoneinfo import ZoneInfo as _ZoneInfo
            today = _datetime.now(_ZoneInfo("America/New_York")).date()
            earnings = client.get_earnings_calendar(today, today)
            for item in earnings:
                sym = str(item.get("symbol") or "").strip().upper()
                if sym in sym_set:
                    self._earnings_today_cache[sym] = item
                    # Update watchlist entry
                    for w in self._watchlist:
                        if str(w.get("symbol", "")).strip().upper() == sym:
                            w["earnings_today"] = True
                            raw_time = str(item.get("time") or item.get("releaseTime") or "").strip().lower()
                            w["earnings_timing"] = raw_time or None
                            logger.info("Earnings today: %s (timing=%s)", sym, raw_time or "unknown")
                            break
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
        # Clear technical indicator cache for removed symbols
        self._technical_scorer.clear()

    def start_async_newsstack(self, poll_interval: float = 15.0) -> None:
        """Start the background newsstack poller (call once at startup)."""
        self._async_newsstack = AsyncNewsstackPoller(poll_interval=poll_interval)
        self._async_newsstack.start()

    # ------------------------------------------------------------------
    # Fetch current quotes for watched symbols
    # ------------------------------------------------------------------
    def _fetch_realtime_quotes(self) -> dict[str, dict[str, Any]]:
        """Fetch current quotes for all watched symbols via FMP batch quote.

        For large watchlists (900+ symbols), requests are chunked into
        batches of ``_BATCH_QUOTE_CHUNK_SIZE`` to avoid URL-length limits.
        """
        if self._client_disabled_reason:
            return {}
        if not self._watchlist:
            return {}
        symbols = [str(r.get("symbol", "")).strip().upper() for r in self._watchlist if r.get("symbol")]
        if not symbols:
            return {}

        quotes: dict[str, dict[str, Any]] = {}
        # Chunk into batches for large watchlists
        chunk_size = _BATCH_QUOTE_CHUNK_SIZE
        for chunk_start in range(0, len(symbols), chunk_size):
            chunk = symbols[chunk_start:chunk_start + chunk_size]
            try:
                raw = self.client.get_batch_quotes(chunk)
                for q in raw:
                    sym = str(q.get("symbol", "")).strip().upper()
                    if sym:
                        quotes[sym] = q
            except Exception as exc:
                logger.warning(
                    "Failed to fetch realtime quotes for chunk %d–%d: %s",
                    chunk_start, chunk_start + len(chunk), exc,
                )
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

        # ── #12 Technical indicator confirmation/boost/penalty ───────
        tech_data = self._technical_scorer.get_technical_data(symbol, "1D")
        tech_score = tech_data.get("technical_score", 0.5)
        tech_signal = tech_data.get("technical_signal", "NEUTRAL")
        tech_rsi = tech_data.get("rsi")
        tech_macd = tech_data.get("macd_signal") or ""

        cooldown_forced = self._dynamic_cooldown.is_cooling(symbol)

        if tech_rsi is not None and level:
            if direction == "LONG":
                # RSI oversold boost — upgrade A1→A0, A2→A1 (only if not in cooldown)
                if tech_rsi < 30 and level == "A1" and not cooldown_forced:
                    level = "A0"
                    logger.debug(
                        "%s RSI %.1f < 30 oversold — upgrading A1→A0", symbol, tech_rsi,
                    )
                elif tech_rsi < 30 and level == "A2":
                    level = "A1"
                # RSI overbought penalty — downgrade A0→A1
                elif tech_rsi > 70 and level == "A0":
                    level = "A1"
                    logger.debug(
                        "%s RSI %.1f > 70 overbought — downgrade A0→A1", symbol, tech_rsi,
                    )
            elif direction == "SHORT":
                # RSI overbought boost for shorts (only if not in cooldown)
                if tech_rsi > 70 and level == "A1" and not cooldown_forced:
                    level = "A0"
                    logger.debug(
                        "%s RSI %.1f > 70 overbought — SHORT upgrade A1→A0", symbol, tech_rsi,
                    )
                elif tech_rsi > 70 and level == "A2":
                    level = "A1"
                # RSI oversold penalty for shorts
                elif tech_rsi < 30 and level == "A0":
                    level = "A1"

        # Technical consensus confirmation (non-RSI)
        if level == "A0" and tech_signal in ("STRONG_SELL",) and direction == "LONG":
            level = "A1"
            logger.debug(
                "%s STRONG_SELL technicals — blocking A0 LONG", symbol,
            )
        elif level == "A0" and tech_signal in ("STRONG_BUY",) and direction == "SHORT":
            level = "A1"
            logger.debug(
                "%s STRONG_BUY technicals — blocking A0 SHORT", symbol,
            )

        # Boost: strong tech alignment can raise A1→A0 for high-conviction
        if (level == "A1" and tech_score >= 0.75
                and ((direction == "LONG" and tech_signal in ("STRONG_BUY", "BUY"))
                     or (direction == "SHORT" and tech_signal in ("STRONG_SELL", "SELL")))
                and volume_ratio >= A1_VOLUME_RATIO_MIN * 1.5):
            level = "A0"
            logger.debug(
                "%s tech_score=%.3f + aligned tech_signal=%s — upgrading A1→A0",
                symbol, tech_score, tech_signal,
            )

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
                "tech_score": tech_score,
                "tech_signal": tech_signal,
                "rsi": tech_rsi,
                "macd_signal": tech_macd,
                "adx": tech_data.get("adx"),
                "williams": tech_data.get("williams"),
                "summary_buy": tech_data.get("summary_buy", 0),
                "summary_sell": tech_data.get("summary_sell", 0),
            },
            symbol_regime=symbol_regime,
            technical_score=tech_score,
            technical_signal=tech_signal,
            rsi=tech_rsi,
            macd_signal=tech_macd,
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
            self._quote_hashes.clear()
            self._avg_vol_cache.clear()
            self._earnings_today_cache.clear()
            self._new_entrant_set.clear()
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
        # Feed cached avg volumes to regime detector (FMP batch omits avgVolume)
        _wl_avgs: dict[str, float] = dict(self._avg_vol_cache)
        for _w in self._watchlist:
            _ws = str(_w.get("symbol", "")).strip().upper()
            if _ws and _ws not in _wl_avgs:
                _av = _safe_float(_w.get("avg_volume"), 0.0)
                if _av >= 1000:
                    _wl_avgs[_ws] = _av
        self._volume_regime._wl_avg_volumes = _wl_avgs
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
                # Technical indicator columns
                "tech_score": round(sym_signals[0].technical_score, 3) if sym_signals else 0.5,
                "rsi": round(sym_signals[0].rsi, 1) if sym_signals and sym_signals[0].rsi is not None else "",
                "tech_signal": sym_signals[0].technical_signal if sym_signals else "—",
                "macd": sym_signals[0].macd_signal if sym_signals else "",
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
            logger.warning("Failed to save signals: %s", exc, exc_info=True)

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
        except Exception as exc:
            logger.warning("Failed to load signals from disk: %s", exc, exc_info=True)
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
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="Number of symbols to monitor (0 = all, default)")
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
    top_label = str(args.top_n) if args.top_n > 0 else "ALL"
    logger.info(
        "Starting realtime signal engine (interval=%ds, top_n=%s, mode=%s, vd=%s)",
        engine.poll_interval, top_label, mode_label, VD_SIGNALS_PATH,
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
