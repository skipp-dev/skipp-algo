"""Persistent per-day signal-event log — the data foundation for a calibrated
follow-through score.

When a realtime breakout signal *first appears* (once per ~12 h state TTL), or
*strengthens* (A2 → A1 → A0), one JSON line is appended to
``<dir>/signal_events_<UTC-DATE>.jsonl`` capturing the signal's features at that
instant. Later, ``scripts/calibrate_signal_followthrough.py`` joins each event to
FMP 1-minute bars to measure what actually happened next, turning the A0/A1/A2
heuristic into an empirical probability.

Opt-in and fail-soft:
- disabled unless ``RT_SIGNAL_EVENT_LOG_DIR`` is set (or a dir is passed),
- every error is swallowed with a debug log, so a full disk / bad row can never
  stall the poll loop.

Dedup is STRICTER than rt_notify: one row per (symbol, direction) strength
*increase* within the 12 h state TTL — there is no cooldown re-log (rt_notify
re-fires a still-active level after its 30-min cooldown; a second same-day
episode adds no second row here). For pushed tiers (A0/A1) Slack push counts
exceed event-log rows; A2 is logged but only pushed if RT_SIGNAL_NOTIFY_LEVELS opts in.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Strength ordering mirrors rt_notify so "strengthened" means the same thing.
_STRENGTH = {"A0": 3, "A1": 2, "A2": 1}
_STATE_TTL_SECS = 12 * 3600.0

# Feature fields copied verbatim from the signal (getattr-guarded). These are the
# inputs a follow-through model would learn from — keep them raw, not derived.
_FEATURE_FIELDS = (
    "price", "prev_close", "volume_ratio", "change_pct", "atr_pct", "freshness",
    "score", "confidence_tier", "pattern", "news_score", "technical_score",
    "rsi", "symbol_regime",
)


def _safe(value: Any) -> Any:
    """JSON-safe scalar: floats stay floats, everything else stringifies cleanly."""
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return str(value)


def event_row(signal: Any, *, now_epoch: float) -> dict[str, Any]:
    """Flatten a signal into a JSON-serialisable event row (pure)."""
    row: dict[str, Any] = {
        "logged_epoch": round(now_epoch, 3),
        "logged_at": datetime.fromtimestamp(now_epoch, UTC).isoformat(),
        "symbol": str(getattr(signal, "symbol", "")).upper(),
        "level": str(getattr(signal, "level", "")),
        "direction": str(getattr(signal, "direction", "")),
        "fired_epoch": getattr(signal, "fired_epoch", None),
    }
    for field in _FEATURE_FIELDS:
        row[field] = _safe(getattr(signal, field, None))
    details = getattr(signal, "details", {})
    details = details if isinstance(details, dict) else {}
    normalized_pace = details.get("normalized_volume_pace")
    row.update({
        "schema_version": int(details.get("signal_schema_version", 2)),
        "raw_daily_volume_ratio": _safe(
            details.get("raw_daily_volume_ratio", getattr(signal, "volume_ratio", None))
        ),
        "expected_volume_fraction": _safe(details.get("expected_volume_fraction")),
        "normalized_volume_pace": _safe(normalized_pace),
        "effective_a0_volume_threshold": _safe(
            details.get("effective_a0_volume_threshold")
        ),
        "effective_a0_price_threshold": _safe(
            details.get("effective_a0_price_threshold")
        ),
        "decision_contract_version": _safe(details.get("decision_contract_version")),
        "detector_version": _safe(details.get("detector_version")),
        "core_level": _safe(details.get("core_level")),
        "final_level": _safe(details.get("final_level")),
        "reason_codes": details.get("reason_codes") or [],
        "decision_id": _safe(details.get("decision_id")),
        "ts_event": _safe(details.get("ts_event")),
        "ts_recv": _safe(details.get("ts_recv")),
        "observed_at": _safe(details.get("observed_at")),
        "decision_at": _safe(details.get("decision_at")),
        "data_age_ms": _safe(details.get("data_age_ms")),
        "data_age_unknown": bool(details.get("data_age_unknown", True)),
        "source": _safe(details.get("source")),
        "session_date": _safe(details.get("session_date")),
        "volume_semantics": (
            "normalized_pace_v2" if normalized_pace is not None else "legacy_raw_only"
        ),
    })
    return row


class SignalEventLogger:
    """Append fresh/strengthened signal events to a daily JSONL. Thread-safe,
    fail-soft."""

    def __init__(self, log_dir: str | os.PathLike[str]) -> None:
        self._dir = Path(log_dir)
        self._seen: dict[tuple[str, str], tuple[int, float]] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> SignalEventLogger | None:
        """Build from ``RT_SIGNAL_EVENT_LOG_DIR``; ``None`` when unset (disabled)."""
        raw = os.environ.get("RT_SIGNAL_EVENT_LOG_DIR", "").strip()
        return cls(raw) if raw else None

    def _path_for(self, now_epoch: float) -> Path:
        day = datetime.fromtimestamp(now_epoch, UTC).strftime("%Y-%m-%d")
        return self._dir / f"signal_events_{day}.jsonl"

    def _is_fresh(self, key: tuple[str, str], strength: int, now_epoch: float) -> bool:
        prev = self._seen.get(key)
        # New (symbol,direction) or a strengthen (A2→A1→A0). A *weaker* re-detect
        # or a same-level re-detect is not a new event.
        return prev is None or strength > prev[0]

    def record(self, signals: list[Any], *, now: float | None = None) -> int:
        """Append rows for signals that are newly-fresh or newly-strengthened.

        Returns the number of rows written. Never raises.
        """
        now_epoch = time.time() if now is None else now
        rows: list[dict[str, Any]] = []
        try:
            with self._lock:
                for s in signals:
                    level = str(getattr(s, "level", ""))
                    strength = _STRENGTH.get(level, 0)
                    if strength == 0:
                        continue
                    key = (str(getattr(s, "symbol", "")).upper(), str(getattr(s, "direction", "")))
                    if not self._is_fresh(key, strength, now_epoch):
                        continue
                    self._seen[key] = (strength, now_epoch)
                    rows.append(event_row(s, now_epoch=now_epoch))
                # Bound the dedup map: drop keys untouched for the TTL.
                stale = [k for k, (_st, t) in self._seen.items() if now_epoch - t > _STATE_TTL_SECS]
                for k in stale:
                    self._seen.pop(k, None)
            if not rows:
                return 0
            self._dir.mkdir(parents=True, exist_ok=True)
            path = self._path_for(now_epoch)
            with path.open("a", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, allow_nan=False) + "\n")
            return len(rows)
        except Exception:  # best-effort logger — must never break the poll loop
            logger.debug("signal-event log write failed", exc_info=True)
            return 0
