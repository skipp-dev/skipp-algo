"""In-process nightly follow-through calibration for the realtime producer.

Runs the same computation as ``scripts/calibrate_signal_followthrough.py`` but
from inside the producer process. It lives here because the signal-event log
(``RT_SIGNAL_EVENT_LOG_DIR``) sits on THIS service's Railway volume, and a
separate Railway cron service cannot mount the same volume. The producer, which
already has the volume mounted and also runs the eventual consumer (rt_notify),
is therefore the natural — and only — home for calibration "on the same volume".

Fail-soft: a calibration error must never disturb the poll loop. The producer
schedules :func:`run_calibration_once` on a throwaway daemon thread once per UTC
day, so the FMP bar fetches never block signal polling.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_calibration_once(
    events_dir: str,
    out_path: str,
    *,
    horizon_min: int = 60,
    target_pct: float = 0.5,
) -> None:
    """Compute follow-through calibration once and write *out_path*.

    Thin wrapper around the calibrator CLI ``main`` so it can run on a throwaway
    thread inside the producer. ``events_dir`` is ``RT_SIGNAL_EVENT_LOG_DIR`` on
    the Railway volume; ``out_path`` is where rt_notify will read the calibrated
    thresholds (``<volume>/calibration_latest.json``). Never raises.
    """
    try:
        from scripts.calibrate_signal_followthrough import main as _calibrate_main

        rc = _calibrate_main([
            "--events-dir", events_dir,
            "--horizon-min", str(horizon_min),
            "--target-pct", str(target_pct),
            "--out", out_path,
        ])
        if rc == 0:
            logger.info("Nightly calibration wrote %s", out_path)
        else:
            logger.warning(
                "Nightly calibration produced no table (rc=%s) — no events yet?", rc,
            )
    except Exception:  # best-effort — must never break the producer poll loop
        logger.debug("nightly calibration failed", exc_info=True)
