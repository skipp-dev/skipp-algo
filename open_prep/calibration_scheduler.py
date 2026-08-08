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

import json
import logging
from datetime import datetime, time

from open_prep.calibration_lookup import _min_samples

logger = logging.getLogger(__name__)


def parse_calibration_hhmm(raw: str) -> time | None:
    """Parse ``RT_CALIBRATION_UTC_HHMM`` into a UTC wall-clock time.

    ``None`` for an empty or unparseable value, so the caller can leave
    calibration off and *say so* instead of appearing scheduled.

    A non-padded hour is accepted deliberately: an operator who types "9:30"
    into Railway means 09:30. The scheduler used to compare the raw string
    against ``datetime.strftime("%H:%M")``, which is only chronological while
    both sides are zero-padded — "9:30" never fired at all (no zero-padded
    hour sorts >= "9"), and "0:05" first fired at 10:00.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%H:%M").time()
    except ValueError:
        return None


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
            _log_bucket_readiness(out_path)
        else:
            logger.warning(
                "Nightly calibration produced no table (rc=%s) — no events yet?", rc,
            )
    except Exception:  # best-effort — must never break the producer poll loop
        logger.warning("nightly calibration failed", exc_info=True)  # debug hid a month of ModuleNotFoundError (2026-08-04)


def _log_bucket_readiness(out_path: str) -> None:
    """Emit a one-line arm-readiness summary so the "enough data yet?" check is a
    log grep, not a volume dig: how many (level|vol_bucket) buckets already hold
    >= RT_CALIBRATION_MIN_SAMPLES events (the floor the consumer needs to trust a
    bucket's measured P). NOTE: the headline count spans ALL levels, but today's
    only consumer (rt_notify's near-A0 star) reads A1|* buckets exclusively — for
    the arming decision check the A1|* keys in the detail string, not the
    headline count. Best-effort; never raises."""
    # Resolved through the consumer's own helper so this readiness count can
    # never report against a floor rt_notify no longer uses.
    min_n = _min_samples()
    try:
        with open(out_path, encoding="utf-8") as fh:
            table = (json.load(fh) or {}).get("table", {}) or {}
        ready = {
            k: v for k, v in table.items()
            if isinstance(v, dict) and isinstance(v.get("n"), (int, float)) and v["n"] >= min_n
        }
        detail = ", ".join(
            f"{k} n={int(v['n'])} P={round(float(v.get('hit_target_rate', 0.0)) * 100)}%"
            for k, v in sorted(ready.items())
        ) or "none"
        logger.info(
            "Nightly calibration readiness: %d/%d buckets have n>=%d (arm-ready: %s)",
            len(ready), len(table), min_n, detail,
        )
    except Exception:  # readiness logging must never break the calibration path
        logger.debug("calibration readiness summary failed", exc_info=True)
