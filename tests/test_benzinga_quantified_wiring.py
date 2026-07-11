"""Wiring for Benzinga NewsQuantified via the DIRECT key.

Massive does not resell the newsquantified analytics pack (verified 404), so
quantified must go direct to api.benzinga.com with BENZINGA_DIRECT_API_KEY — a
key distinct from the Massive-transport BENZINGA_API_KEY. The direct key was
verified live (2026-07-11) to return newsquantified 200 with the real schema
(Symb/Headlines/PUBt + price-impact analytics), whereas the plain news feed
keeps flowing over Massive.

These tests pin (a) the normalizer maps the real quantified schema (previously
it read the plain-news title/created fields and produced near-empty items), and
(b) the news bus routes the DIRECT key — not the Massive key — to quantified.
"""
from __future__ import annotations

from unittest.mock import patch

import scripts.smc_live_news_bus as bus
from newsstack_fmp.normalize import normalize_benzinga_quantified


def test_quantified_normalizer_maps_real_schema() -> None:
    it = {
        "_id": "6a518c57c3bb295042623465",
        "Symb": "AAPL",
        "Headlines": "Apple Pops On Whale Alerts",
        "PUBt": "2026-07-10 17:35:14.000",
        "RECt": "2026-07-10 17:35:15.000",
        "Date": "7/10/2026",
        # price-impact analytics — must ride along recorded-only in raw
        "OpenGap%": "0.52",
        "Range%": "0.10",
        "DayOpen": "192.54",
        "ATR14": "2.46",
        "Result%": "-3.49",
        "Vol_Ratio": "1.30",
        "ShortInterest%": "",
        "PERatio": "31.4",
    }
    item = normalize_benzinga_quantified(it)
    assert item.provider == "benzinga_quantified"
    assert item.item_id == "6a518c57c3bb295042623465"
    assert item.headline == "Apple Pops On Whale Alerts"
    assert item.tickers == ["AAPL"]
    assert item.published_ts > 0.0  # PUBt actually parsed (not the old empty path)
    # analytics preserved untouched for later use, not flattened away
    assert item.raw["OpenGap%"] == "0.52"
    assert item.raw["ATR14"] == "2.46"
    assert item.raw["Result%"] == "-3.49"


def test_quantified_normalizer_tolerates_plain_shape() -> None:
    # Schema tolerance: a plain title/created payload still maps.
    it = {"id": "x1", "title": "Foo", "created": "2026-07-10 10:00:00"}
    item = normalize_benzinga_quantified(it)
    assert item.item_id == "x1"
    assert item.headline == "Foo"
    assert item.published_ts > 0.0


def test_config_reads_direct_key(monkeypatch) -> None:
    monkeypatch.setenv("BENZINGA_DIRECT_API_KEY", "bz.production.test")
    from newsstack_fmp.config import Config

    cfg = Config()
    assert cfg.benzinga_direct_api_key == "bz.production.test"


def test_news_bus_routes_direct_key_to_quantified() -> None:
    captured: dict[str, str] = {}

    def _cap(provider: str):
        def _fn(**kw):
            captured[provider] = kw.get("api_key")
            return bus.ProviderPollResult(provider=provider, items=[], raw_count=0, cursor=0.0)
        return _fn

    with (
        patch.object(bus, "fetch_live_news_benzinga", side_effect=_cap("benzinga")),
        patch.object(bus, "fetch_live_news_benzinga_quantified", side_effect=_cap("benzinga_quantified")),
    ):
        bus.poll_live_news_bus(
            symbols=["AAPL"],
            benzinga_api_key="MASSIVE_TRANSPORT_KEY",
            benzinga_direct_api_key="bz.DIRECT_KEY",
            include_benzinga=True,
            include_fmp=False,
            include_newsapi_ai=False,
            include_tradingview=False,
            now_ts=1_750_250_000.0,
        )

    # The plain news feed rides Massive; quantified must get the direct key.
    assert captured["benzinga"] == "MASSIVE_TRANSPORT_KEY"
    assert captured["benzinga_quantified"] == "bz.DIRECT_KEY"
