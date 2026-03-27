"""Market-session window resolution for the Databento pipeline.

Provides the ``WindowDefinition`` dataclass and helpers that convert
human-readable "pre-open N minutes / post-open M minutes" specifications
into concrete UTC fetch boundaries for a given trade date and display
timezone.

Backward compatibility:  all names exported from this module are still
importable from ``databento_volatility_screener`` via re-export shims.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from databento_utils import US_EASTERN_TZ, resolve_display_timezone

# ── Default window parameters ──────────────────────────────────────────────

# ET-relative defaults for the intraday screening window
DEFAULT_INTRADAY_PRE_OPEN_MINUTES = 10
DEFAULT_INTRADAY_POST_OPEN_MINUTES = 30
# ET-relative defaults for the open window detail
DEFAULT_OPEN_WINDOW_PRE_OPEN_MINUTES = 1
DEFAULT_OPEN_WINDOW_POST_OPEN_SECONDS = 5 * 60 + 59  # 5:59 after open
# ET-relative defaults for close-imbalance detail
DEFAULT_CLOSE_IMBALANCE_WINDOW_START_ET = time(15, 50)
DEFAULT_CLOSE_IMBALANCE_AUCTION_TIME_ET = time(16, 0)
DEFAULT_CLOSE_IMBALANCE_WINDOW_END_ET = time(16, 5)
DEFAULT_CLOSE_IMBALANCE_AFTERHOURS_END_ET = time(20, 0)
DEFAULT_CLOSE_IMBALANCE_NEXT_DAY_OUTCOME_TIME_ET = time(10, 0)


# ── Dataclass ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class WindowDefinition:
    trade_date: date
    display_timezone: str
    window_start_local: datetime
    window_end_local: datetime
    fetch_start_utc: datetime
    fetch_end_utc: datetime
    regular_open_utc: datetime
    premarket_anchor_utc: datetime


# ── Window builders ────────────────────────────────────────────────────────

def compute_market_relative_window(
    trade_date: date,
    display_timezone: str,
    *,
    pre_open_minutes: int = DEFAULT_INTRADAY_PRE_OPEN_MINUTES,
    post_open_minutes: int = DEFAULT_INTRADAY_POST_OPEN_MINUTES,
    post_open_seconds: int | None = None,
) -> tuple[time, time]:
    if pre_open_minutes < 0:
        raise ValueError(f"pre_open_minutes must be >= 0, got {pre_open_minutes}")
    if post_open_minutes < 0:
        raise ValueError(f"post_open_minutes must be >= 0, got {post_open_minutes}")
    if post_open_seconds is not None and post_open_seconds < 0:
        raise ValueError(f"post_open_seconds must be >= 0, got {post_open_seconds}")
    tz = resolve_display_timezone(display_timezone)
    regular_open_local = datetime.combine(trade_date, time(9, 30), tzinfo=US_EASTERN_TZ).astimezone(tz)
    start_local = regular_open_local - timedelta(minutes=pre_open_minutes)
    if post_open_seconds is not None:
        end_local = regular_open_local + timedelta(seconds=post_open_seconds)
    else:
        end_local = regular_open_local + timedelta(minutes=post_open_minutes)
    return start_local.time(), end_local.time()


def _resolve_window_for_date(
    trade_date: date,
    display_timezone: str,
    window_start: time | None,
    window_end: time | None,
    *,
    default_pre_open_minutes: int = DEFAULT_INTRADAY_PRE_OPEN_MINUTES,
    default_post_open_minutes: int = DEFAULT_INTRADAY_POST_OPEN_MINUTES,
    default_post_open_seconds: int | None = None,
) -> tuple[time, time]:
    if window_start is not None and window_end is not None:
        return window_start, window_end
    return compute_market_relative_window(
        trade_date,
        display_timezone,
        pre_open_minutes=default_pre_open_minutes,
        post_open_minutes=default_post_open_minutes,
        post_open_seconds=default_post_open_seconds,
    )


def build_window_definition(
    trade_date: date,
    *,
    display_timezone: str,
    window_start: time,
    window_end: time,
    premarket_anchor_et: time,
) -> WindowDefinition:
    tz = resolve_display_timezone(display_timezone)
    local_start = datetime.combine(trade_date, window_start, tzinfo=tz)
    local_end = datetime.combine(trade_date, window_end, tzinfo=tz)
    if local_end <= local_start:
        raise ValueError("Window end must be after window start")
    regular_open_utc = datetime.combine(trade_date, time(9, 30), tzinfo=US_EASTERN_TZ).astimezone(UTC)
    premarket_anchor_utc = datetime.combine(trade_date, premarket_anchor_et, tzinfo=US_EASTERN_TZ).astimezone(UTC)
    fetch_start_utc = min(local_start.astimezone(UTC), premarket_anchor_utc)
    fetch_end_utc = local_end.astimezone(UTC)
    return WindowDefinition(
        trade_date=trade_date,
        display_timezone=display_timezone,
        window_start_local=local_start,
        window_end_local=local_end,
        fetch_start_utc=fetch_start_utc,
        fetch_end_utc=fetch_end_utc,
        regular_open_utc=regular_open_utc,
        premarket_anchor_utc=premarket_anchor_utc,
    )
