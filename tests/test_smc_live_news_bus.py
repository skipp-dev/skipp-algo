from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import smc_live_news_bus as bus


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
