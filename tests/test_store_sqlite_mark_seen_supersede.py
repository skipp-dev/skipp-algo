"""Regression tests for WP-B3 (pipeline/data/ops audit, HIGH).

``mark_seen`` must reprocess a strictly newer update to an already-seen story
(corrections, escalations) while still deduping same/older timestamps.
"""

from __future__ import annotations

from newsstack_fmp.store_sqlite import SqliteStore


def test_brand_new_item_is_processed() -> None:
    store = SqliteStore(":memory:")
    assert store.mark_seen("p", "id1", 100.0) is True


def test_same_timestamp_is_duplicate() -> None:
    store = SqliteStore(":memory:")
    assert store.mark_seen("p", "id1", 100.0) is True
    assert store.mark_seen("p", "id1", 100.0) is False


def test_older_timestamp_is_duplicate() -> None:
    store = SqliteStore(":memory:")
    assert store.mark_seen("p", "id1", 100.0) is True
    assert store.mark_seen("p", "id1", 50.0) is False


def test_newer_update_is_reprocessed_and_supersedes() -> None:
    store = SqliteStore(":memory:")
    assert store.mark_seen("p", "id1", 100.0) is True
    # newer update → reprocess
    assert store.mark_seen("p", "id1", 200.0) is True
    # the stored ts now advanced to 200, so 200 is a duplicate again
    assert store.mark_seen("p", "id1", 200.0) is False
    # and an older-than-200 update is still a duplicate
    assert store.mark_seen("p", "id1", 150.0) is False
