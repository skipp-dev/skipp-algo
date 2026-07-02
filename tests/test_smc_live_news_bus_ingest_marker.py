"""Regression tests for WP-C1c (pipeline/data/ops audit, MED).

``last_ingest_success_at`` must advance only when new items are accepted and
survive a state roundtrip so the daemon can key a 'news not flowing' alert on
actual ingest instead of the always-fresh producer tick (generated_at).
"""

from __future__ import annotations

from scripts import smc_live_news_bus as bus


def test_normalize_state_preserves_last_ingest_success_at() -> None:
    state = bus._normalize_state({"last_ingest_success_at": 1_700_000_000.0})
    assert state["last_ingest_success_at"] == 1_700_000_000.0


def test_normalize_state_defaults_last_ingest_to_zero() -> None:
    state = bus._normalize_state(None)
    assert state["last_ingest_success_at"] == 0.0


def test_normalize_state_coerces_invalid_last_ingest_to_zero() -> None:
    state = bus._normalize_state({"last_ingest_success_at": "not-a-number"})
    assert state["last_ingest_success_at"] == 0.0
