"""Regression tests for WP-A (pipeline/data/ops audit, CRIT).

A single future-dated news item must never advance the persisted cursor
past ``now + skew``. Otherwise the ``> min_cursor`` filter in
``filter_news_items_since`` silently drops ALL real news until wall-clock
catches up with the bogus timestamp.
"""

from __future__ import annotations

import time

from newsstack_fmp.common_types import NewsItem
from newsstack_fmp.shared_fetch import _clamped_cursor


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
