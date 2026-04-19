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
    assert float(merged["asof_ts"]) == 1709253600.0
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


def test_merge_raw_meta_domains_surfaces_domain_drop_reasons_for_technical() -> None:
    merged = merge_raw_meta_domains(
        volume_meta=_volume_meta(),
        technical_meta=None,
        news_meta={
            "symbol": "AAPL",
            "timeframe": "15m",
            "asof_ts": 1709253602.0,
            "news": {
                "value": {"strength": 0.3, "bias": "BEARISH"},
                "asof_ts": 1709253602.0,
                "stale": False,
            },
            "provenance": ["news:a"],
        },
        domain_sources={
            "structure": "databento_watchlist_csv",
            "volume": "databento_watchlist_csv",
            "technical": "fmp_watchlist_json",
            "news": "benzinga_watchlist_json",
        },
        domain_drop_reasons={"technical": "domain_fields_incomplete"},
        domain_drop_providers={"technical": "fmp_watchlist_json"},
    )

    assert merged["domain_drop_reasons"]["technical"] == "domain_fields_incomplete"
    assert merged["domain_drop_providers"]["technical"] == "fmp_watchlist_json"
    assert "news" not in merged["domain_drop_reasons"]


def test_merge_raw_meta_domains_surfaces_domain_drop_reasons_for_news() -> None:
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
        news_meta=None,
        domain_sources={
            "structure": "databento_watchlist_csv",
            "volume": "databento_watchlist_csv",
            "technical": "fmp_watchlist_json",
            "news": "benzinga_watchlist_json",
        },
        domain_drop_reasons={"news": "source_file_not_found"},
        domain_drop_providers={"news": "benzinga_watchlist_json"},
    )

    assert merged["domain_drop_reasons"]["news"] == "source_file_not_found"
    assert merged["domain_drop_providers"]["news"] == "benzinga_watchlist_json"
    assert "technical" not in merged["domain_drop_reasons"]


def test_merge_raw_meta_domains_exposes_empty_drop_reasons_when_all_domains_are_present() -> None:
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
                "stale": False,
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

    assert merged["domain_drop_reasons"] == {}
    assert merged["domain_drop_providers"] == {}


# ── pure helper coverage ─────────────────────────────────────────

import pytest

from smc_integration.meta_merge import (
    _coerce_float,
    _coerce_str,
    _domain_payload,
    _unique_preserve_order,
)


class TestCoerceFloat:
    def test_int(self) -> None:
        assert _coerce_float(42) == 42.0

    def test_float(self) -> None:
        assert _coerce_float(3.14) == 3.14

    def test_valid_string(self) -> None:
        assert _coerce_float("2.5") == 2.5

    def test_invalid_string(self) -> None:
        assert _coerce_float("not_a_number") is None

    def test_none(self) -> None:
        assert _coerce_float(None) is None

    def test_list(self) -> None:
        assert _coerce_float([1]) is None


class TestCoerceStr:
    def test_string(self) -> None:
        assert _coerce_str("  AAPL  ") == "AAPL"

    def test_non_string(self) -> None:
        assert _coerce_str(42) == ""


class TestDomainPayload:
    def test_valid(self) -> None:
        result = _domain_payload({"volume": {"regime": "NORMAL"}}, "volume")
        assert result == {"regime": "NORMAL"}

    def test_non_mapping(self) -> None:
        assert _domain_payload({"volume": "bad"}, "volume") is None

    def test_missing_key(self) -> None:
        assert _domain_payload({}, "volume") is None


class TestUniquePreserveOrder:
    def test_dedup(self) -> None:
        assert _unique_preserve_order(["a", "b", "a", "c"]) == ["a", "b", "c"]


class TestMergeSymbolFallback:
    def test_symbol_from_technical_when_volume_empty(self) -> None:
        merged = merge_raw_meta_domains(
            volume_meta={"asof_ts": 1.0, "volume": {"regime": "X"}},
            technical_meta={"symbol": "MSFT", "timeframe": "15m", "asof_ts": 2.0},
            news_meta=None,
            domain_sources={"structure": "a", "volume": "b", "technical": "c", "news": "d"},
        )
        assert merged["symbol"] == "MSFT"

    def test_symbol_from_news_when_others_empty(self) -> None:
        merged = merge_raw_meta_domains(
            volume_meta={"asof_ts": 1.0, "volume": {"regime": "X"}},
            technical_meta=None,
            news_meta={"symbol": "GOOG", "timeframe": "1D", "asof_ts": 3.0},
            domain_sources={"structure": "a", "volume": "b", "technical": "c", "news": "d"},
        )
        assert merged["symbol"] == "GOOG"

    def test_no_symbol_raises(self) -> None:
        with pytest.raises(ValueError, match="requires symbol"):
            merge_raw_meta_domains(
                volume_meta={"asof_ts": 1.0, "volume": {"regime": "X"}},
                technical_meta=None,
                news_meta=None,
                domain_sources={"structure": "a", "volume": "b", "technical": "c", "news": "d"},
            )

    def test_no_asof_ts_raises(self) -> None:
        with pytest.raises(ValueError, match="asof_ts"):
            merge_raw_meta_domains(
                volume_meta={"symbol": "AAPL", "timeframe": "15m", "volume": {"regime": "X"}},
                technical_meta=None,
                news_meta=None,
                domain_sources={"structure": "a", "volume": "b", "technical": "c", "news": "d"},
            )

    def test_no_volume_payload_raises(self) -> None:
        with pytest.raises(ValueError, match="requires volume"):
            merge_raw_meta_domains(
                volume_meta={"symbol": "AAPL", "timeframe": "15m", "asof_ts": 1.0},
                technical_meta=None,
                news_meta=None,
                domain_sources={"structure": "a", "volume": "b", "technical": "c", "news": "d"},
            )


class TestMergeEnrichmentDomains:
    def _vol(self) -> dict:
        return {
            "symbol": "AAPL",
            "timeframe": "15m",
            "asof_ts": 1709253600.0,
            "volume": {"value": {"regime": "NORMAL"}, "asof_ts": 1709253600.0, "stale": False},
        }

    def test_event_risk(self) -> None:
        merged = merge_raw_meta_domains(
            volume_meta=self._vol(),
            technical_meta=None,
            news_meta=None,
            domain_sources={"structure": "a", "volume": "b", "technical": "c", "news": "d"},
            event_risk={"earnings": True},
        )
        assert merged["event_risk"] == {"earnings": True}

    def test_enriched_news(self) -> None:
        merged = merge_raw_meta_domains(
            volume_meta=self._vol(),
            technical_meta=None,
            news_meta=None,
            domain_sources={"structure": "a", "volume": "b", "technical": "c", "news": "d"},
            enriched_news=[{"headline": "test"}],
        )
        assert merged["enriched_news"] == [{"headline": "test"}]

    def test_market_regime(self) -> None:
        merged = merge_raw_meta_domains(
            volume_meta=self._vol(),
            technical_meta=None,
            news_meta=None,
            domain_sources={"structure": "a", "volume": "b", "technical": "c", "news": "d"},
            market_regime={"label": "RISK_ON"},
        )
        assert merged["market_regime"] == {"label": "RISK_ON"}

    def test_enriched_news_empty_skipped(self) -> None:
        merged = merge_raw_meta_domains(
            volume_meta=self._vol(),
            technical_meta=None,
            news_meta=None,
            domain_sources={"structure": "a", "volume": "b", "technical": "c", "news": "d"},
            enriched_news=[],
        )
        assert "enriched_news" not in merged
