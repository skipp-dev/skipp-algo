from __future__ import annotations

import pytest

from smc_adapters.ingest import build_meta_from_raw, build_snapshot_from_raw, build_structure_from_raw
from smc_core.types import SmcSnapshot


RAW_STRUCTURE = {
    "bos": [
        {"id": "bos:AAPL:15m:1709250000:BOS:UP:185.25", "time": 1709250000, "price": 185.25, "kind": "BOS", "dir": "UP"}
    ],
    "orderblocks": [
        {"id": "ob:AAPL:15m:1709250000:BULL:184.50:185.10", "low": 184.5, "high": 185.1, "dir": "BULL", "valid": True}
    ],
    "fvg": [
        {"id": "fvg:AAPL:15m:1709250000:BULL:186.00:186.50", "low": 186.0, "high": 186.5, "dir": "BULL", "valid": True}
    ],
    "liquidity_sweeps": [
        {"id": "sweep:AAPL:15m:1709250300:SELL_SIDE:184.90", "time": 1709250300, "price": 184.9, "side": "SELL_SIDE"}
    ],
}

RAW_META = {
    "symbol": "aapl ",
    "timeframe": "15m ",
    "asof_ts": 1709253580,
    "volume": {
        "value": {"regime": "NORMAL", "thin_fraction": 0.1},
        "asof_ts": 1709253580,
        "stale": False,
    },
    "technical": {
        "value": {"strength": 0.8, "bias": "BULLISH"},
        "asof_ts": 1709253550,
        "stale": False,
    },
    "news": {
        "value": {"strength": 0.4, "bias": "BEARISH"},
        "asof_ts": 1709253500,
        "stale": False,
    },
    "provenance": ["TEST"],
}


def test_build_structure_from_raw_builds_domain_objects() -> None:
    structure = build_structure_from_raw(RAW_STRUCTURE)
    assert len(structure.bos) == 1
    assert len(structure.orderblocks) == 1
    assert len(structure.fvg) == 1
    assert len(structure.liquidity_sweeps) == 1
    assert structure.orderblocks[0].dir == "BULL"


def test_build_meta_from_raw_builds_smcmeta() -> None:
    meta = build_meta_from_raw(RAW_META)
    assert meta.symbol == "AAPL"
    assert meta.timeframe == "15m"
    assert meta.volume.value.regime == "NORMAL"
    assert meta.technical is not None
    assert meta.technical.value.bias == "BULLISH"


def test_build_snapshot_from_raw_returns_smcsnapshot() -> None:
    snapshot = build_snapshot_from_raw(RAW_STRUCTURE, RAW_META, generated_at=1709254000.0)
    assert isinstance(snapshot, SmcSnapshot)
    assert snapshot.symbol == "AAPL"
    assert snapshot.generated_at == 1709254000.0


def test_missing_required_fields_raise_value_error() -> None:
    raw = dict(RAW_STRUCTURE)
    raw["orderblocks"] = [{"low": 184.5, "high": 185.1, "dir": "BULL", "valid": True}]
    with pytest.raises(ValueError):
        build_structure_from_raw(raw)


def test_invalid_enum_values_raise_value_error() -> None:
    bad_meta = dict(RAW_META)
    bad_meta["volume"] = {
        "value": {"regime": "BROKEN", "thin_fraction": 0.1},
        "asof_ts": 1709253580,
        "stale": False,
    }
    with pytest.raises(ValueError):
        build_meta_from_raw(bad_meta)


def test_symbol_is_normalized() -> None:
    meta = build_meta_from_raw(RAW_META)
    assert meta.symbol == "AAPL"
