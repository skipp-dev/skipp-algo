from __future__ import annotations

from smc_integration.meta_merge import merge_raw_meta_domains


def _volume_meta() -> dict:
    return {
        "symbol": "AAPL",
        "timeframe": "15m",
        "asof_ts": 1709253600.0,
        "volume": {
            "value": {"regime": "NORMAL", "thin_fraction": 0.1},
            "asof_ts": 1709253600.0,
            "stale": False,
        },
        "provenance": ["volume:a", "volume:b"],
    }


def test_merge_raw_meta_domains_keeps_required_volume_and_optional_domains() -> None:
    merged = merge_raw_meta_domains(
        volume_meta=_volume_meta(),
        technical_meta={
            "symbol": "AAPL",
            "timeframe": "15m",
            "asof_ts": 1709253601.0,
            "technical": {
                "value": {"strength": 0.8, "bias": "BULLISH"},
                "asof_ts": 1709253601.0,
                "stale": False,
            },
            "provenance": ["tech:a"],
        },
        news_meta={
            "symbol": "AAPL",
            "timeframe": "15m",
            "asof_ts": 1709253602.0,
            "news": {
                "value": {"strength": 0.3, "bias": "BEARISH"},
                "asof_ts": 1709253602.0,
                "stale": True,
            },
            "provenance": ["news:a"],
        },
        domain_sources={
            "structure": "databento_watchlist_csv",
            "volume": "databento_watchlist_csv",
            "technical": "fmp_watchlist_json",
            "news": "benzinga_watchlist_json",
        },
    )

    assert merged["symbol"] == "AAPL"
    assert merged["timeframe"] == "15m"
    assert float(merged["asof_ts"]) == 1709253602.0
    assert merged["technical"]["value"]["bias"] == "BULLISH"
    assert merged["news"]["value"]["bias"] == "BEARISH"
    assert merged["volume"]["value"]["regime"] == "NORMAL"
    assert "smc_integration:composite_meta[structure=databento_watchlist_csv,volume=databento_watchlist_csv,technical=fmp_watchlist_json,news=benzinga_watchlist_json]" in merged["provenance"]


def test_merge_raw_meta_domains_deduplicates_provenance_and_allows_missing_optional_domains() -> None:
    merged = merge_raw_meta_domains(
        volume_meta={
            **_volume_meta(),
            "provenance": ["same:item", "same:item"],
        },
        technical_meta=None,
        news_meta=None,
        domain_sources={
            "structure": "databento_watchlist_csv",
            "volume": "databento_watchlist_csv",
            "technical": "fmp_watchlist_json",
            "news": "benzinga_watchlist_json",
        },
    )

    assert "technical" not in merged
    assert "news" not in merged
    assert merged["provenance"][0] == "same:item"
    assert merged["provenance"].count("same:item") == 1
