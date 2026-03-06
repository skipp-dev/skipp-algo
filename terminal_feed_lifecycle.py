"""Overnight / weekend feed lifecycle management.

Handles:
1. Auto-clear stale weekend data on Monday pre-market
2. Pre-seed the feed with pre-market news 30 min before NYSE open
3. Detect session gaps and manage SQLite dedup state

The main entry point is ``manage_feed_lifecycle()`` which should be
called on every Streamlit rerun cycle.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _now_et() -> datetime:
    """Return current time in US/Eastern."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        try:
            from dateutil.tz import gettz

            return datetime.now(gettz("America/New_York"))
        except Exception:
            from datetime import timezone

            logger.debug("zoneinfo + dateutil unavailable, using UTC-4 fallback", exc_info=True)
            return datetime.now(timezone.utc) - timedelta(hours=4)


def _minutes_since_midnight(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


# NYSE regular session: 09:30 – 16:00 ET
_NYSE_OPEN_MIN = 9 * 60 + 30   # 570
_NYSE_CLOSE_MIN = 16 * 60      # 960
_PREMARKET_START_MIN = 4 * 60  # 04:00 ET
_PRESEED_WINDOW_MIN = 30       # pre-seed 30 min before open
_STALE_RECOVERY_COOLDOWN_S = 180.0  # 3 min between auto-recovery attempts
_STALE_RECOVERY_GRACE_S = 90.0  # 90s grace after recovery before re-checking


def is_weekend(dt: datetime | None = None) -> bool:
    """True on Saturday (5) or Sunday (6)."""
    dt = dt or _now_et()
    return dt.weekday() >= 5


def is_premarket_window(dt: datetime | None = None) -> bool:
    """True during the 30-minute pre-seed window (09:00–09:30 ET, Mon-Fri).

    This is when we want to pre-seed the feed with pre-market news
    so that traders have fresh data at the opening bell.
    """
    dt = dt or _now_et()
    if dt.weekday() >= 5:
        return False
    mins = _minutes_since_midnight(dt)
    return (_NYSE_OPEN_MIN - _PRESEED_WINDOW_MIN) <= mins < _NYSE_OPEN_MIN


def is_market_hours(dt: datetime | None = None) -> bool:
    """True during extended hours (04:00–20:00 ET, Mon-Fri)."""
    dt = dt or _now_et()
    if dt.weekday() >= 5:
        return False
    return 4 <= dt.hour < 20


def is_off_hours(dt: datetime | None = None) -> bool:
    """True outside extended hours or on weekends."""
    return not is_market_hours(dt)


# ---------------------------------------------------------------------------
# Feed staleness detection
# ---------------------------------------------------------------------------


def feed_staleness_minutes(feed: list[dict[str, Any]]) -> float | None:
    """Return the age of the newest item in minutes, or None if empty."""
    if not feed:
        return None
    newest_ts = max((d.get("published_ts") or 0 for d in feed), default=0)
    if newest_ts <= 0:
        return None
    return (time.time() - newest_ts) / 60


def is_feed_stale(feed: list[dict[str, Any]], max_age_min: float = 120,
                  last_ingest_ts: float = 0.0) -> bool:
    """True if the newest feed item is older than max_age_min.

    If *last_ingest_ts* is provided and recent (within 2× max_age_min),
    the feed is NOT considered stale — the API returned articles that
    happen to have old publication timestamps but data IS flowing.
    """
    # If we ingested data recently, the feed is alive regardless of published_ts
    if last_ingest_ts > 0:
        ingest_age_min = (time.time() - last_ingest_ts) / 60
        if ingest_age_min < max_age_min * 2:
            return False
    age = feed_staleness_minutes(feed)
    if age is None:
        return True  # empty feed is stale
    return age > max_age_min


# ---------------------------------------------------------------------------
# Lifecycle actions
# ---------------------------------------------------------------------------


class FeedLifecycleManager:
    """Manages feed state transitions across sessions.

    Tracks whether weekend-clear and pre-seed actions have already
    been performed this session to avoid repeating them on every rerun.

    Parameters
    ----------
    jsonl_path : str
        Path to the terminal JSONL feed file.
    sqlite_path : str
        Path to the SQLite dedup store.
    feed_max_age_s : float
        Maximum age for feed items (seconds).
    """

    def __init__(
        self,
        jsonl_path: str = "artifacts/terminal_feed.jsonl",
        sqlite_path: str = "newsstack_fmp/terminal_state.db",
        feed_max_age_s: float = 14400.0,
    ) -> None:
        self.jsonl_path = jsonl_path
        self.sqlite_path = sqlite_path
        self.feed_max_age_s = feed_max_age_s

        # Session flags — prevent repeating actions on every rerun
        self._weekend_cleared: bool = False
        self._preseed_done: bool = False
        self._last_lifecycle_check: float = 0.0
        self._last_stale_recovery_ts: float = 0.0
        self._last_ingest_ts: float = 0.0
        # Date of last weekend clear (to only clear once per Monday)
        self._weekend_clear_date: str = ""

    def notify_ingest(self) -> None:
        """Record that items were just ingested from the BG poller.

        This timestamp is used by ``is_feed_stale`` to avoid false
        positives when the API returns articles with old ``published_ts``
        but data IS actually flowing.
        """
        self._last_ingest_ts = time.time()

    def should_clear_weekend_data(self) -> bool:
        """True on Monday pre-market if stale weekend data hasn't been cleared yet."""
        if self._weekend_cleared:
            return False
        now = _now_et()
        # Monday (0) before market open
        if now.weekday() != 0:
            return False
        mins = _minutes_since_midnight(now)
        # Clear between 03:30 and 09:30 ET (before open)
        if mins < 3 * 60 + 30 or mins >= _NYSE_OPEN_MIN:
            return False
        # Only clear once per Monday
        today = now.strftime("%Y-%m-%d")
        if self._weekend_clear_date == today:
            self._weekend_cleared = True
            return False
        return True

    def clear_weekend_data(self, store: Any) -> dict[str, Any]:
        """Clear stale weekend data from JSONL + SQLite.

        Returns a summary dict of what was cleared.
        """
        result: dict[str, Any] = {"action": "weekend_clear", "cleared": False}

        try:
            # Clear JSONL
            if self.jsonl_path and os.path.isfile(self.jsonl_path):
                from terminal_export import rewrite_jsonl

                rewrite_jsonl(self.jsonl_path, [])
                result["jsonl_cleared"] = True
                logger.info("Weekend clear: JSONL emptied")

            # Full SQLite prune
            store.prune_seen(keep_seconds=0.0)
            store.prune_clusters(keep_seconds=0.0)
            result["sqlite_cleared"] = True
            logger.info("Weekend clear: SQLite dedup tables emptied")

            result["cleared"] = True
        except Exception as exc:
            logger.warning("Weekend clear failed: %s", exc, exc_info=True)
            result["error"] = type(exc).__name__

        now = _now_et()
        self._weekend_cleared = True
        self._weekend_clear_date = now.strftime("%Y-%m-%d")
        return result

    def should_preseed(self) -> bool:
        """True during the pre-market pre-seed window if not yet done."""
        if self._preseed_done:
            return False
        return is_premarket_window()

    def mark_preseed_done(self) -> None:
        """Mark pre-seed as complete for this session."""
        self._preseed_done = True

    def get_off_hours_poll_interval(self, base_interval: float) -> float:
        """Return a longer poll interval during off-hours to save API quota.

        During market hours: returns base_interval (unchanged)
        During pre-market (04:00-09:30): returns base_interval * 2
        During after-hours (16:00-20:00): returns base_interval * 3
        During weekends: returns max(90, base_interval * 6)
        During night (20:00-04:00): returns max(60, base_interval * 4)
        """
        now = _now_et()
        if is_weekend(now):
            return max(90.0, base_interval * 6)

        mins = _minutes_since_midnight(now)
        if now.weekday() < 5:
            if _PREMARKET_START_MIN <= mins < _NYSE_OPEN_MIN:
                # Pre-market: slightly slower
                return base_interval * 2
            if _NYSE_OPEN_MIN <= mins < _NYSE_CLOSE_MIN:
                # Regular hours: full speed
                return base_interval
            if _NYSE_CLOSE_MIN <= mins < 20 * 60:
                # After-hours: slower
                return base_interval * 3
        # Off-hours: moderate throttle (×4) to save API quota
        # while still keeping data reasonably fresh.
        return max(60.0, base_interval * 4)

    def manage(
        self,
        feed: list[dict[str, Any]],
        store: Any,
    ) -> dict[str, Any]:
        """Run lifecycle checks. Call on every Streamlit rerun.

        Returns a dict with any actions taken.  When ``feed_action``
        is ``"stale_recovery"`` the caller should reset its cursor to
        ``None`` and trigger an immediate re-poll so the API returns
        the latest articles without an ``updatedSince`` filter.
        """
        # Throttle: only check every 30 seconds
        now = time.time()
        if now - self._last_lifecycle_check < 30:
            return {"action": "throttled"}
        self._last_lifecycle_check = now

        result: dict[str, Any] = {"action": "check"}

        # 1. Weekend clear (Monday only)
        if self.should_clear_weekend_data():
            clear_result = self.clear_weekend_data(store)
            result["weekend_clear"] = clear_result
            if clear_result.get("cleared"):
                result["feed_action"] = "cleared"
                return result

        # 2. Stale-data auto-recovery (all hours)
        #    During market hours (04:00-20:00 ET): trigger when feed > 5 min old.
        #    During off-hours / weekends: trigger when feed > 15 min old
        #    (articles are still published but less frequently).
        #    Guarded by a cooldown so we don't reset every 30 s if the
        #    API genuinely has no new articles.
        _stale_threshold = 5.0 if is_market_hours() else 15.0
        _last_ingest = getattr(self, '_last_ingest_ts', 0.0)
        # Grace period: skip stale check entirely right after a recovery
        # to give the BG poller time to fetch and deliver items.
        _in_grace = (now - self._last_stale_recovery_ts) < _STALE_RECOVERY_GRACE_S
        if not _in_grace and is_feed_stale(feed, max_age_min=_stale_threshold,
                                            last_ingest_ts=_last_ingest):
            staleness = feed_staleness_minutes(feed)
            result["feed_stale"] = True
            result["staleness_min"] = staleness

            cooldown_ok = (now - self._last_stale_recovery_ts) >= _STALE_RECOVERY_COOLDOWN_S
            if cooldown_ok:
                # Each prune is independent — one failing must not block the other.
                for _prune_fn, _tbl in (
                    (store.prune_seen, "seen"),
                    (store.prune_clusters, "clusters"),
                ):
                    try:
                        _prune_fn(keep_seconds=0.0)
                    except Exception as exc:
                        logger.warning("Stale-recovery prune(%s) failed: %s", _tbl, exc, exc_info=True)
                self._last_stale_recovery_ts = now
                result["feed_action"] = "stale_recovery"
                _phase = "market hours" if is_market_hours() else "off-hours"
                logger.info(
                    "Stale-recovery triggered: feed %.0f min old during %s — "
                    "cursor reset + dedup pruned",
                    staleness or 0, _phase,
                )

        # 3. Pre-seed window detection
        if self.should_preseed():
            result["preseed_needed"] = True

        return result

    def get_status_display(self) -> dict[str, str]:
        """Return human-readable status for the dashboard."""
        now = _now_et()
        mins = _minutes_since_midnight(now)

        if is_weekend(now):
            phase = "🌙 Weekend"
        elif mins < _PREMARKET_START_MIN:
            phase = "🌙 Off-hours"
        elif mins < _NYSE_OPEN_MIN - _PRESEED_WINDOW_MIN:
            phase = "🌅 Pre-market (early)"
        elif mins < _NYSE_OPEN_MIN:
            phase = "🔔 Pre-market (pre-seed)"
        elif mins < _NYSE_CLOSE_MIN:
            phase = "📈 Market hours"
        elif mins < 20 * 60:
            phase = "🌆 After-hours"
        else:
            phase = "🌙 Off-hours"

        return {
            "phase": phase,
            "time_et": now.strftime("%H:%M ET"),
            "weekend_cleared": "✅" if self._weekend_cleared else "—",
            "preseed_done": "✅" if self._preseed_done else "—",
        }
