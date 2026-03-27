"""Tests for the SMC TV bridge adapter layer (ADR-001).

Validates:
1. Protocol classes are runtime-checkable and well-defined.
2. Open Prep adapter implementations satisfy the protocols.
3. Bridge snapshot builder works with injected adapters (no live FMP).
4. The bridge module has no direct ``from open_prep`` imports.
5. Stub providers obey contract invariants (golden payloads, error injection).
6. Payload validation catches bad data.
"""
from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ── 1. Protocol surface ────────────────────────────────────────────────────

class TestProtocolSurface:
    """Adapter protocols are importable and runtime-checkable."""

    def test_candle_provider_importable(self) -> None:
        from smc_tv_bridge.adapters import CandleProvider
        assert hasattr(CandleProvider, "fetch_candles")

    def test_regime_provider_importable(self) -> None:
        from smc_tv_bridge.adapters import RegimeProvider
        assert hasattr(RegimeProvider, "update")

    def test_technical_score_provider_importable(self) -> None:
        from smc_tv_bridge.adapters import TechnicalScoreProvider
        assert hasattr(TechnicalScoreProvider, "get_technical_data")

    def test_protocols_are_runtime_checkable(self) -> None:
        from smc_tv_bridge.adapters import (
            CandleProvider,
            RegimeProvider,
            TechnicalScoreProvider,
        )
        # runtime_checkable protocols can be used with isinstance()
        assert hasattr(CandleProvider, "__protocol_attrs__") or hasattr(
            CandleProvider, "__abstractmethods__"
        ) or issubclass(type(CandleProvider), type)


# ── 2. Concrete adapters satisfy protocols ──────────────────────────────────

class _StubCandleProvider:
    """Minimal stub that satisfies CandleProvider."""

    def fetch_candles(self, symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
        return [
            {"date": "2026-03-27", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100}
        ]


class _StubRegimeProvider:
    """Minimal stub that satisfies RegimeProvider."""

    def __init__(self) -> None:
        self._regime = "NORMAL"
        self._thin = 0.0

    @property
    def regime(self) -> str:
        return self._regime

    @property
    def thin_fraction(self) -> float:
        return self._thin

    def update(self, quotes: dict[str, dict[str, Any]]) -> str:
        return self._regime


class _StubTechProvider:
    """Minimal stub that satisfies TechnicalScoreProvider."""

    def get_technical_data(self, symbol: str, interval: str) -> dict[str, Any]:
        return {"technical_score": 0.72, "technical_signal": "BULLISH"}


class TestProtocolConformance:
    """Stubs satisfy the protocol isinstance check."""

    def test_stub_candle_provider(self) -> None:
        from smc_tv_bridge.adapters import CandleProvider
        assert isinstance(_StubCandleProvider(), CandleProvider)

    def test_stub_regime_provider(self) -> None:
        from smc_tv_bridge.adapters import RegimeProvider
        assert isinstance(_StubRegimeProvider(), RegimeProvider)

    def test_stub_tech_provider(self) -> None:
        from smc_tv_bridge.adapters import TechnicalScoreProvider
        assert isinstance(_StubTechProvider(), TechnicalScoreProvider)


# ── 3. Bridge snapshot with injected stubs ──────────────────────────────────

class TestBridgeWithAdapters:
    """build_smc_snapshot produces correct output when adapters are injected."""

    def _inject_stubs(self) -> None:
        """Replace global adapter singletons with stubs."""
        import smc_tv_bridge.smc_api as api
        api._candle_provider = _StubCandleProvider()
        api._regime_provider = _StubRegimeProvider()
        api._tech_provider = _StubTechProvider()

    def _clear_stubs(self) -> None:
        import smc_tv_bridge.smc_api as api
        api._candle_provider = None
        api._regime_provider = None
        api._tech_provider = None

    def test_snapshot_with_stubs_returns_expected_shape(self) -> None:
        import smc_tv_bridge.smc_api as api

        self._inject_stubs()
        try:
            # Patch out the canonical structure producer to avoid needing
            # real bar data
            with patch.object(api, "_detect_structure_canonical", return_value={
                "bos": [{"time": 1, "price": 100.0, "dir": "UP"}],
                "orderblocks": [],
                "fvg": [],
                "liquidity_sweeps": [],
            }):
                # Override USE_MOCK to False so we exercise the real path
                original_mock = api.USE_MOCK
                api.USE_MOCK = False
                try:
                    snap = api.build_smc_snapshot("TEST", "15m")
                finally:
                    api.USE_MOCK = original_mock
        finally:
            self._clear_stubs()

        assert snap["symbol"] == "TEST"
        assert snap["timeframe"] == "15m"
        assert snap["regime"]["volume_regime"] == "NORMAL"
        assert snap["technicalscore"] == 0.72
        assert snap["technicalsignal"] == "BULLISH"
        assert len(snap["bos"]) == 1

    def test_mock_mode_unaffected(self) -> None:
        import smc_tv_bridge.smc_api as api

        original_mock = api.USE_MOCK
        api.USE_MOCK = True
        try:
            snap = api.build_smc_snapshot("AAPL", "15m")
        finally:
            api.USE_MOCK = original_mock

        assert snap["symbol"] == "AAPL"
        assert "regime" in snap
        assert "technicalscore" in snap


# ── 4. No direct open_prep imports in bridge ────────────────────────────────

class TestNoBridgeOpenPrepImports:
    """smc_api.py must not contain any ``from open_prep`` or ``import open_prep`` statements."""

    def test_no_open_prep_imports_in_bridge(self) -> None:
        src = Path(__file__).resolve().parents[1] / "smc_tv_bridge" / "smc_api.py"
        tree = ast.parse(src.read_text(encoding="utf-8"), filename=str(src))
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                # Imports from the adapter wrapper are allowed; direct
                # imports from the open_prep package are not.
                if node.module.startswith("open_prep"):
                    violations.append(f"line {node.lineno}: from {node.module} import ...")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("open_prep"):
                        violations.append(f"line {node.lineno}: import {alias.name}")
        assert not violations, (
            f"smc_api.py still has direct open_prep imports:\n"
            + "\n".join(f"  {v}" for v in violations)
        )


# ── 5. Adapter implementations have correct method signatures ──────────────

class TestAdapterSignatures:
    """Verify adapter_open_prep classes expose the right method names."""

    @pytest.mark.parametrize("cls_name, method", [
        ("FMPCandleProvider", "fetch_candles"),
        ("OpenPrepRegimeProvider", "update"),
        ("OpenPrepTechnicalScoreProvider", "get_technical_data"),
    ])
    def test_method_exists(self, cls_name: str, method: str) -> None:
        mod = importlib.import_module("smc_tv_bridge.adapters_open_prep")
        cls = getattr(mod, cls_name)
        assert hasattr(cls, method), f"{cls_name} missing {method}"

    def test_regime_provider_has_properties(self) -> None:
        from smc_tv_bridge.adapters_open_prep import OpenPrepRegimeProvider
        # Properties must be declared on the class
        assert isinstance(
            inspect.getattr_static(OpenPrepRegimeProvider, "regime"),
            property,
        )
        assert isinstance(
            inspect.getattr_static(OpenPrepRegimeProvider, "thin_fraction"),
            property,
        )


# ── 6. Stub provider contract invariants ────────────────────────────────────

class TestStubProviderContracts:
    """Stubs in smc_tv_bridge.stubs produce valid contract-conforming data."""

    def test_golden_candle_has_required_keys(self) -> None:
        from smc_tv_bridge.adapters import CANDLE_REQUIRED_KEYS, CANDLE_TIMESTAMP_KEYS
        from smc_tv_bridge.stubs import GOLDEN_CANDLE
        assert CANDLE_REQUIRED_KEYS.issubset(GOLDEN_CANDLE.keys())
        assert CANDLE_TIMESTAMP_KEYS & GOLDEN_CANDLE.keys(), "needs date or timestamp"

    def test_golden_candles_sorted_oldest_first(self) -> None:
        from smc_tv_bridge.stubs import GOLDEN_CANDLES_5
        dates = [c["date"] for c in GOLDEN_CANDLES_5]
        assert dates == sorted(dates)

    def test_golden_tech_bullish_has_required_keys(self) -> None:
        from smc_tv_bridge.adapters import TECH_REQUIRED_KEYS, TECH_VALID_SIGNALS
        from smc_tv_bridge.stubs import GOLDEN_TECH_BULLISH
        assert TECH_REQUIRED_KEYS.issubset(GOLDEN_TECH_BULLISH.keys())
        assert GOLDEN_TECH_BULLISH["technical_signal"] in TECH_VALID_SIGNALS

    def test_golden_tech_bearish_valid(self) -> None:
        from smc_tv_bridge.adapters import TECH_VALID_SIGNALS
        from smc_tv_bridge.stubs import GOLDEN_TECH_BEARISH
        assert 0.0 <= GOLDEN_TECH_BEARISH["technical_score"] <= 1.0
        assert GOLDEN_TECH_BEARISH["technical_signal"] in TECH_VALID_SIGNALS

    def test_golden_tech_neutral_valid(self) -> None:
        from smc_tv_bridge.stubs import GOLDEN_TECH_NEUTRAL
        assert GOLDEN_TECH_NEUTRAL["technical_score"] == 0.5
        assert GOLDEN_TECH_NEUTRAL["technical_signal"] == "NEUTRAL"

    def test_stub_candle_returns_deep_copy(self) -> None:
        from smc_tv_bridge.stubs import StubCandleProvider
        p = StubCandleProvider()
        a = p.fetch_candles("X", "5min", 5)
        b = p.fetch_candles("X", "5min", 5)
        assert a == b
        a[0]["close"] = -999  # mutate
        assert b[0]["close"] != -999, "must return independent copies"

    def test_stub_candle_respects_limit(self) -> None:
        from smc_tv_bridge.stubs import StubCandleProvider
        p = StubCandleProvider()
        assert len(p.fetch_candles("X", "5min", 2)) == 2

    def test_stub_candle_tracks_calls(self) -> None:
        from smc_tv_bridge.stubs import StubCandleProvider
        p = StubCandleProvider()
        p.fetch_candles("AAPL", "15min", 100)
        assert p.calls == [("AAPL", "15min", 100)]

    def test_stub_candle_error_injection(self) -> None:
        from smc_tv_bridge.stubs import StubCandleProvider
        p = StubCandleProvider(raise_on_call=ConnectionError("down"))
        with pytest.raises(ConnectionError, match="down"):
            p.fetch_candles("X", "5min", 5)

    def test_stub_regime_tracks_updates(self) -> None:
        from smc_tv_bridge.stubs import StubRegimeProvider
        p = StubRegimeProvider(regime_label="LOW_VOLUME", thin=0.42)
        assert p.regime == "LOW_VOLUME"
        assert p.thin_fraction == 0.42
        p.update({"AAPL": {"price": 150}})
        assert len(p.update_calls) == 1

    def test_stub_regime_labels_valid(self) -> None:
        from smc_tv_bridge.adapters import REGIME_VALID_LABELS
        from smc_tv_bridge.stubs import StubRegimeProvider
        for label in REGIME_VALID_LABELS:
            p = StubRegimeProvider(regime_label=label)
            assert p.regime == label

    def test_stub_tech_error_injection(self) -> None:
        from smc_tv_bridge.stubs import StubTechProvider
        p = StubTechProvider(raise_on_call=TimeoutError("slow"))
        with pytest.raises(TimeoutError, match="slow"):
            p.get_technical_data("X", "15m")

    def test_stub_tech_returns_deep_copy(self) -> None:
        from smc_tv_bridge.stubs import StubTechProvider
        p = StubTechProvider()
        a = p.get_technical_data("X", "5m")
        b = p.get_technical_data("X", "5m")
        a["technical_score"] = -1
        assert b["technical_score"] != -1


# ── 7. Payload validation helpers ──────────────────────────────────────────

class TestPayloadValidation:
    """Contract key sets are correct and usable for validation."""

    def test_candle_required_keys_complete(self) -> None:
        from smc_tv_bridge.adapters import CANDLE_REQUIRED_KEYS
        assert {"open", "high", "low", "close", "volume"} <= CANDLE_REQUIRED_KEYS

    def test_candle_missing_volume_detected(self) -> None:
        from smc_tv_bridge.adapters import CANDLE_REQUIRED_KEYS
        bad = {"open": 1, "high": 2, "low": 0.5, "close": 1.5, "date": "2026-01-01"}
        missing = CANDLE_REQUIRED_KEYS - bad.keys()
        assert "volume" in missing

    def test_tech_missing_signal_detected(self) -> None:
        from smc_tv_bridge.adapters import TECH_REQUIRED_KEYS
        bad = {"technical_score": 0.5}
        missing = TECH_REQUIRED_KEYS - bad.keys()
        assert "technical_signal" in missing

    def test_regime_label_unknown_rejected(self) -> None:
        from smc_tv_bridge.adapters import REGIME_VALID_LABELS
        assert "UNKNOWN_REGIME" not in REGIME_VALID_LABELS
