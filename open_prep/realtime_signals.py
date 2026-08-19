"""Realtime signal engine — source-pluggable breakout detector with A0/A1/A2 alerting.

Monitors top-N ranked candidates from the latest open_prep run and detects
breakout signals every 20 s. Databento is the default; FMP is fallback/rollback.

Signal Levels
-------------
  A0 — Immediate action: strong breakout; volume-confirmed OR via key-level/technicals.
  A1 — Watch closely: early breakout forming.  A2 — Early warning, pre-A1.

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

from typing import Any, ClassVar

fcntl: Any | None
try:
    import fcntl  # POSIX only
    _FLOCK_SUPPORTED = True
except ImportError:  # Windows
    fcntl = None
    _FLOCK_SUPPORTED = False
import hashlib
import hmac
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

from newsstack_fmp._market_cal import is_us_equity_trading_day, regular_session_close_minutes

from .macro import FMPClient
from .quote_source import DatabentoQuoteSource, FMPQuoteSource, QuoteSource
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

# FMP stable batch-quote accepts comma-separated symbols.  Keep chunks below
# gateway URL limits; the production 200-symbol watchlist fits in one request.
_BATCH_QUOTE_CHUNK_SIZE = 250

# Signal level thresholds
A0_VOLUME_RATIO_MIN = 3.0        # 3x time-of-day-normalized volume pace (not the raw avg multiple)
A1_VOLUME_RATIO_MIN = 1.0        # 1x for A1 (was 1.5 — too late for mid-caps)
A2_VOLUME_RATIO_MIN = 0.6        # 0.6x for A2 early warning
A0_PRICE_CHANGE_PCT_MIN = 1.5    # 1.5% move for A0
A1_PRICE_CHANGE_PCT_MIN = 0.35   # 0.35% for A1 (was 0.5 — missed slow grinders)
A2_PRICE_CHANGE_PCT_MIN = 0.15   # 0.15% for A2 early warning

# Signal expiry & time-based level decay
MAX_SIGNAL_AGE_SECONDS = 480     # 8 min total signal life (was 15 — still too long)
A0_MAX_AGE_SECONDS = 180         # A0 → A1 after 3 min (was 5 — stale A0s)
A1_MAX_AGE_SECONDS = 300         # A1 → A2 after 5 min (was 10)
DATA_STALL_SECONDS = 300         # market-hours gap w/o a non-empty FMP fetch → data_stale=1 (catches an outage the loop-liveness gauges miss)

# Price velocity — detect stale moves where cumulative change is misleading
VELOCITY_LOOKBACK = 5            # polls to look back for price velocity
STALE_VELOCITY_PCT = 0.05        # <0.05% change over lookback = flat/stale

# Multi-rail safety (#7) — UNUSED as of 2026-07-08: nothing reads this constant;
A0_COOLDOWN_SECONDS = 600  # the real per-symbol cooldown is DynamicCooldown (base 60/20/10 s, max 300/180 s)

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


def _extract_snapshot_epoch(data: dict[str, Any] | None) -> float:
    """Best-effort epoch extraction from an Open-Prep snapshot."""
    if not data:
        return 0.0
    raw = data.get("generated_at") or data.get("run_datetime_utc")  # run payloads only set run_datetime_utc top-level
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        raw = raw.strip()
        if raw:
            try:
                # Python's fromisoformat does not accept a trailing 'Z' before 3.11.
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt.timestamp()
            except ValueError:
                try:
                    return float(raw)
                except ValueError:
                    pass
    return 0.0


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
    bind_host: str | None = None, error: str | None = None,
) -> None:
    _write_json_atomically(
        _RT_ENGINE_TELEMETRY_FILE,
        {
            "enabled": bool(enabled),
            "requested_port": int(requested_port),
            "active_port": int(active_port) if active_port is not None else None,
            "url": (f"http://{(bind_host or os.getenv('TELEMETRY_BIND_HOST', '0.0.0.0'))}:{active_port}" if active_port is not None else ""),
            "error": str(error) if error else "",
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    )


def _detect_rt_engine_pid() -> int | None:
    import shutil
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
        pgrep_exe = shutil.which("pgrep") or "pgrep"
        result = subprocess.run(  # noqa: S603 -- hardcoded pgrep argv resolved via shutil.which (no shell, no user input)
            [pgrep_exe, "-f", "python.*-m open_prep.realtime_signals"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    own_pid = os.getpid()
    for raw_pid in result.stdout.splitlines():
        try:
            pid = int(raw_pid.strip())
        except ValueError:
            continue
        if pid == own_pid:
            continue
        try:
            os.kill(pid, 0)
        except OSError:
            continue
        try:
            _RT_ENGINE_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
            _RT_ENGINE_PID_FILE.write_text(str(pid), encoding="utf-8")
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
    elif payload.get("running"):
        # The status file is written on START paths only — a crashed engine
        # leaves running:true + a dead PID forever. Re-validate liveness.
        pid = payload.get("pid")
        alive = False
        if isinstance(pid, int) and pid > 0:
            try:
                os.kill(pid, 0)
                alive = True
            except OSError:
                alive = False
        if not alive:
            detected = _detect_rt_engine_pid()
            payload["running"] = detected is not None
            payload["pid"] = detected
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
    lock_fd = open(_RT_ENGINE_LOCK_FILE, "w", encoding="utf-8")  # lock file is stateful by design (not atomic-replaced)
    if _FLOCK_SUPPORTED and fcntl is not None:
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
        if _FLOCK_SUPPORTED and fcntl is not None:
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
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{project_root}{os.pathsep}{existing_pp}" if existing_pp else str(project_root)

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

        log_fh = open(_RT_ENGINE_LOG_FILE, "a", encoding="utf-8")  # append-only runtime log; atomic replace would lose stream semantics
        try:
            proc = subprocess.Popen(  # noqa: S603 -- sys.executable with hardcoded module argv (no shell, no user input)
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
        _RT_ENGINE_PID_FILE.write_text(str(proc.pid), encoding="utf-8")
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
        poll_age = max(0.0, now - prev["epoch"])  # clamp backward wall-clock jumps
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

    ANP-5: the background loop itself never blocks on ``poll_once``; each poll
    runs in a short-lived worker thread so ``stop()`` can interrupt the wait.
    ANP-6: lightweight telemetry exposes poll health, latency, and cache size.
    """

    def __init__(self, poll_interval: float = 15.0) -> None:
        import threading
        self._data: dict[str, dict[str, Any]] = {}
        self._feed_items: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._interval = max(poll_interval, 5.0)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        # ANP-6 telemetry
        self.poll_count: int = 0
        self.poll_errors: int = 0
        self.last_poll_duration: float = 0.0
        self.last_success_at: float | None = None
        self.last_error_at: float | None = None
        self.last_error_msg: str | None = None
        self.cached_tickers_count: int = 0

    def start(self) -> None:
        """Start the background polling thread (daemon).

        Idempotent and thread-safe: the check-and-create runs under ``_lock`` so
        concurrent callers cannot each spawn a loop (a bare check-then-start
        races — two callers both see ``_thread is None`` and start two threads).
        """
        import threading
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name="newsstack-bg")
            self._thread.start()
        logger.info("Async newsstack poller started (interval=%.0fs)", self._interval)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def latest(self) -> dict[str, dict[str, Any]]:
        """Return the latest newsstack data (never blocks)."""
        with self._lock:
            return dict(self._data)

    def metrics(self) -> dict[str, Any]:
        """Return telemetry for the async poller (ANP-6).

        Metrics are kept intentionally cheap so they can be exposed on every
        poll cycle with minimal lock hold time.
        """
        with self._lock:
            return {
                "poll_count": self.poll_count,
                "poll_errors": self.poll_errors,
                "last_poll_duration": self.last_poll_duration,
                "last_success_at": self.last_success_at,
                "last_error_at": self.last_error_at,
                "last_error_msg": self.last_error_msg,
                "cached_tickers_count": self.cached_tickers_count,
            }

    def _loop(self) -> None:
        _newsstack_poll: Any = None
        _NSConfig: Any = None
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                if _newsstack_poll is None:
                    from newsstack_fmp.config import Config as _NSConfig
                    from newsstack_fmp.pipeline import poll_once as _newsstack_poll

                ns_candidates = _run_poll_once_in_thread(
                    _newsstack_poll, _NSConfig(), self._stop
                )
                if self._stop.is_set():
                    break
                new_data: dict[str, dict[str, Any]] = {}
                for nc in ns_candidates:
                    tk = str(nc.get("ticker", "")).strip().upper()
                    if tk:
                        prev = new_data.get(tk)
                        if prev is None or nc.get("news_score", 0) > prev.get("news_score", 0):
                            new_data[tk] = nc
                with self._lock:
                    self._data = new_data
                    self._feed_items = [dict(item) for item in ns_candidates[:500]]
                    self.cached_tickers_count = len(new_data)
                    self.poll_count += 1
                    self.last_success_at = time.time()
                    self.last_error_msg = None
            except Exception as exc:
                logger.debug("Async newsstack poll error: %s", exc)
                with self._lock:
                    self.poll_errors += 1
                    self.last_error_at = time.time()
                    self.last_error_msg = str(exc)
            finally:
                with self._lock:
                    self.last_poll_duration = time.monotonic() - t0
            self._stop.wait(self._interval)




def _run_poll_once_in_thread(
    poll_fn: Any,
    cfg: Any,
    stop_event: Any,
) -> list[dict[str, Any]]:
    """Run ``poll_once(cfg)`` in a worker thread that respects ``stop_event``.

    ANP-5: keeps the poller loop interruptible even when ``poll_once`` blocks
    on slow network adapters (e.g. RSS fetch with retry backoff).
    """
    import threading
    result: list[dict[str, Any]] = []
    error: Exception | None = None

    def _target() -> None:
        nonlocal result, error
        try:
            result = list(poll_fn(cfg))
        except Exception as exc:
            error = exc

    # Keep worker daemonized from creation time. Python forbids toggling
    # ``daemon`` after ``start()``, and this path intentionally detaches
    # blocked workers during shutdown.
    worker = threading.Thread(target=_target, name="newsstack-poll-once", daemon=True)
    worker.start()
    # Wait in small slices so stop_event can interrupt us promptly.
    while worker.is_alive() and not stop_event.is_set():
        worker.join(timeout=0.5)
    if worker.is_alive():
        # stop_event is set; detach the worker. It will finish eventually or
        # be killed when the process exits (already daemonized).
        return []
    if error is not None:
        raise error
    return result


class NearA0Repoller:
    """Opt-in background thread that re-polls the *near-A0 warm set* faster than
    the full ~30 s cycle, so an A1/A2 escalating to A0 reaches Slack in seconds
    instead of up to a full cycle late.

    Default-off (``RT_NEAR_A0_REPOLL_SECS=0``). Design for safety on a live
    producer:

    * **Reuses ``_detect_signal``** — a fast A0 is the same verdict as the full
      poll's detector (the news-catalyst A1→A0 upgrade stays full-poll-only). Reads
      ``_watchlist``/``_volume_regime``/active signals — but NOT read-only: detecting
      an A0 records a (shared, lock-guarded) DynamicCooldown transition.
    * **Shared quote source** — fetches through the engine's shared
      ``QuoteSource`` (``engine._quote_source``), the SAME seam
      ``RealtimeEngine._fetch_realtime_quotes`` uses for the main poll loop
      (self-healed the same way if not yet built). This guarantees the fast
      lane and the main loop always read off the SAME data source — both
      realtime Databento or both 15-min-delayed FMP, never split across the
      two. (Pre-Finding-2-fix this lane held its own ``FMPClient``, bypassing
      the seam entirely — the exact defect this fixes.) ``QuoteSource.fetch``
      does independent, side-effect-free HTTP/cache reads for
      ``session="regular"``, so concurrent calls from this thread and the
      main poll thread are safe.
    * **rt_notify dedup** — fresh A0s are pushed through the same per-(symbol,
      direction) dedup as the full poll, so the next full cycle never
      double-sends.

    Scope: this accelerates the *escalation* path only (A1/A2 → A0). A de-novo
    A0 on a symbol that was quiet last cycle is still first seen by the full
    poll — nothing short of polling everything faster can change that.
    """

    def __init__(self, engine: Any, interval: float) -> None:
        import threading
        self._engine = engine
        self._interval = max(float(interval), 2.0)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.poll_count = 0
        self.poll_errors = 0
        self.a0_pushed = 0
        self.last_warm_set_size = 0
        self.last_success_at: float | None = None
        self.last_error_msg: str | None = None

    def start(self) -> None:
        import threading
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="near-a0-repoll")
        self._thread.start()
        logger.info("Near-A0 re-poller started (interval=%.0fs)", self._interval)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def metrics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "poll_count": self.poll_count,
                "poll_errors": self.poll_errors,
                "a0_pushed": self.a0_pushed,
                "last_warm_set_size": self.last_warm_set_size,
                "last_success_at": self.last_success_at,
                "last_error_msg": self.last_error_msg,
            }

    def _quote_source_or_init(self) -> Any:
        """Resolve the engine's shared ``QuoteSource``, self-healing a
        rebuild if it hasn't been constructed yet.

        Mirrors ``RealtimeEngine._fetch_realtime_quotes``'s own self-heal
        (``getattr`` + ``_default_quote_source()`` + ``start_quote_source()``)
        exactly, so both lanes always converge on the identical
        ``QuoteSource`` instance rather than each independently deciding
        FMP-vs-Databento. In production this branch is essentially never
        taken: ``main()`` builds the engine (which sets ``_quote_source`` in
        ``__init__``) and calls ``engine.start_quote_source()`` before
        ``start_near_a0_repoller()`` ever spins up this thread.
        """
        eng = self._engine
        quote_source = getattr(eng, "_quote_source", None)
        if quote_source is None:
            quote_source = eng._default_quote_source()
            eng._quote_source = quote_source
            eng.start_quote_source()
        return quote_source

    def _warm_set(self) -> list[str]:
        """Current A1/A2 symbols — the tiers below A0 that can still escalate to it."""
        active = self._engine.get_active_signals()  # errors bubble to _loop's guard
        seen: set[str] = set()
        out: list[str] = []
        for s in active:
            if str(getattr(s, "level", "")) in ("A1", "A2"):
                sym = str(getattr(s, "symbol", "")).strip().upper()
                if sym and sym not in seen:
                    seen.add(sym)
                    out.append(sym)
        return out

    def _fetch(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch quotes for ``symbols`` through the engine's shared
        ``QuoteSource`` (Finding 2 fix — see the class docstring's "Shared
        quote source" bullet). Converts the ``QuoteSource.fetch`` list
        contract into the ``{symbol: row}`` dict ``_detect_fresh_a0`` wants,
        identically to ``RealtimeEngine._fetch_realtime_quotes`` (same
        upper-case keying, same last-wins dedup on duplicate symbols).

        Deliberate failure-semantics change, accepted (Finding-2 followup):
        pre-fix, a FMP fetch exception propagated out of this method to
        ``_loop()``'s outer ``except``, bumping ``poll_errors``. Post-fix,
        the SAME seam the main loop uses (``FMPQuoteSource._fetch_regular``)
        swallows per-chunk fetch errors internally (``logger.warning``, no
        re-raise) and returns ``[]`` — so a FMP outage now surfaces as an
        empty ``quotes`` dict, and ``_tick()``'s ``if not quotes: return``
        exits silently instead of recording a ``poll_errors`` count. This is
        "same seam = same failure semantics" by design, not a regression:
        the main loop already swallows FMP chunk errors the identical way,
        and a uniform failure path across both lanes is the point of routing
        through one shared source. Provider-level failures stay visible at
        the seam (FMPQuoteSource warnings, provider_usage tracking, the
        connected gauge) and via the main loop's own ``data_stale``
        gauge/visibility — this thread is only an acceleration of the main
        loop's signals, not an independent data-health source of truth, so
        it does not need its own redundant error counter for the same
        outage. (The Databento path's empty-fetch case is the analogous
        *normal* outcome — fail-closed omission of quote-less symbols — so
        treating an empty fetch here as an error would be false-positive
        prone on that path.)
        """
        quotes: dict[str, dict[str, Any]] = {}
        for q in self._quote_source_or_init().fetch(symbols, "regular"):
            sym = str(q.get("symbol", "")).strip().upper()
            if sym:
                quotes[sym] = q
        return quotes

    def _detect_fresh_a0(self, quotes: dict[str, dict[str, Any]]) -> list[Any]:
        eng = self._engine
        thresholds = eng._volume_regime.adjusted_thresholds()
        wl_map = {
            str(r.get("symbol", "")).strip().upper(): r
            for r in eng._watchlist if r.get("symbol")
        }
        news: dict[str, dict[str, Any]] = {}
        if getattr(eng, "_async_newsstack", None) is not None:
            news = eng._async_newsstack.latest()
        fresh: list[Any] = []
        for sym, quote in quotes.items():
            try:
                sig = eng._detect_signal(
                    sym, quote, wl_map.get(sym, {}),
                    regime_thresholds=thresholds,
                    expected_volume_fraction=quote.get("expected_volume_fraction"),
                )
            except Exception:
                continue  # one bad symbol must not sink the batch (bubble via _loop otherwise)
            if sig is not None and getattr(sig, "level", "") == "A0":
                nd = news.get(sym)
                if nd:  # cheap news enrich so the early push still carries 📰
                    sig.news_score = _safe_float(nd.get("news_score", 0))
                    sig.news_category = str(nd.get("category", ""))
                    sig.news_headline = str(nd.get("headline", ""))[:200]
                # Attach entry/stop/target so the EARLIEST push carries the
                # bracket too — fulfilling the "consumed by BOTH" contract the
                # trade-context comment states for the main poll path.
                from open_prep import trade_context as _trade_context
                _trade_context.attach(sig)
                fresh.append(sig)
        return fresh

    def _push(self, fresh: list[Any]) -> None:
        from open_prep import rt_notify
        pushed = rt_notify.notify_fresh_signals(fresh)
        with self._lock:
            self.a0_pushed += len(pushed)

    def _tick(self) -> None:
        if not _is_within_market_hours():
            return  # no orders resting off-hours; skip the quote fetch entirely
        warm = self._warm_set()
        with self._lock:
            self.last_warm_set_size = len(warm)
        if not warm:
            return
        quotes = self._fetch(warm)
        if not quotes:
            return
        fresh = self._detect_fresh_a0(quotes)
        if fresh:
            self._push(fresh)
        with self._lock:
            self.poll_count += 1
            self.last_success_at = time.time()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:  # fail-soft — never let the fast lane die
                with self._lock:
                    self.poll_errors += 1
                    self.last_error_msg = str(exc)
                logger.debug("Near-A0 re-poll error: %s", exc)
            self._stop.wait(self._interval)


# ---------------------------------------------------------------------------
# Market-hours gate
# ---------------------------------------------------------------------------

def _expected_cumulative_volume_fraction() -> float:
    """Expected fraction of daily volume at current time of day.

    Uses a front-loaded intraday model (corrected 2026-07-08 — NOT a
    U-shape, and there is no closing-surge step):
      - First 30 min (9:30-10:00): 0 → 25% of daily volume (linear)
      - 10:00-11:00 (elapsed 30-90 min): 25% → 40% (linear)
      - 11:00-16:00 (elapsed 90-390 min): 40% → 100% single linear ramp
      KNOWN LIMITATION: the 30/90/300-min breakpoints assume a 390-min session;
      on NYSE half-days (early 13:00 close) the fraction reaches only ~0.64 at
      the close then jumps to 1.0 — pace/thin detection is mis-calibrated on
      ~3 sessions/yr (same class as the daemon's disclosed half-day limitation).

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
    close_min = regular_session_close_minutes(now_et.date())
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


def _resolve_expected_volume_fraction(snapshot_fraction: Any | None = None) -> float:
    """Return replay-safe expected cumulative volume fraction.

    If a quote provides ``expected_volume_fraction`` we trust that persisted
    value (bounded to ``[0.02, 1.0]``) so replay/test runs are deterministic.
    Otherwise we fall back to the live wall-clock model.
    """
    candidate = _safe_float(snapshot_fraction, 0.0)
    if candidate > 0.0:
        return max(0.02, min(1.0, candidate))
    return max(_expected_cumulative_volume_fraction(), 0.02)


def _market_session(now_et: datetime | None = None) -> str:
    """Return closed, premarket, regular, or postmarket for US equities.

    ``now_et`` is injectable for deterministic boundary tests.  Without it,
    use ``America/New_York`` with a fail-closed timezone fallback.
    """
    if now_et is None:
        try:
            from zoneinfo import ZoneInfo
            now_et = datetime.now(ZoneInfo("America/New_York"))
        except ImportError:
            try:
                from dateutil.tz import gettz
                tz = gettz("America/New_York")
                if tz is None:
                    raise ImportError("dateutil could not resolve America/New_York")
                now_et = datetime.now(tz)
            except ImportError as exc:
                raise RuntimeError(
                    "America/New_York timezone unavailable: install `tzdata` "
                    "or `python-dateutil`. Refusing to fall back to a fixed UTC "
                    "offset because that silently drifts 1h every winter and "
                    "would corrupt realtime signal market-hours gating."
                ) from exc

    # Monday=0, Sunday=6
    if now_et.weekday() >= 5:
        return "closed"

    # NYSE full-day holiday: FMP quotes carry the previous session's prints, so
    # without this gate the engine fires false A0/A1 breakouts across the whole
    # watchlist on a closed day (e.g. observed Independence Day 2026-07-03).
    if not is_us_equity_trading_day(now_et.date()):
        return "closed"

    now_minute = now_et.hour * 60 + now_et.minute
    regular_open = 9 * 60 + 30
    regular_close = regular_session_close_minutes(now_et.date())
    if 4 * 60 <= now_minute < regular_open:
        return "premarket"
    if regular_open <= now_minute < regular_close:
        return "regular"
    if regular_close <= now_minute < 20 * 60:
        return "postmarket"
    return "closed"


def _is_within_market_hours() -> bool:
    """Compatibility wrapper for the 04:00-20:00 ET product window."""
    return _market_session() != "closed"


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
        """Record metrics from a *productive* poll cycle (early-return paths — client-disabled / no-quotes / holiday-suspect — skip this, so poll_count undercounts total cycles). Internal /telemetry.json only: score_diff carries the mean signal SCORE (not a delta); change_pct the mean ABSOLUTE change."""
        self._poll_count += 1
        self._score_diffs.append(score_diff)
        self._volume_ratios.append(volume_ratio)
        self._change_pcts.append(change_pct)
        a0 = 1.0 if any(getattr(s, "level", "") == "A0" for s in signals) else 0.0
        self._a0_events.append(a0)

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary of accumulated metrics."""

        def _stats(d: deque[float]) -> dict[str, float]:
            vals = sorted(v for v in d if (v == v and v not in (float("inf"), float("-inf"))))
            if not vals:
                return {"min": 0.0, "mean": 0.0, "max": 0.0, "count": 0}
            n = len(vals)
            return {
                "min": round(vals[0], 4),
                "mean": round(sum(vals) / n, 4),
                "median": round((vals[(n - 1) // 2] + vals[n // 2]) / 2, 4),
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

_PROCESS_START_TIME = time.time()

# FMP endpoints an alert rule watches by label. A per-endpoint series exists
# only once that endpoint has been called, so increase(...{endpoint="X"}[15m])
# takes the FIRST burst as its own baseline and swallows it — precisely the
# event sp-fmp-profile-bulk-used (for: 0s, threshold > 0, noDataState: OK) was
# written to catch, and the one that previously burned ~113 MB per six minutes.
# Seeding at zero mirrors the closed verdict set the daemon exporter already
# seeds for live_overlay_portfolio_risk_decisions_total. The seed sits inside
# the usage block on purpose: before the first poll there is no client and
# nothing can have called profile-bulk either, so the series exists from the
# first moment the watched event is possible. The population is re-derived from
# alert-rules.yaml by tests/test_realtime_signals_metrics_endpoint.py::
# test_every_alert_watched_fmp_endpoint_is_seeded, so a rule that starts
# watching another endpoint cannot leave it unseeded.
SEEDED_FMP_ENDPOINTS: tuple[str, ...] = ("/stable/profile-bulk",)


def _collect_process_metrics(engine: Any | None = None) -> str:
    """Return Prometheus exposition format metrics for this process.

    Pure-stdlib implementation — no prometheus_client dependency required.
    Emits standard process metrics (cpu, memory, fds, uptime) plus
    Python GC stats.  Designed for Alloy/Grafana Cloud Prometheus scraping.

    When ``engine`` is provided, additional semantic readiness gauges
    are emitted so Grafana can alert on watchlist/snapshot/poll health
    without treating "zero active signals" as an incident.
    """
    import gc as _gc
    import platform as _platform

    try:
        import resource as _resource  # POSIX-only; guarded for cross-platform safety
        _resource_available = True
    except ImportError:
        _resource_available = False
        _resource = None  # type: ignore[assignment]

    _prefix = "signals_producer"
    lines: list[str] = []

    # CPU seconds (user + system) — POSIX only; skip on non-POSIX platforms
    if _resource_available and _resource is not None:
        usage = _resource.getrusage(_resource.RUSAGE_SELF)
        cpu_seconds = usage.ru_utime + usage.ru_stime
        lines.append(f"# HELP {_prefix}_process_cpu_seconds_total Total user and system CPU time spent in seconds.")
        lines.append(f"# TYPE {_prefix}_process_cpu_seconds_total counter")
        lines.append(f"{_prefix}_process_cpu_seconds_total {cpu_seconds:.6f}")

        # Resident memory (RSS)
        try:
            with open("/proc/self/status", encoding="utf-8") as _f:
                for _line in _f:
                    if _line.startswith("VmRSS:"):
                        rss_bytes = int(_line.split()[1]) * 1024
                        break
                else:
                    raise FileNotFoundError
        except (FileNotFoundError, PermissionError, ValueError):
            rss_bytes = usage.ru_maxrss
            if _platform.system() == "Linux":
                rss_bytes *= 1024
        lines.append(f"# HELP {_prefix}_process_resident_memory_bytes Resident memory size in bytes.")
        lines.append(f"# TYPE {_prefix}_process_resident_memory_bytes gauge")
        lines.append(f"{_prefix}_process_resident_memory_bytes {rss_bytes}")

    # Virtual memory
    try:
        with open("/proc/self/status", encoding="utf-8") as _f:
            for _line in _f:
                if _line.startswith("VmSize:"):
                    vsize_bytes = int(_line.split()[1]) * 1024
                    lines.append(f"# HELP {_prefix}_process_virtual_memory_bytes Virtual memory size in bytes.")
                    lines.append(f"# TYPE {_prefix}_process_virtual_memory_bytes gauge")
                    lines.append(f"{_prefix}_process_virtual_memory_bytes {vsize_bytes}")
                    break
    except (FileNotFoundError, PermissionError, ValueError):
        pass

    # Open file descriptors
    try:
        fd_count = len(os.listdir(f"/proc/{os.getpid()}/fd"))
        lines.append(f"# HELP {_prefix}_process_open_fds Number of open file descriptors.")
        lines.append(f"# TYPE {_prefix}_process_open_fds gauge")
        lines.append(f"{_prefix}_process_open_fds {fd_count}")
    except (FileNotFoundError, PermissionError):
        pass

    # Process start time
    lines.append(f"# HELP {_prefix}_process_start_time_seconds Start time of the process since unix epoch in seconds.")
    lines.append(f"# TYPE {_prefix}_process_start_time_seconds gauge")
    lines.append(f"{_prefix}_process_start_time_seconds {_PROCESS_START_TIME:.6f}")

    # Uptime (convenience gauge)
    uptime = time.time() - _PROCESS_START_TIME
    lines.append(f"# HELP {_prefix}_process_uptime_seconds Time since process start in seconds.")
    lines.append(f"# TYPE {_prefix}_process_uptime_seconds gauge")
    lines.append(f"{_prefix}_process_uptime_seconds {uptime:.1f}")

    # Python GC collections
    gc_stats = _gc.get_stats()
    lines.append(f"# HELP {_prefix}_python_gc_collections_total Total number of GC collections per generation.")
    lines.append(f"# TYPE {_prefix}_python_gc_collections_total counter")
    for i, stat in enumerate(gc_stats):
        lines.append(f'{_prefix}_python_gc_collections_total{{generation="{i}"}} {stat["collections"]}')

    if engine is not None:
        now = time.time()
        poll_age = (
            max(0.0, now - engine.last_poll_success_epoch)
            if engine.last_poll_success_epoch > 0
            else 999999.0
        )
        lines.append(f"# TYPE {_prefix}_watchlist_symbols gauge")
        lines.append(f"{_prefix}_watchlist_symbols {len(engine._watchlist)}")
        lines.append(f"# TYPE {_prefix}_open_prep_snapshot_loaded gauge")
        lines.append(f"{_prefix}_open_prep_snapshot_loaded {engine.open_prep_snapshot_loaded}")
        lines.append(f"# TYPE {_prefix}_open_prep_snapshot_age_seconds gauge")
        lines.append(f"{_prefix}_open_prep_snapshot_age_seconds {engine.open_prep_snapshot_age_seconds:.1f}")
        lines.append(f"# TYPE {_prefix}_last_poll_age_seconds gauge")
        lines.append(f"{_prefix}_last_poll_age_seconds {poll_age:.1f}")
        lines.append(f"# TYPE {_prefix}_last_poll_duration_seconds gauge")
        lines.append(f"{_prefix}_last_poll_duration_seconds {engine.last_poll_duration_seconds:.3f}")
        # Data-freshness, distinct from loop-liveness above: last_data_age grows
        # during a market-hours FMP outage that leaves last_poll_age at ~0.
        # data_stale is self-gated on market hours, so an empty off-hours fetch
        # (normal) is not flagged — only a real market-hours data stall trips it.
        _last_data_epoch = getattr(engine, "_last_data_epoch", 0.0)
        _last_data_age = max(0.0, now - _last_data_epoch) if _last_data_epoch > 0 else 999999.0
        _data_stale = 1 if (getattr(engine, "_in_market_hours", False) and _last_data_age > DATA_STALL_SECONDS) else 0  # cached flag, NOT the raising _is_within_market_hours() probe (must not break /metrics)
        lines.append(f"# TYPE {_prefix}_last_data_age_seconds gauge")
        lines.append(f"{_prefix}_last_data_age_seconds {_last_data_age:.1f}")
        lines.append(f"# TYPE {_prefix}_data_stale gauge")
        lines.append(f"{_prefix}_data_stale {_data_stale}")
        # Client-disabled visibility: FMPClient.from_env() failed at boot (e.g.
        # missing FMP_API_KEY) and every cycle publishes empty signals while
        # loop-liveness stays green — without this gauge that state is
        # indistinguishable from a healthy zero-signal market. Rendered
        # unconditionally so absence == scrape-down (sp-scrape-down covers it).
        _disabled_reason = getattr(engine, "_client_disabled_reason", None)
        lines.append(f"# TYPE {_prefix}_client_disabled gauge")
        lines.append(f"{_prefix}_client_disabled {1 if _disabled_reason else 0}")
        if _disabled_reason:
            _reason_label = str(_disabled_reason).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f"# TYPE {_prefix}_client_disabled_info gauge")
            lines.append(f'{_prefix}_client_disabled_info{{reason="{_reason_label}"}} 1')
        _session_name = str(getattr(engine, "_market_session_name", "closed"))
        lines.append(f"# TYPE {_prefix}_market_session gauge")
        for _session in ("closed", "premarket", "regular", "postmarket"):
            lines.append(
                f'{_prefix}_market_session{{session="{_session}"}} '
                f'{1 if _session_name == _session else 0}'
            )
        lines.append(f"# TYPE {_prefix}_quotes_polled gauge")
        lines.append(f"{_prefix}_quotes_polled {1 if getattr(engine, '_quotes_polled', False) else 0}")
        _shadow = getattr(engine, "_extended_shadow", {})
        _shadow_epoch = _safe_float(_shadow.get("last_poll_epoch"), 0.0)
        _shadow_age = max(0.0, now - _shadow_epoch) if _shadow_epoch > 0 else 999999.0
        lines.append(f"# TYPE {_prefix}_extended_shadow_enabled gauge")
        lines.append(
            f"{_prefix}_extended_shadow_enabled "
            f"{1 if getattr(engine, 'extended_shadow_enabled', False) else 0}"
        )
        lines.append(f"# TYPE {_prefix}_extended_shadow_last_poll_age_seconds gauge")
        lines.append(f"{_prefix}_extended_shadow_last_poll_age_seconds {_shadow_age:.1f}")
        lines.append(f"# TYPE {_prefix}_extended_shadow_rows gauge")
        for _feed, _key in (
            ("regular", "regular_rows"),
            ("aftermarket_quote", "quote_rows"),
            ("aftermarket_trade", "trade_rows"),
        ):
            lines.append(
                f'{_prefix}_extended_shadow_rows{{feed="{_feed}"}} '
                f'{int(_shadow.get(_key, 0))}'
            )
        lines.append(f"# TYPE {_prefix}_extended_shadow_fresh_rows gauge")
        for _feed, _key in (
            ("regular", "fresh_regular_rows"),
            ("aftermarket_quote", "fresh_quote_rows"),
            ("aftermarket_trade", "fresh_trade_rows"),
        ):
            lines.append(
                f'{_prefix}_extended_shadow_fresh_rows{{feed="{_feed}"}} '
                f'{int(_shadow.get(_key, 0))}'
            )
        lines.append(f"# TYPE {_prefix}_extended_shadow_overlap_rows gauge")
        lines.append(
            f"{_prefix}_extended_shadow_overlap_rows "
            f"{int(_shadow.get('overlap_rows', 0))}"
        )
        lines.append(f"# TYPE {_prefix}_extended_shadow_reference_delta_bps gauge")
        lines.append(
            f"{_prefix}_extended_shadow_reference_delta_bps "
            f"{_safe_float(_shadow.get('mean_reference_delta_bps'), 0.0):.3f}"
        )
        _postmarket_stats = getattr(engine, "_postmarket_adapter_stats", {})
        lines.append(f"# TYPE {_prefix}_postmarket_baseline_symbols gauge")
        lines.append(
            f"{_prefix}_postmarket_baseline_symbols "
            f"{len(getattr(engine, '_postmarket_close_volume', {}))}"
        )
        lines.append(f"# TYPE {_prefix}_postmarket_adapter_rows gauge")
        for _state, _key in (
            ("price_ready", "price_ready_rows"),
            ("signal_ready", "signal_ready_rows"),
            ("trade_price", "trade_price_rows"),
            ("midpoint_price", "midpoint_price_rows"),
        ):
            lines.append(
                f'{_prefix}_postmarket_adapter_rows{{state="{_state}"}} '
                f'{int(_postmarket_stats.get(_key, 0))}'
            )
        lines.append(f"# TYPE {_prefix}_postmarket_adapter_rejections gauge")
        for _reason, _key in (
            ("no_reference", "rejected_no_reference"),
            ("no_fresh_price", "rejected_no_fresh_price"),
            ("crossed_quote", "rejected_crossed_quote"),
            ("missing_baseline", "rejected_missing_baseline"),
            ("volume_regression", "rejected_volume_regression"),
        ):
            lines.append(
                f'{_prefix}_postmarket_adapter_rejections{{reason="{_reason}"}} '
                f'{int(_postmarket_stats.get(_key, 0))}'
            )

        # H3 (2026-07-08): FMP usage counters. The 24/7 producer is the
        # single largest FMP consumer and previously ran past every
        # bandwidth-quota check — only the ingest paths were instrumented
        # (newsstack provider_usage). Reads the lazily created client's
        # per-endpoint stats; absent client (key missing / never polled)
        # simply emits nothing.
        fmp_client = getattr(engine, "_client", None)
        if fmp_client is not None and hasattr(fmp_client, "get_endpoint_usage_stats"):
            try:
                _usage = fmp_client.get_endpoint_usage_stats()
            except Exception:  # pragma: no cover - stats must never break /metrics
                _usage = {}
            _req = sum(int(s.get("calls", 0)) for s in _usage.values())
            _err = sum(int(s.get("errors", 0)) for s in _usage.values())
            _rbytes = sum(int(s.get("response_bytes", 0)) for s in _usage.values())
            lines.append(f"# HELP {_prefix}_fmp_requests_total FMP API requests since process start (all endpoints).")
            lines.append(f"# TYPE {_prefix}_fmp_requests_total counter")
            lines.append(f"{_prefix}_fmp_requests_total {_req}")
            lines.append(f"# TYPE {_prefix}_fmp_request_errors_total counter")
            lines.append(f"{_prefix}_fmp_request_errors_total {_err}")
            lines.append(f"# HELP {_prefix}_fmp_response_bytes_total Decoded FMP response payload bytes since process start.")
            lines.append(f"# TYPE {_prefix}_fmp_response_bytes_total counter")
            lines.append(f"{_prefix}_fmp_response_bytes_total {_rbytes}")
            lines.append(f"# TYPE {_prefix}_fmp_endpoint_requests_total counter")
            lines.append(f"# TYPE {_prefix}_fmp_endpoint_errors_total counter")
            lines.append(f"# TYPE {_prefix}_fmp_endpoint_empty_responses_total counter")
            lines.append(f"# TYPE {_prefix}_fmp_endpoint_response_bytes_total counter")
            for _path, _stats in sorted(({e: {} for e in SEEDED_FMP_ENDPOINTS} | _usage).items()):
                _endpoint = str(_path).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
                _labels = f'{{endpoint="{_endpoint}"}}'
                lines.append(f"{_prefix}_fmp_endpoint_requests_total{_labels} {int(_stats.get('calls', 0))}")
                lines.append(f"{_prefix}_fmp_endpoint_errors_total{_labels} {int(_stats.get('errors', 0))}")
                lines.append(f"{_prefix}_fmp_endpoint_empty_responses_total{_labels} {int(_stats.get('empty_responses', 0))}")
                lines.append(f"{_prefix}_fmp_endpoint_response_bytes_total{_labels} {int(_stats.get('response_bytes', 0))}")

        _missing_avg = sum(
            1 for _row in engine._watchlist
            if isinstance(_row, dict) and _safe_float(_row.get("avg_volume"), 0.0) < 1000
        )
        _negative_avg = len(getattr(engine, "_avg_vol_retry_after", {}))
        lines.append(f"# TYPE {_prefix}_avg_volume_missing_symbols gauge")
        lines.append(f"{_prefix}_avg_volume_missing_symbols {_missing_avg}")
        lines.append(f"# TYPE {_prefix}_avg_volume_negative_cache_symbols gauge")
        lines.append(f"{_prefix}_avg_volume_negative_cache_symbols {_negative_avg}")
        lines.extend(_collect_a0_latency_metrics(engine, now, _prefix) + _collect_databento_feed_metrics(engine))

    return "\n".join(lines) + "\n"


def _require_internal_token_on_railway() -> None:
    """Refuse to serve tokenless on Railway — a missing secret arrives as "".

    The tokenless mode is a deliberate LOCAL convenience (documented and
    tested); on Railway it is indistinguishable from a deleted/renamed secret
    and would expose ``/signals.json`` + ``/metrics`` unauthenticated on the
    public domain while the sibling endpoints keep failing closed. Crash at
    startup instead — loud and immediate (2026-08-18, Doppelgaenger-Sweep).
    """
    if os.getenv("RAILWAY_ENVIRONMENT") and not os.getenv("SIGNALS_INTERNAL_TOKEN", "").strip():
        raise SystemExit(
            "SIGNALS_INTERNAL_TOKEN is required on Railway: a missing secret is "
            "served as an empty string and would publish /signals.json and "
            "/metrics unauthenticated. Set the variable on this service."
        )


def _start_telemetry_server(
    telemetry: ScoreTelemetry,
    port: int = 8099,
    host: str | None = None,
    engine: Any = None,
) -> Any:
    """Launch a lightweight HTTP server serving ``/telemetry.json`` and ``/healthz``.

    Runs as a daemon thread — will be cleaned up when the main process exits.
    Returns the HTTPServer instance (or None on failure) for graceful shutdown.

    The bind host defaults to ``0.0.0.0`` (all interfaces) so Railway's
    reverse proxy can reach the process from outside the container.  Override
    via the ``host`` argument or the ``TELEMETRY_BIND_HOST`` environment
    variable (e.g. set to ``127.0.0.1`` to restrict to loopback in
    non-container deployments).

    When ``engine`` is provided, ``/signals`` falls back to live engine state
    if ``SIGNALS_PATH`` has not yet been written (cold start before the first
    ``poll_once()`` finishes).  When ``SIGNALS_INTERNAL_TOKEN`` is set in the
    environment, both ``/signals`` and ``/metrics`` additionally require an
    ``Authorization: Bearer <token>`` header — a minimal shared-secret guard
    for the case where the bind host is exposed beyond the private network
    (audit PR #2913 F2; ``/metrics`` token-gate added by audit F6).  The
    private ``/news-feed`` endpoint always fails closed unless that token is
    configured and supplied.

    On Railway the empty-token mode is refused at startup (see
    ``_require_internal_token_on_railway``): Railway serves a MISSING secret
    as an empty string, so the tokenless local-dev convenience would silently
    publish ``/signals.json`` and ``/metrics`` on the public domain
    (2026-08-18, Doppelgaenger-Sweep D-K1).
    """
    _require_internal_token_on_railway()
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    bind_host = host or os.getenv("TELEMETRY_BIND_HOST", "0.0.0.0")

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/healthz":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"ok\n")
            elif self.path == "/readyz":
                ready = False
                reason = "engine not initialised"
                source_reason = _quote_source_readiness_reason(engine)
                if engine is None:
                    pass
                elif source_reason:
                    reason = source_reason
                elif _client_disabled_for_selected_quote_source(engine):
                    reason = f"client disabled ({engine._client_disabled_reason})"
                elif len(getattr(engine, "_watchlist", [])) == 0:
                    reason = "watchlist not loaded"
                elif getattr(engine, "open_prep_snapshot_loaded", 0.0) != 1.0:
                    reason = "open-prep snapshot not loaded"
                else:
                    poll_age = max(0.0, time.time() - getattr(engine, "last_poll_success_epoch", 0.0))
                    if poll_age < 300:
                        ready = True
                    else:
                        reason = f"last poll stale ({poll_age:.0f}s ago)"
                self.send_response(200 if ready else 503)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"ready\n" if ready else reason.encode() + b"\n")
            elif self.path in ("/telemetry.json", "/telemetry"):
                import json as _json
                try:
                    body = _json.dumps(telemetry.snapshot(), indent=2, allow_nan=False).encode()
                except (ValueError, TypeError):
                    body = _json.dumps({"error": "non-finite value in telemetry payload"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            elif self.path in ("/signals.json", "/signals"):
                _auth_token = os.getenv("SIGNALS_INTERNAL_TOKEN", "").strip()
                if _auth_token:
                    _hdr = self.headers.get("Authorization", "")
                    _parts = _hdr.split(" ", 1)
                    _supplied = _parts[1].strip() if len(_parts) == 2 and _parts[0].lower() == "bearer" else ""
                    if not hmac.compare_digest(_supplied.encode(), _auth_token.encode()):  # bytes: a non-ASCII header would make the str form raise
                        self.send_response(401)
                        self.end_headers()
                        return
                import json as _json
                payload = _read_json_file(SIGNALS_PATH)
                if not payload and engine is not None:
                    _active = engine.get_active_signals()
                    payload = {
                        "signals": [s.to_dict() for s in _active],
                        "signal_count": len(_active),
                        "a0_count": sum(1 for s in _active if s.level == "A0"),
                        "a1_count": sum(1 for s in _active if s.level == "A1"),
                        "a2_count": sum(1 for s in _active if s.level == "A2"),
                        "status": "cold_start",
                    }
                if not payload:
                    payload = {"signals": [], "signal_count": 0, "a0_count": 0, "a1_count": 0, "a2_count": 0, "status": "warming_up"}
                try:
                    body = _json.dumps(payload, indent=2, allow_nan=False, default=str).encode()
                except (ValueError, TypeError):
                    body = _json.dumps({"error": "non-finite value in signals payload"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            elif self.path in ("/news-feed.json", "/news-feed"):
                _serve_news_feed(self, engine)
            elif self.path == "/metrics":
                _auth_token = os.getenv("SIGNALS_INTERNAL_TOKEN", "").strip()
                if _auth_token:
                    _hdr = self.headers.get("Authorization", "")
                    _parts = _hdr.split(" ", 1)
                    _supplied = _parts[1].strip() if len(_parts) == 2 and _parts[0].lower() == "bearer" else ""
                    if not hmac.compare_digest(_supplied.encode(), _auth_token.encode()):  # bytes: a non-ASCII header would make the str form raise
                        self.send_response(401)
                        self.end_headers()
                        return
                body = _collect_process_metrics(engine).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self) -> None:
            if self.path in ("/ai-insights", "/ai-validation"):
                _serve_ai_insights(self)
            else:
                self.send_response(404)
                self.end_headers()

        def do_HEAD(self) -> None:
            if self.path == "/healthz":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, fmt: str, *args: Any) -> None:
            # Silence standard request logging to avoid log noise
            pass

    try:
        server = ThreadingHTTPServer((bind_host, port), _Handler)  # threaded: one slow scrape must not block /healthz
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        _update_telemetry_status(enabled=True, requested_port=port, active_port=int(server.server_port), bind_host=bind_host, error=None)
        logger.info("Telemetry HTTP server listening on http://%s:%d", bind_host, int(server.server_port))
        return server
    except OSError as exc:
        logger.warning("Could not start telemetry server on port %d: %s", port, type(exc).__name__, exc_info=True)
        try:
            fallback_server = ThreadingHTTPServer((bind_host, 0), _Handler)
            t = threading.Thread(target=fallback_server.serve_forever, daemon=True)
            t.start()
            fallback_port = int(fallback_server.server_port)
            error = f"Requested port {port} unavailable ({type(exc).__name__}); using fallback port {fallback_port}."
            _update_telemetry_status(
                enabled=True,
                requested_port=port,
                active_port=fallback_port,
                bind_host=bind_host, error=error,
            )
            logger.warning("Telemetry server fell back to port %d after port %d failed", fallback_port, port)
            return fallback_server
        except OSError as fallback_exc:
            error = (
                f"Requested port {port} unavailable ({type(exc).__name__}); "
                f"fallback bind failed ({type(fallback_exc).__name__})."
            )
            _update_telemetry_status(enabled=False, requested_port=port, active_port=None, bind_host=bind_host, error=error)
            logger.warning("Could not start telemetry server fallback after port %d failed", port, exc_info=True)
            return None


def _fetch_json_url(url: str, timeout: float = 15.0) -> dict[str, Any] | None:
    """Fetch and parse a JSON document from ``url``.

    Returns the decoded mapping, or ``None`` on any network/parse error so
    callers can fall back to a local snapshot.  Only ``http(s)`` URLs are
    accepted; an optional snapshot token is sent as Bearer only over HTTPS.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    if not url.lower().startswith(("http://", "https://")):
        logger.warning("OPEN_PREP_SNAPSHOT_URL ignored — unsupported scheme")
        return None
    try:
        parsed_url = urllib.parse.urlsplit(url)
        github_contents = (
            parsed_url.scheme.lower() == "https"
            and parsed_url.netloc.lower() == "api.github.com"
            and parsed_url.path.lower().startswith("/repos/")
            and "/contents/" in parsed_url.path.lower()
        )
        token = os.getenv("OPEN_PREP_SNAPSHOT_URL_TOKEN", "").strip()
        if not token and github_contents:
            # Reuse an existing repo-read credential only for GitHub's Contents
            # API. Never forward these generic credentials to a custom URL.
            token = next(
                (
                    os.getenv(name, "").strip()
                    for name in ("GITHUB_WORKFLOW_MONITOR_TOKEN", "GH_PAT", "GITHUB_TOKEN")
                    if os.getenv(name, "").strip()
                ),
                "",
            )
        headers = {"User-Agent": "smc-signals-producer"}
        if github_contents:
            headers["Accept"] = "application/vnd.github.raw+json"
        if token and parsed_url.scheme.lower() == "https":
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, OSError) as exc:
        logger.warning("Failed to fetch snapshot from URL: %s", type(exc).__name__)
        return None
    if not isinstance(payload, dict):
        logger.warning("Snapshot URL returned non-object JSON — ignoring")
        return None
    return payload


def _refresh_quote_reference_from_url() -> bool:
    """Fetch the daily quote-reference snapshot (previous_close/ADV for the
    producer universe) from ``QUOTE_REFERENCE_SNAPSHOT_URL`` and write it to the
    local path ``QuoteReference.load()`` reads — mirroring the watchlist's
    ``OPEN_PREP_SNAPSHOT_URL`` fetch. It rides the SAME bot branch, so the same
    ``OPEN_PREP_SNAPSHOT_URL_TOKEN`` authorizes it (``_fetch_json_url`` reuse,
    no new HTTP site). Fail-soft: on a missing URL or fetch/write error the
    last-good local file is kept (never blanked). Returns True only when a
    fresh reference was written."""
    url = _quote_reference_snapshot_url()
    if not url:
        return False
    payload = _fetch_json_url(url)
    if not payload:
        logger.warning("QUOTE_REFERENCE_SNAPSHOT_URL fetch failed — keeping last-good local quote_reference")
        return False
    dest = _ARTIFACTS_LATEST / "quote_reference.json"
    try:
        from scripts.smc_atomic_write import atomic_write_text
        dest.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(json.dumps(payload, ensure_ascii=True), dest)
        return True
    except (OSError, TypeError):
        logger.warning("Failed to write fetched quote_reference locally", exc_info=True)
        return False


# ═══════════════════════════════════════════════════════════════════════════
# Dynamic Cooldown (Oscillation-Based) — enables high-frequency VisiData
# ═══════════════════════════════════════════════════════════════════════════

class DynamicCooldown:
    """Adaptive cooldown between A0 signals per symbol.

    Ported from IB_MON's oscillation-aware cooldown logic.  Instead of a
    fixed 10-minute gap between A0 signals, the cooldown adjusts based on:

    1. **Volume regime** — call sites map "HIGH" = per-symbol pace >3x (0.4x,
       the typical A0 case); "THIN" only under HOLIDAY_SUSPECT (suspended).
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
        # Guards _transitions / _last_a0: the near-A0 re-poller thread and the
        # main poll both mutate + read these (record_transition / check_cooldown
        # / prune_stale run cross-thread). Non-reentrant — never call compute()
        # while holding it (compute → _oscillation_factor re-acquires).
        self._lock = threading.Lock()

    def _oscillation_factor(self, symbol: str) -> float:
        """Return a multiplier ≥ 1.0 if the symbol is oscillating."""
        with self._lock:
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

        - ``"THIN"``   → 2.0x (mapped only from HOLIDAY_SUSPECT → unreachable)
        - ``"NORMAL"`` → 1.0 (includes LOW_VOLUME sessions)
        - ``"HIGH"``   → 0.4x (per-symbol pace >3x, the typical A0 case)
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
        with self._lock:
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

    def prune_stale(self, keep: set[str]) -> None:
        """Drop symbols not in *keep* (thread-safe watchlist reconciliation).

        Callers must NOT reach into ``_transitions`` / ``_last_a0`` directly —
        the near-A0 re-poller thread mutates them concurrently.
        """
        with self._lock:
            for sym in (set(self._transitions) | set(self._last_a0)) - keep:
                self._transitions.pop(sym, None)
                self._last_a0.pop(sym, None)

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
        with self._lock:
            last = self._last_a0.get(symbol, 0.0)
        if last == 0.0:
            return False, 0.0
        cd = self.compute(symbol, volume_regime, has_news_catalyst)  # takes _lock internally — do NOT call while holding it
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
        max_state_size: int = 1000,
    ):
        self._margin_pct = margin_pct
        self._min_hold = min_hold_seconds
        self._max_state_size = max_state_size
        # {symbol: {"level": "A0"|"A1", "ts": float}}
        self._state: dict[str, dict[str, Any]] = {}

    def evaluate(
        self,
        symbol: str,
        proposed_level: str,
        volume_ratio: float,
        abs_change_pct: float,
        a0_vol_threshold: float = A0_VOLUME_RATIO_MIN,
        a0_chg_threshold: float = A0_PRICE_CHANGE_PCT_MIN,
    ) -> str:
        """Return the effective signal level after hysteresis filtering.

        If the proposed level differs from the current state and the metrics
        are within the margin band AND not enough time has passed, the level
        is kept unchanged rather than allowed to flip.

        ``a0_vol_threshold`` / ``a0_chg_threshold`` are the *effective*
        (regime-adjusted) A0 thresholds. They default to the absolute constants
        for backward compatibility, but the caller passes the relaxed values in
        LOW_VOLUME / HOLIDAY_SUSPECT so the "clearly A0" margin band tracks the
        regime instead of blocking legitimate upgrades against the NORMAL bar.
        """
        now = time.monotonic()
        prev = self._state.get(symbol)

        if prev is None:
            # First time — accept whatever is proposed; evict oldest if at capacity
            if len(self._state) >= self._max_state_size:
                oldest = next(iter(self._state))
                del self._state[oldest]
            self._state[symbol] = {"level": proposed_level, "ts": now}
            return proposed_level

        if proposed_level == prev["level"]:
            return proposed_level  # no transition, nothing to gate

        # Transition requested — check if it's clearly beyond the *effective*
        # (regime-adjusted) A0 threshold, not the absolute NORMAL constant.
        a0_vol_margin = a0_vol_threshold * (1 - self._margin_pct)
        a0_chg_margin = a0_chg_threshold * (1 - self._margin_pct)

        clearly_a0 = (
            volume_ratio >= a0_vol_threshold * (1 + self._margin_pct)
            and abs_change_pct >= a0_chg_threshold * (1 + self._margin_pct)
        )
        clearly_a1 = (
            volume_ratio < a0_vol_margin
            or abs_change_pct < a0_chg_margin
        )

        if proposed_level == "A0":
            is_clear = clearly_a0
        elif proposed_level == "A1":
            is_clear = clearly_a1
        else:
            # A2 downgrade: allow unless metrics clearly support staying at
            # current level (A0).  Detection logic uses richer criteria to
            # propose A2 — hysteresis should only block if still clearly A0.
            is_clear = not clearly_a0
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
        """Record the level for a symbol without hysteresis evaluation.

        Honours ``max_state_size`` the same way :meth:`evaluate` does, so a new
        symbol at capacity evicts the oldest entry rather than growing the map
        unbounded. (Currently uncalled — this keeps the two write paths
        consistent for any future caller.)
        """
        if symbol not in self._state and len(self._state) >= self._max_state_size:
            oldest = next(iter(self._state))
            del self._state[oldest]
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
        self._last_missing_avg_warn_ts: float | None = None

    def update(self, quotes: dict[str, dict[str, Any]]) -> str:
        if not quotes:
            # An empty quote map is a transient fetch failure, NOT evidence of
            # normal volume. Resetting to NORMAL here would silently lift an
            # active HOLIDAY_SUSPECT suspension on a single bad poll — keep the
            # last known regime instead. (The distinct "quotes present but
            # avgVolume unavailable" fail-open path below is unchanged.)
            return self.regime

        thin_count = 0
        total = 0
        vol_frac = max(_expected_cumulative_volume_fraction(), 0.02)
        for _sym, q in quotes.items():
            vol = _safe_float(q.get("volume"), 0.0)
            # Only non-Databento rows may use the consolidated watchlist fallback.
            avg_vol = _safe_float(q.get("avgVolume"), 0.0)
            is_databento = str(q.get("source") or "").strip().lower().startswith("databento")
            if avg_vol <= 0 and not is_databento:
                avg_vol = self._wl_avg_volumes.get(_sym, 0.0)
            if avg_vol <= 0:
                continue   # unknown volume — exclude from both counts
            # Compare against expected intraday pace, not raw cumulative day fraction.
            vol_pace = vol / vol_frac
            total += 1
            if vol_pace < avg_vol * THIN_VOLUME_RATIO:
                thin_count += 1

        self.thin_fraction = (thin_count / total) if total > 0 else 0.0
        if total == 0 and quotes:
            now = time.monotonic()
            if self._last_missing_avg_warn_ts is None or (now - self._last_missing_avg_warn_ts) >= 300.0:
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
    return hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()[:12]


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

    Wraps ``fetch_technicals()`` (FMP-only after TradingView retirement)
    with per-symbol caching and rate-limit awareness.  Computes a weighted
    ``technical_score`` (0.0–1.0) from RSI, MACD, EMA/SMA alignment, and ADX.

    Weight allocation (inspired by IB_monitoring EWMA engine):

        RSI oversold/overbought :  40%
        MA alignment            :  25%
        MACD cross              :  15%
        ADX trend strength      :  amplifies bias ≤20% (0 if no bias)
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
                # None (skip), NOT 0.0, on a non-numeric/non-finite RSI (e.g. a
                # provider "N/A"): raw float() would raise and break the poll, and
                # 0.0 would read as deeply oversold → spurious STRONG_BUY. _r == _r
                # is the NaN test (_safe_float yields NaN for bad/non-finite input).
                _r = _safe_float(val, float("nan"))
                rsi = _r if _r == _r else None
            elif "MACD" in name and "STOCHASTIC" not in name:
                macd_signal = str(osc.get("action", "NEUTRAL")).upper()
            elif name.startswith("ADX"):
                adx = _safe_float(val, 0.0)  # not float(): non-finite ADX would collapse score to STRONG_BUY via min(nan/50,1.0)
            elif "WILLIAMS" in name or name.startswith("WILL"):
                # Same guard as RSI: bad/non-finite Williams → None (skip), not a
                # raise and not a spurious 0.0.
                _w = _safe_float(val, float("nan"))
                williams = _w if _w == _w else None

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
    level: str                        # "A0", "A1", or "A2"
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
    level_since_at: str = ""          # ISO timestamp for current A0/A1/A2 level start
    level_since_epoch: float = 0.0    # unix timestamp for current A0/A1/A2 level start
    details: dict[str, Any] = field(default_factory=dict)
    symbol_regime: str = "NEUTRAL"
    # ── News catalyst enrichment (from newsstack_fmp) ──
    news_score: float = 0.0
    news_category: str = ""
    news_headline: str = ""
    news_warn_flags: list[str] = field(default_factory=list)
    # ── Technical indicator enrichment (FMP-only) ──
    technical_score: float = 0.5      # 0.0–1.0 weighted indicator score
    technical_signal: str = "NEUTRAL" # STRONG_BUY / BUY / NEUTRAL / SELL / STRONG_SELL
    rsi: float | None = None          # RSI-14 value (None if unavailable)
    macd_signal: str = ""             # MACD action: BUY / SELL / NEUTRAL
    # ── ATR trade context (open_prep/trade_context.py) — display guidance for
    # Slack/Pine consumers, NOT order placement (C13 computes its own levels).
    trade_entry: float | None = None
    trade_stop: float | None = None
    trade_target: float | None = None
    trade_r: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def is_expired(self, now_epoch: float | None = None) -> bool:
        now = now_epoch or time.time()
        return (now - self.fired_epoch) > MAX_SIGNAL_AGE_SECONDS


class RealtimeEngine:
    """Source-pluggable realtime breakout detection engine."""

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
        # Quote-source seam (Databento signal-migration Task 1.1 introduced
        # the seam; Task 2.1 wires RT_QUOTE_SOURCE=databento through
        # _default_quote_source() -- the single factory also used by the
        # _fetch_realtime_quotes self-heal below, so the two always agree and
        # the env flag is actually honored. _databento_feed is the engine's
        # own handle on the constructed DatabentoQuoteFeed (kept separate
        # from DatabentoQuoteSource's internals, untouched by this task) so
        # start_quote_source()/stop_quote_source() know what to start/stop.
        # Both are built AFTER _load_watchlist() further down, once the
        # watchlist has a symbol list for a Databento feed to subscribe to.
        self._databento_feed: Any = None
        self._quote_source: QuoteSource | None = None
        self._active_signals: list[RealtimeSignal] = []
        self._lock = threading.Lock()  # guards _active_signals
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
        # Opt-in near-A0 fast-lane re-poller (started via start_near_a0_repoller)
        self._near_a0_repoller: NearA0Repoller | None = None

        # VisiData snapshot: latest per-symbol row data
        self._vd_rows: dict[str, dict[str, Any]] = {}
        self._vd_last_change_epoch: dict[str, float] = {}
        self._poll_seq: int = 0

        # Cached avg_volume & earnings (fetched once per watchlist load)
        self._avg_vol_cache: dict[str, float] = {}
        self._earnings_today_cache: dict[str, dict[str, Any]] = {}
        self._new_entrant_set: set[str] = set()

        # #12 Technical indicator scorer (FMP-only)
        self._technical_scorer = TechnicalScorer()

        # #11 Dirty flag — {symbol: quote_hash}
        self._quote_hashes: dict[str, str] = {}

        # Timing — last poll duration for adaptive sleep
        self.last_poll_duration: float = 0.0

        # Semantic readiness gauges for Grafana alerts and /readyz.
        # These describe pipeline health, not the presence of A0/A1 signals.
        self.watchlist_load_success: float = 0.0
        self.watchlist_loaded_at: float = 0.0
        self.watchlist_symbols: int = 0
        self.open_prep_snapshot_loaded: float = 0.0
        self.open_prep_snapshot_age_seconds: float = 0.0
        self.last_poll_attempt_epoch: float = 0.0
        self.last_poll_success_epoch: float = 0.0
        self.last_poll_interval_actual_seconds: float = 0.0
        self._poll_phase_seconds: dict[str, float] = {}
        self._last_data_epoch: float = 0.0  # stamped ONLY on a non-empty fetch (real data) — drives the data_stale gauge (vs last_poll_success_epoch = loop-liveness)
        self._in_market_hours: bool = False  # cached in poll_once so the /metrics renderer never calls the (raising) market-hours probe
        self._market_session_name: str = "closed"
        self._quotes_polled: bool = False
        # Extended-hours signals stay fail-closed until the dedicated FMP
        # aftermarket endpoints have been validated in shadow mode.  In
        # particular, do not let an environment override route pre/post-market
        # decisions through the regular-session stable batch quote endpoint.
        self.extended_signals_mode: str = "off"
        self.extended_shadow_enabled: bool = os.getenv(
            "RT_EXTENDED_SHADOW_ENABLED", "0"
        ).strip().lower() in {"1", "true", "yes", "on"}
        self._extended_shadow: dict[str, Any] = {
            "last_poll_epoch": 0.0,
            "session": "closed",
            "symbols": 0,
            "regular_rows": 0,
            "quote_rows": 0,
            "trade_rows": 0,
            "fresh_regular_rows": 0,
            "fresh_quote_rows": 0,
            "fresh_trade_rows": 0,
            "overlap_rows": 0,
            "mean_reference_delta_bps": 0.0,
        }
        self._postmarket_baseline_date: str = ""
        self._postmarket_close_volume: dict[str, float] = {}
        self._postmarket_adapter_stats: dict[str, int] = {}
        self._postmarket_adapter_quotes: dict[str, dict[str, Any]] = {}
        self.last_poll_duration_seconds: float = 0.0

        self._load_watchlist()
        try:
            self._quote_source = self._default_quote_source()
        except Exception as exc:
            logger.warning(
                "Failed to build quote source (RT_QUOTE_SOURCE=%s): %s -- "
                "will retry via the _fetch_realtime_quotes self-heal once "
                "the watchlist is non-empty.",
                os.environ.get("RT_QUOTE_SOURCE", "databento"), exc, exc_info=True,
            )
            self._quote_source = None
        self._restore_signals_from_disk()

    # ------------------------------------------------------------------
    # Restore non-expired signals from previous run (dedup across restarts)
    # ------------------------------------------------------------------
    def _restore_signals_from_disk(self) -> None:
        """Load previously persisted signals to avoid re-firing on restart."""
        try:
            data = self.load_signals_from_disk()
            baseline_date = str(data.get("postmarket_baseline_date") or "")
            raw_baseline = data.get("postmarket_close_volume") or {}
            if isinstance(raw_baseline, dict):
                restored_baseline = {
                    str(symbol).strip().upper(): _safe_float(volume, 0.0)
                    for symbol, volume in raw_baseline.items()
                    if str(symbol).strip() and _safe_float(volume, 0.0) > 0
                }
                self._postmarket_baseline_date = baseline_date
                self._postmarket_close_volume = restored_baseline
            from .atr_quality import actionable_atr_pct
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
                    atr_pct=actionable_atr_pct(raw.get("atr_pct")) or 0.0,
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
        snapshot_url = _open_prep_snapshot_url()
        data: dict[str, Any] | None = None
        if snapshot_url:
            data = _fetch_json_url(snapshot_url)
            if data is None:
                logger.warning(
                    "OPEN_PREP_SNAPSHOT_URL fetch failed — "
                    "falling back to local snapshot",
                )
        if data is None:
            run_path = LATEST_RUN_PATH if LATEST_RUN_PATH.exists() else _LEGACY_RUN_PATH
            if not run_path.exists():
                logger.warning("No latest_open_prep_run.json found — watchlist empty")
                return
            try:
                with open(run_path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception as exc:
                logger.warning("Failed to load watchlist: %s", exc, exc_info=True)
                return
        try:
            # -- Build full universe: ranked + overflow -------------------
            ranked_v2 = _active_snapshot_rows(data, "ranked_v2")
            seen: set[str] = set()
            full: list[dict[str, Any]] = []
            for r in ranked_v2:
                sym = str(r.get("symbol", "")).strip().upper()
                if sym and sym not in seen:
                    seen.add(sym)
                    full.append(r)

            # Recover scored-but-below-cutoff entries from filtered_out_v2
            for r in _active_snapshot_rows(data, "filtered_out_v2"):
                reasons = r.get("filter_reasons") or []
                if "below_top_n_cutoff" not in reasons:
                    continue  # truly filtered out — skip
                sym = str(r.get("symbol", "")).strip().upper()
                if sym and sym not in seen:
                    seen.add(sym)
                    full.append(r)

            # Also include any symbols from enriched_quotes not yet covered
            for q in _active_snapshot_rows(data, "enriched_quotes"):
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

            self._watchlist = full or self._watchlist  # degraded-empty snapshot: keep last-good (fresh boot stays [])

            # Semantic readiness: snapshot/watchlist state
            now = time.time()
            self.watchlist_symbols = len(self._watchlist)
            self.watchlist_load_success = 1.0 if self._watchlist else 0.0
            self.watchlist_loaded_at = now
            self.open_prep_snapshot_loaded = 1.0 if data else 0.0
            self.open_prep_snapshot_age_seconds = max(0.0, now - _extract_snapshot_epoch(data))

            # 🆕 aus dem Diff — first_run trägt keine Vergleichsinfo (Sweep F3)
            diff = data.get("diff") or {}
            self._new_entrant_set = set() if diff.get("first_run") else {
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

        Missing average-volume values use bounded per-symbol profile lookups.
        The realtime producer must never scan the provider-wide profile-bulk
        dataset merely because one or two watchlist symbols are incomplete.
        Negative results are cached so an unsupported symbol cannot trigger a
        remote retry on every five-minute watchlist reload.

        The batch-quote endpoint omits avgVolume.  Without it the volume
        ratio is meaningless (everything looks like A0).  We fetch company
        profiles at most once per symbol/day and cache the value.  The earnings
        calendar is likewise fetched at most once per Eastern trading date.
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

        # symbol → first matching watchlist entry (first-wins, mirrors the
        # prior linear `break`-on-first scans). Built once so the enrichment
        # loops are O(1) lookups instead of O(n²) rescans (audit P3 MED).
        wl_by_sym: dict[str, dict] = {}
        for _w in self._watchlist:
            _k = str(_w.get("symbol", "")).strip().upper()
            if _k and _k not in wl_by_sym:
                wl_by_sym[_k] = _w

        # Identify symbols that still need avgVolume enrichment.  A failed or
        # unsupported profile is retried only after its negative-cache TTL.
        now_epoch = time.time()
        retry_after: dict[str, float] = getattr(self, "_avg_vol_retry_after", {})
        self._avg_vol_retry_after = retry_after
        need_avg_vol: set[str] = set()
        for sym in symbols:
            if sym in self._avg_vol_cache:
                continue  # already have it from a previous cycle
            _entry = wl_by_sym.get(sym)
            wl_avg = _safe_float(_entry.get("avg_volume"), 0.0) if _entry is not None else 0.0
            if wl_avg < 1000 and retry_after.get(sym, 0.0) <= now_epoch:
                need_avg_vol.add(sym)

        if need_avg_vol:
            enriched_count = 0
            attempted_count = 0
            # Bounded targeted lookups: the watchlist snapshot is the primary
            # source, so unresolved symbols fail closed in _detect_signal().
            for sym in sorted(need_avg_vol)[:50]:
                attempted_count += 1
                try:
                    profile = client.get_company_profile(sym)
                    avg_vol = _safe_float(
                        profile.get("averageVolume") or profile.get("volAvg"), 0.0
                    )
                    if avg_vol >= 1000:
                        self._avg_vol_cache[sym] = avg_vol
                        retry_after.pop(sym, None)
                        _entry = wl_by_sym.get(sym)
                        if _entry is not None and _safe_float(_entry.get("avg_volume"), 0.0) < 1000:
                            _entry["avg_volume"] = avg_vol
                        enriched_count += 1
                    else:
                        retry_after[sym] = now_epoch + 86_400.0
                except Exception as exc:
                    retry_after[sym] = now_epoch + 900.0
                    logger.debug("Profile fetch failed for %s: %s", sym, exc)
                time.sleep(0.15)  # throttle the bounded per-symbol fallback
            logger.info(
                "Targeted profile enriched %d/%d attempted symbols with avgVolume",
                enriched_count, attempted_count,
            )

        # Apply cached avg_volume to any watchlist entries still missing it
        for w in self._watchlist:
            sym = str(w.get("symbol", "")).strip().upper()
            if _safe_float(w.get("avg_volume"), 0.0) < 1000 and sym in self._avg_vol_cache:
                w["avg_volume"] = self._avg_vol_cache[sym]

        # ── Earnings calendar for today (one remote fetch per ET date) ──
        try:
            from datetime import datetime as _datetime
            from zoneinfo import ZoneInfo as _ZoneInfo
            today = _datetime.now(_ZoneInfo("America/New_York")).date()
            cached_date = getattr(self, "_earnings_cache_date", None)
            earnings_by_symbol: dict[str, dict[str, Any]] = getattr(
                self, "_earnings_day_map", {},
            )
            if cached_date != today:
                earnings = client.get_earnings_calendar(today, today)
                earnings_by_symbol = {
                    str(item.get("symbol") or "").strip().upper(): item
                    for item in earnings
                    if isinstance(item, dict) and str(item.get("symbol") or "").strip()
                }
                self._earnings_cache_date = today
                self._earnings_day_map = earnings_by_symbol
            self._earnings_today_cache = {
                sym: item for sym, item in earnings_by_symbol.items() if sym in sym_set
            }
            for sym, item in self._earnings_today_cache.items():
                _entry = wl_by_sym.get(sym)
                if _entry is not None:
                    _entry["earnings_today"] = True
                    raw_time = str(item.get("time") or item.get("releaseTime") or "").strip().lower()
                    _entry["earnings_timing"] = raw_time or None
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
            self._vd_last_change_epoch,
            self._avg_vol_cache,
        ):
            stale = set(d) - wl_syms
            for k in stale:
                del d[k]
        # DynamicCooldown's dicts are mutated by the near-A0 re-poller thread, so
        # prune them under its lock rather than reaching in directly.
        self._dynamic_cooldown.prune_stale(wl_syms)
        # Clear technical indicator cache for removed symbols
        self._technical_scorer.clear()

        # A rotation that drops a symbol must retract its signal too — expiry
        # alone keeps it published for up to MAX_SIGNAL_AGE_SECONDS. Skipped on
        # an empty reload so a degraded snapshot cannot clear the active set.
        if wl_syms:
            with self._lock:
                self._active_signals = [
                    s for s in self._active_signals
                    if str(getattr(s, "symbol", "")).strip().upper() in wl_syms
                ]

        # Databento feed lifecycle on watchlist rotation (no-op for the FMP
        # default). Both calls are duck-typed and internally fail-soft, so they
        # never touch the FMP path and never break the reload cycle:
        #  (1) resubscribe the live feed to the new symbol set — otherwise the
        #      feed keeps yesterday's subscription and never emits bars for
        #      symbols added by the rotation (they'd fail-closed omit forever);
        #  (2) reload the daily quote-reference so a new session's
        #      previous_close/ADV replaces yesterday's (else changesPercentage
        #      skews for the life of the process).
        feed = getattr(self, "_databento_feed", None)
        if feed is not None:
            feed.update_symbols(sorted(wl_syms))
            _refresh_quote_reference_from_url()  # pull today's prev_close/ADV before reload_reference
        reload_reference = getattr(getattr(self, "_quote_source", None), "reload_reference", None)
        if callable(reload_reference):
            reload_reference()
        elif isinstance(self._quote_source, FMPQuoteSource) and _selected_quote_source() == "databento":
            recovered_source = self._default_quote_source()
            if isinstance(recovered_source, DatabentoQuoteSource):
                self._quote_source = recovered_source
                self.start_quote_source()

    def start_async_newsstack(self, poll_interval: float = 15.0) -> None:
        """Start the background newsstack poller (call once at startup)."""
        self._async_newsstack = AsyncNewsstackPoller(poll_interval=poll_interval)
        self._async_newsstack.start()

    def start_near_a0_repoller(self, interval: float) -> None:
        """Start the opt-in near-A0 fast-lane re-poller (call once at startup)."""
        self._near_a0_repoller = NearA0Repoller(self, interval)
        self._near_a0_repoller.start()

    # ------------------------------------------------------------------
    # Fetch current quotes for watched symbols
    # ------------------------------------------------------------------
    def _fetch_realtime_quotes(self) -> dict[str, dict[str, Any]]:
        """Fetch current quotes for all watched symbols via the active source.

        Databento is primary. Its source reads the live cache; explicit or
        fallback FMP mode retains URL-safe batch chunking internally.
        The returned quote-row contract remains provider-neutral.
        """
        if _client_disabled_for_selected_quote_source(self):
            return {}
        if not self._watchlist:
            return {}
        symbols = [str(r.get("symbol", "")).strip().upper() for r in self._watchlist if r.get("symbol")]
        if not symbols:
            return {}

        # Quote-source seam (Databento signal-migration Task 1.1 introduced
        # this self-heal for engines built via RealtimeEngine.__new__(),
        # bypassing __init__, e.g. in some tests. Task 2.1: reuse
        # _default_quote_source() -- the SAME factory __init__ uses -- so a
        # None _quote_source under RT_QUOTE_SOURCE=databento rebuilds a
        # DatabentoQuoteSource here too, instead of always silently falling
        # back to FMP regardless of the flag (the Task 1.1 carry-forward
        # this task fixes).
        quote_source = getattr(self, "_quote_source", None)
        if quote_source is None:
            quote_source = self._default_quote_source()
            self._quote_source = quote_source
            # A self-healed DatabentoQuoteFeed is freshly constructed, not
            # started -- main() only calls start_quote_source() once, before
            # the poll loop begins, so a rebuild here would otherwise leave
            # the feed's threads dead forever (cache stays empty -> every
            # symbol is fail-closed omitted). start() is idempotent (guards
            # on an already-alive thread), so this is always safe, including
            # when quote_source is FMP (no-op: _databento_feed stays None).
            self.start_quote_source()

        quotes: dict[str, dict[str, Any]] = {}
        for q in quote_source.fetch(symbols, "regular"):
            sym = str(q.get("symbol", "")).strip().upper()
            if sym:
                quotes[sym] = q
        return quotes

    # ------------------------------------------------------------------
    # Quote-source factory + Databento feed lifecycle (Task 2.1)
    # ------------------------------------------------------------------
    def _default_quote_source(self) -> QuoteSource:
        """Build the engine's quote source per ``RT_QUOTE_SOURCE``.

        Databento is the default; FMP is only an explicit rollback or an
        observable fallback when Databento cannot be constructed. This single
        factory is shared by ``__init__`` and the ``_fetch_realtime_quotes``
        self-heal so both paths make the same source decision.
        """
        if _selected_quote_source() == "databento":
            try:
                source = self._build_databento_quote_source()
            except Exception as exc:
                logger.warning(
                    "Databento quote source unavailable; falling back to FMP (%s)",
                    type(exc).__name__,
                    exc_info=True,
                )
                self._databento_feed = None
                self._quote_source_fallback_reason = type(exc).__name__
                return FMPQuoteSource(lambda: self.client)
            self._quote_source_fallback_reason = ""
            return source
        self._quote_source_fallback_reason = "explicit_fmp"
        return FMPQuoteSource(lambda: self.client)

    def _build_databento_quote_source(self) -> DatabentoQuoteSource:
        """Construct a Databento-backed ``QuoteSource`` over the current
        watchlist's symbols: a ``DatabentoQuoteFeed`` (Task 1.2, NOT started
        here -- see ``start_quote_source()``) plus the daily
        ``QuoteReference`` (Task 0.2) for ``previousClose``/``avgVolume``.

        Local imports (``databento``, ``DatabentoQuoteFeed``,
        ``QuoteReference``) keep explicit FMP rollback and Databento-startup
        fallback paths independent from the live-feed implementation.
        """
        import databento as db

        from .databento_quote_feed import DatabentoQuoteFeed, resolve_current_symbol_support
        from .quote_reference import QuoteReference

        symbols = [
            str(r.get("symbol", "")).strip().upper()
            for r in self._watchlist if r.get("symbol")
        ]
        api_key = os.environ.get("DATABENTO_API_KEY", "")
        if not api_key.strip():
            raise RuntimeError("DATABENTO_API_KEY is required when RT_QUOTE_SOURCE=databento")

        # Today's 09:30 ET open in UTC, bounded to now; fresh boots replay the
        # session so far without ever requesting a future start.
        from zoneinfo import ZoneInfo

        now = datetime.now(UTC)
        now_et = now.astimezone(ZoneInfo("America/New_York"))
        session_open_et = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        replay_start = min(now, session_open_et.astimezone(UTC))

        feed = DatabentoQuoteFeed(
            symbols,
            lambda: db.Live(key=api_key),
            replay_start=replay_start,
            symbol_support_resolver=lambda provider_symbols: resolve_current_symbol_support(
                api_key,
                provider_symbols,
                session_date=now_et.date(),
            ),
        )
        _refresh_quote_reference_from_url()  # fetch today's reference (no-op if URL unset / on error -> last-good)
        reference = QuoteReference.load()
        if len(reference) == 0:
            raise RuntimeError("Databento quote reference is empty")
        self._databento_feed = feed
        return DatabentoQuoteSource(feed, reference)

    def start_quote_source(self) -> None:
        """Start the Databento feed's background threads (call once, at
        run-loop start -- see ``main()`` -- and again from the
        ``_fetch_realtime_quotes`` self-heal after a rebuild, since that
        rebuild produces a freshly-constructed, unstarted feed). No-op for
        explicit FMP mode: no feed is constructed, so there is nothing to
        start. ``getattr`` (not ``self._databento_feed`` directly) so this
        stays safe on engines built via ``RealtimeEngine.__new__()``
        (bypassing ``__init__``, e.g. in some tests) that never set the
        attribute at all."""
        feed = getattr(self, "_databento_feed", None)
        if feed is not None:
            feed.start()

    def stop_quote_source(self) -> None:
        """Stop the Databento feed's background threads (call on shutdown
        -- see ``main()``). No-op for explicit FMP mode. Same ``getattr``
        safety as ``start_quote_source()``."""
        feed = getattr(self, "_databento_feed", None)
        if feed is not None:
            feed.stop()

    def _capture_regular_close_baseline(self, quotes: dict[str, dict[str, Any]]) -> None:
        """Retain the latest regular-session cumulative volume for postmarket."""

        from zoneinfo import ZoneInfo

        session_date = (now_et := datetime.now(ZoneInfo("America/New_York"))).date().isoformat()
        captured = {
            symbol: _safe_float(row.get("volume"), 0.0)
            for symbol, row in quotes.items()
            if _safe_float(row.get("volume"), 0.0) > 0
        }
        if captured and now_et.hour * 60 + now_et.minute >= regular_session_close_minutes(now_et.date()) - 5:
            self._postmarket_baseline_date = session_date
            self._postmarket_close_volume = captured

    def _poll_extended_shadow(self, market_session: str) -> None:
        """Compare regular and dedicated extended-hours feeds without signaling."""

        if not self.extended_shadow_enabled or market_session not in {"premarket", "postmarket"}:
            return
        symbols = [
            str(row.get("symbol") or "").strip().upper()
            for row in self._watchlist
            if str(row.get("symbol") or "").strip()
        ]
        if not symbols:
            return

        regular = self.client.get_stable_batch_quotes(symbols)
        quote_rows = self.client.get_stable_batch_aftermarket_quotes(symbols)
        trade_rows = self.client.get_stable_batch_aftermarket_trades(symbols)
        now_epoch = time.time()

        if market_session == "postmarket":
            from zoneinfo import ZoneInfo

            from open_prep.postmarket_quotes import build_postmarket_quotes

            current_session_date = datetime.now(
                ZoneInfo("America/New_York")
            ).date().isoformat()
            adapted = build_postmarket_quotes(
                reference_rows=regular,
                quote_rows=quote_rows,
                trade_rows=trade_rows,
                close_volume_by_symbol=self._postmarket_close_volume,
                baseline_session_date=self._postmarket_baseline_date,
                current_session_date=current_session_date,
                now_epoch=now_epoch,
            )
            self._postmarket_adapter_quotes = adapted.quotes
            self._postmarket_adapter_stats = adapted.stats

        def _timestamp_epoch(row: dict[str, Any]) -> float:
            raw = _safe_float(row.get("timestamp"), 0.0)
            return raw / 1000.0 if raw >= 1_000_000_000_000 else raw

        def _is_fresh(row: dict[str, Any]) -> bool:
            age = now_epoch - _timestamp_epoch(row)
            return -30.0 <= age <= 300.0

        regular_by = {str(row.get("symbol") or "").upper(): row for row in regular}
        quote_by = {str(row.get("symbol") or "").upper(): row for row in quote_rows}
        trade_by = {str(row.get("symbol") or "").upper(): row for row in trade_rows}
        deltas: list[float] = []
        for symbol in sorted(set(regular_by) & set(quote_by) & set(trade_by)):
            ref_price = _safe_float(regular_by[symbol].get("price"), 0.0)
            bid = _safe_float(quote_by[symbol].get("bidPrice"), 0.0)
            ask = _safe_float(quote_by[symbol].get("askPrice"), 0.0)
            trade_price = _safe_float(trade_by[symbol].get("price"), 0.0)
            extended_price = trade_price or ((bid + ask) / 2.0 if bid > 0 and ask > 0 else 0.0)
            if ref_price > 0 and extended_price > 0:
                deltas.append(abs(ref_price - extended_price) / extended_price * 10_000.0)

        self._extended_shadow = {
            "last_poll_epoch": now_epoch,
            "session": market_session,
            "symbols": len(set(symbols)),
            "regular_rows": len(regular),
            "quote_rows": len(quote_rows),
            "trade_rows": len(trade_rows),
            "fresh_regular_rows": sum(1 for row in regular if _is_fresh(row)),
            "fresh_quote_rows": sum(1 for row in quote_rows if _is_fresh(row)),
            "fresh_trade_rows": sum(1 for row in trade_rows if _is_fresh(row)),
            "overlap_rows": len(deltas),
            "mean_reference_delta_bps": sum(deltas) / len(deltas) if deltas else 0.0,
        }

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
        expected_volume_fraction: float | None = None,
    ) -> RealtimeSignal | None:
        """Analyze a single symbol's current quote for breakout signals."""

        # --- Market-hours gate ---
        # Only detect signals during extended US trading hours (Mon–Fri, 4:00–20:00 ET).
        if not _is_within_market_hours():
            return None

        price = _safe_float(quote.get("price") or quote.get("lastPrice"), 0.0)
        prev_close = _safe_float(quote.get("previousClose"), 0.0)
        raw_volume_value = quote.get("volume")
        volume = _safe_float(raw_volume_value, 0.0)
        avg_volume = _safe_float(
            quote.get("avgVolume") or _watchlist_average_volume(watchlist_entry), 0.0
        )
        if raw_volume_value is not None:
            try:
                parsed_volume = float(raw_volume_value)
            except (TypeError, ValueError, OverflowError):
                parsed_volume = float("nan")
            if parsed_volume < 0 or parsed_volume != parsed_volume or parsed_volume in (
                float("inf"), float("-inf"),
            ):
                logger.debug(
                    "Skipping %s: invalid cumulative volume=%r", symbol, raw_volume_value,
                )
                return None
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

        # ── Time-of-day volume normalization ─────────────────────
        # Raw volume_ratio uses cumulative daily volume vs daily average.
        # At 10:00 AM, even an unusually active stock only shows 0.5x
        # because most of the day hasn't happened yet.  Normalize by
        # expected cumulative fraction so we measure *pace above average*
        # rather than *cumulative total*.
        raw_volume_ratio, vol_frac, volume_ratio = _volume_semantics(
            volume,
            avg_volume,
            expected_volume_fraction
            if expected_volume_fraction is not None
            else quote.get("expected_volume_fraction"),
        )

        from .atr_quality import actionable_atr_pct
        atr_pct = actionable_atr_pct(
            watchlist_entry.get("atr_pct_computed") or watchlist_entry.get("atr_pct")
        ) or 0.0
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

        # Provider-neutral, deterministic core decision. Stateful modifiers
        # below retain ownership of hysteresis/cooldown and append reason codes.
        from open_prep.a0_contract import (
            A0ReasonCode,
            A0ThresholdContext,
            build_market_snapshot,
            decide_core_level,
        )
        observed_at = time.time()
        market_snapshot = build_market_snapshot(
            symbol=symbol,
            price=price,
            prev_close=prev_close,
            change_pct=change_pct,
            raw_daily_volume_ratio=raw_volume_ratio,
            expected_volume_fraction=vol_frac,
            normalized_volume_pace=volume_ratio,
            source=str(quote.get("source") or "fmp"),
            raw_ts_event=quote.get("timestamp"),
            raw_ts_recv=quote.get("received_at"),
            observed_at=observed_at,
        )
        core_decision = decide_core_level(
            market_snapshot,
            A0ThresholdContext(
                a0_volume=eff_a0_vol,
                a1_volume=eff_a1_vol,
                a2_volume=eff_a2_vol,
                a0_price=eff_a0_chg,
                a1_price=eff_a1_chg,
                a2_price=eff_a2_chg,
            ),
        )
        level = core_decision.final_level
        reason_codes = list(core_decision.reason_codes)

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
        # Downgrade (A0→A1) or warn-and-pass LONG signals on negative intraday momentum
        # (price falling from previous poll → still accelerating down).
        falling_knife_warned = False
        if direction == "LONG" and prev_price is not None and price < prev_price:
            # Price dropped since last poll — momentum is negative
            if level == "A0":
                level = "A1"  # downgrade — do not fire A0 into a falling knife
                reason_codes.append(A0ReasonCode.FALLING_KNIFE_DOWNGRADE)
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
                reason_codes.append(A0ReasonCode.PDH_BREAKOUT_UPGRADE)
        if pdl > 0 and price < pdl and prev_price is not None and prev_price >= pdl:
            pattern = "pdl_breakdown"
            direction = "SHORT"
            if level == "A1":
                level = "A0"
                reason_codes.append(A0ReasonCode.PDL_BREAKDOWN_UPGRADE)

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
                        reason_codes.append(A0ReasonCode.STALE_VELOCITY_DOWNGRADE)
                        logger.debug(
                            "Stale velocity: %s A0→A1 (vel=%.3f%% < %.3f%%)",
                            symbol, velocity_pct, STALE_VELOCITY_PCT,
                        )
                    elif level == "A1":
                        level = "A2"
                        reason_codes.append(A0ReasonCode.STALE_VELOCITY_DOWNGRADE)
                        logger.debug(
                            "Stale velocity: %s A1→A2 (vel=%.3f%%)",
                            symbol, velocity_pct,
                        )

        # ── #1  Gate hysteresis — prevent A0↔A1 flapping ───────────
        # Pass the regime-adjusted A0 thresholds so the "clearly A0" band tracks
        # the effective bar (e.g. relaxed in LOW_VOLUME), not the NORMAL constant.
        pre_hysteresis_level = level
        level = self._hysteresis.evaluate(
            symbol, level, volume_ratio, abs_change,
            a0_vol_threshold=eff_a0_vol, a0_chg_threshold=eff_a0_chg,
        )
        if level != pre_hysteresis_level:
            reason_codes.append(A0ReasonCode.HYSTERESIS_ADJUSTMENT)

        # ── #12 Technical indicator confirmation/boost/penalty ───────
        tech_data = self._technical_scorer.get_technical_data(symbol, "1D")
        tech_score = tech_data.get("technical_score", 0.5)
        tech_signal = tech_data.get("technical_signal", "NEUTRAL")
        tech_rsi = tech_data.get("rsi")
        tech_macd = tech_data.get("macd_signal") or ""

        if tech_rsi is not None and level:
            if direction == "LONG":
                # RSI oversold boost — upgrade A1→A0, A2→A1
                if tech_rsi < 30 and level == "A1":
                    level = "A0"
                    reason_codes.append(A0ReasonCode.RSI_DIRECTIONAL_UPGRADE)
                    logger.debug(
                        "%s RSI %.1f < 30 oversold — upgrading A1→A0", symbol, tech_rsi,
                    )
                elif tech_rsi < 30 and level == "A2":
                    level = "A1"
                    reason_codes.append(A0ReasonCode.RSI_DIRECTIONAL_UPGRADE)
                # RSI overbought penalty — downgrade A0→A1
                elif tech_rsi > 70 and level == "A0":
                    level = "A1"
                    reason_codes.append(A0ReasonCode.RSI_CONTRA_DOWNGRADE)
                    logger.debug(
                        "%s RSI %.1f > 70 overbought — downgrade A0→A1", symbol, tech_rsi,
                    )
            elif direction == "SHORT":
                # RSI overbought boost for shorts
                if tech_rsi > 70 and level == "A1":
                    level = "A0"
                    reason_codes.append(A0ReasonCode.RSI_DIRECTIONAL_UPGRADE)
                    logger.debug(
                        "%s RSI %.1f > 70 overbought — SHORT upgrade A1→A0", symbol, tech_rsi,
                    )
                elif (tech_rsi > 70 and level == "A2") or (tech_rsi < 30 and level == "A0"):
                    level = "A1"
                    reason_codes.append(
                        A0ReasonCode.RSI_DIRECTIONAL_UPGRADE
                        if tech_rsi > 70
                        else A0ReasonCode.RSI_CONTRA_DOWNGRADE
                    )

        # Technical consensus confirmation (non-RSI)
        if level == "A0" and tech_signal in ("STRONG_SELL",) and direction == "LONG":
            level = "A1"
            reason_codes.append(A0ReasonCode.TECHNICAL_CONTRA_DOWNGRADE)
            logger.debug(
                "%s STRONG_SELL technicals — blocking A0 LONG", symbol,
            )
        elif level == "A0" and tech_signal in ("STRONG_BUY",) and direction == "SHORT":
            level = "A1"
            reason_codes.append(A0ReasonCode.TECHNICAL_CONTRA_DOWNGRADE)
            logger.debug(
                "%s STRONG_BUY technicals — blocking A0 SHORT", symbol,
            )

        # Boost: strong tech alignment can raise A1→A0 for high-conviction
        if (level == "A1"
                and ((direction == "LONG" and tech_score >= 0.75 and tech_signal in ("STRONG_BUY", "BUY"))
                     or (direction == "SHORT" and tech_score <= 0.25 and tech_signal in ("STRONG_SELL", "SELL")))
                and volume_ratio >= A1_VOLUME_RATIO_MIN * 1.5):
            level = "A0"
            reason_codes.append(A0ReasonCode.TECHNICAL_ALIGNMENT_UPGRADE)
            logger.debug(
                "%s tech_score=%.3f + aligned tech_signal=%s — upgrading A1→A0",
                symbol, tech_score, tech_signal,
            )

        # ── #7  Final dynamic cooldown gate (after ALL upgrades) ────
        # Authoritative cooldown check for the DETECTION paths (base
        # thresholds, PDH/PDL breakout, technicals, RSI boost). The
        # news-catalyst A1/A2->A0 upgrade in poll_once runs its own
        # check_cooldown before promoting — same gate, second call site.
        _vol_regime = self._volume_regime.regime if hasattr(self._volume_regime, "regime") else "NORMAL"
        _cd_regime = "THIN" if _vol_regime == "HOLIDAY_SUSPECT" else (
            "HIGH" if volume_ratio > A0_VOLUME_RATIO_MIN else "NORMAL"
        )
        _has_news = bool(_safe_float(watchlist_entry.get("news_catalyst_score"), 0.0) > 0.3)

        if level == "A0":
            is_active, remaining = self._dynamic_cooldown.check_cooldown(
                symbol, volume_regime=_cd_regime, has_news_catalyst=_has_news,
            )
            if is_active:
                level = "A1"  # cooldown active — downgrade to A1
                reason_codes.append(A0ReasonCode.COOLDOWN_DOWNGRADE)
                logger.debug(
                    "Dynamic cooldown active for %s (%.0fs remaining, regime=%s)",
                    symbol, remaining, _cd_regime,
                )
            else:
                # Require momentum confirmation for A0
                if prev_price is not None and direction == "LONG" and price <= prev_price:
                    level = "A1"  # momentum not confirming — downgrade A0→A1 (this block runs only when level=="A0")
                    reason_codes.append(A0ReasonCode.MOMENTUM_NOT_CONFIRMED)
                elif prev_price is not None and direction == "SHORT" and price >= prev_price:
                    level = "A1"
                    reason_codes.append(A0ReasonCode.MOMENTUM_NOT_CONFIRMED)
                else:
                    self._dynamic_cooldown.record_transition(symbol, direction)

        final_decision = core_decision.with_final_level(level, reason_codes)
        now_ts = final_decision.decision_at
        now_iso = datetime.fromtimestamp(now_ts, UTC).isoformat()
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
                "signal_schema_version": 2,
                "raw_daily_volume_ratio": round(raw_volume_ratio, 6),
                "expected_volume_fraction": round(vol_frac, 6),
                "normalized_volume_pace": round(volume_ratio, 6),
                "effective_a0_volume_threshold": round(eff_a0_vol, 6),
                "effective_a0_price_threshold": round(eff_a0_chg, 6),
                **final_decision.to_details(),
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
    def _mark_poll_success(self, poll_start: float) -> None:
        """Track poll duration and mark the poll as successfully completed."""
        self.last_poll_duration = time.monotonic() - poll_start
        self.last_poll_success_epoch = time.time()
        self.last_poll_duration_seconds = self.last_poll_duration

    _LEVEL_RANK: ClassVar[dict[str, int]] = {"A0": 0, "A1": 1, "A2": 2}

    def _reconcile_new_signal(
        self, sym: str, signal: RealtimeSignal, new_signals: list,
    ) -> None:
        """Merge a freshly-detected signal against the active set for *sym*.

        Lifecycle rules (mutates ``self._active_signals`` under the lock and
        appends the kept signal to ``new_signals``):

        - **Level upgrade** (A2→A1→A0, lower rank): replace the active signal.
        - **Direction flip** (same/higher rank but opposite direction): replace.
        - **Same/lower level, same direction**: dedupe (skip — no re-fire).
        - **No active signal** for the symbol: append.
        """
        with self._lock:
            existing = [
                s for s in self._active_signals
                if s.symbol == sym and not s.is_expired()
            ]
            if existing:
                latest = existing[-1]
                new_rank = self._LEVEL_RANK.get(signal.level, 3)
                old_rank = self._LEVEL_RANK.get(latest.level, 3)
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
        poll_attempt_epoch = time.time()
        if self.last_poll_attempt_epoch > 0:
            self.last_poll_interval_actual_seconds = max(
                0.0, poll_attempt_epoch - self.last_poll_attempt_epoch,
            )
        self.last_poll_attempt_epoch = poll_attempt_epoch

        # ── Session-boundary detection: clear stale _last_prices ──
        # When the engine transitions from outside→inside market hours,
        # yesterday's prices would cause false breakout/falling-knife
        # signals on the first poll cycle of the new session.
        market_session = _market_session()
        self._market_session_name = market_session
        quotes_expected = market_session == "regular"
        self._in_market_hours = quotes_expected  # data-stale applies only when this deployment expects quotes
        self._quotes_polled = False
        if market_session == "closed":
            self._was_outside_market = True
        elif self._was_outside_market:
            n_cleared = len(self._last_prices)
            self._last_prices.clear()
            self._price_history.clear()
            self._quote_hashes.clear()
            # NOTE: _avg_vol_cache is NOT cleared here — reload_watchlist()
            # prunes symbols no longer on the watchlist, keeping valid
            # avg-volume data available on the first in-session poll cycle.
            self._earnings_today_cache.clear()
            self._was_outside_market = False
            logger.info("Session boundary — cleared stale _last_prices (%d symbols)", n_cleared)
            # Rebuild watchlist enrichment immediately so avg_volume fallback is
            # available on the first in-session poll cycle.
            self.reload_watchlist()

        if _client_disabled_for_selected_quote_source(self):
            # Persist empty signals with disabled reason so UIs stay green
            with self._lock:
                self._active_signals.clear()
            self._save_signals(disabled_reason=self._client_disabled_reason)
            self._mark_poll_success(poll_start)
            return []

        # ── Newsstack: prefer async poller, fall back to synchronous ──
        phase_started = time.monotonic()
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
        self._poll_phase_seconds["news_context"] = time.monotonic() - phase_started

        new_signals: list[RealtimeSignal] = []

        if not quotes_expected:
            # Closed or deliberately disabled extended-hours mode: keep the
            # producer heartbeat alive, but never fetch quotes that cannot
            # contribute a published signal.  Expiry still advances by wall
            # clock so the snapshot cannot retain an overnight stale signal.
            self._poll_extended_shadow(market_session)
            now_epoch = time.time()
            with self._lock:
                for signal in self._active_signals:
                    signal.freshness = adaptive_freshness_decay(
                        now_epoch - signal.fired_epoch,
                        atr_pct=signal.atr_pct if signal.atr_pct > 0 else None,
                    )
                self._active_signals = [
                    signal for signal in self._active_signals
                    if not signal.is_expired(now_epoch)
                ]
            self._save_signals()
            self._mark_poll_success(poll_start)
            return new_signals

        self._quotes_polled = True
        phase_started = time.monotonic()
        quotes = self._fetch_realtime_quotes()
        self._poll_phase_seconds["quote_fetch"] = time.monotonic() - phase_started
        if not quotes:
            logger.debug("No quotes received in poll cycle")
            self._save_signals()
            self._mark_poll_success(poll_start)  # loop-liveness, NOT data-freshness: an empty market-hours fetch still marks success (poll_age/readyz/snapshot_stale stay green) — data-feed health is now in signals_producer_data_stale / last_data_age_seconds (+ fmp_request_errors_total)
            return new_signals

        self._capture_regular_close_baseline(quotes)

        self._poll_seq += 1
        self._last_data_epoch = time.time()  # real data arrived — data-freshness clock (see the data_stale gauge)

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
            with self._lock:
                self._active_signals.clear()
            self._save_signals()
            self._mark_poll_success(poll_start)
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
                sym,
                quote,
                wl_entry,
                regime_thresholds=regime_thresholds,
                expected_volume_fraction=quote.get("expected_volume_fraction"),
            )
            # Newsstack data (used for signal enrichment & VD row)
            ns_data = news_by_ticker.get(sym)

            if signal:
                # ATR trade context (entry/stop/target/R) — one computation,
                # consumed by BOTH the Slack push (rt_notify) and the Pine
                # overlay (snapshot → daemon /smc_live). Fail-soft no-op when
                # price/ATR/direction are unusable (fields stay None).
                from open_prep import trade_context as _trade_context
                _trade_context.attach(signal)
                # Enrich with newsstack data
                if ns_data:
                    signal.news_score = _safe_float(ns_data.get("news_score", 0))
                    signal.news_category = str(ns_data.get("category", ""))
                    signal.news_headline = str(ns_data.get("headline", ""))[:200]
                    signal.news_warn_flags = list(ns_data.get("warn_flags") or [])
                    # Upgrade A1/A2 → A0 only when the catalyst is strong,
                    # DIRECTIONALLY ALIGNED, and the dynamic cooldown is idle.
                    # news_score is a non-directional magnitude (impact/clarity/
                    # novelty) — the sign lives in `polarity`. Without the
                    # alignment gate a strongly BEARISH headline could escalate
                    # a LONG to highest conviction with reason "news_catalyst".
                    _pol = _safe_float(ns_data.get("polarity", 0))
                    _pol_aligned = (_pol < 0) if signal.direction == "SHORT" else (_pol > 0)
                    if signal.level in ("A1", "A2") and signal.news_score >= 0.80 and _pol_aligned:
                        _vol_regime_ns = self._volume_regime.regime if hasattr(self._volume_regime, "regime") else "NORMAL"
                        _cd_regime_ns = "THIN" if _vol_regime_ns == "HOLIDAY_SUSPECT" else "NORMAL"
                        cd_active, _ = self._dynamic_cooldown.check_cooldown(
                            sym, volume_regime=_cd_regime_ns, has_news_catalyst=True,
                        )
                        if not cd_active:
                            signal.level = "A0"
                            signal.details["a0_upgrade_reason"] = "news_catalyst"
                            from open_prep.a0_contract import (
                                A0ReasonCode,
                                amend_decision_details,
                            )
                            amend_decision_details(
                                signal.details,
                                final_level="A0",
                                reason_code=A0ReasonCode.NEWS_CATALYST_UPGRADE,
                            )
                            self._dynamic_cooldown.record_transition(sym, signal.direction)

                # Check if we already have an active signal for this symbol
                self._reconcile_new_signal(sym, signal, new_signals)

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
                quote.get("avgVolume") or _watchlist_average_volume(wl_entry), 0.0
            )
            vol_ratio, expected_vol_frac, normalized_volume_pace = _volume_semantics(
                q_volume,
                _avg_vol,
                quote.get("expected_volume_fraction"),
            )
            # Determine signal status for this symbol
            with self._lock:
                _current_active = list(self._active_signals)
            sym_signals = [
                s for s in (*_current_active, *new_signals)
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
                near = _is_upcoming_a2(
                    normalized_volume_pace,
                    abs(chg_pct),
                    eff_a2_vol,
                    eff_a2_chg,
                )
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
                "signal_schema_version": 2,
                "raw_daily_volume_ratio": round(vol_ratio, 6),
                "expected_volume_fraction": round(expected_vol_frac, 6),
                "normalized_volume_pace": round(normalized_volume_pace, 6),
                "effective_a0_volume_threshold": round(
                    A0_VOLUME_RATIO_MIN * regime_thresholds["vol_mult"], 6,
                ),
                "effective_a0_price_threshold": round(
                    A0_PRICE_CHANGE_PCT_MIN * regime_thresholds["chg_mult"], 6,
                ),
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
        with self._lock:
            self._active_signals.extend(new_signals)

        # ── #6  Signal re-qualification ──────────────────────────
        # Re-validate active signals CARRIED OVER from prior polls against the
        # current quotes.  If a carried-over signal no longer meets even A1
        # criteria → expire it early.  Signals detected THIS poll are exempt:
        # _detect_signal already validated them against this same quote (incl.
        # the news/PDH/RSI/technical A1→A0 upgrades, whose raw vol/change sit in
        # the A1 band by construction) — re-qualifying them here would strip
        # every upgrade back to A1 before it reaches /smc_live.  2026-07-25.
        requalified: list[RealtimeSignal] = []
        _fresh_ids = {id(s) for s in new_signals}
        from open_prep.a0_contract import A0ReasonCode, amend_decision_details
        with self._lock:
            signals_snapshot = list(self._active_signals)
        for sig in signals_snapshot:
            if sig.is_expired():
                continue
            if id(sig) in _fresh_ids:
                requalified.append(sig)  # detected this poll — already current
                continue
            q = quotes.get(sig.symbol)
            if q is None:
                requalified.append(sig)  # no data this cycle — keep
                continue
            cur_price = _safe_float(q.get("price") or q.get("lastPrice"), 0.0)
            cur_prev_close = _safe_float(q.get("previousClose"), 0.0)
            cur_volume = _safe_float(q.get("volume"), 0.0)
            # Use watchlist fallback for avgVolume (FMP batch quote omits it).
            # Reuse the wl_map built earlier this poll instead of rescanning the
            # ~900-entry watchlist per active signal (audit P3 LOW). Key uses the
            # same strip().upper() normalization as wl_map.
            wl_avg = 0.0
            wl_entry = wl_map.get(str(sig.symbol).strip().upper())
            if wl_entry is not None:
                wl_avg = _watchlist_average_volume(wl_entry)
            cur_avg_vol = _safe_float(q.get("avgVolume") or wl_avg, 0.0)
            if cur_avg_vol < 1000:
                requalified.append(sig)  # can't verify — keep
                continue
            if cur_price <= 0 or cur_prev_close <= 0:
                requalified.append(sig)
                continue
            cur_change = abs(((cur_price / cur_prev_close) - 1) * 100)
            raw_cur_vol = cur_volume / cur_avg_vol
            cur_vol_ratio = raw_cur_vol / max(
                _resolve_expected_volume_fraction(q.get("expected_volume_fraction")), 0.02
            )

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
                amend_decision_details(
                    sig.details,
                    final_level="A1",
                    reason_code=A0ReasonCode.TIME_DECAY_DOWNGRADE,
                )
                now_iso = datetime.now(UTC).isoformat()
                sig.level_since_at = now_iso
                sig.level_since_epoch = time.time()
                logger.debug(
                    "Time-decay: %s A0→A1 (age %.0fs > %ds, stale=%s)",
                    sig.symbol, sig_age, eff_a0_max, momentum_stale,
                )
            if sig.level == "A1" and sig_age > eff_a1_max:
                sig.level = "A2"
                amend_decision_details(
                    sig.details,
                    final_level="A2",
                    reason_code=A0ReasonCode.TIME_DECAY_DOWNGRADE,
                )
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
                amend_decision_details(
                    sig.details,
                    final_level="A1",
                    reason_code=A0ReasonCode.REQUALIFICATION_DOWNGRADE,
                )
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
                amend_decision_details(
                    sig.details,
                    final_level="A2",
                    reason_code=A0ReasonCode.REQUALIFICATION_DOWNGRADE,
                )
                now_iso = datetime.now(UTC).isoformat()
                sig.level_since_at = now_iso
                sig.level_since_epoch = time.time()
                logger.debug("Re-qualification: downgrade %s A1→A2", sig.symbol)

            requalified.append(sig)

        with self._lock:
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

        # Semantic readiness: successful poll completion
        self._mark_poll_success(poll_start)

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
        # Update freshness before returning; guard with lock to avoid racing
        # with the poll loop that also mutates _active_signals.
        with self._lock:
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
                    fh.write(json.dumps(_replace_non_finite(_meta_row), default=str, allow_nan=False))
                    fh.write("\n")
                    for row in self._vd_rows.values():
                        fh.write(json.dumps(_replace_non_finite(row), default=str, allow_nan=False))
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

        _lock = getattr(self, "_lock", None)
        if _lock is not None:
            with _lock:
                _snap = list(self._active_signals)
        else:
            _snap = list(self._active_signals)
        payload = {
            "updated_at": datetime.now(UTC).isoformat(),
            "updated_epoch": time.time(),
            "poll_interval": self.poll_interval,
            "poll_duration": round(self.last_poll_duration, 3),
            "market_session": getattr(self, "_market_session_name", "closed"),
            "quotes_polled": bool(getattr(self, "_quotes_polled", False)),
            "extended_signals_mode": getattr(self, "extended_signals_mode", "off"),
            "extended_shadow_enabled": getattr(self, "extended_shadow_enabled", False),
            "extended_shadow": dict(getattr(self, "_extended_shadow", {})),
            "postmarket_baseline_date": getattr(self, "_postmarket_baseline_date", ""),
            "postmarket_close_volume": dict(getattr(self, "_postmarket_close_volume", {})),
            "postmarket_adapter_stats": dict(getattr(self, "_postmarket_adapter_stats", {})),
            "watched_symbols": [str(r.get("symbol", "")) for r in self._watchlist],
            "signals": [s.to_dict() for s in _snap],
            "signal_count": len(_snap),
            "a0_count": sum(1 for s in _snap if s.level == "A0"),
            "a1_count": sum(1 for s in _snap if s.level == "A1"),
            "a2_count": sum(1 for s in _snap if s.level == "A2"),
            "disabled_reason": disabled_reason,
        }
        try:
            SIGNALS_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=SIGNALS_PATH.parent, suffix=".tmp", prefix="signals_",
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                    json.dump(_replace_non_finite(payload), fh, indent=2, default=str, allow_nan=False)
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
        _empty: dict[str, Any] = {"signals": [], "signal_count": 0, "a0_count": 0, "a1_count": 0, "a2_count": 0}
        if not SIGNALS_PATH.exists():
            return _empty
        try:
            file_age_s = time.time() - SIGNALS_PATH.stat().st_mtime
            with open(SIGNALS_PATH, encoding="utf-8") as fh:
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

def _raise_keyboard_interrupt_on_sigterm(_signum: int, _frame: Any) -> None:
    """SIGTERM handler: translate the orchestrator stop signal (Railway/Docker
    ``stop`` send SIGTERM, then SIGKILL after a grace period) into the same
    ``KeyboardInterrupt`` the SIGINT path already handles, so ``main()``'s
    graceful-shutdown block runs — stopping the Databento feed's ``db.Live``
    socket + threads, the telemetry server and the pollers cleanly — instead
    of the process being killed mid-connection."""
    raise KeyboardInterrupt


def main() -> None:
    """Run the realtime signal engine as a standalone polling loop."""
    import argparse
    import signal

    # Auto-load .env so FMP_API_KEY is available without manual shell sourcing
    env_path = Path(__file__).resolve().parents[1] / ".env"
    try:
        from dotenv import load_dotenv

        if env_path.is_file():
            load_dotenv(env_path, override=False)
    except ImportError:
        # python-dotenv not installed — minimal stdlib fallback
        if env_path.is_file():
            with open(env_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key, val = key.strip(), val.strip().strip("'\"")
                    # R-E2 (2026-06-14): os.environ mutation is safe here —
                    # this code runs in main() before any threads are started,
                    # is additive-only (guarded by `not in os.environ`), and
                    # is the stdlib fallback when python-dotenv is absent.
                    if key and key not in os.environ:
                        os.environ[key] = val

    parser = argparse.ArgumentParser(description="Realtime signal engine")
    parser.add_argument("--interval", type=int, default=_env_int("RT_POLL_INTERVAL_SECS", DEFAULT_POLL_INTERVAL, maximum=None), help="Poll interval in seconds")
    parser.add_argument("--top-n", type=int, default=_env_int("RT_TOP_N", DEFAULT_TOP_N, minimum=0, maximum=None), help="Number of symbols to monitor (0 = all, default)")
    parser.add_argument("--reload-interval", type=int, default=300, help="Seconds between watchlist reloads")
    parser.add_argument(
        "--fast", action="store_true",
        help="Enable fast/VisiData mode: 5s min poll interval, 20s base cooldown",
    )
    parser.add_argument(
        "--ultra", action="store_true",
        help="Ultra-fast 2s polling for VisiData near-realtime breakout monitoring",
    )
    _default_port = _env_int("PORT", 8099)
    parser.add_argument(
        "--telemetry-port", type=int, default=_default_port,
        help="Port for the telemetry HTTP endpoint (0 to disable, default: $PORT or 8099)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # Route SIGTERM (container/orchestrator stop) through the existing
    # KeyboardInterrupt graceful-shutdown path. signal.signal only works on the
    # main thread; the narrow ValueError guard keeps main() importable/callable
    # off the main thread (e.g. under a test runner) without a handler.
    try:
        signal.signal(signal.SIGTERM, _raise_keyboard_interrupt_on_sigterm)
    except ValueError:
        logger.debug("SIGTERM handler not installed (main() not on main thread)")

    engine = RealtimeEngine(
        poll_interval=args.interval,
        top_n=args.top_n,
        fast_mode=args.fast or args.ultra,
        ultra_mode=args.ultra,
    )

    # Start the Databento feed's background threads now that the run loop is
    # actually beginning (Task 2.1). No-op for explicit/fallback FMP -- no feed was
    # constructed, so there is nothing to start.
    engine.start_quote_source()

    # Start telemetry HTTP server (daemon thread — auto-stops on exit).
    # Pass the engine so /signals can fall back to live state during the
    # cold-start window before the first poll cycle writes SIGNALS_PATH.
    telemetry_server: Any = None
    if args.telemetry_port > 0:
        telemetry_server = _start_telemetry_server(
            engine.telemetry, port=args.telemetry_port, engine=engine,
        )

    # News is always off the quote-critical path. Fast/ultra only change the
    # default cadence; RT_NEWS_POLL_SECS can tune it independently of mode.
    ns_interval = _env_int(
        "RT_NEWS_POLL_SECS", 30 if args.ultra else 60, minimum=5, maximum=None,
    )
    engine.start_async_newsstack(poll_interval=ns_interval)
    logger.info("Async newsstack started (interval=%ds)", ns_interval)

    # Opt-in near-A0 fast lane: re-poll A1/A2 symbols every N seconds so an
    # escalation to A0 pushes to Slack in seconds, not a full ~30s cycle late.
    # Default 0 = off (no extra thread, no extra FMP calls).
    near_a0_secs = _env_int("RT_NEAR_A0_REPOLL_SECS", 0, minimum=0)
    if near_a0_secs > 0:
        engine.start_near_a0_repoller(float(near_a0_secs))
        logger.info("Near-A0 re-poller started (interval=%ds)", near_a0_secs)

    # Opt-in persistent signal-event log (RT_SIGNAL_EVENT_LOG_DIR) — the data
    # foundation for scripts/calibrate_signal_followthrough.py. Fail-soft.
    event_logger = None
    try:
        from open_prep.signal_events import SignalEventLogger
        event_logger = SignalEventLogger.from_env()
        if event_logger is not None:
            logger.info("Signal-event log enabled (RT_SIGNAL_EVENT_LOG_DIR)")
    except Exception:
        logger.debug("signal-event logger init failed", exc_info=True)

    # Opt-in A0 parity evidence. This is independent from notifications and
    # fail-soft so an evidence-volume issue cannot interrupt the FMP fallback.
    a0_parity_journal = None
    a0_parity_dir = os.environ.get("RT_A0_PARITY_LOG_DIR", "").strip()
    if a0_parity_dir:
        try:
            from open_prep.a0_parity_store import A0ParityJournal, parity_source_from_env
            parity_source = "fmp" if isinstance(engine._quote_source, FMPQuoteSource) else parity_source_from_env()
            a0_parity_journal = A0ParityJournal(a0_parity_dir, source=parity_source)
            logger.info("A0 parity journal enabled (RT_A0_PARITY_LOG_DIR, source=%s)", parity_source)
        except Exception:
            logger.warning("FMP A0 parity journal init failed", exc_info=True)

    # Opt-in nightly follow-through calibration (RT_CALIBRATION_UTC_HHMM="HH:MM"
    # UTC, e.g. "21:30" ≈ 17:30 ET). Runs in-process because the event log lives
    # on THIS service's Railway volume and a separate cron cannot share it; fires
    # once per UTC day on a throwaway thread so the poll loop never blocks.
    cal_hhmm = os.environ.get("RT_CALIBRATION_UTC_HHMM", "").strip()
    from open_prep.calibration_scheduler import parse_calibration_hhmm

    cal_at = parse_calibration_hhmm(cal_hhmm)
    cal_ev_dir = os.environ.get("RT_SIGNAL_EVENT_LOG_DIR", "")
    cal_out = str(Path(cal_ev_dir).parent / "calibration_latest.json") if cal_ev_dir else ""
    cal_last_day: str | None = None
    if cal_hhmm and cal_at is None:
        # Never log a schedule we cannot honour: this used to accept any string
        # and then silently never fire.
        logger.warning(
            "RT_CALIBRATION_UTC_HHMM=%r is not a valid HH:MM UTC time — "
            "nightly calibration stays OFF", cal_hhmm,
        )
    elif cal_at is not None and event_logger is not None:
        # Log the PARSED time, so "9:30" reads back as 09:30.
        logger.info(
            "Nightly calibration scheduled (%s UTC -> %s)",
            cal_at.strftime("%H:%M"), cal_out,
        )

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

            # Push a notification the instant a fresh/strengthened breakout
            # fires — faster than the snapshot -> Grafana path and hands-off.
            # Opt-in + fail-soft: a no-op unless RT_SIGNAL_WEBHOOK_* is set, and
            # it never raises (see open_prep/rt_notify.py).
            try:
                from open_prep import rt_notify

                rt_notify.notify_fresh_signals(active)
            except Exception:  # best-effort notifier — must never break polling
                logger.debug("rt_notify hook failed", exc_info=True)

            # Persist the fresh/strengthened events (record() is itself fail-soft).
            if event_logger is not None:
                event_logger.record(active)

            if a0_parity_journal is not None:
                try:
                    from open_prep.a0_parity_store import record_realtime_a0_signals
                    record_realtime_a0_signals(
                        a0_parity_journal,
                        active,
                        now_epoch=time.time(),
                    )
                except Exception:
                    logger.warning("FMP A0 parity persistence failed", exc_info=True)

            # Nightly follow-through calibration — once per UTC day, off-thread
            # (the poll loop must never block on the calibrator's FMP fetches).
            if cal_at is not None and event_logger is not None:
                _now = datetime.now(UTC)
                _today = _now.strftime("%Y-%m-%d")
                if cal_last_day != _today and _now.time() >= cal_at:
                    cal_last_day = _today
                    from open_prep.calibration_scheduler import run_calibration_once
                    threading.Thread(
                        target=run_calibration_once, args=(cal_ev_dir, cal_out), daemon=True,
                    ).start()

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
            # Stop the near-A0 fast-lane re-poller gracefully
            if engine._near_a0_repoller is not None:
                engine._near_a0_repoller.stop()
            # Stop the Databento feed's background threads gracefully
            # (no-op for explicit/fallback FMP)
            engine.stop_quote_source()
            # Shutdown telemetry HTTP server
            if telemetry_server is not None:
                telemetry_server.shutdown()
            break
        except Exception as exc:
            logger.error("Poll error: %s", exc, exc_info=True)
            time.sleep(max(10, engine.poll_interval))


def _env_int(key: str, default: int, *, minimum: int = 1, maximum: int | None = 65535) -> int:
    raw = os.getenv(key)
    if raw is None:
        return default
    value = raw.strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        logger.warning("Invalid %s=%r, using default %d", key, raw, default)
        return default
    # Strict ASCII digits guard PORT-style vars (default 1..65535); callers pass
    # their own bounds so a poll interval or symbol count is NOT clamped to the
    # TCP-port range (minimum=0 keeps RT_TOP_N "0 = all"; maximum=None = no cap).
    if not value.isascii() or not value.isdigit() or parsed < minimum or (maximum is not None and parsed > maximum):
        logger.warning(
            "Invalid %s=%r (outside [%s, %s]), using default %d",
            key, raw, minimum, maximum if maximum is not None else "inf", default,
        )
        return default
    return parsed


def _replace_non_finite(value: Any) -> Any:
    if isinstance(value, float):
        return value if (value == value and value not in (float("inf"), float("-inf"))) else None
    if isinstance(value, dict):
        return {key: _replace_non_finite(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_non_finite(item) for item in value]
    if isinstance(value, tuple):
        return [_replace_non_finite(item) for item in value]
    return value


def _collect_a0_latency_metrics(engine: Any, now: float, prefix: str) -> list[str]:
    """Render A0 latency/news/fast-lane metrics without blocking poll threads."""
    lines: list[str] = []
    last_data_epoch = _safe_float(getattr(engine, "_last_data_epoch", 0.0), 0.0)
    quote_age = max(0.0, now - last_data_epoch) if last_data_epoch > 0 else 999999.0
    lines.extend([
        f"# TYPE {prefix}_a0_quote_data_age_seconds gauge",
        f"{prefix}_a0_quote_data_age_seconds {quote_age:.3f}",
        f"# TYPE {prefix}_a0_poll_interval_actual_seconds gauge",
        f"{prefix}_a0_poll_interval_actual_seconds "
        f"{_safe_float(getattr(engine, 'last_poll_interval_actual_seconds', 0.0), 0.0):.3f}",
    ])
    lines.append(f"# TYPE {prefix}_a0_poll_phase_seconds gauge")
    for phase, duration in sorted(getattr(engine, "_poll_phase_seconds", {}).items()):
        safe_phase = str(phase).replace("\\", "_").replace('"', "_").replace("\n", "_")
        lines.append(
            f'{prefix}_a0_poll_phase_seconds{{phase="{safe_phase}"}} '
            f"{_safe_float(duration, 0.0):.6f}"
        )

    news_poller = getattr(engine, "_async_newsstack", None)
    lines.append(f"# TYPE {prefix}_a0_news_async_enabled gauge")
    lines.append(f"{prefix}_a0_news_async_enabled {1 if news_poller is not None else 0}")
    if news_poller is not None:
        news = news_poller.metrics()
        success_at = _safe_float(news.get("last_success_at"), 0.0)
        snapshot_age = max(0.0, now - success_at) if success_at > 0 else 999999.0
        lines.extend([
            f"# TYPE {prefix}_a0_news_snapshot_age_seconds gauge",
            f"{prefix}_a0_news_snapshot_age_seconds {snapshot_age:.3f}",
            f"# TYPE {prefix}_a0_news_poll_duration_seconds gauge",
            f"{prefix}_a0_news_poll_duration_seconds "
            f"{_safe_float(news.get('last_poll_duration'), 0.0):.6f}",
            f"# TYPE {prefix}_a0_news_polls_total counter",
            f"{prefix}_a0_news_polls_total {int(news.get('poll_count', 0))}",
            f"# TYPE {prefix}_a0_news_poll_errors_total counter",
            f"{prefix}_a0_news_poll_errors_total {int(news.get('poll_errors', 0))}",
            f"# TYPE {prefix}_a0_news_cached_tickers gauge",
            f"{prefix}_a0_news_cached_tickers {int(news.get('cached_tickers_count', 0))}",
        ])

    repoller = getattr(engine, "_near_a0_repoller", None)
    lines.append(f"# TYPE {prefix}_a0_near_repoll_enabled gauge")
    lines.append(f"{prefix}_a0_near_repoll_enabled {1 if repoller is not None else 0}")
    if repoller is not None:
        near = repoller.metrics()
        lines.extend([
            f"# TYPE {prefix}_a0_near_repoll_interval_seconds gauge",
            f"{prefix}_a0_near_repoll_interval_seconds "
            f"{_safe_float(getattr(repoller, '_interval', 0.0), 0.0):.3f}",
            f"# TYPE {prefix}_a0_near_repoll_warm_set_size gauge",
            f"{prefix}_a0_near_repoll_warm_set_size "
            f"{int(near.get('last_warm_set_size', 0))}",
            f"# TYPE {prefix}_a0_near_repolls_total counter",
            f"{prefix}_a0_near_repolls_total {int(near.get('poll_count', 0))}",
            f"# TYPE {prefix}_a0_near_repoll_errors_total counter",
            f"{prefix}_a0_near_repoll_errors_total {int(near.get('poll_errors', 0))}",
            f"# TYPE {prefix}_a0_near_repoll_a0_pushed_total counter",
            f"{prefix}_a0_near_repoll_a0_pushed_total {int(near.get('a0_pushed', 0))}",
        ])
    return lines


def _watchlist_average_volume(entry: dict[str, Any]) -> float:
    """Prefer the explicit 15-session FMP ADV once the snapshot carries it.

    Presence is authoritative: an explicit null means insufficient same-basis
    history and must fail closed rather than fall back to profile averageVolume.
    Older snapshots retain the legacy fallback during the rollout window.
    """
    if "avg_volume_15_session" in entry:
        return _safe_float(entry.get("avg_volume_15_session"), 0.0)
    return _safe_float(entry.get("avg_volume"), 0.0)


def _volume_semantics(
    volume: Any,
    avg_volume: Any,
    expected_volume_fraction: Any = None,
) -> tuple[float, float, float]:
    """Return raw daily ratio, expected fraction, and normalized volume pace."""
    average = _safe_float(avg_volume, 0.0)
    raw_ratio = _safe_float(volume, 0.0) / average if average >= 1000 else 0.0
    expected_fraction = _resolve_expected_volume_fraction(expected_volume_fraction)
    return raw_ratio, expected_fraction, raw_ratio / expected_fraction


def _is_upcoming_a2(
    normalized_volume_pace: float,
    abs_change_pct: float,
    effective_a2_volume_threshold: float,
    effective_a2_price_threshold: float,
) -> bool:
    """Whether a symbol has reached 80% of both effective A2 thresholds."""
    return (
        normalized_volume_pace >= 0.8 * effective_a2_volume_threshold
        and abs_change_pct >= 0.8 * effective_a2_price_threshold
    )


def _open_prep_snapshot_url() -> str:
    """Return the explicit source URL or the canonical rolling snapshot.

    An explicitly present-but-empty variable keeps local/offline operation
    possible. Hosted producers no longer start with an empty watchlist merely
    because a redundant URL variable was omitted.
    """
    return os.getenv(
        "OPEN_PREP_SNAPSHOT_URL",
        "https://api.github.com/repos/skipp-dev/skipp-algo/contents/"
        "artifacts/open_prep/latest/latest_open_prep_run.json"
        "?ref=bot/live-open-prep-snapshot",
    ).strip()


def _serve_news_feed(handler: Any, engine: Any) -> None:
    """Serve the fail-closed private news snapshot to an HTTP handler."""
    if not _authorize_private_request(
        handler,
        token_env="SIGNALS_INTERNAL_TOKEN",
        minimum_length=1,
    ):
        return

    poller = getattr(engine, "_async_newsstack", None)
    if poller is None:
        generated_ts = None
        items: list[dict[str, Any]] = []
    else:
        with poller._lock:
            generated_ts = poller.last_success_at
            items = [dict(item) for item in poller._feed_items]
    payload = {
        "schema_version": 1,
        "generated_ts": generated_ts,
        "source": "smc-signals-producer",
        "status": "ready" if generated_ts is not None else "warming_up",
        "item_count": len(items),
        "items": items,
    }
    try:
        body = json.dumps(payload, allow_nan=False, default=str).encode()
        status = 200 if payload["status"] == "ready" else 503
    except (TypeError, ValueError):
        body = json.dumps({"error": "invalid producer feed payload"}).encode()
        status = 500
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.end_headers()
    handler.wfile.write(body)


def _authorize_private_request(
    handler: Any,
    *,
    token_env: str,
    minimum_length: int,
) -> bool:
    """Authorize a private Producer endpoint without exposing token material."""
    raw_token = os.getenv(token_env, "")
    auth_token = raw_token.strip()
    strict_config_invalid = minimum_length > 1 and (
        len(auth_token) > 512
        or auth_token != raw_token
        or any(ord(character) < 0x21 or ord(character) == 0x7F for character in auth_token)
    )
    if (
        len(auth_token) < minimum_length
        or strict_config_invalid
    ):
        handler.send_response(503)
        handler.end_headers()
        return False

    header = handler.headers.get("Authorization", "")
    parts = header.split(" ", 1)
    supplied = (
        parts[1].strip()
        if len(parts) == 2 and parts[0].lower() == "bearer"
        else ""
    )
    constant_time_equals = hmac.compare_digest
    if not constant_time_equals(supplied.encode(), auth_token.encode()):  # bytes: a non-ASCII header would make the str form raise
        handler.send_response(401)
        handler.end_headers()
        return False
    return True


def _serve_ai_insights(handler: Any) -> None:
    """Run an AI Insights query at the Producer's inspected LLM boundary."""
    validation_request = handler.path == "/ai-validation"
    if validation_request:
        authorized = _authorize_private_request(
            handler,
            token_env="AI_VALIDATION_TOKEN",
            minimum_length=32,
        )
    else:
        authorized = _authorize_private_request(
            handler,
            token_env="SIGNALS_INTERNAL_TOKEN",
            minimum_length=1,
        )
    if not authorized:
        return

    raw_length = handler.headers.get("Content-Length", "")
    try:
        content_length = int(raw_length)
    except (TypeError, ValueError):
        content_length = -1
    request_limit = 64_000 if validation_request else 900_000
    if not 0 < content_length <= request_limit:
        handler.send_response(413 if content_length > request_limit else 400)
        handler.end_headers()
        return

    try:
        payload = json.loads(handler.rfile.read(content_length))
    except (UnicodeDecodeError, json.JSONDecodeError):
        handler.send_response(400)
        handler.end_headers()
        return
    if not isinstance(payload, dict):
        handler.send_response(400)
        handler.end_headers()
        return
    if validation_request:
        question = payload.get("prompt")
        context_json = json.dumps(
            {
                "validation_target": "skipp-ai-insights",
                "total_articles": 0,
                "top_articles": [],
                "ticker_summary": {},
            },
            separators=(",", ":"),
        )
    else:
        if payload.get("schema_version") != 1:
            handler.send_response(400)
            handler.end_headers()
            return
        question = payload.get("question")
        context_json = payload.get("context_json")
    if (
        not isinstance(question, str)
        or not question.strip()
        or len(question) > 32_000
        or not isinstance(context_json, str)
        or len(context_json) > 850_000
    ):
        handler.send_response(400)
        handler.end_headers()
        return

    from terminal_fmp_insights import query_fmp_llm

    result = query_fmp_llm(
        question=question.strip(),
        context_json=context_json,
        api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        blocked_answer=(
            "This request was blocked by the Skipp AI security policy."
            if validation_request
            else ""
        ),
    )
    response_payload = {
        "schema_version": 1,
        "answer": result.answer,
        "model": result.model,
        "cached": result.cached,
        "context_articles": result.context_articles,
        "context_tickers": result.context_tickers,
        "fmp_tickers": result.fmp_tickers,
        "error": result.error,
    }
    if validation_request and (result.error or not result.answer):
        response_payload = {
            "schema_version": 1,
            "error": "validation backend unavailable",
        }
        response_status = 502
    else:
        response_status = 200
    body = json.dumps(response_payload, allow_nan=False).encode("utf-8")
    handler.send_response(response_status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _quote_reference_snapshot_url() -> str:
    """Return the explicit URL or the canonical rolling quote reference."""
    return os.getenv(
        "QUOTE_REFERENCE_SNAPSHOT_URL",
        "https://api.github.com/repos/skipp-dev/skipp-algo/contents/"
        "artifacts/open_prep/latest/quote_reference.json"
        "?ref=bot/live-open-prep-snapshot",
    ).strip()


def _client_disabled_for_selected_quote_source(engine: Any) -> bool:
    """Only the FMP quote source is disabled by an unavailable FMP client."""
    source = getattr(engine, "_quote_source", None)
    fmp_active = isinstance(source, FMPQuoteSource) or (
        source is None and _selected_quote_source() == "fmp"
    )
    return bool(getattr(engine, "_client_disabled_reason", None)) and fmp_active


def _quote_source_readiness_reason(engine: Any) -> str:
    """Return why the selected Databento source is not runtime-ready."""
    if engine is None:
        return ""
    source = getattr(engine, "_quote_source", None)
    if isinstance(source, FMPQuoteSource) or _selected_quote_source() == "fmp":
        return ""
    if not isinstance(source, DatabentoQuoteSource):
        return "databento quote source not initialised"
    reference = getattr(source, "_reference", None)
    if reference is None or len(reference) == 0:
        return "databento quote reference empty"
    feed = getattr(engine, "_databento_feed", None)
    try:
        feed_state = feed.telemetry.snapshot()
    except (AttributeError, TypeError):
        return "databento feed telemetry unavailable"
    if not feed_state.get("connected"):
        return "databento feed not connected"
    if _market_session() == "regular" and int(feed_state.get("records_received") or 0) < 1:
        return "databento feed has no regular-session records"
    return ""


def _selected_quote_source() -> str:
    """Resolve the desired source: Databento by default, FMP by opt-in."""
    configured = os.getenv("RT_QUOTE_SOURCE", "databento").strip().lower()
    if configured == "fmp":
        return "fmp"
    if configured not in {"", "databento"}:
        logger.warning(
            "Unsupported RT_QUOTE_SOURCE=%r; using the Databento default",
            configured,
        )
    return "databento"


def _active_snapshot_rows(
    data: dict[str, Any],
    key: str,
    *,
    max_stale_age_seconds: float = 7 * 24 * 60 * 60,
) -> list[dict[str, Any]]:
    """Keep inactive/stale quote evidence out of the realtime watchlist.

    The producer now removes these rows before publishing, but the consumer
    repeats the guard so a rollout cannot revive ``DAY`` from an older
    already-published snapshot.
    """
    snapshot_epoch = _extract_snapshot_epoch(data) or time.time()
    excluded: set[str] = set()
    for quote in data.get("enriched_quotes") or []:
        symbol = str(quote.get("symbol") or "").strip().upper()
        quote_epoch = _safe_float(quote.get("timestamp"), 0.0)
        if quote_epoch >= 1_000_000_000_000:
            quote_epoch /= 1000.0
        explicitly_inactive = quote.get("isActivelyTrading") is False
        severely_stale = (
            str(quote.get("gap_reason") or "") == "stale_prior_session_quote"
            and quote_epoch > 0
            and snapshot_epoch - quote_epoch >= max_stale_age_seconds
        )
        if symbol and (explicitly_inactive or severely_stale):
            excluded.add(symbol)
    if excluded and key == "ranked_v2":
        logger.warning("Excluded inactive realtime-watchlist symbols: %s", sorted(excluded))
    return [
        row
        for row in (data.get(key) or [])
        if str(row.get("symbol") or "").strip().upper() not in excluded
    ]


def _collect_databento_feed_metrics(engine: Any) -> list[str]:
    """Render optional feed telemetry without risking the central endpoint."""
    feed_telemetry = getattr(
        getattr(engine, "_databento_feed", None),
        "telemetry",
        None,
    )
    render_feed_metrics = getattr(feed_telemetry, "render_prometheus", None)
    if not callable(render_feed_metrics):
        return []
    try:
        return render_feed_metrics().splitlines()
    except Exception:  # pragma: no cover - metrics must remain available
        logger.exception("Failed to render Databento feed metrics")
        return []


if __name__ == "__main__":
    main()
