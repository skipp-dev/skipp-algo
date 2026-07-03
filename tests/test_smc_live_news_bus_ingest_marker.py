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


# --------------------------------------------------------------------------- #
# WP-3: producer-start bootstrap for a never-ingested pipeline
# --------------------------------------------------------------------------- #
from typing import Any
from unittest.mock import patch


def _dummy_score(**overrides: Any) -> Any:
    defaults = {
        "category": "other",
        "impact": 0.5,
        "clarity": 0.6,
        "polarity": 0.0,
        "score": 0.5,
        "cluster_hash": "deadbeef",
        "relevance": 0.5,
        "entity_count": 1,
    }
    defaults.update(overrides)
    return type("ScoreResult", (), defaults)()


def _patch_fetchers(mock_results: dict[str, Any]) -> list[Any]:
    def _make(provider: str):
        def _fetch(*_args: Any, **_kwargs: Any) -> Any:
            return mock_results.get(provider, bus.ProviderPollResult(provider=provider))

        return _fetch

    return [
        patch.object(bus, "fetch_live_news_benzinga", _make("benzinga")),
        patch.object(bus, "fetch_live_news_benzinga_quantified", _make("benzinga_quantified")),
        patch.object(bus, "fetch_live_news_fmp_stock", _make("fmp_stock")),
        patch.object(bus, "fetch_live_news_fmp_press", _make("fmp_press")),
        patch.object(bus, "fetch_live_news_fmp_articles", _make("fmp_articles")),
        patch.object(bus, "fetch_live_news_newsapi_ai", _make("newsapi_ai")),
        patch.object(bus, "fetch_live_news_tv", _make("tv")),
        patch.object(bus, "classify_and_score", lambda _item, cluster_count, chash=None: _dummy_score()),
    ]


def _run_bus(*, state: dict[str, Any] | None, now_ts: float, mock_results: dict[str, Any]) -> tuple[dict, dict]:
    patches = _patch_fetchers(mock_results)
    for p in patches:
        p.start()
    try:
        return bus.poll_live_news_bus(
            symbols=["AAPL"],
            state=state,
            now_ts=now_ts,
            include_benzinga=True,
            include_fmp=False,
            include_newsapi_ai=False,
            include_tradingview=False,
            include_fmp_articles=False,
        )
    finally:
        for p in reversed(patches):
            p.stop()


def test_fresh_state_bootstraps_marker_without_new_story() -> None:
    """A state that has NEVER ingested (no marker) and gets no new story this
    run must bootstrap ``last_ingest_success_at`` to producer start, NOT stay
    at 0.0 — otherwise ingest_age_known never arms and the stale alert is
    silenced for exactly the broken-from-deploy case it guards."""
    now_ts = 1_700_000_000.0
    snapshot, next_state = _run_bus(
        state=None,
        now_ts=now_ts,
        mock_results={
            "benzinga": bus.ProviderPollResult(provider="benzinga", items=[], raw_count=0, cursor=0.0),
        },
    )
    assert snapshot["last_ingest_success_at"] == now_ts
    assert next_state["last_ingest_success_at"] == now_ts


def test_existing_marker_not_overwritten_by_bootstrap() -> None:
    """A state with a real prior marker must be preserved, not reset to now."""
    now_ts = 1_700_000_000.0
    prior = now_ts - 3_600.0
    snapshot, _ = _run_bus(
        state={"last_ingest_success_at": prior},
        now_ts=now_ts,
        mock_results={
            "benzinga": bus.ProviderPollResult(provider="benzinga", items=[], raw_count=0, cursor=0.0),
        },
    )
    assert snapshot["last_ingest_success_at"] == prior
