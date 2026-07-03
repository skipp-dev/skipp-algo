"""Regression tests for WP-A (pipeline/data/ops audit, CRIT).

A single future-dated news item must never advance the persisted cursor
past ``now + skew``. Otherwise the ``> min_cursor`` filter in
``filter_news_items_since`` silently drops ALL real news until wall-clock
catches up with the bogus timestamp.
"""

from __future__ import annotations

import math
import time

from hypothesis import assume, given
from hypothesis import strategies as st

from newsstack_fmp.common_types import NewsItem
from newsstack_fmp.shared_fetch import _MAX_FUTURE_SKEW_SECS, _clamped_cursor


def _item(published_ts: float, item_id: str = "x") -> NewsItem:
    return NewsItem(
        provider="fmp_stock_latest",
        item_id=item_id,
        published_ts=published_ts,
        updated_ts=published_ts,
        headline="h",
        snippet="",
        tickers=["AAPL"],
        url=None,
        source="src",
    )


def test_future_item_does_not_jump_cursor_past_now() -> None:
    now = time.time()
    future = now + 365 * 24 * 3600  # a full year in the future
    items = [_item(now - 60, "a"), _item(future, "b")]

    cursor = _clamped_cursor(0.0, items, now=now)

    # cursor must not exceed now + skew, so the next poll still sees
    # newly published (real) items.
    assert cursor <= now + 300.0
    # and the plausible recent item should still advance the cursor
    assert cursor >= now - 60


def test_all_future_items_keep_cursor_at_floor() -> None:
    now = time.time()
    items = [_item(now + 10_000, "a"), _item(now + 20_000, "b")]

    cursor = _clamped_cursor(1234.0, items, now=now)

    # No plausible items → cursor stays at the existing floor (min_cursor),
    # never jumping into the future.
    assert cursor == 1234.0


def test_cursor_advances_to_latest_plausible_item() -> None:
    now = time.time()
    items = [_item(now - 300, "a"), _item(now - 100, "b"), _item(now - 200, "c")]

    cursor = _clamped_cursor(0.0, items, now=now)

    assert cursor == now - 100


# --------------------------------------------------------------------------- #
# Audit F1: self-heal a cursor poisoned before this clamp shipped
# --------------------------------------------------------------------------- #
def test_poisoned_floor_self_heals() -> None:
    now = 1_800_000_000.0
    poisoned = now + 86_400.0 * 30  # cursor 30 days in the future
    cursor = _clamped_cursor(poisoned, [], now=now)
    assert cursor == now + _MAX_FUTURE_SKEW_SECS


def test_nan_min_cursor_resets_to_zero() -> None:
    assert _clamped_cursor(float("nan"), [], now=1_800_000_000.0) == 0.0


def test_inf_min_cursor_resets_to_zero() -> None:
    assert _clamped_cursor(float("inf"), [], now=1_800_000_000.0) == 0.0


def test_negative_min_cursor_resets_to_zero() -> None:
    assert _clamped_cursor(-500.0, [], now=1_800_000_000.0) == 0.0


def test_negative_now_returns_sanitized_floor() -> None:
    assert _clamped_cursor(float("nan"), [], now=-1.0) == 0.0
    assert _clamped_cursor(1234.0, [], now=-1.0) == 1234.0


# --------------------------------------------------------------------------- #
# Property-based tests
# --------------------------------------------------------------------------- #
_EPOCH = st.one_of(
    st.floats(min_value=0.0, max_value=2_000_000_000.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.0, max_value=1e12, allow_nan=False, allow_infinity=False),
)


@given(min_cursor=_EPOCH, now=_EPOCH, items=st.lists(_EPOCH, max_size=20))
def test_cursor_never_exceeds_future_ceiling(min_cursor: float, now: float, items: list[float]) -> None:
    news_items = [_item(ts) for ts in items]
    cursor = _clamped_cursor(min_cursor, news_items, now=now)
    ceiling = now + _MAX_FUTURE_SKEW_SECS
    if math.isfinite(now) and math.isfinite(ceiling):
        assert cursor <= ceiling
    assert not math.isnan(cursor)
    assert cursor >= 0.0


@given(min_cursor=_EPOCH, now=_EPOCH, items=st.lists(_EPOCH, max_size=20))
def test_cursor_is_at_least_floor_while_plausible(min_cursor: float, now: float, items: list[float]) -> None:
    """Monotonic ONLY while the floor is plausible; a poisoned floor self-heals
    down to the ceiling, so monotonicity does not apply there."""
    news_items = [_item(ts) for ts in items]
    cursor = _clamped_cursor(min_cursor, news_items, now=now)
    floor = max(float(min_cursor or 0.0), 0.0)
    ceiling = now + _MAX_FUTURE_SKEW_SECS
    if math.isfinite(floor) and math.isfinite(now) and floor <= ceiling:
        assert cursor >= floor


@given(min_cursor=_EPOCH, now=_EPOCH)
def test_all_future_items_clamp_to_floor_or_ceiling(min_cursor: float, now: float) -> None:
    assume(math.isfinite(now))
    future_items = [
        _item(now + _MAX_FUTURE_SKEW_SECS + 1000.0),
        _item(now + _MAX_FUTURE_SKEW_SECS + 2000.0),
    ]
    cursor = _clamped_cursor(min_cursor, future_items, now=now)
    floor = max(float(min_cursor or 0.0), 0.0)
    ceiling = now + _MAX_FUTURE_SKEW_SECS
    if math.isfinite(floor):
        assert cursor == (floor if floor <= ceiling else ceiling)


def test_cursor_uses_updated_ts_when_newer() -> None:
    now = 1_700_000_000.0
    item = NewsItem(
        provider="fmp_stock_latest",
        item_id="x",
        published_ts=now - 100.0,
        updated_ts=now - 10.0,
        headline="h",
        snippet="",
        tickers=["AAPL"],
        url=None,
        source="src",
    )
    assert _clamped_cursor(0.0, [item], now=now) == now - 10.0
