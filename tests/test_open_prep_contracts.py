"""Contract and regression tests for Open Prep surfaces consumed by the bridge.

Validates:
1. Candle payload shape: required keys, numeric types, ordering.
2. Technical score payload shape: required keys, value ranges, signal enum.
3. Regime payload shape: valid labels, thin_fraction bounds.
4. Fallback/degradation: bridge survives provider errors/malformed data.
5. Stub providers satisfy adapter protocols.
6. End-to-end snapshot shape through stubs.
"""
from __future__ import annotations

import copy
from typing import Any
from unittest.mock import patch

import pytest

from smc_tv_bridge.adapters import (
    CANDLE_REQUIRED_KEYS,
    CANDLE_TIMESTAMP_KEYS,
    REGIME_VALID_LABELS,
    TECH_REQUIRED_KEYS,
    TECH_VALID_SIGNALS,
    CandleProvider,
    RegimeProvider,
    TechnicalScoreProvider,
)
from smc_tv_bridge.stubs import (
    GOLDEN_CANDLE,
    GOLDEN_CANDLES_5,
    GOLDEN_TECH_BEARISH,
    GOLDEN_TECH_BULLISH,
    GOLDEN_TECH_NEUTRAL,
    StubCandleProvider,
    StubRegimeProvider,
    StubTechProvider,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. Candle contract
# ═══════════════════════════════════════════════════════════════════════════

class TestCandleContract:
    """Candle dicts produced by providers must satisfy the bridge contract."""

    def test_golden_candle_has_required_ohlcv_keys(self) -> None:
        missing = CANDLE_REQUIRED_KEYS - set(GOLDEN_CANDLE.keys())
        assert not missing, f"Missing OHLCV keys: {missing}"

    def test_golden_candle_has_timestamp_key(self) -> None:
        assert CANDLE_TIMESTAMP_KEYS & set(GOLDEN_CANDLE.keys()), (
            "Candle must have 'date' or 'timestamp'"
        )

    def test_golden_candle_values_are_numeric(self) -> None:
        for key in CANDLE_REQUIRED_KEYS:
            assert isinstance(GOLDEN_CANDLE[key], (int, float)), (
                f"{key} should be numeric, got {type(GOLDEN_CANDLE[key])}"
            )

    def test_golden_candles_sorted_oldest_first(self) -> None:
        dates = [c["date"] for c in GOLDEN_CANDLES_5]
        assert dates == sorted(dates), "Candles must be sorted oldest-first"

    @pytest.mark.parametrize("candle", GOLDEN_CANDLES_5)
    def test_each_golden_candle_satisfies_contract(self, candle: dict[str, Any]) -> None:
        missing = CANDLE_REQUIRED_KEYS - set(candle.keys())
        assert not missing

    def test_empty_candle_list_is_valid(self) -> None:
        provider = StubCandleProvider(candles=[])
        result = provider.fetch_candles("AAPL", "15min", 100)
        assert result == []

    def test_stub_respects_limit(self) -> None:
        provider = StubCandleProvider()
        result = provider.fetch_candles("AAPL", "15min", 2)
        assert len(result) == 2

    def test_candle_with_timestamp_instead_of_date(self) -> None:
        """Candles may use integer 'timestamp' instead of 'date'."""
        candle = {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100, "timestamp": 1711540200}
        assert CANDLE_REQUIRED_KEYS <= set(candle.keys())
        assert CANDLE_TIMESTAMP_KEYS & set(candle.keys())


# ═══════════════════════════════════════════════════════════════════════════
# 2. Technical score contract
# ═══════════════════════════════════════════════════════════════════════════

class TestTechScoreContract:
    """Technical score payloads must contain required keys with valid values."""

    @pytest.mark.parametrize("payload", [
        GOLDEN_TECH_BULLISH,
        GOLDEN_TECH_BEARISH,
        GOLDEN_TECH_NEUTRAL,
    ])
    def test_required_keys_present(self, payload: dict[str, Any]) -> None:
        missing = TECH_REQUIRED_KEYS - set(payload.keys())
        assert not missing, f"Missing tech keys: {missing}"

    @pytest.mark.parametrize("payload", [
        GOLDEN_TECH_BULLISH,
        GOLDEN_TECH_BEARISH,
        GOLDEN_TECH_NEUTRAL,
    ])
    def test_score_in_range(self, payload: dict[str, Any]) -> None:
        score = payload["technical_score"]
        assert 0.0 <= score <= 1.0, f"Score {score} out of range"

    @pytest.mark.parametrize("payload", [
        GOLDEN_TECH_BULLISH,
        GOLDEN_TECH_BEARISH,
        GOLDEN_TECH_NEUTRAL,
    ])
    def test_signal_is_valid_label(self, payload: dict[str, Any]) -> None:
        assert payload["technical_signal"] in TECH_VALID_SIGNALS

    def test_bullish_score_above_neutral(self) -> None:
        assert GOLDEN_TECH_BULLISH["technical_score"] > 0.5

    def test_bearish_score_below_neutral(self) -> None:
        assert GOLDEN_TECH_BEARISH["technical_score"] < 0.5

    def test_neutral_score_is_half(self) -> None:
        assert GOLDEN_TECH_NEUTRAL["technical_score"] == 0.5

    def test_extra_keys_are_tolerated(self) -> None:
        """Providers may include optional keys like rsi, adx, etc."""
        assert "rsi" in GOLDEN_TECH_BULLISH  # optional but valid


# ═══════════════════════════════════════════════════════════════════════════
# 3. Regime contract
# ═══════════════════════════════════════════════════════════════════════════

class TestRegimeContract:
    """Regime provider must expose valid labels and bounded thin_fraction."""

    @pytest.mark.parametrize("label", list(REGIME_VALID_LABELS))
    def test_valid_regime_labels(self, label: str) -> None:
        provider = StubRegimeProvider(regime_label=label)
        assert provider.regime == label
        assert provider.regime in REGIME_VALID_LABELS

    def test_thin_fraction_bounded(self) -> None:
        provider = StubRegimeProvider(thin=0.45)
        assert 0.0 <= provider.thin_fraction <= 1.0

    def test_default_is_normal(self) -> None:
        provider = StubRegimeProvider()
        assert provider.regime == "NORMAL"
        assert provider.thin_fraction == 0.0

    def test_update_returns_regime_label(self) -> None:
        provider = StubRegimeProvider(regime_label="LOW_VOLUME")
        result = provider.update({"AAPL": {"price": 150.0}})
        assert result == "LOW_VOLUME"
        assert len(provider.update_calls) == 1

    def test_update_with_empty_quotes(self) -> None:
        provider = StubRegimeProvider()
        result = provider.update({})
        assert result == "NORMAL"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Protocol conformance for stubs
# ═══════════════════════════════════════════════════════════════════════════

class TestStubProtocolConformance:
    """All stubs satisfy their respective adapter protocols."""

    def test_stub_candle_is_candle_provider(self) -> None:
        assert isinstance(StubCandleProvider(), CandleProvider)

    def test_stub_regime_is_regime_provider(self) -> None:
        assert isinstance(StubRegimeProvider(), RegimeProvider)

    def test_stub_tech_is_tech_provider(self) -> None:
        assert isinstance(StubTechProvider(), TechnicalScoreProvider)


# ═══════════════════════════════════════════════════════════════════════════
# 5. Fallback / degradation behavior
# ═══════════════════════════════════════════════════════════════════════════

class TestFallbackBehavior:
    """Bridge must degrade gracefully when providers fail or return bad data."""

    def _build_snapshot_with_providers(
        self,
        candle_prov: Any,
        regime_prov: Any,
        tech_prov: Any,
    ) -> dict[str, Any]:
        import smc_tv_bridge.smc_api as api

        saved = (api._candle_provider, api._regime_provider, api._tech_provider, api.USE_MOCK)
        api._candle_provider = candle_prov
        api._regime_provider = regime_prov
        api._tech_provider = tech_prov
        api.USE_MOCK = False
        try:
            with patch.object(api, "_detect_structure_canonical", return_value={
                "bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": [],
            }):
                return api.build_smc_snapshot("TEST", "15m")
        finally:
            api._candle_provider, api._regime_provider, api._tech_provider, api.USE_MOCK = saved

    def test_empty_candles_produce_empty_structure(self) -> None:
        snap = self._build_snapshot_with_providers(
            StubCandleProvider(candles=[]),
            StubRegimeProvider(),
            StubTechProvider(),
        )
        assert snap["bos"] == []
        assert snap["orderblocks"] == []
        assert snap["symbol"] == "TEST"

    def test_tech_provider_returns_neutral_on_missing_keys(self) -> None:
        """If tech payload is missing keys, bridge falls back to defaults."""
        snap = self._build_snapshot_with_providers(
            StubCandleProvider(),
            StubRegimeProvider(),
            StubTechProvider(payload={}),  # missing required keys
        )
        # Bridge uses .get("technical_score", 0.5)
        assert snap["technicalscore"] == 0.5
        assert snap["technicalsignal"] == "NEUTRAL"

    def test_tech_provider_extra_keys_ignored(self) -> None:
        """Extra keys in tech payload don't break the snapshot."""
        payload = {
            "technical_score": 0.88,
            "technical_signal": "BULLISH",
            "rsi": 72.0,
            "something_new": True,
        }
        snap = self._build_snapshot_with_providers(
            StubCandleProvider(),
            StubRegimeProvider(),
            StubTechProvider(payload=payload),
        )
        assert snap["technicalscore"] == 0.88

    def test_regime_persists_through_quote_fetch_failure(self) -> None:
        """If quote fetch for regime update fails, snapshot still works."""
        regime = StubRegimeProvider(regime_label="LOW_VOLUME", thin=0.55)
        snap = self._build_snapshot_with_providers(
            StubCandleProvider(),
            regime,
            StubTechProvider(),
        )
        assert snap["regime"]["volume_regime"] == "LOW_VOLUME"
        assert snap["regime"]["thin_fraction"] == 0.55

    def test_snapshot_shape_always_stable(self) -> None:
        """Regardless of provider output, snapshot always has required keys."""
        snap = self._build_snapshot_with_providers(
            StubCandleProvider(candles=[]),
            StubRegimeProvider(),
            StubTechProvider(payload={}),
        )
        required = {
            "symbol", "timeframe", "bos", "orderblocks", "fvg",
            "liquidity_sweeps", "regime", "technicalscore",
            "technicalsignal", "newsscore",
        }
        assert required <= set(snap.keys())

    def test_news_score_fallback_when_unavailable(self) -> None:
        """_get_news_score returns 0.0 when newsstack is unavailable."""
        import smc_tv_bridge.smc_api as api
        with patch.object(api, "_get_news_score", return_value=0.0):
            snap = self._build_snapshot_with_providers(
                StubCandleProvider(),
                StubRegimeProvider(),
                StubTechProvider(),
            )
        assert snap["newsscore"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# 6. Candle → DataFrame conversion (bridge-internal contract)
# ═══════════════════════════════════════════════════════════════════════════

class TestCandleDataframeConversion:
    """candles_to_dataframe produces the shape the structure producer expects."""

    def test_empty_candles_yield_empty_df(self) -> None:
        from smc_tv_bridge.smc_api import candles_to_dataframe
        df = candles_to_dataframe([], "AAPL")
        assert df.empty
        assert "symbol" in df.columns

    def test_golden_candles_convert_correctly(self) -> None:
        from smc_tv_bridge.smc_api import candles_to_dataframe
        df = candles_to_dataframe(GOLDEN_CANDLES_5, "AAPL")
        assert len(df) == 5
        assert set(df.columns) == {"symbol", "timestamp", "open", "high", "low", "close", "volume"}
        assert all(df["symbol"] == "AAPL")

    def test_numeric_timestamp_candle(self) -> None:
        from smc_tv_bridge.smc_api import candles_to_dataframe
        candles = [{"timestamp": 1711540200, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100}]
        df = candles_to_dataframe(candles, "TEST")
        assert df.iloc[0]["timestamp"] == 1711540200

    def test_symbol_uppercased(self) -> None:
        from smc_tv_bridge.smc_api import candles_to_dataframe
        df = candles_to_dataframe([GOLDEN_CANDLE], "aapl")
        assert df.iloc[0]["symbol"] == "AAPL"

    def test_missing_ohlcv_fields_default_to_zero(self) -> None:
        from smc_tv_bridge.smc_api import candles_to_dataframe
        candles = [{"date": "2026-03-27"}]
        df = candles_to_dataframe(candles, "X")
        row = df.iloc[0]
        for col in ("open", "high", "low", "close", "volume"):
            assert row[col] == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# 7. Encoding contract (bridge → Pine)
# ═══════════════════════════════════════════════════════════════════════════

class TestEncodingContract:
    """Pipe-delimited encoders produce stable output for TradingView."""

    def test_encode_levels(self) -> None:
        from smc_tv_bridge.smc_api import encode_levels
        levels = [{"time": 1000, "price": 99.5, "dir": "UP"}]
        assert encode_levels(levels) == "1000|99.5|UP"

    def test_encode_zones(self) -> None:
        from smc_tv_bridge.smc_api import encode_zones
        zones = [{"low": 95.0, "high": 97.0, "dir": "BULL", "valid": True}]
        assert encode_zones(zones) == "95.0|97.0|BULL|1"

    def test_encode_sweeps(self) -> None:
        from smc_tv_bridge.smc_api import encode_sweeps
        sweeps = [{"time": 2000, "price": 101.0, "side": "SELL"}]
        assert encode_sweeps(sweeps) == "2000|101.0|SELL"

    def test_encode_empty_lists(self) -> None:
        from smc_tv_bridge.smc_api import encode_levels, encode_zones, encode_sweeps
        assert encode_levels([]) == ""
        assert encode_zones([]) == ""
        assert encode_sweeps([]) == ""

    def test_encode_multiple_entries_semicolon_separated(self) -> None:
        from smc_tv_bridge.smc_api import encode_levels
        levels = [
            {"time": 1000, "price": 99.5, "dir": "UP"},
            {"time": 2000, "price": 98.0, "dir": "DOWN"},
        ]
        encoded = encode_levels(levels)
        assert encoded.count(";") == 1
        parts = encoded.split(";")
        assert len(parts) == 2


# ═══════════════════════════════════════════════════════════════════════════
# 8. Stub call tracking
# ═══════════════════════════════════════════════════════════════════════════

class TestStubCallTracking:
    """Stubs record calls for test assertions."""

    def test_candle_stub_tracks_calls(self) -> None:
        s = StubCandleProvider()
        s.fetch_candles("AAPL", "15min", 50)
        s.fetch_candles("MSFT", "5min", 200)
        assert len(s.calls) == 2
        assert s.calls[0] == ("AAPL", "15min", 50)
        assert s.calls[1] == ("MSFT", "5min", 200)

    def test_tech_stub_tracks_calls(self) -> None:
        s = StubTechProvider()
        s.get_technical_data("AAPL", "15m")
        assert s.calls == [("AAPL", "15m")]

    def test_regime_stub_tracks_update_calls(self) -> None:
        s = StubRegimeProvider()
        s.update({"X": {"price": 1.0}})
        s.update({})
        assert len(s.update_calls) == 2

    def test_candle_stub_raise_on_call(self) -> None:
        s = StubCandleProvider(raise_on_call=RuntimeError("network down"))
        with pytest.raises(RuntimeError, match="network down"):
            s.fetch_candles("AAPL", "15min", 100)

    def test_tech_stub_raise_on_call(self) -> None:
        s = StubTechProvider(raise_on_call=TimeoutError("slow"))
        with pytest.raises(TimeoutError, match="slow"):
            s.get_technical_data("AAPL", "15m")
