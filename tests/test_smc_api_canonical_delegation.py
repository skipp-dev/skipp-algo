"""Tests for canonical structure delegation in smc_tv_bridge.smc_api.

Validates:
  - candles_to_dataframe conversion
  - adapter functions (_adapt_bos, _adapt_zones, _adapt_sweeps)
  - _detect_structure_canonical delegation path
  - response contract stability (same keys as before)
  - empty/no-candle behavior
  - mock mode unchanged
"""
from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from smc_tv_bridge.smc_api import (
    _adapt_bos,
    _adapt_sweeps,
    _adapt_zones,
    _detect_structure_canonical,
    _mock_snapshot,
    candles_to_dataframe,
    encode_levels,
    encode_sweeps,
    encode_zones,
)
from tests.fixture_helpers import assert_keys_subset


# ── candles_to_dataframe ─────────────────────────────────

SAMPLE_CANDLES = [
    {"date": "2024-03-01T10:00:00", "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 5000},
    {"date": "2024-03-01T10:15:00", "open": 101.0, "high": 103.0, "low": 100.0, "close": 102.5, "volume": 6000},
    {"date": "2024-03-01T10:30:00", "open": 102.5, "high": 104.0, "low": 101.5, "close": 103.0, "volume": 4500},
]


def test_candles_to_dataframe_columns() -> None:
    df = candles_to_dataframe(SAMPLE_CANDLES, "AAPL")
    expected_cols = {"symbol", "timestamp", "open", "high", "low", "close", "volume"}
    assert set(df.columns) == expected_cols
    assert len(df) == 3
    assert (df["symbol"] == "AAPL").all()


def test_candles_to_dataframe_empty() -> None:
    df = candles_to_dataframe([], "AAPL")
    assert df.empty
    assert "symbol" in df.columns


def test_candles_to_dataframe_normalizes_symbol() -> None:
    df = candles_to_dataframe(SAMPLE_CANDLES, " aapl ")
    assert (df["symbol"] == "AAPL").all()


def test_candles_to_dataframe_unix_timestamp() -> None:
    candles = [{"timestamp": 1709250000, "open": 100, "high": 102, "low": 99, "close": 101, "volume": 5000}]
    df = candles_to_dataframe(candles, "AAPL")
    assert df.iloc[0]["timestamp"] == 1709250000


# ── adapter functions ────────────────────────────────────

def test_adapt_bos_strips_extra_fields() -> None:
    canonical = [
        {"id": "bos:AAPL:15m:1709250000:BOS:UP:185.25", "time": 1709250000, "price": 185.25, "kind": "BOS", "dir": "UP"},
    ]
    adapted = _adapt_bos(canonical)
    assert adapted == [{"time": 1709250000, "price": 185.25, "dir": "UP"}]


def test_adapt_zones_strips_extra_fields() -> None:
    canonical = [
        {"id": "ob:AAPL:15m:…", "low": 184.5, "high": 185.1, "dir": "BULL", "valid": True, "anchor_ts": 1709250000, "source": "makuchaku_ob"},
    ]
    adapted = _adapt_zones(canonical)
    assert adapted == [{"low": 184.5, "high": 185.1, "dir": "BULL", "valid": True}]


def test_adapt_sweeps_maps_side_values() -> None:
    canonical = [
        {"id": "sweep:1", "time": 1709250300, "price": 184.9, "side": "SELL_SIDE"},
        {"id": "sweep:2", "time": 1709250600, "price": 185.5, "side": "BUY_SIDE"},
    ]
    adapted = _adapt_sweeps(canonical)
    assert adapted[0]["side"] == "SELL"
    assert adapted[1]["side"] == "BUY"
    # must keep only time, price, side
    assert set(adapted[0].keys()) == {"time", "price", "side"}


def test_adapt_sweeps_passthrough_unknown_side() -> None:
    canonical = [{"time": 100, "price": 50.0, "side": "CUSTOM"}]
    adapted = _adapt_sweeps(canonical)
    assert adapted[0]["side"] == "CUSTOM"


# ── _detect_structure_canonical ──────────────────────────

def test_detect_structure_canonical_empty_candles() -> None:
    result = _detect_structure_canonical([], "AAPL", "15m")
    assert result == {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}


def test_detect_structure_canonical_delegates_to_producer() -> None:
    """Monkeypatch build_full_structure_from_bars to verify delegation."""
    fake_structure = {
        "bos": [{"id": "bos:1", "time": 100, "price": 50.0, "kind": "BOS", "dir": "UP"}],
        "orderblocks": [{"id": "ob:1", "low": 48.0, "high": 50.0, "dir": "BULL", "valid": True, "anchor_ts": 100}],
        "fvg": [{"id": "fvg:1", "low": 49.0, "high": 51.0, "dir": "BEAR", "valid": True, "anchor_ts": 100}],
        "liquidity_sweeps": [{"id": "sw:1", "time": 200, "price": 47.0, "side": "SELL_SIDE"}],
    }

    candles = [
        {"timestamp": 100 + i * 60, "open": 50 + i, "high": 52 + i, "low": 49 + i, "close": 51 + i, "volume": 1000}
        for i in range(20)
    ]

    # Deferred import inside _detect_structure_canonical → patch on the source module
    with patch("scripts.explicit_structure_from_bars.build_full_structure_from_bars", return_value=fake_structure):
        result = _detect_structure_canonical(candles, "AAPL", "15m")

    # BOS adapted: stripped id/kind
    assert result["bos"] == [{"time": 100, "price": 50.0, "dir": "UP"}]
    # OB adapted: stripped id/anchor_ts
    assert result["orderblocks"] == [{"low": 48.0, "high": 50.0, "dir": "BULL", "valid": True}]
    # FVG adapted: stripped id/anchor_ts
    assert result["fvg"] == [{"low": 49.0, "high": 51.0, "dir": "BEAR", "valid": True}]
    # Sweeps: SELL_SIDE → SELL
    assert result["liquidity_sweeps"] == [{"time": 200, "price": 47.0, "side": "SELL"}]


# ── response contract stability ──────────────────────────

_SNAPSHOT_REQUIRED_KEYS = {
    "symbol", "timeframe", "bos", "orderblocks", "fvg",
    "liquidity_sweeps", "regime", "technicalscore", "newsscore",
}

_TV_REQUIRED_KEYS = {"bos", "ob", "fvg", "sweeps", "regime", "tech", "news"}


def test_mock_snapshot_preserves_contract() -> None:
    snap = _mock_snapshot("AAPL", "15m")
    assert_keys_subset(_SNAPSHOT_REQUIRED_KEYS, snap, "mock snapshot")


def test_mock_snapshot_encodes_to_tv_shape() -> None:
    snap = _mock_snapshot("AAPL", "15m")
    tv = {
        "bos": encode_levels(snap["bos"]),
        "ob": encode_zones(snap["orderblocks"]),
        "fvg": encode_zones(snap["fvg"]),
        "sweeps": encode_sweeps(snap["liquidity_sweeps"]),
        "regime": snap["regime"]["volume_regime"],
        "tech": snap["technicalscore"],
        "news": snap["newsscore"],
    }
    assert_keys_subset(_TV_REQUIRED_KEYS, tv, "TV payload")
    assert "|" in tv["bos"]
    assert "|" in tv["ob"]


def test_adapted_structure_encodes_to_tv_shape() -> None:
    """Canonical-adapted structure can be encoded for /smc_tv."""
    adapted = {
        "bos": [{"time": 1709250000, "price": 185.25, "dir": "UP"}],
        "orderblocks": [{"low": 184.5, "high": 185.1, "dir": "BULL", "valid": True}],
        "fvg": [{"low": 186.0, "high": 186.5, "dir": "BEAR", "valid": True}],
        "liquidity_sweeps": [{"time": 1709250300, "price": 184.9, "side": "SELL"}],
    }
    bos_str = encode_levels(adapted["bos"])
    assert bos_str == "1709250000|185.25|UP"

    ob_str = encode_zones(adapted["orderblocks"])
    assert ob_str == "184.5|185.1|BULL|1"

    fvg_str = encode_zones(adapted["fvg"])
    assert fvg_str == "186.0|186.5|BEAR|1"

    sw_str = encode_sweeps(adapted["liquidity_sweeps"])
    assert sw_str == "1709250300|184.9|SELL"


# ── empty results ────────────────────────────────────────

def test_encode_levels_empty() -> None:
    assert encode_levels([]) == ""


def test_encode_zones_empty() -> None:
    assert encode_zones([]) == ""


def test_encode_sweeps_empty() -> None:
    assert encode_sweeps([]) == ""
