from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from newsstack_fmp.common_types import NewsItem
from newsstack_fmp.shared_fetch import CachedNewsBatch
from scripts import smc_live_news_bus as bus
from scripts.smc_newsapi_ai import NewsApiAiProviderError

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_json_fixture(name: str) -> dict[str, Any]:
    payload = json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))
    return cast(dict[str, Any], payload)


def _story_entry_for_replay(entry: dict[str, Any], *, first_seen_ts: float) -> dict[str, Any]:
    return {
        **entry,
        "tickers": list(entry["tickers"]),
        "providers": list(entry["providers"]),
        "provider_names": list(entry["provider_names"]),
        "sources": list(entry["sources"]),
        "first_seen_ts": first_seen_ts,
    }


def _candidate(
    provider_bucket: str,
    provider_name: str,
    headline: str,
    tickers: tuple[str, ...],
    published_ts: float,
    *,
    source: str,
    item_id: str,
) -> bus.LiveNewsCandidate:
    return bus.LiveNewsCandidate(
        provider_bucket=provider_bucket,
        provider_name=provider_name,
        item_id=item_id,
        headline=headline,
        tickers=tickers,
        published_ts=published_ts,
        updated_ts=published_ts,
        url=f"https://example.test/{item_id}",
        source=source,
    )


def test_poll_live_news_bus_deduplicates_across_providers_and_tracks_cursors() -> None:
    now_ts = 1_750_000_000.0
    shared_headline = "AAPL raises guidance after earnings beat"

    with (
        patch.object(
            bus,
            "fetch_live_news_benzinga",
            return_value=bus.ProviderPollResult(
                provider="benzinga",
                items=[
                    _candidate(
                        "benzinga",
                        "benzinga_rest",
                        shared_headline,
                        ("AAPL",),
                        now_ts - 60.0,
                        source="Benzinga",
                        item_id="bz-1",
                    )
                ],
                raw_count=1,
                cursor=now_ts - 50.0,
            ),
        ),
        patch.object(
            bus,
            "fetch_live_news_fmp_stock",
            return_value=bus.ProviderPollResult(
                provider="fmp_stock",
                items=[
                    _candidate(
                        "fmp_stock",
                        "fmp_stock_latest",
                        shared_headline,
                        ("AAPL",),
                        now_ts - 55.0,
                        source="Financial Modeling Prep",
                        item_id="fmp-1",
                    )
                ],
                raw_count=1,
                cursor=now_ts - 45.0,
            ),
        ),
        patch.object(
            bus,
            "fetch_live_news_fmp_press",
            return_value=bus.ProviderPollResult(provider="fmp_press", items=[], raw_count=0, cursor=0.0),
        ),
        patch.object(
            bus,
            "fetch_live_news_fmp_articles",
            return_value=bus.ProviderPollResult(provider="fmp_articles", items=[], raw_count=0, cursor=0.0),
        ),
        patch.object(
            bus,
            "fetch_live_news_tv",
            return_value=bus.ProviderPollResult(provider="tv", items=[], raw_count=0, cursor=0.0),
        ),
    ):
        snapshot, next_state = bus.poll_live_news_bus(
            symbols=["AAPL", "MSFT"],
            state=None,
            fmp_api_key="fmp",
            benzinga_api_key="benzinga",
            include_tradingview=True,
            now_ts=now_ts,
        )

    assert snapshot["summary"]["active_story_count"] == 1
    assert snapshot["summary"]["new_story_count"] == 1
    assert snapshot["provider_cursors"]["benzinga"] == now_ts - 50.0
    assert snapshot["provider_cursors"]["fmp_stock"] == now_ts - 45.0
    assert snapshot["legacy_cursor"] == now_ts - 45.0

    story = snapshot["stories"][0]
    assert story["first_provider"] == "benzinga"
    assert story["providers"] == ["benzinga", "fmp_stock"]
    assert story["provider_count"] == 2
    assert story["is_new"] is True

    by_symbol = snapshot["news_catalyst_by_symbol"]["AAPL"]
    assert by_symbol["mentions_24h"] == 1
    assert by_symbol["first_provider"] == "benzinga"
    assert by_symbol["news_catalyst_score"] > 0.0
    assert next_state["provider_cursors"]["legacy_cursor"] == now_ts - 45.0
    assert len(next_state["story_state"]) == 1


def test_poll_live_news_bus_keeps_first_provider_for_existing_story() -> None:
    now_ts = 1_750_100_000.0
    headline = "MSFT wins major cloud contract"
    cluster, story_key = bus._story_key(headline, ("MSFT",), now_ts - 120.0)
    initial_state = {
        "provider_cursors": {
            "benzinga": now_ts - 100.0,
            "fmp_stock": now_ts - 100.0,
            "fmp_press": 0.0,
            "tv": 0.0,
            "legacy_cursor": now_ts - 100.0,
        },
        "story_state": {
            story_key: {
                "story_key": story_key,
                "cluster_hash": cluster,
                "headline": headline,
                "tickers": ["MSFT"],
                "published_ts": now_ts - 120.0,
                "first_seen_ts": now_ts - 100.0,
                "first_provider": "benzinga",
                "providers": ["benzinga"],
                "provider_names": ["benzinga_rest"],
                "sources": ["Benzinga"],
                "url": "https://example.test/existing",
                "category": "contract",
                "impact": 0.7,
                "clarity": 0.8,
                "relevance": 0.75,
                "polarity": 0.5,
                "source_tier": "TIER_2",
                "source_rank": 2,
                "last_seen_ts": now_ts - 100.0,
            }
        },
    }

    with (
        patch.object(bus, "fetch_live_news_benzinga", return_value=bus.ProviderPollResult(provider="benzinga", items=[], raw_count=0, cursor=now_ts - 100.0)),
        patch.object(
            bus,
            "fetch_live_news_fmp_stock",
            return_value=bus.ProviderPollResult(
                provider="fmp_stock",
                items=[
                    _candidate(
                        "fmp_stock",
                        "fmp_stock_latest",
                        headline,
                        ("MSFT",),
                        now_ts - 110.0,
                        source="Reuters",
                        item_id="fmp-2",
                    )
                ],
                raw_count=1,
                cursor=now_ts - 90.0,
            ),
        ),
        patch.object(bus, "fetch_live_news_fmp_articles", return_value=bus.ProviderPollResult(provider="fmp_articles", items=[], raw_count=0, cursor=0.0)),
        patch.object(bus, "fetch_live_news_fmp_press", return_value=bus.ProviderPollResult(provider="fmp_press", items=[], raw_count=0, cursor=0.0)),
        patch.object(bus, "fetch_live_news_tv", return_value=bus.ProviderPollResult(provider="tv", items=[], raw_count=0, cursor=0.0)),
    ):
        snapshot, next_state = bus.poll_live_news_bus(
            symbols=["MSFT"],
            state=initial_state,
            fmp_api_key="fmp",
            benzinga_api_key="benzinga",
            include_tradingview=True,
            now_ts=now_ts,
        )

    story = snapshot["stories"][0]
    assert story["first_provider"] == "benzinga"
    assert story["providers"] == ["benzinga", "fmp_stock"]
    assert story["source_tier"] == "TIER_1"
    assert story["is_new"] is False
    assert next_state["story_state"][story_key]["first_provider"] == "benzinga"
    assert next_state["story_state"][story_key]["source_tier"] == "TIER_1"


def test_build_story_record_keeps_early_aging_high_conviction_story_actionable() -> None:
    published_ts = 1_775_700_960.0
    now_ts = published_ts + 132.0 * 60.0

    story = bus._build_story_record(
        {
            "story_key": "story-1",
            "headline": "Exxon Mobil Stock: War Effect On Earnings (NYSE:XOM)",
            "tickers": ["XOM"],
            "published_ts": published_ts,
            "first_provider": "newsapi_ai",
            "providers": ["newsapi_ai"],
            "provider_names": ["newsapi_ai"],
            "sources": ["Seeking Alpha"],
            "source_tier": "TIER_3",
            "source_rank": 3,
            "category": "earnings",
            "polarity": 0.0,
            "impact": 0.8,
            "clarity": 0.6,
            "relevance": 0.79,
            "first_seen_ts": now_ts,
        },
        now_ts=now_ts,
        is_new=True,
    )

    assert story["age_minutes"] == 132.0
    assert story["recency_bucket"] == "AGING"
    assert story["news_catalyst_score"] == 0.5162
    assert story["materiality"] == "MEDIUM"
    assert story["is_actionable"] is True


def test_historical_xom_replay_prevents_original_132_minute_regression() -> None:
    fixture = _load_json_fixture("live_news_xom_132_minute_case.json")
    base_entry = dict(fixture["entry"])
    historical_local = fixture["historical"]["local"]
    historical_remote = fixture["historical"]["remote"]
    replay_expected_remote = fixture["replay_expected"]["remote"]

    local_story = bus._build_story_record(
        _story_entry_for_replay(base_entry, first_seen_ts=historical_local["first_seen_ts"]),
        now_ts=historical_local["now_ts"],
        is_new=True,
    )
    remote_story = bus._build_story_record(
        _story_entry_for_replay(base_entry, first_seen_ts=historical_remote["first_seen_ts"]),
        now_ts=historical_remote["now_ts"],
        is_new=True,
    )

    assert historical_local["observed"]["is_actionable"] is True
    assert historical_remote["observed"]["is_actionable"] is False

    assert local_story["age_minutes"] == historical_local["observed"]["age_minutes"]
    assert local_story["news_catalyst_score"] == historical_local["observed"]["news_catalyst_score"]
    assert local_story["materiality"] == historical_local["observed"]["materiality"]
    assert local_story["recency_bucket"] == historical_local["observed"]["recency_bucket"]
    assert local_story["is_actionable"] is historical_local["observed"]["is_actionable"]

    assert remote_story["age_minutes"] == replay_expected_remote["age_minutes"]
    assert remote_story["news_catalyst_score"] == replay_expected_remote["news_catalyst_score"]
    assert remote_story["materiality"] == replay_expected_remote["materiality"]
    assert remote_story["recency_bucket"] == replay_expected_remote["recency_bucket"]
    assert remote_story["is_actionable"] is replay_expected_remote["is_actionable"]
    assert remote_story["news_catalyst_score"] > historical_remote["observed"]["news_catalyst_score"]


def test_historical_xom_replay_eventually_demotes_story_after_soft_aging_window() -> None:
    fixture = _load_json_fixture("live_news_xom_132_minute_case.json")
    base_entry = dict(fixture["entry"])
    replay_expected_remote = fixture["replay_expected"]["remote"]
    replay_expected_late_aging = fixture["replay_expected"]["late_aging"]

    late_aging_story = bus._build_story_record(
        _story_entry_for_replay(base_entry, first_seen_ts=replay_expected_late_aging["first_seen_ts"]),
        now_ts=replay_expected_late_aging["now_ts"],
        is_new=True,
    )

    assert late_aging_story["age_minutes"] == replay_expected_late_aging["age_minutes"]
    assert late_aging_story["news_catalyst_score"] == replay_expected_late_aging["news_catalyst_score"]
    assert late_aging_story["materiality"] == replay_expected_late_aging["materiality"]
    assert late_aging_story["recency_bucket"] == replay_expected_late_aging["recency_bucket"]
    assert late_aging_story["is_actionable"] is replay_expected_late_aging["is_actionable"]
    assert late_aging_story["news_catalyst_score"] < replay_expected_remote["news_catalyst_score"]


def test_build_story_record_demotes_older_aging_high_conviction_story() -> None:
    published_ts = 1_775_700_960.0
    now_ts = published_ts + 216.0 * 60.0

    story = bus._build_story_record(
        {
            "story_key": "story-1",
            "headline": "Exxon Mobil Stock: War Effect On Earnings (NYSE:XOM)",
            "tickers": ["XOM"],
            "published_ts": published_ts,
            "first_provider": "newsapi_ai",
            "providers": ["newsapi_ai"],
            "provider_names": ["newsapi_ai"],
            "sources": ["Seeking Alpha"],
            "source_tier": "TIER_3",
            "source_rank": 3,
            "category": "earnings",
            "polarity": 0.0,
            "impact": 0.8,
            "clarity": 0.6,
            "relevance": 0.79,
            "first_seen_ts": now_ts,
        },
        now_ts=now_ts,
        is_new=True,
    )

    assert story["age_minutes"] == 216.0
    assert story["recency_bucket"] == "AGING"
    assert story["news_catalyst_score"] == 0.4569
    assert story["materiality"] == "LOW"
    assert story["is_actionable"] is False


def test_resolve_live_news_symbols_from_base_csv_uses_adv_dollar_order(tmp_path: Path) -> None:
    base_csv = tmp_path / "base.csv"
    base_csv.write_text(
        "symbol,adv_dollar_rth_20d\n"
        "TSLA,2500000\n"
        "AAPL,5500000\n"
        "MSFT,4100000\n",
        encoding="utf-8",
    )

    symbols, metadata = bus.resolve_live_news_symbols(base_csv_path=base_csv, symbol_limit=2)

    assert symbols == ["AAPL", "MSFT"]
    assert metadata["mode"] == "base_csv"
    assert metadata["base_csv_path"] == str(base_csv)


def test_resolve_live_news_symbols_falls_back_to_release_policy_without_manifest(tmp_path: Path) -> None:
    export_dir = tmp_path / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    symbols, metadata = bus.resolve_live_news_symbols(export_dir=export_dir, symbol_limit=5)

    assert symbols == ["AAPL", "MSFT", "AMZN", "JPM", "JNJ"]
    assert metadata["mode"] == "release_policy_fallback"
    assert metadata["base_csv_path"] is None
    assert metadata["export_dir"] == str(export_dir)


def test_export_live_news_snapshot_writes_snapshot_and_state(tmp_path: Path) -> None:
    output_path = tmp_path / "smc_live_news_snapshot.json"
    state_path = tmp_path / "smc_live_news_state.json"

    fake_snapshot = {
        "summary": {
            "active_story_count": 1,
            "new_story_count": 1,
            "actionable_story_count": 1,
            "actionable_symbols": ["AAPL"],
            "symbol_count": 1,
        },
        "stories": [],
        "news_catalyst_by_symbol": {},
        "provider_cursors": {"benzinga": 1.0, "fmp_stock": 2.0, "fmp_press": 3.0, "tv": 4.0, "legacy_cursor": 4.0},
        "providers": {},
        "generated_at": "2025-01-01T00:00:00Z",
        "symbols": ["AAPL"],
        "legacy_cursor": 4.0,
    }
    fake_state = {
        "provider_cursors": {"benzinga": 1.0, "fmp_stock": 2.0, "fmp_press": 3.0, "tv": 4.0, "legacy_cursor": 4.0},
        "story_state": {},
    }

    with patch.object(bus, "poll_live_news_bus", return_value=(fake_snapshot, fake_state)):
        snapshot = bus.export_live_news_snapshot(
            symbols=["AAPL"],
            output_path=output_path,
            state_path=state_path,
            scope_metadata={"mode": "explicit"},
        )

    assert snapshot["symbol_scope"] == {"mode": "explicit"}
    assert json.loads(output_path.read_text(encoding="utf-8"))["symbol_scope"] == {"mode": "explicit"}
    assert json.loads(state_path.read_text(encoding="utf-8"))["provider_cursors"]["legacy_cursor"] == 4.0


def test_poll_live_news_bus_passes_and_persists_newsapi_feed_uri() -> None:
    now_ts = 1_750_200_000.0
    captured_kwargs: dict[str, object] = {}

    def _fake_newsapi(**kwargs):
        captured_kwargs.update(kwargs)
        return bus.ProviderPollResult(
            provider="newsapi_ai",
            items=[
                _candidate(
                    "newsapi_ai",
                    "newsapi_ai",
                    "AAPL spikes on fresh wire",
                    ("AAPL",),
                    now_ts - 30.0,
                    source="Reuters",
                    item_id="newsapi-1",
                )
            ],
            raw_count=1,
            cursor=now_ts - 20.0,
            meta={"last_seen_news_uri": "uri-feed-2"},
        )

    initial_state = {
        "provider_cursors": {
            "benzinga": 0.0,
            "fmp_stock": 0.0,
            "fmp_press": 0.0,
            "fmp_articles": 0.0,
            "newsapi_ai": now_ts - 60.0,
            "tv": 0.0,
            "legacy_cursor": now_ts - 60.0,
        },
        "provider_state": {
            "newsapi_ai": {
                "last_seen_news_uri": "uri-feed-1",
            }
        },
        "story_state": {},
    }

    with (
        patch.object(bus, "fetch_live_news_benzinga", return_value=bus.ProviderPollResult(provider="benzinga", items=[], raw_count=0, cursor=0.0)),
        patch.object(bus, "fetch_live_news_fmp_stock", return_value=bus.ProviderPollResult(provider="fmp_stock", items=[], raw_count=0, cursor=0.0)),
        patch.object(bus, "fetch_live_news_fmp_press", return_value=bus.ProviderPollResult(provider="fmp_press", items=[], raw_count=0, cursor=0.0)),
        patch.object(bus, "fetch_live_news_fmp_articles", return_value=bus.ProviderPollResult(provider="fmp_articles", items=[], raw_count=0, cursor=0.0)),
        patch.object(bus, "fetch_live_news_newsapi_ai", side_effect=_fake_newsapi),
        patch.object(bus, "fetch_live_news_tv", return_value=bus.ProviderPollResult(provider="tv", items=[], raw_count=0, cursor=0.0)),
    ):
        snapshot, next_state = bus.poll_live_news_bus(
            symbols=["AAPL"],
            state=initial_state,
            newsapi_ai_key="newsapi",
            include_tradingview=True,
            now_ts=now_ts,
        )

    assert captured_kwargs["article_feed_after_uri"] == "uri-feed-1"
    assert next_state["provider_state"]["newsapi_ai"]["last_seen_news_uri"] == "uri-feed-2"
    assert snapshot["providers"]["newsapi_ai"]["last_seen_news_uri"] == "uri-feed-2"


def test_poll_live_news_bus_exports_newsapi_no_recent_matches_status() -> None:
    now_ts = 1_750_250_000.0

    with (
        patch.object(bus, "fetch_live_news_benzinga", return_value=bus.ProviderPollResult(provider="benzinga", items=[], raw_count=0, cursor=0.0)),
        patch.object(bus, "fetch_live_news_fmp_stock", return_value=bus.ProviderPollResult(provider="fmp_stock", items=[], raw_count=0, cursor=0.0)),
        patch.object(bus, "fetch_live_news_fmp_press", return_value=bus.ProviderPollResult(provider="fmp_press", items=[], raw_count=0, cursor=0.0)),
        patch.object(bus, "fetch_live_news_fmp_articles", return_value=bus.ProviderPollResult(provider="fmp_articles", items=[], raw_count=0, cursor=0.0)),
        patch.object(
            bus,
            "fetch_live_news_newsapi_ai",
            return_value=bus.ProviderPollResult(
                provider="newsapi_ai",
                ok=True,
                items=[],
                raw_count=14,
                cursor=now_ts - 10.0,
                meta={
                    "last_seen_news_uri": "",
                    "provider_status": "ok_no_recent_matches",
                    "status_detail": "Event Registry reachable, but no new symbol-matching NewsAPI.ai items were newer than the current cursor.",
                },
            ),
        ),
        patch.object(bus, "fetch_live_news_tv", return_value=bus.ProviderPollResult(provider="tv", items=[], raw_count=0, cursor=0.0)),
    ):
        snapshot, _next_state = bus.poll_live_news_bus(
            symbols=["AAPL"],
            state={
                "provider_cursors": {
                    "benzinga": 0.0,
                    "fmp_stock": 0.0,
                    "fmp_press": 0.0,
                    "fmp_articles": 0.0,
                    "newsapi_ai": now_ts - 60.0,
                    "tv": 0.0,
                    "legacy_cursor": now_ts - 60.0,
                },
                "provider_state": {},
                "story_state": {},
            },
            newsapi_ai_key="newsapi",
            include_tradingview=True,
            now_ts=now_ts,
        )

    provider_payload = snapshot["providers"]["newsapi_ai"]
    assert provider_payload["provider_status"] == "ok_no_recent_matches"
    assert provider_payload["status_detail"] == "Event Registry reachable, but no new symbol-matching NewsAPI.ai items were newer than the current cursor."
    assert provider_payload["new_item_count"] == 0


def test_fetch_live_news_newsapi_ai_returns_no_recent_matches_status() -> None:
    raw_item = NewsItem(
        provider="newsapi_ai",
        item_id="event-1",
        published_ts=1_750_000_000.0,
        updated_ts=1_750_000_000.0,
        headline="AAPL older event coverage",
        snippet="snippet",
        tickers=["AAPL"],
        url=None,
        source="Event Registry",
        raw={
            "uri": "event-1",
            "newsapi_fetch_mode": "search_events",
        },
    )

    with patch.object(
        bus,
        "_fetch_cached_live_provider_batch",
        return_value=CachedNewsBatch(
            provider="newsapi_ai",
            scope={"symbols": ["AAPL"]},
            items=[],
            raw_items=[raw_item],
            raw_count=1,
            cursor=1_750_000_100.0,
            fetched_at=1_750_000_100.0,
            from_cache=False,
        ),
    ):
        result = bus.fetch_live_news_newsapi_ai(
            api_key="news-key",
            symbols=["AAPL"],
            cursor=1_750_000_050.0,
        )

    assert result.ok is True
    assert result.items == []
    assert result.meta["provider_status"] == "ok_no_recent_matches"
    assert result.meta["status_detail"] == "Event Registry reachable, but no new symbol-matching NewsAPI.ai items were newer than the current cursor."
    assert result.meta["last_seen_news_uri"] == ""


def test_poll_live_news_bus_redacts_provider_error_secrets() -> None:
    now_ts = 1_750_300_000.0

    def _raise_newsapi(**_kwargs):
        raise RuntimeError(
            "request failed https://eventregistry.org/api/v1/article/getArticles?apiKey=secret-token&keyword=AAPL"
        )

    with (
        patch.object(bus, "fetch_live_news_benzinga", return_value=bus.ProviderPollResult(provider="benzinga", items=[], raw_count=0, cursor=0.0)),
        patch.object(bus, "fetch_live_news_fmp_stock", return_value=bus.ProviderPollResult(provider="fmp_stock", items=[], raw_count=0, cursor=0.0)),
        patch.object(bus, "fetch_live_news_fmp_press", return_value=bus.ProviderPollResult(provider="fmp_press", items=[], raw_count=0, cursor=0.0)),
        patch.object(bus, "fetch_live_news_fmp_articles", return_value=bus.ProviderPollResult(provider="fmp_articles", items=[], raw_count=0, cursor=0.0)),
        patch.object(bus, "fetch_live_news_newsapi_ai", side_effect=_raise_newsapi),
        patch.object(bus, "fetch_live_news_tv", return_value=bus.ProviderPollResult(provider="tv", items=[], raw_count=0, cursor=0.0)),
    ):
        snapshot, _next_state = bus.poll_live_news_bus(
            symbols=["AAPL"],
            state=None,
            newsapi_ai_key="newsapi",
            include_tradingview=True,
            now_ts=now_ts,
        )

    error = snapshot["providers"]["newsapi_ai"]["error"]
    assert "apiKey=***" in error
    assert "secret-token" not in error


def test_fetch_live_news_newsapi_ai_returns_quota_exhausted_status() -> None:
    with patch.object(
        bus,
        "_fetch_cached_live_provider_batch",
        side_effect=NewsApiAiProviderError(
            "quota_exhausted",
            "Event Registry token quota exhausted or paid plan required",
            status_code=403,
        ),
    ):
        result = bus.fetch_live_news_newsapi_ai(
            api_key="news-key",
            symbols=["AAPL"],
            cursor=123.0,
        )

    assert result.ok is False
    assert result.error == "quota_exhausted: Event Registry token quota exhausted or paid plan required"
    assert result.meta["provider_status"] == "quota_exhausted"
    assert result.meta["error_code"] == "quota_exhausted"


def test_poll_live_news_bus_can_run_newsapi_only() -> None:
    now_ts = 1_750_310_000.0
    captured_kwargs: dict[str, object] = {}

    def _fake_newsapi(**kwargs):
        captured_kwargs.update(kwargs)
        return bus.ProviderPollResult(
            provider="newsapi_ai",
            items=[
                _candidate(
                    "newsapi_ai",
                    "newsapi_ai",
                    "AAPL moves on fresh Event Registry hit",
                    ("AAPL",),
                    now_ts - 15.0,
                    source="Event Registry",
                    item_id="newsapi-only-1",
                )
            ],
            raw_count=1,
            cursor=now_ts - 10.0,
            meta={"last_seen_news_uri": "uri-feed-3"},
        )

    with (
        patch.object(bus, "fetch_live_news_benzinga") as mock_benzinga,
        patch.object(bus, "fetch_live_news_fmp_stock") as mock_fmp_stock,
        patch.object(bus, "fetch_live_news_fmp_press") as mock_fmp_press,
        patch.object(bus, "fetch_live_news_fmp_articles") as mock_fmp_articles,
        patch.object(bus, "fetch_live_news_newsapi_ai", side_effect=_fake_newsapi),
        patch.object(bus, "fetch_live_news_tv") as mock_tv,
    ):
        snapshot, next_state = bus.poll_live_news_bus(
            symbols=["AAPL"],
            state=None,
            newsapi_ai_key="newsapi",
            include_benzinga=False,
            include_fmp=False,
            include_fmp_articles=False,
            include_tradingview=False,
            newsapi_lookback_days=1,
            newsapi_articles_per_request=50,
            now_ts=now_ts,
        )

    mock_benzinga.assert_not_called()
    mock_fmp_stock.assert_not_called()
    mock_fmp_press.assert_not_called()
    mock_fmp_articles.assert_not_called()
    mock_tv.assert_not_called()
    assert captured_kwargs["lookback_days"] == 1
    assert captured_kwargs["articles_per_request"] == 50
    assert snapshot["providers"]["benzinga"]["error"] == "disabled"
    assert snapshot["providers"]["fmp_stock"]["error"] == "disabled"
    assert snapshot["providers"]["tv"]["error"] == "disabled"
    assert snapshot["providers"]["newsapi_ai"]["new_item_count"] == 1
    assert next_state["provider_state"]["newsapi_ai"]["last_seen_news_uri"] == "uri-feed-3"


# ── Benzinga RSS migration (run 628 follow-up) ──────────────────────


def test_fetch_live_news_benzinga_uses_rss_adapter_not_rest() -> None:
    """The benzinga provider must use the free BenzingaRssAdapter (RSS feed),
    not the BenzingaRestAdapter (paid API). The REST adapter returned 401
    since the subscription lapsed (smc-library-refresh run 628, 2026-06-30).
    """
    from unittest.mock import MagicMock

    now_ts = 1_750_000_000.0
    item = NewsItem(
        provider="benzinga_rss",
        item_id="rss-1",
        headline="AAPL rallies",
        snippet="",
        published_ts=now_ts - 30.0,
        updated_ts=now_ts - 30.0,
        tickers=["AAPL"],
        url="https://benzinga.com/news/rss-1",
        source="Benzinga",
    )

    mock_adapter = MagicMock()
    mock_adapter.fetch_news.return_value = [item]

    def _passthrough_batch(*, provider, scope, cursor, fetcher):
        items = fetcher()
        return CachedNewsBatch(
            provider=provider, scope=scope or {}, items=items,
            raw_items=list(items), raw_count=len(items),
            cursor=max(cursor, *(it.published_ts for it in items), 0.0) if items else cursor,
            fetched_at=now_ts,
        )

    with (
        patch("scripts.smc_live_news_bus.BenzingaRssAdapter", return_value=mock_adapter),
        patch("scripts.smc_live_news_bus._fetch_cached_live_provider_batch", side_effect=_passthrough_batch),
    ):
        result = bus.fetch_live_news_benzinga(
            api_key="",  # empty key — must NOT disable the provider
            symbols=["AAPL"],
            cursor=0.0,
            page_size=50,
        )

    mock_adapter.fetch_news.assert_called_once()
    assert result.ok is True
    assert result.provider == "benzinga"
    assert len(result.items) == 1
    assert result.items[0].provider_name == "benzinga_rss"


def test_fetch_live_news_benzinga_works_without_api_key() -> None:
    """RSS needs no key — an empty/missing api_key must NOT return the
    disabled-provider sentinel (which the old REST path did).
    """
    from unittest.mock import MagicMock

    mock_adapter = MagicMock()
    mock_adapter.fetch_news.return_value = []

    with patch("scripts.smc_live_news_bus.BenzingaRssAdapter", return_value=mock_adapter):
        result = bus.fetch_live_news_benzinga(
            api_key="",
            symbols=["AAPL"],
            cursor=0.0,
            page_size=50,
        )

    assert result.ok is True
    assert result.provider == "benzinga"
    # Must NOT have an error field indicating disabled
    assert not getattr(result, "error", None)
