from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import smc_integration.batch as batch


def _bundle(symbol: str, timeframe: str) -> dict:
    return {
        "source": {"name": "databento_watchlist_csv", "path_hint": "reports/databento_watchlist_top5_pre1530.csv", "capabilities": {}, "notes": []},
        "snapshot": {
            "symbol": symbol,
            "timeframe": timeframe,
            "structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
            "meta": {"symbol": symbol, "timeframe": timeframe},
        },
        "dashboard_payload": {"symbol": symbol, "timeframe": timeframe},
        "pine_payload": {"symbol": symbol, "timeframe": timeframe},
    }


def test_build_snapshot_bundles_for_symbols_keeps_deterministic_order(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake(symbol: str, timeframe: str, *, source: str = "auto", generated_at: float | None = None) -> dict:
        del source, generated_at
        return _bundle(symbol, timeframe)

    monkeypatch.setattr(batch, "build_snapshot_bundle_for_symbol_timeframe", _fake)

    out = batch.build_snapshot_bundles_for_symbols(["nvda", "aapl", "msft"], "15m")
    assert [row["snapshot"]["symbol"] for row in out] == ["NVDA", "AAPL", "MSFT"]


def test_build_snapshot_bundles_for_symbols_deduplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _fake(symbol: str, timeframe: str, *, source: str = "auto", generated_at: float | None = None) -> dict:
        del source, generated_at
        calls.append(symbol)
        return _bundle(symbol, timeframe)

    monkeypatch.setattr(batch, "build_snapshot_bundle_for_symbol_timeframe", _fake)

    out = batch.build_snapshot_bundles_for_symbols(["AAPL", "aapl", "MSFT", "MSFT"], "15m")
    assert [row["snapshot"]["symbol"] for row in out] == ["AAPL", "MSFT"]
    assert calls == ["AAPL", "MSFT"]


def test_build_snapshot_bundles_for_symbols_is_deterministic_with_fixed_generated_at(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake(symbol: str, timeframe: str, *, source: str = "auto", generated_at: float | None = None) -> dict:
        payload = _bundle(symbol, timeframe)
        payload["snapshot"]["generated_at"] = generated_at
        return payload

    monkeypatch.setattr(batch, "build_snapshot_bundle_for_symbol_timeframe", _fake)

    one = batch.build_snapshot_bundles_for_symbols(["AAPL", "MSFT"], "15m", generated_at=1709254000.0)
    two = batch.build_snapshot_bundles_for_symbols(["AAPL", "MSFT"], "15m", generated_at=1709254000.0)
    assert one == two


def test_build_snapshot_bundles_for_symbols_bundle_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batch, "build_snapshot_bundle_for_symbol_timeframe", lambda symbol, timeframe, **kwargs: _bundle(symbol, timeframe))
    out = batch.build_snapshot_bundles_for_symbols(["AAPL"], "15m")
    assert set(["source", "snapshot", "dashboard_payload", "pine_payload"]).issubset(set(out[0].keys()))


def test_write_snapshot_bundles_for_symbols_surfaces_failures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def _fake(symbol: str, timeframe: str, *, source: str = "auto", generated_at: float | None = None) -> dict:
        del source, generated_at
        if symbol == "BAD":
            raise ValueError("bad symbol")
        return _bundle(symbol, timeframe)

    monkeypatch.setattr(batch, "build_snapshot_bundle_for_symbol_timeframe", _fake)

    manifest = batch.write_snapshot_bundles_for_symbols(["AAPL", "BAD"], "15m", output_dir=tmp_path, generated_at=1709254000.0)
    assert manifest["counts"]["symbols_requested"] == 2
    assert manifest["counts"]["symbols_built"] == 1
    assert manifest["counts"]["errors"] == 1
    assert manifest["errors"][0]["symbol"] == "BAD"


def test_load_symbols_from_json_watchlist_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_path = tmp_path / "fmp_watchlist_snapshot.json"
    source_path.write_text(
        json.dumps(
            {
                "symbols": [
                    {"symbol": "AAPL"},
                    {"symbol": "msft"},
                    {"symbol": "AAPL"},
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(batch, "_descriptor_for_source_name", lambda name: SimpleNamespace(path_hint=str(source_path)))

    symbols = batch.load_symbols_from_watchlist_source(source="fmp_watchlist_json")
    assert symbols == ["AAPL", "MSFT"]
