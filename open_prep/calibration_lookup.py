"""Fallback-safe consumer of the nightly follow-through calibration.

The nightly in-process calibrator (``open_prep/calibration_scheduler.py``,
scheduled by ``RT_CALIBRATION_UTC_HHMM``) writes ``calibration_latest.json`` to
the producer's Railway volume — an empirical ``table`` keyed by
``"<level>|<vol_bucket>"`` with a measured ``hit_target_rate`` (P of the move
following through to target within the horizon).

``rt_notify`` uses :func:`follow_through_p` to let that measured P *replace* the
hard-coded ⭐ near-A0 midpoint heuristic — but only once **armed**
(``RT_CALIBRATION_ARMED``) and only for ``(level, vol_bucket)`` buckets with
enough samples. Until then (and whenever the file is absent, malformed, or a
bucket is too sparse) it returns ``None`` so the caller keeps its heuristic.
Never raises: a calibration hiccup must never disturb the notifier.

Arming is therefore a single env flip once ~2-4 weeks of events have accrued and
``calibration_latest.json`` looks populated — no code change required.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Buckets below this many observed events fall back to the heuristic — a handful
# of samples is not a probability. Override with RT_CALIBRATION_MIN_SAMPLES.
_DEFAULT_MIN_SAMPLES = 20

# mtime-keyed cache: the nightly job rewrites the file at most once a day, so we
# parse it once and reuse until it changes (this is called per fresh signal).
_cache: dict[str, Any] = {"path": None, "mtime": None, "table": None}


def _armed() -> bool:
    return os.environ.get("RT_CALIBRATION_ARMED", "").strip().lower() in ("1", "true", "yes", "on")


def _min_samples() -> int:
    try:
        return int(os.environ.get("RT_CALIBRATION_MIN_SAMPLES", _DEFAULT_MIN_SAMPLES))
    except (TypeError, ValueError):
        return _DEFAULT_MIN_SAMPLES


def calibration_path() -> str:
    """Path of ``calibration_latest.json``: explicit ``RT_CALIBRATION_PATH`` or,
    like the scheduler's out-path, ``<RT_SIGNAL_EVENT_LOG_DIR>/../calibration_latest.json``."""
    explicit = os.environ.get("RT_CALIBRATION_PATH", "").strip()
    if explicit:
        return explicit
    ev_dir = os.environ.get("RT_SIGNAL_EVENT_LOG_DIR", "").strip()
    if ev_dir:
        return str(Path(ev_dir).parent / "calibration_latest.json")
    return ""


def _load_table() -> dict[str, Any] | None:
    """The calibration ``table`` dict, mtime-cached. ``None`` when unavailable."""
    path = calibration_path()
    if not path:
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    if _cache["path"] == path and _cache["mtime"] == mtime:
        return _cache["table"]
    table: dict[str, Any] | None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        table = data.get("table") if isinstance(data, dict) else None
        if not isinstance(table, dict):
            table = None
    except (OSError, ValueError):
        table = None
    _cache.update({"path": path, "mtime": mtime, "table": table})
    return table


def _vol_bucket(volume_ratio: float) -> str | None:
    # Reuse the calibrator's exact bucketing so lookup keys match what was
    # written. Lazy import (scripts/ is a namespace package) keeps this module
    # import-safe even where scripts/ is unavailable.
    try:
        from scripts.calibrate_signal_followthrough import vol_bucket

        return vol_bucket(float(volume_ratio))
    except (ImportError, TypeError, ValueError):
        return None


def follow_through_p(level: str, volume_ratio: float) -> float | None:
    """Measured P(follow-through) = ``hit_target_rate`` for ``(level, vol_bucket)``.

    Returns ``None`` — meaning *fall back to the heuristic* — when the consumer is
    unarmed, the calibration file is absent/malformed, the bucket is missing, or
    the bucket holds fewer than ``RT_CALIBRATION_MIN_SAMPLES`` events. Never raises.
    """
    try:
        if not _armed():
            return None
        table = _load_table()
        if not table:
            return None
        bucket = _vol_bucket(volume_ratio)
        if bucket is None:
            return None
        row = table.get(f"{level}|{bucket}")
        if not isinstance(row, dict):
            return None
        n = row.get("n", 0)
        if not isinstance(n, (int, float)) or n < _min_samples():
            return None
        p = row.get("hit_target_rate")
        return float(p) if isinstance(p, (int, float)) else None
    except Exception:  # never break the notifier over a calibration read
        logger.debug("calibration lookup failed", exc_info=True)
        return None
